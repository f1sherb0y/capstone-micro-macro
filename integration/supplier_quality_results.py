"""Persist original Supplier A07 decisions without creating inspection or stock effects."""
from dataclasses import dataclass
from pydantic import TypeAdapter

from integration.supplier_execution_handoff import supplier_execution_handoff_schemas
from integration.supplier_quality_actions import PreparedSupplierQuality
from integration.supplier_quote_results import SavedSupplierQuote, SupplierQuoteResultWorker
from src.actions.contracts.common import ActionContext, Reference, ScopeRef
from src.actions.contracts.supplier_quality_objects import (
    SupplierQualityBatchView, SupplierQualityEvidenceView, SupplierQualityProfileView,
    SupplierQualityRequirementView, SupplierVisibleDefectView, supplier_quality_schemas,
)
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class SavedSupplierQuality(SavedSupplierQuote):
    """Historical quality request evidence; no passed inspection or disposition receipt."""


class SupplierQualityResultWorker(SupplierQuoteResultWorker):
    """Reuse original result-first, pending and interrupted-recovery rules for A07."""
    SCHEMA = 'supplier-quality-result.v1'
    ACTION_ID = 'SUPPLIER-A07'
    PREPARED_TYPE = PreparedSupplierQuality
    RESULT_TABLE = 'supplier_quality_results'
    WAIT_KIND = 'manual_supplier_quality_result_review'
    EXECUTION_ERROR_CODE = 'supplier_quality_execution_exception'
    SOURCE_SCHEMAS = staticmethod(supplier_execution_handoff_schemas)
    READ_ACTION_IDS = frozenset({'SUPPLIER-A07', 'SUPPLIER-A08', 'SUPPLIER-A12'})
    SAVED_TYPE = SavedSupplierQuality

    @staticmethod
    def _original(sources, ref, schema):
        originals = [row for row in sources if Reference.model_validate(row['ref']) == ref]
        if len(originals) != 1:
            raise TaskConflict('Saved quality lacks its exact original batch or source version')
        row = schema.model_validate(originals[0]['projection'])
        if row.ref != ref:
            raise TaskConflict('Saved quality projection changes its original reference')
        return row

    def _validate_primary_sources(self, snapshot, identity, sources):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = snapshot['action_input']
        batch = self._original(sources, Reference.model_validate(action_input['batch_ref']), SupplierQualityBatchView)
        profile = self._original(sources, Reference.model_validate(action_input['inspection_profile_ref']), SupplierQualityProfileView)
        if (TypeAdapter(ScopeRef).validate_python(action_input['scope_ref']) != context.scope
                or batch.organization_id != identity.organization_id or profile.organization_id != identity.organization_id
                or not scope_covers(context.scope, batch.scope) or profile.scope != context.scope
                or profile.batch_ref != batch.ref or profile.actor_id != context.actor_id
                or profile.function_ref != context.function_ref
                or profile.authority_ref not in context.authorization_refs):
            raise TaskConflict('Saved quality changes original Supplier, batch, scope or profile authority')
        for raw_ref in action_input['requirement_refs']:
            row = self._original(sources, Reference.model_validate(raw_ref), SupplierQualityRequirementView)
            if row.batch_ref != batch.ref or row.product_ref != batch.product_ref:
                raise TaskConflict('Saved quality requirement changes original batch or product')
        for field, schema in (('evidence_refs', SupplierQualityEvidenceView), ('known_defect_refs', SupplierVisibleDefectView)):
            for raw_ref in action_input[field]:
                row = self._original(sources, Reference.model_validate(raw_ref), schema)
                if row.batch_ref != batch.ref or row.physical_batch_key != batch.physical_batch_key:
                    raise TaskConflict('Saved quality observation or defect changes original physical batch lineage')

    def prepare_order_handoff(self, *args, **kwargs):
        raise ValueError('A07 saved decision is not an A03 quote, quality certificate or native disposition receipt')

    def prepare_logistics_handoff(self, identity, *, current_context, reading, execution_versions,
            basis_ref, dispatchable_refs, validate_history, validate_current):
        from integration.supplier_quality_handoff import prepare_supplier_quality_handoff

        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        saved = self.read_completed(identity, current_context=current, reading=reading,
            execution_versions=execution_versions, validate_current=validate_history)
        return prepare_supplier_quality_handoff(saved, context=current, reading=reading,
            basis_ref=basis_ref, dispatchable_refs=dispatchable_refs, validate_current=validate_current)
