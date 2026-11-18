"""Explicit host entry points for A03 drafts and A04 decisions on actual offers."""
from dataclasses import dataclass

from integration.supplier_order_actions import PreparedSupplierOrder, SupplierOrderActionAssembler
from integration.supplier_order_results import SupplierOrderResultWorker
from integration.supplier_quote_actions import PreparedSupplierQuote, SupplierQuoteActionAssembler
from integration.supplier_quote_results import SupplierQuoteResultWorker
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest


@dataclass(frozen=True)
class PreparedSupplierQuotePipeline:
    invocation: PreparedSupplierQuote
    provenance_json: str
    provenance_sha256: str

    def provenance(self):
        import json

        evidence = json.loads(self.provenance_json)
        if not isinstance(evidence, dict) or task_digest(evidence) != self.provenance_sha256:
            raise TaskConflict('Prepared Supplier product source relation changed')
        return evidence


@dataclass(frozen=True)
class PreparedSupplierOrderPipeline:
    invocation: PreparedSupplierOrder
    # Immutable JSON evidence; the original relation projections are retained
    # separately in the A04 worker's source cache, not in a new business ledger.
    provenance_json: str
    provenance_sha256: str

    def provenance(self):
        import json

        evidence = json.loads(self.provenance_json)
        if not isinstance(evidence, dict) or task_digest(evidence) != self.provenance_sha256:
            raise TaskConflict('Prepared Supplier source relation changed')
        return evidence


class SupplierProcurementPipeline:
    """Share original stores and host guards without manufacturing native effects.

    Quote execution and order preparation are separate explicit operations: an
    A03 quote does not register an offer. A04 may use an actual offer with an
    explicitly selected saved quote relation or another authorized formal
    source. No polling, automatic retries, model creation or silent rule path
    is added. Original processors and workers retain all result branches.
    """
    VERSION = 'supplier-procurement-pipeline.v6'

    def __init__(self, *, quote_assembler, quote_worker, order_assembler,
            order_worker, read_guard, validate_history, validate_offer):
        if (not isinstance(quote_assembler, SupplierQuoteActionAssembler)
                or isinstance(quote_assembler, SupplierOrderActionAssembler)
                or not isinstance(order_assembler, SupplierOrderActionAssembler)
                or not isinstance(quote_worker, SupplierQuoteResultWorker)
                or quote_worker.ACTION_ID != 'SUPPLIER-A03'
                or not isinstance(order_worker, SupplierOrderResultWorker)
                or quote_worker.store is not order_worker.store
                or quote_worker.snapshots is not order_worker.snapshots
                or quote_worker.registry is not quote_assembler.registry
                or order_worker.registry is not order_assembler.registry
                or quote_worker.registry is not order_worker.registry
                or quote_assembler.organizations is not order_assembler.organizations
                or quote_worker.store.run_id != quote_assembler.organizations.run_id
                or quote_assembler.source_mode != order_assembler.source_mode
                or quote_worker.client_version != order_worker.client_version
                or quote_worker.model_version != order_worker.model_version
                or not all(callable(callback) for callback in
                    (read_guard, validate_history, validate_offer))):
            raise ValueError('Supplier pipeline requires original same-run stores, registry and explicit host guards')
        self.quote_assembler, self.quote_worker = quote_assembler, quote_worker
        self.order_assembler, self.order_worker = order_assembler, order_worker
        self.read_guard = read_guard
        self.validate_history, self.validate_offer = validate_history, validate_offer

    def publish_quote_cost(self, source_context, *, next_context, adoption_ref,
            publications, validate_current):
        """Produce and publish an explicitly adopted original rate under the host guard."""
        return self._publish_quote_source(source_context, next_context=next_context,
            adoption_ref=adoption_ref, publications=publications,
            validate_current=validate_current, source_kind='cost')

    def publish_quote_logistics(self, source_context, *, next_context, adoption_ref,
            publications, validate_current):
        """Publish an adopted original logistics plan, retaining original cost sources."""
        return self._publish_quote_source(source_context, next_context=next_context,
            adoption_ref=adoption_ref, publications=publications,
            validate_current=validate_current, source_kind='logistics')

    def publish_quote_inventory(self, source_context, *, next_context, adoption_ref,
            publications, validate_current):
        """Publish the actual adopted finished-stock snapshot under the original guard."""
        return self._publish_quote_source(source_context, next_context=next_context,
            adoption_ref=adoption_ref, publications=publications,
            validate_current=validate_current, source_kind='inventory')

    def publish_quote_capacity(self, source_context, *, next_context, adoption_ref,
            publications, validate_current, assembly):
        """Read actual macro resources and publish adopted capacity/pools under one host guard."""
        return self._publish_quote_source(source_context, next_context=next_context,
            adoption_ref=adoption_ref, publications=publications, validate_current=validate_current,
            source_kind='capacity', assembly=assembly)

    def _publish_quote_source(self, source_context, *, next_context, adoption_ref,
            publications, validate_current, source_kind, assembly=None):
        """Share original host bindings and guard across explicit source publication.

        Host supplies the next context/token. Quote preparation and execution
        remain separate explicit operations; no model, native writes or retries.
        """
        from integration.supplier_quote_cost_publication import (
            SupplierQuoteCostPublicationStore, SupplierQuoteCostPublishedViewProvider,
        )
        from integration.supplier_quote_costs import prepare_supplier_quote_cost
        from integration.supplier_quote_logistics_source import prepare_supplier_quote_logistics
        from integration.supplier_quote_inventory_source import prepare_supplier_quote_inventory
        from src.actions.contracts.common import ActionContext, Reference

        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        target = ActionContext.model_validate(next_context).model_copy(deep=True)
        adoption = Reference.model_validate(adoption_ref).model_copy(deep=True)
        provider = self.quote_assembler.view_provider
        if (not isinstance(publications, SupplierQuoteCostPublicationStore)
                or publications.store is not self.quote_worker.store
                or publications.organizations is not self.quote_assembler.organizations
                or not isinstance(provider, SupplierQuoteCostPublishedViewProvider)
                or provider.publications is not publications
                or not callable(validate_current)):
            raise TaskConflict('Quote source publication requires original store, registry, configured provider and host validator')
        if (source.contract_ref.kind != 'ActionContract' or source.contract_ref.id != 'SUPPLIER-A03'
                or source.read_token == target.read_token
                or any(getattr(source, name) != getattr(target, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('Quote source publication requires original same-time A03 and a fresh token')
        if source_kind == 'cost':
            producer, publish = prepare_supplier_quote_cost, publications.publish
        elif source_kind == 'logistics':
            producer, publish = prepare_supplier_quote_logistics, publications.publish_logistics
        elif source_kind == 'inventory':
            producer, publish = prepare_supplier_quote_inventory, publications.publish_inventory
        elif source_kind == 'capacity':
            from integration.bindings.gba_v1 import GbaV1Assembly

            if (not isinstance(assembly, GbaV1Assembly) or assembly.client.tasks is not self.quote_worker.store
                    or assembly.client.run_id != source.run_id):
                raise TaskConflict('Quote capacity requires the original same-run macro assembly and TaskStore')
        else:
            raise ValueError('Only explicitly supported quote sources can be published')
        with self.read_guard():
            reading = self.quote_assembler.build_source_reading(source)
            if source_kind == 'capacity':
                from contextlib import nullcontext
                from functools import partial

                prepared = assembly.prepare_supplier_quote_capacity(context=source, reading=reading,
                    read_guard=nullcontext, adoption_ref=adoption, validate_current=validate_current)
                if prepared['kind'] != 'prepared':
                    return prepared
                publish = partial(publications.publish_capacity, source=prepared['source_record'])
            else:
                prepared = producer(context=source, reading=reading,
                    adoption_ref=adoption, validate_current=validate_current)
            record = publish(prepared, source_context=source, reading=reading,
                next_context=target, adoption_ref=adoption, validate_current=validate_current)
            reading.recheck()
            return {'kind': 'published', 'publication': record,
                'publication_sha256': record['record_sha256'],
                'read_token': target.read_token,
                f'{source_kind}_ref': prepared[f'{source_kind}_projection'].ref.model_dump(mode='json'),
                f'{source_kind}_sha256': prepared[f'{source_kind}_sha256'], 'source_mode': prepared['source_mode']}

    def prepare_quote(self, context, **quote_refs):
        """Assemble only; actual product, cost and logistics refs remain explicit."""
        with self.read_guard():
            return self.quote_assembler.build(context, **quote_refs)

    def prepare_quote_from_products(self, context, *, product_worker, product_identity,
            product_execution_versions, basis_ref, validate_product_history,
            validate_product_source, **quote_refs):
        """Select original A02 provenance explicitly; never execute A02 or create a proposal."""
        from integration.supplier_product_results import SupplierProductResultWorker

        if (not isinstance(product_worker, SupplierProductResultWorker)
                or product_worker.store is not self.quote_worker.store
                or product_worker.snapshots is not self.quote_worker.snapshots
                or product_worker.registry is not self.quote_worker.registry
                or product_worker.client_version != self.quote_worker.client_version
                or product_worker.model_version != self.quote_worker.model_version
                or not isinstance(product_identity, TaskIdentity)
                or product_identity.run_id != self.quote_worker.store.run_id
                or product_identity.role != 'Supplier' or product_identity.action_id != 'SUPPLIER-A02'
                or not callable(validate_product_history) or not callable(validate_product_source)):
            raise TaskConflict('Quote product source requires original same-run A02 stores, versions and host validators')
        with self.read_guard():
            handoff = self.quote_assembler.build_from_products(context, product_worker=product_worker,
                product_identity=product_identity, product_execution_versions=product_execution_versions,
                basis_ref=basis_ref, validate_history=validate_product_history,
                validate_current=validate_product_source, **quote_refs)
            if handoff['kind'] != 'prepared':
                return handoff
            invocation = handoff['invocation']
            evidence = {'source': 'saved_product_actual_proposal', 'product_identity': product_identity.as_dict(),
                'product_proposal_refs': [ref.model_dump(mode='json') for ref in invocation.action_input.product_proposal_refs],
                **{key: handoff[key] for key in ('basis_sha256', 'product_record_sha256',
                    'product_result_sha256', 'unresolved_confirmation_count')},
                'input_sha256': invocation.input_sha256, 'context_sha256': invocation.context_sha256,
                'reading_sha256': invocation.reading_sha256}
            invocation.reading.recheck()
            return PreparedSupplierQuotePipeline(invocation, canonical(evidence), task_digest(evidence))

    def execute_quote(self, prepared, *, request_id, purpose='action'):
        """Persist the original A03 result; a declined quote remains a decline."""
        evidence = None
        if isinstance(prepared, PreparedSupplierQuotePipeline):
            evidence = prepared.provenance()
            invocation = prepared.invocation
            if (not isinstance(invocation, PreparedSupplierQuote)
                    or evidence.get('input_sha256') != invocation.input_sha256
                    or evidence.get('context_sha256') != invocation.context_sha256
                    or evidence.get('reading_sha256') != task_digest(invocation.reading.evidence())
                    or evidence.get('product_proposal_refs') != [ref.model_dump(mode='json')
                        for ref in invocation.action_input.product_proposal_refs]):
                raise TaskConflict('Prepared quote changed its original input, context, proposal set or source reading')
        else:
            invocation = prepared
        if (not isinstance(invocation, PreparedSupplierQuote)
                or invocation.context.contract_ref.id != 'SUPPLIER-A03'):
            raise TaskConflict('Quote execution requires its original A03 invocation')
        with self.read_guard():
            identity = self.quote_worker.register(invocation, request_id=request_id, purpose=purpose)
            outcome = self.quote_worker.execute(identity, invocation)
            if evidence is None:
                return {**outcome, 'identity': identity}
            return {**outcome, 'identity': identity, 'source_relation': evidence,
                'source_relation_sha256': prepared.provenance_sha256}

    def prepare_order(self, context, *, quote_identity=None, quote_execution_versions=None,
            basis_ref=None, **order_refs):
        """Use an actual offer; saved quote provenance is an explicit complete selection."""
        selection = (quote_identity, quote_execution_versions, basis_ref)
        if any(item is not None for item in selection) and any(item is None for item in selection):
            raise ValueError('Saved quote source requires identity, all execution versions and relation basis')
        with self.read_guard():
            if quote_identity is None:
                invocation = self.order_assembler.build(context, **order_refs)
                evidence = {'source': 'authorized_formal_offer',
                    'offer_ref': invocation.action_input.offer_ref.model_dump(mode='json')}
            else:
                if (not isinstance(quote_identity, TaskIdentity)
                        or quote_identity.action_id != 'SUPPLIER-A03'
                        or quote_identity.role != 'Supplier'
                        or quote_identity.run_id != self.quote_worker.store.run_id):
                    raise TaskConflict('Order source requires its exact original same-run A03 task')
                handoff = self.order_assembler.build_from_quote(context,
                    quote_worker=self.quote_worker, quote_identity=quote_identity,
                    quote_execution_versions=quote_execution_versions, basis_ref=basis_ref,
                    validate_history=self.validate_history, validate_current=self.validate_offer,
                    **order_refs)
                if handoff['kind'] != 'prepared':
                    return handoff
                invocation = handoff['invocation']
                evidence = {'source': 'saved_quote_actual_offer',
                    'quote_identity': quote_identity.as_dict(),
                    'offer_ref': handoff['offer_ref'].model_dump(mode='json'),
                    **{key: handoff[key] for key in ('basis_sha256', 'quote_record_sha256',
                        'quote_result_sha256', 'offer_projection_sha256', 'native_offer_source_sha256')}}
            evidence.update(input_sha256=invocation.input_sha256,
                context_sha256=invocation.context_sha256, reading_sha256=task_digest(invocation.reading.evidence()))
            invocation.reading.recheck()
            return PreparedSupplierOrderPipeline(invocation, canonical(evidence), task_digest(evidence))

    def execute_order(self, prepared, *, request_id, purpose='action'):
        """Execute original A04 once; no order formation or downstream authorization."""
        if not isinstance(prepared, PreparedSupplierOrderPipeline):
            raise TaskConflict('Order execution requires its original prepared Supplier chain')
        evidence = prepared.provenance()
        invocation = prepared.invocation
        if (not isinstance(invocation, PreparedSupplierOrder)
                or evidence.get('input_sha256') != invocation.input_sha256
                or evidence.get('context_sha256') != invocation.context_sha256
                or evidence.get('reading_sha256') != task_digest(invocation.reading.evidence())
                or evidence.get('offer_ref') != invocation.action_input.offer_ref.model_dump(mode='json')):
            raise TaskConflict('Prepared order changed its original input, context, offer or relation reading')
        with self.read_guard():
            identity = self.order_worker.register(invocation, request_id=request_id, purpose=purpose)
            outcome = self.order_worker.execute(identity, invocation)
            return {**outcome, 'identity': identity, 'source_relation': evidence,
                'source_relation_sha256': prepared.provenance_sha256}
