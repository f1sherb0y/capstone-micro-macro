"""Read original GOV-A05 consultation sources for guarded same-task recovery."""
from copy import deepcopy
from dataclasses import dataclass

from integration.government_inspection_reader import (
    GovernmentInspectionReader, GovernmentInspectionRecoverySettings, GovernmentInspectionRecoveryBindings,
    _build_assembled_government_dispatcher,
)
from integration.government_consultation_actions import GovernmentConsultationActionAssembler, validate_government_consultation_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, EvidenceRecord, walk_references
from src.actions.contracts.government_objects import (
    GovJurisdictionView, GovMatterView, GovRecipientView, GovResponseRequirementView,
)
from src.actions.contracts.government_review_objects import GovReviewSubmissionView
from src.actions.contracts.government_consultation_objects import (
    GovConsultationCaseView, GovConsultationRuleView, GovConsultationProcedureView,
    GovConsultationApplicabilityView, GovDisclosurePackageView, GovDisclosureAuthorityView,
    GovConsultationRecipientView, GovConsultationClockView, GovConsultationView,
    GovConsultationDeliveryView, GovConsultationResponseView, GovParticipationView,
    GovConsultationTaskView, GovConsultationResultView, GovConsultationQuestionView,
)
from src.coordination.government_consultation_conditions import (
    GovernmentConsultationConditionReading, _CODE, _CODES, _BASES, _DISCLOSURE_CODE, _CASE_CODE, _ACTIVE_CODE,
    _OPINION_CODE, _NO_OPINION_CODE, _APPLICABILITY_CODE, _QUERY_CODE,
)
from src.coordination.government_consultation_query import GovernmentConsultationQueryRecord
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.models import Authorization, RoleAssignment


@dataclass(frozen=True)
class GovernmentConsultationCurrentSelection:
    request: RoleContractInvocation
    consultation_query: GovernmentConsultationQueryRecord | None = None


class GovernmentConsultationRecoverySettings(GovernmentInspectionRecoverySettings):
    """Original consultation source and policy versions."""


@dataclass(frozen=True)
class GovernmentConsultationRecoveryBindings(GovernmentInspectionRecoveryBindings):
    """Actual source guard, selector and independent native recovery validators."""


_HISTORY_SCHEMAS = {
    'Authorization': Authorization, 'FunctionAssignment': RoleAssignment, 'Evidence': EvidenceRecord,
    'Jurisdiction': GovJurisdictionView, 'RegulatoryMatter': GovMatterView,
    'Submission': GovReviewSubmissionView, 'Rule': GovConsultationRuleView,
    'Procedure': GovConsultationProcedureView, 'ApplicabilityBasis': GovConsultationApplicabilityView,
    'DisclosurePackage': GovDisclosurePackageView, 'Authority': GovDisclosureAuthorityView,
    'ConsultationRecipient': GovConsultationRecipientView, 'ClockRule': GovConsultationClockView,
    'Consultation': GovConsultationView, 'ConsultationDelivery': GovConsultationDeliveryView,
    'ConsultationResponse': GovConsultationResponseView, 'ParticipationVerification': GovParticipationView,
    'Task': GovConsultationTaskView, 'MethodResult': GovConsultationResultView,
    'EvidenceTarget': GovConsultationQuestionView, 'RegulatoryRecipient': GovRecipientView,
    'ResponseRequirement': GovResponseRequirementView,
}


class GovernmentConsultationReader(GovernmentInspectionReader):
    """Read two consultation histories without performing consultation or issuing a decision."""
    ACTION_ID = 'GOV-A05'
    CONDITION_CODE = _CODE
    CONDITION_CODES = _CODES
    ASSEMBLER_TYPE = GovernmentConsultationActionAssembler
    READER_SCHEMA = 'government-consultation-reader.v1'

    def __call__(self, check):
        self._check()
        source, waited = check.source['identity'], check.condition.object_refs
        analysis_wait = check.condition.condition_code == _CODE
        query_wait = check.condition.condition_code == _QUERY_CODE
        wait_kind = {_CODE: 'Task', _DISCLOSURE_CODE: 'DisclosurePackage', _CASE_CODE: 'RegulatoryCase',
            _ACTIVE_CODE: 'Consultation', _OPINION_CODE: 'Consultation', _NO_OPINION_CODE: 'Consultation',
            _QUERY_CODE: 'Consultation'}.get(
                check.condition.condition_code)
        wait_kinds = ('RegulatoryCase', 'ApplicabilityBasis') if check.condition.condition_code == _APPLICABILITY_CODE else (wait_kind,)
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code not in _CODES or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in waited) != wait_kinds
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Government consultation reader replaces original readiness wait or agency')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if analysis_wait and original_input.prior_consultation_ref is None:
            raise TaskConflict('Government consultation reader requires original selected consultation')
        if check.condition.condition_code == _DISCLOSURE_CODE and original_input.disclosure_package_ref != waited[0]:
            raise TaskConflict('Government consultation reader changes exact original waited disclosure package')
        if check.condition.condition_code == _CASE_CODE and original_input.case_ref != waited[0]:
            raise TaskConflict('Government consultation reader changes exact original waited case')
        if check.condition.condition_code == _APPLICABILITY_CODE and original_input.case_ref != waited[0]:
            raise TaskConflict('Government consultation reader changes exact original waited applicability case')
        if (check.condition.condition_code in {_ACTIVE_CODE, _OPINION_CODE, _NO_OPINION_CODE}
                and original_input.prior_consultation_ref != waited[0]):
            raise TaskConflict('Government consultation reader changes exact original waited consultation')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, GovernmentConsultationCurrentSelection):
            raise TaskConflict('Government consultation reader requires typed independently authorized current invocation')
        query = None if selected.consultation_query is None else GovernmentConsultationQueryRecord.model_validate(
            selected.consultation_query).model_copy(deep=True)
        if query is not None and not query_wait:
            raise TaskConflict('Government consultation lookup evidence belongs only to the original query wait')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or context.execution_mode != 'llm'
                or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope']
                or current_input.scope != original_input.scope
                or not query_wait and (original_input.prior_consultation_ref is None) != (current_input.prior_consultation_ref is None)
                or any(getattr(original_input, field).key()[:2] != getattr(current_input, field).key()[:2]
                    for field, _, _ in _BASES if getattr(original_input, field) is not None
                    and (not query_wait or field == 'case_ref'))
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input),
                    *(query.evidence_refs if query is not None else ()))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Government consultation reader replaces original scope/task/content or authorized source visibility')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        reading, baseline = prepared.reading, deepcopy(prepared.reading.evidence())
        sources, typed_sources, missing = {}, {}, {}
        try:
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('Government consultation assembly changes original source snapshot or agency')

            def read(ref, schema):
                row = reading.resolve(ref)
                actual_ref = getattr(row, 'ref', getattr(row, 'function_ref', None))
                if not isinstance(row, schema) or actual_ref != ref:
                    raise TaskConflict('Government consultation history lacks exact typed original/current source')
                typed_sources[ref.key()] = row
                sources[ref.key()] = row.model_dump(mode='json')
                return row

            pending = []
            if query_wait:
                # Explicit prior lookup may concern a historical rule/package
                # different from the proposed initiation. Preserve both inputs;
                # the condition binds continuation to the actually found history.
                looked_up = read(waited[0], GovConsultationView)
                pending.extend(ref for ref in walk_references(looked_up) if ref.kind in _HISTORY_SCHEMAS)
            if query is not None:
                for ref in query.evidence_refs:
                    read(ref, EvidenceRecord)
            for action_input in (original_input, prepared.action_input):
                bases = {field: read(getattr(action_input, field), schema)
                    for field, _, schema in _BASES if getattr(action_input, field) is not None}
                case, rule = bases['case_ref'], bases['consultation_rule_ref']
                if (check.condition.condition_code == _APPLICABILITY_CODE and action_input is original_input
                        and rule.applicability_basis_ref != waited[1]):
                    raise TaskConflict('Government consultation reader changes exact original waited applicability source')
                if analysis_wait and (rule.choice != 'analyze' or rule.analysis_task_ref is None):
                    raise TaskConflict('Government consultation reader replaces original analysis choice/task')
                task = read(rule.analysis_task_ref, GovConsultationTaskView) if analysis_wait else None
                if analysis_wait and action_input is original_input and task.ref != waited[0]:
                    raise TaskConflict('Government consultation reader changes exact original waited task')
                # Follow the selected analysis task; other case tasks belong to
                # other Government actions and have distinct projection schemas.
                pending.extend([case.matter_ref, case.jurisdiction_ref, case.procedure_ref,
                    case.current_submission_ref, *case.consultation_refs])
                pending.extend(ref for ref in walk_references(case) if ref.kind == 'Evidence')
                history_rows = [row for field, row in bases.items() if field != 'case_ref']
                if task is not None:
                    history_rows.append(task)
                for row in history_rows:
                    pending.extend(ref for ref in walk_references(row) if ref.kind in _HISTORY_SCHEMAS)
                for ref in walk_references(action_input):
                    if ref.kind in _HISTORY_SCHEMAS:
                        row = read(ref, _HISTORY_SCHEMAS[ref.kind])
                        pending.extend(ref for ref in walk_references(row) if ref.kind in _HISTORY_SCHEMAS)
                authority_ref = task.authority_ref if task is not None else rule.authority_ref
                grant = read(authority_ref, Authorization)
                function_ref = task.function_ref if task is not None else grant.function_ref
                read(function_ref, RoleAssignment)
                if grant.organization_id != source['organization_id'] or grant.function_ref != function_ref:
                    raise TaskConflict('Government consultation history borrows another agency/function task authority')
            visited = set()
            while pending:
                ref = pending.pop()
                if ref.key() in visited:
                    continue
                visited.add(ref.key())
                if ref.key() not in reading._resolver._objects:
                    # Waits precede later substantive consultation sources. Preserve
                    # every omission for native validation, without inventing it.
                    missing[ref.key()] = ref.model_dump(mode='json')
                    continue
                row = read(ref, _HISTORY_SCHEMAS[ref.kind])
                if hasattr(row, 'author_authority_ref'):
                    grant = read(row.author_authority_ref, Authorization)
                    read(row.author_function_ref, RoleAssignment)
                    if (grant.actor_id != row.author_actor_id or grant.organization_id != row.author_organization_id
                            or grant.function_ref != row.author_function_ref or row.author_action_id not in grant.action_ids):
                        raise TaskConflict('Government consultation history substitutes actual source author/action authority')
                related = ([row.function_ref, *row.basis_refs] if isinstance(row, Authorization)
                    else row.basis_refs if isinstance(row, RoleAssignment) else walk_references(row))
                pending.extend(ref for ref in related if ref.kind in _HISTORY_SCHEMAS)
            for action_input in (original_input, prepared.action_input):
                selected_context = ActionContext.model_validate(snapshot['context']) if action_input is original_input else context
                validate_government_consultation_sources(action_input, context=selected_context,
                    organization_id=source['organization_id'], sources=typed_sources)
            return GovernmentConsultationConditionReading(context=context.model_copy(deep=True), reading=reading,
                original_action_input=original_input.model_dump(mode='json'),
                action_input=prepared.action_input.model_dump(mode='json'),
                consultation_sources=deepcopy(list(sources.values())), unavailable_targets=deepcopy(list(missing.values())),
                consultation_query=None if query is None else query.model_dump(mode='json'))
        finally:
            self._check()
            reading.recheck()
            if (self.snapshots.get(identity) != snapshot or reading.evidence() != baseline
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Government consultation reader changes original snapshot or current assembled source/input/context')


def build_assembled_government_consultation_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    from integration.task_continuation import build_government_consultation_continuation_dispatcher
    return _build_assembled_government_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate,
        reader_type=GovernmentConsultationReader, dispatcher_factory=build_government_consultation_continuation_dispatcher)
