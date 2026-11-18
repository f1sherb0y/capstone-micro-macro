"""Select original payment claims under guarded same-store Supplier history reads."""
from dataclasses import dataclass, replace
from pydantic import model_serializer

from integration.contractor_closeout_recovery_reader import build_assembled_contractor_closeout_dispatcher
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from integration.supplier_payment_actions import SupplierPaymentActionAssembler
from integration.supplier_remedy_recovery_reader import SupplierRemedyRecoveryReader
from integration.supplier_transport_reader import SupplierTransportRecoveryBindings
from src.actions.contracts.common import Reference, StrictRecord, TextId
from src.actions.roles.supplier_payment import manage_supplier_cash, recheck_original_supplier_claim_wait
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.supplier_payment_conditions import (
    SAME_CODE, NODE_CODE, SupplierPaymentConditionReading, supplier_original_payment_claim_profile,
)
from src.methods.supplier_payment import calculate_claim_amount


@dataclass(frozen=True)
class SupplierPaymentCurrentSelection:
    request: RoleContractInvocation
    history_ref: Reference


class SupplierPaymentRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    terminal_claim_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_claim_enabled:
            result.pop('terminal_claim_enabled', None)
        return result


@dataclass(frozen=True)
class SupplierPaymentRecoveryBindings(SupplierTransportRecoveryBindings):
    """Actual claim query, source guard and independently checked successor callbacks."""


class SupplierPaymentRecoveryReader(SupplierRemedyRecoveryReader):
    ACTION_ID = 'SUPPLIER-A10'
    ASSEMBLER_TYPE = SupplierPaymentActionAssembler
    SELECTION_TYPE = SupplierPaymentCurrentSelection
    READING_TYPE = SupplierPaymentConditionReading
    PROFILE_FACTORY = staticmethod(supplier_original_payment_claim_profile)
    ROOT_FIELD = None
    READER_SCHEMA = 'supplier-payment-recovery-reader.v1'
    CONDITION_CODES = (SAME_CODE, NODE_CODE)
    CONDITION_KINDS = {SAME_CODE: 'PaymentClaim', NODE_CODE: 'PaymentClaim'}

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract,
            manage_supplier_cash, recheck_original_supplier_claim_wait, calculate_claim_amount)

    def __call__(self, check, *, history_terminal=False):
        selected = super().__call__(check, history_terminal=history_terminal)
        return replace(selected, contract=self.assembler.registry.get(self.ACTION_ID).contract)

    def _configuration(self):
        result = super()._configuration()
        for name, callback in (('payment_checks', manage_supplier_cash),
                ('original_claim_checks', recheck_original_supplier_claim_wait), ('claim_arithmetic', calculate_claim_amount)):
            result[name] = module_factory_descriptor(callback, name)
        return result


def build_assembled_supplier_payment_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or SupplierPaymentRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, SupplierPaymentRecoveryReader):
        raise ValueError('Payment claim recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
