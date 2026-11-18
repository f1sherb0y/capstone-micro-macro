"""Connect Supplier A09 to actual arrival, receipt and independent inspection sources."""
from dataclasses import dataclass, replace

from integration.supplier_logistics_handoff import supplier_logistics_handoff_schemas
from integration.supplier_quote_actions import PreparedSupplierQuote, SupplierQuoteActionAssembler
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_receiving_objects import (
    SupplierArrivalEvidenceView, SupplierCustomerReceiptView, SupplierDeliveryDiscrepancyView,
    SupplierDeliveryResponseProfileView, SupplierLogisticsOrderView, SupplierReceiptInspectionView,
    SupplierReceivingPartyView, SupplierReceivingShipmentView, supplier_receiving_schemas,
)
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedSupplierReceiving(PreparedSupplierQuote):
    """Original Supplier response; no independent receiver approval is generated."""


class SupplierReceivingActionAssembler(SupplierQuoteActionAssembler):
    """Reuse host configuration with A09's original receiving projections.

    Arrival, customer receipt, inspection and usable quantities remain distinct
    original facts. The processor checks original shipment commands, complete
    receiving history, independent party mandates and inspection/use rights,
    discrepancies and replacement quantities. A08 local requests are never
    treated as arrival evidence; Supplier responses do not grant acceptance,
    usable inventory, responsibility allocation or payment entitlement.
    """
    ACTION_ID = 'SUPPLIER-A09'
    SOURCE_SCHEMAS = staticmethod(supplier_logistics_handoff_schemas)

    def build(self, context, *, shipment_ref, arrival_refs, receipt_refs,
            inspection_refs, discrepancy_refs, receiving_party_refs):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A09':
            raise ValueError('Receiving response assembly requires its original A09 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture receiving sources require explicit offline_fixture execution')
        registration = self.registry.get('SUPPLIER-A09')
        if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
            raise ValueError('Receiving response assembly requires its original Supplier Skill and processor')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id, registration.role,
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in (
            ('arrival_refs', arrival_refs), ('receipt_refs', receipt_refs), ('inspection_refs', inspection_refs),
            ('discrepancy_refs', discrepancy_refs), ('receiving_party_refs', receiving_party_refs))}
        for refs in selected.values():
            unique_refs(refs)
        action_input = registration.contract.validate_input({**selected,
            'shipment_ref': Reference.model_validate(shipment_ref)})

        def read(ref, schema):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref != ref:
                raise ValueError('Receiving response requires its exact original concrete source version')
            return row

        try:
            shipment = read(action_input.shipment_ref, SupplierReceivingShipmentView)
            profile = read(shipment.response_profile_ref, SupplierDeliveryResponseProfileView)
            order = read(shipment.order_ref, SupplierLogisticsOrderView)
            if (shipment.organization_id != reading.organization_id or shipment.run_id != context.run_id
                    or order.supplier_id != reading.organization_id or not scope_covers(order.scope, context.scope)
                    or profile.shipment_ref != shipment.ref or profile.organization_id != reading.organization_id
                    or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
                    or profile.scope != context.scope or profile.authority_ref not in context.authorization_refs):
                raise ValueError('Receiving response changes original Supplier, shipment, order or profile authority')
            for refs, schema in ((action_input.arrival_refs, SupplierArrivalEvidenceView),
                    (action_input.receipt_refs, SupplierCustomerReceiptView),
                    (action_input.inspection_refs, SupplierReceiptInspectionView),
                    (action_input.discrepancy_refs, SupplierDeliveryDiscrepancyView)):
                for ref in refs:
                    if read(ref, schema).shipment_ref != shipment.ref:
                        raise ValueError('Receiving evidence names another original shipment')
            for ref in action_input.receiving_party_refs:
                if read(ref, SupplierReceivingPartyView).order_ref != order.ref:
                    raise ValueError('Receiving party names another original order')
            for ref in walk_references(action_input):
                reading.resolve(ref)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Receiving response requires its actual current authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            reading.recheck()
            return PreparedSupplierReceiving(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_from_logistics(self, context, *, logistics_worker, logistics_identity,
            logistics_execution_versions, basis_ref, validate_history, validate_current, **receiving_refs):
        """Bind explicitly selected receiving source to saved A08 and actual native Shipment."""
        from integration.supplier_logistics_results import SupplierLogisticsResultWorker

        if (not isinstance(logistics_worker, SupplierLogisticsResultWorker) or logistics_worker.registry is not self.registry
                or logistics_worker.store.run_id != self.organizations.run_id
                or not callable(validate_history) or not callable(validate_current)):
            raise ValueError('Receiving logistics source requires original worker/registry and explicit host checks')
        invocation = self.build(context, **receiving_refs)
        handoff = logistics_worker.prepare_receiving_handoff(logistics_identity, current_context=invocation.context,
            reading=invocation.reading, execution_versions=logistics_execution_versions, basis_ref=basis_ref,
            shipment_ref=invocation.action_input.shipment_ref,
            validate_history=validate_history, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        invocation.reading.recheck()
        return {**handoff, 'invocation': replace(invocation,
            reading_sha256=task_digest(invocation.reading.evidence()))}
