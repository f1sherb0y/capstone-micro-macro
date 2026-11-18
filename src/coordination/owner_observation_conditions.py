"""Rejudge original Owner screening waits without reserving capacity or creating cases."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.owner_objects import (
    OwnerCaseView, OwnerDemandObservationView, OwnerManagementCapacityView,
    OwnerObjectiveView, OwnerOpportunityView,
)
from src.actions.roles.owner import observe_opportunities
from src.coordination.continuations import ConditionProfile
from src.coordination.owner_saved_wait_conditions import OwnerSavedWaitConditionReading, read_owner_saved_wait
from src.coordination.tasks import TaskConflict


CODE = 'management_capacity_revalidated'


@dataclass(frozen=True)
class OwnerObservationConditionReading(OwnerSavedWaitConditionReading):
    """Actual saved A01 capacity wait and current authorized screening input."""


def check_owner_observation_capacity(check, selected, validate_relation):
    old_input, current_input, saved = read_owner_saved_wait(check, selected, validate_relation,
        action_id='OWN-A01', code=CODE, kinds=('ManagementCapacity',),
        reading_type=OwnerObservationConditionReading)
    source = check.source['identity']
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    contract = selected.contract

    def physical(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Owner screening recovery aliases physical observations, cases or commitments')
        return result

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Owner screening recovery lacks exact typed original/current source versions')
        return row

    versions = []
    for values, at, invocation_scope in ((old_input, original.business_time, original.scope),
            (current_input, context.business_time, context.scope)):
        if values.scope_ref != invocation_scope:
            raise TaskConflict('Owner screening recovery changes its authorized input scope')
        objective = read(values.objective_ref, OwnerObjectiveView)
        capacity = read(values.capacity_ref, OwnerManagementCapacityView)
        if objective.organization_id != source['organization_id'] or capacity.organization_id != source['organization_id']:
            raise TaskConflict('Owner screening recovery borrows another owner objective or management pool')
        opportunities = {key: read(ref, OwnerOpportunityView) for key, ref in physical(values.opportunity_refs).items()}
        observation_refs = {ref.key(): ref for ref in (*values.observations,
            *(ref for row in opportunities.values() for ref in row.observation_refs))}
        observations = {key: read(ref, OwnerDemandObservationView)
            for key, ref in physical(list(observation_refs.values())).items()}
        cases = {key: read(ref, OwnerCaseView) for key, ref in physical(values.existing_case_refs).items()}
        if any(row.organization_id != source['organization_id'] for row in cases.values()):
            raise TaskConflict('Owner screening recovery changes its private case owner')
        learned = [row.learned_at for row in (*opportunities.values(), *observations.values())]
        learned.extend(row.updated_at for row in cases.values())
        if any(point.clock_ref != at.clock_ref or point.offset > at.offset for point in learned):
            raise TaskConflict('Owner screening recovery imports sources unavailable at their original/current read time')
        versions.append(dict(objective=objective, capacity=capacity, opportunities=opportunities,
            observations=observations, cases=cases))
    old, current = versions
    if (old_input.capacity_ref != check.condition.object_refs[0] or current_input.capacity_ref != selected.history_ref
            or old_input.capacity_ref.key()[:2] != current_input.capacity_ref.key()[:2]
            or old_input.objective_ref.key()[:2] != current_input.objective_ref.key()[:2]):
        raise TaskConflict('Owner screening recovery substitutes its original capacity pool or objective')
    for name in ('observations', 'opportunity_refs', 'existing_case_refs'):
        if not set(physical(getattr(old_input, name))) <= set(physical(getattr(current_input, name))):
            raise TaskConflict('Owner screening recovery drops its original supplied signals, opportunities or cases')
    for name in ('objective', 'capacity'):
        before, after = old[name], current[name]
        if before.ref == after.ref and before != after:
            raise TaskConflict('Owner screening recovery rewrites an immutable source version')
    for name in ('observations', 'opportunities', 'cases'):
        if not set(old[name]) <= set(current[name]):
            raise TaskConflict('Owner screening recovery loses original associated information')
        for key, before in old[name].items():
            after = current[name][key]
            if before.ref == after.ref and before != after:
                raise TaskConflict('Owner screening recovery rewrites an immutable private information version')
    loads = []
    original_loads = {row.commitment_ref.key()[:2]: row for row in old['capacity'].commitments}
    current_loads = {row.commitment_ref.key()[:2]: row for row in current['capacity'].commitments}
    for key, before in original_loads.items():
        after = current_loads.get(key)
        if after is not None and before.commitment_ref == after.commitment_ref and before != after:
            raise TaskConflict('Owner screening recovery rewrites the same native resource commitment version')
        loads.append({'original': before.model_dump(mode='json'),
            'current': None if after is None else after.model_dump(mode='json')})
    # A disappeared/changed commitment is evidence to authenticate natively,
    # never a micro decision to release resources. Keep every original load.
    before_methods = reading.method_evidence()
    original_gate = observe_opportunities(original, old_input, reading)
    if (reading.method_evidence() != before_methods
            or original_gate.get('resume_condition', {}).get('condition_code') != CODE
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Owner screening wait differs from its actual original processor gate')
    evidence = []
    capacity = current['capacity']
    actual_refs = list(capacity.evidence_refs)
    if capacity.total.state == 'known':
        actual_refs.append(capacity.total.value.basis_ref)
    actual_refs.extend(load.quantity.basis_ref for load in capacity.commitments)
    for ref in dict.fromkeys(actual_refs):
        row = read(ref, EvidenceRecord)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Formal screening recovery requires observed actual management capacity evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    current_result = observe_opportunities(context, current_input, reading)
    if current_result.get('kind') != 'completed':
        return 'waiting', None
    contract.validate_decision(current_input, current_result['payload'])

    def dump(version):
        return {name: ({str(key): row.model_dump(mode='json') for key, row in value.items()}
            if isinstance(value, dict) else value.model_dump(mode='json')) for name, value in version.items()}

    resolution = dict(schema_version='owner-observation-capacity-resolution.v1', condition_code=CODE,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_action_input=raw, action_input=current_raw, original_record=saved, original_sources=dump(old), current_sources=dump(current),
        original_commitments=loads, evidence=evidence, sources=reading.evidence(),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'),
        current_result=contract.result_adapter.validate_python(current_result).model_dump(mode='json'))
    if validate_relation(source_identity=deepcopy(source), condition_code=CODE, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Owner screening recovery lacks native capacity/commitment and current information authentication')
    return 'ready', resolution


def owner_original_observation_profile(read_current, validate_relation, condition_code=CODE):
    if condition_code != CODE or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Owner screening recovery requires actual guarded sources and native authentication')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_owner_observation_capacity(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('OWN-A01', CODE, '1', frozenset({'dependency_change'}), evaluate)
