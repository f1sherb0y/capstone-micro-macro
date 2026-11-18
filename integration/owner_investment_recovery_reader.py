"""Bind original A03 waits to saved evidence and a current authorized comparison."""
from dataclasses import dataclass

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutCurrentSelection, build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from integration.owner_continuation_execution_reader import OwnerContinuationRecoveryBindings, OwnerContinuationRecoverySettings
from integration.owner_investment_actions import OwnerInvestmentActionAssembler, validate_owner_investment_sources
from integration.owner_investment_results import OwnerInvestmentResultWorker
from integration.owner_saved_wait_recovery_reader import OwnerSavedWaitRecoveryReader
from src.actions.roles.owner_investment import decide_investment
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.owner_closeout_conditions import same_closeout_scope
from src.coordination.owner_investment_conditions import CODE, OwnerInvestmentConditionReading, owner_original_investment_profile


class OwnerInvestmentRecoverySettings(OwnerContinuationRecoverySettings):
    """Versioned actual sources; an investment wait has no terminal archive."""


@dataclass(frozen=True)
class OwnerInvestmentCurrentSelection(ContractorCloseoutCurrentSelection):
    """Explicit new invocation and actual current OptionComparison version."""


@dataclass(frozen=True)
class OwnerInvestmentRecoveryBindings(OwnerContinuationRecoveryBindings):
    assembler: OwnerInvestmentActionAssembler
    snapshots: InvocationSnapshotStore

    def __post_init__(self):
        if (type(self.assembler) is not OwnerInvestmentActionAssembler
                or not isinstance(self.snapshots, InvocationSnapshotStore)
                or not all(callable(value) for value in super().components()[1:])):
            raise ValueError('Owner investment recovery requires its actual assembler, same journal and callbacks')
        object.__setattr__(self, '_reader', OwnerInvestmentRecoveryReader(assembler=self.assembler,
            snapshots=self.snapshots, select_current=self.select_current))

    def components(self):
        return (*super().components(), self.snapshots, self.snapshots.store)


class OwnerInvestmentRecoveryReader(OwnerSavedWaitRecoveryReader):
    ACTION_ID = 'OWN-A03'
    ROLE = 'Owner'
    ASSEMBLER_TYPE = OwnerInvestmentActionAssembler
    SELECTION_TYPE = OwnerInvestmentCurrentSelection
    READING_TYPE = OwnerInvestmentConditionReading
    PROFILE_FACTORY = staticmethod(owner_original_investment_profile)
    RESULT_WORKER_TYPE = OwnerInvestmentResultWorker
    VALIDATE_ORIGINAL_SOURCES = staticmethod(validate_owner_investment_sources)
    ROOT_FIELD = 'case_ref'
    SCOPE_FIELD = None
    READER_SCHEMA = 'owner-investment-recovery-reader.v1'
    CONDITION_CODES = (CODE,)
    CONDITION_KINDS = {CODE: ('OptionComparison', 'ProjectRegistrationProfile', 'OwnerPortfolio')}
    CONDITION_REF_KIND_SEQUENCES = {CODE: ('OptionComparison', 'ProjectRegistrationProfile', 'OwnerPortfolio')}
    _same_scope = staticmethod(same_closeout_scope)

    def _components(self):
        return (*super()._components(), decide_investment)

    def _configuration(self):
        result = super()._configuration()
        result['investment_checks'] = module_factory_descriptor(decide_investment, 'investment_checks')
        return result


def build_assembled_owner_investment_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or OwnerInvestmentRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, OwnerInvestmentRecoveryReader):
        raise ValueError('Owner investment recovery requires its actual typed same-journal reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
