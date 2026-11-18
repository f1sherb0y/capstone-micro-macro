"""CONTRACTOR-A02 priced, bounded bid plans without resource locking."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, TimeWindow
from src.actions.contracts.contractor_bid_objects import (
    ContractorBidPackageView, ContractorBidDeliverableView, ContractorBidQuantityView,
    ContractorBidCostView, ContractorBidProgrammeView, ContractorBidMethodView,
    ContractorBidCapacityView, ContractorBidProfileView, ContractorBidReferenceView,
    ContractorBidResourceView, ContractorBidCommitmentView,
)
from src.actions.contracts.contractor_objects import QualificationView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, ExactAmount
from src.methods.contractor_bid import CONTRACTOR_BID_METHOD, ContractorPriceInput
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def prepare_bid(context, action_input, reading, *, profile_action_id='CONTRACTOR-A02'):
    now, sources = context.business_time, {}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('contractor-bid-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('contractor-bid-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not row.effective_window.contains(now): _needs('current_original_bid_evidence', [ref])
            sources[ref.key()] = ref

    def read(ref, schema, covered=True):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'contractor-bid-projection:{ref.kind}')
        if covered and hasattr(row, 'scope') and not scope_covers(row.scope, context.scope):
            raise ValueError('Bid input changes the original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at); clock(row.effective_window.start)
            if row.available_at.offset > now.offset or not row.effective_window.contains(now):
                _needs('current_received_original_bid_input', [ref])
        evidence(getattr(row, 'evidence_refs', [])); sources[ref.key()] = ref; return row

    def authorized(ref, actor, function, action, roles, organization=None):
        grant = read(ref, Authorization); assignment = read(function, RoleAssignment)
        if (grant.actor_id != actor or grant.function_ref != function or assignment.role not in roles
                or (organization is not None and grant.organization_id != organization)
                or action not in grant.action_ids or not any(scope_covers(s, context.scope) for s in grant.scopes)):
            raise ValueError('Original bid/technical input lacks independent author and scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(now): _needs('current_original_bid_authority')
        evidence([*grant.basis_refs, *assignment.basis_refs])

    def reference(ref):
        row = read(ref, ContractorBidReferenceView)
        if row.package_ref != package.ref or (row.organization_id is not None and row.organization_id != reading.organization_id):
            raise ValueError('Bid reference changes original package or organization')
        if not _known(row.allowed, 'original_bid_reference_permission'): _needs('original_bid_reference_permission', [ref])
        return row

    def technical(code):
        reading.recheck()
        return {'kind': 'technical_error', 'error': {'kind': 'unrecorded', 'correlation_id': context.operation_id,
                'code': code}, 'retryability': 'unknown'}

    def method_result(result, capability):
        if result.kind == 'ok': return result.value
        if result.kind == 'invalid_input': _unsupported(capability)
        raw = result.model_dump(mode='python')
        if result.kind == 'needs_information': raw['requested_refs'] = []
        raise ObservationGap(raw)

    try:
        package = read(action_input.package_ref, ContractorBidPackageView)
        profile = read(action_input.pricing_profile_ref, ContractorBidProfileView)
        capacity = read(action_input.capacity_ref, ContractorBidCapacityView)
        if (profile.organization_id != reading.organization_id or capacity.organization_id != reading.organization_id
                or profile.package_ref != package.ref or reading.organization_id not in package.recipient_organization_ids):
            raise ValueError('Bid facts belong to another contractor or original package')
        authorized(profile.authority_ref, context.actor_id, context.function_ref, profile_action_id, {'Contractor'}, reading.organization_id)
        if profile.choice == 'decline_bid':
            reading.recheck()
            return {'kind': 'completed', 'payload': {'choice': 'decline_bid', 'note': profile.decline_reason}}
        reference(package.round_ref)
        if package.status != 'open': _needs('original_package_open_for_bid_submission')
        submission_window = read(package.submission_window_ref, TimeWindow); clock(submission_window.start)
        if not submission_window.contains(now): _needs('original_bid_submission_window')
        for refs in (action_input.deliverable_refs, action_input.quantity_refs, action_input.cost_refs,
                     action_input.allowed_method_refs, package.deliverable_refs, package.quantity_refs, package.allowed_method_refs): unique_refs(refs)
        if (set(action_input.deliverable_refs) != set(package.deliverable_refs)
                or set(action_input.quantity_refs) != set(package.quantity_refs)):
            _needs('complete_current_package_deliverable_and_quantity_versions')
        if not set(action_input.allowed_method_refs) <= set(package.allowed_method_refs):
            raise ValueError('Bid adds a work method outside original procurement permission')
        for ref in action_input.deliverable_refs:
            row = read(ref, ContractorBidDeliverableView)
            if row.package_ref != package.ref or row.maturity not in package.permitted_maturities or 'procurement' not in row.allowed_uses:
                _needs('original_procurement_use_and_permitted_deliverable_maturity', [ref])
            role = {'ARCHITECT-A07': 'Architect', 'ENGINEER-A07': 'Engineer', 'QS-A05': 'QS'}[row.author_action_id]
            authorized(row.author_authority_ref, row.author_actor_id, row.author_function_ref, row.author_action_id, {role})
        clock(capacity.as_of)
        if capacity.as_of != now or capacity.coverage != 'complete' or capacity.qualification_coverage != 'complete':
            _needs('complete_current_original_contractor_capacity_and_qualifications')
        qualified = set(); unique_refs(capacity.qualification_refs)
        for ref in capacity.qualification_refs:
            row = read(ref, QualificationView)
            if row.organization_ref.id != reading.organization_id: raise ValueError('Bid qualification belongs to another organization')
            clock(row.effective_window.start)
            if (row.effective_window.contains(now) and _known(row.standing, 'original_qualification_standing')
                    and package.region_id in row.region_ids and package.work_type in row.work_types): qualified.add(row.qualification_code)
        if not set(package.required_qualification_codes) <= qualified:
            _needs('actual_bid_qualification_for_original_region_and_work')
        excluded = set(); unique_refs(profile.exclusion_refs)
        if not set(profile.exclusion_refs) <= set(package.allowed_exclusion_refs):
            raise ValueError('Bid exclusions remove unauthorized procurement scope')
        for ref in profile.exclusion_refs: excluded.update(reference(ref).excluded_coverage_keys)
        if excluded and not package.allow_limited_bid: _needs('original_procurement_permission_for_limited_bid')
        if not excluded <= set(package.coverage_keys): raise ValueError('Bid exclusion adds unrelated physical coverage')
        required = set(package.coverage_keys) - excluded
        if len(set(package.coverage_keys)) != len(package.coverage_keys) or not required:
            raise ValueError('Bid needs unique nonempty priced coverage')
        quantities, coverage = {}, set()
        for ref in action_input.quantity_refs:
            row = read(ref, ContractorBidQuantityView)
            if row.package_ref != package.ref or not set(row.deliverable_refs) <= set(action_input.deliverable_refs):
                raise ValueError('Quantity basis changes original package or permitted design versions')
            if row.status == 'failed': return technical('contractor_bid_quantity_failed')
            if row.status != 'ok': _unsupported('contractor-bid-quantity-method')
            reference(row.measurement_rule_ref)
            for line in row.lines:
                key = (ref.key(), line.local_key)
                if key in quantities or len(set(line.coverage_keys)) != len(line.coverage_keys):
                    raise ValueError('Bid repeats an original quantity line or physical coverage')
                if set(line.coverage_keys) <= excluded: continue
                if not set(line.coverage_keys) <= required or coverage.intersection(line.coverage_keys):
                    _needs('disjoint_original_included_quantity_coverage')
                quantity = _known(line.quantity, 'original_bid_quantity'); evidence([quantity.basis_ref])
                if decimal_fraction(quantity.value) <= 0: raise ValueError('Bid planned quantity must be positive')
                quantities[key] = (line, quantity); coverage.update(line.coverage_keys)
        if coverage != required: _needs('complete_original_included_quantity_scope')
        costs, lines = {}, []
        for ref in action_input.cost_refs:
            row = read(ref, ContractorBidCostView)
            authorized(row.author_authority_ref, row.author_actor_id, row.author_function_ref, 'CONTRACTOR-A02', {'Contractor'}, reading.organization_id)
            key = (row.quantity_basis_ref.key(), row.quantity_line_key)
            if row.organization_id != reading.organization_id or row.package_ref != package.ref or key not in quantities:
                raise ValueError('Bid cost changes original quantity, contractor or package')
            if key in costs: raise ValueError('Bid cost repeats an original priced quantity line')
            if row.status == 'failed': return technical('contractor_bid_cost_failed')
            if row.status != 'ok': _unsupported('contractor-bid-quantity-price-method')
            reference(row.method_ref)
            line, quantity = quantities[key]
            if row.region_id != package.region_id or set(row.coverage_keys) != set(line.coverage_keys):
                _needs('original_applicable_cost_region_and_included_scope')
            rate = _known(row.unit_rate, 'original_bid_unit_rate'); evidence([rate.basis_ref])
            if rate.currency != profile.currency: _unsupported('contractor-bid-currency-conversion')
            lines.append({'coverage_keys': line.coverage_keys, 'quantity': quantity,
                          'unit_rate': rate, 'quantity_unit': row.quantity_unit}); costs[key] = row
        if set(costs) != set(quantities): _needs('complete_original_priced_quantity_lines')
        programme = read(profile.programme_ref, ContractorBidProgrammeView)
        if (programme.package_ref != package.ref or programme.organization_id != reading.organization_id
                or set(programme.quantity_refs) != set(action_input.quantity_refs)):
            raise ValueError('Bid programme changes original package, contractor or quantity versions')
        authorized(programme.author_authority_ref, programme.author_actor_id, programme.author_function_ref, 'CONTRACTOR-A02', {'Contractor'}, reading.organization_id)
        if not programme.tasks or len({row.local_key for row in programme.tasks}) != len(programme.tasks):
            _needs('nonempty_distinct_original_bid_task_plan')
        methods, allocations, demands = {}, [], []
        planned_amounts = {}
        original_amounts = {key: decimal_fraction(quantity.value) for key, (_, quantity) in quantities.items()}
        resources = {row.resource_ref.key(): row for row in capacity.resources}
        if len(resources) != len(capacity.resources): raise ValueError('Bid calendar repeats a real resource version')
        unique_refs([row.resource_ref for row in capacity.resources]); unique_refs([row.commitment_ref for row in capacity.commitments])
        for row in capacity.resources:
            original = read(row.resource_ref, ContractorBidResourceView, covered=False)
            if (original.organization_id != reading.organization_id or original.resource_kind != row.resource_kind
                    or original.region_id != row.region_id or original.total != row.total):
                raise ValueError('Bid capacity duplicates or changes original physical resource')
            evidence([row.total.basis_ref])
        for row in capacity.commitments:
            original = read(row.commitment_ref, ContractorBidCommitmentView, covered=False)
            if (original.organization_id != reading.organization_id or original.resource_ref != row.resource_ref
                    or original.quantity != row.quantity or original.window != row.window or row.resource_ref.key() not in resources):
                raise ValueError('Bid calendar loses or changes original occupied physical resource')
            evidence([row.quantity.basis_ref])
        for task in programme.tasks:
            if not scope_covers(package.scope, task.scope_ref) or task.work_method_ref not in action_input.allowed_method_refs:
                raise ValueError('Bid task exceeds original scope or selected permitted method')
            method = methods.get(task.work_method_ref.key())
            if method is None:
                method = read(task.work_method_ref, ContractorBidMethodView); methods[method.ref.key()] = method
            if (package.region_id not in method.region_ids or package.object_type not in method.object_types
                    or package.work_type not in method.work_types or not set(package.special_condition_codes) <= set(method.special_condition_codes)
                    or not set(action_input.quantity_refs) <= set(method.output_quantity_basis_refs)):
                _unsupported('contractor-bid-work-method-object-region-special-condition-domain')
            rate = _known(method.quantity_per_capacity_tick, 'supported_bid_productivity')
            evidence([method.productivity_basis_ref])
            if decimal_fraction(rate) <= 0: _unsupported('contractor-bid-productivity-domain')
            window = read(task.window_ref, TimeWindow); clock(window.start)
            ticks = window.end.offset - window.start.offset
            if window.bounds != 'closed_open' or ticks <= 0 or window.start.offset < now.offset:
                _unsupported('contractor-bid-future-half-open-work-window')
            unique_refs(task.dependency_refs)
            for ref in task.dependency_refs: reference(ref)
            if not task.target_quantities or not task.allocations or len(task.quantity_sources) != len(task.target_quantities):
                _needs('original_bid_task_target_and_resource_plan')
            target_total = Fraction()
            for target, quantity in zip(task.quantity_sources, task.target_quantities):
                key = (target.quantity_basis_ref.key(), target.quantity_line_key)
                if key not in quantities or quantity.unit != quantities[key][1].unit:
                    raise ValueError('Bid task target changes original physical quantity line or unit')
                evidence([quantity.basis_ref])
                if quantity.unit != method.quantity_unit or decimal_fraction(quantity.value) <= 0:
                    _unsupported('contractor-bid-target-unit-or-conversion')
                target_total += decimal_fraction(quantity.value)
                planned_amounts[key] = planned_amounts.get(key, Fraction()) + decimal_fraction(quantity.value)
            available = Fraction()
            seen = set()
            for allocation in task.allocations:
                resource = resources.get(allocation.resource_ref.key())
                if (resource is None or resource.resource_kind != method.resource_kind or resource.region_id != package.region_id
                        or allocation.resource_ref.key() in seen or allocation.task_scope_ref != task.scope_ref or allocation.window_ref != task.window_ref):
                    raise ValueError('Bid allocation duplicates or changes original task/resource/location/window')
                seen.add(allocation.resource_ref.key()); evidence([allocation.quantity.basis_ref])
                if allocation.quantity.unit != method.capacity_unit or resource.total.unit != method.capacity_unit:
                    _unsupported('contractor-bid-resource-unit-conversion')
                amount = decimal_fraction(allocation.quantity.value)
                if amount <= 0: raise ValueError('Proposed bid resource amount must be positive')
                available += amount
                # Each physical resource is checked independently against ALL proposed tasks and original occupancy.
                allocations.append(allocation)
                demands.append((resource, {'resource_kind': method.resource_kind, 'region_id': package.region_id,
                    'unit': method.capacity_unit, 'amount': ExactAmount.from_fraction(amount), 'window': window,
                    'basis_refs': [allocation.quantity.basis_ref]}))
            if target_total > available * decimal_fraction(rate) * ticks:
                _needs('supported_original_work_quantity_productivity_and_programme_window')
        if planned_amounts != original_amounts: _needs('bid_plan_covers_exact_original_included_quantities')
        for resource_key, resource in resources.items():
            selected = [d for r, d in demands if r.resource_ref.key() == resource_key]
            if not selected: continue
            commitments = [r for r in capacity.commitments if r.resource_ref.key() == resource_key]
            result = reading.calculate(CAPACITY_METHOD, CapacityInput(clock_ref=now.clock_ref, demands=selected,
                resources=[resource], commitments=commitments, source_refs=list(sources.values())))
            report = method_result(result, 'contractor-bid-capacity-domain')
            if not report.feasible: _needs('original_crew_capacity_for_proposed_bid_programme')
        reference(profile.terms_ref)
        validity = read(profile.validity_ref, TimeWindow); clock(validity.start)
        if not validity.contains(now): _needs('valid_original_bid_offer_window')
        evidence([profile.markup_basis_ref, profile.commercial_allowance.basis_ref])
        if profile.commercial_allowance.currency != profile.currency: _unsupported('contractor-bid-commercial-allowance-currency')
        result = reading.calculate(CONTRACTOR_BID_METHOD, ContractorPriceInput(lines=lines,
            markup_fraction=profile.markup_fraction, markup_basis_ref=profile.markup_basis_ref,
            allowance=profile.commercial_allowance, source_refs=list(sources.values())))
        price = method_result(result, 'contractor-bid-pricing-domain').offered_price
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': 'submit_bid',
            'note': 'Original-version priced proposal and planned tasks only; internal cost differs from commercial price; crews unreserved, no construction release or actual work',
            'bid': {'package_ref': package.ref, 'scope_ref': package.scope, 'price': price, 'cost_basis_refs': action_input.cost_refs,
                'programme_ref': programme.ref, 'terms_ref': profile.terms_ref, 'exclusion_refs': profile.exclusion_refs,
                'validity_ref': profile.validity_ref,
                'proposed_resources': [allocation.model_dump(mode='python') for allocation in allocations]},
                'planned_tasks': [task.model_dump(exclude={'quantity_sources'}) for task in programme.tasks]}}
    except ObservationGap as gap:
        reading.recheck(); return gap.result
