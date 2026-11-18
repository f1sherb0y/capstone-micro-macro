"""Build exact A03 capacity inputs while preserving already occupied resources."""
from fractions import Fraction

from src.actions.contracts.architect_appointment_objects import ArchitectReservationView
from src.actions.contracts.qs_appointment_objects import QSWorkPlanView, QSTaskDependencyView
from src.coordination.tasks import TaskConflict
from src.methods.capacity import CapacityInput, ExactAmount
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def read_appointment_capacity(*, version, read, proof_refs, now):
    """Read complete planning history and subtract only exact owned occupancy.

    Return a wait state when current facts are unavailable. Historical and current
    inputs remain separate; their publication lineage is validated by the native
    source callback before any successor is registered.
    """
    appointment, terms, calendar, profile = (version[field] for field in ('appointment', 'terms', 'calendar', 'profile'))
    tasks, allocations = version['tasks'], version['allocations']
    if not tasks or calendar.coverage != 'complete' or calendar.as_of != now:
        return 'unavailable'
    if (profile.clock_ref != now.clock_ref or not profile.effective_window.contains(now)
            or profile.method != 'constant_capacity_over_half_open_window_v1'):
        return 'unavailable'

    def known(value):
        return value.value if value.state == 'known' else None

    region, service = known(terms.region_id), known(terms.service_code)
    window, accepted_effort = known(terms.desired_window), known(terms.effort_estimate)
    if (region is None or service is None or window is None or accepted_effort is None
            or region not in profile.region_ids or service not in profile.service_codes
            or window.start.clock_ref != now.clock_ref or accepted_effort.unit != profile.effort_unit):
        return 'unavailable'
    proof_refs.append(accepted_effort.basis_ref)
    resources = {row.resource_ref.key(): row for row in calendar.resources}
    commitments = {row.commitment_ref.key(): row for row in calendar.commitments}
    if any(row.resource_ref.key() not in resources for row in calendar.commitments):
        raise TaskConflict('QS capacity calendar omits an occupied resource version')
    prior = None
    if appointment.prior_plan_ref is not None:
        prior = read(appointment.prior_plan_ref, QSWorkPlanView)
        if (prior.organization_id != calendar.organization_id or prior.appointment_ref != appointment.ref
                or prior.scope != terms.scope or prior.status != 'authorized'
                or set(prior.task_refs) != {row.ref for row in tasks.values()}
                or set(prior.allocation_refs) != {row.ref for row in allocations.values()}):
            raise TaskConflict('QS capacity recovery substitutes its original plan/task/allocation set')
        grant = read(prior.authority_ref, Authorization)
        function = read(grant.function_ref, RoleAssignment)
        if (grant.organization_id != calendar.organization_id or function.role != 'QS'
                or function.function_ref != grant.function_ref or grant.actor_id != appointment.provider_id
                or 'QS-A03' not in grant.action_ids or not grant.validity.contains(now)
                or not any(scope_covers(scope, terms.scope) for scope in grant.scopes)):
            raise TaskConflict('QS capacity plan borrows another organization or function authority')
        proof_refs.extend([*grant.basis_refs, *function.basis_refs])
    if allocations and prior is None:
        raise TaskConflict('QS capacity recovery excludes allocations without their original authorized plan')
    if {row.existing_allocation_ref for row in tasks.values() if row.existing_allocation_ref is not None} != {
            row.ref for row in allocations.values()}:
        raise TaskConflict('QS capacity recovery replaces its exact task/allocation links')
    excluded = set()

    def exclude(rows):
        for row in rows:
            key = row.commitment_ref.key()
            if key in excluded or commitments.get(key) != row:
                raise TaskConflict('QS capacity recovery double-counts or substitutes original occupancy')
            excluded.add(key); proof_refs.append(row.quantity.basis_ref)

    for row in allocations.values():
        if (row.organization_id != calendar.organization_id or row.appointment_ref != appointment.ref
                or row.scope != terms.scope or row.work_plan_ref != prior.ref
                or row.task_ref not in {task.ref for task in tasks.values()}):
            raise TaskConflict('QS capacity recovery borrows another original allocation')
        if row.status != 'active' or row.as_of != now:
            return 'unavailable'
        exclude(row.commitments)
    reservation = None
    if appointment.reservation_ref is not None:
        reservation = read(appointment.reservation_ref, ArchitectReservationView)
        if (reservation.organization_id != calendar.organization_id or reservation.appointment_ref != appointment.ref
                or reservation.terms_ref != terms.ref or reservation.scope != terms.scope):
            raise TaskConflict('QS capacity recovery borrows another original quote reservation')
        if reservation.as_of != now or reservation.status != 'reserved' or not reservation.effective_window.contains(now):
            return 'unavailable'
        exclude(reservation.allocations)
    demands, total = {}, Fraction()
    dependencies = []
    for task in tasks.values():
        remaining = known(task.remaining_effort)
        if task.status != 'authorized' or task.as_of != now:
            return 'waiting'
        if (remaining is None or remaining.unit != profile.effort_unit or task.total_effort.unit != profile.effort_unit
                or task.planned_window.start.clock_ref != now.clock_ref or task.planned_window.bounds != 'closed_open'
                or task.planned_window.start.offset >= task.planned_window.end.offset
                or task.planned_window.start.offset < now.offset
                or task.planned_window.start.offset < max(window.start.offset, profile.effective_window.start.offset)
                or task.planned_window.end.offset > min(window.end.offset, profile.effective_window.end.offset)):
            return 'unavailable'
        if terms.responsibility_codes.state != 'known' or task.function_code not in terms.responsibility_codes.value:
            return 'unavailable'
        for ref in task.dependency_refs:
            dependency = read(ref, QSTaskDependencyView)
            if dependency.task_ref != task.ref or dependency.scope != task.scope:
                raise TaskConflict('QS capacity recovery borrows another task dependency')
            dependencies.append(dependency.model_dump(mode='json'))
            if dependency.as_of != now or known(dependency.satisfied) is not True:
                return 'waiting'
        if task.existing_allocation_ref is not None:
            allocation = allocations.get(task.existing_allocation_ref.key()[:2])
            if allocation is None or allocation.ref != task.existing_allocation_ref or allocation.task_ref != task.ref:
                raise TaskConflict('QS capacity task borrows another existing allocation')
        total += decimal_fraction(task.total_effort.value)
        proof_refs.extend([task.total_effort.basis_ref, remaining.basis_ref])
        rate = decimal_fraction(remaining.value) / decimal_fraction(profile.effort_per_capacity_tick) / (
            task.planned_window.end.offset - task.planned_window.start.offset)
        for share in task.resource_shares:
            resource = resources.get(share.resource_ref.key())
            if (resource is None or resource.resource_kind != profile.resource_kind or known(resource.region_id) != region
                    or known(resource.suitable) is not True or not known(resource.personnel_ids)):
                return 'unavailable'
            amount = rate * decimal_fraction(share.share)
            demands.setdefault(share.resource_ref.key(), []).append(dict(resource_kind=profile.resource_kind,
                region_id=region, unit=profile.capacity_unit, amount=ExactAmount.from_fraction(amount),
                window=task.planned_window, basis_refs=[remaining.basis_ref]))
    if total > decimal_fraction(accepted_effort.value):
        return 'unavailable'
    inputs = []
    source_refs = [appointment.ref, terms.ref, calendar.ref, profile.ref, *[task.ref for task in tasks.values()],
        *[row.ref for row in allocations.values()]]
    if prior is not None:
        source_refs.extend([prior.ref, grant.ref, grant.function_ref])
    if reservation is not None:
        source_refs.append(reservation.ref)
    source_refs.extend(ref for task in tasks.values() for ref in task.dependency_refs)
    source_refs = list({ref.key(): ref for ref in source_refs}.values())
    for key, requests in demands.items():
        resource = resources[key]; quantity = known(resource.total)
        if quantity is None or quantity.unit != profile.capacity_unit:
            return 'unavailable'
        proof_refs.append(quantity.basis_ref)
        occupied = [row for row in calendar.commitments if row.resource_ref.key() == key and row.commitment_ref.key() not in excluded]
        proof_refs.extend(row.quantity.basis_ref for row in occupied)
        inputs.append(CapacityInput(clock_ref=now.clock_ref, demands=requests,
            resources=[dict(resource_ref=resource.resource_ref, resource_kind=resource.resource_kind, region_id=region,
                total=quantity, effective_window=resource.effective_window)],
            commitments=[row.model_dump(mode='python') for row in occupied], source_refs=source_refs))
    return dict(inputs=inputs, history=dict(prior_plan=None if prior is None else prior.model_dump(mode='json'),
        reservation=None if reservation is None else reservation.model_dump(mode='json'), dependencies=dependencies,
        excluded_commitments=[list(key) for key in sorted(excluded, key=str)]))
