"""Read original GOV-A06 supplement sources for guarded same-task recovery."""
from copy import deepcopy
from dataclasses import dataclass

from integration.government_inspection_reader import (
    GovernmentInspectionReader, GovernmentInspectionRecoverySettings, GovernmentInspectionRecoveryBindings,
    _build_assembled_government_dispatcher,
)
from integration.government_supplement_actions import GovernmentSupplementActionAssembler, validate_government_supplement_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, EvidenceRecord, walk_references
from src.actions.contracts.government_objects import (
    GovJurisdictionView, GovMatterView, GovRecipientView, GovResponseRequirementView,
)
from src.actions.contracts.government_supplement_objects import (
    GovSupplementCaseView, GovSupplementSubmissionView, GovSubmissionComponentView,
    GovSupplementProfileView, GovSupplementIssueView, GovSupplementRequirementView,
    GovSupplementRuleView, GovSupplementResponseView, GovResponseFactView,
    GovSupplementResultView, GovSupplementAssessmentView, GovSupplementRevisionView,
    GovSupplementQuestionView, GovSupplementClockView, GovSupplementDelayAuthorityView, GovSupplementTriggerView,
)
from src.coordination.government_supplement_conditions import (
    GovernmentSupplementConditionReading, _CODE, _CODES, _BASES, _WINDOW_CODE, _DELAY_BASIS_CODE, _DELAY_PERMISSION_CODE,
    _RESPONSE_CODE,
    _REASSESSMENT_CODE,
)
from src.coordination.government_supplement_reassessment import GovernmentSupplementReassessmentRecord
from src.coordination.government_supplement_transfer import GovernmentSupplementTransferRecord, NEW_CASE_CODE
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.models import Authorization, RoleAssignment


@dataclass(frozen=True)
class GovernmentSupplementCurrentSelection:
    request: RoleContractInvocation
    reassessment: GovernmentSupplementReassessmentRecord | None = None
    transfer: GovernmentSupplementTransferRecord | None = None


class GovernmentSupplementRecoverySettings(GovernmentInspectionRecoverySettings):
    """Original supplement source and policy versions."""
    terminal_transfer_enabled: bool = False


@dataclass(frozen=True)
class GovernmentSupplementRecoveryBindings(GovernmentInspectionRecoveryBindings):
    """Actual source guard, selector and independent native recovery validators."""


_HISTORY_SCHEMAS = {
    'Authorization': Authorization, 'FunctionAssignment': RoleAssignment, 'Evidence': EvidenceRecord,
    'Jurisdiction': GovJurisdictionView, 'RegulatoryMatter': GovMatterView,
    'Submission': GovSupplementSubmissionView, 'SubmissionComponent': GovSubmissionComponentView,
    'SupplementProfile': GovSupplementProfileView, 'Issue': GovSupplementIssueView,
    'InformationRequirement': GovSupplementRequirementView, 'Rule': GovSupplementRuleView,
    'Response': GovSupplementResponseView, 'ResponseFact': GovResponseFactView,
    'MethodResult': GovSupplementResultView, 'Assessment': GovSupplementAssessmentView,
    'RevisionBasis': GovSupplementRevisionView, 'EvidenceTarget': GovSupplementQuestionView,
    'ClockRule': GovSupplementClockView, 'Authority': GovSupplementDelayAuthorityView,
    'Trigger': GovSupplementTriggerView, 'RegulatoryRecipient': GovRecipientView,
    'ResponseRequirement': GovResponseRequirementView,
}


class GovernmentSupplementReader(GovernmentInspectionReader):
    """Read two supplement histories without resolving issues or issuing a decision."""
    ACTION_ID = 'GOV-A06'
    CONDITION_CODE = _CODE
    CONDITION_CODES = _CODES
    ASSEMBLER_TYPE = GovernmentSupplementActionAssembler
    READER_SCHEMA = 'government-supplement-reader.v1'

    def __call__(self, check):
        self._check()
        source, waited = check.source['identity'], check.condition.object_refs
        clock_wait = check.condition.condition_code in {_WINDOW_CODE, _DELAY_BASIS_CODE}
        permission_wait = check.condition.condition_code == _DELAY_PERMISSION_CODE
        response_wait = check.condition.condition_code == _RESPONSE_CODE
        reassessment_wait = check.condition.condition_code == _REASSESSMENT_CODE
        transfer_wait = check.condition.condition_code == NEW_CASE_CODE
        revision_wait = reassessment_wait or transfer_wait
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code not in _CODES or check.condition.trigger != 'dependency_change'
                or (not response_wait and not revision_wait and tuple(ref.kind for ref in waited) != ('RegulatoryCase',
                    'Rule' if permission_wait else 'ClockRule' if clock_wait else 'Submission'))
                or (revision_wait and tuple(ref.kind for ref in waited) != ('RegulatoryCase', 'RevisionBasis', 'Submission'))
                or (response_wait and (len(waited) < 2 or waited[0].kind != 'RegulatoryCase'
                    or any(ref.kind != 'Response' for ref in waited[1:])))
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Government supplement reader replaces original readiness wait or agency')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        if not permission_wait and not response_wait and not revision_wait and tuple(waited) != (original_input.case_ref,
                original_input.clock_rule_ref if clock_wait else original_input.current_submission_ref):
            raise TaskConflict('Government supplement reader changes exact original waited input references')
        if response_wait and tuple(waited) != (original_input.case_ref, *original_input.response_refs):
            raise TaskConflict('Government supplement reader changes exact original waited response list')
        if permission_wait and original_input.case_ref != waited[0]:
            raise TaskConflict('Government supplement reader changes exact original delay-permission case')
        if revision_wait and (original_input.case_ref, original_input.current_submission_ref) != (waited[0], waited[2]):
            raise TaskConflict('Government supplement reader changes exact original reassessment case/submission')
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, GovernmentSupplementCurrentSelection):
            raise TaskConflict('Government supplement reader requires typed independently authorized current invocation')
        reassessment = None if selected.reassessment is None else GovernmentSupplementReassessmentRecord.model_validate(
            selected.reassessment).model_copy(deep=True)
        if reassessment is not None and not reassessment_wait:
            raise TaskConflict('Government supplement reassessment record belongs only to its original procedure wait')
        transfer = None if selected.transfer is None else GovernmentSupplementTransferRecord.model_validate(
            selected.transfer).model_copy(deep=True)
        if transfer is not None and not transfer_wait:
            raise TaskConflict('Government supplement transfer record belongs only to its original new-case wait')
        # New-case projections are supplied by native intake under the same
        # source guard; A06's case schema cannot reinterpret an intake case.
        # Terminal validation authenticates these supplied projections in full.
        transfer_refs = [] if transfer is None else [transfer.authority_ref, transfer.function_ref,
            *transfer.evidence_refs, *[ref for ref in walk_references(transfer) if ref.kind == 'Evidence']]
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
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
                or not {ref.key() for ref in (*walk_references(original_input), *walk_references(current_input),
                    *(walk_references(reassessment) if reassessment is not None else ()), *transfer_refs)}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Government supplement reader replaces original scope/submission/content or authorized source visibility')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        reading, baseline = prepared.reading, deepcopy(prepared.reading.evidence())
        sources, typed_sources, missing = {}, {}, {}
        try:
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('Government supplement assembly changes original source snapshot or agency')

            def read(ref, schema):
                row = reading.resolve(ref)
                actual_ref = getattr(row, 'ref', getattr(row, 'function_ref', None))
                if not isinstance(row, schema) or actual_ref != ref:
                    raise TaskConflict('Government supplement history lacks exact typed original/current source')
                typed_sources[ref.key()] = row
                sources[ref.key()] = row.model_dump(mode='json')
                return row

            pending = []
            if reassessment is not None:
                pending.extend(ref for ref in walk_references(reassessment) if ref.kind in _HISTORY_SCHEMAS)
            pending.extend(transfer_refs)
            for action_input in (original_input, prepared.action_input):
                bases = {field: read(getattr(action_input, field), schema) for field, _, schema in _BASES}
                case = bases['case_ref']
                profile = read(case.supplement_profile_ref, GovSupplementProfileView)
                if permission_wait and action_input is original_input and profile.delay_rule_ref != waited[1]:
                    raise TaskConflict('Government supplement reader changes exact original waited delay rule')
                if revision_wait and action_input is original_input and profile.revision_basis_ref != waited[1]:
                    raise TaskConflict('Government supplement reader changes exact original waited revision basis')
                # Case task_refs belong to other action schemas. Follow only
                # original supplement sources and retained submission lineage.
                pending.extend([case.matter_ref, case.jurisdiction_ref, *case.linked_submission_refs])
                pending.extend(ref for ref in walk_references(case) if ref.kind == 'Evidence')
                for row in (*[row for field, row in bases.items() if field != 'case_ref'], profile):
                    pending.extend(ref for ref in walk_references(row) if ref.kind in _HISTORY_SCHEMAS)
                for ref in walk_references(action_input):
                    if ref.kind in _HISTORY_SCHEMAS:
                        row = read(ref, _HISTORY_SCHEMAS[ref.kind])
                        pending.extend(ref for ref in walk_references(row) if ref.kind in _HISTORY_SCHEMAS)
                # Original readiness waits precede agency authorization. Later
                # missing historical targets are recorded for native validation.
                if action_input is prepared.action_input:
                    grant = read(profile.authority_ref, Authorization)
                    read(context.function_ref, RoleAssignment)
                    if grant.organization_id != source['organization_id'] or grant.function_ref != context.function_ref:
                        raise TaskConflict('Government supplement history borrows another agency/function authority')
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
                        raise TaskConflict('Government supplement history substitutes actual source author/action authority')
                related = ([row.function_ref, *row.basis_refs] if isinstance(row, Authorization)
                    else row.basis_refs if isinstance(row, RoleAssignment) else walk_references(row))
                pending.extend(ref for ref in related if ref.kind in _HISTORY_SCHEMAS)
            for action_input in (original_input, prepared.action_input):
                selected_context = ActionContext.model_validate(snapshot['context']) if action_input is original_input else context
                validate_government_supplement_sources(action_input, context=selected_context,
                    organization_id=source['organization_id'], sources=typed_sources)
            return GovernmentSupplementConditionReading(context=context.model_copy(deep=True), reading=reading,
                original_action_input=original_input.model_dump(mode='json'),
                action_input=prepared.action_input.model_dump(mode='json'),
                supplement_sources=deepcopy(list(sources.values())), unavailable_targets=deepcopy(list(missing.values())),
                original_context=ActionContext.model_validate(snapshot['context']).model_copy(deep=True),
                reassessment=None if reassessment is None else reassessment.model_dump(mode='json'),
                transfer=None if transfer is None else transfer.model_dump(mode='json'))
        finally:
            self._check()
            reading.recheck()
            if (self.snapshots.get(identity) != snapshot or reading.evidence() != baseline
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Government supplement reader changes original snapshot or current assembled source/input/context')


def build_assembled_government_supplement_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    from integration.task_continuation import build_government_supplement_continuation_dispatcher
    return _build_assembled_government_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate,
        reader_type=GovernmentSupplementReader, dispatcher_factory=build_government_supplement_continuation_dispatcher)
