"""Read original GOV-A03 task, queue and reviewer histories for guarded recovery."""
from copy import deepcopy
from dataclasses import dataclass

from integration.government_inspection_reader import (
    GovernmentInspectionReader, GovernmentInspectionRecoverySettings, GovernmentInspectionRecoveryBindings,
    _build_assembled_government_dispatcher,
)
from integration.government_scheduling_actions import GovernmentSchedulingActionAssembler
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, ref_type, walk_references
from src.actions.contracts.government_objects import (
    GovMatterView, GovJurisdictionView, GovRecipientView, GovResponseRequirementView,
)
from src.actions.contracts.government_scheduling_objects import (
    GovSchedulingCaseView, GovCaseQueueView, GovQueueProfileView, GovQueueRuleView,
    GovSchedulingWorkProfileView, GovSchedulingTaskView, GovSchedulingEstimateView,
    GovSchedulingWorkFactView, GovSchedulingDependencyView, GovReviewCalendarView,
    GovReviewResourceView, GovReviewQualificationView, GovReviewAssignmentView,
    GovSchedulingPriorityView, GovPriorityAuthorityView, GovSchedulingQuestionView,
)
from src.coordination.government_scheduling_conditions import (
    GovernmentSchedulingConditionReading, _CODE, _DEPENDENCY_CODE, _EFFORT_CODE, _ACTUAL_EFFORT_CODE,
    _QUALIFICATION_CODE, _REVIEWER_CODES, _AVAILABILITY_CODE, _CAPACITY_CODE,
    _CASE_CODE, _CASE_INPUT_CODE, _PRIORITY_CODE, _QUEUE_ORDER_CODE, _PRETASK_CODES, _HANDOFF_CODE, _CODES, _BASES,
)
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.capacity import CapacityCommitment
from src.organization.models import Authorization, RoleAssignment


@dataclass(frozen=True)
class GovernmentSchedulingCurrentSelection:
    request: RoleContractInvocation
    completed_task_ref: Reference | None = None
    completed_task_refs: tuple[Reference, ...] = ()


class GovernmentSchedulingRecoverySettings(GovernmentInspectionRecoverySettings):
    """Original A03 source/policy/binding versions."""
    terminal_handoff_enabled: bool = False


@dataclass(frozen=True)
class GovernmentSchedulingRecoveryBindings(GovernmentInspectionRecoveryBindings):
    """Actual A03 selector, source guard and independent native validators."""


class GovernmentSchedulingReader(GovernmentInspectionReader):
    """Assemble fresh scheduling sources without assigning or reserving reviewers."""
    ACTION_ID = 'GOV-A03'
    CONDITION_CODE = _CODE
    CONDITION_CODES = _CODES
    ASSEMBLER_TYPE = GovernmentSchedulingActionAssembler
    READER_SCHEMA = 'government-scheduling-reader.v1'

    def __call__(self, check):
        self._check()
        source, waited = check.source['identity'], check.condition.object_refs
        dependency_wait = check.condition.condition_code == _DEPENDENCY_CODE
        effort_wait = check.condition.condition_code == _EFFORT_CODE
        actual_wait = check.condition.condition_code == _ACTUAL_EFFORT_CODE
        qualification_wait = check.condition.condition_code == _QUALIFICATION_CODE
        reviewer_wait = check.condition.condition_code in _REVIEWER_CODES
        availability_wait = check.condition.condition_code == _AVAILABILITY_CODE
        capacity_wait = check.condition.condition_code == _CAPACITY_CODE
        case_wait = check.condition.condition_code in _PRETASK_CODES
        priority_wait = check.condition.condition_code == _PRIORITY_CODE
        queue_order_wait = check.condition.condition_code == _QUEUE_ORDER_CODE
        handoff_wait = check.condition.condition_code == _HANDOFF_CODE
        expected_kinds = (('Task', 'Dependency') if dependency_wait
            else ('Task', 'WorkEstimate') if effort_wait
            else ('Task', 'WorkFact') if actual_wait
            else ('Task', 'ResourceCalendar') if availability_wait
            else ('RegulatoryCase', 'CaseQueue', 'ResourceCalendar') if capacity_wait
            else ('RegulatoryCase',) if check.condition.condition_code == _CASE_CODE
            else ('RegulatoryCase', 'CaseQueue') if check.condition.condition_code == _CASE_INPUT_CODE
            else ('RegulatoryCase', 'PriorityBasis') if priority_wait
            else ('CaseQueue', *('RegulatoryCase' for _ in waited[1:])) if queue_order_wait
            else ('Task', 'Resource') if reviewer_wait else ('Task',))
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code not in self.CONDITION_CODES or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or tuple(ref.kind for ref in waited) != expected_kinds
                or queue_order_wait and len(waited) < 2):
            raise TaskConflict('Government scheduling reader replaces its original task wait or agency')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if not (capacity_wait or case_wait) and waited[0] not in original_input.task_refs:
            raise TaskConflict('Government scheduling wait differs from its original task input')
        if capacity_wait and tuple(waited) != (original_input.case_ref, original_input.queue_ref, original_input.capacity_ref):
            raise TaskConflict('Government capacity wait differs from its original case/queue/calendar')
        if availability_wait and waited[1] != original_input.capacity_ref:
            raise TaskConflict('Government availability wait differs from its original capacity calendar')
        if case_wait and not queue_order_wait and waited[0] != original_input.case_ref:
            raise TaskConflict('Government case wait differs from its original case snapshot')
        if queue_order_wait and waited[0] != original_input.queue_ref:
            raise TaskConflict('Government FIFO wait differs from its original queue snapshot')
        if check.condition.condition_code == _CASE_INPUT_CODE and waited[1] != original_input.queue_ref:
            raise TaskConflict('Government case-input wait differs from its original queue snapshot')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, GovernmentSchedulingCurrentSelection):
            raise TaskConflict('Government scheduling reader requires typed explicit current invocation')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        completed_task_ref = None
        completed_task_refs = ()
        if selected.completed_task_refs:
            if not handoff_wait:
                raise TaskConflict('Government terminal completion sources require their original handoff wait')
            completed_task_refs = tuple(ref_type('Task').model_validate(ref) for ref in selected.completed_task_refs)
            if len({ref.key()[:2] for ref in completed_task_refs}) != len(completed_task_refs):
                raise TaskConflict('Government terminal handoff duplicates a physical completion task')
        if selected.completed_task_ref is not None:
            if not handoff_wait:
                raise TaskConflict('Government scheduling completion source supplied outside its original handoff wait')
            completed_task_ref = ref_type('Task').model_validate(selected.completed_task_ref)
            if completed_task_ref.key()[:2] != waited[0].key()[:2]:
                raise TaskConflict('Government handoff reader substitutes original completed-task identity')
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope']
                or current_input.scope != original_input.scope
                or any(getattr(original_input, field).key()[:2] != getattr(current_input, field).key()[:2]
                    for field, _, _ in _BASES)
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Government scheduling reader changes original scope/case/queue or visible historical sources')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        reading = prepared.reading
        baseline = deepcopy(reading.evidence())
        sources, missing = {}, {}
        try:
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('Government scheduling assembly changes its original source snapshot or agency')
            for ref in walk_references(original_input):
                reading.resolve(ref)

            def read(ref, schema):
                row = reading.resolve(ref)
                actual_ref = getattr(row, 'ref', getattr(row, 'function_ref', getattr(row, 'commitment_ref', None)))
                if not isinstance(row, schema) or actual_ref != ref:
                    raise TaskConflict('Government scheduling history lacks an exact original/current source')
                for evidence_ref in walk_references(row):
                    if evidence_ref.kind == 'Evidence':
                        reading.resolve(evidence_ref)
                sources[ref.key()] = row.model_dump(mode='json')
                return row

            def authority(ref, function_ref):
                grant, function = read(ref, Authorization), read(function_ref, RoleAssignment)
                if grant.function_ref != function_ref:
                    raise TaskConflict('Government scheduling history substitutes original agency/function authority')
                for basis_ref in (*grant.basis_refs, *function.basis_refs):
                    reading.resolve(basis_ref)

            def supplied(ref):
                if ref.key() in reading._resolver._objects:
                    return True
                # Original waits may precede reading later effort/eligibility targets.
                # Keep omissions explicit for native validation; they prove no readiness.
                missing[ref.key()] = ref.model_dump(mode='json')
                return False

            for action_input in (original_input, prepared.action_input):
                case = read(action_input.case_ref, GovSchedulingCaseView)
                queue = read(action_input.queue_ref, GovCaseQueueView)
                if queue_order_wait:
                    prior_ids = {ref.key()[:2] for ref in waited[1:]}
                    refs = [*waited[1:], *[row.case_ref for row in queue.entries if row.case_ref.key()[:2] in prior_ids]]
                    for ref in {ref.key(): ref for ref in refs}.values():
                        if supplied(ref):
                            earlier_case = read(ref, GovSchedulingCaseView)
                            if earlier_case.organization_id != source['organization_id'] or earlier_case.queue_ref.key()[:2] != queue.ref.key()[:2]:
                                raise TaskConflict('Government FIFO history borrows another agency/queue earlier case')
                profile = read(action_input.ordering_profile_ref, GovQueueProfileView)
                work = read(profile.work_profile_ref, GovSchedulingWorkProfileView)
                read(queue.ordering_rule_ref, GovQueueRuleView)
                read(case.matter_ref, GovMatterView)
                read(case.jurisdiction_ref, GovJurisdictionView)
                profile_grant = read(profile.authority_ref, Authorization)
                authority(profile.authority_ref, profile_grant.function_ref)
                if case_wait:
                    for ref in profile.question_refs:
                        if not supplied(ref):
                            continue
                        question = read(ref, GovSchedulingQuestionView)
                        if question.case_ref != case.ref:
                            raise TaskConflict('Government case recovery borrows another cooperation question')
                        for target in question.question.target_refs:
                            if supplied(target):
                                read(target, GovSchedulingQuestionView)
                        for recipient in question.question.recipient_refs:
                            if supplied(recipient):
                                read(recipient, GovRecipientView)
                        if supplied(question.question.response_requirement_ref):
                            read(question.question.response_requirement_ref, GovResponseRequirementView)
                if priority_wait and (profile.priority_basis_ref is None
                        or action_input is original_input and profile.priority_basis_ref != waited[1]):
                    raise TaskConflict('Government priority reader replaces its exact original waited priority basis')
                if profile.priority_basis_ref is not None and (priority_wait or supplied(profile.priority_basis_ref)):
                    priority = read(profile.priority_basis_ref, GovSchedulingPriorityView)
                    grant = read(priority.authority_ref, Authorization)
                    authority(grant.ref, grant.function_ref)
                    if priority_wait or supplied(priority.priority_authority_ref):
                        read(priority.priority_authority_ref, GovPriorityAuthorityView)
                for ref in action_input.task_refs:
                    task = read(ref, GovSchedulingTaskView)
                    if task.case_ref != case.ref or task.work_profile_ref != work.ref:
                        raise TaskConflict('Government scheduling task borrows another original case/work profile')
                    authority(task.authority_ref, task.function_ref)
                    selected_handoff = handoff_wait and task.ref.key()[:2] == waited[0].key()[:2]
                    selected_effort = capacity_wait or selected_handoff or (effort_wait or actual_wait) and task.ref.key()[:2] == waited[0].key()[:2]
                    if selected_effort and effort_wait and action_input is original_input and task.estimate_ref != waited[1]:
                        raise TaskConflict('Government scheduling reader replaces its exact original waited estimate')
                    if selected_effort and actual_wait:
                        matching = [ref for ref in task.work_fact_refs if ref.key()[:2] == waited[1].key()[:2]]
                        if (len(matching) != 1 or action_input is original_input and matching[0] != waited[1]):
                            raise TaskConflict('Government scheduling reader replaces or omits its original waited investment')
                    if selected_effort or supplied(task.estimate_ref):
                        estimate = read(task.estimate_ref, GovSchedulingEstimateView)
                        if estimate.task_ref != task.ref or estimate.work_profile_ref != work.ref:
                            raise TaskConflict('Government scheduling estimate substitutes its original task/method')
                    for fact_ref in task.work_fact_refs:
                        selected_fact = (selected_effort and actual_wait
                            and fact_ref.key()[:2] == waited[1].key()[:2])
                        if not capacity_wait and not selected_handoff and not selected_fact and not (selected_effort and action_input is not original_input) and not supplied(fact_ref):
                            continue
                        fact = read(fact_ref, GovSchedulingWorkFactView)
                        if fact.task_ref != task.ref or fact.organization_id != source['organization_id']:
                            raise TaskConflict('Government scheduling actual effort borrows another original task/agency')
                    for dependency_ref in task.dependency_refs:
                        selected_dependency = (dependency_wait and task.ref.key()[:2] == waited[0].key()[:2]
                            and dependency_ref.key()[:2] == waited[1].key()[:2])
                        if not capacity_wait and not selected_dependency and not supplied(dependency_ref):
                            continue
                        dependency = read(dependency_ref, GovSchedulingDependencyView)
                        if (dependency.task_ref != task.ref or selected_dependency and dependency.scope != current_input.scope):
                            raise TaskConflict('Government scheduling dependency borrows another original task')
                    if dependency_wait and task.ref.key()[:2] == waited[0].key()[:2]:
                        matching = [ref for ref in task.dependency_refs if ref.key()[:2] == waited[1].key()[:2]]
                        if (len(matching) != 1 or action_input is original_input and matching[0] != waited[1]):
                            raise TaskConflict('Government scheduling reader replaces or omits its exact original dependency wait')
                calendar = read(action_input.capacity_ref, GovReviewCalendarView)
                if reviewer_wait:
                    matching = [row.ref for row in calendar.resources if row.ref.key()[:2] == waited[1].key()[:2]]
                    if (len(matching) != 1 or action_input is original_input and matching[0] != waited[1]):
                        raise TaskConflict('Government scheduling reader omits its original waited reviewer')
                for embedded in calendar.resources:
                    resource = read(embedded.ref, GovReviewResourceView)
                    if resource != embedded or resource.organization_id != source['organization_id']:
                        raise TaskConflict('Government scheduling calendar rewrites an original reviewer projection')
                    authority(resource.authority_ref, resource.function_ref)
                    for ref in resource.qualification_refs:
                        if capacity_wait or (qualification_wait and resource.ref.key()[:2] == waited[1].key()[:2]) or supplied(ref):
                            read(ref, GovReviewQualificationView)
                commitments = {row.commitment_ref.key(): row for row in calendar.commitments}
                for embedded in calendar.commitments:
                    if (capacity_wait or supplied(embedded.commitment_ref)) and read(embedded.commitment_ref, CapacityCommitment) != embedded:
                        raise TaskConflict('Government scheduling calendar substitutes its original occupancy projection')
                for ref in action_input.existing_assignment_refs:
                    assignment = read(ref, GovReviewAssignmentView)
                    if assignment.case_ref != case.ref or assignment.work_profile_ref != work.ref:
                        raise TaskConflict('Government scheduling assignment borrows another original case/method')
                    for commitment_ref in assignment.commitment_refs:
                        occupied = commitments.get(commitment_ref.key())
                        if (occupied is None or occupied.resource_ref not in assignment.resource_refs
                                or occupied.window != assignment.window):
                            raise TaskConflict('Government scheduling assignment changes its original exact occupancy')
            for completion_ref in {ref.key(): ref for ref in (*completed_task_refs,
                    *(() if completed_task_ref is None else (completed_task_ref,)))}.values():
                if completion_ref not in context.visible_refs:
                    raise TaskConflict('Government handoff reader requires visible actual completed-task publication')
                completed = read(completion_ref, GovSchedulingTaskView)
                if completed.organization_id != source['organization_id'] or completed.case_ref != current_input.case_ref:
                    raise TaskConflict('Government handoff reader borrows another agency/case completion')
                completed_work = read(completed.work_profile_ref, GovSchedulingWorkProfileView)
                estimate = read(completed.estimate_ref, GovSchedulingEstimateView)
                if estimate.task_ref != completed.ref or estimate.work_profile_ref != completed_work.ref:
                    raise TaskConflict('Government handoff reader changes original completed effort binding')
                for ref in completed.work_fact_refs:
                    fact = read(ref, GovSchedulingWorkFactView)
                    if fact.task_ref != completed.ref or fact.organization_id != source['organization_id']:
                        raise TaskConflict('Government handoff reader borrows another completed work investment')
                if completed.existing_assignment_ref is not None:
                    released = read(completed.existing_assignment_ref, GovReviewAssignmentView)
                    if released.task_ref != completed.ref or released.case_ref != current_input.case_ref:
                        raise TaskConflict('Government handoff reader borrows another original released assignment')
            return GovernmentSchedulingConditionReading(context=context.model_copy(deep=True), reading=reading,
                original_action_input=original_input.model_dump(mode='json'), action_input=prepared.action_input.model_dump(mode='json'),
                scheduling_sources=deepcopy(list(sources.values())), unavailable_targets=deepcopy(list(missing.values())),
                completed_task_ref=None if completed_task_ref is None else completed_task_ref.model_copy(deep=True),
                completed_task_refs=tuple(ref.model_copy(deep=True) for ref in completed_task_refs))
        finally:
            self._check()
            reading.recheck()
            if (self.snapshots.get(identity) != snapshot or reading.evidence() != baseline
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Government scheduling reader changed original snapshot or assembled context/input/source reading')


def build_assembled_government_scheduling_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    from integration.task_continuation import build_government_scheduling_continuation_dispatcher
    return _build_assembled_government_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate,
        reader_type=GovernmentSchedulingReader, dispatcher_factory=build_government_scheduling_continuation_dispatcher)
