"""Rejudge an original QS appointment task without assigning resources."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, ScopeRef, ref_type
from src.actions.contracts.qs_appointment_objects import (
    QSAppointmentView, QSTaskCalendarView, QSTaskView, QSAllocationView, QSTaskDependencyView,
)
from src.actions.contracts.service_objects import ServiceTermsView, ServiceWorkProfileView
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.capacity import CAPACITY_METHOD, CapacityReport
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'qs_task_not_ready'
_DEPENDENCY_CODE = 'qs_task_dependency_waiting'
_CAPACITY_CODE = 'qs_task_shared_capacity_unavailable'
_CODES = (_CODE, _DEPENDENCY_CODE, _CAPACITY_CODE)
_FIELDS = frozenset({'scope', 'appointment_ref', 'accepted_terms_ref', 'function_refs',
    'task_refs', 'capacity_ref', 'work_profile_ref', 'existing_allocation_refs'})


@dataclass(frozen=True)
class QSAppointmentConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict


def qs_original_appointment_task_profile(read_current, validate_relation, *, condition_code=_CODE):
    """Ready permits fresh A03 judgment; dependency and capacity gates still run."""
    if condition_code not in _CODES or not callable(read_current) or not callable(validate_relation):
        raise ValueError('QS appointment recovery requires actual sources and native task/history validation')

    def identity(ref):
        return None if ref is None else ref.key()[:2]

    def refs(raw, field, kind):
        rows = [ref_type(kind).model_validate(value) for value in raw[field]]
        indexed = {identity(ref): ref for ref in rows}
        if len(indexed) != len(rows):
            raise TaskConflict('QS appointment recovery duplicates a physical source')
        return indexed

    def evaluate(check):
        source, waited = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'QS-A03' or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != condition_code or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not waited
                or condition_code != _CAPACITY_CODE and len(waited) != (2 if condition_code == _DEPENDENCY_CODE else 1)
                or waited[0].kind != ('Dependency' if condition_code == _DEPENDENCY_CODE
                    else 'ResourceCalendar' if condition_code == _CAPACITY_CODE else 'Task')
                or condition_code == _DEPENDENCY_CODE and waited[1].kind != 'Task'):
            raise TaskConflict('QS appointment recovery replaces its original task wait or recipient')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, QSAppointmentConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.original_action_input, dict)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('QS appointment recovery requires typed current sources and original input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        try:
            original_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            if (set(original_input) != _FIELDS or set(action_input) != _FIELDS
                    or task_digest(original_input) != source['input_sha256']
                    or original_input['scope'] != action_input['scope'] or context.run_id != source['run_id']
                    or reading.organization_id != source['organization_id'] or context.contract_ref.kind != 'ActionContract'
                    or context.contract_ref.id != 'QS-A03' or context.execution_mode == 'offline_fixture'
                    or reading._resolver.source_mode != 'formal' or context.business_time != check.signal.business_time
                    or context.operation_id == source['request_id']):
                raise TaskConflict('QS appointment recovery changes original snapshot, scope or current invocation')
            scope = TypeAdapter(ScopeRef).validate_python(action_input['scope'])
            if not scope_covers(context.scope, scope):
                raise TaskConflict('QS appointment recovery leaves its authorized coverage')
            reading.check_method_context(context, 'QS-A03')
            proof_rows, proof_refs, versions = [], [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
                    raise TaskConflict('QS appointment recovery lacks an exact original/current source')
                proof_rows.append(row)
                return row

            for raw in (original_input, action_input):
                appointment = read(ref_type('Appointment').model_validate(raw['appointment_ref']), QSAppointmentView)
                terms = read(ref_type('ServiceTerms').model_validate(raw['accepted_terms_ref']), ServiceTermsView)
                calendar = read(ref_type('ResourceCalendar').model_validate(raw['capacity_ref']), QSTaskCalendarView)
                profile = None if raw['work_profile_ref'] is None else read(
                    ref_type('WorkProfile').model_validate(raw['work_profile_ref']), ServiceWorkProfileView)
                functions = refs(raw, 'function_refs', 'FunctionAssignment')
                tasks = {key: read(ref, QSTaskView) for key, ref in refs(raw, 'task_refs', 'Task').items()}
                allocations = {key: read(ref, QSAllocationView) for key, ref in refs(raw, 'existing_allocation_refs', 'ResourceAllocation').items()}
                if (appointment.scope != scope or terms.scope != scope or appointment.terms_ref != terms.ref
                        or appointment.provider_organization_id != source['organization_id']
                        or appointment.provider_id != context.actor_id or terms.provider_id != context.actor_id
                        or terms.request_ref != appointment.request_ref or appointment.capacity_ref != calendar.ref
                        or calendar.organization_id != source['organization_id'] or profile is None
                        or terms.work_profile_ref != profile.ref or set(functions.values()) != set(appointment.function_refs)
                        or {row.ref for row in tasks.values()} != set(appointment.task_refs)
                        or {row.ref for row in allocations.values()} != set(appointment.existing_allocation_refs)):
                    raise TaskConflict('QS appointment recovery substitutes its original appointment, accepted terms or planning sources')
                for task in tasks.values():
                    if (task.organization_id != source['organization_id'] or task.scope != scope
                            or task.appointment_ref != appointment.ref or task.accepted_terms_ref != terms.ref
                            or task.work_profile_ref != profile.ref or task.function_ref not in functions.values()):
                        raise TaskConflict('QS appointment recovery borrows another task, function or work profile')
                    proof_refs.append(task.total_effort.basis_ref)
                    if task.remaining_effort.state == 'known':
                        proof_refs.append(task.remaining_effort.value.basis_ref)
                versions.append(dict(appointment=appointment, terms=terms, calendar=calendar, profile=profile,
                    functions=functions, tasks=tasks, allocations=allocations))
            old, current = versions
            if condition_code == _CAPACITY_CODE:
                if (waited[0] != old['calendar'].ref
                        or [ref.key() for ref in waited[1:]] != [ref_type('Task').model_validate(ref).key()
                            for ref in original_input['task_refs']] or not old['tasks']):
                    raise TaskConflict('QS capacity recovery replaces its original calendar or complete ordered task wait')
            waited_task_ref = waited[1] if condition_code in {_DEPENDENCY_CODE, _CAPACITY_CODE} else waited[0]
            waited_key = identity(waited_task_ref)
            if waited_key not in old['tasks'] or old['tasks'][waited_key].ref != waited_task_ref:
                raise TaskConflict('QS appointment recovery replaces its original task wait')
            if (condition_code == _CODE and old['tasks'][waited_key].status == 'authorized'
                    or any(identity(old[field].ref) != identity(current[field].ref) for field in ('appointment', 'calendar', 'profile'))
                    or old['terms'] != current['terms']
                    or any(old[field].keys() != current[field].keys() for field in ('functions', 'tasks', 'allocations'))):
                raise TaskConflict('QS appointment recovery replaces its original task wait, accepted terms or complete planning set')
            for field in ('request_ref', 'provider_id', 'provider_organization_id', 'client_id', 'client_organization_id',
                    'payer_id', 'payer_organization_id', 'relation', 'terms_digest', 'acceptance_ref'):
                if getattr(old['appointment'], field) != getattr(current['appointment'], field):
                    raise TaskConflict('QS appointment recovery rewrites accepted parties, request or independent acceptance')
            for field in ('prior_plan_ref', 'reservation_ref', 'service_relationship_ref'):
                if identity(getattr(old['appointment'], field)) != identity(getattr(current['appointment'], field)):
                    raise TaskConflict('QS appointment recovery replaces original plan, reservation or relationship history')
            for key, task in current['tasks'].items():
                before = old['tasks'][key]
                if (any(getattr(before, field) != getattr(task, field) for field in ('total_effort', 'function_code'))
                        or identity(before.function_ref) != identity(task.function_ref)
                        or identity(before.work_profile_ref) != identity(task.work_profile_ref)
                        or identity(before.existing_allocation_ref) != identity(task.existing_allocation_ref)
                        or {identity(ref) for ref in before.dependency_refs} != {identity(ref) for ref in task.dependency_refs}
                        or {identity(row.resource_ref): row.share for row in before.resource_shares}
                            != {identity(row.resource_ref): row.share for row in task.resource_shares}):
                    raise TaskConflict('QS appointment recovery rewrites original effort, task function, resources or dependency set')
            if waited_key not in current['tasks']:
                raise TaskConflict('QS appointment recovery drops its original waited task')
            task = current['tasks'][waited_key]
            dependency_history = None
            if condition_code == _DEPENDENCY_CODE:
                original_task = old['tasks'][waited_key]
                if original_task.status != 'authorized' or waited[0] not in original_task.dependency_refs:
                    raise TaskConflict('QS dependency recovery replaces its original authorized task/dependency pair')
                matching = [ref for ref in task.dependency_refs if identity(ref) == identity(waited[0])]
                if len(matching) != 1:
                    raise TaskConflict('QS dependency recovery replaces its original physical dependency')
                original_dependency = read(waited[0], QSTaskDependencyView)
                dependency = read(matching[0], QSTaskDependencyView)
                if (original_dependency.task_ref != original_task.ref or dependency.task_ref != task.ref
                        or original_dependency.scope != scope or dependency.scope != scope
                        or original_dependency.satisfied.state != 'known' or original_dependency.satisfied.value is not False):
                    raise TaskConflict('QS dependency recovery substitutes its original unsatisfied dependency facts')
                dependency_history = dict(original=original_dependency.model_dump(mode='json'),
                    current=dependency.model_dump(mode='json'))
            if task.status != 'authorized' or task.as_of != context.business_time:
                return 'waiting'
            if condition_code == _DEPENDENCY_CODE:
                if (dependency.as_of != context.business_time or dependency.satisfied.state != 'known'
                        or dependency.satisfied.value is not True):
                    return 'waiting'
            capacity_history, capacity_inputs = None, None
            if condition_code == _CAPACITY_CODE:
                from src.coordination.qs_appointment_capacity import read_appointment_capacity
                original_capacity = read_appointment_capacity(version=old, read=read, proof_refs=proof_refs,
                    now=old['calendar'].as_of)
                if isinstance(original_capacity, str):
                    raise TaskConflict('QS capacity recovery lacks its complete original authorized planning snapshot')
                capacity = read_appointment_capacity(version=current, read=read, proof_refs=proof_refs,
                    now=context.business_time)
                if isinstance(capacity, str):
                    return capacity
                capacity_inputs = capacity['inputs']
                capacity_history = dict(original=original_capacity['history'], current=capacity['history'],
                    original_inputs=[data.model_dump(mode='json') for data in original_capacity['inputs']])
            for row in current['tasks'].values():
                grant, function = reading.resolve(row.authority_ref), reading.resolve(row.function_ref)
                if (not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment)
                        or function.function_ref != row.function_ref or function.role != 'QS'
                        or grant.organization_id != source['organization_id'] or grant.actor_id != context.actor_id
                        or grant.function_ref != row.function_ref or 'QS-A03' not in grant.action_ids
                        or not grant.validity.contains(context.business_time)
                        or not any(scope_covers(s, scope) for s in grant.scopes)):
                    raise TaskConflict('QS appointment recovery lacks current actual task authority')
                proof_refs.extend([*grant.basis_refs, *function.basis_refs])
            for row in proof_rows:
                proof_refs.extend(getattr(row, 'evidence_refs', []))
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('QS appointment recovery requires native observed task/planning evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            capacity_results = None
            if capacity_inputs is not None:
                capacity_results = []
                for data in capacity_inputs:
                    result = reading.calculate(CAPACITY_METHOD, data)
                    if result.kind in {'technical_error', 'invalid_input'}:
                        raise TaskConflict('QS recovery capacity calculation failed; inspect the original method evidence')
                    if result.kind != 'ok':
                        return 'unavailable'
                    report = CapacityReport.model_validate(result.value)
                    if not report.feasible:
                        return 'waiting'
                    capacity_results.append(dict(input=data.model_dump(mode='json'),
                        report=report.model_dump(mode='json'), method_result=result.model_dump(mode='json')))

            def history(version):
                return {field: [ref.model_dump(mode='json') for ref in value.values()]
                    if isinstance(value, dict) else value.model_dump(mode='json') for field, value in version.items()}

            if validate_relation(source_identity=deepcopy(source), original_action_input=original_input,
                    action_input=action_input, original_sources=history(old), current_sources=history(current),
                    condition_code=condition_code, dependency_history=deepcopy(dependency_history),
                    capacity_history=deepcopy(capacity_history), capacity_results=deepcopy(capacity_results),
                    evidence=deepcopy(list(evidence.values())),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('QS appointment recovery lacks native original-task transition and complete planning history validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('QS-A03', condition_code, '1', frozenset({'dependency_change'}), evaluate)


def qs_original_appointment_task_profiles(read_current, validate_relation):
    return tuple(qs_original_appointment_task_profile(read_current, validate_relation, condition_code=code)
        for code in _CODES)


def qs_original_appointment_dependency_profile(read_current, validate_relation):
    """Require independently authenticated satisfaction of the original dependency."""
    return qs_original_appointment_task_profile(read_current, validate_relation, condition_code=_DEPENDENCY_CODE)


def qs_original_appointment_capacity_profile(read_current, validate_relation):
    """Recompute original task demand with authentic current calendar/occupancy."""
    return qs_original_appointment_task_profile(read_current, validate_relation, condition_code=_CAPACITY_CODE)
