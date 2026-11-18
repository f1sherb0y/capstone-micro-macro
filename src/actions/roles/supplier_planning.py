"""SUPPLIER-A05 requests bounded plans and upstream procurement, not stock."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, TimeWindow
from src.actions.contracts.supplier_planning_objects import (
    SupplierWorkAuthorityView, SupplierPlanningOrderView, SupplierStockingAuthorityView,
    SupplierPlanningProfileView, SupplierSupplyPlanView, SupplierPlanningRequirementView,
    SupplierPlanningDesignView, SupplierPlanningMethodView, SupplierPlanningResourceView,
    SupplierInventoryAllocationView, SupplierPlanningDependencyView, SupplierPlanningProductView,
    SupplierPlanningProductRequirementView, SupplierPlanningDeviationView, SupplierPlanningOrderLineView,
    SupplierProcurementAuthorityView, SupplierUpstreamCommitmentView,
    SupplierPlanningCommitmentView,
    QuoteInventoryView, QuoteCapacityView, FormationOfferView, FormationTermsView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _known, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, CapacityResource, CapacityCommitment, CapacityDemand, ExactAmount
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def plan_supply(context, action_input, reading):
    now, org, scope = context.business_time, reading.organization_id, context.scope
    sources = {}

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('supplier-planning-clock-alignment')

    def evidence(refs, *, at=None, historic=False):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset:
            _needs('received_original_supply_planning_evidence_time')
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('supplier-planning-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if row.effective_window.start.offset > now.offset:
                    _needs('received_original_supply_planning_evidence', [ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_supply_planning_evidence_valid_at_use', [ref])
            sources[ref.key()] = ref

    def read(ref, schema, historic=False, linked=False, *, evidence_at_field=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('supplier-planning-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Supply plan expands original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_supply_planning_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now):
                _needs('current_original_supply_planning_source', [ref])
        point = None if evidence_at_field is None else getattr(row, evidence_at_field)
        if point is not None:
            clock(point)
            if point.offset > now.offset:
                _needs('received_original_supply_planning_evidence_time', [ref])
            if point.offset > row.available_at.offset:
                raise ValueError('Supply planning source receipt precedes original authorship')
        evidence(getattr(row, 'evidence_refs', []), at=point, historic=historic)
        sources[ref.key()] = ref
        return row

    def true(value):
        return isinstance(value, Known) and value.value is True

    def authorize(ref, actor, function, at, target):
        grant = read(ref, Authorization, historic=True, linked=True)
        assignment = read(function, RoleAssignment, historic=True, linked=True)
        if (grant.actor_id != actor or grant.organization_id != org or grant.function_ref != function
                or assignment.function_ref != function or assignment.role != 'Supplier' or 'SUPPLIER-A05' not in grant.action_ids
                or not any(scope_covers(s, target) for s in grant.scopes)):
            raise ValueError('Supply plan lacks actual independent actor/function/scope authority')
        clock(at); clock(grant.validity.start)
        if at.offset > now.offset:
            _needs('received_original_supply_planning_author_time', [ref])
        if not grant.validity.contains(at):
            _needs('original_supply_planning_authority_at_execution', [ref])
        for basis_ref in [*grant.basis_refs, *assignment.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=at)
            else:
                reading.resolve(basis_ref); sources[basis_ref.key()] = basis_ref

    def author(plan):
        clock(plan.authored_at)
        if (plan.author_organization_id != org or plan.author_action_id != 'SUPPLIER-A05'
                or plan.authored_at.offset > plan.available_at.offset
                or not plan.effective_window.contains(plan.authored_at)):
            raise ValueError('Supply plan substitutes original author or execution time')
        authorize(plan.author_authority_ref, plan.author_actor_id, plan.author_function_ref, plan.authored_at, plan.scope)

    def quantity(value, unit):
        evidence([value.basis_ref])
        if value.unit != unit or decimal_fraction(value.value) <= 0:
            raise ValueError('Supply plan requires positive quantities in original units')
        return decimal_fraction(value.value)

    def product(line):
        if not scope_covers(scope, line.destination_scope_ref):
            raise ValueError('Planned product destination leaves original work authority')
        spec = read(line.product_ref, SupplierPlanningProductView, linked=True)
        q = quantity(line.quantity, spec.quantity_unit)
        if not line.requirement_refs:
            _needs('original_product_requirements')
        keys(line.requirement_refs); keys(line.deviation_refs)
        for ref in line.requirement_refs:
            req = read(ref, SupplierPlanningProductRequirementView)
            if line.product_ref.key() not in keys(req.product_refs):
                raise ValueError('Product requirement does not apply to original planned specification')
        for ref in line.deviation_refs:
            deviation = read(ref, SupplierPlanningDeviationView)
            if (deviation.product_ref != line.product_ref or not true(deviation.permitted)
                    or not keys(deviation.requirement_refs) <= keys(line.requirement_refs)):
                _needs('independent_original_specification_deviation_authority', [ref])
        return q

    def same_product(left, right):
        return (left.product_ref == right.product_ref and left.destination_scope_ref == right.destination_scope_ref
            and left.quantity.unit == right.quantity.unit and keys(left.requirement_refs) == keys(right.requirement_refs)
            and keys(left.deviation_refs) == keys(right.deviation_refs))

    def complete(choice, **fields):
        note=profile.note
        if profile.monthly_inventory_policy_ref is not None or profile.monthly_inventory_observation_ref is not None:
            if (profile.monthly_inventory_policy_ref is None or profile.monthly_inventory_observation_ref is None
                    or profile.monthly_reliability_policy_ref is not None or profile.monthly_reliability_observation_ref is not None
                    or choice != 'request_quote' or mandate.order_ref is not None):
                raise ValueError('Monthly inventory review requires one complete own-risk planning policy')
            from src.actions.roles.supplier_monthly_inventory import analyze_inventory_review
            note = analyze_inventory_review(context, reading, profile=profile, mandate=mandate,
                inventory=inventory, capacity=capacity, request=fields).model_dump_json()
        if profile.monthly_reliability_policy_ref is not None or profile.monthly_reliability_observation_ref is not None:
            if profile.monthly_reliability_policy_ref is None or profile.monthly_reliability_observation_ref is None:
                raise ValueError('Monthly reliability review requires both policy and observation')
            if choice!='request_quote' or mandate.order_ref is not None:
                raise ValueError('Monthly reliability review requires an independently authorized own-risk nonbinding request')
            from src.actions.roles.supplier_monthly_reliability import analyze_reliability_review
            note=analyze_reliability_review(context,action_input,reading,profile=profile,mandate=mandate,
                inventory=inventory,capacity=capacity,request=fields).model_dump_json()
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, **fields,
            'note': note if (profile.monthly_reliability_policy_ref is not None or profile.monthly_inventory_policy_ref is not None) else note + ' Plan/request only. Outstanding material/design dependencies remain gates of their own tasks; no stock, reserved resources, production, agreed delivery change or upstream order is created. Core and independent upstream confirmation precede execution.'}}

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
            'trigger': 'dependency_change', 'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    try:
        if action_input.scope_ref != scope:
            raise ValueError('Supply planning changes original invocation scope')
        mandate = read(action_input.work_authority_ref, SupplierWorkAuthorityView)
        profile = read(mandate.profile_ref, SupplierPlanningProfileView)
        if (mandate.organization_id != org or not true(mandate.permitted)
                or profile.work_authority_ref != mandate.ref or profile.organization_id != org
                or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
                or profile.authority_ref not in context.authorization_refs or profile.scope != scope):
            raise ValueError('Supply planning changes original organization, effective mandate or actor')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, now, scope)
        if (mandate.order_ref is None) == (mandate.speculative_authority_ref is None):
            raise ValueError('Work requires exactly one effective order or independent stocking authority')
        order = None
        if mandate.order_ref is not None:
            order = read(mandate.order_ref, SupplierPlanningOrderView, linked=True)
            if order.supplier_id != org or not true(order.effective) or not scope_covers(order.scope, scope):
                _needs('original_effective_core_confirmed_supply_order', [order.ref])
            if not mandate.order_line_refs or not keys(mandate.order_line_refs) <= keys(order.line_refs):
                raise ValueError('Scoped work mandate substitutes original effective order lines')
        else:
            stocking = read(mandate.speculative_authority_ref, SupplierStockingAuthorityView)
            if (stocking.organization_id != org or stocking.risk_bearer_id != org or not true(stocking.permitted)
                    or not keys(mandate.requirement_refs) <= keys(stocking.requirement_refs)):
                _needs('independent_own_risk_speculative_stocking_authority')
            authorize(stocking.authority_ref, context.actor_id, context.function_ref, now, scope)
            if mandate.order_line_refs:
                raise ValueError('Speculative stocking substitutes unsigned customer order lines')
        for field in ('requirement_refs', 'design_refs', 'method_refs'):
            if keys(getattr(action_input, field)) != keys(getattr(mandate, field)):
                _needs('complete_original_supply_' + field)
        requirements = {}
        for ref in action_input.requirement_refs:
            req = read(ref, SupplierPlanningRequirementView)
            if req.work_authority_ref != mandate.ref or not true(req.permitted):
                _needs('original_authorized_supply_requirement', [ref])
            product(req.target); requirements[ref.key()] = req
        outputs = {k:r for k,r in requirements.items() if r.purpose == 'order_output'}
        if not outputs:
            _needs('original_output_supply_requirements')
        if order is not None:
            lines = {ref.key():read(ref, SupplierPlanningOrderLineView) for ref in mandate.order_line_refs}
            allocated = {}
            for req in outputs.values():
                if req.order_line_ref is None or req.order_line_ref.key() not in lines:
                    raise ValueError('Supply output requirement replaces original effective order line')
                line = lines[req.order_line_ref.key()]
                clock(line.as_of)
                if line.order_ref != order.ref or line.as_of != now or not same_product(req.target, line.product):
                    raise ValueError('Supply output substitutes original order product or current remaining amount')
                allocated[line.ref.key()] = allocated.get(line.ref.key(), Fraction(0)) + decimal_fraction(req.target.quantity.value)
            if set(allocated) != set(lines):
                raise ValueError('Supply requirements drop an original effective order line')
            for key,line in lines.items():
                evidence([line.remaining_quantity.basis_ref])
                if (line.remaining_quantity.unit != line.product.quantity.unit
                        or allocated[key] != decimal_fraction(line.remaining_quantity.value)):
                    raise ValueError('Supply requirements do not match actual remaining original order quantity')
        elif any(req.order_line_ref is not None for req in outputs.values()):
            raise ValueError('Speculative stocking requirements invent customer order-line coverage')
        for ref in action_input.design_refs:
            design = read(ref, SupplierPlanningDesignView)
            if design.work_authority_ref != mandate.ref or not keys(design.requirement_refs) <= set(requirements):
                raise ValueError('Supply planning design replaces original mandate or requirements')
        inventory = read(action_input.inventory_ref, QuoteInventoryView, linked=True)
        capacity = read(action_input.capacity_ref, QuoteCapacityView, linked=True)
        clock(inventory.as_of); clock(capacity.as_of)
        if inventory.organization_id != org or capacity.organization_id != org:
            raise ValueError('Supply plan uses another organization stock or capacity')
        keys(action_input.upstream_offer_refs)

        def requested_lines(lines):
            if not lines:
                _needs('concrete_original_upstream_product_lines')
            assigned = {}
            for line in lines:
                q = product(line)
                matches = [r for r in requirements.values() if same_product(line, r.target)]
                if len(matches) != 1:
                    _needs('unambiguous_original_requirement_for_requested_product')
                req = matches[0]
                assigned[req.ref.key()] = assigned.get(req.ref.key(), Fraction(0)) + q
                if assigned[req.ref.key()] > decimal_fraction(req.target.quantity.value):
                    raise ValueError('Upstream request exceeds original authorized product requirement')

        if profile.choice == 'request_quote':
            if not profile.supplier_ids or len(set(profile.supplier_ids)) != len(profile.supplier_ids) or org in profile.supplier_ids:
                raise ValueError('Quote request requires distinct explicit independent upstream recipients')
            requested_lines(profile.required_lines)
            return complete('request_quote', supplier_ids=profile.supplier_ids,
                required_lines=[line.model_dump(mode='python') for line in profile.required_lines])

        if profile.choice == 'seek_delivery_change':
            if order is None or not profile.affected_line_refs or profile.proposed_window_ref is None:
                _needs('original_order_lines_and_proposed_delivery_window')
            if not keys(profile.affected_line_refs) <= keys(mandate.order_line_refs):
                raise ValueError('Delivery-change request affects other original order lines')
            for ref in profile.affected_line_refs:
                line = read(ref, SupplierPlanningOrderLineView)
                if line.order_ref != order.ref:
                    raise ValueError('Delivery change replaces original effective order')
                product(line.product); read(line.delivery_window_ref, TimeWindow)
            window = read(profile.proposed_window_ref, TimeWindow); clock(window.start); clock(window.end)
            if window.start.offset < now.offset:
                raise ValueError('Proposed delivery window starts before current request')
            return complete('seek_delivery_change', affected_line_refs=profile.affected_line_refs,
                proposed_window_ref=profile.proposed_window_ref)

        if profile.choice == 'accept_upstream_offer':
            if profile.offer_ref is None or profile.procurement_authority_ref is None:
                _needs('original_upstream_offer_and_independent_procurement_authority')
            if profile.offer_ref.key() not in keys(action_input.upstream_offer_refs):
                raise ValueError('Upstream acceptance selects an unreceived offer')
            offer = read(profile.offer_ref, FormationOfferView, linked=True)
            validity = read(offer.validity_ref, TimeWindow); clock(validity.start)
            if offer.status != 'active' or not validity.contains(now) or offer.buyer_id != org or offer.supplier_organization_id == org:
                _needs('current_original_independent_upstream_offer', [offer.ref])
            terms = read(offer.terms_ref, FormationTermsView, linked=True)
            if (terms.offer_ref != offer.ref or terms.buyer_id != org or terms.payer_id != offer.payer_id
                    or terms.supplier_organization_id != offer.supplier_organization_id):
                raise ValueError('Upstream acceptance substitutes original offer terms or parties')
            procurement = read(profile.procurement_authority_ref, SupplierProcurementAuthorityView)
            if (procurement.work_authority_ref != mandate.ref or procurement.organization_id != org
                    or procurement.actor_id != context.actor_id or procurement.function_ref != context.function_ref
                    or not true(procurement.permitted) or offer.payer_id not in procurement.allowed_payer_ids):
                _needs('independent_original_upstream_procurement_and_payer_authority')
            clock(procurement.as_of)
            if procurement.coverage != 'complete' or procurement.as_of != now:
                _needs('complete_current_original_upstream_procurement_history')
            selected = profile.offer_line_keys
            if not selected or len(set(selected)) != len(selected):
                raise ValueError('Upstream acceptance requires unique exact original offer lines')
            by_key = {line.local_key:line for line in offer.lines}
            if not set(selected) <= set(by_key):
                raise ValueError('Upstream acceptance invents an original offer line')
            if profile.required_lines != [by_key[key].delivery.product for key in selected]:
                raise ValueError('Upstream acceptance changes quoted batch specification, scope or quantity')
            requested_lines(profile.required_lines)
            total = Fraction(0)
            for key in selected:
                delivery = by_key[key].delivery
                evidence([delivery.price.basis_ref])
                if delivery.price.currency != terms.currency:
                    raise ValueError('Upstream offer batch price changes original terms currency')
                total += decimal_fraction(delivery.price.value)
            used = Fraction(0); seen = set()
            for ref in procurement.commitment_refs:
                previous = read(ref, SupplierUpstreamCommitmentView, historic=True)
                identity = (previous.offer_ref.key(), tuple(sorted(previous.offer_line_keys)))
                if (previous.work_authority_ref != mandate.ref or previous.organization_id != org or identity in seen
                        or previous.amount.currency != terms.currency):
                    raise ValueError('Upstream history substitutes original mandate or repeats accepted offer lines')
                seen.add(identity); evidence([previous.amount.basis_ref], historic=True)
                if decimal_fraction(previous.amount.value) < 0:
                    raise ValueError('Original procurement commitment amount cannot be negative')
                if previous.offer_ref == offer.ref and set(previous.offer_line_keys) & set(selected):
                    return wait('continue_original_upstream_procurement', [previous.ref])
                if previous.status not in {'released', 'failed'}:
                    used += decimal_fraction(previous.amount.value)
            keys(procurement.commitment_refs)
            actual_used = _known(procurement.used, 'actual_used_procurement_authority')
            evidence([actual_used.basis_ref, procurement.limit.basis_ref])
            if (actual_used.currency != terms.currency or procurement.limit.currency != terms.currency
                    or decimal_fraction(actual_used.value) < 0 or decimal_fraction(procurement.limit.value) <= 0
                    or decimal_fraction(actual_used.value) != used or total + used > decimal_fraction(procurement.limit.value)):
                _needs('original_remaining_upstream_procurement_limit')
            for ref in offer.condition_refs:
                condition = read(ref, SupplierPlanningProductRequirementView, linked=True)
                if condition.offer_ref != offer.ref or not true(condition.satisfied):
                    _needs('original_upstream_offer_acceptance_condition', [ref])
            return complete('accept_upstream_offer', offer_ref=offer.ref, terms_ref=terms.ref,
                required_lines=[line.model_dump(mode='python') for line in profile.required_lines])

        if profile.choice not in {'plan_manufacture', 'plan_purchase', 'split_plan', 'revise_plan'}:
            _unsupported('supplier-planning-choice')
        if profile.plan_ref is None:
            _needs('original_authored_supply_plan')
        plan = read(profile.plan_ref, SupplierSupplyPlanView, evidence_at_field='authored_at'); author(plan)
        if plan.work_authority_ref != mandate.ref or not plan.tasks or plan.status != 'proposed':
            raise ValueError('Supply plan substitutes mandate or original proposed tasks')
        task_keys = {t.local_key for t in plan.tasks}
        if len(task_keys) != len(plan.tasks) or set(plan.task_requirement_refs) != task_keys:
            raise ValueError('Supply plan requires unique original tasks and exact requirement bindings')
        modes = {t.mode for t in plan.tasks}
        if not modes <= set(mandate.permitted_modes):
            raise ValueError('Supplier mandate does not support declared manufacture/purchase/rework modes')
        if profile.choice == 'plan_purchase' and modes != {'purchase'}:
            raise ValueError('Trade procurement plan cannot create own production')
        if profile.choice == 'plan_manufacture' and not modes <= {'manufacture', 'rework'}:
            raise ValueError('Manufacturing plan substitutes purchase tasks')
        if profile.choice == 'split_plan' and len(plan.tasks) < 2:
            raise ValueError('Split supply plan requires multiple explicit task partitions')
        excluded = set()
        if profile.choice == 'revise_plan':
            if profile.prior_plan_ref is None or plan.replaces_plan_ref != profile.prior_plan_ref:
                _needs('original_prior_supply_plan_and_explicit_revision')
            prior = read(profile.prior_plan_ref, SupplierSupplyPlanView, historic=True, evidence_at_field='authored_at'); author(prior)
            if prior.work_authority_ref != mandate.ref or prior.status not in {'proposed', 'effective'} or prior.ref == plan.ref:
                raise ValueError('Supply revision replaces another mandate or stale plan')
            excluded = keys(plan.replacement_commitment_refs)
            # Only commitments independently bound to the original prior plan
            # may be replaced; replacements remain requests to the core.
            for ref in plan.replacement_commitment_refs:
                original = read(ref, SupplierPlanningCommitmentView)
                if original.plan_ref != prior.ref or original.organization_id != org:
                    raise ValueError('Supply revision releases another original plan commitment')
        elif plan.replaces_plan_ref is not None or plan.replacement_commitment_refs:
            raise ValueError('New supply plan cannot discard existing plan or resource reservations')
        if modes != {'purchase'} and (capacity.as_of != now or capacity.resource_coverage != 'complete'
                or capacity.commitment_coverage != 'complete'):
            _needs('complete_current_original_supply_capacity_snapshot')
        pools = {row.resource_ref.key():row for row in capacity.resources}
        resources = []; commitments = []; demands = []; allocated_stock = {}; used_allocations = set(); allocation_events = set()
        future_requirements = {}
        assigned_outputs = {}; acquired_material = {}; task_windows = {}; graph = {}
        for row in (capacity.resources if modes != {'purchase'} else []):
            original = read(row.resource_ref, SupplierPlanningResourceView, linked=True)
            clock(row.effective_window.start)
            if original.organization_id != org or original.region_id != row.region_id:
                raise ValueError('Supply capacity substitutes original physical own pool')
            total = _known(row.total, 'actual_supply_resource_capacity')
            evidence([total.basis_ref])
            resources.append(CapacityResource(resource_ref=row.resource_ref, resource_kind=row.resource_ref.id,
                region_id=row.region_id, total=total, effective_window=row.effective_window))
        for row in (capacity.commitments if modes != {'purchase'} else []):
            if row.commitment_ref.key() in excluded:
                original = read(row.commitment_ref, SupplierPlanningCommitmentView)
                window = read(original.window_ref, TimeWindow)
                if original.resource_ref != row.resource_ref or original.quantity != row.quantity or window != row.window:
                    raise ValueError('Revision changes original commitment quantity, physical pool or occupied window')
                continue
            commitments.append(CapacityCommitment(commitment_ref=row.commitment_ref,
                resource_ref=row.resource_ref, quantity=row.quantity, window=row.window))
            evidence([row.quantity.basis_ref])
        if not excluded <= keys([r.commitment_ref for r in capacity.commitments]):
            raise ValueError('Revision replacement is absent from complete original capacity ledger')
        for task in plan.tasks:
            if not scope_covers(scope, task.scope_ref) or not scope_covers(task.scope_ref, task.target.destination_scope_ref):
                raise ValueError('Supply task expands original work or product scope')
            target_quantity = product(task.target)
            if task.method_ref.key() not in keys(action_input.method_refs):
                raise ValueError('Supply task uses an unreceived original supply method')
            method = read(task.method_ref, SupplierPlanningMethodView)
            if (method.mode != task.mode or method.product_ref != task.target.product_ref
                    or method.quantity_unit != task.target.quantity.unit or not true(method.supported)):
                _unsupported('original_supply_method_mode_or_product_support')
            if not keys(method.design_refs) <= keys(action_input.design_refs):
                _needs('original_method_required_design_sources', method.design_refs)
            bindings = plan.task_requirement_refs[task.local_key]
            if not bindings or not keys(bindings) <= set(requirements):
                raise ValueError('Supply task omits original specific requirements')
            compatible = [requirements[r.key()] for r in bindings if same_product(task.target, requirements[r.key()].target)]
            if len(compatible) != 1:
                _needs('unambiguous_original_supply_task_requirement')
            req = compatible[0]
            target_map = assigned_outputs if req.purpose == 'order_output' else acquired_material
            target_map[req.ref.key()] = target_map.get(req.ref.key(), Fraction(0)) + target_quantity
            if target_map[req.ref.key()] > decimal_fraction(req.target.quantity.value):
                raise ValueError('Split tasks exceed original product/material demand')
            graph[task.local_key] = set(); keys(task.dependency_refs)
            keys([a.resource_ref for a in task.resources])
            if task.mode == 'purchase':
                if (task.planned_inputs or task.resources or method.material_inputs
                        or method.procurement_basis_ref is None or method.purchase_window_ref is None):
                    raise ValueError('Purchase method cannot generate manufacture inputs, capacity or own stock')
                evidence([method.procurement_basis_ref])
                window = read(method.purchase_window_ref, TimeWindow); clock(window.start); clock(window.end)
                if window.start.offset < now.offset:
                    raise ValueError('Planned upstream purchase window precedes original request')
                task_windows[task.local_key] = [window]
                continue
            if not task.resources or method.resource_kind is None or method.capacity_unit is None:
                _needs('explicit_original_manufacturing_resources_and_method')
            rate = decimal_fraction(_known(method.quantity_per_capacity_tick, 'sourced_supply_productivity'))
            evidence([method.productivity_basis_ref])
            if rate <= 0:
                raise ValueError('Manufacturing productivity must be positive')
            achievable = Fraction(0); windows = []
            for allocation in task.resources:
                original = read(allocation.resource_ref, SupplierPlanningResourceView, linked=True)
                if allocation.resource_ref.key() not in pools or original.resource_kind != method.resource_kind:
                    raise ValueError('Supply allocation substitutes actual original physical resource kind')
                if allocation.scope_ref != task.scope_ref:
                    raise ValueError('Supply allocation widens original task scope')
                q = quantity(allocation.quantity, method.capacity_unit)
                window = read(allocation.window_ref, TimeWindow); clock(window.start); clock(window.end)
                if window.bounds != 'closed_open' or window.start.offset < now.offset:
                    _unsupported('supply-planning-half-open-future-window')
                windows.append(window); achievable += q * rate * (window.end.offset - window.start.offset)
                demands.append(CapacityDemand(resource_kind=allocation.resource_ref.id, region_id=original.region_id,
                    unit=allocation.quantity.unit, amount=ExactAmount.from_fraction(q), window=window,
                    basis_refs=[allocation.quantity.basis_ref, method.productivity_basis_ref]))
            if achievable < target_quantity:
                _needs('supply_task_capacity_for_original_output_quantity')
            task_windows[task.local_key] = windows
            recipe = {row.product_ref.key():row for row in method.material_inputs}
            keys([row.product_ref for row in method.material_inputs]); keys([row.product_ref for row in task.planned_inputs])
            if keys([row.product_ref for row in task.planned_inputs]) != set(recipe):
                raise ValueError('Supply plan drops original method material recipe')
            for planned in task.planned_inputs:
                ingredient = recipe[planned.product_ref.key()]; evidence([ingredient.basis_ref])
                ratio = decimal_fraction(ingredient.quantity_per_output)
                required = quantity(planned.required, ingredient.unit)
                if ratio <= 0 or required != ratio * target_quantity:
                    raise ValueError('Planned inputs differ from original sourced recipe and target quantity')
                available = Fraction(0); keys(planned.available_allocation_refs)
                for ref in planned.available_allocation_refs:
                    if (ref.kind, ref.id) in used_allocations:
                        raise ValueError('Supply plan consumes one original input allocation twice')
                    row = read(ref, SupplierInventoryAllocationView)
                    if row.core_event_id in allocation_events:
                        raise ValueError('Supply plan aliases the same original stock allocation event')
                    if (row.organization_id != org or row.work_authority_ref != mandate.ref
                            or row.inventory_ref != inventory.ref or row.product_ref != planned.product_ref or row.status != 'reserved'):
                        raise ValueError('Planned input substitutes original actual inventory allocation')
                    if inventory.as_of != now or inventory.coverage != 'complete':
                        _needs('complete_current_actual_supply_inventory')
                    lots = [lot for lot in inventory.lots if lot.batch_ref == row.batch_ref]
                    if len(lots) != 1 or lots[0].status != 'usable' or lots[0].product_ref != row.product_ref:
                        _needs('actual_usable_original_supply_batch', [ref])
                    lot = lots[0]; q = quantity(row.quantity, ingredient.unit)
                    evidence([lot.actual.basis_ref, lot.committed.basis_ref])
                    if lot.actual.unit != ingredient.unit or lot.committed.unit != ingredient.unit:
                        raise ValueError('Input allocation changes original stock units')
                    batch = row.batch_ref.key(); allocated_stock[batch] = allocated_stock.get(batch, Fraction(0)) + q
                    if allocated_stock[batch] > min(decimal_fraction(lot.actual.value), decimal_fraction(lot.committed.value)):
                        raise ValueError('Planned allocations exceed actual original reserved stock')
                    used_allocations.add((ref.kind, ref.id)); allocation_events.add(row.core_event_id); available += q
                future = Fraction(0); keys(planned.acquisition_requirement_refs)
                for ref in planned.acquisition_requirement_refs:
                    if ref.key() not in requirements:
                        raise ValueError('Supply material acquisition uses an unknown original requirement')
                    acquisition = requirements[ref.key()]
                    if acquisition.purpose != 'material' or acquisition.target.product_ref != planned.product_ref:
                        raise ValueError('Supply acquisition requirement changes original ingredient')
                    q = quantity(acquisition.target.quantity, ingredient.unit)
                    future += q
                    future_requirements[ref.key()] = future_requirements.get(ref.key(), Fraction(0)) + q
                    if future_requirements[ref.key()] > q:
                        _needs('explicit_material_requirement_partitions_for_split_tasks', [ref])
                if available + future < required:
                    _needs('original_material_acquisition_requirement_for_task', [task.method_ref])
        if set(assigned_outputs) != set(outputs) or any(assigned_outputs[k] != decimal_fraction(req.target.quantity.value) for k,req in outputs.items()):
            raise ValueError('Supply plan must preserve complete original output demand across task partitions')
        for task in plan.tasks:
            required_acquisitions = {r.key() for row in task.planned_inputs for r in row.acquisition_requirement_refs}
            declared_acquisitions = set()
            for ref in task.dependency_refs:
                dependency = read(ref, SupplierPlanningDependencyView)
                if (dependency.plan_ref != plan.ref or dependency.dependent_task_key != task.local_key
                        or not keys(dependency.requirement_refs) <= set(requirements)):
                    raise ValueError('Supply plan replaces original task/material dependency')
                declared_acquisitions.update(keys(dependency.requirement_refs))
                for predecessor in dependency.predecessor_task_keys:
                    if predecessor not in task_keys or predecessor == task.local_key:
                        raise ValueError('Supply task omits or repeats original predecessor')
                    graph[task.local_key].add(predecessor)
                    before, after = task_windows[predecessor], task_windows[task.local_key]
                    if before and after and max(w.end.offset for w in before) > min(w.start.offset for w in after):
                        _needs('original_supply_predecessor_window_completion')
            if not required_acquisitions <= declared_acquisitions:
                raise ValueError('Supply task omits unresolved material acquisition dependencies')
        active = set(); visited = set()
        def visit(key):
            if key in active: raise ValueError('Supply task dependency cycle')
            if key not in visited:
                active.add(key)
                for predecessor in graph[key]:visit(predecessor)
                active.remove(key);visited.add(key)
        for key in task_keys:visit(key)
        if demands:
            result = reading.calculate(CAPACITY_METHOD, CapacityInput(clock_ref=now.clock_ref,
                demands=demands, resources=resources, commitments=commitments, source_refs=list(sources.values())))
            if result.kind != 'ok':
                if result.kind == 'invalid_input':
                    _unsupported('supplier-planning-capacity-method-domain')
                raw = result.model_dump(mode='python')
                if result.kind == 'needs_information':
                    raw['requested_refs'] = []
                raise ObservationGap(raw)
            if not result.value.feasible:
                _needs('original_concurrent_supply_capacity_for_plan')
        fields = {'tasks':[task.model_dump(mode='python') for task in plan.tasks]}
        if profile.choice == 'revise_plan': fields['prior_plan_ref'] = profile.prior_plan_ref
        return complete(profile.choice, **fields)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
