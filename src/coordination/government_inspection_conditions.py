"""Resume an original Government A10 task after an authorized task update."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, ScopeRef, ref_type
from src.actions.contracts.government_inspection_objects import (
    GovInspectionTaskView, GovInspectionView, GovSchedulingWorkProfileView, GovSchedulingDependencyView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.coordination.government_inspection_work_history import read_completed_inspection_work
from src.coordination.government_inspection_capacity import read_inspection_capacity
from src.methods.capacity import CAPACITY_METHOD, CapacityReport
from src.organization.registry import scope_covers


_CODE = 'government-inspection-original-task-waiting'
_WINDOW_CODE = 'government-inspection-finite-current-work-window'
_DEPENDENCY_CODE = 'government-inspection-plan-dependency-wait'
_HANDOFF_CODE = 'government-inspection-completed-work-awaits-original-handoff'
_CAPACITY_CODE = 'government-inspection-resource-capacity-wait'
_CODES = (_CODE, _WINDOW_CODE, _DEPENDENCY_CODE, _HANDOFF_CODE, _CAPACITY_CODE)
_WAIT_KINDS = {_DEPENDENCY_CODE: 'Dependency', _CAPACITY_CODE: 'ResourceCalendar'}
_INPUT_FIELDS = frozenset({
    'scope', 'inspection_basis_ref', 'permit_ref', 'task_ref', 'access_ref',
    'observation_method_ref', 'observation_refs', 'prior_issue_refs',
})


@dataclass(frozen=True)
class GovernmentInspectionTaskConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict


def government_original_inspection_task_profile(read_current, validate_relation):
    """Rejudge the same inspection using its immutable original input snapshot.

    The host supplies authorized original/current task versions and independently
    validates the native task transition and complete current input. A ready task
    only permits fresh A10 judgment: inspection permission, observations, finite
    work, capacity and independent enforcement authority remain processor gates.
    A scheduling signal supplies none of those facts.
    """
    return _government_inspection_task_profile(_CODE, read_current, validate_relation)


def government_original_inspection_window_profile(read_current, validate_relation):
    """Authenticate a finite current window for the same original plan task.

    Native validation receives original/current work profiles and the emitted
    condition code. Window readiness reserves no personnel or capacity and
    proves no work completion; the original A10 plan gates still run.
    """
    return _government_inspection_task_profile(_WINDOW_CODE, read_current, validate_relation)


def government_original_inspection_profiles(read_current, validate_relation):
    return tuple(_government_inspection_task_profile(code, read_current, validate_relation) for code in _CODES)


def government_original_inspection_dependency_profile(read_current, validate_relation):
    """Rejudge the original plan after its emitted dependency becomes known true.

    Native validation receives the exact original/current dependency versions.
    Other dependencies, work completion and capacity remain A10 processor gates.
    """
    return _government_inspection_task_profile(_DEPENDENCY_CODE, read_current, validate_relation)


def government_original_inspection_handoff_profile(read_current, validate_relation):
    """Rejudge a completed original plan using a current authorized A10 choice.

    Retain actual work and all known observations/issues. Newly received sources
    require native provenance validation and the ordinary current processor
    gates; this condition executes no work, inspection or enforcement effect.
    """
    return _government_inspection_task_profile(_HANDOFF_CODE, read_current, validate_relation)


def government_original_inspection_capacity_profile(read_current, validate_relation):
    """Recompute same-task capacity after authentic native occupancy changes.

    Native validation receives original/current calendars, work history and
    the exact capacity input/report. No occupancy is freed, assigned or reserved
    by a scheduling hint or this calculation.
    """
    return _government_inspection_task_profile(_CAPACITY_CODE, read_current, validate_relation)


def _government_inspection_task_profile(code, read_current, validate_relation):
    if code not in _CODES or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Government task recovery requires actual reading and native transition validation')

    def identity(ref):
        return None if ref is None else (ref.kind, ref.id)

    def identities(refs):
        result = {identity(ref) for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Government inspection recovery duplicates a physical source identity')
        return result

    def retained(old, current, allow_new=False):
        old_ids, current_ids = identities(old), identities(current)
        return old_ids <= current_ids if allow_new else old_ids == current_ids

    def input_ref(raw, field, kind, optional=False):
        value = raw[field]
        if value is None and optional:
            return None
        return ref_type(kind).model_validate(value)

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        wait_kind = _WAIT_KINDS.get(code, 'Task')
        if (source['action_id'] != 'GOV-A10' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != wait_kind):
            raise TaskConflict('Government inspection recovery replaces its original action, recipient or task wait')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, GovernmentInspectionTaskConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.original_action_input, dict) or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Government inspection recovery requires typed current reading and original snapshot input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        try:
            old_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            scope = TypeAdapter(ScopeRef).validate_python(action_input['scope'])
            if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'GOV-A10'
                    or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                    or set(old_input) != _INPUT_FIELDS or set(action_input) != _INPUT_FIELDS
                    or task_digest(old_input) != source['input_sha256']
                    or old_input['scope'] != action_input['scope']
                    or not scope_covers(context.scope, scope)):
                raise TaskConflict('Government inspection recovery changes its original snapshot, scope or current invocation')
            reading.check_method_context(context, 'GOV-A10')
            original_ref = input_ref(old_input, 'task_ref', 'Task')
            task_ref = input_ref(action_input, 'task_ref', 'Task')
            if (identity(original_ref) != identity(task_ref)
                    or wait_kind == 'Task' and original_ref.key() != old_refs[0].key()):
                raise TaskConflict('Government inspection recovery substitutes the original physical task')
            for field, kind, optional in (
                    ('inspection_basis_ref', 'Rule', False), ('permit_ref', 'Permit', True),
                    ('access_ref', 'SiteAccess', True), ('observation_method_ref', 'Method', False)):
                old_selected = input_ref(old_input, field, kind, optional)
                current_selected = input_ref(action_input, field, kind, optional)
                if (identity(old_selected) != identity(current_selected)
                        and not (code == _HANDOFF_CODE and field == 'access_ref' and old_selected is None)):
                    raise TaskConflict('Government inspection recovery replaces original basis, permit, access or method')
            for field, kind in (('observation_refs', 'Observation'), ('prior_issue_refs', 'Issue')):
                if not isinstance(old_input[field], list) or not isinstance(action_input[field], list):
                    raise TaskConflict('Government inspection recovery requires original received source lists')
                old_selected = [input_ref({'ref': raw}, 'ref', kind) for raw in old_input[field]]
                current_selected = [input_ref({'ref': raw}, 'ref', kind) for raw in action_input[field]]
                if not retained(old_selected, current_selected, code == _HANDOFF_CODE):
                    raise TaskConflict('Government inspection recovery replaces original received observations or issues')
            original, task = reading.resolve(original_ref), reading.resolve(task_ref)
            if (not isinstance(original, GovInspectionTaskView) or not isinstance(task, GovInspectionTaskView)
                    or original.ref != original_ref or task.ref != task_ref
                    or task.organization_id != source['organization_id'] or task.execution_action_id != 'GOV-A10'
                    or task.scope != scope
                    or task.function_ref != context.function_ref or task.authority_ref not in context.authorization_refs
                    or any(getattr(original, field) != getattr(task, field) for field in (
                        'organization_id', 'scope', 'execution_action_id', 'function_code', 'discipline_codes',
                        'region_id'))
                    or code != _CAPACITY_CODE and original.resource_shares != task.resource_shares
                    or code != _HANDOFF_CODE and original.choice != task.choice
                    or any(identity(getattr(original, field)) != identity(getattr(task, field)) for field in (
                        'case_ref', 'authority_ref', 'function_ref', 'work_profile_ref', 'estimate_ref',
                        'inspection_basis_ref', 'permit_ref', 'inspection_ref', 'observation_method_ref'))
                    or identity(original.measure_basis_ref) != identity(task.measure_basis_ref)
                        and not (code == _HANDOFF_CODE and original.measure_basis_ref is None)
                    or not retained(original.dependency_refs, task.dependency_refs)
                    or any(not retained(getattr(original, field), getattr(task, field), code == _HANDOFF_CODE) for field in (
                        'received_observation_refs', 'prior_issue_refs', 'check_rule_refs', 'question_refs'))
                    or not identities(original.work_fact_refs) <= identities(task.work_fact_refs)):
                raise TaskConflict('Government inspection recovery substitutes original task purpose, authority or retained work/evidence')
            for raw, row in ((old_input, original), (action_input, task)):
                if (row.scope != scope
                        or row.inspection_basis_ref != input_ref(raw, 'inspection_basis_ref', 'Rule')
                        or row.permit_ref != input_ref(raw, 'permit_ref', 'Permit', True)
                        or row.observation_method_ref != input_ref(raw, 'observation_method_ref', 'Method')
                        or {ref.key() for ref in row.received_observation_refs}
                            != {Reference.model_validate(ref).key() for ref in raw['observation_refs']}
                        or {ref.key() for ref in row.prior_issue_refs}
                            != {Reference.model_validate(ref).key() for ref in raw['prior_issue_refs']}):
                    raise TaskConflict('Government inspection recovery input differs from its exact original/current task sources')
            old_inspection, inspection = reading.resolve(original.inspection_ref), reading.resolve(task.inspection_ref)
            for row, expected_task in ((old_inspection, original), (inspection, task)):
                if (not isinstance(row, GovInspectionView) or row.ref != expected_task.inspection_ref
                        or row.task_ref != expected_task.ref or row.organization_id != task.organization_id
                        or row.permit_ref != expected_task.permit_ref or not scope_covers(expected_task.scope, row.scope)):
                    raise TaskConflict('Government inspection recovery changes original inspection, agency or permit linkage')
            if old_inspection.scope != inspection.scope:
                raise TaskConflict('Government inspection recovery changes original inspection coverage')
            now = context.business_time
            if (task.available_at.clock_ref != now.clock_ref or task.available_at.offset > now.offset
                    or inspection.available_at.clock_ref != now.clock_ref or inspection.available_at.offset > now.offset
                    or not task.effective_window.contains(now) or not inspection.effective_window.contains(now)):
                return 'unavailable'
            if task.status != 'authorized' or task.as_of != now:
                return 'waiting'
            extra_rows, extra_refs, validation_sources, capacity_data = [], [], {}, None
            if code == _WINDOW_CODE:
                if original.choice != 'plan' or task.choice != 'plan':
                    raise TaskConflict('Government work window recovery requires the original inspection plan choice')
                original_work = reading.resolve(original.work_profile_ref)
                work = reading.resolve(task.work_profile_ref)
                if (not isinstance(original_work, GovSchedulingWorkProfileView) or not isinstance(work, GovSchedulingWorkProfileView)
                        or original_work.ref != original.work_profile_ref or work.ref != task.work_profile_ref
                        or original_work.organization_id != task.organization_id or work.organization_id != task.organization_id
                        or not scope_covers(original.scope, original_work.scope)
                        or not scope_covers(task.scope, work.scope)):
                    raise TaskConflict('Government inspection window replaces original agency work profile or coverage')
                if (work.available_at.clock_ref != now.clock_ref or work.available_at.offset > now.offset
                        or not work.effective_window.contains(now)):
                    return 'unavailable'
                window = task.planned_window
                if (window.start.clock_ref != now.clock_ref or window.bounds != 'closed_open'
                        or work.effective_window.bounds != 'closed_open' or task.effective_window.bounds != 'closed_open'):
                    return 'unavailable'
                duration = window.end.offset - window.start.offset
                if (duration <= 0 or window.start.offset < now.offset or duration > work.maximum_assignment_ticks
                        or window.start.offset < work.effective_window.start.offset
                        or window.end.offset > work.effective_window.end.offset
                        or window.start.offset < task.effective_window.start.offset
                        or window.end.offset > task.effective_window.end.offset):
                    return 'waiting'
                extra_rows = [(original_work, False), (work, True)]
                validation_sources = {'condition_code': code,
                    'original_work_profile': original_work.model_copy(deep=True), 'work_profile': work.model_copy(deep=True)}
            elif code == _DEPENDENCY_CODE:
                if (original.choice != 'plan' or task.choice != 'plan'
                        or old_refs[0].key() not in {ref.key() for ref in original.dependency_refs}):
                    raise TaskConflict('Government dependency recovery changes its original plan or emitted dependency')
                current_ref = next(ref for ref in task.dependency_refs if identity(ref) == identity(old_refs[0]))
                old_dependency, dependency = reading.resolve(old_refs[0]), reading.resolve(current_ref)
                if (not isinstance(old_dependency, GovSchedulingDependencyView) or not isinstance(dependency, GovSchedulingDependencyView)
                        or old_dependency.ref.key() != old_refs[0].key() or dependency.ref != current_ref
                        or old_dependency.task_ref != original.ref or dependency.task_ref != task.ref
                        or old_dependency.scope != dependency.scope or not scope_covers(task.scope, dependency.scope)):
                    raise TaskConflict('Government dependency recovery replaces its original dependency or task association')
                if (dependency.available_at.clock_ref != now.clock_ref or dependency.available_at.offset > now.offset
                        or not dependency.effective_window.contains(now)):
                    return 'unavailable'
                if (dependency.as_of != now or dependency.satisfied.state != 'known' or dependency.satisfied.value is not True):
                    return 'waiting'
                extra_rows = [(old_dependency, False), (dependency, True)]
                validation_sources = {'condition_code': code, 'original_dependency': old_dependency.model_copy(deep=True),
                    'dependency': dependency.model_copy(deep=True)}
            elif code == _HANDOFF_CODE:
                if original.choice != 'plan':
                    raise TaskConflict('Government completed-work handoff requires its original inspection plan')
                if task.choice == 'plan':
                    return 'waiting'
                completion = read_completed_inspection_work(reading=reading, original=original, task=task, now=now)
                if isinstance(completion, str):
                    return completion
                extra_rows, extra_refs = completion['proof_rows'], completion['proof_refs']
                validation_sources = {'condition_code': code, 'completed_work_history': deepcopy(completion['histories'])}
            elif code == _CAPACITY_CODE:
                capacity = read_inspection_capacity(reading=reading, original=original, task=task,
                    original_calendar_ref=old_refs[0], now=now)
                if isinstance(capacity, str):
                    return capacity
                extra_rows, extra_refs, capacity_data = capacity['proof_rows'], capacity['proof_refs'], capacity['data']
                validation_sources = {'condition_code': code, 'capacity_history': deepcopy(capacity['history']),
                    'capacity_input': None, 'capacity_report': None, 'capacity_method_result': None}
            observed = {}
            evidence_refs = list(extra_refs)
            for row, current in [(original, False), (task, True), (old_inspection, False), (inspection, True), *extra_rows]:
                evidence_refs.extend((ref, current) for ref in row.evidence_refs)
            for ref, current in evidence_refs:
                evidence = reading.resolve(ref)
                if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic'
                        or evidence.basis_kind != 'observed'):
                    raise TaskConflict('Government task recovery requires actual observed native task evidence')
                if current and evidence.effective_window is not None and not evidence.effective_window.contains(now):
                    return 'unavailable'
                observed[ref.key()] = evidence.model_dump(mode='json')
            if capacity_data is not None:
                result = reading.calculate(CAPACITY_METHOD, capacity_data)
                if result.kind in {'technical_error', 'invalid_input'}:
                    raise TaskConflict('Inspection capacity method failed; inspect original method evidence before retrying')
                if result.kind != 'ok':
                    return 'unavailable'
                report = CapacityReport.model_validate(result.value)
                if not report.feasible:
                    return 'waiting'
                validation_sources.update(capacity_input=capacity_data.model_dump(mode='json'),
                    capacity_report=report.model_dump(mode='json'), capacity_method_result=result.model_dump(mode='json'))
            if validate_relation(source_identity=deepcopy(source), original_action_input=old_input, action_input=action_input,
                    original_task=original.model_copy(deep=True), task=task.model_copy(deep=True),
                    original_inspection=old_inspection.model_copy(deep=True), inspection=inspection.model_copy(deep=True),
                    evidence=deepcopy(list(observed.values())), context=context.model_copy(deep=True), reading=reading,
                    **validation_sources) is not True:
                raise TaskConflict('Government task recovery lacks native original transition and complete current input validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('GOV-A10', code, '1', frozenset({'dependency_change'}), evaluate)
