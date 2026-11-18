"""Persist original Supplier A05 plans and requests without granting execution."""
from dataclasses import dataclass
from pydantic import TypeAdapter

from integration.supplier_order_handoff import supplier_order_handoff_schemas
from integration.supplier_planning_actions import PreparedSupplierPlanning
from integration.supplier_quote_results import SavedSupplierQuote, SupplierQuoteResultWorker
from src.actions.contracts.common import ActionContext, Reference, ScopeRef
from src.actions.contracts.supplier_planning_objects import (
    QuoteCapacityView, QuoteInventoryView, SupplierPlanningProfileView,
    SupplierWorkAuthorityView, supplier_planning_schemas,
)
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class SavedSupplierPlanning(SavedSupplierQuote):
    """Historical A05 evidence; completed plans/requests are not SupplyTasks or stock."""


class SupplierPlanningResultWorker(SupplierQuoteResultWorker):
    """Keep original claim, audit, pending and recovery rules in a distinct A05 table."""
    SCHEMA = 'supplier-planning-result.v1'
    ACTION_ID = 'SUPPLIER-A05'
    PREPARED_TYPE = PreparedSupplierPlanning
    RESULT_TABLE = 'supplier_planning_results'
    WAIT_KIND = 'manual_supplier_planning_result_review'
    EXECUTION_ERROR_CODE = 'supplier_planning_execution_exception'
    SOURCE_SCHEMAS = staticmethod(supplier_order_handoff_schemas)
    READ_ACTION_IDS = frozenset({'SUPPLIER-A05', 'SUPPLIER-A06', 'SUPPLIER-A12'})
    SAVED_TYPE = SavedSupplierPlanning

    @staticmethod
    def _original(sources, ref, schema):
        originals = [row for row in sources if Reference.model_validate(row['ref']).key() == ref.key()]
        if len(originals) != 1:
            raise TaskConflict('Saved planning lacks its exact original work or private source')
        row = schema.model_validate(originals[0]['projection'])
        if row.ref.key() != ref.key():
            raise TaskConflict('Saved planning projection changes its original reference')
        return row

    def _validate_primary_sources(self, snapshot, identity, sources):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = snapshot['action_input']
        mandate = self._original(sources, Reference.model_validate(action_input['work_authority_ref']),
            SupplierWorkAuthorityView)
        profile = self._original(sources, mandate.profile_ref, SupplierPlanningProfileView)
        inventory = self._original(sources, Reference.model_validate(action_input['inventory_ref']), QuoteInventoryView)
        capacity = self._original(sources, Reference.model_validate(action_input['capacity_ref']), QuoteCapacityView)
        if (TypeAdapter(ScopeRef).validate_python(action_input['scope_ref']) != context.scope
                or any(row.organization_id != identity.organization_id for row in (mandate, profile, inventory, capacity))
                or not scope_covers(context.scope, mandate.scope)
                or profile.work_authority_ref != mandate.ref or profile.scope != context.scope
                or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
                or profile.authority_ref not in context.authorization_refs):
            raise TaskConflict('Saved planning changes original Supplier, scope, work mandate or profile authority')

    def prepare_order_handoff(self, *args, **kwargs):
        raise ValueError('A05 saved planning is not an A03 quote; actual task/upstream order authorization remains separate')

    def prepare_execution_handoff(self, identity, *, current_context, reading, execution_versions,
            basis_ref, task_ref, release_ref, validate_history, validate_current):
        from integration.supplier_planning_handoff import prepare_supplier_planning_handoff

        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        saved = self.read_completed(identity, current_context=current, reading=reading,
            execution_versions=execution_versions, validate_current=validate_history)
        return prepare_supplier_planning_handoff(saved, context=current, reading=reading,
            basis_ref=basis_ref, task_ref=task_ref, release_ref=release_ref, validate_current=validate_current)
