"""Read original Engineer A02 terms/policy waits with actual professional hooks."""
from dataclasses import dataclass

from integration.architect_intake_recovery_reader import ArchitectIntakeRecoveryReader, ArchitectIntakeCurrentSelection
from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, build_assembled_contractor_closeout_dispatcher,
)
from integration.engineer_intake_actions import EngineerIntakeActionAssembler
from integration.engineer_submission_receipt_reader import EngineerSubmissionRecoverySettings, EngineerSubmissionRecoveryBindings
from integration.module_host import module_factory_descriptor
from src.actions.roles.engineer import assess_service_request
from src.actions.roles.service_intake import recheck_original_service_policy_wait
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.service_intake_conditions import engineer_original_intake_profile


class EngineerIntakeRecoverySettings(EngineerSubmissionRecoverySettings):
    """Original private sources and policy versions; no terminal archive."""


@dataclass(frozen=True)
class EngineerIntakeCurrentSelection(ArchitectIntakeCurrentSelection):
    """Actual current terms and independently selected Engineer service invocation."""


@dataclass(frozen=True)
class EngineerIntakeRecoveryBindings(EngineerSubmissionRecoveryBindings):
    """Actual guarded sources, independent native history and successor callbacks."""


class EngineerIntakeRecoveryReader(ArchitectIntakeRecoveryReader):
    ACTION_ID = 'ENGINEER-A02'
    ROLE = 'Engineer'
    ASSEMBLER_TYPE = EngineerIntakeActionAssembler
    SELECTION_TYPE = EngineerIntakeCurrentSelection
    PROFILE_FACTORY = staticmethod(engineer_original_intake_profile)
    READER_SCHEMA = 'engineer-intake-recovery-reader.v1'

    def _components(self):
        return (*ContractorCloseoutRecoveryReader._components(self),
            self.assembler.registry.get(self.ACTION_ID).contract, assess_service_request, recheck_original_service_policy_wait)

    def _configuration(self):
        result = ContractorCloseoutRecoveryReader._configuration(self)
        result['intake_checks'] = module_factory_descriptor(assess_service_request, 'intake_checks')
        result['historical_policy_checks'] = module_factory_descriptor(recheck_original_service_policy_wait, 'historical_policy_checks')
        return result


def build_assembled_engineer_intake_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or EngineerIntakeRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, EngineerIntakeRecoveryReader):
        raise ValueError('Engineer intake recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
