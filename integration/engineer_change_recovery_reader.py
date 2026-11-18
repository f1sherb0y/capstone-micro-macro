"""Recover the original A09 revision instruction wait from formal sources."""
from dataclasses import dataclass, replace
from pydantic import BaseModel, model_serializer

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, ContractorCloseoutCurrentSelection,
    build_assembled_contractor_closeout_dispatcher,
)
from integration.engineer_change_actions import EngineerChangeActionAssembler
from integration.engineer_submission_receipt_reader import EngineerSubmissionRecoverySettings, EngineerSubmissionRecoveryBindings
from integration.module_host import module_factory_descriptor
from src.actions.roles.engineer_change import (
    handle_professional_change, recheck_original_engineer_change_candidate_limit, recheck_original_engineer_change_work_limit,
    recheck_original_engineer_change_submission,
)
from src.coordination.engineer_change_conditions import (
    INSTRUCTION_REQUIRED_CODE, INSTRUCTION_AUTHORIZATION_CODE, AUTHOR_HANDOFF_CODE,
    DESIGN_AUTHORIZATION_CODE, DESIGN_CANDIDATE_CODE, DESIGN_WORK_CODE, DESIGN_SUBMISSION_CODE,
    EngineerChangeConditionReading, engineer_original_change_profile,
)
from src.coordination.engineer_change_author_conditions import check_engineer_change_author_handoff
from src.coordination.engineer_change_design_conditions import (
    check_engineer_change_design_authorization, check_engineer_change_design_candidate_limit,
    check_engineer_change_design_work_limit, check_engineer_change_design_submission, prepare_engineer_change_design_inputs,
)
from src.coordination.engineer_design_conditions import _check_engineer_design_history
from src.coordination.invocations import InvocationSnapshotStore
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, task_digest


class EngineerChangeRecoverySettings(EngineerSubmissionRecoverySettings):
    """Actual instruction recovery; native handoff/query archival is explicitly enabled."""
    terminal_author_handoff_enabled: bool = False
    terminal_submission_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_author_handoff_enabled:
            result.pop('terminal_author_handoff_enabled', None)
        if not self.terminal_submission_enabled:
            result.pop('terminal_submission_enabled', None)
        return result


@dataclass(frozen=True)
class EngineerChangeRecoveryBindings(EngineerSubmissionRecoveryBindings):
    """Guarded current sources and independent native instruction authentication."""


@dataclass(frozen=True)
class EngineerChangeCurrentSelection(ContractorCloseoutCurrentSelection):
    """Current original issue and separately authorized successor invocation."""


@dataclass(frozen=True)
class _EngineerChangeHistoryReading:
    context: ActionContext
    action_input: BaseModel
    reading: ActionReadView
    context_sha256: str
    input_sha256: str


class EngineerChangeRecoveryReader(ContractorCloseoutRecoveryReader):
    ACTION_ID = 'ENGINEER-A09'
    ROLE = 'Engineer'
    ASSEMBLER_TYPE = EngineerChangeActionAssembler
    SELECTION_TYPE = EngineerChangeCurrentSelection
    READING_TYPE = EngineerChangeConditionReading
    PROFILE_FACTORY = staticmethod(engineer_original_change_profile)
    ROOT_FIELD = 'issue_ref'
    SCOPE_FIELD = 'scope'
    READER_SCHEMA = 'engineer-change-recovery-reader.v1'
    CONDITION_CODES = (INSTRUCTION_REQUIRED_CODE, INSTRUCTION_AUTHORIZATION_CODE, AUTHOR_HANDOFF_CODE,
        DESIGN_AUTHORIZATION_CODE, DESIGN_CANDIDATE_CODE, DESIGN_WORK_CODE, DESIGN_SUBMISSION_CODE)
    CONDITION_KINDS = {INSTRUCTION_REQUIRED_CODE: ('Issue', 'Obligation'), INSTRUCTION_AUTHORIZATION_CODE: 'Instruction',
        AUTHOR_HANDOFF_CODE: ('Deliverable', 'Issue'), DESIGN_AUTHORIZATION_CODE: 'Task',
        DESIGN_CANDIDATE_CODE: 'DesignLimit', DESIGN_WORK_CODE: 'DesignLimit', DESIGN_SUBMISSION_CODE: 'Submission'}
    MULTI_REF_CONDITION_CODES = (INSTRUCTION_REQUIRED_CODE, AUTHOR_HANDOFF_CODE)
    CONDITION_REF_KIND_SEQUENCES = {INSTRUCTION_REQUIRED_CODE: ('Issue', 'Obligation'),
        INSTRUCTION_AUTHORIZATION_CODE: ('Instruction',), AUTHOR_HANDOFF_CODE: ('Deliverable', 'Issue'),
        DESIGN_AUTHORIZATION_CODE: ('Task',), DESIGN_CANDIDATE_CODE: ('DesignLimit',), DESIGN_WORK_CODE: ('DesignLimit',),
        DESIGN_SUBMISSION_CODE: ('Submission',)}

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract,
            handle_professional_change, check_engineer_change_author_handoff,
            check_engineer_change_design_authorization, prepare_engineer_change_design_inputs, _check_engineer_design_history,
            check_engineer_change_design_candidate_limit, recheck_original_engineer_change_candidate_limit,
            check_engineer_change_design_work_limit, recheck_original_engineer_change_work_limit,
            check_engineer_change_design_submission, recheck_original_engineer_change_submission)

    def _configuration(self):
        result = super()._configuration()
        result['change_checks'] = module_factory_descriptor(handle_professional_change, 'change_checks')
        result['author_handoff_checks'] = module_factory_descriptor(check_engineer_change_author_handoff, 'author_handoff_checks')
        result['revision_design_checks'] = module_factory_descriptor(check_engineer_change_design_authorization, 'revision_design_checks')
        result['revision_design_sources'] = module_factory_descriptor(prepare_engineer_change_design_inputs, 'revision_design_sources')
        result['professional_design_checks'] = module_factory_descriptor(_check_engineer_design_history, 'professional_design_checks')
        result['revision_candidate_checks'] = module_factory_descriptor(check_engineer_change_design_candidate_limit, 'revision_candidate_checks')
        result['historical_revision_candidate_checks'] = module_factory_descriptor(
            recheck_original_engineer_change_candidate_limit, 'historical_revision_candidate_checks')
        result['revision_work_checks'] = module_factory_descriptor(check_engineer_change_design_work_limit, 'revision_work_checks')
        result['historical_revision_work_checks'] = module_factory_descriptor(
            recheck_original_engineer_change_work_limit, 'historical_revision_work_checks')
        result['revision_submission_checks'] = module_factory_descriptor(check_engineer_change_design_submission, 'revision_submission_checks')
        result['historical_revision_submission_checks'] = module_factory_descriptor(
            recheck_original_engineer_change_submission, 'historical_revision_submission_checks')
        return result

    def __call__(self, check, *, history_terminal=False):
        if history_terminal and check.condition.condition_code not in {AUTHOR_HANDOFF_CODE, DESIGN_SUBMISSION_CODE}:
            raise ValueError('Only actual author-handoff receipts or prior revision queries support terminal status archival')
        return replace(super().__call__(check, history_terminal=history_terminal),
            contract=self.assembler.registry.get(self.ACTION_ID).contract)

    def _assemble_current(self, context, action_input, history_terminal):
        if not history_terminal:
            return super()._assemble_current(context, action_input, history_terminal)
        assembler = self.assembler
        registration = assembler.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.skill is None or registration.role != self.ROLE:
            raise TaskConflict('Author handoff history requires the original implemented A09 contract')
        resolver = assembler._views.build_resolver(context, self.ACTION_ID, self.ROLE)
        reading = ActionReadView(context, resolver, assembler.organizations, self.ACTION_ID, self.ROLE,
            methods=assembler.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            for ref in walk_references(action_input):
                reading.resolve(ref)
            return _EngineerChangeHistoryReading(context, action_input, reading,
                task_digest(context.model_dump(mode='json')), task_digest(action_input.model_dump(mode='json')))
        finally:
            reading.recheck()


def build_assembled_engineer_change_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or EngineerChangeRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, EngineerChangeRecoveryReader):
        raise ValueError('Revision recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
