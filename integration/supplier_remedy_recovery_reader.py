"""Select actual original Supplier remedy requests and refund executions under the existing source guard."""
from dataclasses import dataclass
from pydantic import BaseModel, model_serializer

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, build_assembled_contractor_closeout_dispatcher,
)
from integration.supplier_remedy_actions import SupplierRemedyActionAssembler
from integration.supplier_transport_reader import SupplierTransportRecoveryBindings
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId, walk_references
from src.actions.contracts.references import ActionReadView
from src.coordination.supplier_remedy_conditions import (
    REQUEST_CODE, REFUND_CODE, SupplierRemedyConditionReading, supplier_original_remedy_profile,
)
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class SupplierRemedyCurrentSelection:
    request: RoleContractInvocation
    history_ref: Reference


@dataclass(frozen=True)
class _SupplierRemedyHistoryReading:
    context: ActionContext
    action_input: BaseModel
    reading: ActionReadView
    context_sha256: str
    input_sha256: str


class SupplierRemedyRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    terminal_history_enabled: bool = False
    terminal_refund_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        for field in ('terminal_history_enabled', 'terminal_refund_enabled'):
            if not getattr(self, field):
                result.pop(field, None)
        return result


@dataclass(frozen=True)
class SupplierRemedyRecoveryBindings(SupplierTransportRecoveryBindings):
    """Reuse actual source selection, native validation and independently prepared successor callbacks."""


class SupplierRemedyRecoveryReader(ContractorCloseoutRecoveryReader):
    ACTION_ID = 'SUPPLIER-A11'
    ROLE = 'Supplier'
    ASSEMBLER_TYPE = SupplierRemedyActionAssembler
    SELECTION_TYPE = SupplierRemedyCurrentSelection
    READING_TYPE = SupplierRemedyConditionReading
    PROFILE_FACTORY = staticmethod(supplier_original_remedy_profile)
    ROOT_FIELD = 'order_ref'
    SCOPE_FIELD = None
    PROVIDER_ATTRIBUTE = 'view_provider'
    READER_SCHEMA = 'supplier-remedy-recovery-reader.v1'
    CONDITION_CODES = (REQUEST_CODE, REFUND_CODE)
    CONDITION_KINDS = {REQUEST_CODE: 'SupplyRemedyRequest', REFUND_CODE: 'RefundExecution'}

    def _assemble_current(self, context, action_input, history_terminal):
        if not history_terminal:
            return super()._assemble_current(context, action_input, history_terminal)
        # Archive the immutable original proposal under actual current read
        # grants. Its historical profile authority is checked at original time
        # by the condition checker, never reused as a current grant.
        assembler = self.assembler
        registration = assembler.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.skill is None or registration.role != self.ROLE:
            raise TaskConflict('Remedy history reading requires its original implemented Supplier contract')
        resolver = assembler._views.build_resolver(context, self.ACTION_ID, self.ROLE)
        reading = ActionReadView(context, resolver, assembler.organizations, self.ACTION_ID, self.ROLE,
            methods=assembler.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            for ref in walk_references(action_input):
                reading.resolve(ref)
            return _SupplierRemedyHistoryReading(context, action_input, reading,
                task_digest(context.model_dump(mode='json')), task_digest(action_input.model_dump(mode='json')))
        finally:
            reading.recheck()


def build_assembled_supplier_remedy_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or SupplierRemedyRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
