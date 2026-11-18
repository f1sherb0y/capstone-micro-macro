"""Read original Supplier A06 inventory pending commands without consuming stock."""
from dataclasses import dataclass
from typing import Literal

from integration.role_contract_host import RoleContractInvocation
from integration.supplier_execution_reader import SupplierExecutionRecoveryBindings, SupplierExecutionRecoverySettings
from integration.supplier_resource_reader import SupplierResourceReader, _build_assembled_supplier_input_dispatcher
from src.actions.contracts.common import Reference
from src.actions.contracts.supplier_execution_objects import SupplierActualInventoryView
from src.coordination.supplier_inventory_conditions import SupplierInventoryConditionReading, _CODE
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SupplierInventoryCurrentSelection:
    request: RoleContractInvocation
    execution_refs: tuple[Reference, ...]


class SupplierInventoryRecoverySettings(SupplierExecutionRecoverySettings):
    wait_kind: Literal['inventory_query'] = 'inventory_query'


@dataclass(frozen=True)
class SupplierInventoryRecoveryBindings(SupplierExecutionRecoveryBindings):
    """Actual inventory selector, original guard and native/successor validators."""


class SupplierInventoryReader(SupplierResourceReader):
    """Recover original inventory demand using the same immutable task snapshot.

    Current and original inventory versions must be explicitly authorized.
    Pending commands are read independently across tasks; current own history
    stays complete. The inherited source/snapshot checks and guarded bridge
    run no processor, method, model, stock consumption or reservation release.
    """
    CONDITION_CODE = _CODE
    SELECTION_TYPE = SupplierInventoryCurrentSelection
    SCHEMA_VERSION = 'supplier-inventory-reader.v1'

    def _dependency_refs(self, selected):
        request = RoleContractInvocation.model_validate(selected.request)
        return (Reference.model_validate(request.action_input['inventory_ref']),)

    def _valid_dependencies(self, refs):
        return len(refs) == 1 and refs[0].kind == 'InventorySnapshot'

    def _validate_dependencies(self, prepared, refs, source, original_input):
        current = prepared.reading.resolve(refs[0])
        original = prepared.reading.resolve(original_input.inventory_ref)
        if (not isinstance(original, SupplierActualInventoryView) or not isinstance(current, SupplierActualInventoryView)
                or original.ref.key() != original_input.inventory_ref.key() or current.ref.key() != refs[0].key()
                or original.ref.key()[:2] != current.ref.key()[:2]
                or current.ref.key() != prepared.action_input.inventory_ref.key()
                or original.organization_id != source['organization_id'] or current.organization_id != original.organization_id
                or current.scope != original.scope):
            raise TaskConflict('Supplier inventory reader replaces original inventory version, physical identity, owner or scope')

    def _condition_reading(self, prepared, refs, dependencies, snapshot):
        from copy import deepcopy

        return SupplierInventoryConditionReading(prepared.context, prepared.reading, refs,
            deepcopy(snapshot['action_input']), prepared.action_input.model_dump(mode='json'))


def build_assembled_supplier_inventory_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold one original source/authority/inbox/journal guard across inventory recovery."""
    from integration.task_continuation import build_supplier_inventory_continuation_dispatcher

    return _build_assembled_supplier_input_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate,
        reader_type=SupplierInventoryReader, dispatcher_factory=build_supplier_inventory_continuation_dispatcher)
