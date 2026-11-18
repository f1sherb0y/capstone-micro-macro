"""Persist original Supplier A04 local decisions; native order formation remains separate."""
from dataclasses import dataclass

from integration.supplier_order_actions import PreparedSupplierOrder, validate_supplier_order_sources
from integration.supplier_quote_handoff import supplier_quote_handoff_schemas
from integration.supplier_quote_results import SavedSupplierQuote, SupplierQuoteResultWorker
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.supplier_order_objects import OrderProposalView, order_agreement_digest
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedSupplierOrder(SavedSupplierQuote):
    """Historical A04 acceptance/partial/revision/rejection; no native SupplyOrder is implied."""
    proposal_agreement_sha256: str


class SupplierOrderResultWorker(SupplierQuoteResultWorker):
    """Reuse original task/source persistence with a distinct A04 schema and table."""
    SCHEMA = 'supplier-order-result.v1'
    ACTION_ID = 'SUPPLIER-A04'
    PREPARED_TYPE = PreparedSupplierOrder
    RESULT_TABLE = 'supplier_order_results'
    WAIT_KIND = 'manual_supplier_order_result_review'
    EXECUTION_ERROR_CODE = 'supplier_order_execution_exception'
    EXTRA_FIELDS = SupplierQuoteResultWorker.EXTRA_FIELDS | {'proposal_agreement_sha256'}
    SOURCE_SCHEMAS = staticmethod(supplier_quote_handoff_schemas)
    READ_ACTION_IDS = frozenset({'SUPPLIER-A04', 'SUPPLIER-A05', 'SUPPLIER-A12'})
    SAVED_TYPE = SavedSupplierOrder

    @staticmethod
    def _original(sources, ref, schema):
        matches = [row for row in sources if Reference.model_validate(row['ref']).key() == ref.key()]
        if len(matches) != 1:
            raise TaskConflict('Saved order assembly lacks its exact original proposal or offer')
        row = schema.model_validate(matches[0]['projection'])
        if row.ref.key() != ref.key():
            raise TaskConflict('Saved order projection changes its original reference')
        return row

    def _result_extras(self, prepared):
        extras = super()._result_extras(prepared)
        proposal = self._original(extras['source_reading'], prepared.action_input.order_proposal_ref, OrderProposalView)
        return {**extras, 'proposal_agreement_sha256': order_agreement_digest(proposal)}

    def _validate_primary_sources(self, snapshot, identity, sources):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        schemas = self.SOURCE_SCHEMAS()
        originals = {}
        # The parent checks source shape, exact refs, schemas and duplicate rows first.
        for row in sources:
            ref = Reference.model_validate(row['ref'])
            originals[ref.key()] = schemas.validate_projection(ref, row['projection'])
        validate_supplier_order_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)

    def _validate_record(self, identity, record):
        snapshot = super()._validate_record(identity, record)
        proposal = self._original(record['source_reading'],
            Reference.model_validate(snapshot['action_input']['order_proposal_ref']), OrderProposalView)
        if order_agreement_digest(proposal) != record['proposal_agreement_sha256']:
            raise TaskConflict('Saved order changes its exact original proposed agreement')
        return snapshot

    def _saved_extras(self, record):
        return {'proposal_agreement_sha256': record['proposal_agreement_sha256']}

    def prepare_order_handoff(self, *args, **kwargs):
        raise ValueError('A04 saved decision is not an A03 quote; use an explicit actual order/source relation')

    def prepare_planning_handoff(self, identity, *, current_context, reading, execution_versions,
            basis_ref, work_authority_ref, validate_history, validate_current):
        """Read the stored A04 original before checking an existing native order for A05."""
        from integration.supplier_order_handoff import prepare_supplier_order_handoff

        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        saved = self.read_completed(identity, current_context=current, reading=reading,
            execution_versions=execution_versions, validate_current=validate_history)
        return prepare_supplier_order_handoff(saved, context=current, reading=reading,
            basis_ref=basis_ref, work_authority_ref=work_authority_ref, validate_current=validate_current)
