"""Read original QS A02 terms/policy wait with its actual conflict and fee checks."""
from dataclasses import dataclass

from integration.architect_intake_recovery_reader import ArchitectIntakeRecoveryReader, ArchitectIntakeCurrentSelection
from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from integration.qs_appointment_reader import QSAppointmentRecoverySettings, QSAppointmentRecoveryBindings
from integration.qs_intake_actions import QSIntakeActionAssembler
from src.actions.roles.qs import assess_service_request
from src.actions.roles.service_intake import recheck_original_service_policy_wait
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.service_intake_conditions import qs_original_intake_profile


class QSIntakeRecoverySettings(QSAppointmentRecoverySettings):
    """Original actual source/policy versions; no terminal archive."""


@dataclass(frozen=True)
class QSIntakeCurrentSelection(ArchitectIntakeCurrentSelection):
    """Actual current offered terms and independently selected QS service input."""


@dataclass(frozen=True)
class QSIntakeRecoveryBindings(QSAppointmentRecoveryBindings):
    """Actual guarded task query, native conflict/history and successor callbacks."""


class QSIntakeRecoveryReader(ArchitectIntakeRecoveryReader):
    ACTION_ID = 'QS-A02'
    ROLE = 'QS'
    ASSEMBLER_TYPE = QSIntakeActionAssembler
    SELECTION_TYPE = QSIntakeCurrentSelection
    PROFILE_FACTORY = staticmethod(qs_original_intake_profile)
    READER_SCHEMA = 'qs-intake-recovery-reader.v1'

    def _components(self):
        return (*ContractorCloseoutRecoveryReader._components(self),
            self.assembler.registry.get(self.ACTION_ID).contract, assess_service_request, recheck_original_service_policy_wait)

    def _configuration(self):
        result = ContractorCloseoutRecoveryReader._configuration(self)
        result['intake_checks'] = module_factory_descriptor(assess_service_request, 'intake_checks')
        result['historical_policy_checks'] = module_factory_descriptor(recheck_original_service_policy_wait, 'historical_policy_checks')
        return result


def build_assembled_qs_intake_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or QSIntakeRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, QSIntakeRecoveryReader):
        raise ValueError('QS intake recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
