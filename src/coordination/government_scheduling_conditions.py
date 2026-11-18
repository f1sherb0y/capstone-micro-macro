"""Rejudge original GOV-A03 tasks without bypassing queues or reserving reviewers."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, Reference, ScopeRef, ref_type, walk_references
from src.actions.contracts.government_objects import GovJurisdictionView
from src.actions.contracts.government_scheduling_objects import (
    GovSchedulingCaseView, GovCaseQueueView, GovQueueProfileView, GovQueueRuleView,
    GovSchedulingWorkProfileView, GovSchedulingTaskView, GovSchedulingDependencyView,
    GovSchedulingEstimateView, GovSchedulingWorkFactView, GovReviewCalendarView, GovReviewAssignmentView,
    GovReviewResourceView, GovReviewQualificationView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.government_scheduling_availability import government_scheduling_availability_history
from src.coordination.government_scheduling_capacity import read_government_scheduling_capacity
from src.coordination.government_scheduling_priority import government_scheduling_priority_history
from src.coordination.government_scheduling_queue_order import government_scheduling_queue_order_history
from src.coordination.government_scheduling_handoff import read_government_scheduling_handoff
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.pricing import decimal_fraction
from src.methods.capacity import CAPACITY_METHOD, CapacityReport
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'government_review_task_waiting_or_closed'
_DEPENDENCY_CODE = 'government_review_dependency_wait'
_WINDOW_CODE = 'government_review_requires_finite_current_assignment_window'
_EFFORT_CODE = 'government_review_remaining_effort_unknown'
_ACTUAL_EFFORT_CODE = 'government_review_actual_effort_pending'
_QUALIFICATION_CODE = 'government_review_missing_current_reviewer_qualification'
_AUTHORIZATION_CODE = 'government_review_no_authorized_reviewer_for_window'
_DISCIPLINE_CODE = 'government_review_no_qualified_resource'
_AVAILABILITY_CODE = 'government_review_no_suitable_available_resource'
_CAPACITY_CODE = 'government_review_capacity_queue_wait'
_CASE_CODE = 'government_review_case_not_open'
_CASE_INPUT_CODE = 'government_review_waiting_for_case_inputs'
_CASE_CODES = (_CASE_CODE, _CASE_INPUT_CODE)
_PRIORITY_CODE = 'government_review_priority_exception_not_authorized'
_QUEUE_ORDER_CODE = 'government_review_preserve_prior_lawful_queue_order'
_HANDOFF_CODE = 'government_review_task_complete_requires_formal_handoff'
_PRETASK_CODES = (*_CASE_CODES, _PRIORITY_CODE, _QUEUE_ORDER_CODE)
_REVIEWER_CODES = (_QUALIFICATION_CODE, _AUTHORIZATION_CODE, _DISCIPLINE_CODE)
_CODES = (_CODE, _DEPENDENCY_CODE, _WINDOW_CODE, _EFFORT_CODE, _ACTUAL_EFFORT_CODE,
    *_REVIEWER_CODES, _AVAILABILITY_CODE, _CAPACITY_CODE, *_PRETASK_CODES, _HANDOFF_CODE)
_FIELDS = frozenset({'scope', 'case_ref', 'queue_ref', 'task_refs', 'capacity_ref',
    'ordering_profile_ref', 'existing_assignment_refs'})
_BASES = (('case_ref', 'RegulatoryCase', GovSchedulingCaseView),
    ('queue_ref', 'CaseQueue', GovCaseQueueView), ('ordering_profile_ref', 'QueueProfile', GovQueueProfileView),
    ('capacity_ref', 'ResourceCalendar', GovReviewCalendarView))


@dataclass(frozen=True)
class GovernmentSchedulingConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict
    scheduling_sources: list[dict] | None = None
    unavailable_targets: list[dict] | None = None
    completed_task_ref: Reference | None = None
    completed_task_refs: tuple[Reference, ...] = ()


def government_original_scheduling_task_profile(read_current, validate_relation, *, condition_code=_CODE):
    """Task readiness permits fresh scheduling; lawful order/capacity still gate it."""
    if condition_code not in _CODES or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Government scheduling recovery requires actual sources and native task/queue history validation')

    def indexed(refs):
        values = {ref.key()[:2]: ref for ref in refs}
        if len(values) != len(refs):
            raise TaskConflict('Government scheduling recovery duplicates a physical source')
        return values

    def evaluate(check):
        source, waited = check.source['identity'], check.condition.object_refs
        expected_kinds = (('Task', 'Dependency') if condition_code == _DEPENDENCY_CODE
            else ('Task', 'WorkEstimate') if condition_code == _EFFORT_CODE
            else ('Task', 'WorkFact') if condition_code == _ACTUAL_EFFORT_CODE
            else ('Task', 'ResourceCalendar') if condition_code == _AVAILABILITY_CODE
            else ('RegulatoryCase', 'CaseQueue', 'ResourceCalendar') if condition_code == _CAPACITY_CODE
            else ('RegulatoryCase',) if condition_code == _CASE_CODE
            else ('RegulatoryCase', 'CaseQueue') if condition_code == _CASE_INPUT_CODE
            else ('RegulatoryCase', 'PriorityBasis') if condition_code == _PRIORITY_CODE
            else ('CaseQueue', *('RegulatoryCase' for _ in waited[1:])) if condition_code == _QUEUE_ORDER_CODE
            else ('Task', 'Resource') if condition_code in _REVIEWER_CODES else ('Task',))
        if (source['action_id'] != 'GOV-A03' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != condition_code or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or tuple(ref.kind for ref in waited) != expected_kinds
                or condition_code == _QUEUE_ORDER_CODE and len(waited) < 2):
            raise TaskConflict('Government scheduling recovery replaces its original task wait or agency')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, GovernmentSchedulingConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.original_action_input, dict)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Government scheduling recovery requires typed current reading and original input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        try:
            original_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            if (set(original_input) != _FIELDS or set(action_input) != _FIELDS
                    or task_digest(original_input) != source['input_sha256'] or original_input['scope'] != action_input['scope']
                    or context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'GOV-A03'
                    or context.execution_mode != 'llm' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']):
                raise TaskConflict('Government scheduling recovery changes original snapshot, scope or current invocation')
            scope = TypeAdapter(ScopeRef).validate_python(action_input['scope'])
            if context.scope != scope:
                raise TaskConflict('Government scheduling recovery changes original requested review coverage')
            reading.check_method_context(context, 'GOV-A03')
            proof_rows, versions, proof_refs = [], [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or row.scope != scope:
                    raise TaskConflict('Government scheduling recovery lacks exact scoped original/current sources')
                proof_rows.append(row)
                return row

            for raw in (original_input, action_input):
                bases = {field: read(ref_type(kind).model_validate(raw[field]), schema) for field, kind, schema in _BASES}
                case, queue, profile, calendar = (bases[field] for field, _, _ in _BASES)
                work = read(profile.work_profile_ref, GovSchedulingWorkProfileView)
                rule = read(queue.ordering_rule_ref, GovQueueRuleView)
                tasks = {key: read(ref, GovSchedulingTaskView) for key, ref in indexed(
                    [ref_type('Task').model_validate(ref) for ref in raw['task_refs']]).items()}
                assignments = {key: read(ref, GovReviewAssignmentView) for key, ref in indexed(
                    [ref_type('ReviewAssignment').model_validate(ref) for ref in raw['existing_assignment_refs']]).items()}
                if (any(row.organization_id != source['organization_id'] for row in (*bases.values(), work, rule))
                        or case.queue_ref != queue.ref or profile.case_ref != case.ref or profile.queue_ref != queue.ref
                        or rule.queue_ref != queue.ref
                        or condition_code not in _PRETASK_CODES and (profile.choice == 'request_cooperation'
                            or {row.ref for row in tasks.values()} != set(case.task_refs) or not tasks)):
                    raise TaskConflict('Government scheduling recovery substitutes original agency/case/queue or task planning set')
                for task in tasks.values():
                    if (task.organization_id != source['organization_id'] or task.case_ref != case.ref
                            or task.work_profile_ref != work.ref):
                        raise TaskConflict('Government scheduling recovery borrows another agency/case task or work profile')
                for assignment in assignments.values():
                    task = tasks.get(assignment.task_ref.key()[:2])
                    if (task is None or task.ref != assignment.task_ref or task.existing_assignment_ref != assignment.ref
                            or assignment.organization_id != source['organization_id'] or assignment.case_ref != case.ref
                            or assignment.work_profile_ref != work.ref):
                        raise TaskConflict('Government scheduling recovery borrows another original task assignment')
                versions.append(dict(**bases, work=work, rule=rule, tasks=tasks, assignments=assignments))
            old, current = versions
            capacity_wait = condition_code == _CAPACITY_CODE
            case_wait = condition_code in _PRETASK_CODES
            handoff_wait = condition_code == _HANDOFF_CODE
            key = next(iter(old['tasks']), None) if capacity_wait or case_wait else waited[0].key()[:2]
            if not (capacity_wait or case_wait) and (key not in old['tasks'] or old['tasks'][key].ref != waited[0]):
                raise TaskConflict('Government scheduling wait differs from its original full task input')
            if capacity_wait and tuple(waited) != (old['case_ref'].ref, old['queue_ref'].ref, old['capacity_ref'].ref):
                raise TaskConflict('Government capacity wait differs from its original case/queue/calendar input')
            if case_wait and condition_code != _QUEUE_ORDER_CODE and waited[0] != old['case_ref'].ref:
                raise TaskConflict('Government case wait differs from its original case input')
            if condition_code == _QUEUE_ORDER_CODE and waited[0] != old['queue_ref'].ref:
                raise TaskConflict('Government FIFO wait differs from its original queue input')
            if condition_code == _CASE_INPUT_CODE and waited[1] != old['queue_ref'].ref:
                raise TaskConflict('Government case-input wait differs from its original queue input')
            if (any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field, _, _ in _BASES)
                    or old['work'].ref.key()[:2] != current['work'].ref.key()[:2]
                    or old['rule'].ref.key()[:2] != current['rule'].ref.key()[:2]
                    or (False if handoff_wait else bool(old['tasks'].keys() - current['tasks'].keys()) if case_wait
                        else old['tasks'].keys() != current['tasks'].keys())
                    or (False if handoff_wait else bool(old['assignments'].keys() - current['assignments'].keys()) if case_wait
                        else old['assignments'].keys() != current['assignments'].keys())
                    or old['ordering_profile_ref'].choice != current['ordering_profile_ref'].choice
                    or old['case_ref'].matter_ref != current['case_ref'].matter_ref
                    or old['case_ref'].jurisdiction_ref.key()[:2] != current['case_ref'].jurisdiction_ref.key()[:2]
                    or old['case_ref'].region_id != current['case_ref'].region_id):
                raise TaskConflict('Government scheduling recovery rewrites original case, review choice or complete task/assignment identities')
            for task_key, task in current['tasks'].items():
                if (case_wait or handoff_wait) and task_key not in old['tasks']:
                    continue  # Native validation authenticates newly published tasks; original histories remain intact.
                original = old['tasks'][task_key]
                if (any(getattr(original, field) != getattr(task, field) for field in (
                        'execution_action_id', 'function_code', 'discipline_codes'))
                        or original.function_ref.key()[:2] != task.function_ref.key()[:2]
                        or original.estimate_ref.key()[:2] != task.estimate_ref.key()[:2]
                        or set(indexed(original.work_fact_refs)) - set(indexed(task.work_fact_refs))
                        or set(indexed(original.dependency_refs)) != set(indexed(task.dependency_refs))
                        or (None if original.existing_assignment_ref is None else original.existing_assignment_ref.key()[:2])
                            != (None if task.existing_assignment_ref is None else task.existing_assignment_ref.key()[:2])
                        or {row.resource_ref.key()[:2]: row.share for row in original.resource_shares}
                            != {row.resource_ref.key()[:2]: row.share for row in task.resource_shares}):
                    raise TaskConflict('Government scheduling recovery rewrites original task function, effort history or resource/assignment ownership')
            task, now = current['tasks'].get(key), context.business_time
            dependency, relation_details = None, {}
            capacity_input = None
            if handoff_wait:
                handoff = read_government_scheduling_handoff(reading=reading, original=old, current=current,
                    waited=waited, completed_task_ref=selected.completed_task_ref, now=now, read=read)
                if isinstance(handoff, str):
                    return handoff
                completion = handoff['completion']
                proof_rows.extend(row for row, _ in completion['proof_rows'])
                proof_refs.extend(ref for ref, _ in completion['proof_refs'])
                relation_details = dict(condition_code=condition_code, handoff_history=dict(
                    completed_task=handoff['completed_task'].model_dump(mode='json'),
                    released_assignment=None if handoff['released_assignment'] is None
                        else handoff['released_assignment'].model_dump(mode='json'),
                    completed_work_history=completion['histories']))
            if condition_code == _QUEUE_ORDER_CODE:
                status, queue_order_history = government_scheduling_queue_order_history(
                    original=old, current=current, waited=waited, now=now)
                if status != 'ready':
                    return status
                relation_details = dict(condition_code=condition_code, queue_order_history=queue_order_history)
            if condition_code == _PRIORITY_CODE:
                status, priority_history = government_scheduling_priority_history(original=old, current=current,
                    waited=waited, context=context, read=read, resolve=reading.resolve, proof_refs=proof_refs)
                if status != 'ready':
                    return status
                relation_details = dict(condition_code=condition_code, priority_history=priority_history)
            if condition_code == _CASE_CODE:
                if old['case_ref'].status not in {'closed', 'withdrawn'}:
                    raise TaskConflict('Government case recovery does not match an original closed or withdrawn case')
                if current['case_ref'].status in {'closed', 'withdrawn'}:
                    return 'waiting'
                relation_details = dict(condition_code=condition_code, case_history=dict(
                    original=old['case_ref'].model_dump(mode='json'), current=current['case_ref'].model_dump(mode='json')))
            if condition_code == _CASE_INPUT_CODE:
                old_queue, queue = old['queue_ref'], current['queue_ref']
                if old['case_ref'].status in {'closed', 'withdrawn'} or old_queue.coverage != 'complete':
                    raise TaskConflict('Government case-input recovery lacks its original open case and complete queue')
                selected_entries = []
                for version, time in ((old, old_queue.as_of), (current, now)):
                    rows = version['queue_ref'].entries
                    if len({row.case_ref.key()[:2] for row in rows}) != len(rows):
                        raise TaskConflict('Government case-input recovery duplicates a physical queued case')
                    if any(row.entered_at.clock_ref != time.clock_ref or row.entered_at.offset > time.offset for row in rows):
                        raise TaskConflict('Government case-input recovery includes a future or foreign-clock queue entry')
                    selected_entries.append(next((row for row in rows if row.case_ref == version['case_ref'].ref), None))
                original_entry, entry = selected_entries
                if original_entry is None or original_entry.status in {'ready', 'assigned'}:
                    raise TaskConflict('Government case-input recovery does not match an original queue input wait')
                if (current['case_ref'].status in {'closed', 'withdrawn'} or queue.coverage != 'complete'
                        or queue.as_of != now or entry is None or entry.status not in {'ready', 'assigned'}):
                    return 'waiting'
                if original_entry.entered_at != entry.entered_at:
                    raise TaskConflict('Government case-input recovery rewrites original lawful queue receipt time')
                relation_details = dict(condition_code=condition_code, case_input_history=dict(
                    original_case=old['case_ref'].model_dump(mode='json'), case=current['case_ref'].model_dump(mode='json'),
                    original_entry=original_entry.model_dump(mode='json'), entry=entry.model_dump(mode='json')))
            if capacity_wait:
                original_capacity = read_government_scheduling_capacity(version=old, read=read,
                    resolve=reading.resolve, proof_refs=proof_refs, now=old['capacity_ref'].as_of)
                if isinstance(original_capacity, str):
                    raise TaskConflict('Government capacity recovery lacks its original complete authorized scheduling snapshot')
                capacity = read_government_scheduling_capacity(version=current, read=read,
                    resolve=reading.resolve, proof_refs=proof_refs, now=now)
                if isinstance(capacity, str):
                    return capacity
                capacity_input = capacity['input']
                relation_details = dict(condition_code=condition_code, capacity_history=dict(
                    original=original_capacity['history'], current=capacity['history'],
                    original_input=original_capacity['input'].model_dump(mode='json')))
            if condition_code in {_EFFORT_CODE, _ACTUAL_EFFORT_CODE}:
                original_task = old['tasks'][key]
                actual_wait = condition_code == _ACTUAL_EFFORT_CODE
                if (original_task.status != 'authorized'
                        or not actual_wait and waited[1] != original_task.estimate_ref
                        or actual_wait and waited[1] not in original_task.work_fact_refs):
                    raise TaskConflict('Government effort wait replaces its original authorized task estimate')
                original_estimate = read(original_task.estimate_ref, GovSchedulingEstimateView)
                estimate = read(task.estimate_ref, GovSchedulingEstimateView)
                for row, owner, work in ((original_estimate, original_task, old['work']),
                        (estimate, task, current['work'])):
                    if (row.task_ref != owner.ref or row.work_profile_ref != work.ref
                            or row.effort.unit != work.effort_unit or row.executed_at.clock_ref != owner.as_of.clock_ref
                            or row.available_at.clock_ref != owner.as_of.clock_ref):
                        raise TaskConflict('Government effort recovery borrows another task/method/unit or clock')
                original_estimate_ready = (original_estimate.status == 'succeeded'
                        and original_estimate.executed_at.offset <= min(original_task.as_of.offset, original_estimate.available_at.offset)
                        and original_task.work_fact_coverage == 'complete')
                if original_estimate_ready != actual_wait:
                    raise TaskConflict('Government effort recovery does not match its original estimate/history gate')
                waited_history = {}
                if actual_wait:
                    if decimal_fraction(original_estimate.effort.value) <= 0:
                        raise TaskConflict('Government actual-effort wait requires its original positive successful estimate')
                    original_fact = read(waited[1], GovSchedulingWorkFactView)
                    fact_ref = indexed(task.work_fact_refs)[waited[1].key()[:2]]
                    current_fact = read(fact_ref, GovSchedulingWorkFactView)
                    if (original_fact.task_ref != original_task.ref
                            or original_fact.organization_id != source['organization_id']
                            or original_fact.effort.unit != old['work'].effort_unit
                            or original_fact.window.start.clock_ref != original_task.as_of.clock_ref
                            or original_fact.available_at.clock_ref != original_task.as_of.clock_ref
                            or original_fact.window.bounds != 'closed_open'
                            or original_fact.window.end.offset <= original_fact.window.start.offset
                            or current_fact.task_ref != task.ref
                            or original_fact.investment_key != current_fact.investment_key
                            or original_fact.status == 'committed' and original_fact.window.end.offset
                                <= min(original_task.as_of.offset, original_fact.available_at.offset)):
                        raise TaskConflict('Government actual-effort recovery replaces its original pending investment or task/time')
                    waited_history = dict(original_waited_work_fact=original_fact.model_dump(mode='json'),
                        waited_work_fact=current_fact.model_dump(mode='json'))
                if (estimate.status != 'succeeded' or estimate.available_at.offset > now.offset
                        or estimate.executed_at.offset > min(now.offset, estimate.available_at.offset)
                        or task.work_fact_coverage != 'complete'):
                    return 'waiting'
                remaining = decimal_fraction(estimate.effort.value)
                if remaining <= 0:
                    raise TaskConflict('Government effort recovery requires a positive successful original estimate')
                facts, original_facts, investments = [], [], set()
                old_facts = indexed(original_task.work_fact_refs)
                for ref in task.work_fact_refs:
                    fact = read(ref, GovSchedulingWorkFactView)
                    if (fact.task_ref != task.ref or fact.organization_id != source['organization_id']
                            or fact.effort.unit != current['work'].effort_unit or fact.investment_key in investments
                            or fact.window.bounds != 'closed_open' or fact.window.start.clock_ref != now.clock_ref
                            or fact.window.end.offset <= fact.window.start.offset
                            or fact.available_at.clock_ref != now.clock_ref):
                        raise TaskConflict('Government effort recovery substitutes or duplicates actual investment/task/unit/time')
                    investments.add(fact.investment_key)
                    if (fact.status != 'committed' or fact.available_at.offset > now.offset
                            or fact.window.end.offset > min(now.offset, fact.available_at.offset)):
                        return 'waiting'
                    spent = decimal_fraction(fact.effort.value)
                    if spent <= 0:
                        raise TaskConflict('Government effort recovery cannot count waiting as positive actual investment')
                    remaining -= spent
                    facts.append(fact.model_dump(mode='json'))
                    old_ref = old_facts.get(ref.key()[:2])
                    if old_ref is not None and old_ref.key() in reading._resolver._objects:
                        original_fact = read(old_ref, GovSchedulingWorkFactView)
                        if (original_fact.task_ref != original_task.ref
                                or original_fact.organization_id != source['organization_id']
                                or original_fact.investment_key != fact.investment_key):
                            raise TaskConflict('Government effort recovery rewrites an original actual investment identity')
                        original_facts.append(original_fact.model_dump(mode='json'))
                if not isinstance(task.remaining_effort, Known):
                    return 'waiting'
                declared = task.remaining_effort.value
                if (declared.unit != current['work'].effort_unit or remaining < 0
                        or decimal_fraction(declared.value) != remaining):
                    raise TaskConflict('Government remaining effort differs from successful estimate minus actual investment')
                proof_refs.append(declared.basis_ref)
                relation_details = dict(condition_code=condition_code, effort_history=dict(
                    original_estimate=original_estimate.model_dump(mode='json'), estimate=estimate.model_dump(mode='json'),
                    original_work_facts=original_facts, work_facts=facts,
                    remaining_effort=declared.model_dump(mode='json'), **waited_history))
            if condition_code == _WINDOW_CODE:
                original_task = old['tasks'][key]
                original_window, planned = original_task.planned_window, task.planned_window
                original_duration = original_window.end.offset - original_window.start.offset
                if (original_task.status != 'authorized'
                        or original_window.bounds != 'closed_open' or original_duration <= 0
                        or original_window.start.clock_ref != original_task.as_of.clock_ref
                        or not (original_window.start.offset < original_task.as_of.offset
                            or original_duration > old['work'].maximum_assignment_ticks)):
                    raise TaskConflict('Government window recovery does not match its original expired or excessive task window')
                jurisdictions = []
                for version in (old, current):
                    ref = version['case_ref'].jurisdiction_ref
                    jurisdiction = reading.resolve(ref)
                    if (not isinstance(jurisdiction, GovJurisdictionView) or jurisdiction.ref != ref
                            or jurisdiction.organization_id != source['organization_id']):
                        raise TaskConflict('Government window recovery replaces original agency jurisdiction')
                    jurisdictions.append(jurisdiction)
                    proof_rows.append(jurisdiction)
                relation_details = dict(condition_code=condition_code, window_history=dict(
                    original=original_window.model_dump(mode='json'), current=planned.model_dump(mode='json'),
                    original_as_of=original_task.as_of.model_dump(mode='json'),
                    original_maximum_assignment_ticks=old['work'].maximum_assignment_ticks,
                    current_maximum_assignment_ticks=current['work'].maximum_assignment_ticks,
                    original_jurisdiction=jurisdictions[0].model_dump(mode='json'),
                    current_jurisdiction=jurisdictions[1].model_dump(mode='json')))
                duration = planned.end.offset - planned.start.offset
                if (planned.bounds != 'closed_open' or planned.start.clock_ref != now.clock_ref
                        or duration <= 0 or planned.start.offset < now.offset
                        or duration > current['work'].maximum_assignment_ticks):
                    return 'waiting'
                for validity in (current['work'].effective_window, jurisdictions[1].effective_window):
                    if (validity.bounds != 'closed_open' or validity.start.clock_ref != now.clock_ref
                            or validity.start.offset > planned.start.offset or validity.end.offset < planned.end.offset):
                        return 'unavailable'
                if (not jurisdictions[1].effective_window.contains(now)
                        or not any(scope_covers(covered, scope) for covered in jurisdictions[1].covered_scopes)):
                    return 'unavailable'
            if condition_code == _DEPENDENCY_CODE:
                original_task = old['tasks'][key]
                if waited[1] not in original_task.dependency_refs or original_task.status != 'authorized':
                    raise TaskConflict('Government dependency wait differs from its original authorized task dependency')
                dependency_ref = indexed(task.dependency_refs)[waited[1].key()[:2]]
                original_dependency = read(waited[1], GovSchedulingDependencyView)
                dependency = read(dependency_ref, GovSchedulingDependencyView)
                if (original_dependency.task_ref != original_task.ref or dependency.task_ref != task.ref
                        or original_dependency.as_of != original_task.as_of
                        or isinstance(original_dependency.satisfied, Known) and original_dependency.satisfied.value):
                    raise TaskConflict('Government dependency recovery replaces the original task/time or unmet dependency')
                relation_details = dict(condition_code=condition_code, dependency_history=dict(
                    original=original_dependency.model_dump(mode='json'), current=dependency.model_dump(mode='json')))
            if not (case_wait or handoff_wait) and (task.status != 'authorized' or task.as_of != now):
                return 'waiting'
            if condition_code == _AVAILABILITY_CODE:
                status, availability_history = government_scheduling_availability_history(
                    original=old, current=current, task_key=key, waited=waited, now=now, read=read)
                if status != 'ready':
                    return status
                relation_details = dict(condition_code=condition_code, availability_history=availability_history)
            if condition_code in _REVIEWER_CODES:
                authorization_wait = condition_code == _AUTHORIZATION_CODE
                qualification_wait = condition_code == _QUALIFICATION_CODE
                discipline_wait = condition_code == _DISCIPLINE_CODE
                resources, qualifications = [], []

                def covers(validity, planned):
                    return (validity.bounds == planned.bounds == 'closed_open'
                        and validity.start.clock_ref == planned.start.clock_ref
                        and planned.end.offset > planned.start.offset
                        and validity.start.offset <= planned.start.offset
                        and validity.end.offset >= planned.end.offset)

                for version in (old, current):
                    owner = version['tasks'][key]
                    refs = indexed([share.resource_ref for share in owner.resource_shares])
                    ref = refs.get(waited[1].key()[:2])
                    embedded = next((row for row in version['capacity_ref'].resources if row.ref == ref), None)
                    if ref is None or embedded is None or version is old and ref != waited[1]:
                        raise TaskConflict('Government qualification wait replaces its original task reviewer/calendar')
                    resource = read(ref, GovReviewResourceView)
                    if (resource != embedded or resource.organization_id != source['organization_id']
                            or not isinstance(resource.personnel_ids, Known) or not resource.personnel_ids.value
                            or len(set(resource.personnel_ids.value)) != len(resource.personnel_ids.value)):
                        raise TaskConflict('Government qualification recovery lacks exact actual reviewer personnel')
                    indexed(resource.qualification_refs)
                    resources.append(resource)
                    qualifications.append([read(ref, GovReviewQualificationView) for ref in resource.qualification_refs
                        if qualification_wait or ref.key() in reading._resolver._objects])
                if old['tasks'][key].status != 'authorized':
                    raise TaskConflict('Government qualification wait lacks its original authorized task')

                def qualified(resource, rows, owner, case):
                    if not isinstance(case.region_id, Known) or resource.region_id != case.region_id.value:
                        return False
                    return all(any(row.organization_id == source['organization_id'] and row.region_id == case.region_id.value
                        and person in row.personnel_ids and discipline in row.discipline_codes
                        and owner.function_code in row.function_codes and isinstance(row.valid, Known) and row.valid.value
                        and covers(row.effective_window, owner.planned_window) for row in rows)
                        for person in resource.personnel_ids.value for discipline in owner.discipline_codes)

                if qualification_wait and qualified(resources[0], qualifications[0], old['tasks'][key], old['case_ref']):
                    raise TaskConflict('Government qualification recovery does not match an original missing reviewer qualification')
                if discipline_wait:
                    original_task, original_resource = old['tasks'][key], resources[0]
                    if (set(original_task.discipline_codes) <= set(original_resource.discipline_codes)
                            and original_task.function_code in original_resource.function_codes):
                        raise TaskConflict('Government discipline recovery does not match original reviewer discipline/function gap')
                resource = resources[1]
                if (current['capacity_ref'].coverage != 'complete' or current['capacity_ref'].as_of != now
                        or resource.available_at.clock_ref != now.clock_ref or resource.available_at.offset > now.offset
                        or not covers(resource.effective_window, task.planned_window)
                        or not set(task.discipline_codes) <= set(resource.discipline_codes)
                        or task.function_code not in resource.function_codes
                        or not isinstance(current['case_ref'].region_id, Known)
                        or resource.region_id != current['case_ref'].region_id.value
                        or qualification_wait and (any(row.available_at.clock_ref != now.clock_ref
                            or row.available_at.offset > now.offset for row in qualifications[1])
                            or not qualified(resource, qualifications[1], task, current['case_ref']))):
                    return 'waiting'

                def reviewer_authority(reviewer):
                    grant, function = reading.resolve(reviewer.authority_ref), reading.resolve(reviewer.function_ref)
                    if (not isinstance(grant, Authorization) or grant.ref != reviewer.authority_ref
                            or not isinstance(function, RoleAssignment) or function.function_ref != reviewer.function_ref
                            or grant.actor_id != reviewer.actor_id or grant.organization_id != source['organization_id']
                            or grant.function_ref != reviewer.function_ref):
                        raise TaskConflict('Government reviewer recovery borrows another reviewer authorization')
                    proof_refs.extend([*grant.basis_refs, *function.basis_refs])
                    return grant, function

                def eligible(grant, function, owner, time):
                    return (function.role == 'Government' and owner.execution_action_id in grant.action_ids
                        and grant.validity.contains(time) and covers(grant.validity, owner.planned_window)
                        and any(scope_covers(covered, scope) for covered in grant.scopes))

                original_authority = {}
                if authorization_wait:
                    original_grant, original_function = reviewer_authority(resources[0])
                    if eligible(original_grant, original_function, old['tasks'][key], old['tasks'][key].as_of):
                        raise TaskConflict('Government authorization recovery does not match an original reviewer action/scope/window gap')
                    original_authority = dict(original_reviewer_authority=original_grant.model_dump(mode='json'),
                        original_reviewer_function=original_function.model_dump(mode='json'))
                grant, function = reviewer_authority(resource)
                if not discipline_wait and not eligible(grant, function, task, now):
                    return 'waiting'
                reviewer_history = dict(
                    original_resource=resources[0].model_dump(mode='json'), resource=resource.model_dump(mode='json'),
                    original_qualifications=[row.model_dump(mode='json') for row in qualifications[0]],
                    qualifications=[row.model_dump(mode='json') for row in qualifications[1]],
                    reviewer_authority=grant.model_dump(mode='json'), reviewer_function=function.model_dump(mode='json'),
                    **original_authority)
                relation_details = dict(condition_code=condition_code,
                    **{'authorization_history' if authorization_wait else 'discipline_history' if discipline_wait
                        else 'qualification_history': reviewer_history})
            if dependency is not None and (dependency.as_of != now
                    or not isinstance(dependency.satisfied, Known) or not dependency.satisfied.value):
                return 'waiting'
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in (*[current[field] for field, _, _ in _BASES],
                        current['work'], current['rule'], *([] if case_wait or handoff_wait else [task]),
                        *([] if dependency is None else [dependency]))):
                return 'unavailable'
            for authority_ref, function_ref in [(current['ordering_profile_ref'].authority_ref, context.function_ref),
                    *([] if case_wait else [(row.authority_ref, row.function_ref) for row in current['tasks'].values()])]:
                grant, function = reading.resolve(authority_ref), reading.resolve(function_ref)
                if (not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment)
                        or function.role != 'Government' or function.function_ref != function_ref
                        or grant.actor_id != context.actor_id or grant.organization_id != source['organization_id']
                        or grant.function_ref != function_ref or 'GOV-A03' not in grant.action_ids
                        or not grant.validity.contains(now) or not any(scope_covers(s, scope) for s in grant.scopes)):
                    raise TaskConflict('Government scheduling recovery lacks actual current agency/task authority')
                proof_refs.extend([*grant.basis_refs, *function.basis_refs])
            for row in proof_rows:
                proof_refs.extend(ref for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Government scheduling recovery requires observed native task/queue/assignment evidence')
                evidence[ref.key()] = row.model_dump(mode='json')

            if capacity_input is not None:
                result = reading.calculate(CAPACITY_METHOD, capacity_input)
                if result.kind in {'technical_error', 'invalid_input'}:
                    raise TaskConflict('Government recovery capacity calculation failed; inspect original method evidence')
                if result.kind != 'ok':
                    return 'unavailable'
                report = CapacityReport.model_validate(result.value)
                if not report.feasible:
                    return 'waiting'
                relation_details['capacity_result'] = dict(input=capacity_input.model_dump(mode='json'),
                    report=report.model_dump(mode='json'), method_result=result.model_dump(mode='json'))

            def history(version):
                return {field: [row.model_dump(mode='json') for row in value.values()] if isinstance(value, dict)
                    else value.model_dump(mode='json') for field, value in version.items()}

            if validate_relation(source_identity=deepcopy(source), original_action_input=original_input, action_input=action_input,
                    original_sources=history(old), current_sources=history(current), evidence=deepcopy(list(evidence.values())),
                    scheduling_sources=deepcopy(selected.scheduling_sources),
                    unavailable_targets=deepcopy(selected.unavailable_targets),
                    context=context.model_copy(deep=True), reading=reading, **deepcopy(relation_details)) is not True:
                raise TaskConflict('Government scheduling recovery lacks native original-task readiness and lawful queue/occupancy history validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('GOV-A03', condition_code, '1', frozenset({'dependency_change'}), evaluate)


def government_original_scheduling_profiles(read_current, validate_relation):
    return tuple(government_original_scheduling_task_profile(read_current, validate_relation, condition_code=code)
        for code in _CODES)


def government_original_scheduling_dependency_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_DEPENDENCY_CODE)


def government_original_scheduling_window_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_WINDOW_CODE)


def government_original_scheduling_effort_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_EFFORT_CODE)


def government_original_scheduling_actual_effort_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_ACTUAL_EFFORT_CODE)


def government_original_scheduling_qualification_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_QUALIFICATION_CODE)


def government_original_scheduling_authorization_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_AUTHORIZATION_CODE)


def government_original_scheduling_discipline_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_DISCIPLINE_CODE)


def government_original_scheduling_availability_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_AVAILABILITY_CODE)


def government_original_scheduling_capacity_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_CAPACITY_CODE)


def government_original_scheduling_case_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_CASE_CODE)


def government_original_scheduling_case_input_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_CASE_INPUT_CODE)


def government_original_scheduling_priority_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_PRIORITY_CODE)


def government_original_scheduling_queue_order_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_QUEUE_ORDER_CODE)


def government_original_scheduling_handoff_profile(read_current, validate_relation):
    return government_original_scheduling_task_profile(read_current, validate_relation, condition_code=_HANDOFF_CODE)
