"""Reconstruct the original use plan's current capacity from actual sources."""
from fractions import Fraction

from src.actions.contracts.government_use_objects import (
    GovUseCapacityResultView, GovUseWorkFactView, GovSchedulingTaskView, GovSchedulingWorkProfileView,
    GovSchedulingEstimateView, GovReviewCalendarView, GovReviewResourceView, GovReviewAssignmentView, GovReviewQualificationView,
)
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict
from src.methods.capacity import CAPACITY_METHOD, CapacityCommitment, CapacityInput, CapacityReport, ExactAmount
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def read_use_capacity(*, reading, original_plan, plan, original_case, case, original_calendar_ref, now):
    """Authenticate complete multi-task demand and the independently saved result.

    Native validation receives original/current calendars and task investments,
    including old commitments absent from the current calendar. Only observed
    native release evidence may explain those omissions. This reader calculates
    capacity and creates no reservation, release, use permission or supervision.
    """
    if (original_plan.resource_calendar_ref.key() != original_calendar_ref.key()
            or plan.resource_calendar_ref.key()[:2] != original_calendar_ref.key()[:2]):
        raise TaskConflict('Government use capacity changes the original emitted calendar')
    old_calendar, calendar = reading.resolve(original_calendar_ref), reading.resolve(plan.resource_calendar_ref)
    if (not isinstance(old_calendar, GovReviewCalendarView) or not isinstance(calendar, GovReviewCalendarView)
            or old_calendar.organization_id != case.organization_id or calendar.organization_id != case.organization_id
            or old_calendar.scope != calendar.scope or old_calendar.coverage != 'complete'):
        raise TaskConflict('Government use capacity substitutes original complete agency calendar')
    proof_rows, proof_refs = [(old_calendar, False), (calendar, True)], []
    if calendar.as_of != now or calendar.coverage != 'complete':
        return 'waiting'
    if calendar.available_at.clock_ref != now.clock_ref or calendar.available_at.offset > now.offset or not calendar.effective_window.contains(now):
        return 'unavailable'
    resources, commitments, old_resources, old_commitments = {}, {}, {}, {}
    for selected, resource_map, commitment_map, current in (
            (old_calendar, old_resources, old_commitments, False), (calendar, resources, commitments, True)):
        people = set()
        for embedded in selected.resources:
            resource = reading.resolve(embedded.ref)
            if (not isinstance(resource, GovReviewResourceView) or resource != embedded
                    or resource.organization_id != case.organization_id or resource.ref.key()[:2] in resource_map
                    or not scope_covers(case.scope, resource.scope)):
                raise TaskConflict('Government use capacity substitutes or duplicates original physical resources')
            if resource.personnel_ids.state != 'known':
                return 'waiting'
            persons = resource.personnel_ids.value
            if len(set(persons)) != len(persons) or people.intersection(persons):
                raise TaskConflict('Government use capacity aliases personnel across physical resources')
            people.update(persons)
            if current and (resource.available_at.clock_ref != now.clock_ref or resource.available_at.offset > now.offset
                    or not resource.effective_window.contains(now)):
                return 'unavailable'
            resource_map[resource.ref.key()[:2]] = resource
            proof_rows.append((resource, current)); proof_refs.append((resource.total.basis_ref, current))
        for embedded in selected.commitments:
            row = reading.resolve(embedded.commitment_ref)
            resource = resource_map.get(row.resource_ref.key()[:2]) if isinstance(row, CapacityCommitment) else None
            if (not isinstance(row, CapacityCommitment) or row != embedded or resource is None or row.resource_ref != resource.ref
                    or row.commitment_ref.key()[:2] in commitment_map):
                raise TaskConflict('Government use capacity substitutes actual occupancy or duplicates a commitment')
            commitment_map[row.commitment_ref.key()[:2]] = row
            proof_refs.append((row.quantity.basis_ref, current))
    for key, old in old_commitments.items():
        row = commitments.get(key)
        if row is not None and (row.resource_ref.key()[:2] != old.resource_ref.key()[:2] or row.quantity != old.quantity or row.window != old.window):
            raise TaskConflict('Government use capacity rewrites retained original occupancy')
    old_tasks = {ref.key()[:2]: reading.resolve(ref) for ref in original_plan.task_refs}
    work = reading.resolve(plan.plan.work_profile_ref)
    if not isinstance(work, GovSchedulingWorkProfileView) or work.organization_id != case.organization_id:
        raise TaskConflict('Government use capacity changes original agency work method')
    if work.available_at.clock_ref != now.clock_ref or work.available_at.offset > now.offset or not work.effective_window.contains(now):
        return 'unavailable'
    productivity = decimal_fraction(work.effort_per_capacity_tick)
    if productivity <= 0:
        raise TaskConflict('Government use capacity requires positive original productivity')
    proof_rows.append((work, True))
    demands, reused, investments, histories = [], set(), set(), []
    required = [work.ref, calendar.ref, *(row.ref for row in resources.values()), *(row.commitment_ref for row in commitments.values())]
    for item in plan.plan.items:
        task, old_task = reading.resolve(item.task_ref), old_tasks.get(item.task_ref.key()[:2])
        if (not isinstance(task, GovSchedulingTaskView) or not isinstance(old_task, GovSchedulingTaskView)
                or task.organization_id != case.organization_id or old_task.organization_id != case.organization_id
                or task.case_ref != case.ref or old_task.case_ref != original_case.ref or task.work_profile_ref != work.ref
                or task.execution_action_id != ('GOV-A11' if plan.purpose == 'use_verification' else 'GOV-A10')
                or any(getattr(task, field) != getattr(old_task, field) for field in ('execution_action_id', 'scope', 'function_code', 'discipline_codes'))
                or {ref.key()[:2] for ref in task.dependency_refs} != {ref.key()[:2] for ref in old_task.dependency_refs}
                or not {ref.key()[:2] for ref in old_task.work_fact_refs} <= {ref.key()[:2] for ref in task.work_fact_refs}
                or {share.resource_ref.key()[:2]: share.share for share in task.resource_shares}
                    != {share.resource_ref.key()[:2]: share.share for share in old_task.resource_shares}
                or task.planned_window != item.window or task.existing_assignment_ref != item.existing_assignment_ref
                or {ref.key() for ref in task.dependency_refs} != {ref.key() for ref in item.dependency_refs}):
            raise TaskConflict('Government use capacity changes original complete task demand, dependencies or retained work')
        if task.status != 'authorized' or task.as_of != now:
            return 'waiting'
        if task.available_at.clock_ref != now.clock_ref or task.available_at.offset > now.offset or not task.effective_window.contains(now):
            return 'unavailable'
        duration = item.window.end.offset - item.window.start.offset
        def covers(window):
            return (window.bounds == item.window.bounds == 'closed_open' and window.start.clock_ref == item.window.start.clock_ref == now.clock_ref
                and window.start.offset <= item.window.start.offset < item.window.end.offset <= window.end.offset)
        if duration <= 0 or duration > work.maximum_assignment_ticks or item.window.start.offset < now.offset or not covers(task.effective_window) or not covers(work.effective_window):
            return 'waiting'
        estimate, old_estimate = reading.resolve(task.estimate_ref), reading.resolve(old_task.estimate_ref)
        if (not isinstance(estimate, GovSchedulingEstimateView) or not isinstance(old_estimate, GovSchedulingEstimateView)
                or estimate.task_ref != task.ref or old_estimate.task_ref != old_task.ref or estimate.work_profile_ref != work.ref
                or any(getattr(estimate, field) != getattr(old_estimate, field) for field in ('effort', 'executed_at', 'method', 'status'))
                or estimate.effort.unit != work.effort_unit):
            raise TaskConflict('Government use capacity rewrites its original estimate or units')
        if estimate.status != 'succeeded' or task.work_fact_coverage != 'complete':
            return 'waiting'
        remaining = decimal_fraction(estimate.effort.value)
        if remaining <= 0 or estimate.executed_at.clock_ref != now.clock_ref or estimate.executed_at.offset > min(now.offset, estimate.available_at.offset):
            raise TaskConflict('Government use capacity lacks a positive actually executed original estimate')
        facts = {}
        for ref in task.work_fact_refs:
            fact = reading.resolve(ref)
            if (not isinstance(fact, GovUseWorkFactView) or fact.task_ref != task.ref or fact.case_ref != case.ref
                    or fact.work_kind != 'review_effort' or fact.investment_key in investments or fact.ref.key()[:2] in facts
                    or fact.effort.unit != work.effort_unit or fact.window.end.clock_ref != now.clock_ref
                    or fact.status != 'committed' or fact.window.end.offset > min(now.offset, fact.available_at.offset)):
                raise TaskConflict('Government use capacity substitutes or repeats actual review investment')
            spent = decimal_fraction(fact.effort.value)
            if spent <= 0:
                raise TaskConflict('Government use capacity cannot count waiting as actual investment')
            remaining -= spent; investments.add(fact.investment_key); facts[fact.ref.key()[:2]] = fact
            required.append(ref); proof_rows.append((fact, False)); proof_refs.append((fact.effort.basis_ref, False))
        for ref in old_task.work_fact_refs:
            old_fact = reading.resolve(ref); fact = facts[ref.key()[:2]]
            if not isinstance(old_fact, GovUseWorkFactView) or any(getattr(old_fact, field) != getattr(fact, field) for field in (
                    'investment_key', 'core_event_id', 'effort', 'window', 'status', 'work_kind', 'author_actor_id', 'author_function_ref', 'author_authority_ref')):
                raise TaskConflict('Government use capacity rewrites known original investment history')
            proof_rows.append((old_fact, False))
        if task.remaining_effort.state != 'known':
            return 'waiting'
        declared = task.remaining_effort.value
        if remaining <= 0 or decimal_fraction(declared.value) != remaining or declared.unit != work.effort_unit or item.effort != declared:
            raise TaskConflict('Government use capacity effort differs from actual estimate minus retained work')
        fractions = [decimal_fraction(share.share) for share in task.resource_shares]
        if any(f <= 0 for f in fractions) or sum(fractions, Fraction()) != 1 or item.resource_ids != [share.resource_ref.id for share in task.resource_shares]:
            raise TaskConflict('Government use capacity changes original conserved resource shares')
        if len({share.resource_ref.key()[:2] for share in task.resource_shares}) != len(task.resource_shares):
            raise TaskConflict('Government use capacity duplicates selected physical resources')
        if old_task.existing_assignment_ref is not None and (task.existing_assignment_ref is None or old_task.existing_assignment_ref.key()[:2] != task.existing_assignment_ref.key()[:2]):
            raise TaskConflict('Government use capacity drops an original continuing assignment')
        assignment = None
        if item.existing_assignment_ref is not None:
            assignment = reading.resolve(item.existing_assignment_ref)
            if (not isinstance(assignment, GovReviewAssignmentView) or assignment.task_ref != task.ref or assignment.case_ref != case.ref
                    or assignment.organization_id != case.organization_id or assignment.work_profile_ref != work.ref
                    or assignment.status != 'effective' or assignment.window != item.window or not assignment.commitment_refs
                    or {ref.key() for ref in assignment.resource_refs} != {share.resource_ref.key() for share in task.resource_shares}):
                raise TaskConflict('Government use capacity borrows another assignment or excludes arbitrary occupancy')
            for ref in assignment.commitment_refs:
                row = commitments.get(ref.key()[:2])
                if row is None or row.commitment_ref != ref or ref.key() in reused or row.window != item.window or row.resource_ref not in assignment.resource_refs:
                    raise TaskConflict('Government use capacity duplicates or substitutes reused assignment occupancy')
                reused.add(ref.key())
            required.append(assignment.ref); proof_rows.append((assignment, True))
        for share, fraction in zip(task.resource_shares, fractions):
            resource, old = resources.get(share.resource_ref.key()[:2]), old_resources.get(share.resource_ref.key()[:2])
            if resource is None or old is None or resource.ref != share.resource_ref or not covers(resource.effective_window):
                return 'unavailable'
            if set(resource.personnel_ids.value) != set(old.personnel_ids.value) or not resource.personnel_ids.value:
                raise TaskConflict('Government use capacity replaces original physical personnel')
            if (resource.actor_id != old.actor_id or resource.function_ref.key()[:2] != old.function_ref.key()[:2]
                    or resource.total.unit != work.capacity_unit or task.function_code not in resource.function_codes
                    or not set(task.discipline_codes) <= set(resource.discipline_codes)):
                raise TaskConflict('Government use capacity replaces original executor function, discipline or units')
            executor_grant, executor_function = reading.resolve(resource.authority_ref), reading.resolve(resource.function_ref)
            if (not isinstance(executor_grant, Authorization) or not isinstance(executor_function, RoleAssignment)
                    or executor_function.role != 'Government' or executor_function.function_ref != resource.function_ref
                    or executor_grant.actor_id != resource.actor_id or executor_grant.function_ref != resource.function_ref
                    or executor_grant.organization_id != case.organization_id or task.execution_action_id not in executor_grant.action_ids
                    or not any(scope_covers(scope, task.scope) for scope in executor_grant.scopes)):
                raise TaskConflict('Government use capacity lacks actual executor authority for its original task')
            if not covers(executor_grant.validity):
                return 'waiting'
            proof_refs.extend((ref, False) for ref in [*executor_grant.basis_refs, *executor_function.basis_refs])
            qualifications = [reading.resolve(ref) for ref in resource.qualification_refs]
            if any(not isinstance(row, GovReviewQualificationView) for row in qualifications):
                raise TaskConflict('Government use capacity lacks actual qualification sources')
            for person in resource.personnel_ids.value:
                for discipline in task.discipline_codes:
                    if not any(row.organization_id == case.organization_id and row.region_id == resource.region_id
                            and person in row.personnel_ids and discipline in row.discipline_codes and task.function_code in row.function_codes
                            and row.valid.state == 'known' and row.valid.value is True and covers(row.effective_window)
                            and row.available_at.clock_ref == now.clock_ref and row.available_at.offset <= now.offset for row in qualifications):
                        return 'waiting'
            proof_rows.extend((row, True) for row in qualifications)
            demands.append({'resource_kind': resource.ref.id, 'region_id': resource.region_id, 'unit': work.capacity_unit,
                'amount': ExactAmount.from_fraction(remaining * fraction / (duration * productivity)), 'window': item.window, 'basis_refs': task.evidence_refs})
            required.extend(resource.qualification_refs)
        required.extend([task.ref, estimate.ref]); proof_rows.extend([(old_task, False), (task, True), (old_estimate, False), (estimate, False)])
        proof_refs.extend([(estimate.effort.basis_ref, False), (declared.basis_ref, True)])
        histories.append({'original_task': old_task.model_dump(mode='json'), 'task': task.model_dump(mode='json'),
            'estimate': estimate.model_dump(mode='json'), 'work_facts': [fact.model_dump(mode='json') for fact in facts.values()],
            'assignment': None if assignment is None else assignment.model_dump(mode='json')})
    saved = reading.resolve(plan.capacity_result_ref)
    if (not isinstance(saved, GovUseCapacityResultView) or saved.plan_ref != plan.ref or saved.method_ref != CAPACITY_METHOD
            or saved.plan_sha256 != content_digest(plan.plan) or saved.author_action_id != 'GOV-A03' or saved.author_organization_id != case.organization_id):
        raise TaskConflict('Government use capacity lacks its independent original plan calculation')
    if saved.status in {'failed', 'unsupported'}:
        raise TaskConflict('Government use saved capacity calculation failed or unsupported; inspect cause before retrying')
    if saved.status != 'ok' or saved.report is None:
        return 'waiting'
    data = CapacityInput(clock_ref=now.clock_ref, demands=demands,
        resources=[{'resource_ref': row.ref, 'resource_kind': row.ref.id, 'region_id': row.region_id, 'total': row.total,
            'effective_window': row.effective_window} for row in resources.values()],
        commitments=[row for row in commitments.values() if row.commitment_ref.key() not in reused], source_refs=saved.data.source_refs)
    grant, function = reading.resolve(saved.author_authority_ref), reading.resolve(saved.author_function_ref)
    if (not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment) or function.role != 'Government'
            or grant.actor_id != saved.author_actor_id or grant.function_ref != saved.author_function_ref
            or grant.organization_id != case.organization_id or 'GOV-A03' not in grant.action_ids
            or not grant.validity.contains(saved.authored_at) or not any(scope_covers(scope, saved.scope) for scope in grant.scopes)
            or not saved.effective_window.contains(saved.authored_at) or saved.authored_at.offset > saved.available_at.offset
            or saved.available_at.clock_ref != now.clock_ref or saved.available_at.offset > now.offset
            or data != saved.data or not {ref.key() for ref in required} <= {ref.key() for ref in data.source_refs}
            or not {ref.key() for ref in data.source_refs} <= {ref.key() for ref in grant.readable_refs}):
        raise TaskConflict('Government use saved capacity changes current full demand or original source read authority')
    for ref in data.source_refs:
        row = reading.resolve(ref)
        if getattr(row, 'available_at', saved.authored_at).offset > saved.authored_at.offset:
            raise TaskConflict('Government use capacity calculation predates its original readable inputs')
    result = reading.calculate(CAPACITY_METHOD, data)
    if result.kind != 'ok':
        return 'unavailable'
    report = CapacityReport.model_validate(result.value)
    if report != saved.report:
        raise TaskConflict('Government use capacity saved report differs from current actual inputs')
    proof_rows.append((saved, False)); proof_refs.extend((ref, False) for ref in [*grant.basis_refs, *function.basis_refs])
    return {'ready': report.feasible, 'proof_rows': proof_rows, 'proof_refs': proof_refs,
        'history': {'original_calendar': old_calendar.model_dump(mode='json'), 'calendar': calendar.model_dump(mode='json'),
            'tasks': histories, 'saved_result': saved.model_dump(mode='json'), 'method_result': result.model_dump(mode='json')}}
