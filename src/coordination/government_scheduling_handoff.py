"""Retain completed work and authenticate release before fresh case scheduling."""
from src.actions.contracts.common import Known, Reference
from src.actions.contracts.government_scheduling_objects import (
    GovSchedulingTaskView, GovReviewAssignmentView, GovSchedulingEstimateView, GovSchedulingWorkFactView,
)
from src.coordination.government_inspection_work_history import read_completed_inspection_work
from src.coordination.tasks import TaskConflict
from src.methods.pricing import decimal_fraction


def read_government_scheduling_handoff(*, reading, original, current, waited, completed_task_ref, now, read,
        terminal=False, require_original_completed=True):
    key = waited[0].key()[:2]
    original_task = original['tasks'][key]
    if completed_task_ref is None:
        return 'waiting'
    if not isinstance(completed_task_ref, Reference) or completed_task_ref.kind != 'Task' or completed_task_ref.key()[:2] != key:
        raise TaskConflict('Government handoff substitutes original completed task identity')
    completed = read(completed_task_ref, GovSchedulingTaskView)
    if (completed.organization_id != original_task.organization_id or completed.case_ref != current['case_ref'].ref
            or completed.work_profile_ref != current['work'].ref
            or any(getattr(completed, field) != getattr(original_task, field) for field in (
                'execution_action_id', 'function_code', 'discipline_codes'))
            or completed.function_ref.key()[:2] != original_task.function_ref.key()[:2]
            or completed.estimate_ref.key()[:2] != original_task.estimate_ref.key()[:2]
            or {ref.key()[:2] for ref in completed.dependency_refs} != {ref.key()[:2] for ref in original_task.dependency_refs}
            or {row.resource_ref.key()[:2]: row.share for row in completed.resource_shares}
                != {row.resource_ref.key()[:2]: row.share for row in original_task.resource_shares}):
        raise TaskConflict('Government handoff rewrites original task/case/method/function binding')
    if completed.status != 'complete' or completed.as_of != now or key in current['tasks']:
        return 'waiting'
    if (completed.available_at.clock_ref != now.clock_ref or completed.available_at.offset > now.offset
            or not completed.effective_window.contains(now)):
        return 'unavailable'
    completion = (read_completed_inspection_work(reading=reading, original=original_task, task=completed, now=now)
        if require_original_completed else _read_later_completed_work(reading=reading, original=original_task,
            completed=completed, work=current['work'], now=now, read=read))
    if isinstance(completion, str):
        return completion
    released = None
    original_assignment_ref = original_task.existing_assignment_ref
    if original_assignment_ref is None:
        if completed.existing_assignment_ref is not None:
            raise TaskConflict('Government handoff invents an original completed-task assignment')
    else:
        ref = completed.existing_assignment_ref
        if ref is None or ref.key()[:2] != original_assignment_ref.key()[:2]:
            raise TaskConflict('Government handoff loses original completed-task assignment history')
        original_assignment = original['assignments'].get(original_assignment_ref.key()[:2])
        released = read(ref, GovReviewAssignmentView)
        if (original_assignment is None or original_assignment.ref != original_assignment_ref
                or original_assignment.status != 'effective' or released.task_ref != completed.ref
                or released.case_ref != current['case_ref'].ref or released.work_profile_ref != current['work'].ref
                or released.organization_id != original_task.organization_id
                or released.window != original_assignment.window
                or {ref.key()[:2] for ref in released.resource_refs}
                    != {ref.key()[:2] for ref in original_assignment.resource_refs}
                or {ref.key()[:2] for ref in released.commitment_refs}
                    != {ref.key()[:2] for ref in original_assignment.commitment_refs}):
            raise TaskConflict('Government handoff changes original assignment/resource/occupancy ownership')
        if released.status != 'released' or ref.key()[:2] in current['assignments']:
            return 'waiting'
        if (released.available_at.clock_ref != now.clock_ref or released.available_at.offset > now.offset
                or not released.effective_window.contains(now)):
            return 'unavailable'
        occupied_ids = {row.commitment_ref.key()[:2] for row in current['capacity_ref'].commitments}
        if occupied_ids.intersection(ref.key()[:2] for ref in original_assignment.commitment_refs):
            return 'waiting'
    if not terminal and original['tasks'].keys() - {key} - current['tasks'].keys():
        raise TaskConflict('Government handoff discards other original case tasks')
    retired_assignment = set() if original_assignment_ref is None else {original_assignment_ref.key()[:2]}
    if not terminal and original['assignments'].keys() - retired_assignment - current['assignments'].keys():
        raise TaskConflict('Government handoff discards another original case assignment')
    if not terminal and not current['tasks']:
        return 'waiting'  # Completion alone is no new A03 schedule; a terminal host reconciliation is separate.
    return dict(completed_task=completed, released_assignment=released, completion=completion)


def _read_later_completed_work(*, reading, original, completed, work, now, read):
    """Later tasks may have unfinished/unknown original work; retain any known investments."""
    estimate = read(completed.estimate_ref, GovSchedulingEstimateView)
    if (estimate.task_ref != completed.ref or estimate.work_profile_ref != work.ref
            or estimate.effort.unit != work.effort_unit or estimate.executed_at.clock_ref != now.clock_ref):
        raise TaskConflict('Government later handoff substitutes original completed estimate/task/unit')
    if (estimate.status != 'succeeded' or completed.work_fact_coverage != 'complete'
            or estimate.available_at.clock_ref != now.clock_ref or estimate.available_at.offset > now.offset
            or estimate.executed_at.offset > min(now.offset, estimate.available_at.offset)):
        return 'waiting'
    remaining = decimal_fraction(estimate.effort.value)
    if remaining <= 0:
        raise TaskConflict('Government later handoff requires a positive successful estimate')
    proof_refs, facts, original_facts, investments = [(estimate.effort.basis_ref, False)], {}, [], set()
    for ref in completed.work_fact_refs:
        fact = read(ref, GovSchedulingWorkFactView)
        if (fact.task_ref != completed.ref or fact.organization_id != completed.organization_id
                or fact.effort.unit != work.effort_unit or fact.ref.key()[:2] in facts
                or fact.investment_key in investments or fact.window.bounds != 'closed_open'
                or fact.window.start.clock_ref != now.clock_ref or fact.window.end.offset <= fact.window.start.offset):
            raise TaskConflict('Government later handoff duplicates or substitutes actual investment')
        if (fact.status != 'committed' or fact.available_at.clock_ref != now.clock_ref
                or fact.available_at.offset > now.offset or fact.window.end.offset > min(now.offset, fact.available_at.offset)):
            return 'waiting'
        spent = decimal_fraction(fact.effort.value)
        if spent <= 0:
            raise TaskConflict('Government later handoff cannot count waiting as actual completed work')
        remaining -= spent
        investments.add(fact.investment_key)
        facts[ref.key()[:2]] = fact
        proof_refs.append((fact.effort.basis_ref, False))
    declared = completed.remaining_effort
    if not isinstance(declared, Known):
        return 'waiting'
    if declared.value.unit != work.effort_unit or remaining != 0 or decimal_fraction(declared.value.value) != 0:
        raise TaskConflict('Government later handoff requires exact zero remaining work after actual investments')
    proof_refs.append((declared.value.basis_ref, False))
    original_estimate = None
    if original.estimate_ref.key() in reading._resolver._objects:
        original_estimate = read(original.estimate_ref, GovSchedulingEstimateView)
        if original_estimate.task_ref != original.ref:
            raise TaskConflict('Government later handoff borrows an original estimate')
        if original_estimate.status == 'succeeded' and any(getattr(original_estimate, field) != getattr(estimate, field)
                for field in ('effort', 'executed_at', 'method', 'status')):
            raise TaskConflict('Government later handoff rewrites its original successful estimate')
    for ref in original.work_fact_refs:
        if ref.key()[:2] not in facts:
            raise TaskConflict('Government later handoff discards an original actual investment')
        if ref.key() not in reading._resolver._objects:
            continue  # Explicit reader omissions still require native history authentication.
        old = read(ref, GovSchedulingWorkFactView)
        if old.task_ref != original.ref or old.investment_key != facts[ref.key()[:2]].investment_key:
            raise TaskConflict('Government later handoff substitutes an original investment identity')
        if old.status == 'committed' and any(getattr(old, field) != getattr(facts[ref.key()[:2]], field)
                for field in ('organization_id', 'investment_key', 'effort', 'window', 'status', 'scope')):
            raise TaskConflict('Government later handoff rewrites original committed actual work')
        original_facts.append(old.model_dump(mode='json'))
    return dict(proof_rows=[], proof_refs=proof_refs, histories=dict(
        original=dict(task=original.model_dump(mode='json'),
            estimate=None if original_estimate is None else original_estimate.model_dump(mode='json'), work_facts=original_facts),
        current=dict(work_profile=work.model_dump(mode='json'), estimate=estimate.model_dump(mode='json'),
            work_facts=[row.model_dump(mode='json') for row in facts.values()], remaining_effort=declared.model_dump(mode='json'))))
