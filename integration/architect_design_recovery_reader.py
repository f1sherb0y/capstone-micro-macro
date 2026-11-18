"""Reassemble original A05 design task authorization waits through actual guarded sources."""
from dataclasses import dataclass, replace
from pydantic import BaseModel, model_serializer

from integration.architect_design_actions import ArchitectDesignActionAssembler
from integration.architect_submission_receipt_reader import ArchitectSubmissionRecoverySettings, ArchitectSubmissionRecoveryBindings
from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, ContractorCloseoutCurrentSelection, build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from src.actions.roles.architect_design import (
    compile_design, recheck_original_architect_design_candidate_limit, recheck_original_architect_design_work_limit,
    recheck_original_architect_design_submission,
)
from src.coordination.architect_design_conditions import (
    AUTHORIZATION_CODE, CANDIDATE_CODE, WORK_CODE, SUBMISSION_CODE, ArchitectDesignConditionReading, architect_original_design_profile,
)
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.references import ActionReadView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, task_digest


class ArchitectDesignRecoverySettings(ArchitectSubmissionRecoverySettings):
    """Actual original design queries; submission archival requires an explicit switch."""
    terminal_submission_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_submission_enabled:
            result.pop('terminal_submission_enabled', None)
        return result


@dataclass(frozen=True)
class ArchitectDesignCurrentSelection(ContractorCloseoutCurrentSelection):
    """Actual current version of the original deferred design task."""


@dataclass(frozen=True)
class ArchitectDesignRecoveryBindings(ArchitectSubmissionRecoveryBindings):
    """Actual guarded task history, native authorization and successor callbacks."""


@dataclass(frozen=True)
class _ArchitectDesignHistoryReading:
    context: ActionContext
    action_input: BaseModel
    reading: ActionReadView
    context_sha256: str
    input_sha256: str


class ArchitectDesignRecoveryReader(ContractorCloseoutRecoveryReader):
    ACTION_ID = 'ARCHITECT-A05'
    ROLE = 'Architect'
    ASSEMBLER_TYPE = ArchitectDesignActionAssembler
    SELECTION_TYPE = ArchitectDesignCurrentSelection
    READING_TYPE = ArchitectDesignConditionReading
    PROFILE_FACTORY = staticmethod(architect_original_design_profile)
    ROOT_FIELD = 'task_ref'
    SCOPE_FIELD = 'scope'
    READER_SCHEMA = 'architect-design-recovery-reader.v1'
    CONDITION_CODES = (AUTHORIZATION_CODE, CANDIDATE_CODE, WORK_CODE, SUBMISSION_CODE)
    CONDITION_KINDS = {AUTHORIZATION_CODE: 'Task', CANDIDATE_CODE: 'DesignLimit', WORK_CODE: 'DesignLimit', SUBMISSION_CODE: 'Submission'}
    CONDITION_REF_KIND_SEQUENCES = {CANDIDATE_CODE: ['DesignLimit', 'Task']}

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract, compile_design,
            recheck_original_architect_design_candidate_limit, recheck_original_architect_design_work_limit,
            recheck_original_architect_design_submission)

    def _configuration(self):
        result = super()._configuration()
        result['design_checks'] = module_factory_descriptor(compile_design, 'design_checks')
        result['historical_candidate_checks'] = module_factory_descriptor(recheck_original_architect_design_candidate_limit, 'historical_candidate_checks')
        result['historical_work_checks'] = module_factory_descriptor(recheck_original_architect_design_work_limit, 'historical_work_checks')
        result['historical_submission_checks'] = module_factory_descriptor(recheck_original_architect_design_submission, 'historical_submission_checks')
        return result

    def __call__(self, check, *, history_terminal=False):
        if history_terminal and check.condition.condition_code != SUBMISSION_CODE:
            raise ValueError('Only original design submission queries support terminal status archival')
        selected = super().__call__(check, history_terminal=history_terminal)
        return replace(selected, contract=self.assembler.registry.get(self.ACTION_ID).contract)


    def _assemble_current(self, context, action_input, history_terminal):
        if not history_terminal:
            return super()._assemble_current(context, action_input, history_terminal)
        assembler = self.assembler
        registration = assembler.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.skill is None or registration.role != self.ROLE:
            raise TaskConflict('Design history reading requires its actual original implemented Architect contract')
        resolver = assembler._views.build_resolver(context, self.ACTION_ID, self.ROLE)
        reading = ActionReadView(context, resolver, assembler.organizations, self.ACTION_ID, self.ROLE,
            methods=assembler.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            for ref in walk_references(action_input):
                reading.resolve(ref)
            return _ArchitectDesignHistoryReading(context, action_input, reading,
                task_digest(context.model_dump(mode='json')), task_digest(action_input.model_dump(mode='json')))
        finally:
            reading.recheck()


def build_assembled_architect_design_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or ArchitectDesignRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, ArchitectDesignRecoveryReader):
        raise ValueError('Design recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
