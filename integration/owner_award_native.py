"""Original OWN-A10 for the native independent Owner contract award request."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from pydantic import Field

from integration.bank_financing_private import checked_result
from integration.module_host import module_factory_descriptor
from integration.owner_award_actions import OwnerAwardActionAssembler
from integration.owner_award_results import OwnerAwardResultWorker
from integration.owner_award_native_sources import (
    award_scope, award_sources, received_contractor_acceptance, prior_owner_awards,
)
from src.actions.contracts.common import StrictRecord, TextId, ActionContext, Measured, EvidenceRecord, Reference, ref_type
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.models import Digest


class OwnerAwardNativePlan(StrictRecord):
    organization_id: TextId
    project_id: TextId
    tick: int = Field(ge=1)
    context: ActionContext
    action_input: dict
    objects: list[dict]
    reviewed_contractor_terms: dict
    received_acceptance_ref: ref_type('PartyAcceptance')
    native_evidence_ref: ref_type('Evidence')
    history_revision_refs: list[ref_type('ContractChangeRequest')] = Field(default_factory=list)
    max_prior_accepts: int | None = Field(default=None, ge=1)
    utility: Measured
    probability: Measured


class OwnerAwardNativeSettings(StrictRecord):
    version: TextId
    policy_version: TextId
    file_path: TextId
    file_sha256: Digest


class OwnerAwardNativeApplication:
    VERSION = 'gba-v1-owner-award.v4'
    PREFIX = 'owner_award_native_request:'

    def __init__(self, *, parent, settings):
        self.parent = parent
        self.assembly = parent.assembly
        self.settings = OwnerAwardNativeSettings.model_validate(settings).model_copy(deep=True)
        self._check_file()
        self.document = json.loads(Path(self.settings.file_path).read_bytes())
        if (set(self.document) != {'schema_version', 'run_id', 'plans'}
                or self.document['schema_version'] != 'owner-award-native-input.v1'
                or self.document['run_id'] != self.assembly.client.run_id):
            raise TaskConflict('Owner award requires its original explicit initial agreement views')
        self.plans = [OwnerAwardNativePlan.model_validate(p) for p in self.document['plans']]
        keys = [(p.organization_id, p.project_id, p.tick, p.reviewed_contractor_terms.get('contractor_id'),
                 Decimal(p.reviewed_contractor_terms['price']['value']))
                for p in self.plans]
        if not keys or len(keys) != len(set(keys)):
            raise TaskConflict('Owner award repeats an independent current request plan')
        routes = self.assembly.client.native_routes
        if (not routes.settings.micro_owner_award_scope
                or ('Owner', 'decide_contract_award') in routes._proposals
                or ('Owner', 'owner_contract_award') in routes._decisions):
            raise TaskConflict('Owner award requires exclusive explicitly scoped micro routes')
        self.registry, self.organizations = parent.registry, parent.organizations
        self.read_guard = parent.read_guard
        self.snapshots = InvocationSnapshotStore(self.assembly.client.tasks)
        self._bound = {}
        for p in self.plans:
            if (p.context.run_id != self.assembly.client.run_id or p.context.contract_ref.id != 'OWN-A10'
                    or p.context.execution_mode == 'offline_fixture' or p.context.scope.kind != 'project'
                    or p.context.scope.ref.id != p.project_id or p.context.business_time.offset != p.tick
                    or self.assembly.client.organization_roles.get(p.organization_id) != 'Owner'
                    or self.organizations.get(p.organization_id).actor_id != p.context.actor_id
                    or p.reviewed_contractor_terms.get('client_id') != p.organization_id
                    or self.assembly.client.organization_roles.get(
                        p.reviewed_contractor_terms.get('contractor_id')) != 'Contractor'
                    or p.action_input.get('party_acceptance_refs') != [p.received_acceptance_ref.model_dump(mode='json')]
                    or len({task_digest(r['ref']) for r in p.objects}) != len(p.objects)):
                raise TaskConflict('Owner award changes its own action, project, clock or actual reception reference')
        self.assembler = OwnerAwardActionAssembler(registry=self.registry, organizations=self.organizations,
            provider=self, macro_version='gba-public-2026-08-21', source_mode='formal',
            policy_version=self.settings.policy_version, model_version=self.assembly.client.versions['model'])
        self.worker = OwnerAwardResultWorker(store=self.assembly.client.tasks, snapshots=self.snapshots,
            registry=self.registry, client_version=self.VERSION, model_version=self.assembly.client.versions['model'],
            validate_invocation=self.validate_invocation, validate_wait=self.validate_wait)
        self._pins = task_digest([self.document, self.settings.model_dump(mode='json'),
                                 [p.model_dump(mode='json') for p in self.plans]])
        self._source_pins = self.source_descriptors()
        self._components = (parent, self.assembly, self.registry, self.organizations, self.worker, self.assembler,
                            self.snapshots, self.read_guard)

    @staticmethod
    def source_descriptors():
        from integration.formation_native_outcome_query import query_formation_outcome, _original_result
        return {name: module_factory_descriptor(fn, 'owner-award-native-sources.v1') for name, fn in
                [('query', query_formation_outcome), ('query_original_result', _original_result),
                 ('scope', award_scope), ('prepare', award_sources),
                 ('receive', received_contractor_acceptance), ('history', prior_owner_awards)]}

    def proposal_bindings(self):
        return {('Owner', 'decide_contract_award'): self.propose}

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest() != self.settings.file_sha256:
            raise TaskConflict('Owner award initial reviewed input bytes changed')

    def _check(self):
        self._check_file()
        if (self._components != (self.parent, self.assembly, self.registry, self.organizations, self.worker,
                                 self.assembler, self.snapshots, self.read_guard)
                or self.parent.registry is not self.registry or self.parent.organizations is not self.organizations
                or self.parent.read_guard != self.read_guard or self.parent.assembly is not self.assembly
                or self.parent.settings.owner != self.settings
                or self.worker.store is not self.assembly.client.tasks or self.worker.registry is not self.registry
                or self.assembler.registry is not self.registry or self.assembler.organizations is not self.organizations
                or self.worker.validate_invocation != self.validate_invocation or self.worker.validate_wait != self.validate_wait
                or self._source_pins != self.source_descriptors()
                or self._pins != task_digest([self.document, self.settings.model_dump(mode='json'),
                                             [p.model_dump(mode='json') for p in self.plans]])):
            raise TaskConflict('Owner award changed its original sources, worker or shared authority')

    def current(self, request):
        self.parent._check()
        scope = award_scope(self.assembly, request, purpose='propose')
        price = Decimal(str(self.assembly.engine.projects[scope['project_id']].contract_sum))
        plans = [p for p in self.plans if (p.organization_id, p.project_id, p.tick,
                 p.reviewed_contractor_terms['contractor_id']) ==
                 (scope['owner_id'], scope['project_id'], scope['tick'], scope['contractor_id'])
                 and Decimal(p.reviewed_contractor_terms['price']['value']) == price]
        if len(plans) != 1:
            raise TaskConflict('Actual Owner award request lacks its exact independently supplied plan')
        self.organizations.grants(plans[0].context, 'OWN-A10', 'Owner')
        return plans[0], scope

    def project(self, *, context, organization_id, grants):
        bound = self._bound.get(task_digest(context.model_dump(mode='json')))
        if bound is None:
            raise TaskConflict('Owner award reading lacks the actual current original request')
        plan, request = bound
        self.current(request)
        if context != plan.context or organization_id != plan.organization_id:
            raise TaskConflict('Owner award reading changes its original organization or invocation')
        objects, _ = award_sources(self, plan, request)
        return {'run_id': context.run_id, 'macro_version': 'gba-public-2026-08-21',
                'state_version': 'native-owner-award:' + task_digest(objects), 'read_token': context.read_token,
                'business_time': context.business_time.model_dump(mode='json'),
                'organization_id': organization_id, 'objects': objects}

    def validate_invocation(self, row, prepared):
        plan, request = self._bound[prepared.context_sha256]
        self.current(request)
        if (prepared.context != plan.context or row['identity']['organization_id'] != plan.organization_id
                or prepared.runner.registry is not self.registry):
            raise TaskConflict('Owner award worker changes its original invocation')
        prepared.reading.recheck()
        return True

    def validate_wait(self, *args, **kwargs):
        raise TaskConflict('Unresolved Owner award requires explicit source diagnosis and continuation')

    def query_native_outcome(self,identity,*,organization_id,tick):
        from integration.formation_native_outcome_query import query_formation_outcome
        return query_formation_outcome(self,identity,organization_id=organization_id,tick=tick,owner=True)

    def records(self):
        with self.assembly.client.tasks._lock:
            rows = [json.loads(v) for v, in self.assembly.client.tasks._db.execute(
                'SELECT value FROM metadata WHERE key LIKE ?', (self.PREFIX + '%',))]
        if any(r['record_sha256'] != task_digest({k: v for k, v in r.items() if k != 'record_sha256'}) for r in rows):
            raise TaskConflict('Owner award original technical request evidence changed')
        return rows

    def save(self, key, record):
        record = deepcopy(record)
        record['record_sha256'] = task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
        with self.assembly.client.tasks._transaction():
            self.assembly.client.tasks._db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, canonical(record)))
        return record

    @staticmethod
    def summary(saved):
        choice = saved['result']['payload']['choice']
        if choice == 'accept':
            return True, 'accept_contract'
        if choice == 'revise':
            return False, 'request_contract_revision'
        raise TaskConflict('Owner rejection or unresolved result is not native contract revision')

    def propose(self, request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        with self.read_guard():
            plan, scope = self.current(request)
            key = self.PREFIX + task_digest([self.assembly.client.simulation_id, scope, request.request_id])
            if any(r['key'] == key for r in self.records()):
                raise TaskConflict('Owner award already claimed; inspect its original transport')
            record = self.save(key, {'key': key, 'state': 'preparing', 'scope': scope,
                                     'native_request': request.model_dump(mode='json')})
            self._bound[task_digest(plan.context.model_dump(mode='json'))] = (plan, request.model_copy(deep=True))
            objects, observed = award_sources(self, plan, request)
            prepared = self.assembler.build(plan.context, **deepcopy(plan.action_input))
            identity = self.worker.register(prepared, request_id=key + ':OWN-A10')
            record.update(identity=identity.as_dict(), source_sha256=task_digest(objects), observed=observed)
            record = self.save(key, record)
            self.worker.execute(identity, prepared)
            saved = checked_result(self.worker, identity)
            accepted, action = self.summary(saved)
            if accepted:
                for ref in saved['result']['payload']['condition_refs']:
                    condition = prepared.reading.resolve(Reference.model_validate(ref))
                    if condition.verification.state != 'known' or condition.verification.value is not True:
                        raise TaskConflict('Unresolved detailed award condition cannot become native unconditional acceptance')
            for metric, unit in ((plan.utility, 'score'), (plan.probability, 'probability')):
                if (metric.unit != unit or not 0 <= Decimal(metric.value) <= 1
                        or not isinstance(prepared.reading.resolve(metric.basis_ref), EvidenceRecord)):
                    raise TaskConflict('Owner award indicators require sourced bounded values')
            response = AgentProposalResponseV1(request_id=request.request_id, action_type=action, accepted=accepted,
                utility=float(plan.utility.value), probability=float(plan.probability.value),
                reason=saved['result']['payload']['note'], data={'stage_state_mutated': False},
                factors={'micro_action_id': 'OWN-A10', 'micro_task_key': identity.key,
                         'micro_result_sha256': saved['result_sha256'], 'native_award_scope': scope})
            record.update(state='formed', result_sha256=saved['result_sha256'],
                          proposal_response_sha256=task_digest(response.model_dump(mode='json')))
            self.save(key, record)
            return response

    def decide(self, request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1, AgentDecisionResponseV1
        from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
        with self.read_guard():
            self.parent._check()
            scope = award_scope(self.assembly, request, purpose='decide')
            records = [r for r in self.records() if r['state'] == 'formed' and r['scope'] == scope]
            if len(records) != 1:
                raise TaskConflict('Owner award confirmation lacks its one original micro result')
            record = records[0]
            original = AgentProposalRequestV1.model_validate(record['native_request'])
            plan, _ = self.current(original)
            saved = checked_result(self.worker, TaskIdentity(**record['identity']))
            objects, observed = award_sources(self, plan, original)
            accepted, action = self.summary(saved)
            proposals = [t['output'] for t in self.assembly.client.tasks.for_organization(
                run_id=plan.context.run_id, organization_id=plan.organization_id)
                if t['state'] == 'output_formed' and t['identity']['purpose'] == 'propose'
                and t['identity']['action_id'] == 'decide_contract_award'
                and t['output'].get('factors', {}).get('native_award_scope') == scope]
            if (len(proposals) != 1 or record['result_sha256'] != saved['result_sha256']
                    or record['source_sha256'] != task_digest(objects) or record['observed'] != observed
                    or task_digest(proposals[0]) != record['proposal_response_sha256']
                    or proposals[0]['accepted'] != accepted or proposals[0]['action_type'] != action
                    or action not in request.constraints.allowed_actions
                    or request.current_state.get('risk_inputs') != proposals[0]['factors']
                    or request.choice_contract.output_field is not None or request.candidate_options):
                raise TaskConflict('Owner confirmation changes its original result, sources or bounded action')
            response = AgentDecisionResponseV1(request_id=request.request_id, agent_id=plan.organization_id,
                action_type=action, decision=accepted, reason=proposals[0]['reason'],
                data={**proposals[0]['factors'], 'stage_state_mutated': False,
                      'proposal_response_sha256': record['proposal_response_sha256']})
            ExternalAgentDecisionProvider._validated_action(request, response)
            return response

    def evidence(self):
        self._check()
        return {'version': self.VERSION, 'source_file_sha256': self.settings.file_sha256, 'requests': self.records(),
                'limits': 'Independent Owner acceptance/revision of the reviewed complete agreement. '
                          'Only native macro executes its aggregate signature; no detailed contract core, '
                          'physical reservation, debt, cash execution or payment is inferred.'}
