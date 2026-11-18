"""Read original GOV-A09 transition sources for guarded same-task recovery."""
from copy import deepcopy
from dataclasses import dataclass

from integration.government_inspection_reader import (
    GovernmentInspectionReader, GovernmentInspectionRecoverySettings, GovernmentInspectionRecoveryBindings,
    _build_assembled_government_dispatcher,
)
from integration.government_transition_actions import GovernmentTransitionActionAssembler, validate_government_transition_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, EvidenceRecord, walk_references
from src.actions.contracts.government_objects import GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_transition_objects import (
    GovTransitionDecisionView, GovTransitionPermitView, GovTransitionApplicationView,
    GovTransitionApplicantAuthorityView, GovTransitionRuleView, GovChangeBasisView,
    GovChangeAuthorityView, GovChangeProcedureView, GovChangeEffectView, GovExpiryFactView,
    GovTransitionQuestionView, GovReviewSubmissionView, GovDecisionCommandView, GovDecisionNotificationView,
    GovDecisionAssessmentView, GovDecisionFindingView, GovChangeCheckView,
    GovDecisionConditionBasisView, GovDecisionBindingView, GovDecisionMethodView,
    GovProcedureCompletionView, GovProcedureVerificationView, GovProcedureRequirementView,
)
from src.coordination.government_decision_query import GovernmentDecisionQueryRecord
from src.coordination.government_transition_notification import (
    NOTIFICATION_CODE, GovernmentTransitionNotificationCompletionRecord, GovernmentTransitionNotificationSnapshot,
)
from src.coordination.government_transition_conditions import GovernmentTransitionConditionReading, _CODE, _CODES, _BASES, _OPTIONAL
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.models import Authorization, RoleAssignment


@dataclass(frozen=True)
class GovernmentTransitionCurrentSelection:
    request: RoleContractInvocation
    command_query: GovernmentDecisionQueryRecord | None = None
    notification_completion: GovernmentTransitionNotificationCompletionRecord | None = None
    notification_snapshot: GovernmentTransitionNotificationSnapshot | None = None


class GovernmentTransitionRecoverySettings(GovernmentInspectionRecoverySettings):
    """Original decision change source and policy versions."""
    terminal_notification_enabled: bool = False


@dataclass(frozen=True)
class GovernmentTransitionRecoveryBindings(GovernmentInspectionRecoveryBindings):
    """Actual source guard, selector and independent native recovery validators."""


_HISTORY_SCHEMAS = {
    'Authorization': Authorization, 'FunctionAssignment': RoleAssignment, 'Evidence': EvidenceRecord,
    'Decision': GovTransitionDecisionView, 'Permit': GovTransitionPermitView,
    'RegulatoryApplication': GovTransitionApplicationView, 'Submission': GovReviewSubmissionView,
    'ApplicationAuthority': GovTransitionApplicantAuthorityView, 'Rule': GovTransitionRuleView,
    'DecisionBasis': GovChangeBasisView, 'Authority': GovChangeAuthorityView,
    'Procedure': GovChangeProcedureView, 'EffectRule': GovChangeEffectView,
    'DecisionCommand': GovDecisionCommandView, 'DecisionNotification': GovDecisionNotificationView,
    'Assessment': GovDecisionAssessmentView, 'MethodResult': GovDecisionFindingView,
    'DecisionCheck': GovChangeCheckView, 'ProcedureCompletion': GovProcedureCompletionView,
    'ProcedureRequirement': GovProcedureRequirementView, 'ProcedureVerification': GovProcedureVerificationView,
    'PermitExpiryFact': GovExpiryFactView, 'EvidenceTarget': GovTransitionQuestionView,
    'RegulatoryRecipient': GovRecipientView, 'ResponseRequirement': GovResponseRequirementView,
    'ConditionBasis': GovDecisionConditionBasisView, 'ActionDefinition': GovDecisionBindingView,
    'EvidenceRequirement': GovDecisionBindingView, 'ClockRule': GovDecisionBindingView, 'Method': GovDecisionMethodView,
}


class GovernmentTransitionReader(GovernmentInspectionReader):
    """Read original/current change-command histories without changing a decision."""
    ACTION_ID = 'GOV-A09'
    CONDITION_CODE = _CODE
    CONDITION_CODES = _CODES
    ASSEMBLER_TYPE = GovernmentTransitionActionAssembler
    READER_SCHEMA = 'government-transition-reader.v1'

    def __call__(self, check, *, notification_terminal=False, notification_transport=False):
        self._check()
        source, waited = check.source['identity'], check.condition.object_refs
        recorded_wait = check.condition.condition_code == NOTIFICATION_CODE
        notification_only = notification_terminal or notification_transport
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code not in _CODES or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in waited) != (('Decision',) if recorded_wait else ('DecisionCommand',))
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Government transition reader replaces original original-command wait or agency')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if recorded_wait and not notification_only:
            raise TaskConflict('Recorded changes require explicit actual-delivery reconciliation')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, GovernmentTransitionCurrentSelection):
            raise TaskConflict('Government transition reader requires typed independently authorized current invocation')
        query = None if selected.command_query is None else GovernmentDecisionQueryRecord.model_validate(selected.command_query).model_copy(deep=True)
        completion = None if selected.notification_completion is None else GovernmentTransitionNotificationCompletionRecord.model_validate(
            selected.notification_completion).model_copy(deep=True)
        notification_snapshot = None if selected.notification_snapshot is None else GovernmentTransitionNotificationSnapshot.model_validate(
            selected.notification_snapshot).model_copy(deep=True)
        if notification_transport and (notification_terminal or notification_snapshot is None):
            raise TaskConflict('Change notification transport requires independently supplied actual signed-fact/history snapshot')
        if recorded_wait and query is not None or notification_terminal and completion is None:
            raise TaskConflict('Change delivery requires actual completion and lookup only for original query waits')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time
                or (context.operation_id != source['request_id'] if notification_only else context.operation_id == source['request_id'])
                or notification_only and current_input != original_input
                or context.scope.model_dump(mode='json') != snapshot['context']['scope']
                or current_input.scope != original_input.scope
                or any(getattr(original_input, field).key()[:2] != getattr(current_input, field).key()[:2]
                    for field, _, _ in _BASES)
                or any((getattr(original_input, field) is None) != (getattr(current_input, field) is None)
                    or getattr(original_input, field) is not None and getattr(original_input, field).key()[:2] != getattr(current_input, field).key()[:2]
                    for field, _, _ in _OPTIONAL)
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input),
                    *(query.evidence_refs if query is not None else ()),
                    *((ref for ref in walk_references(completion) if ref.kind == 'Evidence') if notification_terminal else ()),
                    *((ref for ref in walk_references(notification_snapshot) if ref.kind == 'Evidence') if notification_transport else ()))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Government transition reader replaces original scope/permit/action or authorized source visibility')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        reading, baseline = prepared.reading, deepcopy(prepared.reading.evidence())
        sources, typed_sources, missing = {}, {}, {}
        try:
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('Government transition assembly changes original source snapshot or agency')

            def read(ref, schema):
                row = reading.resolve(ref)
                actual_ref = getattr(row, 'ref', getattr(row, 'function_ref', None))
                if not isinstance(row, schema) or actual_ref != ref:
                    raise TaskConflict('Government transition history lacks exact typed original/current source')
                typed_sources[ref.key()] = row
                sources[ref.key()] = row.model_dump(mode='json')
                return row

            pending = []
            if query is not None:
                for ref in query.evidence_refs:
                    read(ref, EvidenceRecord)
            if notification_terminal:
                for ref in walk_references(completion):
                    if ref.kind == 'Evidence':
                        read(ref, EvidenceRecord)
            if notification_transport:
                for ref in walk_references(notification_snapshot):
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
                rule = typed_sources[action_input.transition_rule_ref.key()]
                if rule.decision_basis_ref is None:
                    raise TaskConflict('Transition recovery lacks original change decision basis')
                basis = read(rule.decision_basis_ref, GovChangeBasisView)
                if action_input is original_input and not recorded_wait and basis.command_ref != waited[0]:
                    raise TaskConflict('Transition recovery changes exact original waited command')
                pending.extend(ref for ref in walk_references(basis) if ref.kind in _HISTORY_SCHEMAS)
                invocation = ActionContext.model_validate(snapshot['context']) if action_input is original_input else context
                grant = read(basis.signer_authorization_ref, Authorization)
                read(invocation.function_ref, RoleAssignment)
                if grant.organization_id != source['organization_id'] or grant.function_ref != invocation.function_ref:
                    raise TaskConflict('Transition history borrows another agency/function change signer authority')
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
                        raise TaskConflict('Government transition history substitutes actual source author/action authority')
                related = ([row.function_ref, *row.basis_refs] if isinstance(row, Authorization)
                    else row.basis_refs if isinstance(row, RoleAssignment) else walk_references(row))
                pending.extend(ref for ref in related if ref.kind in _HISTORY_SCHEMAS)
            for action_input in (original_input, prepared.action_input):
                selected_context = ActionContext.model_validate(snapshot['context']) if action_input is original_input else context
                validate_government_transition_sources(action_input, context=selected_context,
                    organization_id=source['organization_id'], sources=typed_sources)
            return GovernmentTransitionConditionReading(context=context.model_copy(deep=True), reading=reading,
                original_action_input=original_input.model_dump(mode='json'),
                action_input=prepared.action_input.model_dump(mode='json'),
                transition_sources=deepcopy(list(sources.values())), unavailable_targets=deepcopy(list(missing.values())),
                original_context=ActionContext.model_validate(snapshot['context']).model_copy(deep=True),
                command_query=None if query is None else query.model_dump(mode='json'),
                notification_completion=None if completion is None else completion.model_dump(mode='json'),
                notification_snapshot=None if notification_snapshot is None else notification_snapshot.model_dump(mode='json'))
        finally:
            self._check()
            reading.recheck()
            if (self.snapshots.get(identity) != snapshot or reading.evidence() != baseline
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Government transition reader changes original snapshot or current assembled source/input/context')


def build_assembled_government_transition_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    from integration.task_continuation import build_government_transition_continuation_dispatcher
    return _build_assembled_government_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate,
        reader_type=GovernmentTransitionReader, dispatcher_factory=build_government_transition_continuation_dispatcher)
