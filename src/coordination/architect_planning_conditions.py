"""Authenticate original design task histories before resuming actual A04 planning."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.architect_planning_objects import (
    ArchitectPlanningProfileView, ArchitectPlanningCalendarView, ArchitectPlanningTaskView,
    ArchitectPlanningEstimateView, ArchitectPlanningWorkFactView, ArchitectPlanningDependencyView,
    ArchitectPlanningAllocationView, ArchitectPlanningReservationView, ArchitectAppointmentView, QSWorkPlanView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.service_objects import ServiceTermsView
from src.actions.roles.architect_planning import plan_design_work, recheck_original_architect_planning_capacity
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


TASK_CODE = 'original_design_tasks_waiting_or_already_invested'
CAPACITY_CODE = 'shared_design_personnel_capacity_unavailable'
_CODES = {TASK_CODE, CAPACITY_CODE}


@dataclass(frozen=True)
class ArchitectPlanningConditionReading(ContractorCloseoutConditionReading):
    contract: ActionContract | None = None


def check_architect_planning_history(check, selected, validate_relation):
    source = check.source['identity']
    code = check.condition.condition_code
    refs = check.condition.object_refs
    if (source['action_id'] != 'ARCHITECT-A04' or source['role'] != 'Architect' or source['purpose'] != 'action'
            or code not in _CODES or check.condition.trigger != 'dependency_change'
            or not refs or (any(ref.kind not in {'Task', 'Dependency', 'WorkProfile'} for ref in refs)
                if code == TASK_CODE else tuple(ref.kind for ref in refs) != ('ResourceCalendar',))
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ArchitectPlanningConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Design planning recovery requires the original private task/dependency wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.operation_id == source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original.contract_ref
            or context.contract_ref.id != 'ARCHITECT-A04' or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Design planning recovery substitutes original snapshot, time, scope or current authority')
    reading.check_method_context(context, 'ARCHITECT-A04')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'ARCHITECT-A04' or contract.role != 'Architect':
        raise TaskConflict('Design planning recovery lacks the actual registered A04 contract')
    original_input, current_input = contract.validate_input(raw), contract.validate_input(current_raw)

    def physical(values):
        result = {ref.key()[:2]: ref for ref in values}
        if len(result) != len(values):
            raise TaskConflict('Design planning recovery aliases physical task, dependency or occupancy histories')
        return result

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Design planning recovery lacks exact typed original/current sources')
        available = getattr(row, 'available_at', None)
        if available is not None and (available.clock_ref != at.clock_ref or available.offset > at.offset):
            raise TaskConflict('Design planning recovery introduces sources unavailable at their original/query time')
        return row

    def unchanged_version(before, after):
        if before.ref == after.ref and before != after:
            raise TaskConflict('Design planning recovery rewrites an immutable source version')

    versions = []
    for values, at in ((original_input, original.business_time), (current_input, context.business_time)):
        profile = read(values.work_profile_ref, ArchitectPlanningProfileView, at)
        appointment = read(profile.appointment_ref, ArchitectAppointmentView, at)
        terms = read(appointment.terms_ref, ServiceTermsView, at)
        calendar = read(values.capacity_ref, ArchitectPlanningCalendarView, at)
        if (values.scope != context.scope or profile.organization_id != source['organization_id']
                or appointment.provider_organization_id != source['organization_id'] or calendar.organization_id != source['organization_id']):
            raise TaskConflict('Design planning recovery borrows another scope, appointment or private resource calendar')
        tasks, dependencies, estimates, facts = {}, {}, {}, {}
        pending = list(values.task_refs)
        declared_tasks = set(physical(pending))
        while pending:
            ref = pending.pop()
            key = ref.key()[:2]
            if key in tasks:
                if tasks[key].ref != ref:
                    raise TaskConflict('Design planning graph aliases an original task version')
                continue
            task = read(ref, ArchitectPlanningTaskView, at)
            tasks[key] = task
            estimates[key] = read(task.estimate_ref, ArchitectPlanningEstimateView, at)
            if (task.organization_id != source['organization_id'] or task.appointment_ref != appointment.ref
                    or task.accepted_terms_ref != terms.ref or task.work_profile_ref != profile.ref):
                raise TaskConflict('Design planning graph changes original appointment, accepted terms or work profile')
            physical(task.work_fact_refs)
            for fact_ref in task.work_fact_refs:
                fact = read(fact_ref, ArchitectPlanningWorkFactView, at)
                if fact.task_ref != task.ref or fact.organization_id != source['organization_id']:
                    raise TaskConflict('Design planning query substitutes original task investments')
                facts[fact_ref.key()[:2]] = fact
            physical(task.dependency_refs)
            # The actual processor reads direct predecessors' effort, not their entire dependency graph.
            for dep_ref in task.dependency_refs if key in declared_tasks else ():
                dep = read(dep_ref, ArchitectPlanningDependencyView, at)
                if dep.task_ref != task.ref:
                    raise TaskConflict('Design planning query borrows another original task dependency')
                dependencies[dep_ref.key()[:2]] = dep
                if dep.predecessor_task_ref is not None:
                    pending.append(dep.predecessor_task_ref)
        allocations = {key: read(ref, ArchitectPlanningAllocationView, at)
            for key, ref in physical(values.existing_allocation_refs).items()}
        reservations = {key: read(ref, ArchitectPlanningReservationView, at)
            for key, ref in physical(profile.reservation_refs).items()}
        prior = None if profile.prior_plan_ref is None else read(profile.prior_plan_ref, QSWorkPlanView, at)
        versions.append(dict(profile=profile, appointment=appointment, terms=terms, calendar=calendar,
            tasks=tasks, dependencies=dependencies, estimates=estimates, facts=facts,
            allocations=allocations, reservations=reservations, prior=prior))
    old, current = versions
    for name in ('profile', 'appointment', 'terms', 'calendar'):
        before, after = old[name], current[name]
        if before.ref.key()[:2] != after.ref.key()[:2]:
            raise TaskConflict('Design planning recovery replaces its original physical engagement or calendar')
        unchanged_version(before, after)
    for name in ('scope', 'provider_id', 'provider_organization_id', 'client_id', 'client_organization_id',
            'payer_id', 'payer_organization_id', 'relation'):
        if getattr(old['appointment'], name) != getattr(current['appointment'], name):
            raise TaskConflict('Design planning recovery changes original service parties or relationship')
    old_relation, new_relation = old['appointment'].service_relationship_ref, current['appointment'].service_relationship_ref
    if ((old_relation is None) != (new_relation is None)
            or old_relation is not None and old_relation.key()[:2] != new_relation.key()[:2]):
        raise TaskConflict('Design planning recovery substitutes the established original service relationship')
    for name in ('clock_ref', 'resource_kind', 'effort_unit', 'capacity_unit', 'method', 'effort_per_capacity_tick'):
        if getattr(old['profile'], name) != getattr(current['profile'], name):
            raise TaskConflict('Design planning recovery reinterprets original task effort or method units')
    if not set(physical(original_input.task_refs)) <= set(physical(current_input.task_refs)):
        raise TaskConflict('Design planning recovery drops original authorized tasks')
    for group in ('tasks', 'dependencies', 'facts', 'allocations', 'reservations'):
        if not set(old[group]) <= set(current[group]):
            raise TaskConflict('Design planning recovery loses original task, investment, dependency or occupation history')
        for key, before in old[group].items():
            unchanged_version(before, current[group][key])
    for key, before in old['tasks'].items():
        after = current['tasks'][key]
        if (before.function_code != after.function_code or before.function_ref.key()[:2] != after.function_ref.key()[:2]
                or before.scope != after.scope or before.status in {'complete', 'cancelled'} and before.status != after.status
                or before.estimate_ref.key()[:2] != after.estimate_ref.key()[:2]
                or not set(physical(before.work_fact_refs)) <= set(physical(after.work_fact_refs))
                or not set(physical(before.dependency_refs)) <= set(physical(after.dependency_refs))
                or before.existing_allocation_ref is not None and (after.existing_allocation_ref is None
                    or before.existing_allocation_ref.key()[:2] != after.existing_allocation_ref.key()[:2])):
            raise TaskConflict('Design planning recovery rewrites original task purpose, workload, investment or allocation')
        estimate, new_estimate = old['estimates'][key], current['estimates'][key]
        unchanged_version(estimate, new_estimate)
        if (estimate.method != new_estimate.method or estimate.effort.value != new_estimate.effort.value
                or estimate.effort.unit != new_estimate.effort.unit
                or estimate.status == 'succeeded' and (new_estimate.status != 'succeeded' or estimate.executed_at != new_estimate.executed_at)):
            raise TaskConflict('Design planning recovery replaces original measured effort or successful method execution')
    for key, before in old['facts'].items():
        after = current['facts'][key]
        if (any(getattr(before, field) != getattr(after, field) for field in
                ('organization_id', 'investment_key', 'effort', 'internal_cost', 'window'))
                or before.status == 'committed' and before.status != after.status):
            raise TaskConflict('Design planning recovery erases actual investment/cost or reuses its original slice')
    for key, before in old['dependencies'].items():
        after = current['dependencies'][key]
        for field in ('deliverable_ref', 'predecessor_task_ref'):
            left, right = getattr(before, field), getattr(after, field)
            if (left is None) != (right is None) or left is not None and left.key()[:2] != right.key()[:2]:
                raise TaskConflict('Design planning recovery swaps the original prerequisite target')
        if before.required_use != after.required_use:
            raise TaskConflict('Design planning recovery changes the authorized original dependency use')
    if old['prior'] is not None:
        if current['prior'] is None or old['prior'].ref.key()[:2] != current['prior'].ref.key()[:2]:
            raise TaskConflict('Design planning recovery drops the original authorized work plan')
        unchanged_version(old['prior'], current['prior'])
        if not set(physical(old['prior'].allocation_refs)) <= set(physical(current['prior'].allocation_refs)):
            raise TaskConflict('Design planning recovery removes original plan allocation history')
    for group in ('allocations', 'reservations'):
        for key, before in old[group].items():
            after = current[group][key]
            if (before.organization_id != after.organization_id or before.appointment_ref.key()[:2] != after.appointment_ref.key()[:2]
                    or before.status == 'released' and after.status != 'released'
                    or group == 'reservations' and before.status == 'converted' and after.status == 'reserved'
                    or group == 'allocations' and (before.task_ref.key()[:2] != after.task_ref.key()[:2]
                        or before.work_plan_ref.key()[:2] != after.work_plan_ref.key()[:2]
                        or not set(physical(before.work_fact_refs)) <= set(physical(after.work_fact_refs)))):
                raise TaskConflict('Design planning recovery substitutes or reactivates original resource occupation history')
    historical_comparisons = []
    if code == TASK_CODE:
        original_gate = plan_design_work(original, original_input, reading, original_wait_only=True)
    else:
        original_gate, historical_comparisons = recheck_original_architect_planning_capacity(original, original_input, reading)
    if (not isinstance(original_gate, dict) or original_gate.get('resume_condition', {}).get('condition_code') != code
            or original_gate.get('resume_condition', {}).get('object_refs') != list(refs)):
        raise TaskConflict('Design planning wait differs from the actual original task/dependency evaluation')
    anchor = refs[0].key()[:2]
    histories = {**current['tasks'], **current['dependencies'], current['profile'].ref.key()[:2]: current['profile'],
        current['calendar'].ref.key()[:2]: current['calendar']}
    history = histories.get(anchor)
    if (history is None or selected.history_ref != history.ref
            or code == CAPACITY_CODE and refs[0] != old['calendar'].ref):
        raise TaskConflict('Design planning query substitutes its original condition history anchor')
    evidence = []
    for ref in history.evidence_refs:
        row = read(ref, EvidenceRecord, context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Design planning recovery requires actual observed task/dependency history')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    if not evidence:
        return 'unavailable', None

    def dump(version):
        return {name: ({str(key): row.model_dump(mode='json') for key, row in value.items()}
            if isinstance(value, dict) else None if value is None else value.model_dump(mode='json'))
            for name, value in version.items()}

    resolution = dict(schema_version=('architect-planning-task-resolution.v1' if code == TASK_CODE
        else 'architect-planning-capacity-resolution.v1'), condition_code=code,
        history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_sources=dump(old), current_sources=dump(current), evidence=evidence,
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'), sources=reading.evidence())
    if code == CAPACITY_CODE:
        resolution['historical_comparisons'] = historical_comparisons
    old_occupations = physical([row.commitment_ref for row in old['calendar'].commitments])
    new_occupations = physical([row.commitment_ref for row in current['calendar'].commitments])
    before_rows = {row.commitment_ref.key()[:2]: row for row in old['calendar'].commitments}
    after_rows = {row.commitment_ref.key()[:2]: row for row in current['calendar'].commitments}
    for key, before in before_rows.items():
        after = after_rows.get(key)
        if after is not None and (before.resource_ref.key()[:2] != after.resource_ref.key()[:2]
                or before.commitment_ref == after.commitment_ref and before != after):
            raise TaskConflict('Design planning recovery substitutes occupied resources or rewrites an immutable commitment')
    changes = [dict(original=before_rows[key].model_dump(mode='json'),
        current=None if key not in new_occupations else after_rows[key].model_dump(mode='json'))
        for key in old_occupations if before_rows[key] != after_rows.get(key)]
    history_changes = [dict(kind=group, original=before.model_dump(mode='json'), current=current[group][key].model_dump(mode='json'))
        for group in ('allocations', 'reservations') for key, before in old[group].items()
        if before.status != current[group][key].status or
            (before.commitments != current[group][key].commitments if group == 'allocations' else before.items != current[group][key].items)]
    if changes or history_changes:
        ledger_evidence = []
        for ref in current['calendar'].evidence_refs:
            row = read(ref, EvidenceRecord, context.business_time)
            if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                raise TaskConflict('Design planning cannot infer native occupation release from changed/omitted calendar rows')
            if row.effective_window is not None and not row.effective_window.contains(context.business_time):
                return 'unavailable', None
            ledger_evidence.append(row.model_dump(mode='json'))
        if not ledger_evidence:
            return 'unavailable', None
        ledger = dict(schema_version='architect-planning-occupation-resolution.v1', occupation_changes=changes,
            allocation_reservation_changes=history_changes, original_sources=resolution['original_sources'],
            current_sources=resolution['current_sources'], evidence=ledger_evidence, sources=reading.evidence())
        if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(ledger),
                context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Design planning recovery lacks independent native occupation release/adjustment history')
        resolution['occupation_resolution'] = ledger
    current_result = plan_design_work(context, current_input, reading)
    if current_result.get('kind') != 'completed':
        return 'waiting', None
    contract.validate_decision(current_input, current_result['payload'])
    resolution['current_result'] = contract.result_adapter.validate_python(current_result).model_dump(mode='json')
    resolution['sources'] = reading.evidence()
    if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Design planning recovery lacks actual independent task revision and remaining-duty authority')
    return 'ready', resolution


def architect_original_planning_profile(read_current, validate_relation, condition_code=TASK_CODE):
    if condition_code not in _CODES or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Design planning recovery requires actual guarded sources and independent native validation')
    def evaluate(check):
        if check.condition.condition_code != condition_code:
            raise TaskConflict('Design planning condition profile substitutes its original wait branch')
        selected = read_current(deepcopy(check))
        try:
            return check_architect_planning_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()
    return ConditionProfile('ARCHITECT-A04', condition_code, '1', frozenset({'dependency_change'}), evaluate)
