"""Reassemble original A02 terms and provider policy through the actual source guard."""
from dataclasses import dataclass, replace

from integration.architect_intake_actions import ArchitectIntakeActionAssembler
from integration.architect_submission_receipt_reader import ArchitectSubmissionRecoverySettings, ArchitectSubmissionRecoveryBindings
from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, ContractorCloseoutCurrentSelection, build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from src.actions.roles.architect import assess_service_request
from src.actions.roles.service_intake import recheck_original_service_policy_wait
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.service_intake_conditions import CODE, ServiceIntakeConditionReading, architect_original_intake_profile


class ArchitectIntakeRecoverySettings(ArchitectSubmissionRecoverySettings):
    """Original private sources and policy versions; no terminal archive."""


@dataclass(frozen=True)
class ArchitectIntakeCurrentSelection(ContractorCloseoutCurrentSelection):
    """Actual current offered terms plus independently selected original service input."""


@dataclass(frozen=True)
class ArchitectIntakeRecoveryBindings(ArchitectSubmissionRecoveryBindings):
    """Actual guarded terms/policy query, native validation and successor callbacks."""


class ArchitectIntakeRecoveryReader(ContractorCloseoutRecoveryReader):
    ACTION_ID = 'ARCHITECT-A02'
    ROLE = 'Architect'
    ASSEMBLER_TYPE = ArchitectIntakeActionAssembler
    SELECTION_TYPE = ArchitectIntakeCurrentSelection
    READING_TYPE = ServiceIntakeConditionReading
    PROFILE_FACTORY = staticmethod(architect_original_intake_profile)
    ROOT_FIELD = 'request_ref'
    SCOPE_FIELD = 'scope'
    READER_SCHEMA = 'architect-intake-recovery-reader.v1'
    CONDITION_CODES = (CODE,)
    CONDITION_KINDS = {CODE: 'ServiceTerms'}
    CONDITION_REF_KIND_SEQUENCES = {CODE: ['ServiceTerms', 'FeeBasis']}

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract,
            assess_service_request, recheck_original_service_policy_wait)

    def _configuration(self):
        result = super()._configuration()
        result['intake_checks'] = module_factory_descriptor(assess_service_request, 'intake_checks')
        result['historical_policy_checks'] = module_factory_descriptor(recheck_original_service_policy_wait, 'historical_policy_checks')
        return result

    def __call__(self, check, *, history_terminal=False):
        if history_terminal:
            raise ValueError('Service terms/policy reassessment must resume intake; no terminal archive is available')
        selected = super().__call__(check, history_terminal=False)
        return replace(selected, contract=self.assembler.registry.get(self.ACTION_ID).contract)


def build_assembled_architect_intake_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or ArchitectIntakeRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, ArchitectIntakeRecoveryReader):
        raise ValueError('Intake recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
