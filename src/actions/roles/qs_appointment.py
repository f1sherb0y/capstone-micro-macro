"""QS-A03 separate appointment compatibility from authorized task planning."""
from fractions import Fraction

from src.actions.contracts.architect_appointment_objects import ArchitectReservationView
from src.actions.contracts.bank_credit_objects import unique_identities
from src.actions.contracts.qs_appointment_objects import (
    QSAllocationView, QSAcceptanceView, QSAppointmentConflictView, QSAppointmentView,
    QSTaskCalendarView, QSTaskDependencyView, QSTaskView, QSWorkPlanView,
)
from src.actions.contracts.service_objects import ServiceIntakeCapabilityView, ServiceMethodView, ServiceQualificationView, ServiceWorkProfileView
from src.actions.roles.architect_appointment import confirm_appointment
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, ExactAmount
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def confirm_qs_appointment(context, action_input, reading):
    now, organization = context.business_time, reading.organization_id
    sources = {}

    def source(read, ref, schema):
        row = read(ref, schema); sources[ref.key()] = ref
        return row

    def authorized(read, evidence, ref, function, scope):
        grant = source(read, ref, Authorization)
        assignment = source(read, function, RoleAssignment)
        evidence(grant.basis_refs + assignment.basis_refs)
        if (grant.organization_id != organization or grant.actor_id != context.actor_id or grant.function_ref != function
                or assignment.role != 'QS' or 'QS-A03' not in grant.action_ids or not grant.validity.contains(now)
                or not any(scope_covers(s, scope) for s in grant.scopes)):
            _needs('authorized_qs_task_or_plan', [ref])
        return grant

    def deferred(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
            'trigger': 'dependency_change', 'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def professional(appointment, terms, request, calendar, read, current, evidence, completed, amendment, questions):
        if not isinstance(calendar, QSTaskCalendarView): _unsupported('qs-task-calendar-schema')
        capability = source(read, appointment.capability_ref, ServiceIntakeCapabilityView)
        if capability.organization_id != organization: raise ValueError('QS capability belongs to another organization')
        if not current(capability.effective_window): _needs('current_qs_appointment_capability')
        responsibilities = set(_known(terms.responsibility_codes, 'accepted_qs_responsibilities'))
        if (not responsibilities <= set(_known(capability.responsibility_codes, 'current_qs_responsibilities'))
                or not set(_known(terms.requested_uses, 'accepted_qs_uses')) <= set(_known(capability.allowed_uses, 'current_qs_uses'))):
            return amendment('Current QS authority does not cover the accepted responsibility or deliverable use')
        check = source(read, appointment.conflict_check_ref, QSAppointmentConflictView)
        if check.organization_id != organization or check.request_ref != request.ref or check.scope != terms.scope:
            raise ValueError('QS conflict check changes original organization, request or scope')
        if check.checked_at != now or not current(check.effective_window): _needs('current_original_qs_conflict_check')
        grant = authorized(read, evidence, check.authority_ref, check.author_function_ref, check.scope)
        if grant.actor_id != check.author_actor_id or not {r.key() for r in check.evidence_refs} <= {r.key() for r in grant.readable_refs}:
            _needs('authorized_original_qs_conflict_evidence')
        if check.status == 'failed':
            return {'kind': 'technical_error', 'error': {'kind': 'unrecorded', 'correlation_id': context.operation_id,
                'code': 'qs_appointment_conflict_check_failed'}, 'retryability': 'unknown'}
        if check.status == 'unknown': _needs('original_qs_conflict_result')
        if check.status == 'conflict': return amendment('Original QS conflict check requires an adjusted appointment')
        region, service = _known(terms.region_id, 'accepted_qs_region'), _known(terms.service_code, 'accepted_qs_service')
        if (region not in _known(capability.region_ids, 'current_qs_regions')
                or service not in _known(capability.service_codes, 'current_qs_service_codes')
                or _known(terms.object_type, 'accepted_qs_object_type') not in _known(capability.object_types, 'current_qs_object_types')):
            return amendment('Accepted QS service exceeds current location or object capability')
        permitted_methods = {ref.key() for ref in _known(capability.method_refs, 'current_qs_methods')}
        for ref in _known(terms.required_method_refs, 'accepted_qs_methods'):
            if ref.key() not in permitted_methods: _unsupported('qs-appointment-required-method')
            method = source(read, ref, ServiceMethodView)
            if (not current(method.effective_window) or region not in method.region_ids or service not in method.service_codes
                    or _known(terms.object_type, 'accepted_qs_object_type') not in method.object_types):
                _unsupported('qs-appointment-method-domain')
        if capability.qualification_coverage != 'complete': _needs('complete_qs_qualification_coverage')
        qualifications = [source(read, r, ServiceQualificationView) for r in capability.qualification_refs]
        for row in qualifications:
            if row.organization_id != organization: raise ValueError('QS qualification belongs to another organization')
        for code in _known(terms.required_qualification_codes, 'accepted_qs_qualification_codes'):
            matched = [r for r in qualifications if r.code == code and current(r.effective_window)
                       and region in r.region_ids and service in r.service_codes]
            if not any(_known(r.standing, 'current_qs_qualification_standing') for r in matched):
                return amendment('No current qualification covers this accepted QS service')
        return None

    def planning(appointment, terms, request, calendar, read, current, evidence, completed, amendment):
        if action_input.capacity_ref != appointment.capacity_ref:
            raise ValueError('Task planning changes original resource calendar')
        unique_identities(action_input.task_refs); unique_identities(action_input.existing_allocation_refs)
        if (set(action_input.task_refs) != set(appointment.task_refs)
                or set(action_input.existing_allocation_refs) != set(appointment.existing_allocation_refs)):
            _needs('complete_original_qs_tasks_and_allocations')
        if not action_input.task_refs:
            if action_input.existing_allocation_refs: _needs('original_task_for_existing_allocation')
            return completed('confirm', 'Confirm original compatible appointment only; tasks and resource assignment require their separate host commands',
                appointment_ref=appointment.ref, accepted_terms_ref=terms.ref)
        if action_input.work_profile_ref is None: _needs('qs_task_planning_work_profile')
        if action_input.work_profile_ref != terms.work_profile_ref:
            raise ValueError('Task planning uses another accepted work profile version')
        profile = source(read, action_input.work_profile_ref, ServiceWorkProfileView)
        if (not current(profile.effective_window) or profile.clock_ref != now.clock_ref
                or profile.method != 'constant_capacity_over_half_open_window_v1'):
            _unsupported('qs-task-work-profile-domain')
        resources = {r.resource_ref.key(): r for r in calendar.resources}
        commitments = {r.commitment_ref.key(): r for r in calendar.commitments}
        if any(r.resource_ref.key() not in resources for r in calendar.commitments):
            raise ValueError('Current QS calendar omits a committed resource version')
        prior = None
        if appointment.prior_plan_ref is not None:
            prior = source(read, appointment.prior_plan_ref, QSWorkPlanView)
            if (prior.organization_id != organization or prior.appointment_ref != appointment.ref or prior.scope != action_input.scope
                    or prior.status != 'authorized' or set(prior.task_refs) != set(action_input.task_refs)
                    or set(prior.allocation_refs) != set(action_input.existing_allocation_refs)):
                raise ValueError('Prior QS plan changes original appointment, task or allocation identities')
            grant = source(read, prior.authority_ref, Authorization)
            authorized(read, evidence, grant.ref, grant.function_ref, action_input.scope)
        if action_input.existing_allocation_refs and prior is None: _needs('original_work_plan_for_existing_allocations')
        tasks = [source(read, ref, QSTaskView) for ref in action_input.task_refs]
        if {t.existing_allocation_ref for t in tasks if t.existing_allocation_ref is not None} != set(action_input.existing_allocation_refs):
            _needs('exact_original_task_allocation_links')
        excluded, items, demands, total = set(), [], {}, Fraction()
        allocations = {}
        for ref in action_input.existing_allocation_refs:
            row = source(read, ref, QSAllocationView)
            if (row.organization_id != organization or row.appointment_ref != appointment.ref or row.scope != action_input.scope
                    or row.work_plan_ref != prior.ref or row.status != 'active' or row.as_of != now
                    or row.task_ref not in action_input.task_refs):
                raise ValueError('Allocation changes original task, appointment, plan or current occupancy')
            allocations[row.ref.key()] = row
            unique_identities([r.commitment_ref for r in row.commitments])
            for occupied in row.commitments:
                if occupied.commitment_ref.key() in excluded: raise ValueError('Original occupancy belongs to multiple allocations')
                if commitments.get(occupied.commitment_ref.key()) != occupied:
                    _needs('exact_original_qs_allocation_occupancy', [occupied.commitment_ref])
                evidence([occupied.quantity.basis_ref]); excluded.add(occupied.commitment_ref.key())
        if appointment.reservation_ref is not None:
            reserved = source(read, appointment.reservation_ref, ArchitectReservationView)
            if (reserved.organization_id != organization or reserved.appointment_ref != appointment.ref
                    or reserved.terms_ref != terms.ref or reserved.scope != action_input.scope or reserved.as_of != now):
                raise ValueError('QS quote reservation changes original appointment or terms')
            if reserved.status != 'reserved' or not current(reserved.effective_window):
                _needs('reconcile_original_qs_reservation', [reserved.ref])
            for occupied in reserved.allocations:
                if occupied.commitment_ref.key() in excluded: raise ValueError('Allocation and reservation overlap the same occupancy')
                if commitments.get(occupied.commitment_ref.key()) != occupied:
                    _needs('exact_original_qs_reserved_occupancy', [occupied.commitment_ref])
                excluded.add(occupied.commitment_ref.key())
        region, service = _known(terms.region_id, 'accepted_qs_region'), _known(terms.service_code, 'accepted_qs_service')
        if region not in profile.region_ids or service not in profile.service_codes:
            _unsupported('qs-task-location-or-service-domain')
        accepted_window = _known(terms.desired_window, 'accepted_qs_work_window')
        if accepted_window.start.clock_ref != now.clock_ref: _unsupported('qs-accepted-work-clock')
        for task in tasks:
            if (task.organization_id != organization or task.appointment_ref != appointment.ref
                    or task.accepted_terms_ref != terms.ref or task.scope != action_input.scope
                    or task.function_ref not in action_input.function_refs or task.work_profile_ref != profile.ref
                    or task.function_code not in _known(terms.responsibility_codes, 'accepted_qs_functions')):
                raise ValueError('Task changes original appointment, terms or authorized function')
            if task.as_of != now: _needs('current_remaining_qs_task_effort')
            authorized(read, evidence, task.authority_ref, task.function_ref, task.scope)
            if task.status != 'authorized': return deferred('qs_task_not_ready', [task.ref])
            remaining = _known(task.remaining_effort, 'actual_remaining_qs_effort')
            evidence([task.total_effort.basis_ref, remaining.basis_ref])
            if remaining.unit != profile.effort_unit or task.total_effort.unit != profile.effort_unit:
                _unsupported('qs-task-effort-unit-conversion')
            total += decimal_fraction(task.total_effort.value)
            window = task.planned_window
            if window.start.clock_ref != now.clock_ref or window.bounds != 'closed_open' or window.start.offset >= window.end.offset:
                _unsupported('qs-task-window-domain')
            if (window.start.offset < now.offset or window.start.offset < profile.effective_window.start.offset
                    or window.end.offset > profile.effective_window.end.offset): _needs('current_qs_task_window')
            if not (accepted_window.start.offset <= window.start.offset and window.end.offset <= accepted_window.end.offset):
                return amendment('Task schedule extends beyond the independently accepted service window')
            for ref in task.dependency_refs:
                dependency = source(read, ref, QSTaskDependencyView)
                if dependency.task_ref != task.ref or dependency.scope != task.scope: raise ValueError('Task dependency changes original scope')
                if dependency.as_of != now: _needs('current_qs_task_dependency')
                if not _known(dependency.satisfied, 'qs_task_dependency_status'):
                    return deferred('qs_task_dependency_waiting', [dependency.ref, task.ref])
            resource_ids = []
            demand = decimal_fraction(remaining.value) / decimal_fraction(profile.effort_per_capacity_tick) / (window.end.offset - window.start.offset)
            for share in task.resource_shares:
                resource = resources.get(share.resource_ref.key())
                if resource is None: _needs('original_qs_task_resource_version')
                if (resource.resource_kind != profile.resource_kind or _known(resource.region_id, 'qs_resource_region') != region
                        or not _known(resource.suitable, 'qs_resource_suitability')):
                    return amendment('Assigned original QS resource is unsuitable for this task')
                if not _known(resource.personnel_ids, 'qs_real_resource_personnel'): _needs('qs_resource_personnel')
                resource_ids.append(resource.resource_ref.id)
                amount = demand * decimal_fraction(share.share)
                demands.setdefault(resource.resource_ref.key(), []).append({'resource_kind': profile.resource_kind,
                    'region_id': region, 'unit': profile.capacity_unit,
                    'amount': ExactAmount(numerator=amount.numerator, denominator=amount.denominator),
                    'window': window, 'basis_refs': [remaining.basis_ref]})
            if task.existing_allocation_ref is not None and allocations[task.existing_allocation_ref.key()].task_ref != task.ref:
                raise ValueError('Task borrows another task allocation')
            items.append({'task_ref': task.ref, 'resource_ids': resource_ids, 'window': window,
                'effort': remaining, 'dependency_refs': task.dependency_refs, 'existing_allocation_ref': task.existing_allocation_ref})
        accepted_effort = _known(terms.effort_estimate, 'accepted_qs_total_effort')
        if accepted_effort.unit != profile.effort_unit: _unsupported('qs-accepted-effort-unit-conversion')
        if total > decimal_fraction(accepted_effort.value): return amendment('Authorized task list exceeds the accepted service effort scope')
        for key, requests in demands.items():
            resource = resources[key]
            quantity = _known(resource.total, 'current_qs_resource_capacity'); evidence([quantity.basis_ref])
            if quantity.unit != profile.capacity_unit: _unsupported('qs-task-resource-unit-conversion')
            occupied = [r for r in calendar.commitments if r.resource_ref.key() == key and r.commitment_ref.key() not in excluded]
            for row in occupied: evidence([row.quantity.basis_ref])
            result = reading.calculate(CAPACITY_METHOD, CapacityInput(clock_ref=now.clock_ref, demands=requests,
                resources=[{'resource_ref': resource.resource_ref, 'resource_kind': resource.resource_kind, 'region_id': region,
                    'total': quantity, 'effective_window': resource.effective_window}],
                commitments=[r.model_dump(mode='python') for r in occupied],
                source_refs=[appointment.ref, terms.ref, calendar.ref, *sources.values()]))
            if result.kind != 'ok':
                if result.kind == 'invalid_input': _unsupported('qs-task-capacity-domain')
                raw = result.model_dump(mode='python')
                if result.kind == 'needs_information': raw['requested_refs'] = []
                raise ObservationGap(raw)
            if not result.value.feasible: return deferred('qs_task_shared_capacity_unavailable', [calendar.ref, *action_input.task_refs])
        plan = {'work_profile_ref': profile.ref, 'items': items}
        if prior is not None:
            return completed('revise_plan', 'Revise original authorized task plan, preserving existing allocation identities; host assignment has its own receipt',
                             plan=plan, prior_plan_ref=prior.ref)
        return completed('confirm_and_plan', 'Compatible appointment and authorized task plan are separate proposed host commands; no allocation or work is completed here',
                         appointment_ref=appointment.ref, accepted_terms_ref=terms.ref, plan=plan)

    return confirm_appointment(context, action_input, reading, role='QS', appointment_schema=QSAppointmentView,
        acceptance_schema=QSAcceptanceView, check_professional=professional, plan_tasks=planning, continue_active=True)
