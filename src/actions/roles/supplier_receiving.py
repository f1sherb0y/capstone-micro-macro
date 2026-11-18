"""SUPPLIER-A09 responds to independent receiving facts without posting stock."""
from fractions import Fraction
from collections import deque

from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.supplier_receiving_objects import (
    SupplierReceivingShipmentView, SupplierDeliveryResponseProfileView, SupplierArrivalEvidenceView,
    SupplierReceivingPartyView, SupplierCustomerReceiptView, SupplierReceiptComponentView,
    SupplierReceivingMandateView,
    SupplierReceiptInspectionView, SupplierGoodsInspectionMethodView, SupplierGoodsUseReleaseView,
    SupplierDeliveryDiscrepancyView, SupplierDeliverySupplementView, SupplierDeliveryReplacementView,
    SupplierReplacementRequirementView, SupplierReplacementDeviationView,
    SupplierPlanningProductView, SupplierLogisticsOrderView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def _check_receipt_arrival_capacity(arrival_quantities, receipt_quantities, *,
        inspection_limits=None, required_quantity=None):
    """Check aggregate physical quantities against each receipt's source links.

    Exact flow feasibility handles overlapping sets of referenced arrivals.
    It produces no allocation or stock effect, and does not assume how a receipt
    splits its quantity between several arrivals. Unreferenced arrivals cannot
    cover a receipt, and each arrival's quantity can be counted only once.
    Callers may restrict source links to arrivals that had actually occurred
    at the relevant author time. An inspection can cover only part of the
    selected receipts. Optional inspection limits maximize coverage available
    at its author time while still satisfying every receipt. This prevents
    borrowing an early arrival already required by another receipt, without
    inventing a split between the selected received components.
    """
    source, sink = 0, 1
    residual = {source: {}, sink: {}}
    costs = {source: {}, sink: {}}
    arrival_nodes = {key: index + 2 + len(receipt_quantities)
        for index, key in enumerate(arrival_quantities)}

    def edge(start, end, quantity, cost=0):
        residual.setdefault(start, {})[end] = quantity
        residual.setdefault(end, {})[start] = Fraction(0)
        costs.setdefault(start, {})[end] = cost
        costs.setdefault(end, {})[start] = -cost

    if (inspection_limits is None) != (required_quantity is None):
        raise ValueError('Inspection coverage requires explicit source limits and quantity together')
    if inspection_limits is not None and (len(inspection_limits) != len(receipt_quantities)
            or required_quantity < 0):
        raise ValueError('Inspection source limits must cover the exact original receipts')

    total = Fraction(0)
    for index, (refs, quantity) in enumerate(receipt_quantities):
        node = index + 2
        total += quantity
        edge(source, node, quantity)
        for key in refs:
            edge(node, arrival_nodes[key], quantity)
        if inspection_limits is not None:
            inspection_refs, inspection_quantity = inspection_limits[index]
            if inspection_quantity < 0:
                raise ValueError('Inspection source capacity cannot be negative')
            inspection_node = index + 2 + len(receipt_quantities) + len(arrival_quantities)
            # Negative cost selects as much early, selected-component coverage
            # as possible within the complete physical receipt allocation.
            edge(node, inspection_node, inspection_quantity, -1)
            for key in refs & inspection_refs:
                edge(inspection_node, arrival_nodes[key], inspection_quantity)
    for key, quantity in arrival_quantities.items():
        edge(arrival_nodes[key], sink, quantity)

    covered = Fraction(0)
    inspected = Fraction(0)
    while covered < total:
        parents = {source: None}
        distances = {source: 0}
        pending = deque([source])
        queued = {source}
        while pending:
            node = pending.popleft()
            queued.remove(node)
            for following, quantity in residual[node].items():
                distance = distances[node] + costs[node][following]
                if quantity > 0 and (following not in distances or distance < distances[following]):
                    distances[following] = distance
                    parents[following] = node
                    if following not in queued:
                        pending.append(following)
                        queued.add(following)
        if sink not in parents:
            raise ValueError('Receipt quantities exceed their linked actual arrivals or count the same arrival twice')
        quantity = total - covered
        node = sink
        while parents[node] is not None:
            previous = parents[node]
            quantity = min(quantity, residual[previous][node])
            node = previous
        node = sink
        while parents[node] is not None:
            previous = parents[node]
            residual[previous][node] -= quantity
            residual[node][previous] += quantity
            node = previous
        covered += quantity
        inspected -= quantity * distances[sink]
    if required_quantity is not None and inspected < required_quantity:
        raise ValueError('Inspection coverage exceeds its linked arrivals at the original inspection time')


def respond_to_receiving(context, action_input, reading):
    now, org, scope = context.business_time, reading.organization_id, context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:_unsupported('supplier-receiving-clock-alignment')

    def evidence(refs, *, at=None, historic=False):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset:_needs('received_original_receiving_evidence_time')
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row,EvidenceRecord):_unsupported('supplier-receiving-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if row.effective_window.start.offset > now.offset:_needs('received_original_receiving_evidence',[ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_receiving_evidence_valid_at_use',[ref])

    def read(ref,schema,historic=False,linked=False,*,at=None,evidence_at_field=None):
        row = reading.resolve(ref)
        if not isinstance(row,schema):_unsupported('supplier-receiving-projection:' + ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Receiving source expands original authorized shipment scope')
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:_needs('received_original_receiving_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now):_needs('current_original_receiving_source',[ref])
        point = at if evidence_at_field is None else getattr(row,evidence_at_field)
        if point is not None:
            clock(point)
            if point.offset > now.offset:_needs('received_original_receiving_evidence_time',[ref])
            if evidence_at_field is not None and point.offset > row.available_at.offset:
                raise ValueError('Receiving source precedes its actual original event or authorship')
        evidence(getattr(row,'evidence_refs',[]),at=point,historic=historic)
        return row

    def true(value):return isinstance(value,Known) and value.value is True

    def q(value,positive=False,*,at=None,historic=False):
        evidence([value.basis_ref],at=at,historic=historic);amount = decimal_fraction(value.value)
        if value.unit != shipment.plan.quantity.unit or amount < 0 or positive and amount == 0:
            raise ValueError('Receiving quantity changes original shipment units or actual positive amount')
        return amount

    def authorize(ref,actor,function,organization,action,at,target):
        grant = read(ref,Authorization,historic=True,linked=True)
        assignment = read(function,RoleAssignment,historic=True,linked=True)
        roles = {'SUPPLIER':'Supplier','CONTRACTOR':'Contractor','OWN':'Owner','ENGINEER':'Engineer','GOV':'Government','QS':'QS','ARCHITECT':'Architect'}
        if (grant.actor_id != actor or grant.organization_id != organization or grant.function_ref != function
                or assignment.function_ref != function or assignment.role != roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Receiving record substitutes actual independent author/function/scope authority')
        clock(at);clock(grant.validity.start)
        if at.offset > now.offset:_needs('received_original_receiving_author_time',[ref])
        if not grant.validity.contains(at):_needs('original_receiving_authority_at_execution',[ref])
        for ref in [*grant.basis_refs,*assignment.basis_refs]:
            if ref.kind == 'Evidence':evidence([ref],at=at)
            else:reading.resolve(ref)

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Receiving source precedes original actual author execution')
        authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,row.author_organization_id,
            row.author_action_id,row.authored_at,row.scope)

    def receiver(row,purpose):
        author(row)
        if row.receiving_party_ref.key() not in parties:_needs('original_independent_receiving_party_record',[row.ref])
        party = parties[row.receiving_party_ref.key()]
        mandate = mandates[party.ref.key()]
        if (party.organization_id == org or party.order_ref != order.ref or party.destination_ref != shipment.plan.destination_ref
                or purpose not in party.allowed_purposes or not true(party.permitted)
                or row.author_actor_id != party.actor_id or row.author_organization_id != party.organization_id
                or row.author_function_ref != party.function_ref or row.author_authority_ref != party.authority_ref
                or row.author_action_id not in party.allowed_action_ids or not scope_covers(party.scope,row.scope)
                or mandate.authored_at.offset > row.authored_at.offset
                or not party.effective_window.contains(row.authored_at) or not mandate.effective_window.contains(row.authored_at)):
            raise ValueError('Supplier cannot replace actual authorized receiver/inspector/use-release author')
        evidence(party.evidence_refs,at=row.authored_at)

    def complete(choice,**fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':choice,**fields,'note':profile.note +
            ' Supplier response/proposal only. Acknowledging independent facts signs no customer receipt. Arrival, physical receipt, quarantine, inspection and authorized uses remain separate; duplicate facts create no stock, cash or completed work.'}}

    def wait(code,refs):
        reading.recheck()
        return {'kind':'deferred','reason_code':code,'resume_condition':{'trigger':'dependency_change',
            'object_refs':refs,'earliest_time':None,'condition_code':code}}

    try:
        shipment = read(action_input.shipment_ref,SupplierReceivingShipmentView,historic=True,linked=True)
        profile = read(shipment.response_profile_ref,SupplierDeliveryResponseProfileView)
        order = read(shipment.order_ref,SupplierLogisticsOrderView,historic=True,linked=True)
        if (shipment.organization_id != org or shipment.run_id != context.run_id or order.supplier_id != org
                or profile.shipment_ref != shipment.ref or profile.organization_id != org
                or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
                or profile.scope != scope or not scope_covers(order.scope,scope)
                or profile.authority_ref not in context.authorization_refs or content_digest(shipment.plan) != shipment.request_sha256):
            raise ValueError('Receiving response replaces original shipment, order, actor or request identity')
        authorize(profile.authority_ref,context.actor_id,context.function_ref,org,'SUPPLIER-A09',now,scope)
        clock(shipment.as_of)
        if shipment.history_coverage != 'complete' or shipment.as_of != now:
            _needs('complete_current_original_shipment_receiving_history')
        for field in ('arrival_refs','receipt_refs','inspection_refs','discrepancy_refs','receiving_party_refs'):
            if keys(getattr(action_input,field)) != keys(getattr(shipment,field)):
                _needs('complete_original_receiving_' + field)
        if shipment.status == 'submitted_unknown' or shipment.query_status in {'unknown','not_queried'}:
            return wait('query_original_shipment_before_receiving_response',[shipment.ref])
        if shipment.status in {'dispatched','in_transit','arrived','received'} and (
                shipment.dispatched_at is None or shipment.core_event_id is None or shipment.query_status != 'present'):
            raise ValueError('Receiving history lacks its actual original dispatch event and time')
        if shipment.dispatched_at is not None:
            clock(shipment.dispatched_at)
            if shipment.dispatched_at.offset > shipment.available_at.offset:
                raise ValueError('Receiving shipment source precedes its actual original dispatch')
        shipped_quantity = q(shipment.plan.quantity,at=shipment.dispatched_at,historic=True)
        parties = {ref.key():read(ref,SupplierReceivingPartyView,historic=True,linked=True) for ref in action_input.receiving_party_refs}
        mandates = {}
        for party in parties.values():
            mandate = read(party.mandate_ref,SupplierReceivingMandateView,historic=True,linked=True,evidence_at_field='authored_at');author(mandate)
            if (party.organization_id == org or party.order_ref != order.ref or mandate.order_ref != order.ref
                    or mandate.author_organization_id != order.buyer_id or mandate.receiving_party_ref != party.ref
                    or mandate.recipient_organization_id != party.organization_id or not true(mandate.permitted)
                    or not set(party.allowed_purposes) <= set(mandate.allowed_purposes)):
                raise ValueError('Receiving party substitutes original actual buyer')
            mandates[party.ref.key()] = mandate

        arrivals = {};arrival_events = set();actual_arrived = Fraction(0);arrival_quantities = {}
        for ref in action_input.arrival_refs:
            row = read(ref,SupplierArrivalEvidenceView,historic=True,linked=True,evidence_at_field='arrived_at');clock(row.arrived_at)
            if (row.shipment_ref != shipment.ref or row.physical_batch_key != shipment.physical_batch_key
                    or row.destination_ref != shipment.plan.destination_ref or row.arrived_at.offset > now.offset
                    or row.arrived_at.offset > row.available_at.offset
                    or row.core_event_id in arrival_events or shipment.dispatched_at is None):
                raise ValueError('Arrival source repeats or substitutes original actual shipment/location/event')
            clock(shipment.dispatched_at)
            if row.arrived_at.offset < shipment.dispatched_at.offset:
                raise ValueError('Arrival precedes original physical dispatch')
            amount = q(row.quantity,positive=True,at=row.arrived_at)
            arrival_events.add(row.core_event_id);actual_arrived += amount;arrivals[ref.key()] = row
            arrival_quantities[ref.key()] = amount
        if actual_arrived > shipped_quantity:raise ValueError('Partial arrivals repeat or exceed original physical shipped amount')

        receipts = {};components = {};commands = set();business = set();events = set();slices = set();received_total = Fraction(0);expected_total = Fraction(0)
        receipt_quantities = []
        for ref in action_input.receipt_refs:
            row = read(ref,SupplierCustomerReceiptView,historic=True,linked=True,evidence_at_field='authored_at');receiver(row,'receipt')
            if (row.shipment_ref != shipment.ref or row.command_id in commands or row.business_key in business
                    or row.core_event_id in events or not keys(row.arrival_refs) <= set(arrivals)):
                raise ValueError('Goods receipt repeats original command/event or substitutes original actual arrivals')
            commands.add(row.command_id);business.add(row.business_key);events.add(row.core_event_id);keys(row.component_refs)
            if row.status == 'recorded' and (not row.arrival_refs or not row.component_refs):
                raise ValueError('Recorded receipt requires actual arrival and original itemized facts')
            receipt_quantity = Fraction(0)
            for component_ref in row.component_refs:
                component = read(component_ref,SupplierReceiptComponentView,historic=True,linked=True)
                if (component.shipment_ref != shipment.ref or component.receipt_ref != row.ref
                        or component.physical_slice_key in slices or component_ref.key() in components):
                    raise ValueError('Receipt components repeat original physical slice or substitute shipment/receipt')
                slices.add(component.physical_slice_key)
                # Components can include later inspection/use updates and
                # have no per-field actual occurrence timestamps.
                expected = q(component.expected_quantity,historic=True);received = q(component.received_quantity,historic=True)
                damaged = q(component.damaged_quantity,historic=True);rejected = q(component.rejected_quantity,historic=True)
                quarantined = q(component.quarantined_quantity,historic=True);usable = q(component.usable_quantity,historic=True)
                if damaged > received or rejected + quarantined + usable > received:
                    raise ValueError('Receipt quality quantities exceed original actual received physical scope')
                if not true(component.specification_matches) and usable > 0:
                    raise ValueError('Unapproved or unknown replacement specification cannot become usable original stock')
                if row.status != 'recorded' and usable > 0:
                    raise ValueError('Pending/rejected/unknown receipt cannot create recognized usable inventory')
                received_total += received;expected_total += expected;receipt_quantity += received
                components[component_ref.key()] = component
            receipts[ref.key()] = row
            # A later actual arrival must not cover an earlier receipt. Keep
            # overlapping source sets for the shared exact-flow check below.
            arrived_refs = {r.key() for r in row.arrival_refs
                if arrivals[r.key()].arrived_at.offset <= row.authored_at.offset}
            receipt_quantities.append((arrived_refs, receipt_quantity))
        if received_total > actual_arrived or expected_total > shipped_quantity:
            raise ValueError('Partial receipts repeat actual arrived or originally shipped scope')
        _check_receipt_arrival_capacity(arrival_quantities, receipt_quantities)

        inspections = {}
        for ref in action_input.inspection_refs:
            row = read(ref,SupplierReceiptInspectionView,historic=True,linked=True,evidence_at_field='authored_at');receiver(row,'inspection')
            if row.shipment_ref != shipment.ref or not row.component_refs or not keys(row.component_refs) <= set(components):
                raise ValueError('Goods inspection replaces original received physical components')
            method = read(row.method_ref,SupplierGoodsInspectionMethodView,historic=True,linked=True,at=row.authored_at)
            # A late-delivered inspection can remain historical evidence, but
            # a method first available later cannot support that earlier act.
            if (method.available_at.clock_ref != row.authored_at.clock_ref
                    or method.effective_window.start.clock_ref != row.authored_at.clock_ref
                    or method.effective_window.end.clock_ref != row.authored_at.clock_ref
                    or method.available_at.offset > row.authored_at.offset
                    or not method.effective_window.contains(row.authored_at)
                    or not scope_covers(method.scope, row.scope)):
                raise ValueError('Goods inspection method was unavailable, invalid or outside its original inspection scope')
            if row.status == 'ok' and true(row.passed) and (not true(method.supported) or row.author_action_id not in method.allowed_author_action_ids):
                _unsupported('original_received_goods_inspection_method_support')
            if not set(row.use_codes) <= set(method.use_codes):raise ValueError('Inspection widens original supported product use')
            if not {components[r.key()].product_ref.key() for r in row.component_refs} <= keys(method.product_refs):
                raise ValueError('Inspection method does not support actual received product versions')
            if q(row.covered_quantity,at=row.authored_at) > sum((q(components[r.key()].received_quantity,historic=True) for r in row.component_refs),Fraction(0)):
                raise ValueError('Inspection covers more than original actual received quantity')
            selected_quantities = {}
            for component_ref in row.component_refs:
                component = components[component_ref.key()]
                key = component.receipt_ref.key()
                selected_quantities[key] = selected_quantities.get(key,Fraction(0)) + q(component.received_quantity,historic=True)
            inspection_limits = [({r.key() for r in receipt.arrival_refs
                if arrivals[r.key()].arrived_at.offset <= row.authored_at.offset},
                selected_quantities.get(receipt.ref.key(),Fraction(0))) for receipt in receipts.values()]
            _check_receipt_arrival_capacity(arrival_quantities, receipt_quantities,
                inspection_limits=inspection_limits, required_quantity=q(row.covered_quantity,at=row.authored_at))
            inspections[ref.key()] = row
        release_events = set();per_inspection = {}
        for component in components.values():
            if not keys(component.inspection_refs) <= set(inspections):
                _needs('complete_original_component_inspection_records',[component.ref])
            released = Fraction(0)
            keys(component.use_release_refs)
            for ref in component.use_release_refs:
                release = read(ref,SupplierGoodsUseReleaseView,historic=True,linked=True,evidence_at_field='authored_at');receiver(release,'use_release')
                if (release.shipment_ref != shipment.ref or release.component_ref != component.ref
                        or release.inspection_ref.key() not in keys(component.inspection_refs)
                        or release.core_event_id in release_events or not true(release.permitted)):
                    raise ValueError('Use release repeats original core effect or substitutes actual receipt/inspection scope')
                inspection = inspections[release.inspection_ref.key()]
                if (inspection.status != 'ok' or not true(inspection.passed) or component.ref.key() not in keys(inspection.component_refs)
                        or not release.use_codes or not set(release.use_codes) <= set(inspection.use_codes)
                        or release.authored_at.offset < inspection.authored_at.offset):
                    raise ValueError('Use release precedes or widens original actually passed inspection and uses')
                amount = q(release.quantity,positive=True,at=release.authored_at);released += amount;release_events.add(release.core_event_id)
                key = inspection.ref.key();per_inspection[key] = per_inspection.get(key,Fraction(0)) + amount
                if per_inspection[key] > q(inspection.covered_quantity,at=inspection.authored_at):raise ValueError('Use release repeats the same inspected quantity')
            if released != q(component.usable_quantity,historic=True):
                raise ValueError('Original usable goods quantity differs from authorized actual scoped releases')

        issues = {}
        for ref in action_input.discrepancy_refs:
            row = read(ref,SupplierDeliveryDiscrepancyView,historic=True,linked=True,evidence_at_field='authored_at');author(row)
            if row.shipment_ref != shipment.ref or not keys(row.component_refs) <= set(components):
                raise ValueError('Delivery discrepancy substitutes original shipment or received component facts')
            if row.author_organization_id != org and not any(p.organization_id == row.author_organization_id
                    and p.actor_id == row.author_actor_id and p.function_ref == row.author_function_ref
                    and p.authority_ref == row.author_authority_ref and row.author_action_id in p.allowed_action_ids
                    for p in parties.values()):
                raise ValueError('Delivery discrepancy substitutes an unrelated original issuer')
            issues[ref.key()] = row

        if profile.choice == 'acknowledge_receipt':
            if profile.receipt_ref is None or profile.receipt_ref.key() not in receipts or not profile.accepted_fact_refs:
                _needs('original_received_customer_receipt_and_selected_fact_components')
            receipt = receipts[profile.receipt_ref.key()]
            if receipt.status != 'recorded' or not keys(profile.accepted_fact_refs) <= keys(receipt.component_refs):
                _needs('recorded_original_customer_receipt_fact_components',[receipt.ref])
            return complete('acknowledge_receipt',receipt_ref=receipt.ref,accepted_fact_refs=profile.accepted_fact_refs)

        if profile.choice in {'supplement_evidence','contest_discrepancy'}:
            if profile.supplement_ref is None:_needs('original_problem_linked_delivery_supplement')
            supplement = read(profile.supplement_ref,SupplierDeliverySupplementView,evidence_at_field='authored_at');author(supplement)
            if (supplement.shipment_ref != shipment.ref or supplement.author_organization_id != org
                    or supplement.author_action_id != 'SUPPLIER-A09' or not supplement.attachment_refs
                    or supplement.purpose != ('supplement' if profile.choice == 'supplement_evidence' else 'contest')
                    or not keys(supplement.discrepancy_refs) <= set(issues)
                    or not keys(supplement.receipt_component_refs) <= set(components)
                    or keys(supplement.attachment_refs) != keys(profile.evidence_refs_received)):
                raise ValueError('Supplier supplement replaces original author/shipment/problem or attachments')
            evidence(supplement.attachment_refs)
            if profile.choice == 'supplement_evidence':
                return complete('supplement_evidence',evidence_refs=supplement.attachment_refs)
            if not profile.component_refs or keys(profile.component_refs) != keys(supplement.receipt_component_refs):
                raise ValueError('Contested receipt components differ from original problem-linked supplement')
            affected = {r.key() for key in keys(supplement.discrepancy_refs) for r in issues[key].component_refs if issues[key].status != 'resolved'}
            if not keys(profile.component_refs) <= affected:_needs('original_unresolved_component_specific_delivery_discrepancy')
            return complete('contest_discrepancy',component_refs=profile.component_refs,evidence_refs=supplement.attachment_refs)

        if profile.choice != 'propose_replacement' or profile.issue_ref is None or profile.issue_ref.key() not in issues or profile.replacement_ref is None:
            _needs('original_delivery_discrepancy_and_replacement_proposal')
        issue = issues[profile.issue_ref.key()];clock(issue.as_of)
        if issue.status == 'resolved' or issue.as_of != now or not issue.replacement_history_complete:
            _needs('current_original_unresolved_delivery_issue_and_replacement_history')
        proposal = read(profile.replacement_ref,SupplierDeliveryReplacementView,evidence_at_field='authored_at');author(proposal)
        if (proposal.shipment_ref != shipment.ref or proposal.discrepancy_ref != issue.ref or proposal.author_organization_id != org
                or proposal.author_action_id != 'SUPPLIER-A09' or proposal.status != 'proposal' or not proposal.lines):
            raise ValueError('Replacement proposal substitutes original shipment/issue or actual supplier author')
        prior_keys = set();keys(issue.replacement_proposal_refs)
        for ref in issue.replacement_proposal_refs:
            previous = read(ref,SupplierDeliveryReplacementView,historic=True,linked=True,evidence_at_field='authored_at');author(previous)
            if (previous.discrepancy_ref != issue.ref or previous.shipment_ref != shipment.ref
                    or previous.author_organization_id != org or previous.business_key in prior_keys):
                raise ValueError('Replacement history repeats or substitutes original problem/business identity')
            prior_keys.add(previous.business_key)
            if previous.business_key == proposal.business_key:
                if previous.lines != proposal.lines:raise ValueError('Existing replacement proposal changes original business content')
                return wait('continue_original_delivery_replacement_proposal',[previous.ref])
        total = Fraction(0)
        affected_products = {components[r.key()].product_ref.key() for r in issue.component_refs}
        for line in proposal.lines:
            spec = read(line.product_ref,SupplierPlanningProductView,linked=True)
            if not scope_covers(scope,line.destination_scope_ref) or line.quantity.unit != spec.quantity_unit or not line.requirement_refs:
                raise ValueError('Replacement proposal changes original destination/units or omits concrete specifications')
            total += q(line.quantity,positive=True);keys(line.requirement_refs);keys(line.deviation_refs)
            for ref in line.requirement_refs:
                req = read(ref,SupplierReplacementRequirementView)
                if req.discrepancy_ref != issue.ref or line.product_ref.key() not in keys(req.product_refs):
                    raise ValueError('Replacement requirements replace original problem or product version')
            if line.product_ref.key() not in affected_products and not line.deviation_refs:
                _needs('explicit_original_replacement_specification_deviation_proposal')
            for ref in line.deviation_refs:
                deviation = read(ref,SupplierReplacementDeviationView,evidence_at_field='authored_at');author(deviation)
                if (deviation.discrepancy_ref != issue.ref or deviation.product_ref != line.product_ref
                        or deviation.status == 'rejected' or not keys(deviation.requirement_refs) <= keys(line.requirement_refs)):
                    raise ValueError('Replacement deviation changes original problem or product requirements')
        remaining = q(issue.replacement_remaining,positive=True)
        if issue.component_refs:
            unresolved = sum((max(Fraction(0),q(components[r.key()].expected_quantity,historic=True)-q(components[r.key()].usable_quantity,historic=True))
                for r in issue.component_refs),Fraction(0))
            if remaining > unresolved:raise ValueError('Replacement issue quantity exceeds original unresolved receipt components')
        if total > remaining:raise ValueError('Replacement proposal exceeds original remaining issue quantity')
        return complete('propose_replacement',issue_ref=issue.ref,replacement_lines=[line.model_dump(mode='python') for line in proposal.lines])
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
