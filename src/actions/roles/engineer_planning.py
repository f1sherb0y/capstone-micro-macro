"""ENGINEER-A04 produces remaining-work plans, never completed work or fees."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, walk_references
from src.actions.contracts.engineer_planning_objects import (
    EngineerPlanningProfileView, EngineerPlanningCalendarView, EngineerPlanningTaskView,
    EngineerPlanningEstimateView, EngineerPlanningWorkFactView, EngineerPlanningDependencyView,
    EngineerPlanningDeliverableView, EngineerPlanningAllocationView, EngineerPlanningReservationView,
    EngineerPlanningQualificationView,
    EngineerAppointmentView, QSWorkPlanView, EngineerServiceTermsView,
    EngineerPlanningAccessView, EngineerPlanningObservationMethodView,
    EngineerIndependenceCheckView, EngineerIndependenceRequirementView, EngineerOrganizationRelationsView,
    EngineerAuthoredTargetView, EngineerConflictView, EngineerPlanningQuestionTargetView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.architect_appointment_objects import service_terms_digest
from src.actions.contracts.service_objects import ServiceResponseRequirementView
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, CapacityReport, ExactAmount, compare_capacity
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def recheck_original_engineer_planning_capacity(context, action_input, reading):
    """Reproduce historical capacity with current read grants and no old method invocation."""
    reading.check_method_context(reading._context, 'ENGINEER-A04')
    binding = reading._methods._bindings.get(CAPACITY_METHOD.key()) if reading._methods is not None else None
    if (CAPACITY_METHOD.key() not in reading._method_refs or binding is None
            or binding.executor is not compare_capacity or binding.input_model is not CapacityInput
            or binding.output_model is not CapacityReport or 'ENGINEER-A04' not in binding.definition.action_ids
            or binding.definition.effect_kind != 'pure_calculation'):
        raise ValueError('Original engineering capacity wait requires its actual declared pure capacity method')
    comparisons = []
    before = reading.method_evidence()
    try:
        result = plan_professional_work(context, action_input, reading, historical_capacity=comparisons)
    finally:
        reading.recheck()
        if reading.method_evidence() != before:
            raise ValueError('Historical engineering capacity checks cannot execute a method')
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'shared_engineering_personnel_capacity_unavailable'):
        raise ValueError('Original engineering sources do not reproduce the actual shared personnel capacity wait')
    return result, comparisons


def plan_professional_work(context, action_input, reading, *, original_wait_only=False, historical_capacity=None):
    now, organization = context.business_time, reading.organization_id
    sources = {}

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('engineer-planning-clock-alignment')

    def evidence(refs, historical=False):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('engineer-planning-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_engineering_planning_evidence', [ref])

    def read(ref, schema, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'engineer-planning-projection:{ref.kind}')
        if hasattr(row, 'scope') and row.scope != action_input.scope: raise ValueError('Engineering planning changes original scope')
        for field in ('available_at', 'received_at'):
            point = getattr(row, field, None)
            if point is not None:
                clock(point)
                if point.offset > now.offset: _needs('received_original_engineering_planning_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('effective_original_engineering_planning_input', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical); sources[ref.key()] = ref
        return row

    def authorize(ref, function_ref):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        if (grant.organization_id != organization or grant.actor_id != context.actor_id or grant.function_ref != function_ref
                or function.role != 'Engineer' or 'ENGINEER-A04' not in grant.action_ids
                or not any(scope_covers(scope, action_input.scope) for scope in grant.scopes)):
            raise ValueError('Engineering planning lacks independent original action/function/scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(now): _needs('current_engineering_planning_authority')
        evidence([*grant.basis_refs, *function.basis_refs])

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'scope': action_input.scope, 'note': profile.note, **fields}}

    def deferred(code, refs):
        reading.recheck(); return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
            'trigger': 'dependency_change', 'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def confirmed_effort(task):
        estimate = read(task.estimate_ref, EngineerPlanningEstimateView, True)
        if not same(estimate.task_ref, task.ref) or not same(estimate.work_profile_ref, profile.ref):
            raise ValueError('Task borrows another task workload estimate')
        clock(estimate.executed_at)
        if estimate.effort.unit != profile.effort_unit: _unsupported('engineer-task-effort-unit-conversion')
        evidence([estimate.effort.basis_ref], True)
        total = decimal_fraction(estimate.effort.value)
        if total <= 0: raise ValueError('Original task effort must be positive')
        if estimate.status != 'succeeded' or estimate.executed_at.offset > min(now.offset, estimate.available_at.offset): return None, total
        if task.work_fact_coverage != 'complete': return None, total
        keys(task.work_fact_refs); spent, investments = Fraction(), set()
        for ref in task.work_fact_refs:
            fact = read(ref, EngineerPlanningWorkFactView, True)
            if (not same(fact.task_ref, task.ref) or fact.organization_id != organization
                    or fact.investment_key in investments): raise ValueError('Task investment repeats a slice or changes original task/organization')
            investments.add(fact.investment_key)
            clock(fact.window.start)
            if fact.status != 'committed': return None, total
            if fact.window.end.offset > min(now.offset, fact.available_at.offset): _needs('engineering_investment_finished_before_received')
            if fact.effort.unit != profile.effort_unit: _unsupported('engineer-investment-unit-conversion')
            effort = decimal_fraction(fact.effort.value)
            if effort < 0 or decimal_fraction(fact.internal_cost.value) < 0: raise ValueError('Original actual investment/cost cannot be negative')
            evidence([fact.effort.basis_ref, fact.internal_cost.basis_ref], True); spent += effort
        if spent > total: raise ValueError('Investment exceeds original task; rework needs a separately authorized increment')
        if isinstance(task.remaining_effort, Known):
            remaining = task.remaining_effort.value
            if remaining.unit != profile.effort_unit or decimal_fraction(remaining.value) != total - spent:
                raise ValueError('Remaining task effort differs from original method effort minus confirmed slices')
            evidence([remaining.basis_ref]); return remaining, total
        return None, total

    def independence_resources(appointment, terms, resources):
        personnel_resources = {key for key, row in resources.items() if row.asset_role == 'personnel'}
        if terms.independence_requirement_ref is None:
            if _known(terms.function_code, 'accepted_engineering_function') == 'independent_review' or appointment.independence_check_ref is not None:
                _needs('original_required_professional_independence_template')
            return personnel_resources
        if appointment.independence_check_ref is None: _needs('original_professional_independence_check')
        check = read(appointment.independence_check_ref, EngineerIndependenceCheckView)
        if (check.organization_id != organization or not same(check.appointment_ref, appointment.ref)
                or not same(check.accepted_terms_ref, terms.ref) or not same(check.requirement_ref, terms.independence_requirement_ref)):
            raise ValueError('Professional independence check changes appointment/terms/organization')
        if check.as_of != now or not check.effective_window.contains(now): _needs('current_professional_independence_check')
        grant = read(check.authority_ref, Authorization); function = read(check.author_function_ref, RoleAssignment)
        clock(grant.validity.start)
        if (grant.organization_id != organization or grant.actor_id != check.author_actor_id
                or not same(grant.function_ref, check.author_function_ref) or function.role != 'Engineer'
                or 'ENGINEER-A03' not in grant.action_ids or not grant.validity.contains(now)
                or not any(scope_covers(s, action_input.scope) for s in grant.scopes)
                or not keys(check.evidence_refs) <= keys(grant.readable_refs)):
            _needs('authorized_original_professional_independence_check')
        evidence([*grant.basis_refs, *function.basis_refs])
        requirement = read(check.requirement_ref, EngineerIndependenceRequirementView)
        if not same(requirement.request_ref, appointment.request_ref): raise ValueError('Independence template changes request')
        if requirement.template_code not in {'separate_organization_and_personnel_v1', 'separate_personnel_v1'}:
            _unsupported('engineer-planning-independence-template')
        relations = read(requirement.relations_ref, EngineerOrganizationRelationsView)
        if relations.organization_id != organization or relations.as_of != now or relations.coverage != 'complete':
            _needs('current_complete_professional_organization_relations')
        related = {organization, *_known(relations.related_organization_ids, 'professional_related_organizations')}
        checked = keys(check.checked_resource_refs)
        if not checked <= personnel_resources: _needs('checked_professional_personnel_in_current_calendar')
        authors, organizations = set(), set()
        keys(requirement.target_refs)
        for ref in requirement.target_refs:
            schema = EngineerPlanningDeliverableView if ref.kind == 'Deliverable' else EngineerAuthoredTargetView
            target = read(ref, schema, True)
            authors.update(_known(target.author_personnel_ids, 'original_professional_target_authors'))
            if requirement.template_code == 'separate_organization_and_personnel_v1':
                organizations.update(_known(target.author_organization_ids, 'original_professional_author_organizations'))
        keys(check.conflict_refs)
        for ref in check.conflict_refs:
            conflict = read(ref, EngineerConflictView)
            if (not same(conflict.appointment_ref, appointment.ref) or not same(conflict.requirement_ref, requirement.ref)
                    or conflict.organization_id != organization): raise ValueError('Conflict changes original appointment/template')
        # Recompute for actual current people: a prior clean record cannot authorize a new reviewer.
        if check.conflict_refs or organizations & related: return set()
        return {key for key in checked if not set(_known(resources[key].personnel_ids, 'actual_professional_review_personnel')) & authors}

    try:
        profile = read(action_input.work_profile_ref, EngineerPlanningProfileView)
        if profile.organization_id != organization or action_input.scope != context.scope: raise ValueError('Engineering work profile changes original organization/scope')
        authorize(profile.authority_ref, context.function_ref)
        if profile.method != 'constant_capacity_over_half_open_window_v1' or profile.clock_ref != now.clock_ref:
            _unsupported('engineer-task-work-method-domain')
        appointment = read(profile.appointment_ref, EngineerAppointmentView)
        if appointment.provider_organization_id != organization or appointment.status != 'active' or appointment.service_relationship_ref is None:
            _needs('original_active_authorized_engineering_appointment')
        terms = read(appointment.terms_ref, EngineerServiceTermsView, True)
        if service_terms_digest(terms) != appointment.terms_digest:
            raise ValueError('Professional plan changes original accepted terms content')
        disciplines = set(_known(terms.discipline_codes, 'original_engineering_disciplines'))
        accepted_function = _known(terms.function_code, 'original_engineering_function')
        if not disciplines <= set(profile.discipline_codes): _unsupported('engineer-planning-discipline-domain')
        region = _known(terms.region_id, 'original_engineering_work_region')
        service = _known(terms.service_code, 'original_engineering_service')
        responsibilities = _known(terms.responsibility_codes, 'original_engineering_functions')
        accepted_window = _known(terms.desired_window, 'original_accepted_engineering_window'); clock(accepted_window.start)
        if region not in profile.region_ids or service not in profile.service_codes: _unsupported('engineer-planning-location-or-service')
        if keys(action_input.task_refs) != keys(profile.task_refs): _needs('all_original_authorized_engineering_tasks', profile.task_refs)
        calendar = read(action_input.capacity_ref, EngineerPlanningCalendarView)
        if calendar.organization_id != organization or calendar.as_of != now or calendar.coverage != 'complete':
            _needs('complete_current_cross_project_engineering_resource_calendar')
        resources = {row.resource_ref.key(): row for row in calendar.resources}
        people = set()
        for resource in resources.values():
            if resource.asset_role == 'equipment':
                if _known(resource.personnel_ids, 'equipment_has_no_personnel'): raise ValueError('Equipment cannot duplicate personnel capacity')
                continue
            identities = _known(resource.personnel_ids, 'actual_engineering_personnel_ids')
            if not identities or len(set(identities)) != len(identities) or people.intersection(identities):
                raise ValueError('Engineering personnel are duplicated or unnamed across shared resources')
            people.update(identities)
        commitments = {row.commitment_ref.key(): row for row in calendar.commitments}
        for row in commitments.values():
            if row.resource_ref.key() not in resources: _needs('original_committed_engineering_resource_version')
        prior = None
        if profile.prior_plan_ref is not None:
            prior = read(profile.prior_plan_ref, QSWorkPlanView)
            if (prior.organization_id != organization or not same(prior.appointment_ref, appointment.ref)
                    or prior.status != 'authorized'): raise ValueError('Revised engineering plan changes original appointment or authorization')
            authorize(prior.authority_ref, context.function_ref)
        tasks = sorted([read(ref, EngineerPlanningTaskView) for ref in action_input.task_refs], key=lambda row: (row.planned_window.start.offset, row.ref.key()))
        expected_allocations = [row.existing_allocation_ref for row in tasks if row.existing_allocation_ref is not None]
        if keys(expected_allocations) != keys(action_input.existing_allocation_refs): _needs('all_original_engineering_task_allocation_links')
        allocations = {}
        for ref in action_input.existing_allocation_refs:
            row = read(ref, EngineerPlanningAllocationView)
            if (prior is None or row.organization_id != organization or not same(row.appointment_ref, appointment.ref)
                    or not same(row.work_plan_ref, prior.ref) or row.as_of != now or row.task_ref.key() not in keys(action_input.task_refs)
                    or row.ref.key() not in keys(prior.allocation_refs)):
                raise ValueError('Engineering allocation changes original task/appointment/plan')
            allocations[ref.key()] = row
        reservations = [read(ref, EngineerPlanningReservationView) for ref in profile.reservation_refs]
        for row in reservations:
            if row.organization_id != organization or not same(row.appointment_ref, appointment.ref) or row.as_of != now:
                raise ValueError('Engineering reservation changes original appointment/organization/snapshot')
        independent_resources = independence_resources(appointment, terms, resources)
        dependency_evidence, blocked, items, demands, excluded = set(), [], [], {}, set()
        excluded_by_task = {}
        authorized_effort = Fraction()
        investment_tasks = {}
        for task in tasks:
            if (task.organization_id != organization or not same(task.appointment_ref, appointment.ref)
                    or not same(task.accepted_terms_ref, terms.ref) or not same(task.work_profile_ref, profile.ref)
                    or task.function_code not in responsibilities or task.as_of != now):
                raise ValueError('Engineering task changes original appointment, terms, function or snapshot')
            if task.function_code != accepted_function or not task.discipline_codes or not set(task.discipline_codes) <= disciplines:
                raise ValueError('Engineering task changes accepted professional discipline/function')
            authorize(task.authority_ref, task.function_ref)
            for ref in task.work_fact_refs:
                fact = read(ref, EngineerPlanningWorkFactView, True)
                previous = investment_tasks.setdefault(fact.investment_key, task.ref.key())
                if previous != task.ref.key(): raise ValueError('Professional investment slice reused across tasks')
            remaining, total = confirmed_effort(task); authorized_effort += total
            ready = task.status in {'authorized', 'waiting'} and remaining is not None and decimal_fraction(remaining.value) > 0
            if task.status == 'complete' and (remaining is None or decimal_fraction(remaining.value)):
                raise ValueError('Completed engineering task lacks fully confirmed actual investment')
            keys(task.dependency_refs)
            for ref in task.dependency_refs:
                dep = read(ref, EngineerPlanningDependencyView)
                if not same(dep.task_ref, task.ref) or dep.as_of != now: raise ValueError('Engineering dependency changes original task/snapshot')
                dependency_evidence.update(keys(dep.input_evidence_refs)); evidence(dep.input_evidence_refs, True)
                satisfied = isinstance(dep.satisfied, Known) and dep.satisfied.value
                for evidence_ref in dep.input_evidence_refs:
                    original = reading.resolve(evidence_ref)
                    satisfied &= original.effective_window is None or original.effective_window.contains(now)
                if dep.deliverable_ref is not None:
                    deliverable = read(dep.deliverable_ref, EngineerPlanningDeliverableView, True)
                    satisfied &= (deliverable.status == 'available' and deliverable.effective_window.contains(now)
                                  and dep.required_use in deliverable.allowed_uses and dep.required_use not in deliverable.invalidated_uses)
                if dep.predecessor_task_ref is not None:
                    predecessor = next((row for row in tasks if same(row.ref, dep.predecessor_task_ref)), None)
                    if predecessor is None: predecessor = read(dep.predecessor_task_ref, EngineerPlanningTaskView)
                    if predecessor.organization_id != organization or not same(predecessor.appointment_ref, appointment.ref):
                        raise ValueError('Engineering dependency borrows another organization/appointment task')
                    predecessor_remaining, _ = confirmed_effort(predecessor)
                    satisfied &= predecessor.status == 'complete' and predecessor_remaining is not None and decimal_fraction(predecessor_remaining.value) == 0
                if dep.deliverable_ref is None and dep.predecessor_task_ref is None and not dep.input_evidence_refs:
                    _needs('original_engineering_dependency_target')
                if not satisfied: ready = False; blocked.append(dep.ref)
            if task.access_ref is not None:
                access = read(task.access_ref, EngineerPlanningAccessView, True)
                if access.organization_id != organization or not same(access.task_ref, task.ref): raise ValueError('Site access changes original task/organization')
                ready &= (isinstance(access.allowed, Known) and access.allowed.value
                          and access.effective_window.start.offset <= task.planned_window.start.offset
                          and task.planned_window.end.offset <= access.effective_window.end.offset)
            if not ready:
                blocked.append(task.ref); continue
            window = task.planned_window; clock(window.start)
            if (window.bounds != 'closed_open' or window.start.offset >= window.end.offset
                    or window.start.offset < now.offset): _needs('current_nonempty_engineering_task_window')
            if not (accepted_window.start.offset <= window.start.offset < window.end.offset <= accepted_window.end.offset
                    and profile.effective_window.start.offset <= window.start.offset < window.end.offset <= profile.effective_window.end.offset):
                _needs('engineering_task_window_within_original_authorized_method_and_appointment')
            keys([row.resource_ref for row in task.resource_shares])
            if any(decimal_fraction(row.share) <= 0 for row in task.resource_shares) or sum(decimal_fraction(row.share) for row in task.resource_shares) != 1:
                raise ValueError('Engineering task resource shares must be positive and conserve remaining effort')
            resource_ids, task_demands, task_excluded = [], {}, set()
            suitable = True
            for share in task.resource_shares:
                resource = resources.get(share.resource_ref.key())
                if resource is None: _needs('original_engineering_task_resource_version')
                if (resource.asset_role != 'personnel' or resource.resource_ref.key() not in independent_resources
                        or not set(task.discipline_codes) <= set(resource.discipline_codes)
                        or resource.resource_kind != profile.resource_kind or _known(resource.region_id, 'engineering_resource_region') != region
                        or task.function_code not in resource.function_codes or not _known(resource.suitable, 'engineering_personnel_suitability')):
                    suitable = False; break
                keys(resource.qualification_refs)
                if not resource.qualification_refs: _needs('original_engineering_personnel_qualification')
                for ref in resource.qualification_refs:
                    qualification = read(ref, EngineerPlanningQualificationView)
                    if qualification.organization_id != organization: raise ValueError('Personnel borrow another organization qualification')
                    if (region not in qualification.region_ids or service not in qualification.service_codes
                            or not set(task.discipline_codes) <= set(qualification.discipline_codes)
                            or task.function_code not in qualification.function_codes
                            or not set(_known(resource.personnel_ids, 'actual_engineering_personnel')) <= set(qualification.personnel_ids)
                            or not _known(qualification.standing, 'engineering_personnel_qualification_standing')):
                        suitable = False; break
                if not suitable: break
                rate = decimal_fraction(remaining.value) * decimal_fraction(share.share) / decimal_fraction(profile.effort_per_capacity_tick) / (window.end.offset - window.start.offset)
                task_demands.setdefault(resource.resource_ref.key(), []).append({'resource_kind': profile.resource_kind,
                    'region_id': region, 'unit': profile.capacity_unit, 'amount': ExactAmount.from_fraction(rate),
                    'window': window, 'basis_refs': [remaining.basis_ref]})
                resource_ids.append(resource.resource_ref.id)
            keys([row.resource_ref for row in task.tool_demands])
            for tool in task.tool_demands:
                resource = resources.get(tool.resource_ref.key())
                if resource is None: _needs('original_engineering_equipment_version')
                amount = decimal_fraction(tool.capacity.value)
                evidence([tool.capacity.basis_ref])
                if amount <= 0: raise ValueError('Equipment demand must be positive')
                if tool.capacity.unit != profile.capacity_unit: _unsupported('engineer-equipment-unit-conversion')
                if (resource.asset_role != 'equipment' or _known(resource.region_id, 'equipment_region') != region
                        or not isinstance(resource.suitable, Known) or not resource.suitable.value
                        or task.function_code not in resource.function_codes
                        or not set(task.discipline_codes) <= set(resource.discipline_codes)):
                    suitable = False; continue
                task_demands.setdefault(resource.resource_ref.key(), []).append({'resource_kind': resource.resource_kind,
                    'region_id': region, 'unit': profile.capacity_unit, 'amount': ExactAmount.from_fraction(amount),
                    'window': window, 'basis_refs': [tool.capacity.basis_ref]})
                resource_ids.append(resource.resource_ref.id)
            if not suitable: blocked.append(task.ref); continue
            if task.existing_allocation_ref is not None:
                original = allocations[task.existing_allocation_ref.key()]
                if not same(original.task_ref, task.ref) or not keys(original.work_fact_refs) <= keys(task.work_fact_refs):
                    raise ValueError('Engineering task borrows another task occupancy or loses original investments')
                if original.status == 'active':
                    for row in original.commitments:
                        if commitments.get(row.commitment_ref.key()) != row or row.commitment_ref.key() in excluded:
                            raise ValueError('Engineering allocation loses or duplicates original shared-calendar occupancy')
                        excluded.add(row.commitment_ref.key()); task_excluded.add(row.commitment_ref.key())
            for reservation in reservations:
                if reservation.status != 'reserved': continue
                for item in reservation.items:
                    if same(item.task_ref, task.ref):
                        row = item.commitment
                        if commitments.get(row.commitment_ref.key()) != row or row.commitment_ref.key() in excluded:
                            raise ValueError('Engineering reservation loses or duplicates original occupancy')
                        excluded.add(row.commitment_ref.key()); task_excluded.add(row.commitment_ref.key())
            demands[task.ref.key()] = task_demands
            excluded_by_task[task.ref.key()] = task_excluded
            items.append({'task_ref': task.ref, 'resource_ids': resource_ids, 'window': window, 'effort': remaining,
                          'dependency_refs': task.dependency_refs, 'existing_allocation_ref': task.existing_allocation_ref})
        if dependency_evidence != keys(action_input.dependency_refs): _needs('all_original_engineering_dependency_evidence')
        accepted_effort = _known(terms.effort_estimate, 'original_accepted_engineering_effort')
        if accepted_effort.unit != profile.effort_unit or authorized_effort > decimal_fraction(accepted_effort.value):
            _needs('authorized_engineering_task_increment_within_original_effort_scope')
        if not items:
            questions = []
            for ref in profile.question_target_refs:
                target = read(ref, EngineerPlanningQuestionTargetView); response = read(target.response_requirement_ref, ServiceResponseRequirementView)
                if (target.request_ref != appointment.request_ref or response.request_ref != appointment.request_ref
                        or not target.recipient_ids or not set(target.recipient_ids) <= set(response.recipient_ids)):
                    raise ValueError('Engineering input question changes original request or recipient authority')
                if not target.task_refs or not keys(target.task_refs) <= keys(action_input.task_refs):
                    raise ValueError('Investigation question changes original authorized tasks')
                questions.append({'scope': action_input.scope, 'target_refs': [target.ref], 'question': target.question,
                    'recipient_ids': target.recipient_ids, 'evidence_refs': target.evidence_refs,
                    'blocking_uses': target.blocking_uses, 'response_requirement_ref': response.ref})
            if questions:
                if profile.observation_method_ref is None: _needs('original_engineering_observation_method')
                method = read(profile.observation_method_ref, EngineerPlanningObservationMethodView)
                if (region not in method.region_ids or accepted_function not in method.function_codes
                        or not disciplines <= set(method.discipline_codes)):
                    _unsupported('engineer-investigation-method-domain')
                if not keys(profile.question_target_refs) <= keys(method.target_refs): raise ValueError('Investigation changes method original targets')
                executors = set()
                for ref in method.executor_authority_refs:
                    grant = read(ref, Authorization); clock(grant.validity.start)
                    assignment = read(grant.function_ref, RoleAssignment)
                    if (not grant.validity.contains(now) or not any(scope_covers(s, action_input.scope) for s in grant.scopes)
                            or assignment.role != 'Engineer' or 'ENGINEER-A08' not in grant.action_ids):
                        _needs('independently_authorized_investigation_executor')
                    evidence([*grant.basis_refs, *assignment.basis_refs]); executors.add(grant.organization_id)
                if not method.executor_organization_ids or executors != set(method.executor_organization_ids):
                    _needs('original_method_authorized_executor_set')
                for ref in profile.question_target_refs:
                    target = read(ref, EngineerPlanningQuestionTargetView)
                    if not target.executor_organization_ids or not set(target.executor_organization_ids) <= executors:
                        raise ValueError('Investigation question changes original authorized executor')
                return completed('request_investigation', questions=questions, observation_method_ref=method.ref)
            return deferred('original_engineering_tasks_waiting_or_already_invested', blocked or [profile.ref])
        if original_wait_only:
            # Reproduce historical task waits before executing any capacity method.
            reading.recheck()
            return None
        selected, selected_demands, selected_excluded = [], {}, set()
        for item in items:
            task_key = item['task_ref'].key()
            trial_excluded = selected_excluded | excluded_by_task[task_key]
            feasible = True
            for key, requests in demands[task_key].items():
                resource = resources[key]; quantity = _known(resource.total, 'current_engineering_resource_capacity')
                evidence([quantity.basis_ref])
                if quantity.unit != profile.capacity_unit: _unsupported('engineer-capacity-unit-conversion')
                data = CapacityInput(clock_ref=now.clock_ref,
                    demands=selected_demands.get(key, []) + requests,
                    resources=[{'resource_ref': resource.resource_ref, 'resource_kind': resource.resource_kind, 'region_id': region,
                        'total': quantity, 'effective_window': resource.effective_window}],
                    commitments=[row.model_dump(mode='python') for row in calendar.commitments
                                 if row.resource_ref.key() == key and row.commitment_ref.key() not in trial_excluded], source_refs=list(sources.values()))
                if historical_capacity is not None:
                    basis = {ref.key(): ref for ref in walk_references(data) if ref.kind == 'Evidence'}
                    if not data.source_refs or not basis: _needs('original_engineering_capacity_input_provenance')
                    for ref in data.source_refs:
                        reading.resolve(ref)
                    evidence(basis.values())
                    reading.recheck()
                    report = compare_capacity(data)
                    historical_capacity.append(dict(method_ref=CAPACITY_METHOD.model_dump(mode='json'),
                        input=data.model_dump(mode='json'), comparison=report.model_dump(mode='json')))
                else:
                    result = reading.calculate(CAPACITY_METHOD, data)
                    if result.kind != 'ok':
                        if result.kind == 'invalid_input': _unsupported('engineer-planning-capacity-domain')
                        raw = result.model_dump(mode='python')
                        if result.kind == 'needs_information': raw['requested_refs'] = []
                        raise ObservationGap(raw)
                    report = result.value
                if not report.feasible: feasible = False; break
            if not feasible: blocked.append(item['task_ref']); continue
            selected.append(item); selected_excluded = trial_excluded
            for key, requests in demands[task_key].items(): selected_demands.setdefault(key, []).extend(requests)
        if not selected: return deferred('shared_engineering_personnel_capacity_unavailable', [calendar.ref])
        if historical_capacity is not None:
            reading.recheck()
            return None
        items = selected
        plan = {'work_profile_ref': profile.ref, 'items': items}
        if prior is not None: return completed('revise_plan', plan=plan, prior_plan_ref=prior.ref)
        return completed('allocate', plan=plan)
    except ObservationGap as gap:
        reading.recheck(); return gap.result
