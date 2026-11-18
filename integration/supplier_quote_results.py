"""Persist original Supplier A03 quote/decline outcomes without forming a native offer."""
from copy import deepcopy
from dataclasses import dataclass

from integration.contractor_bid_results import ContractorBidResultWorker
from integration.supplier_quote_actions import PreparedSupplierQuote, supplier_quote_source_schemas
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_quote_objects import QuoteInquiryView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class SavedSupplierQuote:
    """Historical evidence only; an A03 draft has no formal SupplyOffer reference."""
    identity: TaskIdentity
    context: ActionContext
    current_context: ActionContext
    action_input: object
    result: object
    audit: dict
    source_reading: tuple[dict, ...]
    source_reading_sha256: str
    record_sha256: str


class SupplierQuoteResultWorker(ContractorBidResultWorker):
    """Share original claim-once/pending/recovery logic with a distinct role/schema/table."""
    SCHEMA = 'supplier-quote-result.v1'
    ACTION_ID = 'SUPPLIER-A03'
    ROLE = 'Supplier'
    PREPARED_TYPE = PreparedSupplierQuote
    RESULT_TABLE = 'supplier_quote_results'
    WAIT_KIND = 'manual_supplier_quote_result_review'
    EXECUTION_ERROR_CODE = 'supplier_quote_execution_exception'
    EXTRA_FIELDS = frozenset({'source_reading', 'source_reading_sha256'})
    SOURCE_SCHEMAS = staticmethod(supplier_quote_source_schemas)
    READ_ACTION_IDS = frozenset({'SUPPLIER-A03', 'SUPPLIER-A04'})
    SAVED_TYPE = SavedSupplierQuote

    def prepare_order_handoff(self, identity, *, current_context, reading, execution_versions,
            basis_ref, validate_history, validate_current):
        """Read actual persisted originals and check their relation to an existing native offer."""
        from integration.supplier_quote_handoff import prepare_supplier_quote_handoff

        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        saved = self.read_completed(identity, current_context=current, reading=reading,
            execution_versions=execution_versions, validate_current=validate_history)
        return prepare_supplier_quote_handoff(saved, context=current, reading=reading,
            basis_ref=basis_ref, validate_current=validate_current)

    def _result_extras(self, prepared):
        prepared.reading.recheck()
        sources = prepared.reading.evidence()
        if task_digest(sources) != prepared.reading_sha256:
            raise TaskConflict('Original quote assembly snapshot changed; no historical source substitution')
        return {'source_reading': sources, 'source_reading_sha256': prepared.reading_sha256}

    def _validate_record(self, identity, record):
        snapshot = super()._validate_record(identity, record)
        sources = record['source_reading']
        if not isinstance(sources, list) or task_digest(sources) != record['source_reading_sha256']:
            raise TaskConflict('Original quote assembly evidence changed')
        schemas, seen = self.SOURCE_SCHEMAS(), set()
        for item in sources:
            if not isinstance(item, dict) or set(item) != {'ref', 'projection'}:
                raise TaskConflict('Original quote source reading has missing or extra fields')
            ref = Reference.model_validate(item['ref'])
            if ref.key() in seen:
                raise TaskConflict('Original quote source reading repeats an object version')
            seen.add(ref.key())
            schemas.validate_projection(ref, item['projection'])
        self._validate_primary_sources(snapshot, identity, sources)
        return snapshot

    def _validate_primary_sources(self, snapshot, identity, sources):
        inquiry_ref = Reference.model_validate(snapshot['action_input']['inquiry_ref'])
        inquiries = [item for item in sources if Reference.model_validate(item['ref']) == inquiry_ref]
        if len(inquiries) != 1:
            raise TaskConflict('Original quote assembly snapshot lacks its exact inquiry')
        inquiry = QuoteInquiryView.model_validate(inquiries[0]['projection'])
        context = ActionContext.model_validate(snapshot['context'])
        if inquiry.recipient_organization_id != identity.organization_id or inquiry.recipient_id != context.actor_id:
            raise TaskConflict('Saved quote changes its original private inquiry recipient')

    def _saved_extras(self, record):
        return {}

    def read_completed(self, identity, *, current_context, reading, execution_versions, validate_current):
        """Read finalized original quote/decline evidence for an explicit current Supplier action."""
        identity = TaskIdentity(**identity.as_dict())
        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        if (not isinstance(reading, ActionReadView) or not callable(validate_current)
                or current.run_id != identity.run_id or current.contract_ref.kind != 'ActionContract'
                or current.contract_ref.id not in self.READ_ACTION_IDS
                or reading.organization_id != identity.organization_id or execution_versions != identity.versions):
            raise TaskConflict('Saved quote requires current own Supplier authority and all original execution versions')
        reading.check_method_context(current, current.contract_ref.id)
        record = self.get_record(identity)
        task = self.store.get(identity)
        if (record is None or record['result']['kind'] != 'completed'
                or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                or task['output'] != record['result'] or task['output_sha256'] != record['result_sha256']
                or task['revision'] < record['attempt_revision']):
            raise TaskConflict('Quote evidence requires its exact finalized completed original result')
        snapshot = self.snapshots.get(identity)
        context = ActionContext.model_validate(snapshot['context'])
        if (context.scope != current.scope or context.business_time.clock_ref != current.business_time.clock_ref
                or context.business_time.offset > current.business_time.offset
                or (context.execution_mode == 'offline_fixture') != (current.execution_mode == 'offline_fixture')):
            raise TaskConflict('Quote recovery changes original scope, clock, order or source mode')
        contract = self.registry.get(self.ACTION_ID).contract
        saved = self.SAVED_TYPE(identity=identity, context=context, current_context=current,
            action_input=contract.validate_input(snapshot['action_input']),
            result=contract.result_adapter.validate_python(record['result']), audit=deepcopy(record['audit']),
            source_reading=tuple(deepcopy(record['source_reading'])),
            source_reading_sha256=record['source_reading_sha256'], record_sha256=record['record_sha256'],
            **self._saved_extras(record))
        if validate_current(deepcopy(saved)) is not True:
            raise TaskConflict('Historical quote and current own source relation require explicit host validation')
        reading.recheck()
        return saved
