"""Read original GOV-A12 feedback/work sources for guarded same-task recovery."""
from copy import deepcopy
from dataclasses import dataclass

from integration.government_inspection_reader import (
    GovernmentInspectionReader, GovernmentInspectionRecoverySettings, GovernmentInspectionRecoveryBindings,
    _build_assembled_government_dispatcher,
)
from integration.government_feedback_actions import GovernmentFeedbackActionAssembler, validate_government_feedback_sources
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, EvidenceRecord, walk_references
from src.actions.contracts.government_objects import GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_feedback_objects import (
    GovObservationProfileView, GovWorkingAuthorityView, GovReceivedFeedbackView, GovVisibleStatisticView,
    GovStatisticSnapshotView, GovAvailableProjectView, GovFeedbackWorkView, GovFeedbackTaskView,
    GovFeedbackEstimateView, GovFeedbackRequestEstimateView, GovFeedbackDependencyView,
    GovFeedbackAssignmentView, GovFeedbackCalendarView, GovPolicyControlView, GovPolicyInstrumentView,
    GovFeedbackRuleView, GovFeedbackRequirementView, GovFeedbackExecutionView,
    GovReviewResourceView, GovReviewQualificationView,
)
from src.coordination.government_feedback_conditions import GovernmentFeedbackConditionReading, _CODE, _CODES, _BASES, _OPTIONAL, _ASSIGNMENT_CODE, _CAPACITY_CODE
from src.coordination.government_feedback_assignment_query import GovernmentFeedbackAssignmentQueryRecord
from src.coordination.government_feedback_execution_query import (
    EXECUTION_CODE, GovernmentFeedbackExecutionQueryRecord,
    government_original_feedback_execution_profile, check_feedback_execution,
)
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.models import Authorization, RoleAssignment


@dataclass(frozen=True)
class GovernmentFeedbackCurrentSelection:
    request: RoleContractInvocation
    assignment_query: GovernmentFeedbackAssignmentQueryRecord | None = None
    execution_query: GovernmentFeedbackExecutionQueryRecord | None = None


class GovernmentFeedbackRecoverySettings(GovernmentInspectionRecoverySettings):
    """Original feedback working source and policy versions."""
    terminal_execution_enabled: bool = False


@dataclass(frozen=True)
class GovernmentFeedbackRecoveryBindings(GovernmentInspectionRecoveryBindings):
    """Actual source guard, selector and independent native recovery validators."""


_HISTORY_SCHEMAS = {
    'Authorization': Authorization, 'FunctionAssignment': RoleAssignment, 'Evidence': EvidenceRecord,
    'ObservationProfile': GovObservationProfileView, 'Authority': GovWorkingAuthorityView,
    'Feedback': GovReceivedFeedbackView, 'Statistic': GovVisibleStatisticView, 'StatisticSnapshot': GovStatisticSnapshotView,
    'AvailableProjectObservation': GovAvailableProjectView, 'WorkProfile': GovFeedbackWorkView,
    'Task': GovFeedbackTaskView, 'WorkEstimate': GovFeedbackEstimateView, 'FeedbackRequestEstimate': GovFeedbackRequestEstimateView,
    'Dependency': GovFeedbackDependencyView, 'ReviewAssignment': GovFeedbackAssignmentView,
    'ResourceCalendar': GovFeedbackCalendarView, 'Resource': GovReviewResourceView, 'Qualification': GovReviewQualificationView,
    'PolicyControlProfile': GovPolicyControlView, 'PolicyInstrument': GovPolicyInstrumentView, 'Rule': GovFeedbackRuleView,
    'DeliverableRequirement': GovFeedbackRequirementView, 'GovernmentFeedbackExecution': GovFeedbackExecutionView,
    'RegulatoryRecipient': GovRecipientView, 'ResponseRequirement': GovResponseRequirementView,
}


class GovernmentFeedbackReader(GovernmentInspectionReader):
    """Read original/current work histories without changing assignments or policy."""
    ACTION_ID = 'GOV-A12'
    CONDITION_CODE = _CODE
    CONDITION_CODES = _CODES
    ASSEMBLER_TYPE = GovernmentFeedbackActionAssembler
    READER_SCHEMA = 'government-feedback-reader.v1'
    EXECUTION_PROFILE_FACTORY = staticmethod(government_original_feedback_execution_profile)
    EXECUTION_CHECKER = staticmethod(check_feedback_execution)

    def _components(self):
        return (*super()._components(), self.EXECUTION_PROFILE_FACTORY, self.EXECUTION_CHECKER)

    def _configuration(self):
        return {**super()._configuration(),
            'execution_condition': module_factory_descriptor(self.EXECUTION_PROFILE_FACTORY, 'execution_condition'),
            'execution_checker': module_factory_descriptor(self.EXECUTION_CHECKER, 'execution_checker')}

    def __call__(self, check, *, execution_terminal=False):
        self._check()
        source, waited = check.source['identity'], check.condition.object_refs
        assignment_wait = check.condition.condition_code == _ASSIGNMENT_CODE
        execution_wait = check.condition.condition_code == EXECUTION_CODE
        capacity_wait = check.condition.condition_code == _CAPACITY_CODE
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code not in _CODES or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in waited) != (('GovernmentFeedbackExecution',) if execution_wait else
                    ('ResourceCalendar',) if capacity_wait else ('ReviewAssignment',) if assignment_wait else ('Dependency',))
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Government feedback reader replaces original work-dependency wait or agency')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, GovernmentFeedbackCurrentSelection):
            raise TaskConflict('Government feedback reader requires typed independently authorized current invocation')
        query = None if selected.assignment_query is None else GovernmentFeedbackAssignmentQueryRecord.model_validate(
            selected.assignment_query).model_copy(deep=True)
        if query is not None and not assignment_wait:
            raise TaskConflict('Assignment query belongs only to original assignment uncertainty waits')
        execution_query = None if selected.execution_query is None else GovernmentFeedbackExecutionQueryRecord.model_validate(
            selected.execution_query).model_copy(deep=True)
        if execution_query is not None and not execution_wait or execution_terminal and not execution_wait:
            raise TaskConflict('Execution query/reconciliation belongs only to original execution waits')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time
                or (context.operation_id != source['request_id'] if execution_terminal else context.operation_id == source['request_id'])
                or execution_terminal and current_input != original_input
                or context.scope.model_dump(mode='json') != snapshot['context']['scope']
                or current_input.scope != original_input.scope
                or any(getattr(original_input, field).key()[:2] != getattr(current_input, field).key()[:2]
                    for field, _, _ in _BASES)
                or any((getattr(original_input, field) is None) != (getattr(current_input, field) is None)
                    or getattr(original_input, field) is not None and getattr(original_input, field).key()[:2] != getattr(current_input, field).key()[:2]
                    for field, _, _ in _OPTIONAL)
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input),
                    *(query.evidence_refs if query is not None else ()),
                    *((ref for ref in walk_references(execution_query) if ref.kind == 'Evidence') if execution_query is not None else ()))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Government feedback reader replaces original work scope/profile or authorized source visibility')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        reading, baseline = prepared.reading, deepcopy(prepared.reading.evidence())
        sources, typed_sources, missing = {}, {}, {}
        try:
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('Government feedback assembly changes original source snapshot or agency')

            def read(ref, schema):
                row = reading.resolve(ref)
                actual_ref = getattr(row, 'ref', getattr(row, 'function_ref', None))
                if not isinstance(row, schema) or actual_ref != ref:
                    raise TaskConflict('Government feedback history lacks exact typed original/current source')
                typed_sources[ref.key()] = row
                sources[ref.key()] = row.model_dump(mode='json')
                return row

            pending = []
            if query is not None:
                for ref in query.evidence_refs:
                    read(ref, EvidenceRecord)
            if execution_query is not None:
                for ref in walk_references(execution_query):
                    if ref.kind == 'Evidence':
                        read(ref, EvidenceRecord)
            for action_input in (original_input, prepared.action_input):
                for field, _, schema in (*_BASES, *_OPTIONAL):
                    if getattr(action_input, field) is None:
                        continue
                    row = read(getattr(action_input, field), schema)
                    pending.extend(ref for ref in walk_references(row) if ref.kind in _HISTORY_SCHEMAS)
                for ref in walk_references(action_input):
                    if ref.kind in _HISTORY_SCHEMAS:
                        row = read(ref, _HISTORY_SCHEMAS[ref.kind])
                        pending.extend(ref for ref in walk_references(row) if ref.kind in _HISTORY_SCHEMAS)
                profile = typed_sources[action_input.observation_profile_ref.key()]
                invocation = ActionContext.model_validate(snapshot['context']) if action_input is original_input else context
                grant = read(profile.authority_ref, Authorization)
                read(invocation.function_ref, RoleAssignment)
                if grant.organization_id != source['organization_id'] or grant.function_ref != invocation.function_ref:
                    raise TaskConflict('Government feedback history borrows another agency/function working authority')
            visited = set()
            while pending:
                ref = pending.pop()
                if ref.key() in visited:
                    continue
                visited.add(ref.key())
                if ref.key() not in reading._resolver._objects:
                    # Waits precede later substantive review sources. Preserve
                    # every omission for native validation, without inventing it.
                    missing[ref.key()] = ref.model_dump(mode='json')
                    continue
                row = read(ref, _HISTORY_SCHEMAS[ref.kind])
                if hasattr(row, 'author_authority_ref'):
                    grant = read(row.author_authority_ref, Authorization)
                    read(row.author_function_ref, RoleAssignment)
                    if (grant.actor_id != row.author_actor_id or grant.organization_id != row.author_organization_id
                            or grant.function_ref != row.author_function_ref or row.author_action_id not in grant.action_ids):
                        raise TaskConflict('Government feedback history substitutes actual source author/action authority')
                related = ([row.function_ref, *row.basis_refs] if isinstance(row, Authorization)
                    else row.basis_refs if isinstance(row, RoleAssignment) else walk_references(row))
                pending.extend(ref for ref in related if ref.kind in _HISTORY_SCHEMAS)
            for action_input in (original_input, prepared.action_input):
                selected_context = ActionContext.model_validate(snapshot['context']) if action_input is original_input else context
                validate_government_feedback_sources(action_input, context=selected_context,
                    organization_id=source['organization_id'], sources=typed_sources)
            return GovernmentFeedbackConditionReading(context=context.model_copy(deep=True), reading=reading,
                original_action_input=original_input.model_dump(mode='json'),
                action_input=prepared.action_input.model_dump(mode='json'),
                feedback_sources=deepcopy(list(sources.values())), unavailable_targets=deepcopy(list(missing.values())),
                original_context=ActionContext.model_validate(snapshot['context']).model_copy(deep=True),
                assignment_query=None if query is None else query.model_dump(mode='json'),
                execution_query=None if execution_query is None else execution_query.model_dump(mode='json'))
        finally:
            self._check()
            reading.recheck()
            if (self.snapshots.get(identity) != snapshot or reading.evidence() != baseline
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Government feedback reader changes original snapshot or current assembled source/input/context')


def build_assembled_government_feedback_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    from integration.task_continuation import build_government_feedback_continuation_dispatcher
    return _build_assembled_government_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate,
        reader_type=GovernmentFeedbackReader, dispatcher_factory=build_government_feedback_continuation_dispatcher)
