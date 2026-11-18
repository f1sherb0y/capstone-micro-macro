"""A04 independent order acceptance drafts against current sourced resources."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, TimeWindow
from src.actions.contracts.supplier_order_objects import (
    FormationOfferView, OrderProposalView, FormationAcceptanceView, FormationTermsView,
    FormationRequirementView, FormationFundingView, FormationPlanView, FormationProfileView,
    order_agreement_digest,
)
from src.actions.contracts.supplier_quote_objects import (
    QuoteInventoryView, QuoteCapacityView, QuoteLocationView, QuoteServiceView, QuoteResourcePoolView,
)
from src.actions.contracts.supplier_product_objects import ProductSpecificationView, ProductDeviationView
from src.actions.roles.supplier import SupplyGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, CapacityResource, CapacityCommitment, CapacityDemand, ExactAmount
from src.methods.pricing import decimal_fraction, exact_decimal
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def accept_order(context, action_input, reading):
    now, organization = context.business_time, reading.organization_id

    def current(window, field, at=None):
        point = now if at is None else at
        available(point, field)
        if window.start.clock_ref != now.clock_ref:
            _unsupported("supply-formation-clock")
        if not window.contains(point):
            _needs(field)

    def available(point, field):
        if point.clock_ref != now.clock_ref:
            _unsupported("supply-formation-clock")
        if point.offset > now.offset:
            _needs(field)

    def evidence(refs, *, at=None):
        point = now if at is None else at
        available(point, "available_formation_evidence_time")
        for ref in refs:
            value = reading.resolve(ref)
            if not isinstance(value, EvidenceRecord):
                _unsupported("supply-formation-evidence-schema")
            if value.effective_window is not None:
                current(value.effective_window, "formation_evidence_valid_at_use", point)

    def read(ref, schema, *, evidence_at_field=None):
        value = reading.resolve(ref)
        if not isinstance(value, schema):
            _unsupported(f"supply-formation-projection:{ref.kind}")
        point = None if evidence_at_field is None else getattr(value, evidence_at_field)
        if point is not None:
            available(point, "available_formation_original_source_time")
        if hasattr(value, "evidence_refs"):
            evidence(value.evidence_refs, at=point)
        return value

    def authority_basis(refs, *, at):
        for ref in refs:
            if ref.kind == 'Evidence':
                evidence([ref], at=at)
            else:
                reading.resolve(ref)

    def unique(refs):
        if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
            raise ValueError("Physical identity repeated across versions")

    def quantity(value, unit, positive=False):
        evidence([value.basis_ref])
        if value.unit != unit:
            _unsupported("supply-formation-unit-conversion")
        amount = decimal_fraction(value.value)
        if amount < 0 or positive and amount == 0:
            raise ValueError("Invalid commitment quantity")
        return amount

    def amount(value, currency):
        evidence([value.basis_ref])
        if value.currency != currency:
            _unsupported("supply-formation-currency-conversion")
        result = decimal_fraction(value.value)
        if result < 0:
            raise ValueError("Negative formation money")
        return result

    def interval(window):
        if window.start.clock_ref != now.clock_ref or window.bounds != "closed_open":
            _unsupported("supply-formation-resource-window")
        if window.start.offset >= window.end.offset:
            raise ValueError("Empty commitment window")
        return window

    def scheduled(ref):
        window = interval(read(ref, TimeWindow))
        if window.start.offset < now.offset:
            _needs("current_nonempty_formation_schedule", [ref])
        return window

    def completed(choice, note, **fields):
        reading.recheck()
        return {"kind": "completed", "payload": {"choice": choice, "note": note, **fields}}

    def revision(note):
        if not profile.revision_requirement_refs:
            _needs("explicit_order_revision_requirements")
        unique(profile.revision_requirement_refs)
        for ref in profile.revision_requirement_refs:
            requirement(ref, require_satisfied=False)
        return completed("revise", note, changed_requirement_refs=profile.revision_requirement_refs)

    def requirement(ref, require_satisfied=True):
        row = read(ref, FormationRequirementView)
        if (row.offer_ref != offer.ref or row.order_proposal_ref not in (None, proposal.ref)
                or not scope_covers(proposal.scope, row.scope)):
            raise ValueError("Formation requirement changes offer, proposal version or scope")
        available(row.available_at, "available_formation_requirement")
        current(row.effective_window, "current_formation_requirement")
        return _known(row.satisfied, "satisfied_order_prerequisite") if require_satisfied else True

    def same_delivery(a, b, partial=False):
        # Numeric equality is exact; provenance stays visible in the output.
        if (a.product.product_ref != b.product.product_ref or a.product.destination_scope_ref != b.product.destination_scope_ref
                or set(a.product.requirement_refs) != set(b.product.requirement_refs)
                or set(a.product.deviation_refs) != set(b.product.deviation_refs)
                or a.delivery_window_ref != b.delivery_window_ref or a.destination_ref != b.destination_ref
                or set(a.included_service_refs) != set(b.included_service_refs)):
            return False
        qa = quantity(a.product.quantity, b.product.quantity.unit, True)
        qb = quantity(b.product.quantity, b.product.quantity.unit, True)
        pa, pb = amount(a.price, currency), amount(b.price, currency)
        return (qa <= qb and 0 < pa <= pb and pa * qb >= pb * qa) if partial else qa == qb and pa == pb

    try:
        unique(action_input.counterpart_acceptance_refs)
        offer = read(action_input.offer_ref, FormationOfferView)
        proposal = read(action_input.order_proposal_ref, OrderProposalView)
        if (offer.supplier_organization_id != organization or proposal.supplier_organization_id != organization
                or proposal.recipient_actor_id != context.actor_id or proposal.offer_ref != offer.ref
                or proposal.buyer_id != offer.buyer_id
                or proposal.scope != offer.scope or not scope_covers(context.scope, proposal.scope)):
            raise ValueError("Order identity differs from exact offer, recipient, counterparties or scope")
        available(offer.available_at, "available_supply_offer")
        available(proposal.received_at, "received_order_proposal")
        current(proposal.response_window, "active_order_response_window")
        validity = read(offer.validity_ref, TimeWindow)
        if validity.start.clock_ref != now.clock_ref:
            _unsupported("supply-formation-clock")
        if offer.status != "active" or proposal.status != "active" or not validity.contains(now):
            return completed("reject", "The proposal or exact quoted offer is inactive or expired; no order is formed")
        profile = read(action_input.formation_profile_ref, FormationProfileView)
        if (profile.organization_id != organization or profile.offer_ref != offer.ref
                or profile.order_proposal_ref != proposal.ref):
            raise ValueError("Formation policy belongs to another organization or agreement version")
        current(profile.effective_window, "current_formation_policy")
        if profile.policy == "reject_new_orders":
            return completed("reject", "Current sourced supplier policy refuses new orders")
        if profile.algorithm_code != "sourced_order_commitment_v1":
            _unsupported("supply-formation-policy-method")
        currency = _known(profile.currency, "formation_currency")
        unique(profile.allowed_terms_refs)
        unique(offer.condition_refs)
        unique(proposal.condition_refs)
        changes = set()
        if proposal.payer_id != offer.payer_id:
            changes.add("payer")
        if proposal.terms_ref != offer.terms_ref:
            changes.add("terms")
        if proposal.terms_ref not in profile.allowed_terms_refs:
            return revision("Changed final payment terms require a revised quote and fresh independent acceptances")
        if set(offer.condition_refs) != set(proposal.condition_refs):
            changes.add("conditions")
        quoted = {row.local_key: row.delivery for row in offer.lines}
        proposed = {row.local_key: row for row in proposal.lines}
        rules = {row.order_line_key: row for row in profile.commercial_rules}
        if set(rules) != set(proposed):
            _needs("complete_order_commercial_rules")
        for row in proposal.lines:
            original = quoted.get(row.offer_line_key)
            rule = rules[row.local_key]
            if original is None or rule.offer_line_key != row.offer_line_key:
                raise ValueError("Order line has no exact original quote batch")
            final = row.delivery
            if final.product.destination_scope_ref != original.product.destination_scope_ref:
                return revision("Final line changes the quoted work scope and requires a revised quote")
            if (final.product.product_ref != original.product.product_ref
                    or set(final.product.requirement_refs) != set(original.product.requirement_refs)
                    or set(final.product.deviation_refs) != set(original.product.deviation_refs)):
                changes.add("product")
            if quantity(final.product.quantity, original.product.quantity.unit, True) != quantity(original.product.quantity, original.product.quantity.unit, True):
                changes.add("quantity")
            if amount(final.price, currency) != amount(original.price, currency):
                changes.add("price")
            for field, code in (("delivery_window_ref", "delivery_window"), ("destination_ref", "destination")):
                if getattr(final, field) != getattr(original, field):
                    changes.add(code)
            if set(final.included_service_refs) != set(original.included_service_refs):
                changes.add("services")
            if rule.scope != final.product.destination_scope_ref or not scope_covers(proposal.scope, rule.scope):
                raise ValueError("Commercial rule changes order line scope")
        if {row.offer_line_key for row in proposal.lines} != set(quoted):
            return revision("Final proposal omits quoted batches and requires an explicit revised quote")
        if not changes <= set(profile.permitted_quote_changes):
            return revision("Final terms change the quote outside the supplier's sourced review policy; new same-version confirmation is required")
        if changes:
            if profile.reviewed_agreement_sha256 is None:
                _needs("supplier_review_of_exact_changed_order_agreement")
            if profile.reviewed_agreement_sha256 != order_agreement_digest(proposal):
                raise ValueError("Supplier change review names another final agreement version")
        original_terms = read(offer.terms_ref, FormationTermsView)
        if (original_terms.offer_ref != offer.ref or original_terms.supplier_organization_id != organization
                or original_terms.buyer_id != offer.buyer_id or original_terms.payer_id != offer.payer_id
                or original_terms.currency != currency):
            raise ValueError("Original terms projection changes the exact quoted counterparties or currency")
        terms = read(proposal.terms_ref, FormationTermsView)
        if (terms.offer_ref != offer.ref or terms.order_proposal_ref not in (None, proposal.ref)
                or terms.supplier_organization_id != organization or terms.buyer_id != proposal.buyer_id
                or terms.payer_id != proposal.payer_id or terms.currency != currency):
            raise ValueError("Terms change offer, order version, supplier, buyer, payer or currency")
        current(terms.effective_window, "current_formation_terms")
        if (len({row.milestone_code for row in terms.payment_rules}) != len(terms.payment_rules)
                or any(decimal_fraction(row.fraction) <= 0 for row in terms.payment_rules)
                or sum((decimal_fraction(row.fraction) for row in terms.payment_rules), Fraction()) != 1):
            raise ValueError("Payment rules must be distinct, positive and total exactly one")
        # All submitted acceptances are checked, including ones not needed by this policy.
        parties = _known(profile.required_counterparty_ids, "required_order_counterparties")
        if not parties or len(set(parties)) != len(parties) or organization in parties:
            raise ValueError("Counterparty policy must identify distinct independent organizations")
        if not {proposal.buyer_id, proposal.payer_id} <= set(parties):
            _needs("buyer_and_payer_independent_acceptances")
        accepted, authors = set(), set()
        counterparty_revision = False
        digest = order_agreement_digest(proposal)
        for ref in action_input.counterpart_acceptance_refs:
            acceptance = read(ref, FormationAcceptanceView, evidence_at_field='created_at')
            if (acceptance.run_id != context.run_id or acceptance.proposal_ref != proposal.ref
                    or acceptance.offer_ref != offer.ref or acceptance.terms_ref != terms.ref
                    or acceptance.scope != proposal.scope or acceptance.agreement_sha256 != digest
                    or acceptance.party_id not in parties or acceptance.party_id in accepted
                    or acceptance.author_actor_id == context.actor_id or acceptance.author_actor_id in authors):
                raise ValueError("Acceptance is duplicated, impersonated or names another run/agreement")
            available(acceptance.created_at, "available_counterparty_acceptance")
            if acceptance.created_at.offset < proposal.received_at.offset:
                raise ValueError("Counterparty acceptance predates this proposal")
            current(acceptance.validity, "valid_counterparty_acceptance")
            current(acceptance.validity, "acceptance_valid_when_authored", acceptance.created_at)
            authority = read(acceptance.authorization_ref, Authorization)
            assignment = read(acceptance.author_function_ref, RoleAssignment)
            authority_basis([*authority.basis_refs, *assignment.basis_refs], at=acceptance.created_at)
            if (authority.organization_id != acceptance.party_id or authority.actor_id != acceptance.author_actor_id
                    or authority.function_ref != acceptance.author_function_ref or assignment.function_ref != authority.function_ref):
                raise ValueError("Acceptance author differs from the sourced party/function authorization")
            current(authority.validity, "current_counterparty_authority")
            current(authority.validity, "counterparty_authority_when_authored", acceptance.created_at)
            if (acceptance.action_id not in authority.action_ids or acceptance.action_id not in profile.counterpart_action_ids
                    or not any(scope_covers(scope, proposal.scope) for scope in authority.scopes)
                    or not {offer.ref.key(), proposal.ref.key(), terms.ref.key()} <= {ref.key() for ref in authority.readable_refs}):
                raise ValueError("Counterparty acceptance exceeds action or scope authority")
            expected_role = {"OWN": "Owner", "BANK": "Bank", "CONTRACTOR": "Contractor", "SUPPLIER": "Supplier",
                "ARCHITECT": "Architect", "ENGINEER": "Engineer", "QS": "QS", "GOV": "Government"}.get(acceptance.action_id.split("-", 1)[0])
            if expected_role != assignment.role:
                raise ValueError("Counterparty function role does not authorize its acceptance action")
            if acceptance.status != "active":
                _needs("active_counterparty_acceptance", [acceptance.ref])
            if acceptance.choice != "accept":
                counterparty_revision = True
            accepted.add(acceptance.party_id)
            authors.add(acceptance.author_actor_id)
        if counterparty_revision:
            return revision("A counterparty has rejected or revised this agreement; new independent confirmation is needed")
        if profile.policy == "revise":
            return revision("Current sourced formation policy requires explicit requirements to be revised")
        for ref in dict.fromkeys([*offer.condition_refs, *proposal.condition_refs]):
            if not requirement(ref):
                _needs("fulfilled_original_order_prerequisites", [ref])

        inventory = read(action_input.inventory_ref, QuoteInventoryView)
        capacity = read(action_input.capacity_ref, QuoteCapacityView)
        funds = read(action_input.funding_ref, FormationFundingView)
        if any(row.organization_id != organization for row in (inventory, capacity, funds)):
            raise ValueError("Formation resources or funds belong to another organization")
        if any(row.as_of != now for row in (inventory, capacity, funds)):
            _needs("current_order_funding_stock_and_capacity")
        if (inventory.coverage != "complete" or capacity.resource_coverage != "complete"
                or capacity.commitment_coverage != "complete" or funds.coverage != "complete"):
            _needs("complete_order_resource_and_funding_snapshot")
        cash = amount(_known(funds.actual_cash, "known_supplier_actual_cash"), currency)
        committed_cash = amount(_known(funds.committed_cash, "known_supplier_committed_cash"), currency)
        if committed_cash > cash:
            raise ValueError("Committed cash exceeds actual cash")
        free_cash = cash - committed_cash
        pools = {row.resource_ref.key(): row for row in capacity.resources}
        resources, commitments = [], []
        for pool in capacity.resources:
            object_view = read(pool.resource_ref, QuoteResourcePoolView)
            if object_view.organization_id != organization or object_view.region_id != pool.region_id:
                raise ValueError("Formation pool identity or region mismatch")
            total = _known(pool.total, "known_order_pool_capacity")
            quantity(total, total.unit)
            resources.append(CapacityResource(resource_ref=pool.resource_ref, resource_kind=pool.resource_ref.id,
                region_id=pool.region_id, total=total, effective_window=interval(pool.effective_window)))
        for commitment in capacity.commitments:
            pool = pools.get(commitment.resource_ref.key())
            if pool is None:
                raise ValueError("Existing commitment names an absent pool version")
            quantity(commitment.quantity, _known(pool.total, "known_pool_total").unit, True)
            interval(commitment.window)
            commitments.append(CapacityCommitment(**commitment.model_dump(mode="python")))
        lots = {row.batch_ref.key(): row for row in inventory.lots}
        for lot in inventory.lots:
            evidence([lot.actual.basis_ref, lot.committed.basis_ref])

        def evaluate(ref, partial):
            plan = read(ref, FormationPlanView)
            if (plan.organization_id != organization or plan.offer_ref != offer.ref or plan.order_proposal_ref != proposal.ref
                    or plan.purpose != ("partial_counterproposal" if partial else "full_order")):
                raise ValueError("Commitment plan changes organization, agreement version or purpose")
            current(plan.effective_window, "current_order_commitment_plan")
            available(plan.available_at, "available_order_commitment_plan")
            if any(row.order_line_key not in proposed for row in plan.lines):
                raise ValueError("Commitment plan introduces an unrelated order line")
            if not partial and {row.order_line_key for row in plan.lines} != set(proposed):
                _needs("complete_full_order_commitment_plan")
            used_stock, allocations, demands = {}, [], []
            needed_cash = Fraction()
            failure = None
            for line in plan.lines:
                source, rule, delivery = proposed[line.order_line_key].delivery, rules[line.order_line_key], line.delivery
                if not same_delivery(delivery, source, partial):
                    raise ValueError("Commitment plan changes final delivery or exceeds original quantity/amount")
                q = quantity(delivery.product.quantity, source.product.quantity.unit, True)
                price = amount(delivery.price, currency)
                unique(rule.allowed_product_refs)
                unique(rule.allowed_destination_refs)
                unique(rule.required_service_refs)
                unique(rule.prerequisite_refs)
                if (delivery.product.product_ref not in rule.allowed_product_refs
                        or delivery.destination_ref not in rule.allowed_destination_refs
                        or set(delivery.included_service_refs) != set(rule.required_service_refs)
                        or q > quantity(rule.maximum_quantity, source.product.quantity.unit, True)
                        or price < amount(rule.minimum_batch_price, currency)
                        or price < amount(rule.minimum_unit_price, currency) * q):
                    failure = "The final line violates the sourced commercial minimum or allowed scope"
                for condition in rule.prerequisite_refs:
                    if not requirement(condition):
                        _needs("fulfilled_commitment_plan_prerequisites", [condition])
                window = scheduled(delivery.delivery_window_ref)
                allowed = scheduled(rule.allowed_window_ref)
                if window.start.offset < allowed.start.offset or window.end.offset > allowed.end.offset:
                    failure = "The final delivery lies outside the allowed commercial window"
                product = read(delivery.product.product_ref, ProductSpecificationView)
                if product.supplier_organization_id != organization:
                    raise ValueError("Committed product belongs to another supplier")
                current(product.effective_window, "current_order_product")
                if product.quantity_unit != source.product.quantity.unit:
                    _unsupported("supply-formation-product-unit")
                for requirement_ref in delivery.product.requirement_refs:
                    requirement(requirement_ref, require_satisfied=False)
                for deviation_ref in delivery.product.deviation_refs:
                    deviation = read(deviation_ref, ProductDeviationView)
                    if (deviation.product_ref != product.ref or deviation.scope != delivery.product.destination_scope_ref
                            or deviation.requirement_ref not in delivery.product.requirement_refs):
                        raise ValueError("Committed deviation changes product or requirement scope")
                    current(deviation.effective_window, "current_order_deviation")
                origin = read(line.source_location_ref, QuoteLocationView)
                read(delivery.destination_ref, QuoteLocationView)
                codes = []
                for service_ref in delivery.included_service_refs:
                    service = read(service_ref, QuoteServiceView)
                    current(service.effective_window, "current_order_service")
                    if service.provider_organization_id != organization or service.destination_ref != delivery.destination_ref:
                        raise ValueError("Order service changes provider or destination")
                    codes.append(service.service_code)
                if len(set(codes)) != len(codes) or "factory_supply" not in codes:
                    raise ValueError("Order delivery responsibility is duplicated or incomplete")
                stock_quantity = Fraction()
                unique([use.batch_ref for use in line.stock_uses])
                for use in line.stock_uses:
                    lot = lots.get(use.batch_ref.key())
                    if lot is None:
                        _needs("actual_product_batch_snapshot", [use.batch_ref])
                    if lot.product_ref != product.ref or lot.location_ref != origin.ref:
                        raise ValueError("Stock plan changes actual batch product version or location")
                    used = quantity(use.quantity, source.product.quantity.unit, True)
                    stock_quantity += used
                    used_stock[use.batch_ref.key()] = used_stock.get(use.batch_ref.key(), Fraction()) + used
                    free = quantity(lot.actual, source.product.quantity.unit) - quantity(lot.committed, source.product.quantity.unit)
                    if lot.status != "usable" or used_stock[use.batch_ref.key()] > free:
                        failure = "The plan oversells actual usable uncommitted stock"
                if stock_quantity > q:
                    raise ValueError("Actual stock usage exceeds accepted quantity")
                manufacture = q - stock_quantity
                if stock_quantity and "stock" not in rule.allowed_fulfillment_modes:
                    failure = "Stock fulfilment is prohibited by this line policy"
                production_uses = [use for use in line.resource_uses if use.source == "manufacture"]
                if manufacture:
                    if "manufacture" not in rule.allowed_fulfillment_modes:
                        failure = "Manufacture is prohibited by this line policy"
                    if origin.factory_id != _known(product.factory_id, "order_product_factory"):
                        raise ValueError("Manufacturing changes the exact product factory")
                    if not production_uses:
                        _needs("explicit_order_manufacturing_demands")
                elif production_uses:
                    raise ValueError("Stock-only order carries phantom manufacturing")
                if "transport" in codes and not any(use.source == "delivery" for use in line.resource_uses):
                    _needs("explicit_order_transport_demands")
                if len({(use.resource_ref.key(), use.window_ref.key(), use.source) for use in line.resource_uses}) != len(line.resource_uses):
                    raise ValueError("Physical resource demand repeated")
                for use in line.resource_uses:
                    pool = pools.get(use.resource_ref.key())
                    if pool is None:
                        _needs("current_order_resource_pool", [use.resource_ref])
                    if pool.region_id != origin.region_id:
                        _unsupported("supply-formation-moving-resource")
                    resource_window = scheduled(use.window_ref)
                    if use.source == "manufacture" and resource_window.end.offset > window.start.offset:
                        failure = "Manufacture cannot finish before the final delivery"
                    if use.source == "delivery" and resource_window != window:
                        _unsupported("supply-formation-delivery-window-alignment")
                    rate = quantity(use.rate_per_product_unit, _known(pool.total, "known_pool_total").unit, True)
                    needed = rate * (manufacture if use.source == "manufacture" else q)
                    demands.append(CapacityDemand(resource_kind=pool.resource_ref.id, region_id=pool.region_id,
                        unit=use.rate_per_product_unit.unit, amount=ExactAmount.from_fraction(needed), window=resource_window,
                        basis_refs=[use.rate_per_product_unit.basis_ref]))
                    allocations.append({"resource_ref": pool.resource_ref, "scope_ref": delivery.product.destination_scope_ref,
                        "window_ref": use.window_ref, "quantity": {"value": exact_decimal(needed),
                            "unit": use.rate_per_product_unit.unit, "basis_ref": use.rate_per_product_unit.basis_ref}})
                needed_cash += amount(_known(line.working_capital, "known_order_working_capital"), currency)
            # Quantities across different units are not added to establish subset:
            # per-line comparisons above establish <=; any omission or reduction is strict.
            strict = len(plan.lines) < len(proposal.lines) or any(
                decimal_fraction(line.delivery.product.quantity.value) < decimal_fraction(proposed[line.order_line_key].delivery.product.quantity.value)
                for line in plan.lines)
            if partial and not strict:
                raise ValueError("Partial acceptance must be a strict positive per-line subset")
            if needed_cash > free_cash:
                failure = "Current actual cash minus commitments cannot finance this commitment plan"
            if demands:
                result = reading.calculate(CAPACITY_METHOD, CapacityInput(clock_ref=now.clock_ref, demands=demands,
                    resources=resources, commitments=commitments, source_refs=[capacity.ref, inventory.ref, funds.ref, plan.ref]))
                if result.kind != "ok":
                    if result.kind == "invalid_input":
                        raise ValueError("Formation capacity input exceeds the supported domain")
                    raw = result.model_dump(mode="python")
                    if result.kind == "needs_information":
                        raw["requested_refs"] = []
                    raise SupplyGap(raw)
                if not result.value.feasible:
                    failure = "Current shared physical pool commitments conflict with this plan"
            return plan, allocations, failure

        if profile.full_plan_ref is None and profile.policy != "prefer_partial":
            _needs("explicit_full_order_commitment_plan")
        if profile.policy != "prefer_partial":
            plan, allocations, failure = evaluate(profile.full_plan_ref, False)
            if failure is None:
                if accepted != set(parties):
                    _needs("all_independent_same_version_counterparty_acceptances")
                return completed("accept", "Supplier accepts this exact independently confirmed version; formal formation and resource reservation require the macro core",
                    offer_ref=offer.ref, accepted_lines=[row.delivery.model_dump(mode="python") for row in plan.lines], terms_ref=terms.ref,
                    proposed_allocations=allocations)
            if profile.on_conflict == "revise":
                return revision(failure)
            if profile.on_conflict == "reject":
                return completed("reject", failure + "; no effective order or reservation is formed")
        partials = []
        for item in profile.partial_plans:
            plan, allocations, failure = evaluate(item.plan_ref, True)
            if failure is None:
                partials.append((item.priority, plan, allocations))
        if not partials:
            return completed("reject", "No sourced positive partial plan satisfies current funding, stock and shared capacity")
        rank = min(row[0] for row in partials)
        best = [row for row in partials if row[0] == rank]
        if len(best) != 1:
            _needs("unique_partial_order_policy_priority")
        _, plan, allocations = best[0]
        return completed("accept_partial", "Strict positive subset counterproposal awaits fresh same-version buyer/payer confirmation; uncovered lines remain unaccepted and no partial effective order is formed",
            offer_ref=offer.ref, accepted_lines=[row.delivery.model_dump(mode="python") for row in plan.lines], terms_ref=terms.ref,
            proposed_allocations=allocations)
    except SupplyGap as gap:
        return gap.result
    except (ValueError, KeyError):
        return {"kind": "technical_error", "error": {"kind": "unrecorded", "correlation_id": context.operation_id,
            "code": "supply_formation_projection_invalid"}, "retryability": "non_retryable"}
