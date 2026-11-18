"""Persist original A06 requests and queries without recording native production effects."""
from dataclasses import dataclass

from integration.supplier_planning_handoff import supplier_planning_handoff_schemas
from integration.supplier_execution_actions import PreparedSupplierExecution
from integration.supplier_quote_results import SavedSupplierQuote, SupplierQuoteResultWorker
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.supplier_execution_objects import (
    SupplierActualInventoryView, SupplierExecutionProfileView, SupplierExecutionTaskView,
    SupplierProductionAllocationView, SupplierProductionExecutionView, supplier_execution_schemas,
)
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class SavedSupplierExecution(SavedSupplierQuote):
    """Historical local request/query evidence; no native execution receipt is implied."""


class SupplierExecutionResultWorker(SupplierQuoteResultWorker):
    """Share original claim-once and interrupted-result rules with an A06 schema/table."""
    SCHEMA = 'supplier-execution-result.v1'
    ACTION_ID = 'SUPPLIER-A06'
    PREPARED_TYPE = PreparedSupplierExecution
    RESULT_TABLE = 'supplier_execution_results'
    WAIT_KIND = 'manual_supplier_execution_result_review'
    EXECUTION_ERROR_CODE = 'supplier_execution_exception'
    SOURCE_SCHEMAS = staticmethod(supplier_planning_handoff_schemas)
    READ_ACTION_IDS = frozenset({'SUPPLIER-A06', 'SUPPLIER-A07', 'SUPPLIER-A12'})
    SAVED_TYPE = SavedSupplierExecution

    @staticmethod
    def _original(sources, ref, schema):
        originals = [row for row in sources if Reference.model_validate(row['ref']).key() == ref.key()]
        if len(originals) != 1:
            raise TaskConflict('Saved execution lacks its exact original task or source version')
        row = schema.model_validate(originals[0]['projection'])
        if row.ref.key() != ref.key():
            raise TaskConflict('Saved execution projection changes its original reference')
        return row

    def _validate_primary_sources(self, snapshot, identity, sources):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = snapshot['action_input']
        task = self._original(sources, Reference.model_validate(action_input['task_ref']), SupplierExecutionTaskView)
        profile = self._original(sources, task.profile_ref, SupplierExecutionProfileView)
        inventory = self._original(sources, Reference.model_validate(action_input['inventory_ref']), SupplierActualInventoryView)
        if (any(row.organization_id != identity.organization_id for row in (task, profile, inventory))
                or not scope_covers(context.scope, task.scope) or profile.scope != context.scope
                or profile.task_ref != task.ref or profile.actor_id != context.actor_id
                or profile.function_ref != context.function_ref
                or profile.authority_ref not in context.authorization_refs):
            raise TaskConflict('Saved execution changes original Supplier, task, scope or profile authority')
        for raw_ref in action_input['available_input_refs']:
            allocation = self._original(sources, Reference.model_validate(raw_ref), SupplierProductionAllocationView)
            if allocation.organization_id != identity.organization_id or allocation.task_ref != task.ref:
                raise TaskConflict('Saved resource allocation changes original Supplier or task')
        for raw_ref in action_input['prior_execution_refs']:
            execution = self._original(sources, Reference.model_validate(raw_ref), SupplierProductionExecutionView)
            if (execution.organization_id != identity.organization_id or execution.task_ref != task.ref
                    or execution.run_id != identity.run_id):
                raise TaskConflict('Saved execution history changes original run, Supplier or task')

    def prepare_order_handoff(self, *args, **kwargs):
        raise ValueError('A06 saved request/query is not an A03 quote or a native production receipt')

    def prepare_quality_handoff(self, identity, *, current_context, reading, execution_versions,
            basis_ref, batch_ref, validate_history, validate_current):
        from integration.supplier_execution_handoff import prepare_supplier_execution_handoff

        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        saved = self.read_completed(identity, current_context=current, reading=reading,
            execution_versions=execution_versions, validate_current=validate_history)
        return prepare_supplier_execution_handoff(saved, context=current, reading=reading,
            basis_ref=basis_ref, batch_ref=batch_ref, validate_current=validate_current)
