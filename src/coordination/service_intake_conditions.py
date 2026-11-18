"""Authenticate original professional service terms and actual deferred-policy revision."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, Reference
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.service_objects import (
    ServiceRequestView, ServiceTermsView, ServiceFeeBasisView, ServiceResourceCalendarView, ServiceIntakeCapabilityView,
)
from src.actions.roles.architect import assess_service_request
from src.actions.roles.engineer import assess_service_request as assess_engineer_service_request
from src.actions.roles.qs import assess_service_request as assess_qs_service_request
from src.actions.contracts.qs_objects import QSConflictCheckView
from src.actions.contracts.engineer_objects import (
    EngineerServiceRequestView, EngineerServiceTermsView, EngineerIntakeCapabilityView, EngineerResourceCalendarView,
)
from src.actions.roles.service_intake import recheck_original_service_policy_wait
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


CODE = 'service_terms_or_provider_policy_reassessed'


@dataclass(frozen=True)
class ServiceIntakeConditionReading(ContractorCloseoutConditionReading):
    contract: ActionContract | None = None


def check_architect_intake_revision(check, selected, validate_relation):
    return _check_intake_revision(check, selected, validate_relation, action_id='ARCHITECT-A02', role='Architect',
        processor=assess_service_request, request_schema=ServiceRequestView, terms_schema=ServiceTermsView,
        capability_schema=ServiceIntakeCapabilityView, capacity_schema=ServiceResourceCalendarView)


def check_engineer_intake_revision(check, selected, validate_relation):
    return _check_intake_revision(check, selected, validate_relation, action_id='ENGINEER-A02', role='Engineer',
        processor=assess_engineer_service_request, request_schema=EngineerServiceRequestView,
        terms_schema=EngineerServiceTermsView, capability_schema=EngineerIntakeCapabilityView,
        capacity_schema=EngineerResourceCalendarView)


def check_qs_intake_revision(check, selected, validate_relation):
    return _check_intake_revision(check, selected, validate_relation, action_id='QS-A02', role='QS',
        processor=assess_qs_service_request, request_schema=ServiceRequestView, terms_schema=ServiceTermsView,
        capability_schema=ServiceIntakeCapabilityView, capacity_schema=ServiceResourceCalendarView)


def _check_intake_revision(check, selected, validate_relation, *, action_id, role, processor,
        request_schema, terms_schema, capability_schema, capacity_schema):
    source = check.source['identity']
    if (source['action_id'] != action_id or source['role'] != role or source['purpose'] != 'action'
            or check.condition.condition_code != CODE or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('ServiceTerms', 'FeeBasis')
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ServiceIntakeConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Intake recovery requires original terms/policy wait and private provider')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.operation_id == source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original.contract_ref
            or context.contract_ref.id != action_id or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Intake recovery changes original snapshot, private scope, time or actual current authority')
    reading.check_method_context(context, action_id)
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != action_id or contract.role != role:
        raise TaskConflict('Intake recovery lacks its actual registered original action contract')
    original_input, current_input = contract.validate_input(raw), contract.validate_input(current_raw)

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Intake recovery lacks exact typed original/current sources')
        return row

    def physical(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Intake recovery repeats physical requirement or resource occupation histories')
        return result

    versions = []
    for values in (original_input, current_input):
        request = read(values.request_ref, request_schema)
        terms = read(values.terms_ref, terms_schema)
        policy_ref = getattr(values, 'price_basis_ref', None) or request.fee_basis_ref
        if policy_ref is None:
            raise TaskConflict('Intake recovery loses the original request fee policy')
        policy = read(policy_ref, ServiceFeeBasisView)
        capacity = read(values.capacity_ref, capacity_schema)
        capability = read(values.capability_ref, capability_schema)
        if (request.provider_organization_id != source['organization_id'] or any(row.organization_id != source['organization_id']
                for row in (policy, capacity, capability)) or terms.request_ref != request.ref or request.offered_terms_ref != terms.ref
                or values.scope != context.scope):
            raise TaskConflict('Intake recovery borrows another provider, request, terms, policy or business scope')
        versions.append(dict(request=request, terms=terms, policy=policy, capacity=capacity, capability=capability))
    old, current = versions
    if any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field in versions[0]):
        raise TaskConflict('Intake recovery substitutes original physical service request, terms, capability or calendar')
    if any(getattr(old['request'], field) != getattr(current['request'], field) for field in
            ('scope', 'provider_id', 'provider_organization_id', 'client_id', 'client_organization_id', 'payer_id', 'payer_organization_id')):
        raise TaskConflict('Intake recovery changes original service scope, provider, client or independent payer')
    if any(getattr(old['terms'], field) != getattr(current['terms'], field) for field in
            ('scope', 'provider_id', 'client_id', 'payer_id', 'relation')):
        raise TaskConflict('Intake recovery converts original service relationship or terms parties')
    if not set(physical(old['terms'].deliverable_requirement_refs)) <= set(physical(current['terms'].deliverable_requirement_refs)):
        raise TaskConflict('Intake recovery drops original deliverable requirement history')
    if role == 'Engineer':
        for field in ('discipline_codes', 'function_code'):
            before, after = getattr(old['terms'], field), getattr(current['terms'], field)
            if isinstance(before, Known) and before != after:
                raise TaskConflict('Engineer intake recovery rewrites original known discipline or professional function')
        before, after = original_input.independence_requirement_ref, current_input.independence_requirement_ref
        if (before is not None and (after is None or before.key()[:2] != after.key()[:2])
                or old['terms'].independence_requirement_ref != before
                or current['terms'].independence_requirement_ref != after):
            raise TaskConflict('Engineer intake recovery replaces or removes original independent-review requirement')
    conflicts = []
    if role == 'QS':
        before, after = original_input.conflict_check_ref, current_input.conflict_check_ref
        if before is not None and (after is None or before.key()[:2] != after.key()[:2]):
            raise TaskConflict('QS intake recovery drops or substitutes the original conflict-check identity')
        for values, version, at in ((original_input, old, original.business_time), (current_input, current, context.business_time)):
            if values.conflict_check_ref is not None:
                conflict = read(values.conflict_check_ref, QSConflictCheckView)
                if (conflict.request_ref != version['request'].ref or conflict.organization_id != source['organization_id']
                        or conflict.scope != values.scope or conflict.checked_at.clock_ref != at.clock_ref
                        or conflict.checked_at.offset > at.offset):
                    raise TaskConflict('QS intake recovery borrows another original conflict check or future result')
                conflicts.append(conflict.model_dump(mode='json'))
    historical_options = ({'original_processor': assess_qs_service_request} if role == 'QS' else
        {'role_key': 'engineer', 'accepted_field': 'terms_ref'} if role == 'Engineer' else {})
    original_gate = recheck_original_service_policy_wait(original, original_input, reading, **historical_options)
    if (original_gate.get('resume_condition', {}).get('condition_code') != CODE
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Intake wait differs from the actual original offered terms and deferred policy')
    history = current['terms']
    if selected.history_ref != history.ref or (old['terms'].ref, old['policy'].ref) != tuple(check.condition.object_refs):
        raise TaskConflict('Intake query is not the exact actual original/current terms and fee policy')
    policy = current['policy']
    if not isinstance(policy.new_work_policy, Known) or policy.new_work_policy.value == 'defer':
        return 'waiting', None
    if policy.ref == old['policy'].ref:
        raise TaskConflict('Intake recovery rewrites the immutable original deferred policy version')
    if not policy.effective_window.contains(context.business_time):
        return 'unavailable', None
    evidence = []
    for evidence_ref in policy.evidence_refs:
        row = reading.resolve(evidence_ref)
        if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Intake recovery requires actual observed independent policy revision evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    occupations = []
    old_commitments = {row.commitment_ref.key()[:2]: row for row in old['capacity'].commitments}
    new_commitments = {row.commitment_ref.key()[:2]: row for row in current['capacity'].commitments}
    physical([row.commitment_ref for row in old['capacity'].commitments])
    physical([row.commitment_ref for row in current['capacity'].commitments])
    for key, before in old_commitments.items():
        after = new_commitments.get(key)
        if after is not None and before.resource_ref.key()[:2] != after.resource_ref.key()[:2]:
            raise TaskConflict('Intake recovery aliases the original occupied physical resource')
        if after is None or before.quantity != after.quantity or before.window != after.window:
            occupations.append(dict(original=before.model_dump(mode='json'), current=None if after is None else after.model_dump(mode='json')))
    current_result = processor(context, current_input, reading)
    if current_result.get('kind') != 'completed':
        return 'waiting', None
    contract.validate_decision(current_input, current_result['payload'])
    resolution = dict(schema_version=role.lower() + '-intake-policy-resolution.v1', condition_code=CODE,
        history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_request=old['request'].model_dump(mode='json'), current_request=current['request'].model_dump(mode='json'),
        original_terms=old['terms'].model_dump(mode='json'), current_terms=history.model_dump(mode='json'),
        original_policy=old['policy'].model_dump(mode='json'), current_policy=policy.model_dump(mode='json'),
        original_capacity=old['capacity'].model_dump(mode='json'), current_capacity=current['capacity'].model_dump(mode='json'),
        occupation_changes=occupations, evidence=evidence, sources=reading.evidence(),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'),
        current_result=contract.result_adapter.validate_python(current_result).model_dump(mode='json'))
    if role == 'QS':
        resolution['conflict_checks'] = conflicts
    if occupations:
        ledger_evidence = []
        for evidence_ref in current['capacity'].evidence_refs:
            row = reading.resolve(evidence_ref)
            if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                raise TaskConflict('Intake recovery cannot infer capacity release from omitted/reduced occupations')
            if row.effective_window is not None and not row.effective_window.contains(context.business_time):
                return 'unavailable', None
            ledger_evidence.append(row.model_dump(mode='json'))
        ledger = dict(schema_version=role.lower() + '-intake-occupation-resolution.v1', occupation_changes=occupations,
            original_capacity=resolution['original_capacity'], current_capacity=resolution['current_capacity'],
            evidence=ledger_evidence, sources=reading.evidence())
        if validate_relation(source_identity=deepcopy(source), condition_code=CODE, resolution=deepcopy(ledger),
                context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Intake recovery lacks actual independent native occupation release/adjustment history')
    if validate_relation(source_identity=deepcopy(source), condition_code=CODE, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Intake recovery lacks native service/terms/policy revision authority and remaining-duty authentication')
    return 'ready', resolution


def architect_original_intake_profile(read_current, validate_relation, condition_code=CODE):
    return _intake_profile(read_current, validate_relation, condition_code, action_id='ARCHITECT-A02',
        checker=check_architect_intake_revision)


def engineer_original_intake_profile(read_current, validate_relation, condition_code=CODE):
    return _intake_profile(read_current, validate_relation, condition_code, action_id='ENGINEER-A02',
        checker=check_engineer_intake_revision)


def qs_original_intake_profile(read_current, validate_relation, condition_code=CODE):
    return _intake_profile(read_current, validate_relation, condition_code, action_id='QS-A02',
        checker=check_qs_intake_revision)


def _intake_profile(read_current, validate_relation, condition_code, *, action_id, checker):
    if condition_code != CODE or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Intake recovery requires original guarded sources and independent native validator')
    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return checker(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()
    return ConditionProfile(action_id, CODE, '1', frozenset({'dependency_change'}), evaluate)
