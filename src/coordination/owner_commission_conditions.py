"""Recover original service procurement waits without forming an appointment."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.owner_commission_objects import (
    CommissionProfileView, CommissionServiceScopeView, CommissionManagementView, CommissionResourceView,
)
from src.actions.roles.owner_commission import commission_services
from src.coordination.continuations import ConditionProfile
from src.coordination.owner_closeout_conditions import same_closeout_scope
from src.coordination.owner_saved_wait_conditions import OwnerSavedWaitConditionReading, read_owner_saved_wait
from src.coordination.tasks import TaskConflict


CODE = 'owner.commission.inputs_changed'


@dataclass(frozen=True)
class OwnerCommissionConditionReading(OwnerSavedWaitConditionReading):
    """Actual saved A04 result and a separately authorized current procurement."""


def check_owner_commission_conditions(check, selected, validate_relation):
    old_input, current_input, saved = read_owner_saved_wait(check, selected, validate_relation,
        action_id='OWN-A04', code=CODE, kinds=('ProcurementProfile', 'ServiceScope', 'ManagementCapacity'),
        reading_type=OwnerCommissionConditionReading)
    source = check.source['identity']
    context, original, reading = selected.context, selected.original_context, selected.reading
    old_sources = {tuple(row['ref'][key] for key in ('kind', 'id', 'version')) for row in saved['source_reading']}
    fields = ('procurement_profile_ref', 'service_scope_ref', 'capacity_ref')
    if (tuple(getattr(old_input, name) for name in fields) != tuple(check.condition.object_refs)
            or selected.history_ref != current_input.procurement_profile_ref
            or any(getattr(old_input, name).key()[:2] != getattr(current_input, name).key()[:2] for name in fields)
            or not same_closeout_scope(old_input.scope_ref, current_input.scope_ref)):
        raise TaskConflict('Owner commission recovery substitutes its original procurement, service, capacity pool or scope')

    def physical(refs):
        rows = {ref.key()[:2]: ref for ref in refs}
        if len(rows) != len(refs):
            raise TaskConflict('Owner commission recovery aliases physical providers, offers or shared resources')
        return rows

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Owner commission recovery requires exact typed source versions')
        point = getattr(row, 'available_at', None)
        if point is not None and (point.clock_ref != at.clock_ref or point.offset > at.offset):
            raise TaskConflict('Owner commission recovery imports information unavailable at its read time')
        return row

    for name in ('candidate_provider_refs', 'candidates'):
        if not set(physical(getattr(old_input, name))) <= set(physical(getattr(current_input, name))):
            raise TaskConflict('Owner commission recovery drops originally supplied providers or received offers')
    versions = []
    for values, invocation in ((old_input, original), (current_input, context)):
        at = invocation.business_time
        profile = read(values.procurement_profile_ref, CommissionProfileView, at)
        service = read(values.service_scope_ref, CommissionServiceScopeView, at)
        capacity = read(values.capacity_ref, CommissionManagementView, at)
        if (profile.organization_id != source['organization_id'] or service.employer_organization_id != source['organization_id']
                or capacity.organization_id != source['organization_id'] or profile.service_scope_ref != service.ref
                or profile.scope_ref != values.scope_ref or service.scope_ref != values.scope_ref):
            raise TaskConflict('Owner commission recovery changes its own service version or management owner')
        pools = {}
        for key, ref in physical(capacity.resource_refs).items():
            row = None if values is old_input and ref.key() not in old_sources else read(ref, CommissionResourceView, at)
            if row is not None and (row.organization_id != source['organization_id'] or row.as_of != at):
                raise TaskConflict('Owner commission recovery borrows another organization resources or stale load')
            pools[key] = row
        versions.append(dict(profile=profile, service=service, capacity=capacity, pools=pools))
    old, current = versions
    if (old['service'].scope_ref.kind != current['service'].scope_ref.kind
            or not same_closeout_scope(old['service'].scope_ref, current['service'].scope_ref)):
        raise TaskConflict('Owner commission recovery imports unrelated service work')
    commitments = []
    for key, before in old['pools'].items():
        after = current['pools'].get(key)
        after_loads = {} if after is None else {load.ref.key()[:2]: load for load in after.commitments}
        for load in before.commitments if before is not None else ():
            updated = after_loads.get(load.ref.key()[:2])
            if updated is not None and updated.ref == load.ref and updated != load:
                raise TaskConflict('Owner commission recovery rewrites the same native commitment version')
            commitments.append({'resource_ref': before.ref.model_dump(mode='json'),
                'original': load.model_dump(mode='json'), 'current': None if updated is None else updated.model_dump(mode='json')})
    result = commission_services(context, current_input, reading)
    if result.get('kind') != 'completed':
        return 'waiting', None
    selected.contract.validate_decision(current_input, result['payload'])
    actual_evidence = []
    for pool in current['pools'].values():
        values = [load.quantity for load in pool.commitments]
        if pool.total.state == 'known':
            values.append(pool.total.value)
        for value in values:
            record = read(value.basis_ref, EvidenceRecord, context.business_time)
            if (record.source_kind == 'synthetic' or record.basis_kind != 'observed'
                    or record.effective_window is not None and not record.effective_window.contains(context.business_time)):
                raise TaskConflict('Formal commission recovery requires observed actual resources and commitments')
            actual_evidence.append(record.model_dump(mode='json'))
    resolution = dict(schema_version='owner-commission-conditions-resolution.v1', condition_code=CODE,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_action_input=deepcopy(selected.original_action_input), action_input=deepcopy(selected.action_input),
        original_record=saved, original_service=old['service'].model_dump(mode='json'),
        current_service=current['service'].model_dump(mode='json'), original_commitments=commitments,
        original_management=old['capacity'].model_dump(mode='json'), current_management=current['capacity'].model_dump(mode='json'),
        actual_evidence=actual_evidence, sources=reading.evidence(), methods=reading.method_evidence(),
        current_result=selected.contract.result_adapter.validate_python(result).model_dump(mode='json'))
    if validate_relation(source_identity=deepcopy(source), condition_code=CODE, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Owner commission recovery lacks native original-audit, service, offer and resource authentication')
    return 'ready', resolution


def owner_original_commission_profile(read_current, validate_relation, condition_code=CODE):
    if condition_code != CODE or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Owner commission recovery requires guarded original/current sources and native validation')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_owner_commission_conditions(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('OWN-A04', CODE, '1', frozenset({'dependency_change'}), evaluate)
