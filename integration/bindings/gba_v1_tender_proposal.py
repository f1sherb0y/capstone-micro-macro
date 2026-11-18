"""Expose an audited A02 bid through GBA's existing consider_tender entry."""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
import math

from integration.agent_client import AgentClientError
from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, Measured, Money, Reference, TextId, TimeWindow, ValueState, ref_type, walk_references
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class GbaTenderProposalMappingView(GovReviewAuthored):
    """Independent professional indicators for one exact audited bid result.

    Neither price nor markup is used to invent bid probability, delivery risk,
    utility or profit rate. Declines need an independently sourced reference
    price because the old interface requires all five fields for both branches.
    """
    ref: ref_type('GbaTenderProposalMapping')
    run_id: TextId
    simulation_id: TextId
    organization_id: TextId
    project_id: TextId
    package_ref: ref_type('ProcurementPackage')
    request_sha256: Digest
    context_sha256: Digest
    input_sha256: Digest
    result_sha256: Digest
    result_evidence_ref: ref_type('Evidence')
    legacy_currency: TextId
    utility: ValueState[Measured]
    bid_probability: ValueState[Measured]
    risk_level: ValueState[Measured]
    regional_friction: ValueState[Measured]
    expected_profit: ValueState[Measured]
    declined_reference_price: ValueState[Money]


def gba_tender_proposal_source_schemas():
    # Saved-result reading must also recognize original pipeline source objects.
    from integration.bindings.gba_v1_bid_capacity import gba_bid_capacity_source_schemas

    return gba_bid_capacity_source_schemas()


@dataclass(frozen=True)
class SavedContractorBid:
    """Host-read persisted original input/result/audit, never a model payload."""
    context: ActionContext
    current_context: ActionContext
    action_input: object
    result: object
    audit: dict
    reading: ActionReadView
    mapping_ref: Reference


class GbaTenderProposalAdapter:
    """Register this callable at ('Contractor', 'consider_tender').

    read_output obtains a previously completed, audited A02 from host storage.
    It must supply a fresh authorized view containing the original versions.
    revalidate explicitly approves exposing this original bid at that read point. The
    adapter performs no processor/model call, fallback or automatic retry.
    GbaV1AgentClient owns request identity, persistence and single-flight; the
    simulation retains the later final choice, bid creation and core effects.
    """
    HANDLER_KEY = ('Contractor', 'consider_tender')
    VERSION = 'gba-v1-contractor-a02-proposal.v2'

    def __init__(self, *, run_id, simulation_id, registry, read_output, revalidate):
        if (not isinstance(run_id, str) or not run_id.strip()
                or not isinstance(simulation_id, str) or not simulation_id.strip()
                or not callable(read_output) or not callable(revalidate)):
            raise ValueError('Explicit run, simulation, saved-output reader and fresh validation required')
        self.run_id, self.simulation_id = run_id, simulation_id
        self.registry, self.read_output = registry, read_output
        self.revalidate = revalidate

    def __call__(self, request):
        return self._response(request, self.read_output)

    def _recovery_host(self):
        from integration.contractor_tender_host import GbaContractorTenderHost
        host = getattr(self.read_output, '__self__', None)
        if not isinstance(host, GbaContractorTenderHost) or self.read_output != host._read_output:
            raise AgentClientError('Tender recovery requires its original concrete read-only host')
        host._check(bound=True)
        return host

    @property
    def recovery_guard(self):
        host = getattr(self.read_output, '__self__', None)
        return getattr(host, 'recovery_guard', None)

    @property
    def saved_recovery_enabled(self):
        return self._recovery_host().callbacks.recover_request is not None

    def recover_saved_proposal(self, request):
        return self._response(request, self._recovery_host()._read_saved_output)

    def _response(self, request, read_output):
        from gba_construction_sim.backend.agents.contracts import (
            AGENT_MODULE_CONTRACT_VERSION, AgentProposalRequestV1, AgentProposalResponseV1,
        )
        from gba_construction_sim.backend.agents.operation_specs import (
            get_operation_contract, validate_operation_inputs, validate_operation_response,
        )

        request = AgentProposalRequestV1.model_validate(request).model_copy(deep=True)
        if (request.contract_version != AGENT_MODULE_CONTRACT_VERSION
                or (request.agent.role, request.operation) != self.HANDLER_KEY
                or request.metadata.get('simulation_id') not in {None, self.simulation_id}):
            raise AgentClientError('Tender proposal request differs from its original macro binding')
        contract = get_operation_contract(request.operation, request.agent.role)
        if request.operation_contract != contract:
            raise AgentClientError('Tender proposal requires the actual old operation contract')
        validate_operation_inputs(contract, request.inputs)
        saved = read_output(request.model_copy(deep=True))
        if not isinstance(saved, SavedContractorBid) or not isinstance(saved.reading, ActionReadView):
            raise AgentClientError('Tender proposal requires a saved typed A02 with an authorized reading')
        context, current, reading = saved.context, saved.current_context, saved.reading
        if (not isinstance(context, ActionContext) or context.run_id != self.run_id
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'CONTRACTOR-A02'
                or context.execution_mode == 'offline_fixture' or reading.organization_id != request.agent.agent_id):
            raise AgentClientError('Saved bid changes original run, contract, enterprise or formal source mode')
        if (not isinstance(current, ActionContext) or current.execution_mode == 'offline_fixture'
                or any(getattr(current, field) != getattr(context, field)
                       for field in ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope'))
                or current.business_time.clock_ref != context.business_time.clock_ref
                or current.business_time.offset < context.business_time.offset):
            raise AgentClientError('Current bid reading substitutes its original actor, contract, scope or clock')
        reading.check_method_context(current, 'CONTRACTOR-A02')
        try:
            registration = self.registry.get('CONTRACTOR-A02')
            if not registration.implemented or registration.skill is None:
                raise AgentClientError('Tender proposal requires the actual bound A02 processor and Skill')
            action_input = registration.contract.validate_input(saved.action_input)
            result = registration.contract.result_adapter.validate_python(saved.result)
            if result.kind != 'completed' or result.payload.choice not in {'submit_bid', 'decline_bid'}:
                raise AgentClientError('Noncompleted A02 stays pending; it cannot become a legacy refusal')
            registration.contract.validate_decision(action_input, result.payload)
            for ref in [*walk_references(action_input), *walk_references(result.payload)]:
                reading.resolve(ref)
            input_hash = task_digest(action_input.model_dump(mode='json'))
            result_hash = task_digest(result.model_dump(mode='json'))
            audit = deepcopy(saved.audit)
            expected_audit = {'schema_version': 'action-audit.v1', 'run_id': self.run_id,
                'action_id': 'CONTRACTOR-A02', 'operation_id': context.operation_id,
                'input_version': context.contract_ref.version, 'input_sha256': input_hash,
                'result_kind': 'completed', 'result_sha256': result_hash,
                'processor_id': registration.processor_id}
            if (not isinstance(audit, dict) or any(audit.get(k) != v for k, v in expected_audit.items())
                    or audit.get('stages') != {'input_validation': 'accepted', 'authorization': 'accepted', 'processor': 'bound'}
                    or audit.get('reading', {}).get('status') != 'accepted'
                    or audit.get('reading', {}).get('source_mode') != 'formal'
                    or audit.get('reading', {}).get('read_token') != context.read_token):
                raise AgentClientError('Saved bid lacks its exact successful original formal action audit')
            if audit.get('skill') != {'id': registration.skill.manifest.skill_id,
                    'version': registration.skill.manifest.skill_version,
                    'sha256': registration.skill.manifest.skill_sha256}:
                raise AgentClientError('Saved bid Skill changed; evaluate the current execution version explicitly')
            mapping_ref = Reference.model_validate(saved.mapping_ref)
            mapping = reading.resolve(mapping_ref)
            if not isinstance(mapping, GbaTenderProposalMappingView) or mapping.ref != mapping_ref:
                raise AgentClientError('Tender proposal requires its concrete sourced indicator mapping')
            project = request.inputs['project']
            if (not isinstance(project, dict) or mapping.project_id != project.get('project_id')
                    or mapping.run_id != self.run_id or mapping.simulation_id != self.simulation_id
                    or mapping.organization_id != reading.organization_id or mapping.scope != context.scope
                    or mapping.package_ref != action_input.package_ref
                    or mapping.request_sha256 != task_digest(request.model_dump(mode='json'))
                    or mapping.context_sha256 != task_digest(context.model_dump(mode='json'))
                    or mapping.input_sha256 != input_hash or mapping.result_sha256 != result_hash):
                raise AgentClientError('Tender mapping changes original request, project, package or bid version')
            now = current.business_time
            if (mapping.available_at.clock_ref != now.clock_ref or mapping.available_at.offset > now.offset
                    or not mapping.effective_window.contains(now)
                    or mapping.authored_at.clock_ref != now.clock_ref
                    or mapping.authored_at.offset > mapping.available_at.offset
                    or not mapping.effective_window.contains(mapping.authored_at)):
                raise AgentClientError('Tender professional indicators are not currently available and valid')
            grant = reading.resolve(mapping.author_authority_ref)
            assignment = reading.resolve(mapping.author_function_ref)
            if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                    or mapping.author_organization_id != reading.organization_id
                    or grant.organization_id != mapping.author_organization_id
                    or grant.actor_id != mapping.author_actor_id or grant.function_ref != mapping.author_function_ref
                    or assignment.function_ref != mapping.author_function_ref
                    or mapping.author_action_id not in grant.action_ids
                    or not grant.validity.contains(mapping.authored_at)
                    or not any(scope_covers(scope, mapping.scope) for scope in grant.scopes)):
                raise AgentClientError('Tender mapping lacks its original independent author authority')

            def evidence(ref):
                value = reading.resolve(ref)
                if (not isinstance(value, EvidenceRecord)
                        or value.effective_window is not None and not value.effective_window.contains(now)):
                    raise AgentClientError('Tender proposal lacks current authorized evidence')
                return value

            for ref in [*mapping.evidence_refs, *grant.basis_refs, *assignment.basis_refs]:
                evidence(ref)
            original = evidence(mapping.result_evidence_ref)
            if original.content_hash != result_hash or original.basis_kind != 'observed':
                raise AgentClientError('Tender indicator mapping lacks the actually observed original bid result')

            def number(value):
                amount = Decimal(value)
                converted = float(amount)
                if not math.isfinite(converted) or Decimal(str(converted)) != amount:
                    raise AgentClientError('Legacy number transport would lose the declared decimal value')
                return converted

            def indicator(state, unit, maximum=None):
                if not isinstance(state, Known):
                    raise AgentClientError('Missing professional indicators cannot be invented for the old interface')
                value = state.value
                amount = Decimal(value.value)
                if value.unit != unit or amount < 0 or maximum is not None and amount > maximum:
                    raise AgentClientError('Tender indicator has unsupported units or bounds')
                evidence(value.basis_ref)
                return number(value.value)

            accepted = result.payload.choice == 'submit_bid'
            if accepted:
                price = result.payload.bid.price
                validity = reading.resolve(result.payload.bid.validity_ref)
                if not isinstance(validity, TimeWindow) or not validity.contains(now):
                    raise AgentClientError('Original bid is no longer valid at the current read point')
            elif isinstance(mapping.declined_reference_price, Known):
                price = mapping.declined_reference_price.value
            else:
                raise AgentClientError('Legacy refusal requires an independently sourced reference price')
            if price.currency != mapping.legacy_currency or Decimal(price.value) < 0:
                raise AgentClientError('Tender price changes the explicitly sourced legacy currency')
            evidence(price.basis_ref)
            probability = indicator(mapping.bid_probability, 'probability', Decimal(1))
            data = {'bid_probability': probability, 'bid_price': number(price.value),
                    'expected_profit': indicator(mapping.expected_profit, 'fraction'),
                    'risk_level': indicator(mapping.risk_level, 'fraction', Decimal(1)),
                    'decline_reason': result.payload.note}
            response = AgentProposalResponseV1(request_id=request.request_id,
                action_type=result.payload.choice, accepted=accepted,
                utility=indicator(mapping.utility, 'score', Decimal(1)), probability=probability,
                reason=result.payload.note, data=data, factors={'micro_action_id': 'CONTRACTOR-A02',
                    'regional_friction': indicator(mapping.regional_friction, 'fraction', Decimal(1)),
                    'project_id': mapping.project_id, 'proposal_tick': request.metadata.get('tick'),
                    'proposal_request_sha256': mapping.request_sha256,
                    'micro_result_sha256': result_hash, 'micro_input_sha256': input_hash,
                    'indicator_mapping_sha256': task_digest(mapping.model_dump(mode='json')),
                    'original_audit_sha256': task_digest(audit)})
            validate_operation_response(contract, response, request.inputs)
            if self.revalidate(request=request.model_copy(deep=True),
                    original_context=context.model_copy(deep=True), current_context=current.model_copy(deep=True),
                    action_input=action_input.model_copy(deep=True), result=result.model_copy(deep=True),
                    reading=reading) is not None:
                raise AgentClientError('Fresh original bid validation must explicitly succeed before exposure')
            return response
        finally:
            reading.recheck()

    def evidence(self):
        return {'component': 'integration.bindings.gba_v1_tender_proposal.GbaTenderProposalAdapter',
                'version': self.VERSION, 'run_id': self.run_id, 'simulation_id': self.simulation_id,
                'handler_role': self.HANDLER_KEY[0], 'handler_operation': self.HANDLER_KEY[1],
                'action_id': 'CONTRACTOR-A02', 'status': 'implemented_unverified',
                'limitations': ['Host must supply exact persisted original bid and current authorized indicator mapping.',
                                'Old proposal only; later bounded final decision and simulation-owned effects remain separate.',
                                'No A01 intention endpoint, new action submission/query endpoint or automatic model call.']}
