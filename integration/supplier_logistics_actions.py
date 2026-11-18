"""Assemble Supplier A08 using actual dispatch, route and shipment projections."""
from dataclasses import dataclass, replace

from integration.supplier_quality_handoff import supplier_quality_handoff_schemas
from integration.supplier_quote_actions import PreparedSupplierQuote, SupplierQuoteActionAssembler
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_logistics_objects import (
    SupplierDispatchableView, SupplierLogisticsOrderView, SupplierLogisticsProfileView,
    SupplierReceivingWindowView, SupplierShipmentView, SupplierTransportCapacityView,
    SupplierTransportPositionView, SupplierTransportRequirementView,
    SupplierTransportRouteView, SupplierTransportTermsView, supplier_logistics_schemas,
)
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedSupplierLogistics(PreparedSupplierQuote):
    """Original logistics request/query; no dispatch, receipt or stock effect is implied."""


class SupplierLogisticsActionAssembler(SupplierQuoteActionAssembler):
    """Reuse explicit host setup with A08's distinct original source schemas.

    Host refs retain physical dispatch slices, independent receiving windows,
    actual shared transport capacity and original shipment positions. The
    processor checks release/ledger quantities, reservations, elapsed travel,
    routing from actual positions and risk/title terms. Dispatch, split,
    reroute, reschedule and reconciliation keep their original branches; no
    local quality decision is converted into dispatch release or destination
    stock, and unknown shipment receipts do not cause automatic retries.
    """
    SOURCE_SCHEMAS = staticmethod(supplier_quality_handoff_schemas)

    def build(self, context, *, order_ref, dispatchable_refs, receiving_window_refs,
            route_candidates, capacity_refs, requirement_refs, shipment_refs,
            position_refs, logistics_profile_ref):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A08':
            raise ValueError('Logistics assembly requires its original A08 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture logistics sources require explicit offline_fixture execution')
        registration = self.registry.get('SUPPLIER-A08')
        if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
            raise ValueError('Logistics assembly requires its original Supplier Skill and processor')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id, registration.role,
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in (
            ('dispatchable_refs', dispatchable_refs), ('receiving_window_refs', receiving_window_refs),
            ('route_candidates', route_candidates), ('capacity_refs', capacity_refs),
            ('requirement_refs', requirement_refs), ('shipment_refs', shipment_refs), ('position_refs', position_refs))}
        for refs in selected.values():
            unique_refs(refs)
        action_input = registration.contract.validate_input({**selected,
            'order_ref': Reference.model_validate(order_ref),
            'logistics_profile_ref': Reference.model_validate(logistics_profile_ref)})

        def read(ref, schema):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref != ref:
                raise ValueError('Logistics requires its exact original concrete source version')
            return row

        try:
            order = read(action_input.order_ref, SupplierLogisticsOrderView)
            profile = read(action_input.logistics_profile_ref, SupplierLogisticsProfileView)
            terms = read(order.terms_ref, SupplierTransportTermsView)
            if (order.supplier_id != reading.organization_id or not scope_covers(order.scope, context.scope)
                    or profile.order_ref != order.ref or profile.organization_id != reading.organization_id
                    or profile.scope != context.scope or profile.actor_id != context.actor_id
                    or profile.function_ref != context.function_ref or profile.authority_ref not in context.authorization_refs
                    or terms.order_ref != order.ref or terms.supplier_id != reading.organization_id
                    or terms.buyer_id != order.buyer_id):
                raise ValueError('Logistics changes original order, Supplier, parties, scope or profile authority')
            for refs, schema in ((action_input.dispatchable_refs, SupplierDispatchableView),
                    (action_input.receiving_window_refs, SupplierReceivingWindowView),
                    (action_input.requirement_refs, SupplierTransportRequirementView),
                    (action_input.shipment_refs, SupplierShipmentView)):
                for ref in refs:
                    if read(ref, schema).order_ref != order.ref:
                        raise ValueError('Logistics source names another original order')
            for refs, schema in ((action_input.route_candidates, SupplierTransportRouteView),
                    (action_input.capacity_refs, SupplierTransportCapacityView),
                    (action_input.position_refs, SupplierTransportPositionView)):
                for ref in refs:
                    read(ref, schema)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Logistics requires its actual current authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            reading.recheck()
            return PreparedSupplierLogistics(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_from_quality(self, context, *, quality_worker, quality_identity,
            quality_execution_versions, basis_ref, validate_history, validate_current, **logistics_refs):
        """Bind explicit current dispatchables to saved A07 and actual independent release."""
        from integration.supplier_quality_results import SupplierQualityResultWorker

        if (not isinstance(quality_worker, SupplierQualityResultWorker) or quality_worker.registry is not self.registry
                or quality_worker.store.run_id != self.organizations.run_id
                or not callable(validate_history) or not callable(validate_current)):
            raise ValueError('Logistics quality source requires original worker/registry and explicit host checks')
        invocation = self.build(context, **logistics_refs)
        handoff = quality_worker.prepare_logistics_handoff(quality_identity, current_context=invocation.context,
            reading=invocation.reading, execution_versions=quality_execution_versions, basis_ref=basis_ref,
            dispatchable_refs=invocation.action_input.dispatchable_refs,
            validate_history=validate_history, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        invocation.reading.recheck()
        return {**handoff, 'invocation': replace(invocation,
            reading_sha256=task_digest(invocation.reading.evidence()))}
