"""Read original inspection occupancy and construct an exact current capacity input."""
from fractions import Fraction

from src.actions.contracts.government_inspection_objects import (
    GovReviewCalendarView, GovReviewResourceView, GovReviewAssignmentView, GovReviewQualificationView,
)
from src.coordination.government_inspection_work_history import read_inspection_work_history
from src.coordination.tasks import TaskConflict
from src.methods.capacity import CapacityCommitment, CapacityInput, ExactAmount
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def read_inspection_capacity(*, reading, original, task, original_calendar_ref, now):
    """Return current capacity inputs plus retained native occupancy evidence.

    Native validation must authenticate calendar completeness and actual
    releases or changes to original occupancy. Missing old commitments are
    never interpreted here as release. Reused commitments require the same
    existing assignment; new capacity demand reserves nothing.
    """
    if (original.choice != 'plan' or task.choice != 'plan' or original.resource_calendar_ref is None
            or original.resource_calendar_ref.key() != original_calendar_ref.key()
            or task.resource_calendar_ref is None
            or task.resource_calendar_ref.key()[:2] != original_calendar_ref.key()[:2]):
        raise TaskConflict('Inspection capacity recovery replaces its original plan or resource calendar')
    old_calendar, calendar = reading.resolve(original_calendar_ref), reading.resolve(task.resource_calendar_ref)
    if (not isinstance(old_calendar, GovReviewCalendarView) or not isinstance(calendar, GovReviewCalendarView)
            or old_calendar.ref.key() != original_calendar_ref.key() or calendar.ref != task.resource_calendar_ref
            or old_calendar.organization_id != task.organization_id or calendar.organization_id != task.organization_id
            or old_calendar.scope != calendar.scope or not scope_covers(task.scope, calendar.scope)):
        raise TaskConflict('Inspection capacity recovery replaces original agency or calendar coverage')
    if (calendar.available_at.clock_ref != now.clock_ref or calendar.available_at.offset > now.offset
            or not calendar.effective_window.contains(now)):
        return 'unavailable'
    if calendar.coverage != 'complete' or calendar.as_of != now:
        return 'waiting'
    if old_calendar.coverage != 'complete' or old_calendar.as_of != original.as_of:
        raise TaskConflict('Inspection capacity recovery lacks the original complete calendar read point')
    original_shares = {share.resource_ref.key()[:2]: decimal_fraction(share.share) for share in original.resource_shares}
    current_shares = {share.resource_ref.key()[:2]: decimal_fraction(share.share) for share in task.resource_shares}
    if (len(original_shares) != len(original.resource_shares) or len(current_shares) != len(task.resource_shares)
            or original_shares != current_shares):
        raise TaskConflict('Inspection capacity recovery replaces original physical resources or demand shares')
    if (original.existing_assignment_ref is not None and (task.existing_assignment_ref is None
            or original.existing_assignment_ref.key()[:2] != task.existing_assignment_ref.key()[:2])):
        raise TaskConflict('Inspection capacity recovery drops the original assignment')
    work_history = read_inspection_work_history(reading=reading, original=original, task=task, now=now)
    if isinstance(work_history, str):
        return work_history
    if decimal_fraction(original.remaining_effort.value.value) <= 0:
        raise TaskConflict('Original inspection capacity wait has no positive remaining work')
    proof_rows, proof_refs = work_history['proof_rows'], work_history['proof_refs']
    proof_rows.extend([(old_calendar, False), (calendar, True)])
    resources, commitments, old_resources, old_commitments = {}, {}, {}, {}
    for selected, resource_map, commitment_map, current in (
            (old_calendar, old_resources, old_commitments, False), (calendar, resources, commitments, True)):
        personnel = set()
        for embedded in selected.resources:
            row = reading.resolve(embedded.ref)
            if (not isinstance(row, GovReviewResourceView) or row != embedded or row.organization_id != task.organization_id
                    or row.ref.key()[:2] in resource_map or not scope_covers(task.scope, row.scope)):
                raise TaskConflict('Inspection capacity calendar substitutes or aliases an actual resource')
            if row.personnel_ids.state != 'known':
                return 'waiting'
            if current and (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now)):
                return 'unavailable'
            persons = row.personnel_ids.value
            if len(set(persons)) != len(persons) or personnel.intersection(persons):
                raise TaskConflict('Inspection capacity calendar aliases physical personnel across resources')
            personnel.update(persons)
            resource_map[row.ref.key()[:2]] = row
            proof_rows.append((row, current))
            proof_refs.append((row.total.basis_ref, current))
        for embedded in selected.commitments:
            row = reading.resolve(embedded.commitment_ref)
            resource = resource_map.get(row.resource_ref.key()[:2]) if isinstance(row, CapacityCommitment) else None
            if (not isinstance(row, CapacityCommitment) or row != embedded or resource is None
                    or row.resource_ref != resource.ref or row.commitment_ref.key()[:2] in commitment_map):
                raise TaskConflict('Inspection capacity calendar substitutes an actual original commitment')
            commitment_map[row.commitment_ref.key()[:2]] = row
            proof_refs.append((row.quantity.basis_ref, current))
    for key, old in old_commitments.items():
        current = commitments.get(key)
        if current is not None and (current.resource_ref.key()[:2] != old.resource_ref.key()[:2]
                or current.quantity != old.quantity or current.window != old.window):
            raise TaskConflict('Inspection capacity recovery rewrites retained original occupancy')
    history = {'original_calendar': old_calendar.model_dump(mode='json'), 'calendar': calendar.model_dump(mode='json'),
        'work_history': work_history['histories'], 'original_assignment': None, 'existing_assignment': None,
        'reused_commitment_refs': []}
    for selected, label, current in ((original, 'original_assignment', False), (task, 'existing_assignment', True)):
        if selected.existing_assignment_ref is not None:
            row = reading.resolve(selected.existing_assignment_ref)
            if (not isinstance(row, GovReviewAssignmentView) or row.ref != selected.existing_assignment_ref
                    or row.task_ref != selected.ref or row.organization_id != selected.organization_id):
                raise TaskConflict('Inspection capacity recovery substitutes retained assignment history')
            history[label] = row.model_dump(mode='json')
            proof_rows.append((row, current))
    if decimal_fraction(task.remaining_effort.value.value) == 0:
        # There is no positive demand to assess. Native validation may allow
        # fresh judgment to reach the original completed-work handoff wait.
        return {'data': None, 'proof_rows': proof_rows, 'proof_refs': proof_refs, 'history': history}
    work = reading.resolve(task.work_profile_ref)
    if not work.effective_window.contains(now):
        return 'unavailable'
    window = task.planned_window

    def covers(outer):
        return (outer.bounds == window.bounds == 'closed_open' and outer.start.clock_ref == window.start.clock_ref == now.clock_ref
            and outer.start.offset <= window.start.offset < window.end.offset <= outer.end.offset)

    duration = window.end.offset - window.start.offset
    if (duration <= 0 or window.start.offset < now.offset or duration > work.maximum_assignment_ticks
            or not covers(work.effective_window) or not covers(task.effective_window)):
        return 'waiting'
    shares = [decimal_fraction(share.share) for share in task.resource_shares]
    if (any(share <= 0 for share in shares) or sum(shares, Fraction()) != 1
            or len({share.resource_ref.key()[:2] for share in task.resource_shares}) != len(task.resource_shares)):
        raise TaskConflict('Inspection capacity demand repeats resources or changes effort conservation')
    productivity = decimal_fraction(work.effort_per_capacity_tick)
    if productivity <= 0:
        raise TaskConflict('Inspection capacity requires positive original productivity')
    reusable, assignment = set(), None
    if task.existing_assignment_ref is not None:
        assignment = reading.resolve(task.existing_assignment_ref)
        if (not isinstance(assignment, GovReviewAssignmentView) or assignment.ref != task.existing_assignment_ref
                or assignment.task_ref != task.ref or assignment.organization_id != task.organization_id
                or assignment.case_ref != task.case_ref or assignment.work_profile_ref != work.ref
                or assignment.status != 'effective' or assignment.window != window
                or not scope_covers(task.scope, assignment.scope)
                or {ref.key() for ref in assignment.resource_refs} != {share.resource_ref.key() for share in task.resource_shares}
                or not assignment.commitment_refs or len(set(assignment.commitment_refs)) != len(assignment.commitment_refs)):
            raise TaskConflict('Inspection capacity recovery borrows another assignment or excludes arbitrary occupancy')
        if (assignment.available_at.clock_ref != now.clock_ref or assignment.available_at.offset > now.offset
                or not assignment.effective_window.contains(now)):
            return 'unavailable'
        for ref in assignment.commitment_refs:
            row = commitments.get(ref.key()[:2])
            if (row is None or row.commitment_ref != ref or row.window != window
                    or row.resource_ref.key() not in {resource.key() for resource in assignment.resource_refs}):
                raise TaskConflict('Inspection capacity reuse lacks its actual original assignment commitment')
            reusable.add(ref.key())
        proof_rows.append((assignment, True))
    if original.existing_assignment_ref is not None:
        old_assignment = reading.resolve(original.existing_assignment_ref)
        if (not isinstance(old_assignment, GovReviewAssignmentView) or old_assignment.ref != original.existing_assignment_ref
                or old_assignment.task_ref != original.ref or old_assignment.organization_id != task.organization_id
                or old_assignment.case_ref != original.case_ref or old_assignment.work_profile_ref != original.work_profile_ref
                or old_assignment.window != assignment.window or old_assignment.scope != assignment.scope
                or {ref.key()[:2] for ref in old_assignment.resource_refs} != {ref.key()[:2] for ref in assignment.resource_refs}
                or not {ref.key()[:2] for ref in old_assignment.commitment_refs} <= {ref.key()[:2] for ref in assignment.commitment_refs}):
            raise TaskConflict('Inspection capacity recovery rewrites original assignment or known occupancy selection')
        proof_rows.append((old_assignment, False))
        history['original_assignment'] = old_assignment.model_dump(mode='json')
    remaining, demands = decimal_fraction(task.remaining_effort.value.value), []
    for share, fraction in zip(task.resource_shares, shares):
        resource = resources.get(share.resource_ref.key()[:2])
        old_resource = old_resources.get(share.resource_ref.key()[:2])
        if (resource is None or old_resource is None or resource.ref != share.resource_ref
                or resource.region_id != task.region_id or not covers(resource.effective_window)):
            return 'unavailable'
        if resource.total.unit != work.capacity_unit:
            raise TaskConflict('Inspection capacity recovery changes original resource units')
        if (set(old_resource.personnel_ids.value) != set(resource.personnel_ids.value)
                or old_resource.actor_id != resource.actor_id or old_resource.scope != resource.scope
                or old_resource.function_ref.key()[:2] != resource.function_ref.key()[:2]
                or not resource.personnel_ids.value):
            raise TaskConflict('Inspection capacity recovery replaces original physical personnel or responsible executor')
        grant, function = reading.resolve(resource.authority_ref), reading.resolve(resource.function_ref)
        if (not isinstance(grant, Authorization) or grant.ref != resource.authority_ref
                or not isinstance(function, RoleAssignment) or function.function_ref != resource.function_ref
                or grant.actor_id != resource.actor_id or grant.function_ref != resource.function_ref
                or grant.organization_id != task.organization_id or 'GOV-A10' not in grant.action_ids or function.role != 'Government'
                or not any(scope_covers(scope, task.scope) for scope in grant.scopes)):
            raise TaskConflict('Inspection capacity recovery lacks original executor/function/action authority')
        if not covers(grant.validity):
            return 'waiting'
        proof_refs.extend((ref, False) for ref in [*grant.basis_refs, *function.basis_refs])
        if task.function_code not in resource.function_codes or not set(task.discipline_codes) <= set(resource.discipline_codes):
            return 'waiting'
        qualifications = [reading.resolve(ref) for ref in resource.qualification_refs]
        if (len({ref.key()[:2] for ref in resource.qualification_refs}) != len(resource.qualification_refs)
                or any(not isinstance(row, GovReviewQualificationView) or not scope_covers(task.scope, row.scope) for row in qualifications)):
            raise TaskConflict('Inspection capacity recovery lacks distinct actual qualification sources')
        if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                or not row.effective_window.contains(now) for row in qualifications):
            return 'unavailable'
        for person in resource.personnel_ids.value:
            for discipline in task.discipline_codes:
                if not any(row.organization_id == task.organization_id and row.region_id == task.region_id
                        and person in row.personnel_ids and discipline in row.discipline_codes and task.function_code in row.function_codes
                        and row.valid.state == 'known' and row.valid.value is True and covers(row.effective_window)
                        and row.available_at.clock_ref == now.clock_ref and row.available_at.offset <= now.offset
                        and row.effective_window.contains(now) for row in qualifications):
                    return 'waiting'
        proof_rows.extend((row, True) for row in qualifications)
        if remaining > 0:
            demands.append({'resource_kind': resource.ref.id, 'region_id': resource.region_id, 'unit': work.capacity_unit,
                'amount': ExactAmount.from_fraction(remaining * fraction / (duration * productivity)),
                'window': window, 'basis_refs': task.evidence_refs})
    current_sources = [task.ref, calendar.ref, work.ref, task.estimate_ref, *task.work_fact_refs,
        *(row.ref for row in resources.values()), *(row.commitment_ref for row in commitments.values())]
    data = None if not demands else CapacityInput(clock_ref=now.clock_ref, demands=demands,
        resources=[{'resource_ref': row.ref, 'resource_kind': row.ref.id, 'region_id': row.region_id,
            'total': row.total, 'effective_window': row.effective_window} for row in resources.values()],
        commitments=[row for row in commitments.values() if row.commitment_ref.key() not in reusable],
        source_refs=list({ref.key(): ref for ref in current_sources}.values()))
    history['existing_assignment'] = None if assignment is None else assignment.model_dump(mode='json')
    history['reused_commitment_refs'] = [row.commitment_ref.model_dump(mode='json') for row in commitments.values()
        if row.commitment_ref.key() in reusable]
    return {'data': data, 'proof_rows': proof_rows, 'proof_refs': proof_refs, 'history': history}
