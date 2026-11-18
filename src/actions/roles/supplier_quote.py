"""Sourced, complete A03 quotes; no order, reservation or ledger mutation."""
from decimal import Decimal
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, TimeWindow
from src.actions.contracts.supplier_quote_objects import (
    QuoteInquiryView, QuoteProposalView, QuoteCostView, QuoteInventoryView, QuoteCapacityView,
    QuoteLogisticsView, QuoteProfileView, QuoteTermsView, QuoteLocationView,
    QuoteServiceView, QuoteRequirementView, QuoteResourcePoolView,
)
from src.actions.contracts.supplier_product_objects import ProductSpecificationView, ProductDeviationView
from src.actions.roles.supplier import SupplyGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, CapacityResource, CapacityCommitment, CapacityDemand, ExactAmount
from src.methods.pricing import PRICING_METHOD, SupplyPriceInput, decimal_fraction, exact_decimal
from src.organization.registry import scope_covers


def form_quote(context, action_input, reading):
    now, organization = context.business_time, reading.organization_id

    def current(window, field):
        if window.start.clock_ref != now.clock_ref:
            _unsupported("supply-quote-clock")
        if not window.contains(now):
            _needs(field)

    def available(point, field):
        if point.clock_ref != now.clock_ref:
            _unsupported("supply-quote-clock")
        if point.offset > now.offset:
            _needs(field)

    def evidence(refs):
        for ref in refs:
            value = reading.resolve(ref)
            if not isinstance(value, EvidenceRecord):
                _unsupported("supply-quote-evidence-schema")
            if value.effective_window is not None:
                current(value.effective_window, "current_quote_evidence")

    def read(ref, schema):
        value = reading.resolve(ref)
        if not isinstance(value, schema):
            _unsupported(f"supply-quote-projection:{ref.kind}")
        if not isinstance(value, TimeWindow):
            evidence(value.evidence_refs)
        return value

    def unique(refs, field):
        keys = [(ref.kind, ref.id) for ref in refs]
        if len(set(keys)) != len(keys):
            raise ValueError(f"Repeated physical identity in {field}")

    def quantity(value, unit, *, positive=False):
        evidence([value.basis_ref])
        if value.unit != unit:
            _unsupported("supply-quote-quantity-unit")
        amount = decimal_fraction(value.value)
        if amount < 0 or positive and amount == 0:
            raise ValueError("Invalid quote quantity")
        return amount

    def scheduled(ref):
        value = read(ref, TimeWindow)
        if value.start.clock_ref != now.clock_ref or value.bounds != "closed_open":
            _unsupported("supply-quote-window-domain")
        if value.start.offset < now.offset or value.start.offset >= value.end.offset:
            _needs("current_nonempty_quote_schedule", [ref])
        return value

    def method(ref, data):
        result = reading.calculate(ref, data)
        if result.kind == "ok":
            return result.value
        raw = result.model_dump(mode="python")
        if result.kind == "invalid_input":
            raise ValueError("Quote method input does not satisfy its supported domain")
        if result.kind == "needs_information":
            raw["requested_refs"] = []
        raise SupplyGap(raw)

    def completed(choice, note, **fields):
        return {"kind": "completed", "payload": {"choice": choice, "note": note, **fields}}

    try:
        for field in ("product_proposal_refs", "cost_basis_refs", "logistics_refs"):
            unique(getattr(action_input, field), field)
        inquiry = read(action_input.inquiry_ref, QuoteInquiryView)
        if (inquiry.recipient_id != context.actor_id or inquiry.recipient_organization_id != organization
                or not scope_covers(context.scope, inquiry.scope)):
            raise ValueError("Quote inquiry recipient or scope mismatch")
        current(inquiry.response_window, "active_quote_response_window")
        available(inquiry.received_at, "received_quote_inquiry")
        if inquiry.status != "active":
            _needs("active_quote_inquiry", [inquiry.ref])
        if inquiry.clarification_requirement_refs:
            _needs("clarified_quote_requirements", inquiry.clarification_requirement_refs)
        payer, currency = _known(inquiry.payer_id, "quote_payer"), _known(inquiry.currency, "quote_currency")
        required_services = set(_known(inquiry.required_service_codes, "quote_delivery_responsibility"))
        if not required_services or "factory_supply" not in required_services:
            _needs("complete_quote_delivery_responsibility")
        profile = read(action_input.pricing_profile_ref, QuoteProfileView)
        if profile.organization_id != organization:
            raise ValueError("Pricing policy belongs to another supplier")
        current(profile.effective_window, "current_supply_pricing_policy")
        if profile.policy == "decline_new_quotes":
            return completed("decline_quote", "Current sourced policy declines new quotes; no invented price or order")
        if profile.algorithm_code != "declared_cost_markup_v1":
            _unsupported("supply-binding-price-method")
        if _known(profile.currency, "pricing_currency") != currency:
            _unsupported("supply-quote-currency-conversion")
        if set(_known(profile.required_service_codes, "pricing_delivery_responsibility")) != required_services:
            _needs("consistent_complete_delivery_responsibility")
        markup = _known(profile.markup_rate, "pricing_markup")
        if Decimal(markup) < 0:
            raise ValueError("Cost markup cannot be negative")
        validity = read(profile.validity_ref, TimeWindow)
        current(validity, "current_offer_validity")
        terms = read(profile.terms_ref, QuoteTermsView)
        if (terms.inquiry_ref != inquiry.ref or terms.supplier_organization_id != organization
                or terms.buyer_id != inquiry.buyer_id or terms.payer_id != payer or terms.currency != currency):
            raise ValueError("Quote payment terms do not match the exact inquiry and counterparties")
        current(terms.effective_window, "current_supply_terms")
        if (len({row.milestone_code for row in terms.payment_rules}) != len(terms.payment_rules)
                or any(decimal_fraction(row.fraction) <= 0 for row in terms.payment_rules)
                or sum((decimal_fraction(row.fraction) for row in terms.payment_rules), Fraction()) != 1):
            raise ValueError("Payment fractions must be positive, unique and sum exactly to one")

        if not action_input.product_proposal_refs:
            _needs("same_version_product_proposals")
        proposals = [read(ref, QuoteProposalView) for ref in action_input.product_proposal_refs]
        for proposal in proposals:
            if proposal.inquiry_ref != inquiry.ref or proposal.supplier_organization_id != organization:
                raise ValueError("Product proposal inquiry or supplier mismatch")
            current(proposal.effective_window, "current_product_proposal")
            available(proposal.available_at, "available_product_proposal")
        proposals = [p for p in proposals if p.status not in {"rejected", "withdrawn"}]
        if not proposals:
            return completed("decline_quote", "All supplied product alternatives are rejected or withdrawn")
        unique([row.proposal_ref for row in profile.proposal_priorities], "proposal_priorities")
        if len(proposals) > 1:
            priorities = {row.proposal_ref.key(): row.priority for row in profile.proposal_priorities}
            if any(p.ref.key() not in priorities for p in proposals):
                _needs("explicit_quote_product_priority")
            rank = min(priorities[p.ref.key()] for p in proposals)
            proposals = [p for p in proposals if priorities[p.ref.key()] == rank]
            if len(proposals) != 1:
                _needs("unique_quote_product_priority")
        proposal = proposals[0]
        lines = {row.local_key: row.product for row in proposal.lines}
        inquiry_lines = {row.requirement_ref.key(): row for row in inquiry.lines}
        requirements = []
        products = {}
        for line in lines.values():
            if len(line.requirement_refs) != 1 or line.requirement_refs[0].key() not in inquiry_lines:
                _needs("exact_inquiry_line_product_mapping")
            requirement = line.requirement_refs[0]
            source = inquiry_lines[requirement.key()]
            requested = _known(source.quantity, "quote_requested_quantity")
            if (line.destination_scope_ref != source.scope or line.quantity.unit != requested.unit
                    or decimal_fraction(line.quantity.value) != decimal_fraction(requested.value)):
                raise ValueError("Proposal changes inquiry scope, quantity or unit")
            requirements.append(requirement.key())
            product = read(line.product_ref, ProductSpecificationView)
            current(product.effective_window, "current_quote_product")
            if product.supplier_organization_id != organization:
                raise ValueError("Quoted product belongs to another supplier")
            if product.quantity_unit != line.quantity.unit:
                _unsupported("supply-quote-product-unit")
            products[line.product_ref.key()] = product
            requirement_view = read(requirement, QuoteRequirementView)
            if requirement_view.inquiry_ref != inquiry.ref or requirement_view.scope != source.scope:
                raise ValueError("Quoted requirement belongs to another inquiry scope")
            for ref in line.deviation_refs:
                deviation = read(ref, ProductDeviationView)
                if (deviation.product_ref != line.product_ref or deviation.inquiry_ref != inquiry.ref
                        or deviation.requirement_ref != requirement or deviation.scope != source.scope):
                    raise ValueError("Quoted deviation changes product, inquiry or scope")
                current(deviation.effective_window, "current_quote_deviation")
        if len(set(requirements)) != len(requirements) or set(requirements) != set(inquiry_lines):
            _needs("complete_product_proposal_scope")
        logistics = [read(ref, QuoteLogisticsView) for ref in action_input.logistics_refs]
        candidates = [row for row in logistics if row.product_proposal_ref == proposal.ref]
        if len(candidates) != 1:
            _needs("unique_complete_logistics_plan", [proposal.ref])
        logistics = candidates[0]
        if logistics.inquiry_ref != inquiry.ref or logistics.supplier_organization_id != organization:
            raise ValueError("Logistics plan inquiry or supplier mismatch")
        current(logistics.effective_window, "current_logistics_plan")
        available(logistics.available_at, "available_logistics_plan")
        if not _known(logistics.feasible, "verified_logistics_feasibility"):
            return completed("decline_quote", "The applicable logistics assessment rules out the stated complete delivery plan")
        inventory = read(action_input.inventory_ref, QuoteInventoryView)
        capacity = read(action_input.capacity_ref, QuoteCapacityView)
        if inventory.organization_id != organization or capacity.organization_id != organization:
            raise ValueError("Quote inventory or capacity belongs to another organization")
        if inventory.as_of != now or capacity.as_of != now:
            _needs("current_quote_inventory_and_capacity")
        if inventory.coverage != "complete" or capacity.resource_coverage != "complete" or capacity.commitment_coverage != "complete":
            _needs("complete_quote_resource_snapshot")
        resources = []
        pool_by_key = {row.resource_ref.key(): row for row in capacity.resources}
        for pool in capacity.resources:
            total = _known(pool.total, "known_quote_pool_capacity")
            quantity(total, total.unit)
            object_view = read(pool.resource_ref, QuoteResourcePoolView)
            if object_view.organization_id != organization or object_view.region_id != pool.region_id:
                raise ValueError("Capacity pool identity or region mismatch")
            resources.append(CapacityResource(resource_ref=pool.resource_ref, resource_kind=pool.resource_ref.id,
                region_id=pool.region_id, total=total, effective_window=pool.effective_window))
        commitments = []
        for row in capacity.commitments:
            pool = pool_by_key.get(row.resource_ref.key())
            if pool is None:
                raise ValueError("Commitment names an absent pool or old pool version")
            quantity(row.quantity, _known(pool.total, "pool_total").unit, positive=True)
            commitments.append(CapacityCommitment(**row.model_dump(mode="python")))
        stock = {}
        for lot in inventory.lots:
            evidence([lot.actual.basis_ref, lot.committed.basis_ref])
            if lot.status == "usable":
                key = (lot.product_ref.key(), lot.location_ref.key(), lot.actual.unit)
                stock[key] = stock.get(key, Fraction()) + decimal_fraction(lot.actual.value) - decimal_fraction(lot.committed.value)
        costs = {ref.key(): read(ref, QuoteCostView) for ref in action_input.cost_basis_refs}
        keys = [row.local_key for row in logistics.deliveries]
        if len(set(keys)) != len(keys):
            raise ValueError("Logistics batch identity repeated")
        delivered = {key: Fraction() for key in lines}
        demands, allocations, output_lines, used_costs = [], [], [], {}
        for batch in logistics.deliveries:
            line = lines.get(batch.proposal_line_key)
            if line is None:
                raise ValueError("Delivery batch names an absent product proposal line")
            amount = quantity(batch.quantity, line.quantity.unit, positive=True)
            from_stock = quantity(batch.inventory_quantity, line.quantity.unit)
            if from_stock > amount:
                raise ValueError("Delivery stock quantity exceeds batch quantity")
            delivered[batch.proposal_line_key] += amount
            stock_key = (line.product_ref.key(), batch.source_location_ref.key(), line.quantity.unit)
            if from_stock > stock.get(stock_key, Fraction()):
                return completed("decline_quote", "The complete plan uses more actual uncommitted stock than is available")
            stock[stock_key] = stock.get(stock_key, Fraction()) - from_stock
            manufacturing = amount - from_stock
            source_location = read(batch.source_location_ref, QuoteLocationView)
            destination = read(batch.destination_ref, QuoteLocationView)
            product = products[line.product_ref.key()]
            requirement = inquiry_lines[line.requirement_refs[0].key()]
            if destination.region_id != _known(requirement.delivery_region_id, "quote_destination_region"):
                raise ValueError("Quote destination differs from the inquiry delivery region")
            delivery_window = scheduled(batch.delivery_window_ref)
            requested_window = _known(requirement.work_window, "quote_required_delivery_window")
            if requested_window.start.clock_ref != now.clock_ref or requested_window.bounds != "closed_open":
                _unsupported("supply-quote-request-window")
            if delivery_window.start.offset < requested_window.start.offset or delivery_window.end.offset > requested_window.end.offset:
                return completed("decline_quote", "The delivery schedule exceeds the requested window")
            unique(batch.included_service_refs, "included_services")
            services = [read(ref, QuoteServiceView) for ref in batch.included_service_refs]
            service_codes = [row.service_code for row in services]
            if len(set(service_codes)) != len(service_codes) or set(service_codes) != required_services:
                _needs("complete_batch_delivery_responsibility")
            for service in services:
                current(service.effective_window, "current_included_delivery_services")
                if service.provider_organization_id != organization or service.destination_ref != batch.destination_ref:
                    raise ValueError("Included service provider or destination mismatch")
            unique(batch.cost_basis_refs, "batch_costs")
            selected_costs, unit_costs, fixed_costs = [], [], []
            for ref in batch.cost_basis_refs:
                cost = costs.get(ref.key())
                if cost is None:
                    _needs("supplied_batch_cost_basis", [ref])
                if (cost.supplier_organization_id != organization or cost.product_ref != line.product_ref
                        or cost.destination_scope_ref != line.destination_scope_ref):
                    raise ValueError("Cost basis changes supplier, product version or destination scope")
                if cost.quantity_unit != line.quantity.unit:
                    _unsupported("supply-quote-cost-unit")
                current(cost.effective_window, "current_quote_costs")
                available(cost.available_at, "available_quote_costs")
                if cost.purpose != "binding_quote":
                    _needs("revalidated_binding_quote_costs", [cost.ref])
                unit = _known(cost.unit_cost, "binding_unit_cost")
                fixed = _known(cost.per_batch_cost, "binding_batch_cost")
                evidence([unit.basis_ref, fixed.basis_ref])
                if unit.currency != currency or fixed.currency != currency:
                    _unsupported("supply-quote-cost-currency")
                selected_costs.append(cost)
                unit_costs.append(unit)
                fixed_costs.append(fixed)
                used_costs[ref.key()] = ref
            if len({row.service_code for row in selected_costs}) != len(selected_costs) or {row.service_code for row in selected_costs} != required_services:
                _needs("costs_for_every_included_service")
            manufacturing_uses = [use for use in batch.resource_uses if use.source == "manufacture"]
            if manufacturing:
                if ("manufacture" not in _known(requirement.allowed_fulfillment_modes, "quote_fulfillment_modes")
                        or source_location.factory_id != _known(product.factory_id, "quote_product_factory")
                        or source_location.region_id != _known(requirement.production_region_id, "quote_production_region")):
                    return completed("decline_quote", "Manufacturing location or mode does not satisfy the proposed product and inquiry")
                if not manufacturing_uses:
                    _needs("explicit_manufacturing_capacity_demands")
            elif manufacturing_uses:
                raise ValueError("Stock-only delivery carries phantom manufacturing demands")
            if "transport" in required_services and not any(use.source == "delivery" for use in batch.resource_uses):
                _needs("explicit_transport_capacity_demands")
            identities = [(use.resource_ref.key(), use.window_ref.key(), use.source) for use in batch.resource_uses]
            if len(set(identities)) != len(identities):
                raise ValueError("Batch repeats a physical resource demand")
            for use in batch.resource_uses:
                pool = pool_by_key.get(use.resource_ref.key())
                if pool is None:
                    _needs("current_resource_pool", [use.resource_ref])
                window = scheduled(use.window_ref)
                if use.source == "manufacture" and window.end.offset > delivery_window.start.offset:
                    return completed("decline_quote", "Manufacturing finishes after the batch must leave for delivery")
                if use.source == "delivery" and window != delivery_window:
                    _unsupported("supply-quote-transport-window-alignment")
                if pool.region_id != source_location.region_id:
                    _unsupported("supply-quote-moving-resource")
                rate = quantity(use.rate_per_product_unit, _known(pool.total, "pool_total").unit, positive=True)
                needed = rate * (manufacturing if use.source == "manufacture" else amount)
                demands.append(CapacityDemand(resource_kind=pool.resource_ref.id, region_id=pool.region_id,
                    unit=use.rate_per_product_unit.unit, amount=ExactAmount.from_fraction(needed), window=window,
                    basis_refs=[use.rate_per_product_unit.basis_ref]))
                allocations.append({"resource_ref": use.resource_ref, "scope_ref": line.destination_scope_ref,
                    "window_ref": use.window_ref, "quantity": {"value": exact_decimal(needed),
                        "unit": use.rate_per_product_unit.unit, "basis_ref": use.rate_per_product_unit.basis_ref}})
            price = method(PRICING_METHOD, SupplyPriceInput(quantity=batch.quantity, quantity_unit=line.quantity.unit,
                unit_costs=unit_costs, fixed_costs=fixed_costs, markup_rate=markup, currency=currency,
                minor_places=profile.minor_places, policy_basis_refs=profile.evidence_refs,
                source_refs=[profile.ref, logistics.ref, *batch.cost_basis_refs]))
            if Decimal(price.rounded_price) <= 0:
                _needs("positive_binding_price")
            output_product = line.model_dump(mode="python")
            output_product["quantity"] = batch.quantity
            output_lines.append({"product": output_product, "delivery_window_ref": batch.delivery_window_ref,
                "destination_ref": batch.destination_ref, "included_service_refs": batch.included_service_refs,
                "price": {"value": price.rounded_price, "currency": currency, "basis_ref": profile.evidence_refs[0]}})
        if any(delivered[key] != decimal_fraction(line.quantity.value) for key, line in lines.items()):
            _needs("complete_nonduplicated_delivery_quantities")
        if demands:
            report = method(CAPACITY_METHOD, CapacityInput(clock_ref=now.clock_ref, demands=demands,
                resources=resources, commitments=commitments, source_refs=[capacity.ref, inventory.ref, logistics.ref, proposal.ref]))
            if not report.feasible:
                return completed("decline_quote", "The exact shared pool schedule conflicts with current commitments; no price or reservation is submitted")
        conditions = [*proposal.prerequisite_refs, *logistics.prerequisite_refs, *terms.prerequisite_refs]
        if proposal.status == "pending_confirmation":
            conditions.append(proposal.confirmation_requirement_ref)
        by_key = {ref.key(): ref for ref in conditions}
        for ref in by_key.values():
            requirement = read(ref, QuoteRequirementView)
            if requirement.inquiry_ref != inquiry.ref or not scope_covers(inquiry.scope, requirement.scope):
                raise ValueError("Quote prerequisite belongs to another inquiry or scope")
            if requirement.product_proposal_ref is not None and requirement.product_proposal_ref != proposal.ref:
                raise ValueError("Quote prerequisite names another product proposal version")
        if proposal.status == "pending_confirmation":
            confirmation = read(proposal.confirmation_requirement_ref, QuoteRequirementView)
            if confirmation.condition_code != "buyer_product_confirmation" or confirmation.product_proposal_ref != proposal.ref:
                raise ValueError("Pending product confirmation must identify this exact proposal")
        reading.recheck()
        return completed("quote", "Complete batch-total prices cover the listed services and explicit prerequisites; schedules and allocations are proposals only",
            offer={"buyer_id": inquiry.buyer_id, "payer_id": payer, "lines": output_lines, "terms_ref": terms.ref,
                   "validity_ref": profile.validity_ref, "condition_refs": list(by_key.values()), "cost_basis_refs": list(used_costs.values())},
            proposed_allocations=allocations)
    except SupplyGap as gap:
        return gap.result
    except (ValueError, KeyError):
        return {"kind": "technical_error", "error": {"kind": "unrecorded", "correlation_id": context.operation_id,
            "code": "supply_quote_projection_invalid"}, "retryability": "non_retryable"}
