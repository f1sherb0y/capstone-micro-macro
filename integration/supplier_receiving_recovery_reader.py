"""Select original A09 shipment queries and replacement history under actual source guards."""
from dataclasses import dataclass, replace
from pydantic import model_serializer

from integration.contractor_closeout_recovery_reader import build_assembled_contractor_closeout_dispatcher
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from integration.supplier_receiving_actions import SupplierReceivingActionAssembler
from integration.supplier_remedy_recovery_reader import SupplierRemedyRecoveryReader
from integration.supplier_transport_reader import SupplierTransportRecoveryBindings
from src.actions.contracts.common import Reference, StrictRecord, TextId
from src.actions.roles.supplier_receiving import respond_to_receiving
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.supplier_receiving_conditions import (
    SHIPMENT_CODE, REPLACEMENT_CODE, SupplierReceivingConditionReading, supplier_original_receiving_profile,
)


@dataclass(frozen=True)
class SupplierReceivingCurrentSelection:
    request: RoleContractInvocation
    history_ref: Reference


class SupplierReceivingRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    terminal_replacement_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_replacement_enabled:
            result.pop('terminal_replacement_enabled', None)
        return result


@dataclass(frozen=True)
class SupplierReceivingRecoveryBindings(SupplierTransportRecoveryBindings):
    """Original guarded source, native history and independently prepared successor callbacks."""


class SupplierReceivingRecoveryReader(SupplierRemedyRecoveryReader):
    ACTION_ID = 'SUPPLIER-A09'
    ASSEMBLER_TYPE = SupplierReceivingActionAssembler
    SELECTION_TYPE = SupplierReceivingCurrentSelection
    READING_TYPE = SupplierReceivingConditionReading
    PROFILE_FACTORY = staticmethod(supplier_original_receiving_profile)
    ROOT_FIELD = 'shipment_ref'
    READER_SCHEMA = 'supplier-receiving-recovery-reader.v1'
    CONDITION_CODES = (SHIPMENT_CODE, REPLACEMENT_CODE)
    CONDITION_KINDS = {SHIPMENT_CODE: 'Shipment', REPLACEMENT_CODE: 'DeliveryReplacementProposal'}

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract, respond_to_receiving)

    def __call__(self, check, *, history_terminal=False):
        selected = super().__call__(check, history_terminal=history_terminal)
        return replace(selected, contract=self.assembler.registry.get(self.ACTION_ID).contract)

    def _configuration(self):
        result = super()._configuration()
        result['receiving_checks'] = module_factory_descriptor(respond_to_receiving, 'receiving_checks')
        return result


def build_assembled_supplier_receiving_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or SupplierReceivingRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, SupplierReceivingRecoveryReader):
        raise ValueError('Receiving recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
