"""Authenticate retained completed inspection effort without creating work facts."""
from src.actions.contracts.government_inspection_objects import (
    GovSchedulingWorkProfileView, GovSchedulingEstimateView, GovSchedulingWorkFactView,
)
from src.coordination.tasks import TaskConflict
from src.methods.pricing import decimal_fraction
from src.organization.registry import scope_covers


def read_completed_inspection_work(*, reading, original, task, now):
    return read_inspection_work_history(reading=reading, original=original, task=task, now=now, require_completed=True)


def read_inspection_work_history(*, reading, original, task, now, require_completed=False):
    """Return retained actual work histories, or an unresolved outcome.

    The original wait occurred at its authorized task's as_of time. Actual
    estimate and investment identities, quantities and execution times survive
    task-version rebinding. Completed-work callers also require zero remaining
    effort in both versions. Native transition validation still authenticates
    these observed records; zero remaining effort alone proves no inspection
    observation, quality result, issue closure or enforcement permission.
    """
    if original.status != 'authorized' or original.as_of.clock_ref != now.clock_ref:
        raise TaskConflict('Inspection handoff lacks its original authorized completion read point')
    histories, proof_rows, proof_refs, prior = {}, [], [], None
    for label, selected, at, current in (
            ('original', original, original.as_of, False), ('current', task, now, True)):
        work = reading.resolve(selected.work_profile_ref)
        estimate = reading.resolve(selected.estimate_ref)
        if (not isinstance(work, GovSchedulingWorkProfileView) or work.ref != selected.work_profile_ref
                or work.organization_id != selected.organization_id or not scope_covers(selected.scope, work.scope)
                or not isinstance(estimate, GovSchedulingEstimateView) or estimate.ref != selected.estimate_ref
                or estimate.task_ref != selected.ref or estimate.work_profile_ref != work.ref
                or not scope_covers(selected.scope, estimate.scope) or estimate.effort.unit != work.effort_unit):
            raise TaskConflict('Inspection handoff substitutes original work method, estimate or task binding')
        if (any(row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset for row in (work, estimate))
                or not current and (not work.effective_window.contains(at) or not estimate.effective_window.contains(at))):
            return 'unavailable'
        if (estimate.executed_at.clock_ref != at.clock_ref
                or estimate.executed_at.offset > min(at.offset, estimate.available_at.offset)):
            raise TaskConflict('Inspection handoff estimate changes its original actual execution time')
        if estimate.status != 'succeeded' or selected.work_fact_coverage != 'complete':
            return 'waiting'
        remaining = decimal_fraction(estimate.effort.value)
        if remaining <= 0:
            raise TaskConflict('Inspection handoff requires a positive original actual work estimate')
        facts, investments = {}, set()
        for ref in selected.work_fact_refs:
            fact = reading.resolve(ref)
            if (not isinstance(fact, GovSchedulingWorkFactView) or fact.ref != ref or fact.task_ref != selected.ref
                    or fact.organization_id != selected.organization_id or not scope_covers(selected.scope, fact.scope)
                    or fact.effort.unit != work.effort_unit or fact.ref.key()[:2] in facts
                    or fact.investment_key in investments):
                raise TaskConflict('Inspection handoff duplicates or substitutes an original actual work investment')
            if (fact.available_at.clock_ref != at.clock_ref or fact.available_at.offset > at.offset
                    or fact.window.end.clock_ref != at.clock_ref
                    or fact.window.end.offset > min(at.offset, fact.available_at.offset)):
                return 'unavailable'
            if fact.status != 'committed':
                return 'waiting'
            spent = decimal_fraction(fact.effort.value)
            if spent <= 0:
                raise TaskConflict('Inspection handoff cannot count administrative waiting as actual positive work')
            remaining -= spent
            investments.add(fact.investment_key)
            facts[fact.ref.key()[:2]] = fact
            # These are retained past investments, not present permission.
            # Their archived evidence need not acquire a new validity window.
            proof_rows.append((fact, False))
            proof_refs.append((fact.effort.basis_ref, False))
        declared = selected.remaining_effort
        if declared.state != 'known':
            return 'waiting'
        if (declared.value.unit != work.effort_unit or remaining < 0
                or decimal_fraction(declared.value.value) != remaining):
            raise TaskConflict('Inspection handoff remaining effort differs from original estimate minus actual work')
        if require_completed and remaining != 0:
            if not current:
                raise TaskConflict('Original inspection completion wait has unfinished work')
            return 'waiting'
        if prior is not None:
            old_work, old_estimate, old_facts = prior
            if (any(getattr(old_work, field) != getattr(work, field) for field in (
                        'effort_unit', 'capacity_unit', 'effort_per_capacity_tick', 'method'))
                    or any(getattr(old_estimate, field) != getattr(estimate, field) for field in (
                        'effort', 'executed_at', 'status', 'method'))
                    or not set(old_facts) <= set(facts)
                    or any(any(getattr(old, field) != getattr(facts[key], field) for field in (
                        'organization_id', 'investment_key', 'effort', 'window', 'status', 'scope'))
                        for key, old in old_facts.items())):
                raise TaskConflict('Inspection handoff rewrites original completed estimate or known work investment')
        prior = work, estimate, facts
        proof_rows.extend([(work, False), (estimate, False)])
        proof_refs.extend([(estimate.effort.basis_ref, False), (declared.value.basis_ref, False)])
        histories[label] = {'work_profile': work.model_dump(mode='json'), 'estimate': estimate.model_dump(mode='json'),
            'work_facts': [fact.model_dump(mode='json') for fact in facts.values()],
            'remaining_effort': declared.model_dump(mode='json')}
    return {'histories': histories, 'proof_rows': proof_rows, 'proof_refs': proof_refs}
