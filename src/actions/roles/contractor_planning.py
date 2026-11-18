"""CONTRACTOR-A05 plans within a mandate; own supply acceptance is not fulfillment."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, TimeWindow, walk_references
from src.actions.contracts.contractor_planning_objects import (
    ContractorWorkMandateView, ContractorWorkPlanView, ContractorPlanningProfileView,
    ContractorPlanDependencyView, ContractorPlanDesignView, ContractorSupplyRequirementView,
    ContractorSupplyOfferView, ContractorSupplyTermsView, ContractorProcurementAuthorityView,
    ContractorSupplyReferenceView, ContractorSupplySupplierView, ContractorSupplyCommitmentView,
    ContractorBidCapacityView, ContractorBidResourceView, ContractorBidCommitmentView, ContractorBidMethodView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.contractor_objects import QualificationView
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, CapacityReport, ExactAmount, compare_capacity
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def recheck_original_contractor_supply_wait(context, action_input, reading, *,
        condition_code='contractor-plan-existing-supply-commitment-query-original-order'):
    """Authenticate original quote/purchase waits, which never call capacity."""
    if condition_code not in {'contractor-plan-existing-supply-commitment-query-original-order',
            'contractor-plan-original-preparation-or-contract-procurement-limit',
            'contractor-plan-no-current-supply-inquiry-recipient'}:
        raise ValueError('Historical supply check requires an actual original quote/purchase wait')
    basis = action_input.work_basis
    ref = basis.contract_ref if basis.kind == 'contract' else basis.authorization_ref
    mandate = reading.resolve(ref)
    if not isinstance(mandate, ContractorWorkMandateView):
        raise ValueError('Historical supply wait requires its original typed work mandate')
    profile = reading.resolve(mandate.planning_profile_ref)
    choice = ('request_quote' if condition_code == 'contractor-plan-no-current-supply-inquiry-recipient'
        else 'accept_supply_offer')
    if not isinstance(profile, ContractorPlanningProfileView) or profile.choice != choice:
        raise ValueError('Historical supply wait cannot execute the work-plan capacity branch')
    result = plan_work_and_supply(context, action_input, reading)
    if (result.get('kind') != 'deferred'
            or result.get('reason_code') != condition_code):
        raise ValueError('Historical supply sources do not reproduce the original commitment query')
    return result


def plan_work_and_supply(context, action_input, reading):
    return _plan_work_and_supply(context, action_input, reading)


def recheck_original_contractor_plan_cycle(context, action_input, reading):
    """Reproduce the original cycle gate; never reach capacity or make a plan."""
    result = _plan_work_and_supply(context, action_input, reading, original_cycle_only=True)
    if (result.get('kind') != 'deferred' or result.get('reason_code') !=
            'contractor-plan-circular-dependency-requires-responsible-party-resolution'):
        raise ValueError('Original plan sources do not reproduce the original dependency cycle')
    return result


def recheck_original_contractor_plan_capacity(context, action_input, reading):
    """Reproduce old capacity using authenticated fixed pure arithmetic only.

    Current read grants protect old sources. Comparisons do not impersonate an
    old method invocation, append method records or create a successful plan.
    """
    reading.check_method_context(reading._context, 'CONTRACTOR-A05')
    binding = reading._methods._bindings.get(CAPACITY_METHOD.key()) if reading._methods is not None else None
    if (CAPACITY_METHOD.key() not in reading._method_refs or binding is None
            or binding.executor is not compare_capacity or binding.input_model is not CapacityInput
            or binding.output_model is not CapacityReport or 'CONTRACTOR-A05' not in binding.definition.action_ids
            or binding.definition.effect_kind != 'pure_calculation'):
        raise ValueError('Historical capacity check requires the original declared pure capacity method')
    comparisons = []
    result = _plan_work_and_supply(context, action_input, reading, historical_capacity=comparisons)
    if (result.get('kind') != 'deferred' or result.get('reason_code') !=
            'contractor-plan-shared-resource-capacity-conflict'):
        raise ValueError('Original plan sources do not reproduce the original shared capacity wait')
    return result, comparisons


def _plan_work_and_supply(context, action_input, reading, *, original_cycle_only=False, historical_capacity=None):
    now, scope, org = context.business_time, action_input.authorized_scope_ref, reading.organization_id
    sources = {}

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('contractor-plan-clock-alignment')

    def evidence(refs, *, at=None, historic=False):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset:
            _needs('received_original_plan_evidence_time')
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                _unsupported('contractor-plan-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                clock(row.effective_window.end)
                if row.effective_window.start.offset > now.offset:
                    _needs('received_original_plan_evidence', [ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_plan_evidence_valid_at_use', [ref])
            sources[ref.key()] = ref

    def read(ref, schema, historic=False, linked=False, *, evidence_at_field=None, source_at=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', ref)) != ref:
            _unsupported('contractor-plan-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Plan source leaves original authorized mandate scope')
        use = now if source_at is None else source_at
        clock(use)
        if use.offset > now.offset:
            _needs('received_original_plan_source_time', [ref])
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > use.offset:
                _needs('received_original_plan_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            clock(row.effective_window.end)
            if (source_at is not None or not historic) and not row.effective_window.contains(use):
                _needs('current_original_plan_source', [ref])
        point = source_at if evidence_at_field is None else getattr(row, evidence_at_field)
        if point is not None:
            clock(point)
            if evidence_at_field is not None and point.offset > row.available_at.offset:
                raise ValueError('Plan source precedes its original actual authorship')
        evidence(getattr(row, 'evidence_refs', []), at=point, historic=historic)
        sources[ref.key()] = ref
        return row

    def authorize(ref, actor, function, organization, action, at, target_scope):
        grant = read(ref, Authorization, True); assignment = read(function, RoleAssignment, True)
        roles = {'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier', 'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer',
            'QS': 'QS', 'OWN': 'Owner', 'GOV': 'Government', 'BANK': 'Bank'}
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or assignment.function_ref != function or assignment.role != roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s, target_scope) for s in grant.scopes)):
            raise ValueError('Plan source changes independent executor, original action/function or scope authority')
        clock(at); clock(grant.validity.start); clock(grant.validity.end)
        if at.offset > now.offset:
            _needs('received_original_plan_author_time', [ref])
        if not grant.validity.contains(at):
            _needs('original_plan_authority_at_execution', [ref])
        for basis_ref in (*grant.basis_refs, *assignment.basis_refs):
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=at)
            else:
                basis = reading.resolve(basis_ref)
                if hasattr(basis, 'available_at'):
                    clock(basis.available_at)
                    if basis.available_at.offset > at.offset:
                        _needs('original_plan_authority_basis_available_at_use', [basis_ref])
                sources[basis_ref.key()] = basis_ref
        return grant

    def author(row, actions, organization):
        clock(row.authored_at)
        if (row.author_action_id not in actions or row.author_organization_id != organization
                or row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at)):
            raise ValueError('Plan source substitutes original author, permitted function or execution time')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            organization, row.author_action_id, row.authored_at, row.scope)

    def original_inputs(row, grant, refs):
        refs = {ref.key(): ref for ref in refs}
        if not set(refs) <= keys(grant.readable_refs):
            raise ValueError('Plan or offer author lacks original input read authority')
        for ref in refs.values():
            source = reading.resolve(ref)
            if hasattr(source, 'available_at'):
                clock(source.available_at)
                if source.available_at.offset > row.authored_at.offset:
                    raise ValueError('Plan or offer references a source unavailable at original signing')
            if ref.kind == 'Evidence':
                evidence([ref], at=row.authored_at)

    def window(ref):
        row = read(ref, TimeWindow); clock(row.start); clock(row.end)
        if row.bounds != 'closed_open' or row.start.offset >= row.end.offset:
            _unsupported('contractor-plan-nonempty-half-open-window')
        return row

    def complete(choice, **fields):
        reading.recheck()
        if profile.monthly_supplier_policy_ref is not None or profile.monthly_supplier_observation_ref is not None:
            if choice != 'request_quote' or profile.monthly_supplier_policy_ref is None or profile.monthly_supplier_observation_ref is None:
                raise ValueError('Monthly supplier review needs its paired policy/observation and original inquiry-preparation checks')
            from src.actions.roles.contractor_supplier_review import analyze_supplier_review
            judgment = analyze_supplier_review(context, reading, profile=profile, supplier_ids=fields['supplier_ids'])
            return {'kind': 'completed', 'payload': {'choice': choice, **fields, 'note': judgment.model_dump_json()}}
        return {'kind': 'completed', 'payload': {'choice': choice, **fields,
            'note': profile.note + ' Prepared scope only: formal services own plan/resource conversion and matched supplier orders. No site release, supplier acceptance, stock or actual work is created.'}}

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {'trigger': 'dependency_change',
            'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def technical(code):
        raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': code}, 'retryability': 'unknown'})

    def supply_reference(ref, required, offer=None, terms=None):
        row = read(ref, ContractorSupplyReferenceView, linked=True)
        if (not keys(required) <= keys(row.requirement_refs) or row.offer_ref != offer or row.terms_ref != terms
                or any(not scope_covers(row.scope, requirement_map[value.key()].scope) for value in required)
                or not _known(row.permitted, 'original_supply_requirement_binding_permission')):
            _needs('independent_original_supply_specification_location_or_rule', [ref])
        return row

    try:
        if not scope_covers(context.scope, scope):
            raise ValueError('Work planning expands its original invocation scope')
        basis = action_input.work_basis
        mandate_ref = basis.contract_ref if basis.kind == 'contract' else basis.authorization_ref
        mandate = read(mandate_ref, ContractorWorkMandateView, linked=True)
        if mandate.mandate_kind != basis.kind or mandate.organization_id != org or not scope_covers(mandate.scope, scope):
            raise ValueError('Work basis changes actual contract/preparation authority, contractor or authorized scope')
        if not _known(mandate.effective, 'effective_original_work_mandate'):
            _needs('effective_original_work_mandate')
        if (keys(mandate.design_refs) != keys(action_input.design_refs) or keys(mandate.method_refs) != keys(action_input.work_method_refs)
                or keys(mandate.dependency_refs) != keys(action_input.dependency_refs)):
            _needs('complete_original_design_method_and_dependency_snapshot')
        profile = read(mandate.planning_profile_ref, ContractorPlanningProfileView)
        if profile.mandate_ref != mandate.ref or profile.organization_id != org or profile.authority_ref not in context.authorization_refs:
            raise ValueError('Work profile substitutes original acting contractor mandate or authority')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, org, 'CONTRACTOR-A05', now, scope)
        choice = profile.choice
        if profile.negative_selection_observation_ref is not None:
            from src.actions.roles.contractor_negative_selection import judge_negative_selection
            return judge_negative_selection(context, reading, profile=profile, organization_id=org)
        if choice in {'plan', 'revise_plan'}:
            if profile.plan_ref is None:
                _needs('original_proposed_work_plan')
            plan = read(profile.plan_ref, ContractorWorkPlanView, evidence_at_field='authored_at')
            plan_grant = author(plan, {'CONTRACTOR-A05'}, org)
            if plan.mandate_ref != mandate.ref or plan.purpose not in mandate.allowed_task_purposes or keys(plan.design_refs) != keys(action_input.design_refs):
                raise ValueError('Plan substitutes actual mandate, authorized purpose or design versions')
            if basis.kind == 'preparation' and plan.purpose != 'preparation':
                raise ValueError('Preparation authority cannot authorize construction tasks')
            if plan.status != 'proposed' or not plan.tasks or len({t.local_key for t in plan.tasks}) != len(plan.tasks):
                _needs('nonempty_unique_original_proposed_plan_tasks')
            if plan.commitment_refs:
                raise ValueError('Proposed work plan cannot pretend to own formal resource commitments')
            for ref in action_input.design_refs:
                design = read(ref, ContractorPlanDesignView, evidence_at_field='authored_at')
                author(design, {'ARCHITECT-A07', 'ENGINEER-A07', 'QS-A05'}, design.author_organization_id)
                if design.mandate_ref != mandate.ref or design.status != 'released' or plan.purpose not in design.allowed_uses:
                    _needs('released_original_design_for_authorized_plan_use', [ref])
            dependencies = [read(ref, ContractorPlanDependencyView) for ref in action_input.dependency_refs]
            original_inputs(plan, plan_grant, [mandate.ref, *plan.design_refs, *action_input.dependency_refs, *plan.evidence_refs])
            task_keys = {t.local_key for t in plan.tasks}; graph = {key: set() for key in task_keys}
            for dep in dependencies:
                if dep.mandate_ref != mandate.ref or dep.dependent_task_key not in graph or not set(dep.predecessor_task_keys) <= task_keys:
                    raise ValueError('Plan dependency changes original mandate or local predecessor identities')
                if not _known(dep.planning_permitted, 'original_dependency_planning_permission'):
                    _needs('original_plannable_dependency')
                graph[dep.dependent_task_key].update(dep.predecessor_task_keys)
            visiting, visited = set(), set()
            def visit(key):
                if key in visiting:
                    return False
                if key in visited:
                    return True
                visiting.add(key)
                if not all(visit(other) for other in graph[key]):
                    return False
                visiting.remove(key); visited.add(key)
                return True
            if not all(visit(key) for key in graph):
                return wait('contractor-plan-circular-dependency-requires-responsible-party-resolution', action_input.dependency_refs)
            if original_cycle_only:
                _unsupported('contractor-plan-original-cycle-not-reproduced')
            capacity = read(action_input.capacity_ref, ContractorBidCapacityView)
            if capacity.organization_id != org or capacity.as_of != now or capacity.coverage != 'complete':
                _needs('complete_current_original_plan_capacity')
            if capacity.qualification_coverage != 'complete':
                _needs('complete_original_contractor_plan_qualification_snapshot')
            keys(capacity.qualification_refs)
            qualifications = [read(ref, QualificationView, linked=True) for ref in capacity.qualification_refs]
            for code in mandate.required_qualification_codes:
                if not any(q.organization_ref.id == org and q.qualification_code == code
                        and mandate.region_id in q.region_ids and mandate.work_type in q.work_types
                        and isinstance(q.standing, Known) and q.standing.value for q in qualifications):
                    _needs('original_current_contractor_work_qualification')
            keys([r.resource_ref for r in capacity.resources]); keys([r.commitment_ref for r in capacity.commitments])
            resources = {r.resource_ref.key(): r for r in capacity.resources}; demands = []; reused = set()
            for row in capacity.resources:
                original = read(row.resource_ref, ContractorBidResourceView, linked=True)
                if (original.organization_id != org or original.resource_kind != row.resource_kind or original.region_id != row.region_id
                        or original.total != row.total or original.effective_window != row.effective_window):
                    raise ValueError('Plan calendar aliases original physical resource or location')
                evidence([row.total.basis_ref])
            for row in capacity.commitments:
                original = read(row.commitment_ref, ContractorBidCommitmentView, linked=True)
                if (original.organization_id != org or original.resource_ref != row.resource_ref or original.quantity != row.quantity
                        or original.window != row.window or row.resource_ref.key() not in resources):
                    raise ValueError('Plan calendar loses original occupied resource/amount/window')
                evidence([row.quantity.basis_ref])
            if choice == 'revise_plan':
                if profile.prior_plan_ref is None:
                    _needs('original_effective_plan_for_revision')
                prior = read(profile.prior_plan_ref, ContractorWorkPlanView, evidence_at_field='authored_at')
                author(prior, {'CONTRACTOR-A05'}, org)
                original_inputs(plan, plan_grant, [prior.ref])
                if prior.mandate_ref != mandate.ref or prior.status != 'effective':
                    raise ValueError('Plan revision substitutes original effective mandate/plan identity')
                reused = keys(prior.commitment_refs)
                originals = {r.commitment_ref.key(): r for r in capacity.commitments}
                for key in reused:
                    row = originals.get(key)
                    if row is None or not any(a.resource_ref == row.resource_ref and a.quantity == row.quantity
                            and window(a.window_ref) == row.window for t in prior.tasks for a in t.allocations):
                        raise ValueError('Revised plan borrows another original reservation')
            all_task_deps = []
            task_coverage = set()
            for task in plan.tasks:
                if (not scope_covers(scope, task.scope_ref) or not scope_covers(plan.scope, task.scope_ref)
                        or task.work_method_ref.key() not in keys(action_input.work_method_refs)):
                    raise ValueError('Work task widens original scope or changes permitted method')
                method = read(task.work_method_ref, ContractorBidMethodView, linked=True)
                if not scope_covers(method.scope, task.scope_ref):
                    raise ValueError('Work method does not cover its original planned task scope')
                original_inputs(plan, plan_grant, [task.work_method_ref, task.window_ref,
                    *(quantity.basis_ref for quantity in task.target_quantities),
                    *(allocation.resource_ref for allocation in task.allocations),
                    *(allocation.quantity.basis_ref for allocation in task.allocations)])
                for covered_ref in task.scope_ref.coverage_refs:
                    coverage_key = (covered_ref.key(), task.work_method_ref.key())
                    if coverage_key in task_coverage:
                        raise ValueError('Plan repeats parent/child physical work coverage for the same work method')
                    task_coverage.add(coverage_key)
                    reading.resolve(covered_ref)
                if (mandate.region_id not in method.region_ids or mandate.object_type not in method.object_types
                        or mandate.work_type not in method.work_types or not set(mandate.special_condition_codes) <= set(method.special_condition_codes)):
                    _unsupported('contractor-plan-method-object-location-domain')
                work_window = window(task.window_ref); ticks = work_window.end.offset - work_window.start.offset
                if work_window.start.offset < now.offset or work_window.end.offset > mandate.effective_window.end.offset:
                    _needs('future_original_plan_window_within_mandate')
                if (work_window.start.offset < method.effective_window.start.offset or work_window.end.offset > method.effective_window.end.offset
                        or any(work_window.start.offset < reading.resolve(ref).effective_window.start.offset
                            or work_window.end.offset > reading.resolve(ref).effective_window.end.offset for ref in action_input.design_refs)):
                    _needs('original_method_and_design_effective_for_planned_window')
                for code in mandate.required_qualification_codes:
                    if not any(q.qualification_code == code and q.organization_ref.id == org
                            and q.effective_window.start.offset <= work_window.start.offset
                            and work_window.end.offset <= q.effective_window.end.offset for q in qualifications
                            if isinstance(q.standing, Known) and q.standing.value
                            and mandate.region_id in q.region_ids and mandate.work_type in q.work_types):
                        _needs('original_contractor_work_qualification_for_full_planned_window')
                keys(task.dependency_refs); all_task_deps.extend(task.dependency_refs)
                if keys(task.dependency_refs) != {d.ref.key() for d in dependencies if d.dependent_task_key == task.local_key}:
                    raise ValueError('Task drops or substitutes its original dependencies')
                for predecessor in graph[task.local_key]:
                    predecessor_task = next(t for t in plan.tasks if t.local_key == predecessor)
                    if window(predecessor_task.window_ref).end.offset > work_window.start.offset:
                        _needs('predecessor_work_window_before_dependent_task')
                if not task.target_quantities or not task.allocations:
                    _needs('explicit_original_task_targets_and_allocations')
                target = Fraction(); available = Fraction()
                for quantity in task.target_quantities:
                    if quantity.unit != method.quantity_unit or decimal_fraction(quantity.value) <= 0:
                        raise ValueError('Plan target changes exact supported quantity unit or sign')
                    evidence([quantity.basis_ref]); target += decimal_fraction(quantity.value)
                keys([a.resource_ref for a in task.allocations])
                for allocation in task.allocations:
                    resource = resources.get(allocation.resource_ref.key()); amount = decimal_fraction(allocation.quantity.value)
                    if (resource is None or resource.region_id != mandate.region_id or resource.resource_kind != method.resource_kind
                            or allocation.task_scope_ref != task.scope_ref or allocation.window_ref != task.window_ref or amount <= 0
                            or allocation.quantity.unit != method.capacity_unit or resource.total.unit != method.capacity_unit):
                        raise ValueError('Allocation changes original resource/location/task/window/exact unit')
                    available += amount; evidence([allocation.quantity.basis_ref])
                    demands.append((resource.resource_ref.key(), {'resource_kind': resource.resource_kind, 'region_id': resource.region_id,
                        'unit': method.capacity_unit, 'amount': ExactAmount.from_fraction(amount), 'window': work_window,
                        'basis_refs': [allocation.quantity.basis_ref]}))
                rate = decimal_fraction(_known(method.quantity_per_capacity_tick, 'original_plan_productivity'))
                evidence([method.productivity_basis_ref])
                if rate <= 0 or target > available * rate * ticks:
                    _needs('supported_original_task_quantity_rate_and_window')
            if keys(all_task_deps) != keys(action_input.dependency_refs):
                raise ValueError('Work plan drops or duplicates original dependencies across tasks')
            for key, resource in resources.items():
                selected = [d for resource_key, d in demands if resource_key == key]
                if not selected:
                    continue
                data = CapacityInput(clock_ref=now.clock_ref, demands=selected, resources=[resource],
                    commitments=[r for r in capacity.commitments if r.resource_ref.key() == key and r.commitment_ref.key() not in reused],
                    source_refs=list(sources.values()))
                if historical_capacity is not None:
                    basis_refs = {ref.key(): ref for ref in walk_references(data) if ref.kind == 'Evidence'}
                    if not data.source_refs or not basis_refs:
                        _needs('original_plan_capacity_input_provenance')
                    for source_ref in data.source_refs:
                        reading.resolve(source_ref)
                    for basis_ref in basis_refs.values():
                        row = reading.resolve(basis_ref)
                        if not isinstance(row, EvidenceRecord) or row.ref != basis_ref:
                            _unsupported('contractor-plan-original-capacity-evidence-schema')
                        evidence([basis_ref], at=now)
                    report = compare_capacity(data)
                    historical_capacity.append(dict(method_ref=CAPACITY_METHOD.model_dump(mode='json'),
                        input=data.model_dump(mode='json'), comparison=report.model_dump(mode='json')))
                else:
                    result = reading.calculate(CAPACITY_METHOD, data)
                    if result.kind != 'ok':
                        if result.kind == 'invalid_input':
                            _unsupported('contractor-plan-capacity-method-domain')
                        raw = result.model_dump(mode='python')
                        if result.kind == 'needs_information':
                            raw['requested_refs'] = []
                        raise ObservationGap(raw)
                    report = result.value
                if not report.feasible:
                    return wait('contractor-plan-shared-resource-capacity-conflict', [capacity.ref])
            if historical_capacity is not None:
                _unsupported('contractor-plan-original-capacity-wait-not-reproduced')
            return complete(choice, tasks=[t.model_dump(mode='python') for t in plan.tasks],
                **({'prior_plan_ref': profile.prior_plan_ref} if choice == 'revise_plan' else {}))

        if original_cycle_only or historical_capacity is not None:
            _unsupported('contractor-plan-original-cycle-requires-plan-branch')
        if not profile.requirement_refs:
            _needs('explicit_original_supply_requirements')
        requirements = [read(ref, ContractorSupplyRequirementView) for ref in profile.requirement_refs]
        requirement_map = {row.ref.key(): row for row in requirements}
        keys(profile.requirement_refs)
        for requirement in requirements:
            if requirement.mandate_ref != mandate.ref or decimal_fraction(requirement.quantity.value) <= 0:
                raise ValueError('Procurement changes original mandate or positive required quantity')
            evidence([requirement.quantity.basis_ref])
            for ref in (requirement.product_ref, requirement.destination_ref, requirement.inspection_rule_ref, requirement.payment_rule_ref):
                supply_reference(ref, [requirement.ref])
            delivery, receiving = window(requirement.delivery_window_ref), window(requirement.receiving_window_ref)
            if delivery.start.offset < now.offset or receiving.start.offset > delivery.start.offset or delivery.end.offset > receiving.end.offset:
                _needs('original_delivery_within_available_site_receiving_window')
            if requirement.substitution_authority_ref is not None:
                supply_reference(requirement.substitution_authority_ref, [requirement.ref])
        if choice == 'request_quote':
            if not _known(mandate.allow_quote, 'original_quote_permission'):
                _needs('original_work_mandate_quote_permission')
            if not profile.supplier_refs:
                return wait('contractor-plan-no-current-supply-inquiry-recipient', profile.requirement_refs)
            keys(profile.supplier_refs); suppliers = []
            for ref in profile.supplier_refs:
                supplier = read(ref, ContractorSupplySupplierView)
                if (not keys(profile.requirement_refs) <= keys(supplier.requirement_refs)
                        or any(supplier.organization_id not in r.allowed_supplier_ids for r in requirements)
                        or not _known(supplier.accepts_inquiries, 'original_supplier_inquiry_channel')):
                    _needs('original_eligible_supplier_inquiry_recipient')
                suppliers.append(supplier.organization_id)
            if len(set(suppliers)) != len(suppliers):
                raise ValueError('Inquiry repeats the same original supplier organization')
            return complete(choice, requirement_refs=profile.requirement_refs, supplier_ids=suppliers)
        if not _known(mandate.allow_supply_acceptance, 'original_supply_purchase_permission'):
            _needs('independent_preparation_or_contract_procurement_permission')
        if profile.selected_offer_ref is None or profile.selected_offer_ref.key() not in keys(action_input.supplier_offer_refs):
            _needs('selected_original_valid_supply_offer')
        offer = read(profile.selected_offer_ref, ContractorSupplyOfferView, evidence_at_field='authored_at')
        offer_grant = author(offer, {'SUPPLIER-A03', 'SUPPLIER-A04'}, offer.supplier_id)
        terms = read(offer.terms_ref, ContractorSupplyTermsView, historic=True, source_at=offer.authored_at)
        if not terms.effective_window.contains(now):
            _needs('current_original_selected_supply_terms', [terms.ref])
        original_inputs(offer, offer_grant, [terms.ref, *offer.requirement_refs, *offer.evidence_refs,
            *(line.quantity.basis_ref for line in offer.lines), *(line.batch_price.basis_ref for line in offer.lines),
            terms.gross_price.basis_ref])
        if (offer.status != 'active' or offer.buyer_id != org or offer.payer_id != org or terms.offer_ref != offer.ref
                or terms.supplier_id != offer.supplier_id or terms.buyer_id != org or terms.payer_id != org
                or keys(offer.requirement_refs) != keys(profile.requirement_refs) or keys(terms.requirement_refs) != keys(profile.requirement_refs)
                or terms.receiving_window_ref != profile.receiving_window_ref):
            raise ValueError('Supply selection mixes original supplier/offer/terms/requirements/payer or receiving versions')
        if terms.lines != offer.lines or not terms.lines or len({r.local_key for r in terms.lines}) != len(terms.lines):
            raise ValueError('Supply selection changes original quoted batch identities/quantities/prices')
        if keys([r.requirement_ref for r in terms.lines]) != keys(profile.requirement_refs):
            raise ValueError('Supply selection omits or invents an original required product line')
        price = Fraction()
        for line in terms.lines:
            requirement = requirement_map[line.requirement_ref.key()]
            if (line.product_ref != requirement.product_ref or line.quantity != requirement.quantity
                    or line.batch_price.currency != terms.gross_price.currency or decimal_fraction(line.batch_price.value) < 0):
                raise ValueError('Supply line changes original required product/quantity/unit/currency')
            evidence([line.quantity.basis_ref, line.batch_price.basis_ref], at=offer.authored_at)
            price += decimal_fraction(line.batch_price.value)
        if price != decimal_fraction(terms.gross_price.value):
            raise ValueError('Supply gross commitment differs from complete original batch prices')
        for requirement in requirements:
            if (offer.supplier_id not in requirement.allowed_supplier_ids or terms.receiving_window_ref != requirement.receiving_window_ref
                    or terms.delivery_window_ref != requirement.delivery_window_ref or terms.destination_ref != requirement.destination_ref
                    or terms.inspection_rule_ref != requirement.inspection_rule_ref or terms.payment_rule_ref != requirement.payment_rule_ref):
                raise ValueError('Supply terms change original delivery/site/inspection/payment requirement')
        supply_reference(terms.binding_ref, profile.requirement_refs, offer.ref, terms.ref)
        if profile.procurement_authority_ref is None:
            _needs('independent_original_procurement_responsible_authority')
        authority = read(profile.procurement_authority_ref, ContractorProcurementAuthorityView, linked=True)
        if (authority.mandate_ref != mandate.ref or authority.actor_id != context.actor_id or authority.function_ref != context.function_ref
                or not scope_covers(authority.scope, scope)
                or authority.organization_id != org or authority.offer_ref != offer.ref or authority.terms_ref != terms.ref
                or authority.terms_sha256 != content_digest(terms) or not _known(authority.permitted, 'original_procurement_responsibility_permission')):
            _needs('independent_same_offer_terms_procurement_authority')
        if not mandate.procurement_history_complete:
            _needs('complete_original_mandate_procurement_history')
        keys(mandate.procurement_history_refs); amount = Fraction(); business = set()
        for ref in mandate.procurement_history_refs:
            row = read(ref, ContractorSupplyCommitmentView, True)
            evidence([row.amount.basis_ref], historic=True)
            if row.mandate_ref != mandate.ref or row.business_key in business:
                raise ValueError('Procurement repeats original business commitment or mandate')
            business.add(row.business_key)
            if row.offer_ref == offer.ref or row.terms_ref == terms.ref:
                return wait('contractor-plan-existing-supply-commitment-query-original-order', [row.ref])
            if row.status != 'released':
                if row.amount.currency != terms.gross_price.currency or decimal_fraction(row.amount.value) < 0:
                    raise ValueError('Original procurement commitment changes currency or sign')
                amount += decimal_fraction(row.amount.value)
        limit = _known(mandate.procurement_limit, 'original_mandate_procurement_limit')
        used = _known(mandate.procurement_used, 'original_mandate_procurement_used')
        if (limit.currency != terms.gross_price.currency or used.currency != limit.currency or decimal_fraction(used.value) != amount
                or decimal_fraction(terms.gross_price.value) <= 0 or decimal_fraction(limit.value) < 0):
            raise ValueError('Procurement gross price/history/authorization limit changes original currency or values')
        evidence([limit.basis_ref, used.basis_ref])
        evidence([terms.gross_price.basis_ref], at=offer.authored_at)
        if amount + decimal_fraction(terms.gross_price.value) > decimal_fraction(limit.value):
            return wait('contractor-plan-original-preparation-or-contract-procurement-limit', [mandate.ref])
        return complete(choice, offer_ref=offer.ref, order_terms_ref=terms.ref, receiving_window_ref=terms.receiving_window_ref)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
