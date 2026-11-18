"""Build the original A12 capacity calculation from actual work, personnel and occupancy."""
from fractions import Fraction

from src.actions.contracts.common import Known
from src.actions.contracts.government_feedback_objects import (
    GovFeedbackWorkView, GovFeedbackEstimateView, GovFeedbackCalendarView,
    GovReviewResourceView, GovReviewQualificationView,
)
from src.coordination.tasks import TaskConflict
from src.methods.capacity import (
    CAPACITY_METHOD, CapacityInput, CapacityDemand, CapacityResource, ExactAmount, compare_capacity,
)
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def read_feedback_capacity(*, reading, old, current, original_context, context):
    proof_rows, proof_refs, versions = [], [], []

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Feedback capacity lacks exact actual work/estimate/resource source')
        proof_rows.append(row)
        return row

    def authorize(ref, actor, function_ref, action_id, scope, window, organization_id):
        grant, function = reading.resolve(ref), reading.resolve(function_ref)
        if (not isinstance(grant, Authorization) or grant.ref != ref
                or not isinstance(function, RoleAssignment) or function.function_ref != function_ref
                or function.role != 'Government' or grant.actor_id != actor or grant.function_ref != function_ref
                or grant.organization_id != organization_id or action_id not in grant.action_ids
                or not any(scope_covers(covered, scope) for covered in grant.scopes)
                or grant.validity.start.clock_ref != window.start.clock_ref or not grant.validity.contains(window.start)
                or grant.validity.end is None or grant.validity.end.offset < window.end.offset):
            raise TaskConflict('Feedback capacity lacks actual original executor authority for the entire work window')
        proof_refs.extend([*grant.basis_refs, *function.basis_refs])

    for selected, invocation in ((old, original_context), (current, context)):
        profile, authority = selected['observation_profile_ref'], selected['working_authority_ref']
        plan, now = profile.work_plan, invocation.business_time
        work = read(plan.work_profile_ref, GovFeedbackWorkView)
        calendar = read(authority.calendar_ref, GovFeedbackCalendarView)
        if (work.organization_id != reading.organization_id or work.method != 'constant_capacity_over_half_open_window_v1'
                or work.effort_per_capacity_tick.unit != work.effort_unit
                or calendar.organization_id != reading.organization_id or calendar.as_of != now or calendar.coverage != 'complete'):
            raise TaskConflict('Feedback capacity changes actual agency/work method or full calendar snapshot')
        productivity = decimal_fraction(work.effort_per_capacity_tick.value)
        if productivity <= 0:
            raise TaskConflict('Feedback capacity has no positive sourced productivity')
        proof_refs.append(work.effort_per_capacity_tick.basis_ref)
        resources, people = {}, set()
        for embedded in calendar.resources:
            resource = read(embedded.ref, GovReviewResourceView)
            if (resource != embedded or resource.ref.id in resources or resource.organization_id != reading.organization_id
                    or not isinstance(resource.personnel_ids, Known) or not resource.personnel_ids.value
                    or len(set(resource.personnel_ids.value)) != len(resource.personnel_ids.value)
                    or people.intersection(resource.personnel_ids.value)):
                raise TaskConflict('Feedback capacity duplicates or substitutes actual agency personnel')
            people.update(resource.personnel_ids.value)
            resources[resource.ref.id] = resource
            proof_refs.append(resource.total.basis_ref)
        commitments = {row.commitment_ref.key(): row for row in calendar.commitments}
        if (len(commitments) != len(calendar.commitments)
                or len({row.commitment_ref.key()[:2] for row in calendar.commitments}) != len(calendar.commitments)
                or set(calendar.commitment_assignment_refs) != {row.commitment_ref.id for row in calendar.commitments}):
            raise TaskConflict('Feedback capacity changes actual unique commitments or assignment attribution')
        proof_refs.extend(row.quantity.basis_ref for row in calendar.commitments)
        demands, excluded, estimates = [], set(), {}
        for item in plan.items:
            task = selected['tasks'][item.task_ref.key()[:2]]
            window = item.window
            if (window.start.clock_ref != now.clock_ref or window.end.clock_ref != now.clock_ref
                    or window.bounds != 'closed_open' or window.end.offset <= window.start.offset
                    or window.start.offset < now.offset or window.start.offset < authority.allowed_window.start.offset
                    or window.end.offset > authority.allowed_window.end.offset):
                if selected is current:
                    return 'waiting'
                raise TaskConflict('Original feedback capacity wait has no authorized future work window')
            estimate = read(task.estimate_ref, GovFeedbackEstimateView)
            estimates[task.ref.key()[:2]] = estimate
            if (estimate.task_ref != task.ref or estimate.work_profile_ref != work.ref or estimate.status != 'succeeded'
                    or estimate.executed_at.clock_ref != now.clock_ref or estimate.executed_at.offset > estimate.authored_at.offset
                    or not isinstance(task.remaining_effort, Known) or item.effort != estimate.remaining_effort
                    or task.remaining_effort.value != item.effort or item.effort.unit != work.effort_unit):
                raise TaskConflict('Feedback capacity rewrites original actually estimated remaining effort')
            proof_refs.append(item.effort.basis_ref)
            effort = decimal_fraction(item.effort.value)
            shares = [decimal_fraction(value) for value in task.resource_effort_shares.values()]
            if (effort <= 0 or any(value <= 0 for value in shares) or sum(shares, Fraction()) != 1
                    or not item.resource_ids or len(set(item.resource_ids)) != len(item.resource_ids)
                    or set(item.resource_ids) != set(task.resource_effort_shares) or not task.discipline_codes):
                raise TaskConflict('Feedback capacity changes original positive effort or conserved personnel shares')
            authorize(task.authority_ref, task.actor_id, task.function_ref, task.execution_action_id,
                task.scope, window, reading.organization_id)
            if item.existing_assignment_ref is not None:
                assignment = selected['assignments'][item.existing_assignment_ref.key()[:2]]
                if assignment.status == 'unknown':
                    if selected is current:
                        return 'waiting'
                    raise TaskConflict('Original capacity wait bypasses an unknown assignment')
                if assignment.status == 'effective':
                    held = {ref.key() for ref in assignment.commitment_refs}
                    if (assignment.ref not in authority.replacement_assignment_refs or not held or held & excluded
                            or any(key not in commitments or calendar.commitment_assignment_refs[commitments[key].commitment_ref.id] != assignment.ref
                                for key in held)):
                        raise TaskConflict('Feedback capacity excludes occupancy without independent atomic replacement permission')
                    excluded.update(held)
            for resource_id in item.resource_ids:
                resource = resources.get(resource_id)
                if (resource is None or resource.region_id != task.region_id or task.function_code not in resource.function_codes
                        or not set(task.discipline_codes) <= set(resource.discipline_codes) or resource.total.unit != work.capacity_unit):
                    raise TaskConflict('Feedback capacity substitutes original executor region/function/discipline/units')
                authorize(resource.authority_ref, resource.actor_id, resource.function_ref, task.execution_action_id,
                    task.scope, window, reading.organization_id)
                if (not resource.effective_window.contains(window.start) or resource.effective_window.end is None
                        or resource.effective_window.end.offset < window.end.offset):
                    return 'unavailable'
                qualifications = [read(ref, GovReviewQualificationView) for ref in resource.qualification_refs]
                for person in resource.personnel_ids.value:
                    if not all(any(row.organization_id == reading.organization_id and person in row.personnel_ids
                            and row.region_id == task.region_id and discipline in row.discipline_codes
                            and task.function_code in row.function_codes and isinstance(row.valid, Known) and row.valid.value
                            and row.effective_window.contains(window.start) and row.effective_window.end is not None
                            and row.effective_window.end.offset >= window.end.offset for row in qualifications)
                            for discipline in task.discipline_codes):
                        return 'waiting'
                amount = effort * decimal_fraction(task.resource_effort_shares[resource_id]) / productivity / (window.end.offset - window.start.offset)
                demands.append(CapacityDemand(resource_kind=resource.ref.id, region_id=resource.region_id, unit=resource.total.unit,
                    amount=ExactAmount.from_fraction(amount), window=window,
                    basis_refs=[item.effort.basis_ref, work.effort_per_capacity_tick.basis_ref]))
        if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset for row in proof_rows):
            # Original and current versions share one guarded reading, but each
            # capacity input can only use the sources actually available at its time.
            return 'unavailable'
        data = CapacityInput(clock_ref=now.clock_ref, demands=demands,
            resources=[CapacityResource(resource_ref=row.ref, resource_kind=row.ref.id, region_id=row.region_id,
                total=row.total, effective_window=row.effective_window) for row in calendar.resources],
            commitments=[row for row in calendar.commitments if row.commitment_ref.key() not in excluded],
            source_refs=[calendar.ref, work.ref, authority.ref, *[item.task_ref for item in plan.items]])
        versions.append(dict(work=work, calendar=calendar, resources=resources, estimates=estimates,
            excluded=sorted(excluded), data=data))
    before, after = versions
    if (before['work'].ref.key()[:2] != after['work'].ref.key()[:2]
            or any(getattr(before['work'], field) != getattr(after['work'], field)
                for field in ('method', 'effort_unit', 'capacity_unit', 'effort_per_capacity_tick'))
            or before['calendar'].ref.key()[:2] != after['calendar'].ref.key()[:2]):
        raise TaskConflict('Feedback capacity replaces original work productivity/units or calendar identity')
    for key, estimate in before['estimates'].items():
        other = after['estimates'][key]
        if estimate.model_dump(exclude={'ref', 'task_ref', 'work_profile_ref'}) != other.model_dump(exclude={'ref', 'task_ref', 'work_profile_ref'}):
            raise TaskConflict('Feedback capacity rewrites original successful work estimate')
    for resource_id in {resource_id for item in current['observation_profile_ref'].work_plan.items for resource_id in item.resource_ids}:
        a, b = before['resources'][resource_id], after['resources'][resource_id]
        if (a.personnel_ids != b.personnel_ids or a.actor_id != b.actor_id or a.function_ref.key()[:2] != b.function_ref.key()[:2]
                or a.region_id != b.region_id or a.total.unit != b.total.unit):
            raise TaskConflict('Feedback capacity substitutes original physical personnel/executor or units')
    retained = {row.commitment_ref.key()[:2]: row for row in after['calendar'].commitments}
    for original in before['calendar'].commitments:
        actual = retained.get(original.commitment_ref.key()[:2])
        # Removed occupancy is passed in both calendar snapshots to the native
        # validator, which must authenticate actual release before readiness.
        if actual is None:
            continue
        original_assignment = before['calendar'].commitment_assignment_refs[original.commitment_ref.id]
        actual_assignment = after['calendar'].commitment_assignment_refs[actual.commitment_ref.id]
        if (original.resource_ref.key()[:2] != actual.resource_ref.key()[:2]
                or original.quantity != actual.quantity or original.window != actual.window
                or original_assignment.key()[:2] != actual_assignment.key()[:2]):
            raise TaskConflict('Feedback capacity rewrites retained occupancy quantity/window/assignment')
    if compare_capacity(before['data']).feasible:
        raise TaskConflict('Feedback recovery does not match an original infeasible capacity calculation')
    result = reading.calculate(CAPACITY_METHOD, after['data'])
    if result.kind != 'ok':
        return 'unavailable'
    return dict(ready=result.value.feasible, proof_rows=proof_rows, proof_refs=proof_refs,
        history=dict(original_data=before['data'].model_dump(mode='json'), data=after['data'].model_dump(mode='json'),
            original_calendar=before['calendar'].model_dump(mode='json'), calendar=after['calendar'].model_dump(mode='json'),
            original_excluded=before['excluded'], excluded=after['excluded'], report=result.value.model_dump(mode='json')))
