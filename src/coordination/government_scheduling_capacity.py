"""Build complete GOV-A03 capacity demands without releasing other occupancy."""
from fractions import Fraction

from src.actions.contracts.common import Known
from src.actions.contracts.government_objects import GovJurisdictionView
from src.actions.contracts.government_scheduling_objects import (
    GovSchedulingEstimateView, GovSchedulingWorkFactView, GovSchedulingDependencyView,
    GovReviewResourceView, GovReviewQualificationView,
)
from src.coordination.tasks import TaskConflict
from src.methods.capacity import CapacityInput, CapacityCommitment, ExactAmount
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def read_government_scheduling_capacity(*, version, read, resolve, proof_refs, now):
    case, calendar, work = (version[field] for field in ('case_ref', 'capacity_ref', 'work'))
    tasks, assignments = version['tasks'], version['assignments']
    if calendar.coverage != 'complete' or calendar.as_of != now or not isinstance(case.region_id, Known):
        return 'unavailable'

    def covers(validity, planned):
        return (validity.bounds == planned.bounds == 'closed_open'
            and validity.start.clock_ref == planned.start.clock_ref == now.clock_ref
            and planned.end.offset > planned.start.offset
            and validity.start.offset <= planned.start.offset and validity.end.offset >= planned.end.offset)

    def index(rows, field):
        refs = [getattr(row, field) for row in rows]
        if len({ref.key()[:2] for ref in refs}) != len(refs):
            raise TaskConflict('Government capacity recovery duplicates physical resources or occupancy')
        return {ref.key(): row for ref, row in zip(refs, rows)}

    jurisdiction = resolve(case.jurisdiction_ref)
    if (not isinstance(jurisdiction, GovJurisdictionView) or jurisdiction.ref != case.jurisdiction_ref
            or jurisdiction.organization_id != case.organization_id):
        raise TaskConflict('Government capacity recovery borrows another agency jurisdiction')
    proof_refs.extend(jurisdiction.evidence_refs)
    if not jurisdiction.effective_window.contains(now):
        return 'unavailable'
    resources = index(calendar.resources, 'ref')
    commitments = index(calendar.commitments, 'commitment_ref')
    people, source_refs = set(), [case.ref, calendar.ref, work.ref, jurisdiction.ref]
    for embedded in resources.values():
        resource = read(embedded.ref, GovReviewResourceView)
        if resource != embedded or resource.organization_id != case.organization_id:
            raise TaskConflict('Government capacity recovery changes exact reviewer projection')
        if resource.available_at.clock_ref != now.clock_ref or resource.available_at.offset > now.offset:
            return 'unavailable'
        if not isinstance(resource.personnel_ids, Known) or not resource.personnel_ids.value:
            return 'unavailable'
        persons = resource.personnel_ids.value
        if len(set(persons)) != len(persons) or people.intersection(persons):
            raise TaskConflict('Government capacity recovery duplicates actual reviewer personnel')
        people.update(persons)
        total = decimal_fraction(resource.total.value)
        if resource.total.unit != work.capacity_unit or total < 0 or total > len(persons):
            raise TaskConflict('Government capacity recovery violates original personnel/unit bounds')
        proof_refs.append(resource.total.basis_ref)
        source_refs.append(resource.ref)
    for embedded in commitments.values():
        commitment = resolve(embedded.commitment_ref)
        if (not isinstance(commitment, CapacityCommitment) or commitment != embedded
                or commitment.resource_ref.key() not in resources):
            raise TaskConflict('Government capacity recovery changes exact occupied reviewer resource')
        proof_refs.append(commitment.quantity.basis_ref)
        source_refs.append(commitment.commitment_ref)
    expected = {task.existing_assignment_ref for task in tasks.values() if task.existing_assignment_ref is not None}
    if expected != {row.ref for row in assignments.values()}:
        raise TaskConflict('Government capacity recovery omits original continuing review assignments')
    excluded = set()
    for assignment in assignments.values():
        owner = tasks.get(assignment.task_ref.key()[:2])
        if (owner is None or assignment.task_ref != owner.ref or assignment.ref != owner.existing_assignment_ref
                or assignment.organization_id != case.organization_id or assignment.case_ref != case.ref
                or assignment.work_profile_ref != work.ref or assignment.status != 'effective'
                or not assignment.commitment_refs
                or {ref.key() for ref in assignment.resource_refs} != {row.resource_ref.key() for row in owner.resource_shares}):
            raise TaskConflict('Government capacity recovery excludes another task/case assignment')
        for ref in assignment.commitment_refs:
            occupied = commitments.get(ref.key())
            if (occupied is None or ref.key() in excluded or occupied.window != assignment.window
                    or occupied.resource_ref not in assignment.resource_refs):
                raise TaskConflict('Government capacity recovery duplicates or substitutes owned occupancy')
            excluded.add(ref.key())
        source_refs.append(assignment.ref)
    productivity = decimal_fraction(work.effort_per_capacity_tick)
    if productivity <= 0:
        raise TaskConflict('Government capacity recovery requires original positive productivity')
    demands, investments, histories = [], set(), []
    for task in tasks.values():
        planned = task.planned_window
        duration = planned.end.offset - planned.start.offset
        if (task.status != 'authorized' or task.as_of != now or planned.start.offset < now.offset
                or duration > work.maximum_assignment_ticks or not covers(work.effective_window, planned)
                or not covers(jurisdiction.effective_window, planned)):
            return 'waiting'
        dependencies, facts = [], []
        for ref in task.dependency_refs:
            dep = read(ref, GovSchedulingDependencyView)
            if dep.task_ref != task.ref:
                raise TaskConflict('Government capacity recovery substitutes original task dependency')
            if dep.as_of != now or not isinstance(dep.satisfied, Known) or not dep.satisfied.value:
                return 'waiting'
            dependencies.append(dep.model_dump(mode='json'))
            source_refs.append(ref)
        estimate = read(task.estimate_ref, GovSchedulingEstimateView)
        if (estimate.task_ref != task.ref or estimate.work_profile_ref != work.ref
                or estimate.effort.unit != work.effort_unit or estimate.executed_at.clock_ref != now.clock_ref):
            raise TaskConflict('Government capacity recovery substitutes original estimate/task/unit/time')
        if (estimate.status != 'succeeded' or estimate.available_at.clock_ref != now.clock_ref
                or estimate.available_at.offset > now.offset
                or estimate.executed_at.offset > min(now.offset, estimate.available_at.offset)
                or task.work_fact_coverage != 'complete'):
            return 'waiting'
        remaining = decimal_fraction(estimate.effort.value)
        if remaining <= 0:
            raise TaskConflict('Government capacity recovery requires a positive successful original estimate')
        proof_refs.append(estimate.effort.basis_ref)
        source_refs.extend([task.ref, estimate.ref])
        for ref in task.work_fact_refs:
            fact = read(ref, GovSchedulingWorkFactView)
            if (fact.task_ref != task.ref or fact.organization_id != case.organization_id
                    or fact.effort.unit != work.effort_unit or fact.investment_key in investments
                    or fact.window.bounds != 'closed_open' or fact.window.start.clock_ref != now.clock_ref
                    or fact.window.end.offset <= fact.window.start.offset):
                raise TaskConflict('Government capacity recovery repeats or substitutes actual investment')
            investments.add(fact.investment_key)
            if (fact.status != 'committed' or fact.available_at.clock_ref != now.clock_ref
                    or fact.available_at.offset > now.offset or fact.window.end.offset > min(now.offset, fact.available_at.offset)):
                return 'waiting'
            spent = decimal_fraction(fact.effort.value)
            if spent <= 0:
                raise TaskConflict('Government capacity recovery cannot treat waiting as actual investment')
            remaining -= spent
            proof_refs.append(fact.effort.basis_ref)
            facts.append(fact.model_dump(mode='json'))
            source_refs.append(ref)
        if not isinstance(task.remaining_effort, Known):
            return 'waiting'
        declared = task.remaining_effort.value
        if declared.unit != work.effort_unit or remaining < 0 or decimal_fraction(declared.value) != remaining:
            raise TaskConflict('Government capacity demand differs from successful estimate minus actual work')
        if remaining == 0:
            return 'waiting'
        proof_refs.append(declared.basis_ref)
        shares = [decimal_fraction(row.share) for row in task.resource_shares]
        if (any(share <= 0 for share in shares) or sum(shares, Fraction()) != 1
                or len({row.resource_ref.key()[:2] for row in task.resource_shares}) != len(shares)):
            raise TaskConflict('Government capacity recovery does not conserve original reviewer shares')
        for share, fraction in zip(task.resource_shares, shares):
            resource = resources.get(share.resource_ref.key())
            if (resource is None or resource.region_id != case.region_id.value
                    or not covers(resource.effective_window, planned)
                    or not set(task.discipline_codes) <= set(resource.discipline_codes)
                    or task.function_code not in resource.function_codes):
                return 'waiting'
            grant, function = resolve(resource.authority_ref), resolve(resource.function_ref)
            if (not isinstance(grant, Authorization) or grant.ref != resource.authority_ref
                    or not isinstance(function, RoleAssignment) or function.function_ref != resource.function_ref
                    or grant.actor_id != resource.actor_id or grant.organization_id != case.organization_id
                    or grant.function_ref != resource.function_ref):
                raise TaskConflict('Government capacity recovery substitutes original reviewer authority')
            if (function.role != 'Government' or task.execution_action_id not in grant.action_ids
                    or not grant.validity.contains(now) or not covers(grant.validity, planned)
                    or not any(scope_covers(scope, task.scope) for scope in grant.scopes)):
                return 'waiting'
            proof_refs.extend([*grant.basis_refs, *function.basis_refs])
            source_refs.extend([grant.ref, function.function_ref])
            qualifications = [read(ref, GovReviewQualificationView) for ref in resource.qualification_refs]
            index(qualifications, 'ref')
            if any(q.available_at.clock_ref != now.clock_ref or q.available_at.offset > now.offset for q in qualifications):
                return 'unavailable'
            for person in resource.personnel_ids.value:
                for discipline in task.discipline_codes:
                    if not any(q.organization_id == case.organization_id and q.region_id == case.region_id.value
                            and person in q.personnel_ids and discipline in q.discipline_codes
                            and task.function_code in q.function_codes and isinstance(q.valid, Known) and q.valid.value
                            and covers(q.effective_window, planned) for q in qualifications):
                        return 'waiting'
            source_refs.extend(resource.qualification_refs)
            demands.append(dict(resource_kind=resource.ref.id, region_id=resource.region_id, unit=work.capacity_unit,
                amount=ExactAmount.from_fraction(remaining * fraction / (duration * productivity)),
                window=planned, basis_refs=[declared.basis_ref, *task.evidence_refs]))
        histories.append(dict(task_ref=task.ref.model_dump(mode='json'), estimate=estimate.model_dump(mode='json'),
            work_facts=facts, dependencies=dependencies))
    data = CapacityInput(clock_ref=now.clock_ref, demands=demands,
        resources=[dict(resource_ref=row.ref, resource_kind=row.ref.id, region_id=row.region_id,
            total=row.total, effective_window=row.effective_window) for row in resources.values()],
        commitments=[row for key, row in commitments.items() if key not in excluded],
        source_refs=list({ref.key(): ref for ref in source_refs}.values()))
    return dict(input=data, history=dict(tasks=histories,
        excluded_commitments=[list(key) for key in sorted(excluded, key=str)]))
