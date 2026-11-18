"""Reassemble actual original A01 inquiries after an independently revised policy."""
from dataclasses import dataclass, replace

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from integration.supplier_remedy_recovery_reader import SupplierRemedyRecoveryReader, SupplierRemedyCurrentSelection
from integration.supplier_screening_actions import SupplierScreeningActionAssembler
from integration.supplier_transport_reader import SupplierTransportRecoveryBindings
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.roles.supplier import screen_demand, recheck_original_supplier_policy_wait
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.supplier_policy_conditions import (
    CODE, SupplierPolicyConditionReading, supplier_original_policy_profile,
)


class SupplierPolicyRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId


@dataclass(frozen=True)
class SupplierPolicyCurrentSelection(SupplierRemedyCurrentSelection):
    """Actual current policy and independently selected original inquiry sources."""


@dataclass(frozen=True)
class SupplierPolicyRecoveryBindings(SupplierTransportRecoveryBindings):
    """Actual policy query, guarded sources, native validation and successor callbacks."""


class SupplierPolicyRecoveryReader(SupplierRemedyRecoveryReader):
    ACTION_ID = 'SUPPLIER-A01'
    ASSEMBLER_TYPE = SupplierScreeningActionAssembler
    SELECTION_TYPE = SupplierPolicyCurrentSelection
    READING_TYPE = SupplierPolicyConditionReading
    PROFILE_FACTORY = staticmethod(supplier_original_policy_profile)
    ROOT_FIELD = 'capability_ref'
    SCOPE_FIELD = None
    READER_SCHEMA = 'supplier-policy-recovery-reader.v1'
    CONDITION_CODES = (CODE,)
    CONDITION_KINDS = {CODE: 'SupplyScreeningProfile'}

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract,
            screen_demand, recheck_original_supplier_policy_wait)

    def _configuration(self):
        result = super()._configuration()
        result['screening_checks'] = module_factory_descriptor(screen_demand, 'screening_checks')
        result['historical_policy_checks'] = module_factory_descriptor(recheck_original_supplier_policy_wait, 'historical_policy_checks')
        return result

    def __call__(self, check, *, history_terminal=False):
        if history_terminal:
            raise ValueError('Policy revision must resume screening; no terminal archive is available')
        selected = super().__call__(check, history_terminal=False)
        return replace(selected, contract=self.assembler.registry.get(self.ACTION_ID).contract)

    def _assemble_current(self, context, action_input, history_terminal):
        return ContractorCloseoutRecoveryReader._assemble_current(self, context, action_input, history_terminal)


def build_assembled_supplier_policy_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or SupplierPolicyRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, SupplierPolicyRecoveryReader):
        raise ValueError('Policy recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
