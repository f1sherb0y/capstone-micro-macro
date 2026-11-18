"""Authenticate actual policy revisions without discarding received inquiries or occupation history."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_objects import (
    SupplyScreeningProfileView, SupplierCapabilityView, SupplierCapacityView, SupplyInquiryView,
)
from src.actions.roles.supplier import screen_demand, recheck_original_supplier_policy_wait
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


CODE = 'supplier_policy_revision'


@dataclass(frozen=True)
class SupplierPolicyConditionReading(ContractorCloseoutConditionReading):
    contract: ActionContract | None = None


def check_supplier_policy_revision(check, selected, validate_relation):
    source = check.source['identity']
    if (source['action_id'] != 'SUPPLIER-A01' or source['role'] != 'Supplier' or source['purpose'] != 'action'
            or check.condition.condition_code != CODE or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('SupplyScreeningProfile',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, SupplierPolicyConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Policy recovery requires original typed defer wait and private Supplier')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.operation_id == source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original.contract_ref
            or context.contract_ref.id != 'SUPPLIER-A01' or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Policy recovery changes original snapshot, private scope, time or actual authority')
    reading.check_method_context(context, 'SUPPLIER-A01')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'SUPPLIER-A01' or contract.role != 'Supplier':
        raise TaskConflict('Policy recovery lacks its actual registered original action contract')
    original_input, current_input = contract.validate_input(raw), contract.validate_input(current_raw)

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Policy recovery lacks exact typed original/current sources')
        return row

    def physical(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Policy recovery repeats physical inquiries, markets or resource occupations')
        return result

    versions = []
    for values in (original_input, current_input):
        profile = read(values.screening_profile_ref, SupplyScreeningProfileView)
        capability = read(values.capability_ref, SupplierCapabilityView)
        capacity = read(values.capacity_ref, SupplierCapacityView)
        if any(row.organization_id != source['organization_id'] for row in (profile, capability, capacity)):
            raise TaskConflict('Policy recovery borrows another Supplier policy, capability or capacity')
        versions.append(dict(profile=profile, capability=capability, capacity=capacity))
    old, current = versions
    if any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field in ('profile', 'capability', 'capacity')):
        raise TaskConflict('Policy recovery substitutes original physical policy, capability or resource calendar')
    for field in ('inquiry_refs', 'market_refs'):
        if not set(physical(getattr(original_input, field))) <= set(physical(getattr(current_input, field))):
            raise TaskConflict('Policy recovery discards original received inquiries or market observations')
    inquiries = []
    actual_inquiries = physical(current_input.inquiry_refs)
    for ref in original_input.inquiry_refs:
        before = read(ref, SupplyInquiryView)
        after = read(actual_inquiries[ref.key()[:2]], SupplyInquiryView)
        if (before.scope != after.scope or before.buyer_id != after.buyer_id
                or before.recipient_organization_id != after.recipient_organization_id
                or not set(physical([line.requirement_ref for line in before.lines])) <=
                    set(physical([line.requirement_ref for line in after.lines]))):
            raise TaskConflict('Policy recovery substitutes original inquiry buyer, scope, recipient organization or line history')
        inquiries.append(dict(original=before.model_dump(mode='json'), current=after.model_dump(mode='json')))
    original_gate = recheck_original_supplier_policy_wait(original, original_input, reading)
    if (original_gate.get('resume_condition', {}).get('condition_code') != CODE
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Policy wait differs from original deferred policy and exact received inquiry set')
    history = current['profile']
    if (selected.history_ref != history.ref or old['profile'].ref != check.condition.object_refs[0]
            or history.ref.key()[:2] != old['profile'].ref.key()[:2]):
        raise TaskConflict('Policy query is not the actual original/current selected policy')
    if history.policy == 'defer_new_work':
        return 'waiting', None
    if history.ref == old['profile'].ref:
        raise TaskConflict('Policy revision rewrites an immutable original source version')
    if not history.effective_window.contains(context.business_time):
        return 'unavailable', None
    evidence = []
    for evidence_ref in history.evidence_refs:
        row = reading.resolve(evidence_ref)
        if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Policy recovery requires actual observed independent policy revision evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    old_commitments = {row.commitment_ref.key()[:2]: row for row in old['capacity'].commitments}
    new_commitments = {row.commitment_ref.key()[:2]: row for row in current['capacity'].commitments}
    physical([row.commitment_ref for row in old['capacity'].commitments])
    physical([row.commitment_ref for row in current['capacity'].commitments])
    occupation_changes = []
    for key, before in old_commitments.items():
        after = new_commitments.get(key)
        if after is not None and before.resource_ref.key()[:2] != after.resource_ref.key()[:2]:
            raise TaskConflict('Policy recovery aliases an original occupied physical resource')
        if after is None or before.quantity != after.quantity or before.window != after.window:
            occupation_changes.append(dict(original=before.model_dump(mode='json'),
                current=None if after is None else after.model_dump(mode='json')))
    current_result = screen_demand(context, current_input, reading)
    if current_result.get('kind') != 'completed':
        return 'waiting', None
    contract.validate_decision(current_input, current_result['payload'])
    resolution = dict(schema_version='supplier-policy-revision-resolution.v1', condition_code=CODE,
        history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_policy=old['profile'].model_dump(mode='json'), current_policy=history.model_dump(mode='json'),
        original_capacity=old['capacity'].model_dump(mode='json'), current_capacity=current['capacity'].model_dump(mode='json'),
        inquiries=inquiries, occupation_changes=occupation_changes, evidence=evidence, sources=reading.evidence(),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'),
        current_result=contract.result_adapter.validate_python(current_result).model_dump(mode='json'))
    if occupation_changes:
        occupation_evidence = []
        for evidence_ref in current['capacity'].evidence_refs:
            row = reading.resolve(evidence_ref)
            if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                raise TaskConflict('Policy recovery cannot infer resource release from omitted or reduced occupations')
            if row.effective_window is not None and not row.effective_window.contains(context.business_time):
                return 'unavailable', None
            occupation_evidence.append(row.model_dump(mode='json'))
        ledger_resolution = dict(schema_version='supplier-policy-occupation-history-resolution.v1',
            occupation_changes=occupation_changes, original_capacity=resolution['original_capacity'],
            current_capacity=resolution['current_capacity'], evidence=occupation_evidence, sources=reading.evidence())
        if validate_relation(source_identity=deepcopy(source), condition_code=CODE, resolution=deepcopy(ledger_resolution),
                context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Policy recovery lacks independent native occupation release/adjustment history')
    if validate_relation(source_identity=deepcopy(source), condition_code=CODE, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Policy recovery lacks native policy authority/received inquiry revisions/remaining duty authentication')
    return 'ready', resolution


def supplier_original_policy_profile(read_current, validate_relation, condition_code=CODE):
    if condition_code != CODE or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Policy recovery requires original guarded source query and independent native validator')
    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_supplier_policy_revision(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()
    return ConditionProfile('SUPPLIER-A01', CODE, '1', frozenset({'dependency_change'}), evaluate)
