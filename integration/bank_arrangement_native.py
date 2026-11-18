"""Original BANK-A05 receives actual own native financing selection.

The result is private formation-condition review, never a signature, registered
credit commitment, reservation, disbursement or separate loan ledger.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from pydantic import Field

from integration.bank_arrangement_actions import BankArrangementActionAssembler
from integration.bank_arrangement_results import BankArrangementResultWorker
from integration.bank_arrangement_native_sources import arrangement_sources, received_selection
from integration.bank_financing_private import checked_result
from integration.project_financing_feedback import own_financing_history
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId, ref_type
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.models import Digest


class BankArrangementPlan(StrictRecord):
    organization_id: TextId
    borrower_id: TextId
    project_id: TextId
    tick: int = Field(ge=1)
    context: ActionContext
    action_input: dict
    objects: list[dict]
    quote_read_refs: list[dict]
    borrower_read_refs: list[dict]
    prior_commitment_origins: list[dict]
    native_evidence_ref: ref_type('Evidence')
    quote_evidence_ref: ref_type('Evidence')
    acceptance_evidence_ref: ref_type('Evidence')


class BankArrangementSettings(StrictRecord):
    version: TextId
    file_path: TextId
    file_sha256: Digest


class BankArrangementApplication:
    VERSION = 'gba-v1-bank-arrangement.v3'
    PREFIX = 'bank_arrangement_received:'

    def __init__(self, *, bank, settings):
        self.bank = bank
        self.settings = BankArrangementSettings.model_validate(settings).model_copy(deep=True)
        self._check_file()
        doc = json.loads(Path(self.settings.file_path).read_bytes())
        if (set(doc) != {'schema_version', 'run_id', 'plans'}
                or doc['schema_version'] != 'bank-arrangement-input.v1' or doc['run_id'] != bank.assembly.client.run_id):
            raise TaskConflict('Bank arrangement changes its original pinned input schema or run')
        self.plans = [BankArrangementPlan.model_validate(p) for p in doc['plans']]
        keys = [(p.organization_id, p.borrower_id, p.project_id, p.tick) for p in self.plans]
        if not keys or len(set(keys)) != len(keys):
            raise TaskConflict('Bank arrangement repeats its original bank/project/time plan')
        for p in self.plans:
            c = p.context
            if (c.run_id != doc['run_id'] or c.actor_id != bank.organizations.get(p.organization_id).actor_id or c.contract_ref.id != 'BANK-A05'
                    or c.scope.kind != 'project' or c.scope.ref.id != p.project_id or c.business_time.offset != p.tick
                    or c.execution_mode == 'offline_fixture'
                    or len({task_digest(r['ref']) for r in p.objects}) != len(p.objects)
                    or len({p.native_evidence_ref.key(), p.quote_evidence_ref.key(), p.acceptance_evidence_ref.key()}) != 3):
                raise TaskConflict('Bank arrangement changes its original bank, action, scope or received source identities')
        self._settings_sha = task_digest(self.settings.model_dump(mode='json'))
        self._plans_sha = task_digest([p.model_dump(mode='json') for p in self.plans])
        self._bound = {}
        self.assembler = BankArrangementActionAssembler(registry=bank.registry, organizations=bank.organizations,
            provider=self, macro_version='gba-public-2026-08-21', source_mode='formal',
            policy_version=bank.settings.policy_version, model_version=bank.assembly.client.versions['model'])
        self.worker = BankArrangementResultWorker(store=bank.assembly.client.tasks, snapshots=bank.snapshots,
            registry=bank.registry, client_version=self.VERSION, model_version=bank.assembly.client.versions['model'],
            validate_invocation=self.validate_invocation, validate_wait=bank.validate_wait)

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest() != self.settings.file_sha256:
            raise TaskConflict('Bank arrangement inputs differ from their pinned independent bytes')

    def check_components(self):
        self._check_file()
        if (task_digest(self.settings.model_dump(mode='json')) != self._settings_sha
                or task_digest([p.model_dump(mode='json') for p in self.plans]) != self._plans_sha
                or self.worker.store is not self.bank.assembly.client.tasks or self.worker.registry is not self.bank.registry
                or self.assembler.organizations is not self.bank.organizations):
            raise TaskConflict('Bank arrangement changed its declared plans or original shared runtime')

    def _key(self, event_id, organization_id):
        return self.PREFIX + task_digest({'event_id': event_id, 'organization_id': organization_id})

    def _record(self, event_id, organization_id):
        store = self.bank.assembly.client.tasks
        with store._lock:
            raw = store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key(event_id, organization_id),)).fetchone()
        if raw is None:
            return None
        row = json.loads(raw[0])
        if (row['record_sha256'] != task_digest({k: v for k, v in row.items() if k != 'record_sha256'})
                or row['event_id'] != event_id or row['organization_id'] != organization_id
                or row['source_file_sha256'] != self.settings.file_sha256):
            raise TaskConflict('Bank arrangement receipt changes its original event, recipient or source record')
        return row

    def _save(self, value):
        value = deepcopy(value)
        value['record_sha256'] = task_digest({k: v for k, v in value.items() if k != 'record_sha256'})
        store = self.bank.assembly.client.tasks
        with store._transaction():
            store._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',
                (self._key(value['event_id'], value['organization_id']), canonical(value)))
        return value

    def _current(self, plan, entry):
        self.bank._check()
        event = received_selection(self, plan=plan, entry=entry)
        if plan.tick != self.bank.assembly.engine.current_tick:
            raise TaskConflict('Bank arrangement must receive its actual selection at the native current time')
        grants = self.bank.organizations.grants(plan.context, 'BANK-A05', 'Bank')
        if not grants or any(g.organization_id != plan.organization_id for g in grants):
            raise TaskConflict('Bank arrangement lacks its current independent function authorization')
        return event

    def project(self, *, context, organization_id, grants):
        bound = self._bound.get(task_digest(context.model_dump(mode='json')))
        if bound is None or bound[0].organization_id != organization_id:
            raise TaskConflict('Bank arrangement reading lacks its actual original received selection')
        plan, entry = bound
        self._current(plan, entry)
        objects, observed = arrangement_sources(self, plan=plan, entry=entry)
        return {'run_id': context.run_id, 'macro_version': 'gba-public-2026-08-21',
            'state_version': self.VERSION + ':' + task_digest(observed), 'read_token': context.read_token,
            'business_time': context.business_time.model_dump(mode='json'),
            'organization_id': organization_id, 'objects': objects}

    def validate_invocation(self, row, prepared):
        bound = self._bound.get(prepared.context_sha256)
        if bound is None:
            raise TaskConflict('Bank arrangement worker lost its actual native reception')
        plan, entry = bound
        self._current(plan, entry)
        if (prepared.context != plan.context or row['identity']['organization_id'] != plan.organization_id
                or prepared.runner.registry is not self.bank.registry):
            raise TaskConflict('Bank arrangement substitutes its original actor, action or processor')
        prepared.reading.recheck()
        return True

    def dispatch(self, *, run_id, organization_id):
        bank = self.bank
        with bank.read_guard():
            bank._check()
            client = bank.assembly.client
            if run_id != client.run_id:
                raise TaskConflict('Bank arrangement observation changes its original run')
            if client.organization_roles.get(organization_id) != 'Bank':
                return
            for entry in client.inbox.for_organization(run_id=run_id, organization_id=organization_id):
                own = entry['payload']
                if (own['event_type'] != 'project_financing_selected' or own['tick'] != bank.assembly.engine.current_tick
                        or own['data'].get('selected') is not True):
                    continue
                plans = [p for p in self.plans if (p.organization_id, p.borrower_id, p.project_id, p.tick)
                    == (organization_id, own['data']['owner_id'], own['project_id'], own['tick'])]
                if len(plans) != 1:
                    raise TaskConflict('Selected bank has no unique original arrangement receipt plan')
                plan = plans[0]
                self._current(plan, entry)
                old = self._record(entry['event_id'], organization_id)
                if old is not None:
                    if old['state'] != 'formed':
                        raise TaskConflict('Unresolved arrangement receipt needs diagnosis, not blind replay')
                    self._formed(old, plan, entry)
                    continue
                objects, observed = arrangement_sources(self, plan=plan, entry=entry)
                self._bound[task_digest(plan.context.model_dump(mode='json'))] = (plan, deepcopy(entry))
                record = self._save({'state': 'preparing', 'event_id': entry['event_id'], 'organization_id': organization_id,
                    'borrower_id': plan.borrower_id, 'project_id': plan.project_id, 'tick': plan.tick,
                    'source_file_sha256': self.settings.file_sha256, 'source_sha256': task_digest(objects), 'observed': observed})
                prepared = self.assembler.build(plan.context, **deepcopy(plan.action_input))
                identity = self.worker.register(prepared, request_id='received-bank-arrangement:' + self._key(entry['event_id'], organization_id))
                record.update(state='processing', identity=identity.as_dict())
                record = self._save(record)
                result = self.worker.execute(identity, prepared)['result']
                if result['kind'] != 'completed':
                    raise TaskConflict('Unresolved original arrangement conditions require explicit diagnosis')
                record.update(state='formed', result_sha256=task_digest(result), choice=result['payload']['choice'])
                self._save(record)

    def _formed(self, record, plan, entry):
        grants = self.bank.organizations.grants(plan.context, 'BANK-A05', 'Bank')
        if any(g.organization_id != plan.organization_id for g in grants):
            raise TaskConflict('Bank arrangement history changes its original authorized organization')
        objects, observed = arrangement_sources(self, plan=plan, entry=entry)
        identity = TaskIdentity(**record['identity'])
        saved = checked_result(self.worker, identity)
        readable = {ref.key() for grant in grants for ref in grant.readable_refs} & {ref.key() for ref in plan.context.visible_refs}
        if any(Reference.model_validate(r['ref']).key() not in readable for r in saved['source_reading']):
            raise TaskConflict('Bank arrangement history lost current permission for its original sources')
        snapshot = self.bank.snapshots.get(identity)
        if (record['source_sha256'] != task_digest(objects) or record['observed'] != observed
                or saved['result_sha256'] != record['result_sha256'] or saved['result']['payload']['choice'] != record['choice']
                or snapshot['context'] != plan.context.model_dump(mode='json') or snapshot['action_input'] != plan.action_input
                or {task_digest(r['ref']): r['projection'] for r in saved['source_reading']}
                    != {task_digest(r['ref']): r['value'] for r in objects}):
            raise TaskConflict('Bank arrangement history substitutes its original reception or completed conditions result')
        return saved

    def prior_arrangements(self, *, organization_id, tick):
        origins = self.prior_reviews(organization_id=organization_id, tick=tick)
        if any(row['choice'] != 'confirm' for row in origins):
            raise TaskConflict('Earlier arrangement decline/requote requires explicit resolution before new financing')
        return origins

    def prior_reviews(self, *, organization_id, tick):
        """Own completed private review outcomes, never confirmed arrangements."""
        self.check_components()
        bank = self.bank
        history = own_financing_history(bank.assembly, organization_id=organization_id, tick=tick, read_guard=bank.read_guard)
        inbox = {e['event_id']: e for e in bank.assembly.client.inbox.for_organization(
            run_id=bank.assembly.client.run_id, organization_id=organization_id)}
        origins = []
        for item in history:
            entry = inbox[item['event_id']]
            plan, = [p for p in self.plans if (p.organization_id, p.borrower_id, p.project_id, p.tick)
                == (organization_id, item['owner_id'], item['project_id'], item['tick'])]
            record = self._record(item['event_id'], organization_id)
            if record is None or record['state'] != 'formed':
                raise TaskConflict('Later bank processing requires diagnosis of its unhandled original selected financing')
            self._formed(record, plan, entry)
            if record['choice'] not in {'confirm', 'decline', 'requote'}:
                raise TaskConflict('Bank arrangement history contains an unresolved original review choice')
            origins.append({'event_id': item['event_id'], 'project_id': plan.project_id, 'tick': plan.tick,
                'organization_id': organization_id, 'borrower_id': plan.borrower_id, 'choice': record['choice'],
                'micro_task_key': TaskIdentity(**record['identity']).key, 'result_sha256': record['result_sha256']})
        return origins

    def evidence(self):
        self.check_components()
        store = self.bank.assembly.client.tasks
        with store._lock:
            records = [json.loads(raw) for raw, in store._db.execute(
                'SELECT value FROM metadata WHERE key LIKE ? ORDER BY key', (self.PREFIX + '%',))]
        return {'version': self.VERSION, 'source_file_sha256': self.settings.file_sha256, 'receipts': records,
            'limits': 'Private original A05 conditions only; no registered offer/arrangement, signature, reservation, disbursement or cash receipt.'}
