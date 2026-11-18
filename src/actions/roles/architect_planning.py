"""ARCHITECT-A04 produces remaining-work plans, never completed work or fees."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, walk_references
from src.actions.contracts.architect_planning_objects import (
    ArchitectPlanningProfileView, ArchitectPlanningCalendarView, ArchitectPlanningTaskView,
    ArchitectPlanningEstimateView, ArchitectPlanningWorkFactView, ArchitectPlanningDependencyView,
    ArchitectPlanningDeliverableView, ArchitectPlanningAllocationView, ArchitectPlanningReservationView,
    ArchitectPlanningQualificationView,
    ArchitectAppointmentView, QSWorkPlanView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import ServiceTermsView, ServiceClarificationTargetView, ServiceResponseRequirementView
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, CapacityReport, ExactAmount, compare_capacity
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def recheck_original_architect_planning_capacity(context, action_input, reading):
    """Reproduce original capacity under current read grants, without an old method invocation."""
    reading.check_method_context(reading._context, 'ARCHITECT-A04')
    binding = reading._methods._bindings.get(CAPACITY_METHOD.key()) if reading._methods is not None else None
    if (CAPACITY_METHOD.key() not in reading._method_refs or binding is None
            or binding.executor is not compare_capacity or binding.input_model is not CapacityInput
            or binding.output_model is not CapacityReport or 'ARCHITECT-A04' not in binding.definition.action_ids
            or binding.definition.effect_kind != 'pure_calculation'):
        raise ValueError('Original design capacity wait requires its actual declared pure capacity method')
    comparisons = []
    result = plan_design_work(context, action_input, reading, historical_capacity=comparisons)
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'shared_design_personnel_capacity_unavailable'):
        raise ValueError('Original design sources do not reproduce the actual shared personnel capacity wait')
    return result, comparisons


def plan_design_work(context, action_input, reading, *, original_wait_only=False, historical_capacity=None):
    now, organization = context.business_time, reading.organization_id
    sources = {}

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('architect-planning-clock-alignment')

    def evidence(refs, historical=False):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('architect-planning-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_design_planning_evidence', [ref])

    def read(ref, schema, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'architect-planning-projection:{ref.kind}')
        if hasattr(row, 'scope') and row.scope != action_input.scope: raise ValueError('Design planning changes original scope')
        for field in ('available_at', 'received_at'):
            point = getattr(row, field, None)
            if point is not None:
                clock(point)
                if point.offset > now.offset: _needs('received_original_design_planning_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('effective_original_design_planning_input', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical); sources[ref.key()] = ref
        return row

    def authorize(ref, function_ref):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        if (grant.organization_id != organization or grant.actor_id != context.actor_id or grant.function_ref != function_ref
                or function.role != 'Architect' or 'ARCHITECT-A04' not in grant.action_ids
                or not any(scope_covers(scope, action_input.scope) for scope in grant.scopes)):
            raise ValueError('Design planning lacks independent original action/function/scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(now): _needs('current_design_planning_authority')
        evidence([*grant.basis_refs, *function.basis_refs])

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'scope': action_input.scope, 'note': profile.note, **fields}}

    def deferred(code, refs):
        reading.recheck(); return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
            'trigger': 'dependency_change', 'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def confirmed_effort(task):
        estimate = read(task.estimate_ref, ArchitectPlanningEstimateView, True)
        if not same(estimate.task_ref, task.ref) or not same(estimate.work_profile_ref, profile.ref):
            raise ValueError('Task borrows another task workload estimate')
        clock(estimate.executed_at)
        if estimate.effort.unit != profile.effort_unit: _unsupported('architect-task-effort-unit-conversion')
        evidence([estimate.effort.basis_ref], True)
        total = decimal_fraction(estimate.effort.value)
        if total <= 0: raise ValueError('Original task effort must be positive')
        if estimate.status != 'succeeded' or estimate.executed_at.offset > min(now.offset, estimate.available_at.offset): return None, total
        if task.work_fact_coverage != 'complete': return None, total
        keys(task.work_fact_refs); spent, investments = Fraction(), set()
        for ref in task.work_fact_refs:
            fact = read(ref, ArchitectPlanningWorkFactView, True)
            if (not same(fact.task_ref, task.ref) or fact.organization_id != organization
                    or fact.investment_key in investments): raise ValueError('Task investment repeats a slice or changes original task/organization')
            investments.add(fact.investment_key)
            clock(fact.window.start)
            if fact.status != 'committed': return None, total
            if fact.window.end.offset > min(now.offset, fact.available_at.offset): _needs('design_investment_finished_before_received')
            if fact.effort.unit != profile.effort_unit: _unsupported('architect-investment-unit-conversion')
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

    try:
        profile = read(action_input.work_profile_ref, ArchitectPlanningProfileView)
        if profile.organization_id != organization or action_input.scope != context.scope: raise ValueError('Design work profile changes original organization/scope')
        authorize(profile.authority_ref, context.function_ref)
        if profile.method != 'constant_capacity_over_half_open_window_v1' or profile.clock_ref != now.clock_ref:
            _unsupported('architect-task-work-method-domain')
        appointment = read(profile.appointment_ref, ArchitectAppointmentView)
        if appointment.provider_organization_id != organization or appointment.status != 'active' or appointment.service_relationship_ref is None:
            _needs('original_active_authorized_design_appointment')
        terms = read(appointment.terms_ref, ServiceTermsView, True)
        region = _known(terms.region_id, 'original_design_work_region')
        service = _known(terms.service_code, 'original_design_service')
        responsibilities = _known(terms.responsibility_codes, 'original_design_functions')
        accepted_window = _known(terms.desired_window, 'original_accepted_design_window'); clock(accepted_window.start)
        if region not in profile.region_ids or service not in profile.service_codes: _unsupported('architect-planning-location-or-service')
        if keys(action_input.task_refs) != keys(profile.task_refs): _needs('all_original_authorized_design_tasks', profile.task_refs)
        calendar = read(action_input.capacity_ref, ArchitectPlanningCalendarView)
        if calendar.organization_id != organization or calendar.as_of != now or calendar.coverage != 'complete':
            _needs('complete_current_cross_project_design_resource_calendar')
        resources = {row.resource_ref.key(): row for row in calendar.resources}
        people = set()
        for resource in resources.values():
            identities = _known(resource.personnel_ids, 'actual_design_personnel_ids')
            if not identities or len(set(identities)) != len(identities) or people.intersection(identities):
                raise ValueError('Design personnel are duplicated or unnamed across shared resources')
            people.update(identities)
        commitments = {row.commitment_ref.key(): row for row in calendar.commitments}
        for row in commitments.values():
            if row.resource_ref.key() not in resources: _needs('original_committed_design_resource_version')
        prior = None
        if profile.prior_plan_ref is not None:
            prior = read(profile.prior_plan_ref, QSWorkPlanView)
            if (prior.organization_id != organization or not same(prior.appointment_ref, appointment.ref)
                    or prior.status != 'authorized'): raise ValueError('Revised design plan changes original appointment or authorization')
            authorize(prior.authority_ref, context.function_ref)
        tasks = sorted([read(ref, ArchitectPlanningTaskView) for ref in action_input.task_refs], key=lambda row: (row.planned_window.start.offset, row.ref.key()))
        expected_allocations = [row.existing_allocation_ref for row in tasks if row.existing_allocation_ref is not None]
        if keys(expected_allocations) != keys(action_input.existing_allocation_refs): _needs('all_original_design_task_allocation_links')
        allocations = {}
        for ref in action_input.existing_allocation_refs:
            row = read(ref, ArchitectPlanningAllocationView)
            if (prior is None or row.organization_id != organization or not same(row.appointment_ref, appointment.ref)
                    or not same(row.work_plan_ref, prior.ref) or row.as_of != now or row.task_ref.key() not in keys(action_input.task_refs)
                    or row.ref.key() not in keys(prior.allocation_refs)):
                raise ValueError('Design allocation changes original task/appointment/plan')
            allocations[ref.key()] = row
        reservations = [read(ref, ArchitectPlanningReservationView) for ref in profile.reservation_refs]
        for row in reservations:
            if row.organization_id != organization or not same(row.appointment_ref, appointment.ref) or row.as_of != now:
                raise ValueError('Design reservation changes original appointment/organization/snapshot')
        dependency_deliverables, blocked, items, demands, excluded = set(), [], [], {}, set()
        excluded_by_task = {}
        authorized_effort = Fraction()
        for task in tasks:
            if (task.organization_id != organization or not same(task.appointment_ref, appointment.ref)
                    or not same(task.accepted_terms_ref, terms.ref) or not same(task.work_profile_ref, profile.ref)
                    or task.function_code not in responsibilities or task.as_of != now):
                raise ValueError('Design task changes original appointment, terms, function or snapshot')
            authorize(task.authority_ref, task.function_ref)
            remaining, total = confirmed_effort(task); authorized_effort += total
            ready = task.status in {'authorized', 'waiting'} and remaining is not None and decimal_fraction(remaining.value) > 0
            if task.status == 'complete' and (remaining is None or decimal_fraction(remaining.value)):
                raise ValueError('Completed design task lacks fully confirmed actual investment')
            keys(task.dependency_refs)
            for ref in task.dependency_refs:
                dep = read(ref, ArchitectPlanningDependencyView)
                if not same(dep.task_ref, task.ref) or dep.as_of != now: raise ValueError('Design dependency changes original task/snapshot')
                satisfied = isinstance(dep.satisfied, Known) and dep.satisfied.value
                if dep.deliverable_ref is not None:
                    dependency_deliverables.add(dep.deliverable_ref.key())
                    deliverable = read(dep.deliverable_ref, ArchitectPlanningDeliverableView, True)
                    satisfied &= (deliverable.status == 'available' and deliverable.effective_window.contains(now)
                                  and dep.required_use in deliverable.allowed_uses and dep.required_use not in deliverable.invalidated_uses)
                if dep.predecessor_task_ref is not None:
                    predecessor = next((row for row in tasks if same(row.ref, dep.predecessor_task_ref)), None)
                    if predecessor is None: predecessor = read(dep.predecessor_task_ref, ArchitectPlanningTaskView)
                    if predecessor.organization_id != organization or not same(predecessor.appointment_ref, appointment.ref):
                        raise ValueError('Design dependency borrows another organization/appointment task')
                    predecessor_remaining, _ = confirmed_effort(predecessor)
                    satisfied &= predecessor.status == 'complete' and predecessor_remaining is not None and decimal_fraction(predecessor_remaining.value) == 0
                if dep.deliverable_ref is None and dep.predecessor_task_ref is None: _needs('original_design_dependency_target')
                if not satisfied: ready = False; blocked.append(dep.ref)
            if not ready:
                blocked.append(task.ref); continue
            window = task.planned_window; clock(window.start)
            if (window.bounds != 'closed_open' or window.start.offset >= window.end.offset
                    or window.start.offset < now.offset): _needs('current_nonempty_design_task_window')
            if not (accepted_window.start.offset <= window.start.offset < window.end.offset <= accepted_window.end.offset
                    and profile.effective_window.start.offset <= window.start.offset < window.end.offset <= profile.effective_window.end.offset):
                _needs('design_task_window_within_original_authorized_method_and_appointment')
            keys([row.resource_ref for row in task.resource_shares])
            if any(decimal_fraction(row.share) <= 0 for row in task.resource_shares) or sum(decimal_fraction(row.share) for row in task.resource_shares) != 1:
                raise ValueError('Design task resource shares must be positive and conserve remaining effort')
            resource_ids, task_demands, task_excluded = [], {}, set()
            suitable = True
            for share in task.resource_shares:
                resource = resources.get(share.resource_ref.key())
                if resource is None: _needs('original_design_task_resource_version')
                if (resource.resource_kind != profile.resource_kind or _known(resource.region_id, 'design_resource_region') != region
                        or task.function_code not in resource.function_codes or not _known(resource.suitable, 'design_personnel_suitability')):
                    suitable = False; break
                keys(resource.qualification_refs)
                if not resource.qualification_refs: _needs('original_design_personnel_qualification')
                for ref in resource.qualification_refs:
                    qualification = read(ref, ArchitectPlanningQualificationView)
                    if qualification.organization_id != organization: raise ValueError('Personnel borrow another organization qualification')
                    if (region not in qualification.region_ids or service not in qualification.service_codes
                            or task.function_code not in qualification.function_codes
                            or not set(_known(resource.personnel_ids, 'actual_design_personnel')) <= set(qualification.personnel_ids)
                            or not _known(qualification.standing, 'design_personnel_qualification_standing')):
                        suitable = False; break
                if not suitable: break
                rate = decimal_fraction(remaining.value) * decimal_fraction(share.share) / decimal_fraction(profile.effort_per_capacity_tick) / (window.end.offset - window.start.offset)
                task_demands.setdefault(resource.resource_ref.key(), []).append({'resource_kind': profile.resource_kind,
                    'region_id': region, 'unit': profile.capacity_unit, 'amount': ExactAmount.from_fraction(rate),
                    'window': window, 'basis_refs': [remaining.basis_ref]})
                resource_ids.append(resource.resource_ref.id)
            if not suitable: blocked.append(task.ref); continue
            if task.existing_allocation_ref is not None:
                original = allocations[task.existing_allocation_ref.key()]
                if not same(original.task_ref, task.ref) or not keys(original.work_fact_refs) <= keys(task.work_fact_refs):
                    raise ValueError('Design task borrows another task occupancy or loses original investments')
                if original.status == 'active':
                    for row in original.commitments:
                        if commitments.get(row.commitment_ref.key()) != row or row.commitment_ref.key() in excluded:
                            raise ValueError('Design allocation loses or duplicates original shared-calendar occupancy')
                        excluded.add(row.commitment_ref.key()); task_excluded.add(row.commitment_ref.key())
            for reservation in reservations:
                if reservation.status != 'reserved': continue
                for item in reservation.items:
                    if same(item.task_ref, task.ref):
                        row = item.commitment
                        if commitments.get(row.commitment_ref.key()) != row or row.commitment_ref.key() in excluded:
                            raise ValueError('Design reservation loses or duplicates original occupancy')
                        excluded.add(row.commitment_ref.key()); task_excluded.add(row.commitment_ref.key())
            demands[task.ref.key()] = task_demands
            excluded_by_task[task.ref.key()] = task_excluded
            items.append({'task_ref': task.ref, 'resource_ids': resource_ids, 'window': window, 'effort': remaining,
                          'dependency_refs': task.dependency_refs, 'existing_allocation_ref': task.existing_allocation_ref})
        if dependency_deliverables != keys(action_input.dependency_refs): _needs('all_original_design_dependency_deliverables')
        accepted_effort = _known(terms.effort_estimate, 'original_accepted_design_effort')
        if accepted_effort.unit != profile.effort_unit or authorized_effort > decimal_fraction(accepted_effort.value):
            _needs('authorized_design_task_increment_within_original_effort_scope')
        if not items:
            questions = []
            for ref in profile.question_target_refs:
                target = read(ref, ServiceClarificationTargetView); response = read(target.response_requirement_ref, ServiceResponseRequirementView)
                if (target.request_ref != appointment.request_ref or response.request_ref != appointment.request_ref
                        or not target.recipient_ids or not set(target.recipient_ids) <= set(response.recipient_ids)):
                    raise ValueError('Design input question changes original request or recipient authority')
                questions.append({'scope': action_input.scope, 'target_refs': [target.ref], 'question': target.question,
                    'recipient_ids': target.recipient_ids, 'evidence_refs': target.evidence_refs,
                    'blocking_uses': target.blocking_uses, 'response_requirement_ref': response.ref})
            if questions: return completed('request_inputs', questions=questions)
            return deferred('original_design_tasks_waiting_or_already_invested', blocked or [profile.ref])
        if original_wait_only:
            # Historical task waits must be reproduced before any capacity method.
            reading.recheck()
            return None
        selected, selected_demands, selected_excluded = [], {}, set()
        for item in items:
            task_key = item['task_ref'].key()
            trial_excluded = selected_excluded | excluded_by_task[task_key]
            feasible = True
            for key, requests in demands[task_key].items():
                resource = resources[key]; quantity = _known(resource.total, 'current_design_resource_capacity')
                evidence([quantity.basis_ref])
                if quantity.unit != profile.capacity_unit: _unsupported('architect-capacity-unit-conversion')
                data = CapacityInput(clock_ref=now.clock_ref,
                    demands=selected_demands.get(key, []) + requests,
                    resources=[{'resource_ref': resource.resource_ref, 'resource_kind': resource.resource_kind, 'region_id': region,
                        'total': quantity, 'effective_window': resource.effective_window}],
                    commitments=[row.model_dump(mode='python') for row in calendar.commitments
                                 if row.resource_ref.key() == key and row.commitment_ref.key() not in trial_excluded], source_refs=list(sources.values()))
                if historical_capacity is not None:
                    basis = {ref.key(): ref for ref in walk_references(data) if ref.kind == 'Evidence'}
                    if not data.source_refs or not basis: _needs('original_design_capacity_input_provenance')
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
                        if result.kind == 'invalid_input': _unsupported('architect-planning-capacity-domain')
                        raw = result.model_dump(mode='python')
                        if result.kind == 'needs_information': raw['requested_refs'] = []
                        raise ObservationGap(raw)
                    report = result.value
                if not report.feasible: feasible = False; break
            if not feasible: blocked.append(item['task_ref']); continue
            selected.append(item); selected_excluded = trial_excluded
            for key, requests in demands[task_key].items(): selected_demands.setdefault(key, []).extend(requests)
        if not selected: return deferred('shared_design_personnel_capacity_unavailable', [calendar.ref])
        if historical_capacity is not None:
            reading.recheck()
            return None
        items = selected
        plan = {'work_profile_ref': profile.ref, 'items': items}
        if prior is not None: return completed('revise_plan', plan=plan, prior_plan_ref=prior.ref)
        return completed('allocate', plan=plan)
    except ObservationGap as gap:
        reading.recheck(); return gap.result
