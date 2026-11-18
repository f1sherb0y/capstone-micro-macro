"""Run original OWN-A09 on native invitation requests, using explicit own sources.

The bridge keeps original workers, authority, journal and the engine writer
guard. It returns intentions through the original module; only the native
lifecycle creates invitations and engagements. No publication receipt is made.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from integration.agent_client import AgentClientError
from integration.owner_tender_actions import OwnerTenderActionAssembler
from integration.owner_tender_results import OwnerTenderResultWorker
from src.actions.contracts.common import ActionContext, EvidenceRecord, Measured, StrictRecord, TextId, ref_type
from src.actions.contracts.owner_tender_objects import OwnerEligibleBidderView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.models import Digest


class OwnerInvitationPlan(StrictRecord):
    organization_id: TextId
    project_id: TextId
    tick: Annotated[int, Field(ge=0)]
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    utility: Measured
    probability: Measured

    @model_validator(mode='after')
    def original_invitation_context(self):
        if (self.context.contract_ref.id != 'OWN-A09' or self.context.scope.kind != 'project'
                or self.context.scope.ref.id != self.project_id or self.context.execution_mode == 'offline_fixture'):
            raise ValueError('Native invitation requires its original formal OWN-A09 project context')
        return self


class OwnerInvitationSettings(StrictRecord):
    version: TextId
    file_path: TextId
    file_sha256: Digest
    native_project_ids: list[TextId] = Field(default_factory=list)
    selection_mode: Literal['review_native', 'lowest_eligible_price'] = 'review_native'
    selection_tie_break: Literal['wait', 'organization_id'] = 'wait'


class OwnerInvitationBridge:
    VERSION = 'gba-v1-owner-invitation.v2'
    HANDLER_KEY = ('Owner', 'select_tender_invitees')

    def __init__(self, *, assembly, bindings, settings, policy_version):
        self.assembly, self.bindings = assembly, bindings
        self.settings = OwnerInvitationSettings.model_validate(settings).model_copy(deep=True)
        raw = Path(self.settings.file_path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.settings.file_sha256:
            raise TaskConflict('Owner invitation input differs from its pinned independent file')
        document = json.loads(raw)
        if (set(document) != {'schema_version', 'run_id', 'plans'}
                or document['schema_version'] != 'owner-invitation-input.v1'
                or document['run_id'] != assembly.client.run_id):
            raise TaskConflict('Owner invitation input has a different schema or original run')
        self.plans = [OwnerInvitationPlan.model_validate(value) for value in document['plans']]
        native_projects = self.settings.native_project_ids
        if (len(set(native_projects)) != len(native_projects)
                or set(native_projects) & {p.project_id for p in self.plans}
                or not set(native_projects) <= set(assembly.engine.projects)):
            raise TaskConflict('Native invitation ownership requires distinct existing projects outside every micro plan')
        keys = [(plan.organization_id, plan.project_id, plan.tick) for plan in self.plans]
        if not keys or len(set(keys)) != len(keys) or len({p.context.read_token for p in self.plans}) != len(keys):
            raise TaskConflict('Owner invitation plans require distinct exact request selectors and read tokens')
        self._contexts = {task_digest(plan.context.model_dump(mode='json')): plan for plan in self.plans}
        if len(self._contexts) != len(self.plans):
            raise TaskConflict('Owner invitation plans repeat an immutable action context')
        self._bound = {}
        self.assembler = OwnerTenderActionAssembler(registry=bindings.registry, organizations=bindings.organizations,
            provider=self, macro_version='gba-public-2026-08-21', source_mode='formal', methods=bindings.methods,
            policy_version=policy_version, model_version=assembly.client.versions['model'], model_host=bindings.model_host)
        self.worker = OwnerTenderResultWorker(store=assembly.client.tasks,
            snapshots=InvocationSnapshotStore(assembly.client.tasks), registry=bindings.registry,
            client_version=self.VERSION, model_version=assembly.client.versions['model'],
            validate_invocation=self.validate_invocation, validate_wait=self.validate_wait)
        self._other_decision = assembly.client.decision_handler
        self._original_other_decision = self._other_decision
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._plans_sha256 = task_digest([p.model_dump(mode='json') for p in self.plans])
        self._native_routes = getattr(assembly.client,'native_routes',None)
        self._native_propose = self._native_routes.propose if native_projects and self._native_routes is not None else None
        if native_projects and (self._native_propose is None
                or not self._native_routes.settings.mixed_owner_invitation_scope
                or self.HANDLER_KEY not in self._native_routes._proposals
                or ('Owner','owner_tender_shortlist') not in self._native_routes._decisions):
            raise TaskConflict('Native invitation projects require explicitly declared original proposal and final routes')

    def _check(self):
        self.assembly._validate_components()
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest() != self.settings.file_sha256:
            raise TaskConflict('Owner invitation independent inputs changed during execution')
        if (task_digest(self.settings.model_dump(mode='json')) != self._settings_sha256
                or task_digest([p.model_dump(mode='json') for p in self.plans]) != self._plans_sha256
                or self._other_decision != self._original_other_decision
                or self.settings.native_project_ids and (
                    self.assembly.client.native_routes is not self._native_routes
                    or self._native_propose != self._native_routes.propose)
                or self.worker.store is not self.assembly.client.tasks or self.worker.registry is not self.bindings.registry
                or self.assembler.organizations is not self.bindings.organizations):
            raise TaskConflict('Owner invitation substituted its original worker, authority or journal')

    def install(self):
        client = self.assembly.client
        with client._lock:
            if (client._tender_feedback is not None or client._calls or client._request_hashes
                    or client.binding_installation_blocked()
                    or client.decision_handler is not self._other_decision):
                raise TaskConflict('Owner invitation routes must be declared before tender binding and all native requests')
            if self.HANDLER_KEY in client.proposal_handlers:
                raise TaskConflict('Native invitation ownership cannot replace an already installed micro handler')
            client.bind_proposal_handler(role='Owner', operation='select_tender_invitees',
                handler=self.propose, client_version=self.VERSION)
            # Explicit composition preserves the prior native handler. The
            # original tender installation subsequently pins this entire chain.
            client.decision_handler = self.decide

    def _current(self, request):
        self._check()
        engine = self.assembly.engine
        if (request.agent.role != 'Owner' or request.operation != self.HANDLER_KEY[1]
                or type(request.metadata.get('tick')) is not int or request.metadata['tick'] != engine.current_tick):
            raise TaskConflict('Owner invitation requires the current original native request')
        project = engine.projects.get(request.inputs['project']['project_id'])
        if (project is None or project.owner_id != request.agent.agent_id or project.current_stage.value != 'tendering'
                or project.model_dump(mode='json') != request.inputs['project']):
            raise TaskConflict('Owner invitation substitutes its actual current project, stage or owner')
        for candidate in request.inputs['candidates']:
            actual = engine.agents.get(candidate.get('agent_id'))
            if actual is None or actual.role != 'Contractor' or actual.model_dump(mode='json') != candidate:
                raise TaskConflict('Owner invitation candidate differs from the actual native supplied enterprise')
        return project

    def _plan(self, request):
        self._current(request)
        matches = [plan for plan in self.plans if (plan.organization_id, plan.project_id, plan.tick) ==
            (request.agent.agent_id, request.inputs['project']['project_id'], request.metadata['tick'])]
        if len(matches) != 1:
            raise TaskConflict('Current native invitation lacks its independently supplied exact source plan')
        plan = matches[0]
        if plan.context.run_id != self.assembly.client.run_id:
            raise TaskConflict('Owner invitation context changes original run')
        grants = self.bindings.organizations.grants(plan.context, 'OWN-A09', 'Owner')
        if not grants or grants[0].organization_id != request.agent.agent_id:
            raise TaskConflict('Owner invitation plan changes the actual authorized owner')
        return plan

    def _key(self, request):
        return 'owner_invitation_native_request:' + task_digest([
            self.assembly.client.simulation_id, request.agent.agent_id, request.request_id])

    def _save(self, request, value):
        value = deepcopy(value)
        value['record_sha256'] = task_digest({k: v for k, v in value.items() if k != 'record_sha256'})
        store = self.assembly.client.tasks
        with store._transaction():
            store._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)', (self._key(request), canonical(value)))
        return value

    def _record(self, request):
        with self.worker.store._lock:
            row = self.worker.store._db.execute('SELECT value FROM metadata WHERE key=?', (self._key(request),)).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        if (value['record_sha256'] != task_digest({k: v for k, v in value.items() if k != 'record_sha256'})
                or value['request_sha256'] != task_digest(request.model_dump(mode='json'))
                or value['source_file_sha256'] != self.settings.file_sha256):
            raise TaskConflict('Owner invitation cannot replace its original request or source evidence')
        return value

    def project(self, *, context, organization_id, grants):
        digest = task_digest(context.model_dump(mode='json'))
        bound = self._bound.get(digest)
        if bound is None or bound[0].organization_id != organization_id:
            raise TaskConflict('Owner invitation projection requires the actual current request binding')
        plan, request = bound
        self._current(request)
        objects = deepcopy(plan.objects)
        matches = [row for row in objects if row['ref'] == plan.native_evidence_ref.model_dump(mode='json')]
        if len(matches) != 1 or matches[0]['value'].get('content_hash') is not None:
            raise TaskConflict('Owner native evidence must have exactly one explicit unbound input placeholder')
        matches[0]['value']['content_hash'] = task_digest(request.model_dump(mode='json'))
        evidence = EvidenceRecord.model_validate(matches[0]['value'])
        if evidence.source_kind != 'synthetic' or evidence.basis_kind != 'observed':
            raise TaskConflict('Native invitation provenance must remain simulator observation evidence')
        return {'run_id': context.run_id, 'macro_version': 'gba-public-2026-08-21',
            'state_version': 'current-native-owner-request:' + task_digest(request.model_dump(mode='json')),
            'read_token': context.read_token, 'business_time': context.business_time.model_dump(mode='json'),
            'organization_id': organization_id, 'objects': objects}

    def validate_invocation(self, row, prepared):
        bound = self._bound.get(task_digest(prepared.context.model_dump(mode='json')))
        if bound is None:
            raise TaskConflict('Owner invitation execution lacks its original current request binding')
        plan, request = bound
        self._current(request)
        if (prepared.context != plan.context or row['identity']['organization_id'] != plan.organization_id
                or prepared.runner.registry is not self.worker.registry):
            raise TaskConflict('Owner invitation execution substitutes its selected plan or original processor')
        prepared.reading.recheck()
        return True

    def validate_wait(self, *args, **kwargs):
        raise TaskConflict('Pending Owner invitation requires original-source diagnosis; no automatic continuation')

    def _selected(self, request, plan, result):
        if result['kind'] != 'completed' or result['payload']['choice'] != 'invite':
            raise TaskConflict('Only the completed original OWN-A09 invite branch maps to native invitation')
        selected = result['payload']['bidder_ids']
        candidates = {row['agent_id'] for row in request.inputs['candidates']}
        if (not selected or len(selected) != len(set(selected)) or not set(selected) <= candidates
                or len(selected) > request.inputs['limit']):
            raise TaskConflict('Original micro invitation must fit actual native candidates and declared limit')
        bidders = [OwnerEligibleBidderView.model_validate(row['value']) for row in plan.objects
            if row['ref']['kind'] == 'EligibleBidder']
        for bidder in bidders:
            organization = self.bindings.organizations.get(bidder.organization_id)
            if (bidder.actor_id != organization.actor_id or not any(
                    assignment.role == 'Contractor' and assignment.function_ref == bidder.function_ref
                    for assignment in organization.assignments)):
                raise TaskConflict('Owner invitation bidder substitutes an original registered actor or function')
        supplied = {bidder.organization_id for bidder in bidders}
        if supplied != candidates:
            raise TaskConflict('Owner invitation lacks the complete original native candidate projection set')
        return selected

    def propose(self, request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1

        with self.bindings.read_guard():
            if request.inputs.get('project',{}).get('project_id') in self.settings.native_project_ids:
                self._current(request)
                return self._native_propose(request.model_copy(deep=True))
            plan = self._plan(request)
            prior = self._record(request)
            if prior is not None:
                raise TaskConflict('Original Owner invitation is already claimed; read saved transport output or diagnose it')
            self._bound[task_digest(plan.context.model_dump(mode='json'))] = (plan, request.model_copy(deep=True))
            record = self._save(request, {'schema_version': self.VERSION, 'state': 'preparing',
                'run_id': self.assembly.client.run_id, 'simulation_id': self.assembly.client.simulation_id,
                'organization_id': plan.organization_id, 'project_id': plan.project_id,
                'native_request': request.model_dump(mode='json'), 'request_sha256': task_digest(request.model_dump(mode='json')),
                'source_file_sha256': self.settings.file_sha256})
            prepared = self.assembler.build(plan.context, **deepcopy(plan.action_input))
            identity = self.worker.register(prepared, request_id='owner-invitation:' + request.request_id)
            outcome = self.worker.execute(identity, prepared)
            selected = self._selected(request, plan, outcome['result'])
            record.update(state='formed', identity=identity.as_dict(), result_sha256=task_digest(outcome['result']))
            self._save(request, record)

            def indicator(value, unit):
                from decimal import Decimal
                evidence = prepared.reading.resolve(value.basis_ref)
                if not isinstance(evidence, EvidenceRecord) or value.unit != unit or not 0 <= Decimal(value.value) <= 1:
                    raise TaskConflict('Owner invitation native indicators require explicit current own evidence and units')
                return float(value.value)

            return AgentProposalResponseV1(request_id=request.request_id, action_type='invite_contractors', accepted=True,
                utility=indicator(plan.utility, 'score'), probability=indicator(plan.probability, 'probability'),
                reason=outcome['result']['payload']['note'], data={'selected_agent_ids': selected, 'ranked_candidates': []},
                factors={'micro_action_id': 'OWN-A09', 'micro_result_sha256': record['result_sha256'],
                    'micro_task_key': identity.key, 'source_file_sha256': self.settings.file_sha256})

    def decide(self, request):
        from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1, AgentProposalRequestV1

        if (request.agent.role, request.decision_type) != ('Owner', 'owner_tender_shortlist'):
            return self._other_decision(request)
        with self.bindings.read_guard():
            self._check()
            if request.project_id in self.settings.native_project_ids:
                project = self.assembly.engine.projects.get(request.project_id)
                if (project is None or project.owner_id != request.agent.agent_id
                        or request.tick != self.assembly.engine.current_tick or project.current_stage.value!='tendering'):
                    raise TaskConflict('Native invitation final decision changes its declared current project or Owner')
                return self._other_decision(request.model_copy(deep=True))
            rows = []
            with self.worker.store._lock:
                raw_rows = self.worker.store._db.execute("SELECT value FROM metadata WHERE key LIKE 'owner_invitation_native_request:%'").fetchall()
            for raw, in raw_rows:
                row = json.loads(raw)
                native = row['native_request']
                if (row['organization_id'], row['project_id'], native['metadata']['tick']) == (
                        request.agent.agent_id, request.project_id, request.tick):
                    rows.append(row)
            if len(rows) != 1:
                raise TaskConflict('Owner final invitation lacks one exact original micro request')
            original = AgentProposalRequestV1.model_validate(rows[0]['native_request'])
            record = self._record(original)
            plan = self._plan(original)
            identity = TaskIdentity(**record['identity'])
            saved = self.worker.get_record(identity)
            if (record['state'] != 'formed' or saved is None or saved['result_sha256'] != record['result_sha256']
                    or request.decision_support.get('decision_factors', {}).get('micro_result_sha256') != record['result_sha256']):
                raise TaskConflict('Owner final invitation substitutes its original formed micro decision')
            selected = self._selected(original, plan, saved['result'])
            candidates = {str(option['id']) for option in request.candidate_options}
            if (request.choice_contract.output_field != 'selected_agent_ids' or not request.choice_contract.multiple
                    or not set(selected) <= candidates
                    or request.choice_contract.limit is not None and len(selected) > request.choice_contract.limit):
                raise TaskConflict('Owner final invitation changes its current bounded candidate choice')
            return AgentDecisionResponseV1(request_id=request.request_id, agent_id=request.agent.agent_id,
                action_type='invite_contractors', decision=True, reason=saved['result']['payload']['note'],
                data={'selected_agent_ids': selected, 'micro_action_id': 'OWN-A09',
                    'micro_result_sha256': saved['result_sha256'], 'proposal_request_id': original.request_id})

    def evidence(self):
        self._check()
        with self.worker.store._lock:
            records = [json.loads(raw) for raw, in self.worker.store._db.execute(
                "SELECT value FROM metadata WHERE key LIKE 'owner_invitation_native_request:%'")]
        return {'version': self.VERSION, 'source_file_sha256': self.settings.file_sha256, 'requests': records,
            'native_project_ids':list(self.settings.native_project_ids),
            'formal_execution': 'Original native lifecycle creates actual invitations; micro output alone is no receipt.'}


def build_application(*, assembly, request, output_directory, offline, settings, authority=None):
    """Compose with the existing Contractor application before its route binding."""
    from integration.contractor_tender_application import build_application as build_contractor

    required = {'contractor', 'owner_invitation', 'policy_version'}
    if not isinstance(settings, dict) or not required <= set(settings) or set(settings) - required - {'owner_selection_review'}:
        raise ValueError('Owner/Contractor composition requires explicit original application and Owner source settings')
    original = build_contractor(assembly=assembly, request=request, output_directory=output_directory,
        offline=offline, settings=settings['contractor'], authority=authority)
    try:
        bridge = OwnerInvitationBridge(assembly=assembly, bindings=original,
            settings=settings['owner_invitation'], policy_version=settings['policy_version'])
        bridge.install()

        review = None
        if settings.get('owner_selection_review') is not None:
            from integration.owner_selection_review import OwnerSelectionReview
            review = OwnerSelectionReview(assembly=assembly, bindings=original,
                settings=settings['owner_selection_review'], policy_version=settings['policy_version'])
            review.install()

        def evidence():
            return {'contractor': original.evidence(), 'owner_invitation': bridge.evidence(),
                **({'owner_selection_review':review.evidence()} if review is not None else {})}

        return replace(original, evidence=evidence)
    except Exception:
        original.close()
        raise
