"""Continue two archived A10 waits in an explicitly authorized financial phase.

No original task or historic macro export is rewritten. Initial facts are
scenario declarations; actual execution/credit comes only from the native
ScenarioPaymentLedger. Original A06/A10 processors and payment protocols remain
strict. This module contains no model client and performs no network requests.
"""
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from integration.bootstrap import enable_gba_imports
from integration.contractor_payment_actions import ContractorPaymentActionAssembler
from integration.contractor_payment_results import ContractorPaymentResultWorker
from integration.owner_payment_actions import OwnerPaymentActionAssembler
from integration.owner_payment_execution_reader import OwnerPaymentExecutionReader
from integration.owner_contractor_payment_handoff import read_received_contractor_payments
from integration.owner_payment_results import OwnerPaymentResultWorker
from integration.owner_payment_submission import OwnerPaymentSubmission
from integration.owner_submission import OwnerSubmissionCallbacks
from integration.owner_submission_host import OwnerSubmissionHost
from integration.verify_goal3_minimal_native_fix import macro_snapshot
from src.actions.contracts.common import ActionContext
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, task_digest
from src.organization.registry import OrganizationRegistry

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'case0005-supplemental-payment.v1'


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ref(kind, name, version='1'):
    return {'kind': kind, 'id': 'case0005-payment:' + name, 'version': str(version)}


def rk(reference):
    return reference['kind'], reference['id'], reference['version']


def implementation_snapshot():
    paths=['integration/case0005_payment_continuation.py','config/case0005_payment_continuation.json',
        'integration/owner_payment_actions.py','integration/owner_payment_results.py',
        'integration/owner_submission.py','integration/owner_submission_host.py','integration/owner_payment_submission.py',
        'integration/owner_payment_settlement.py','integration/owner_payment_execution_reader.py',
        'integration/owner_contractor_payment_handoff.py','integration/contractor_payment_actions.py',
        'integration/contractor_payment_results.py','src/actions/roles/owner_payment.py',
        'src/actions/roles/contractor_payment.py','src/coordination/tasks.py','src/coordination/invocations.py']
    return {p:file_sha(ROOT/p) for p in paths}


class PaymentPhase:
    def __init__(self, config, directory):
        enable_gba_imports()
        from gba_construction_sim.backend.simulation.scenario_payment_ledger import ScenarioPaymentLedger
        self.config, self.directory = config, Path(directory)
        self.source = ROOT / config['source_directory']
        self.readiness = read(ROOT / config['readiness'])
        self.verify_parent()
        self.run_id = self.readiness['original_waits'][0]['identity']['run_id']
        self.native_project = read(self.source/'runtime/native-run-state.json')['simulation']['project_results'][0]
        if (self.native_project['project_id'] != config['project_id']
                or self.native_project['selected_contractor_id'] != config['contractor_id']
                or self.native_project['owner_id'] != config['owner_id']):
            raise TaskConflict('Supplemental payment parties differ from the archived signed contract')
        old = sqlite3.connect((self.source/'runtime/tasks.sqlite').resolve().as_uri()+'?mode=ro', uri=True)
        try:
            self.originals = []
            for link in self.readiness['delay_feedback']:
                task = json.loads(old.execute('SELECT record FROM tasks WHERE key=?',
                    (link['micro_task_key'],)).fetchone()[0])
                snapshot = json.loads(old.execute('SELECT record FROM invocation_snapshots WHERE task_key=?',
                    (link['micro_task_key'],)).fetchone()[0])
                result = json.loads(old.execute('SELECT record FROM contractor_payment_results WHERE task_key=?',
                    (link['micro_task_key'],)).fetchone()[0])
                if (task['state']!='waiting_input' or task['output'] is not None
                        or result['result']['kind']!='needs_information'
                        or result['result_sha256']!=link['result_sha256']
                        or result['source_reading_sha256']!=link['source_reading_sha256']
                        or TaskIdentity(**task['identity']).key!=link['micro_task_key']):
                    raise TaskConflict('Selected predecessor is not its authentic archived A10 wait')
                self.originals.append({'link': link, 'snapshot': snapshot, 'result': result})
        finally:
            old.close()
        self.clock = deepcopy(self.originals[0]['snapshot']['context']['business_time']['clock_ref'])
        events={event['event_id']:event for event in self.native_project['event_log']}
        for original in self.originals:
            link=original['link']
            if task_digest(events[link['delay_event_id']])!=link['source_event_sha256']:
                raise TaskConflict('Selected wait does not match the original native delay event')
        self.scope = deepcopy(self.originals[0]['snapshot']['context']['scope'])
        self.basis = ref('Evidence', 'explicit-opening-assumptions')
        self.contract_ref = ref('Contract', 'supplemental-two-request-agreement')
        self.account_refs = {config['owner_id']: ref('Account', 'owner'), config['contractor_id']: ref('Account', 'contractor')}
        self.source_refs = {p: ref('FundingSource', 'owner' if p == config['owner_id'] else 'contractor') for p in self.account_refs}
        self.obligations = [ref('Obligation', event) for event in config['request_event_ids']]
        self.components = [ref('SettlementComponent', event) for event in config['request_event_ids']]
        self.initial = {'schema_version': VERSION, 'run_id': self.run_id,
            'project_id': config['project_id'], 'source_declaration': config['source_declaration'],
            'parent_journal_sha256': config['source_journal_sha256'], 'start_tick': config['start_tick'],
            'currency': config['currency'], 'payment_basis': config['payment_basis'], 'history_coverage': config['history_coverage'],
            'accounts': [{'ref': self.account_refs[party], 'organization_id': party, 'cash': config[field]}
                for party, field in ((config['owner_id'], 'owner_initial_cash'), (config['contractor_id'], 'contractor_initial_cash'))],
            'obligations': [{'ref': obligation, 'component_ref': component, 'amount': config['per_request_amount'],
                'debtor_id': config['owner_id'], 'payee_id': config['contractor_id'],
                'original_request_event_id': event, 'original_wait_task_key': original['link']['micro_task_key'],
                'original_delay_event_sha256': original['link']['source_event_sha256']}
                for obligation, component, event, original in zip(self.obligations, self.components,
                    config['request_event_ids'], self.originals)]}
        if (config['allowed_new_api_attempts'] != 0 or config['opening_paid_for_selected_obligations'] != '0'
                or len(self.initial['obligations']) != 2
                or any(Decimal(o['amount']) != Decimal(str(p['link']['payment_amount']))
                    for o,p in zip(self.initial['obligations'],self.originals))):
            raise TaskConflict('Unsupported financial phase configuration or changed archived request amount')
        self.directory.mkdir(parents=True, exist_ok=False)
        write(self.directory/'input/config.json', config)
        write(self.directory/'input/initial-financial-assumptions.json', self.initial)
        write(self.directory/'input/parent-links.json', self.originals)
        write(self.directory/'macro-before-run.json', macro_snapshot())
        write(self.directory/'implementation-before-run.json',implementation_snapshot())
        self.ledger = ScenarioPaymentLedger(self.directory/'native-payments.sqlite', initial=self.initial)
        self.registry = register_representative_processors(ActionRegistry())
        self.store = TaskStore(run_id=self.run_id, organization_ids=list(self.account_refs), path=self.directory/'tasks.sqlite')
        self.snapshots = InvocationSnapshotStore(self.store)
        self.invocations = {}
        self.owner_prepared = None
        self.organizations = self.build_organizations()
        worker_args = dict(store=self.store, snapshots=self.snapshots, registry=self.registry,
            client_version=VERSION, model_version='rules-no-model', validate_invocation=self.validate_invocation,
            validate_wait=self.validate_wait)
        self.owner_worker = OwnerPaymentResultWorker(**worker_args)
        self.contractor_worker = ContractorPaymentResultWorker(**worker_args)
        self.owner_assembler = OwnerPaymentActionAssembler(registry=self.registry, organizations=self.organizations,
            provider=self, macro_version=VERSION, source_mode='formal')
        self.contractor_assembler = ContractorPaymentActionAssembler(registry=self.registry, organizations=self.organizations,
            provider=self, macro_version=VERSION, source_mode='formal')

    def verify_parent(self):
        if file_sha(self.source/'runtime/tasks.sqlite') != self.config['source_journal_sha256']:
            raise TaskConflict('Frozen parent journal changed')
        manifest = read(self.source/'artifact-manifest.json')
        for path, expected in manifest['files'].items():
            if file_sha(self.source/path) != expected['sha256']:
                raise TaskConflict('Frozen parent artifact changed: '+path)
        return len(manifest['files'])

    def point(self, tick):
        return {'clock_ref': self.clock, 'offset': tick}

    def window(self):
        return {'start': self.point(49), 'end': self.point(56), 'bounds': 'closed_open'}

    def money(self, value):
        return {'value': str(value), 'currency': self.config['currency'], 'basis_ref': self.basis}

    def known_money(self, value):
        return {'state': 'known', 'value': self.money(value)}

    def common(self, tick=49, evidence=None):
        return {'scope': self.scope, 'available_at': self.point(tick), 'effective_window': self.window(),
            'evidence_refs': [self.basis] if evidence is None else evidence}

    def assumed(self):
        return {'ref': self.basis, 'source_kind': 'synthetic', 'basis_kind': 'assumed',
            'locator': str(self.directory/'input/initial-financial-assumptions.json'),
            'content_hash': task_digest(self.initial), 'effective_window': self.window()}

    def observed(self, reference, payload, locator):
        # real_user here denotes a locally observed authorized execution record,
        # never public real-project financial data. The payload declares local simulation.
        return {'ref': reference, 'source_kind': 'real_user', 'basis_kind': 'observed',
            'locator': str(self.directory/'native-payments.sqlite')+'#'+locator,
            'content_hash': task_digest(payload), 'effective_window': self.window()}

    def build_organizations(self):
        from src.organization.models import Organization
        organizations = OrganizationRegistry(self.run_id)
        self.grants = {}
        for party, role, action in ((self.config['owner_id'], 'Owner', 'OWN-A06'),
                (self.config['contractor_id'], 'Contractor', 'CONTRACTOR-A10')):
            function = {'role': role, 'function_ref': ref('FunctionAssignment', role),
                'configuration_version': '1', 'basis_refs': [self.basis]}
            organizations.register(Organization.model_validate({'organization_id': party, 'actor_id': party,
                'source_ids': ['scenario:case0005-payment:'+party], 'public_description': 'Authorized supplemental payment scenario only.',
                'public_location': {'state':'known','value':'Macau'}, 'members': [], 'assignments': [function],
                'evidence_refs': [self.basis]}))
            self.grants[role] = {'ref': ref('Authorization', role), 'organization_id': party, 'actor_id': party,
                'function_ref': function['function_ref'], 'action_ids': [action], 'scopes': [self.scope],
                'readable_refs': [], 'tool_ids': [], 'validity': self.window(), 'basis_refs': [self.basis]}
        self.organization_registry = organizations
        return organizations

    def seal(self, role, tick, name, rows, action_input):
        from src.organization.models import Authorization
        party = self.config['owner_id' if role == 'Owner' else 'contractor_id']
        action = 'OWN-A06' if role == 'Owner' else 'CONTRACTOR-A10'
        grant = deepcopy(self.grants[role])
        function = self.organizations.get(party).assignments[0].model_dump(mode='json')
        candidate_ref = ref('CandidateSet', name)
        operation = 'supplemental:'+name
        candidates = [{'ref': row, 'permitted_choices': ['pay' if role == 'Owner' else 'reconcile']}
            for row in (self.obligations if role == 'Owner' else action_input['execution_refs'])]
        rows = deepcopy(rows) + [{'ref': function['function_ref'], 'value': function},
            {'ref': candidate_ref, 'value': {'operation_id': operation, 'scope': self.scope, 'as_of': self.point(tick),
                'candidates': candidates, 'search_profile_ref': ref('Profile', 'payment-phase')}}]
        refs = [r['ref'] for r in rows] + [grant['ref']]
        grant['readable_refs'] = refs
        # Each invocation has a distinct authority reference; originals never change.
        grant['ref'] = ref('Authorization', name)
        refs[-1] = grant['ref']
        grant['readable_refs'] = deepcopy(refs)
        for row in rows:
            if row['ref']['kind'] in {'PaymentAuthorization','SettlementRule'}:
                row['value']['authority_ref'] = grant['ref']
        rows.append({'ref': grant['ref'], 'value': grant})
        self.organizations.authorize(Authorization.model_validate(grant))
        context = {'run_id': self.run_id, 'actor_id': party, 'function_ref': function['function_ref'],
            'authorization_refs': [grant['ref']], 'operation_id': operation,
            'contract_ref': {'kind':'ActionContract','id':action,'version':'1'}, 'task_ref': ref('DecisionTask',name),
            'scope': self.scope, 'business_time': self.point(tick), 'read_token': operation+':read',
            'visible_refs': refs, 'candidate_set_ref': candidate_ref, 'execution_mode': 'rule'}
        entry = {'context': context, 'action_input': deepcopy(action_input), 'objects': rows}
        self.invocations[operation] = entry
        write(self.directory/'inputs'/ (name+'.json'), entry)
        return entry

    def project(self, *, context, organization_id, grants):
        row = self.invocations[context.operation_id]
        if row['context'] != context.model_dump(mode='json') or organization_id != context.actor_id:
            raise TaskConflict('Projection changes the frozen authorized invocation')
        return {'run_id': self.run_id, 'macro_version': VERSION, 'state_version': task_digest(row),
            'read_token': context.read_token, 'business_time': context.business_time.model_dump(mode='json'),
            'organization_id': organization_id, 'objects': deepcopy(row['objects'])}

    def validate_invocation(self, task, prepared):
        row = self.invocations[prepared.context.operation_id]
        return (task['identity']['input_sha256'] == task_digest(row['action_input'])
            and prepared.context.model_dump(mode='json') == row['context']
            and self.verify_parent() == self.readiness['source_artifact_files_verified'])

    def validate_wait(self, *args):
        # Preserve any genuine gap; never manufacture ready/complete results.
        return True

    @contextmanager
    def read_guard(self, identity):
        self.verify_parent()
        yield
        self.verify_parent()

    def initial_owner(self):
        owner, contractor = self.config['owner_id'], self.config['contractor_id']
        account_ref, source_ref = self.account_refs[owner], self.source_refs[owner]
        common = self.common()
        def row(reference, **fields):
            base = {'evidence_refs':[self.basis]} if reference['kind'] in {'Account','Obligation'} else common
            return {'ref': reference, 'value': {'ref':reference, **base, **fields}}
        rows = [{'ref':self.basis, 'value':self.assumed()}]
        rows.extend({'ref':r['ref'],'value':r['projection']} for r in self.originals[0]['result']['source_reading']
            if r['ref']['kind']=='WorkScope')
        rows.append(row(self.scope['ref'], organization_id=owner, payment_authorization_ref=ref('PaymentAuthorization','pay-two-requests')))
        rows.append(row(account_ref, organization_id=owner, source_ref=source_ref, currency=self.config['currency'],
            region_id='Macau', actual_cash=self.known_money(self.config['owner_initial_cash']),
            restricted_cash=self.known_money('0'), reserved_cash=self.known_money('0'), debt_refs=[],
            obligation_refs=self.obligations, as_of=self.point(49), coverage='complete',
            pending_execution_refs=[], execution_coverage='complete', reservation_refs=[]))
        rows.append(row(source_ref, organization_id=owner, account_ref=account_ref,
            actual_cash=self.known_money(self.config['owner_initial_cash']), restricted_cash=self.known_money('0'),
            as_of=self.point(49), coverage='complete'))
        for obligation,component in zip(self.obligations,self.components):
            rows.append(row(obligation, debtor_id=owner, payee_id=contractor, source_ref=source_ref,
                origin_scope=self.scope, debt_ref=None, component_refs=[component],
                actual_due=self.known_money(self.config['per_request_amount']), actual_paid=self.known_money('0'),
                actual_offset=self.known_money('0'), payable={'state':'known','value':True},
                due_at=self.point(49), as_of=self.point(49), status='effective', kind='works', verification_evidence_refs=[self.basis]))
            rows.append(row(component, obligation_ref=obligation, debt_ref=None, debtor_id=owner, payee_id=contractor,
                source_ref=source_ref, as_of=self.point(49), category='works', settlement_mode='cash',
                actual_due=self.known_money(self.config['per_request_amount']), actual_cash_paid=self.known_money('0'), actual_offset=self.known_money('0')))
        lines = [{'obligation_ref':obligation,'payee_id':contractor,'amount':self.money(self.config['per_request_amount']),
            'component_amounts':[{'component_ref':component,'amount':self.money(self.config['per_request_amount'])}], 'priority':i}
            for i,(obligation,component) in enumerate(zip(self.obligations,self.components))]
        rows.append(row(ref('PaymentAuthorization','pay-two-requests'), organization_id=owner, actor_id=owner,
            function_ref=ref('FunctionAssignment','Owner'),authority_ref=ref('Authorization','Owner'), choice='pay',
            account_ref=account_ref, lines=lines, allow_partial=False, draw_authorization_ref=None,
            obligation_refs=self.obligations, execution_refs=[], note='Scenario authority to pay the two declared obligations; processor must check actual free cash and unpaid components.'))
        return self.seal('Owner',49,'owner-pay',rows,{'scope_ref':self.scope,'account_refs':[account_ref],
            'arrangement_refs':[],'due_refs':self.obligations,'evidence_refs':[self.basis],'pending_execution_refs':[]})

    def command(self, request):
        record = self.owner_worker.get_record(request.identity)
        snapshot = self.snapshots.get(request.identity)
        return {'command_id':request.identity.key, 'run_id':self.run_id, 'project_id':self.config['project_id'],
            'organization_id':request.identity.organization_id, 'phase_tick':49, 'source_task_sha256':request.identity.key,
            'plan':OwnerPaymentSubmission._payment_plan(record,snapshot)}

    def validate_submit(self, request, record, snapshot):
        self.owner_prepared.reading.recheck()
        return (self.verify_parent() == 280 and record == self.owner_worker.get_record(request.identity)
            and snapshot == self.snapshots.get(request.identity)
            and self.owner_prepared.context.model_dump(mode='json') == snapshot['context'])

    def submit(self, request):
        return self.ledger.submit(self.command(request))

    def query(self, request):
        return self.ledger.query(request.identity.key)

    def validate_query(self, request):
        context=ActionContext.model_validate(self.snapshots.get(request.identity)['context'])
        grants=self.organizations.grants(context,'OWN-A06','Owner')
        return (self.verify_parent() == 280 and request.identity.organization_id == self.config['owner_id']
            and grants[0].organization_id==request.identity.organization_id)

    def validate_receipt(self, request, raw):
        if raw != self.query(request):
            raise TaskConflict('Receipt differs from actual native ledger')
        return {**request.receipt_identity(), 'receipt_id':raw['command_id'], 'disposition':'accepted', 'original_receipt':raw}

    def execution_observation(self, *, request, record, snapshot, receipt, payment_plan):
        native = self.query(request)
        if native is None:
            return None
        evidence_ref = ref('Evidence','execution-'+request.identity.key)
        lines = []
        for transfer, planned in zip(native['transfers'],payment_plan['lines']):
            execution_ref = ref('PaymentExecution',transfer['execution_id'])
            receipt_ref = ref('PaymentReceipt',transfer['receipt_id'])
            common = self.common(evidence=[evidence_ref])
            execution = {'ref':execution_ref,**common,'organization_id':request.identity.organization_id,
                'command_id':transfer['execution_id'],'business_key':transfer['execution_id'],
                'authorization_ref':payment_plan['authorization_ref'],'operation':'pay','account_ref':payment_plan['account_ref'],
                'arrangement_ref':None,'obligation_refs':[planned['obligation_ref']],'component_refs':planned['component_refs'],
                'beneficiary_id':planned['payee_id'],'amount':planned['amount'],'status':native['status'],'receipt_ref':receipt_ref}
            issued = {'ref':receipt_ref,**common,'execution_ref':execution_ref,'command_id':transfer['execution_id'],
                'business_key':transfer['execution_id'],'amount':planned['amount'],'beneficiary_id':planned['payee_id'],'status':native['status']}
            lines.append({'line_index':transfer['line_index'],'execution':execution,'receipt':issued,'component_amounts':planned['component_amounts']})
        payload = {'schema_version':'owner-payment-native-execution.v1','receipt_identity':request.receipt_identity(),
            'original_receipt':receipt['original_receipt'],'source_identity':request.identity.as_dict(),
            'source_record_sha256':record['record_sha256'],'source_reading_sha256':record['source_reading_sha256'],
            'payment_plan':payment_plan,'lines':lines,'coverage':'complete'}
        return {'schema_version':'owner-payment-execution-observation.v1','lines':lines,'coverage':'complete',
            'native_payload':payload,'native_evidence':self.observed(evidence_ref,payload,'commands/'+request.identity.key)}

    def settlement_observation(self, *, request, record, snapshot, reception):
        native = self.query(request)
        evidence_ref = ref('Evidence','settlement-'+request.identity.key)
        originals = {rk(row['ref']):row['projection'] for row in record['source_reading']}
        before = [deepcopy(row) for row in originals.values() if row.get('ref',{}).get('kind') in {'Account','FundingSource','Obligation','SettlementComponent'}]
        replacements = {rk(row['ref']): {**row['ref'],'version':'2'} for row in before}
        def replace(value):
            if isinstance(value,list): return [replace(v) for v in value]
            if isinstance(value,dict):
                if set(value)=={'kind','id','version'}:return replacements.get(rk(value),value)
                return {k:replace(v) for k,v in value.items()}
            return value
        after = [replace(row) for row in before]
        effects = {}
        postings = []
        for issued in reception['observation']['lines']:
            execution, receipt = issued['execution'], issued['receipt']
            amount = Decimal(execution['amount']['value'])
            targets = [(reception['payment_plan']['account_ref'],'actual_cash',-amount),
                (self.source_refs[self.config['owner_id']],'actual_cash',-amount),
                (execution['obligation_refs'][0],'actual_paid',amount),
                (execution['component_refs'][0],'actual_cash_paid',amount)]
            if native['status'] != 'succeeded':continue
            for target,field,delta in targets:
                effects[(rk(target),field)] = effects.get((rk(target),field),Decimal(0))+delta
                postings.append({'effect_id':execution['command_id']+':'+field+':'+target['kind'],
                    'source_task_sha256':request.identity.key,'command_id':execution['command_id'],
                    'business_key':execution['business_key'],'receipt_ref':receipt['ref'], 'target_ref':target,
                    'field':field,'delta':self.money(delta)})
        for old,new in zip(before,after):
            new['as_of'] = self.point(49)
            new['evidence_refs'] = [self.basis,evidence_ref]
            for (target,field),delta in effects.items():
                if target == rk(old['ref']):
                    new[field] = self.known_money(Decimal(old[field]['value']['value'])+delta)
        balances = [{'before':old,'after':new} for old,new in zip(before,after)]
        payload = {'schema_version':'owner-payment-native-settlement.v1','issued_reception_sha256':task_digest(reception),
            'source_identity':request.identity.as_dict(),'source_record_sha256':record['record_sha256'],
            'source_reading_sha256':record['source_reading_sha256'],'interval_start':self.point(49),
            'observed_at':self.point(49),'balances':balances,'postings':postings,'coverage':'complete'}
        return {'schema_version':'owner-payment-native-settlement-observation.v1','observed_at':self.point(49),
            'coverage':'complete','balances':balances,'postings':postings,'native_payload':payload,
            'native_evidence':self.observed(evidence_ref,payload,'settlement/'+request.identity.key)}

    def validate_settlement(self, *, request, record, snapshot, reception, observation):
        expected = self.settlement_observation(request=request,record=record,snapshot=snapshot,reception=reception)
        native = self.query(request)
        cash = native['after']
        if observation != expected or self.ledger.balances() != cash:
            return False
        owner, contractor = self.config['owner_id'], self.config['contractor_id']
        successful = native['transfers'] if native['status']=='succeeded' else []
        total = sum((Decimal(t['amount']) for t in successful),Decimal(0))
        # Compare both sides to actual backend balances, independently of the
        # projected posting sum. A payer debit alone does not prove receipt.
        if (Decimal(native['before'][owner])-Decimal(cash[owner]) != total
                or Decimal(cash[contractor])-Decimal(native['before'][contractor]) != total):
            return False
        for pair in observation['balances']:
            after, before = pair['after'], pair['before']
            kind = before['ref']['kind']
            if kind in {'Account','FundingSource'}:
                if Decimal(after['actual_cash']['value']['value']) != Decimal(cash[owner]):
                    return False
            else:
                field='actual_paid' if kind=='Obligation' else 'actual_cash_paid'
                ident= rk(before['ref'])[:2] if kind=='Obligation' else rk(before['obligation_ref'])[:2]
                amount=sum((Decimal(t['amount']) for t in successful if tuple(t['obligation_identity'])==ident),Decimal(0))
                if Decimal(after[field]['value']['value'])-Decimal(before[field]['value']['value']) != amount:
                    return False
        return True

    def owner_history(self, tick):
        original = self.invocations['supplemental:owner-pay']
        row = deepcopy(original)
        context = row['context']
        candidate_ref = ref('CandidateSet','owner-history-'+str(tick))
        context.update(operation_id='supplemental:owner-history-'+str(tick), business_time=self.point(tick),
            read_token='owner-history:'+str(tick), task_ref=ref('DecisionTask','owner-history-'+str(tick)),candidate_set_ref=candidate_ref)
        candidate = deepcopy(next(r for r in row['objects'] if r['ref']==original['context']['candidate_set_ref']))
        candidate.update(ref=candidate_ref)
        candidate['value'].update(operation_id=context['operation_id'],as_of=self.point(tick))
        # A fresh current read grant grants historical access; original source
        # grant/projections stay byte-for-byte unchanged in this read view.
        grant = deepcopy(next(r['value'] for r in row['objects'] if r['ref']==original['context']['authorization_refs'][0]))
        grant['ref'] = ref('Authorization','owner-history-'+str(tick))
        context['authorization_refs'] = [grant['ref']]
        row['objects'].extend([candidate,{'ref':grant['ref'],'value':grant}])
        context['visible_refs'] = [r['ref'] for r in row['objects']]
        grant['readable_refs'] = deepcopy(context['visible_refs'])
        from src.organization.models import Authorization
        self.organizations.authorize(Authorization.model_validate(grant))
        self.invocations[context['operation_id']] = row
        write(self.directory/'inputs'/ ('owner-history-'+str(tick)+'.json'),row)
        return row

    def contractor_input(self, tick, name, reception, index):
        owner, contractor = self.config['owner_id'], self.config['contractor_id']
        observation, ledger = reception['observation'], reception['settlement']['observation']
        execution_refs = [observation['lines'][index]['execution']['ref']]
        rule_ref, procedure_ref = ref('SettlementRule',name), ref('SettlementProcedure',name)
        common = self.common(tick)
        contract = {'ref':self.contract_ref,**common,'contractor_id':contractor,'client_id':owner,
            'currency':self.config['currency'],'effective':{'state':'known','value':True},'settlement_rule_ref':rule_ref,
            'measurement_application_refs':[],'measurement_history_complete':False,'certificate_refs':[],
            'obligation_refs':[],'execution_refs':execution_refs,'payment_history_complete':True,'as_of':self.point(tick)}
        # A fresh current contract projection, scoped to the supplemental ledger,
        # does not revise any archived independent disputed-obligation object.
        contract['ref'] = ref('Contract','supplemental-'+self.config['request_event_ids'][index],str(tick))
        rows = [{'ref':self.basis,'value':self.assumed()},
            {'ref':observation['native_evidence']['ref'],'value':observation['native_evidence']},
            {'ref':ledger['native_evidence']['ref'],'value':ledger['native_evidence']}]
        # Preserve v1 allocations as historical sources. Current cash and the
        # post-payment amounts are checked through the complete settlement;
        # never overwrite v1 or issue fresh claims from that opening snapshot.
        for pair in ledger['balances']:
            if pair['before']['ref']['kind'] not in {'Obligation','SettlementComponent'}:continue
            if pair['before']['ref'] not in (self.obligations[index],self.components[index]):continue
            current = deepcopy(pair['before'])
            # Historical original obligations are retained as historical facts.
            if current['ref']['kind']=='SettlementComponent':
                current.update(contract_ref=contract['ref'],certificate_ref=None,requestable={'state':'known','value':False})
            rows.append({'ref':current['ref'],'value':current})
        contract['obligation_refs']=[deepcopy(self.obligations[index])]
        rule = {'ref':rule_ref,**common,'contract_ref':contract['ref'],'organization_id':contractor,'actor_id':contractor,
            'function_ref':ref('FunctionAssignment','Contractor'),'authority_ref':ref('Authorization','Contractor'),
            'procedure_ref':procedure_ref,'choice':'reconcile','business_key':'supplemental:'+name,
            'measurement':None,'component_refs':[],'account_ref':None,'lines':[],'allow_partial':False,'financing':None,
            'execution_refs':execution_refs,'obligation_refs':[self.obligations[index]],'issue_refs':[],
            'basis_refs':[observation['native_evidence']['ref'],ledger['native_evidence']['ref']],
            'note':'Reconcile actual commands and receipts in the two-request supplemental ledger; do not request the paid amount again.'}
        procedure={'ref':procedure_ref,**common,'contract_ref':contract['ref'],'permitted_choices':['reconcile'],
            'permitted':{'state':'known','value':True},'recipient_ids':[owner],'valuation_basis_refs':[]}
        rows.extend({'ref':v['ref'],'value':v} for v in [contract,rule,procedure])
        for issued in [observation['lines'][index]]:
            rows.extend({'ref':v['ref'],'value':v} for v in [issued['execution'],issued['receipt']])
        # Own cash is queried from the native beneficiary account; never borrowed
        # from the payer's cash projection or inferred from a registration reply.
        account = {'ref':{**self.account_refs[contractor],'version':str(tick)},'evidence_refs':[self.basis,ledger['native_evidence']['ref']],'organization_id':contractor,
            'source_ref':{**self.source_refs[contractor],'version':str(tick)},'currency':self.config['currency'],'region_id':'Macau',
            'actual_cash':self.known_money(self.ledger.balances()[contractor]),'restricted_cash':self.known_money('0'),
            'reserved_cash':self.known_money('0'),'debt_refs':[],'obligation_refs':[self.obligations[index]],'as_of':self.point(tick),
            'coverage':'complete','pending_execution_refs':[],'execution_coverage':'complete','reservation_refs':[]}
        rows.append({'ref':account['ref'],'value':account})
        action_input={'contract_ref':contract['ref'],'work_record_refs':[],'certificate_refs':[],
            'obligation_refs':[self.obligations[index]],'account_refs':[account['ref']], 'execution_refs':execution_refs,'settlement_rule_ref':rule_ref}
        return self.seal('Contractor',tick,name,rows,action_input)

    def validate_sharing(self, *, saved, context, shared_source_refs):
        return (context.actor_id==self.config['contractor_id'] and saved.identity==self.owner_identity
            and {rk(r.model_dump(mode='json')) for r in shared_source_refs} == {rk(r['ref']) for r in saved.source_reading})

    def validate_disclosure(self, *, reception, context, execution_refs):
        return (context.actor_id==self.config['contractor_id'] and reception.saved.identity==self.owner_identity
            and {r.id for r in execution_refs}<={r['execution']['ref']['id'] for r in reception.issued_reception['observation']['lines']})

    def validate_reception(self, *, reception, contract, executions, receipts, components, accounts, context):
        native=self.ledger.query(self.owner_identity.key)
        return (contract.client_id==self.config['owner_id'] and contract.contractor_id==self.config['contractor_id']
            and native['status']=='succeeded' and len(receipts)==1 and len(accounts)==1
            and Decimal(accounts[0].actual_cash.value.value)==Decimal(native['after'][self.config['contractor_id']])
            and all(e.status=='succeeded' and e.command_id==t['execution_id']
                and e.beneficiary_id==t['beneficiary_id'] and Decimal(e.amount.value)==Decimal(t['amount'])
                for e in executions for t in native['transfers'] if e.command_id==t['execution_id'])
            and reception.settlement is not None and self.verify_parent()==280)

    def run(self):
        owner=self.initial_owner()
        prepared=self.owner_assembler.build(owner['context'],**owner['action_input'])
        self.owner_prepared=prepared
        self.owner_identity=self.owner_worker.register(prepared,request_id=prepared.context.operation_id)
        self.owner_worker.execute(self.owner_identity,prepared)
        owner_record=self.owner_worker.get_record(self.owner_identity)
        write(self.directory/'owner-decision.json',owner_record)
        if owner_record['result']['kind']!='completed' or owner_record['result']['payload']['choice']!='pay':
            raise TaskConflict('Original Owner processor did not form a payable instruction')
        callbacks=OwnerSubmissionCallbacks(submit=self.submit,query=self.query,validate_submit=self.validate_submit,
            validate_query=self.validate_query,validate_receipt=self.validate_receipt)
        host=OwnerSubmissionHost(store=self.store,registry=self.registry,workers={'OWN-A06':self.owner_worker},
            callbacks={'OWN-A06':callbacks},read_guard=self.read_guard,
            configuration={'schema_version':'owner-submission-host-config.v1','host_id':VERSION,'version':'1',
                'routes':[{'action_id':'OWN-A06','binding_id':'case0005-native-payment','binding_version':'1',
                    'macro_version':VERSION,'supported_choices':['pay'],'native_payment_execution':True,'native_payment_settlement':True}]},
            read_native_payment_execution=self.execution_observation,read_native_payment_settlement=self.settlement_observation,
            validate_native_payment_settlement=self.validate_settlement)
        submission=host.routes['OWN-A06']
        self.submission=submission
        self.settlement_reconciler=host.payment_settlements['OWN-A06']
        submission.execute(self.owner_identity)
        issued=submission.query_execution(self.owner_identity)
        settlement=host.payment_settlements['OWN-A06'].query(self.owner_identity)
        if settlement is None: raise TaskConflict('Actual financial effects remain unconfirmed')
        write(self.directory/'issued-reception.json',issued)
        write(self.directory/'native-settlement.json',settlement)
        native_before=self.ledger.history()
        self.ledger.submit(self.command(submission._original(self.owner_identity)[0]))
        if self.ledger.history()!=native_before:raise TaskConflict('Duplicate command posted twice')
        links=[]
        for index,tick in enumerate((50,51)):
            name='contractor-successor-'+str(index+1)
            entry=self.contractor_input(tick,name,{**issued,'settlement':settlement},index)
            cp=self.contractor_assembler.build(entry['context'],**entry['action_input'])
            history=self.owner_history(tick)
            reader=OwnerPaymentExecutionReader(settings={'owner_request':{'schema_version':'role-contract-invocation.v1','context':history['context'],
                'action_input':owner['action_input'],'execution_path':self.registry.get('OWN-A06').strategy},
                'recipient_context':entry['context'],'identity':self.owner_identity.as_dict(),
                'source_record_sha256':owner_record['record_sha256'],'source_result_sha256':owner_record['result_sha256'],
                'source_reading_sha256':owner_record['source_reading_sha256'],
                'shared_source_refs':[r['ref'] for r in owner_record['source_reading']], 'sharing_authorized':True,
                'execution_refs':entry['action_input']['execution_refs']},worker=self.owner_worker,assembler=self.owner_assembler,
                submission_host=host,submission=submission,settlement_reconciler=host.payment_settlements['OWN-A06'],
                validate_sharing=self.validate_sharing,validate_disclosure=self.validate_disclosure)
            intake=read_received_contractor_payments(cp,source_task_sha256=self.owner_identity.key,
                execution_refs=entry['action_input']['execution_refs'],read_owner_payment=reader.read,validate_reception=self.validate_reception)
            identity=self.contractor_worker.register(cp,request_id=cp.context.operation_id)
            self.contractor_worker.execute(identity,cp)
            record=self.contractor_worker.get_record(identity)
            if record['result']['kind']!='completed':raise TaskConflict('Original A10 successor still requires information')
            link={'parent_journal_sha256':self.config['source_journal_sha256'],
                'original_wait_task_key':self.originals[index]['link']['micro_task_key'],
                'original_wait_conditions':self.readiness['original_waits'][index]['conditions'],
                'original_request_event_id':self.config['request_event_ids'][index],
                'current_identity':identity.as_dict(),'current_task_key':identity.key,'current_result':record['result'],
                'current_result_sha256':record['result_sha256'],'intake':intake,
                'native_command_id':self.owner_identity.key,'native_receipt_id':self.ledger.history()[0]['transfers'][index]['receipt_id'],
                'history_scope':self.config['history_coverage'],'link_kind':'external-archived-wait-to-current-authorized-invocation'}
            links.append(link)
            write(self.directory/(name+'.json'),{'link':link,'record':record})
        write(self.directory/'continuation-links.json',links)
        write(self.directory/'native-execution.json',self.ledger.history())
        self.verify_parent()
        write(self.directory/'macro-after-run.json',macro_snapshot())
        self.organizations.save(self.directory/'current-organization-snapshot.json')
        result={'schema_version':VERSION,'status':'two-scoped-payment-successors-completed','parent_simulation_id':'SIM81A59DAA',
            'phase':self.config['phase'],'payments':len(self.ledger.history()[0]['transfers']),
            'total_paid':str(sum(Decimal(t['amount']) for t in self.ledger.history()[0]['transfers'])),
            'currency':self.config['currency'],'balances':self.ledger.balances(),'duplicate_submission_no_extra_effect':True,
            'a10_successors':[{'task_key':l['current_task_key'],'tick':t,'choice':l['current_result']['payload']['choice']}
                for l,t in zip(links,(50,51))], 'parent_files_verified':self.verify_parent(),
            'parent_journal_unchanged':True,'new_api_attempts':0,
            'limitations':['Local simulated accounts; no external bank transfer.',
                'Opening amounts and payable basis are explicit scenario assumptions.',
                self.config['history_coverage'],
                'Old two needs_information results remain immutable; these are current linked successor judgments.']}
        write(self.directory/'result.json',result)
        return result

    def close(self):
        self.store.close()
        self.ledger.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='config/case0005_payment_continuation.json')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    phase=PaymentPhase(read(ROOT/args.config),ROOT/args.output)
    try:
        print(json.dumps(phase.run(),ensure_ascii=False,indent=2))
    finally:
        phase.close()
    seal_delivery(phase.directory)


def seal_delivery(directory):
    """Seal this new phase after its databases close; never reseal the parent."""
    directory=Path(directory)
    before=read(ROOT/'output/integration/case0005_payment_continuation_20261026_01/macro-before-authorized-change.json')
    after=macro_snapshot()
    old,new=before['python_sources'],after['python_sources']
    changes={'changed_existing':[p for p in old if new.get(p)!=old[p]],
        'added':[p for p in new if p not in old], 'removed':[p for p in old if p not in new],
        'existing_macro_files_unchanged':before['files']==after['files'],
        'authorization':'User approved the minimal CASE-0005 scenario payment subchain on 2026-10-26.',
        'scope':'Additive opt-in local payment backend; no import or alteration of the original 48-tick engine.'}
    expected='gba_construction_sim/backend/simulation/scenario_payment_ledger.py'
    if changes['changed_existing'] or changes['removed'] or changes['added']!=[expected]:
        raise TaskConflict('Macro changes exceed the approved single-module payment backend')
    if read(directory/'macro-before-run.json')!=read(directory/'macro-after-run.json'):
        raise TaskConflict('Macro source changed during this payment phase')
    after_implementation=implementation_snapshot()
    if read(directory/'implementation-before-run.json')!=after_implementation:
        raise TaskConflict('Payment chain implementation changed during execution')
    write(directory/'implementation-after-run.json',after_implementation)
    write(directory/'authorized-macro-changes.json',changes)
    source_paths=['integration/case0005_payment_continuation.py','config/case0005_payment_continuation.json',
        'tests/test_case0005_payment_continuation.py',str(Path(after['root'])/expected)]
    write(directory/'implementation.json',{'files':{p:file_sha(ROOT/p) for p in source_paths}})
    write(directory/'command.json',{'cwd':str(ROOT),'command':['.venv-integration/Scripts/python.exe','-m',
        'integration.case0005_payment_continuation','--config','config/case0005_payment_continuation.json',
        '--output',str(directory.relative_to(ROOT))], 'new_api_attempts':0})
    files={p.relative_to(directory).as_posix():{'sha256':file_sha(p),'bytes':p.stat().st_size}
        for p in sorted(directory.rglob('*')) if p.is_file() and p.name!='artifact-manifest.json'}
    write(directory/'artifact-manifest.json',{'schema_version':'case0005-payment-artifacts.v1','files':files})


if __name__=='__main__':main()
