"""Read original upstream procurement commitments through the actual A05 source guard."""
from dataclasses import dataclass, replace
from pydantic import model_serializer

from integration.contractor_closeout_recovery_reader import build_assembled_contractor_closeout_dispatcher
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from integration.supplier_planning_actions import SupplierPlanningActionAssembler
from integration.supplier_remedy_recovery_reader import SupplierRemedyRecoveryReader
from integration.supplier_transport_reader import SupplierTransportRecoveryBindings
from src.actions.contracts.common import Reference, StrictRecord, TextId
from src.actions.roles.supplier_planning import plan_supply
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.supplier_procurement_conditions import (
    CODE, SupplierProcurementConditionReading, supplier_original_procurement_profile,
)


@dataclass(frozen=True)
class SupplierProcurementCurrentSelection:
    request: RoleContractInvocation
    history_ref: Reference


class SupplierProcurementRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    terminal_procurement_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_procurement_enabled:
            result.pop('terminal_procurement_enabled', None)
        return result


@dataclass(frozen=True)
class SupplierProcurementRecoveryBindings(SupplierTransportRecoveryBindings):
    """Actual commitment query, source guard and independent successor callbacks."""


class SupplierProcurementRecoveryReader(SupplierRemedyRecoveryReader):
    ACTION_ID = 'SUPPLIER-A05'
    ASSEMBLER_TYPE = SupplierPlanningActionAssembler
    SELECTION_TYPE = SupplierProcurementCurrentSelection
    READING_TYPE = SupplierProcurementConditionReading
    PROFILE_FACTORY = staticmethod(supplier_original_procurement_profile)
    ROOT_FIELD = 'work_authority_ref'
    SCOPE_FIELD = 'scope_ref'
    READER_SCHEMA = 'supplier-procurement-recovery-reader.v1'
    CONDITION_CODES = (CODE,)
    CONDITION_KINDS = {CODE: 'UpstreamSupplyCommitment'}

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract, plan_supply)

    def _configuration(self):
        result = super()._configuration()
        result['procurement_checks'] = module_factory_descriptor(plan_supply, 'procurement_checks')
        return result

    def __call__(self, check, *, history_terminal=False):
        selected = super().__call__(check, history_terminal=history_terminal)
        return replace(selected, contract=self.assembler.registry.get(self.ACTION_ID).contract)

    def _assemble_current(self, context, action_input, history_terminal):
        if history_terminal:
            return super()._assemble_current(context, action_input, history_terminal)
        values = action_input.model_dump(mode='json')
        # The A05 assembler derives this exact field from its authorized context.
        values.pop('scope_ref')
        return self.assembler.build(context, **values)


def build_assembled_supplier_procurement_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or SupplierProcurementRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, SupplierProcurementRecoveryReader):
        raise ValueError('Procurement recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
