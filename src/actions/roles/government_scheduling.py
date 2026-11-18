"""GOV-A03 schedules lawful review work without performing reviews or reservations."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, Measured
from src.actions.contracts.government_objects import GovJurisdictionView, GovMatterView, GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_scheduling_objects import (
    GovSchedulingCaseView, GovCaseQueueView, GovQueueRuleView, GovQueueProfileView,
    GovSchedulingWorkProfileView, GovSchedulingTaskView, GovSchedulingEstimateView, GovSchedulingWorkFactView,
    GovSchedulingDependencyView, GovReviewResourceView, GovReviewQualificationView, GovReviewCalendarView,
    GovReviewAssignmentView, GovSchedulingPriorityView, GovSchedulingQuestionView,
    GovPriorityAuthorityView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, CapacityCommitment, ExactAmount
from src.methods.pricing import decimal_fraction, exact_decimal
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def schedule_reviews(context, action_input, reading):
    now, scope, organization = context.business_time, action_input.scope, reading.organization_id
    sources = {}

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('government-scheduling-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('government-scheduling-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)

    def read(ref, schema, current=True):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('government-scheduling-projection:' + ref.kind)
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'scope') and row.scope != scope:
            raise ValueError('Review input substitutes original requested scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_review_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if current and not row.effective_window.contains(now):
                _needs('current_original_review_input', [ref])
        sources[ref.key()] = ref
        return row

    def window(value):
        clock(value.start); clock(value.end)
        if value.bounds != 'closed_open' or value.end.offset <= value.start.offset:
            _unsupported('government-review-half-open-window')

    def covers(validity, planned):
        window(validity); window(planned)
        return validity.start.offset <= planned.start.offset and validity.end.offset >= planned.end.offset

    def authorize(ref, actor, function, action, planned=None, eligibility=False):
        row = read(ref, Authorization); assignment = read(function, RoleAssignment)
        evidence(row.basis_refs + assignment.basis_refs)
        if row.actor_id != actor or row.function_ref != function or row.organization_id != organization:
            raise ValueError('Review task lacks original agency/function/action/scope authority')
        if (assignment.role != 'Government' or action not in row.action_ids
                or not any(scope_covers(s, scope) for s in row.scopes)):
            if eligibility:
                return None
            raise ValueError('Review task lacks original agency/function/action/scope authority')
        clock(row.validity.start)
        if not row.validity.contains(now) or (planned is not None and not covers(row.validity, planned)):
            if eligibility:
                return None
            _needs('original_review_authority_covers_assignment_window', [ref])
        return row

    def deferred(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {'trigger': 'dependency_change',
            'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope': scope, 'note': profile.note, **fields}}

    try:
        case = read(action_input.case_ref, GovSchedulingCaseView)
        queue = read(action_input.queue_ref, GovCaseQueueView)
        profile = read(action_input.ordering_profile_ref, GovQueueProfileView)
        work = read(profile.work_profile_ref, GovSchedulingWorkProfileView)
        rule = read(queue.ordering_rule_ref, GovQueueRuleView)
        if (case.organization_id != organization or queue.organization_id != organization or profile.organization_id != organization
                or work.organization_id != organization or rule.organization_id != organization
                or case.queue_ref != queue.ref or profile.queue_ref != queue.ref or profile.case_ref != case.ref
                or rule.queue_ref != queue.ref):
            raise ValueError('Review queue/profile changes original agency, case or ordering rule')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, 'GOV-A03')
        matter = read(case.matter_ref, GovMatterView)
        jurisdiction = read(case.jurisdiction_ref, GovJurisdictionView)
        if (jurisdiction.organization_id != organization or matter.matter_code not in _known(jurisdiction.covered_matter_codes, 'review_jurisdiction_matters')
                or not any(scope_covers(s, scope) for s in jurisdiction.covered_scopes)):
            raise ValueError('Idle agency has no lawful review scope or matter jurisdiction')
        region = _known(case.region_id, 'review_case_region')
        if region not in _known(jurisdiction.covered_project_region_ids, 'review_jurisdiction_regions'):
            raise ValueError('Agency cannot schedule a case outside its original territorial authority')
        if _known(matter.project_region_id, 'original_review_matter_region') != region:
            raise ValueError('Review case substitutes original matter region')
        if case.status in {'closed', 'withdrawn'}:
            return deferred('government_review_case_not_open', [case.ref])
        if queue.coverage != 'complete' or queue.as_of != now:
            _needs('complete_current_lawful_case_queue')
        entries = sorted(queue.entries, key=lambda row: (row.entered_at.offset, repr(row.case_ref.key())))
        for entry in entries:
            clock(entry.entered_at)
            if entry.entered_at.offset > now.offset:
                raise ValueError('Review queue cannot include a future received case')
        selected = next((entry for entry in entries if entry.case_ref == case.ref), None)
        if selected is None:
            _needs('original_case_in_lawful_queue')
        if selected.status not in {'ready', 'assigned'}:
            return deferred('government_review_waiting_for_case_inputs', [case.ref, queue.ref])
        earlier = [entry.case_ref for entry in entries if entry.status == 'ready'
            and entry.entered_at.offset < selected.entered_at.offset]
        if profile.choice == 'reprioritize':
            if profile.priority_basis_ref is None or not rule.allows_priority_exception:
                _needs('independent_original_lawful_priority_basis')
            priority = read(profile.priority_basis_ref, GovSchedulingPriorityView)
            if (priority.organization_id != organization or priority.case_ref != case.ref or priority.queue_ref != queue.ref
                    or priority.ordering_rule_ref != rule.ref or keys(priority.bypassed_case_refs) != keys(earlier)):
                raise ValueError('Priority basis substitutes original case, lawful queue or bypassed cases')
            authorize(priority.authority_ref, context.actor_id, context.function_ref, 'GOV-A03')
            priority_authority = read(priority.priority_authority_ref, GovPriorityAuthorityView)
            if (priority_authority.organization_id != organization or priority_authority.actor_id != context.actor_id
                    or priority_authority.function_ref != context.function_ref or priority_authority.case_ref != case.ref
                    or priority_authority.queue_ref != queue.ref or priority_authority.ordering_rule_ref != rule.ref):
                raise ValueError('Priority exception lacks an independent original legal authority')
            if not _known(priority_authority.permitted, 'original_legal_priority_permission'):
                return deferred('government_review_priority_exception_not_authorized', [case.ref, priority.ref])
        elif profile.priority_basis_ref is not None:
            raise ValueError('Assignment cannot silently use an unselected priority exception')
        elif earlier and selected.status != 'assigned' and profile.choice != 'request_cooperation':
            return deferred('government_review_preserve_prior_lawful_queue_order', [queue.ref, *earlier])
        if selected.status == 'assigned' and not action_input.existing_assignment_refs and profile.choice != 'request_cooperation':
            _needs('original_effective_assignments_for_continuing_queue_case')
        if keys(action_input.task_refs) != keys(case.task_refs) or not action_input.task_refs:
            _needs('exact_nonempty_original_authorized_case_tasks')
        tasks = [read(ref, GovSchedulingTaskView) for ref in action_input.task_refs]
        for task in tasks:
            if task.organization_id != organization or task.case_ref != case.ref or task.work_profile_ref != work.ref:
                raise ValueError('Task substitutes original agency, case or work profile')
            authorize(task.authority_ref, context.actor_id, task.function_ref, 'GOV-A03')
        if profile.choice == 'request_cooperation':
            output = []
            keys(profile.question_refs)
            for ref in profile.question_refs:
                row = read(ref, GovSchedulingQuestionView)
                question = row.question
                if (row.case_ref != case.ref or not keys(row.task_refs) <= keys(action_input.task_refs)
                        or question.scope != scope or ref.key() not in keys(question.target_refs)
                        or question.requirement_ref != rule.ref):
                    raise ValueError('Cooperation question changes original case/tasks/order rule')
                response = read(question.response_requirement_ref, GovResponseRequirementView)
                if response.rule_ref != rule.ref:
                    raise ValueError('Cooperation question substitutes original response rule')
                for target in question.target_refs:
                    original = read(target, GovSchedulingQuestionView)
                    if original.case_ref != case.ref or original.question != question:
                        raise ValueError('Cooperation targets mix unrelated original questions')
                if not question.recipient_refs:
                    _needs('original_review_cooperation_recipient')
                for ref in question.recipient_refs:
                    read(ref, GovRecipientView)
                evidence(question.evidence_refs); output.append(question.model_dump(mode='python'))
            if not output:
                _needs('specific_original_review_cooperation_questions')
            return completed('request_cooperation', questions=output)

        calendar = read(action_input.capacity_ref, GovReviewCalendarView)
        if calendar.organization_id != organization or calendar.coverage != 'complete' or calendar.as_of != now:
            _needs('complete_current_review_resource_calendar')
        keys([row.ref for row in calendar.resources]); keys([row.commitment_ref for row in calendar.commitments])
        resources, people = {}, set()
        for embedded in calendar.resources:
            row = read(embedded.ref, GovReviewResourceView, False)
            if row != embedded or row.organization_id != organization:
                raise ValueError('Calendar substitutes original reviewer resource projection')
            persons = _known(row.personnel_ids, 'original_actual_reviewer_personnel')
            if not persons or len(set(persons)) != len(persons) or people.intersection(persons):
                raise ValueError('Review capacity repeats or omits actual reviewer personnel')
            people.update(persons)
            if row.total.unit != work.capacity_unit or decimal_fraction(row.total.value) > len(persons):
                _unsupported('government-review-capacity-unit-or-personnel-bound')
            if decimal_fraction(row.total.value) < 0:
                raise ValueError('Review resource capacity cannot be negative')
            evidence([row.total.basis_ref]); resources[row.ref.key()] = row
        commitments = {}
        for embedded in calendar.commitments:
            row = read(embedded.commitment_ref, CapacityCommitment)
            if row != embedded or row.resource_ref.key() not in resources:
                raise ValueError('Calendar substitutes original commitment or reviewer resource')
            window(row.window); evidence([row.quantity.basis_ref])
            commitments[row.commitment_ref.key()] = row
        expected = [task.existing_assignment_ref for task in tasks if task.existing_assignment_ref is not None]
        if keys(expected) != keys(action_input.existing_assignment_refs):
            _needs('exact_original_continuing_review_assignments')
        assignments, reusable = {}, set()
        for ref in action_input.existing_assignment_refs:
            row = read(ref, GovReviewAssignmentView)
            task = next((task for task in tasks if task.ref == row.task_ref), None)
            if (task is None or task.existing_assignment_ref != row.ref or row.case_ref != case.ref
                    or row.organization_id != organization or row.work_profile_ref != work.ref or row.status != 'effective'):
                raise ValueError('Continued review assignment changes original identity, task or lawful agency')
            if not row.commitment_refs or keys(row.resource_refs) != {share.resource_ref.key() for share in task.resource_shares}:
                raise ValueError('Continued assignment changes original resource ownership')
            for commitment in row.commitment_refs:
                original = commitments.get(commitment.key())
                if (original is None or original.resource_ref not in row.resource_refs or original.window != row.window
                        or commitment.key() in reusable):
                    raise ValueError('Review assignments duplicate or substitute original occupancy')
                reusable.add(commitment.key())
            assignments[row.task_ref.key()] = row
        productivity = decimal_fraction(work.effort_per_capacity_tick)
        if productivity <= 0:
            raise ValueError('Original declared review productivity must be positive')
        demands, items, investments = [], [], set()
        for task in tasks:
            if task.status != 'authorized' or task.as_of != now:
                return deferred('government_review_task_waiting_or_closed', [task.ref])
            planned = task.planned_window; window(planned)
            duration = planned.end.offset - planned.start.offset
            if planned.start.offset < now.offset or duration > work.maximum_assignment_ticks:
                return deferred('government_review_requires_finite_current_assignment_window', [task.ref])
            if not covers(jurisdiction.effective_window, planned) or not covers(work.effective_window, planned):
                _needs('lawful_review_profile_and_jurisdiction_for_window', [task.ref])
            for ref in task.dependency_refs:
                dep = read(ref, GovSchedulingDependencyView)
                if dep.task_ref != task.ref or dep.as_of != now:
                    raise ValueError('Review dependency substitutes original task or read time')
                if not isinstance(dep.satisfied, Known) or not dep.satisfied.value:
                    return deferred('government_review_dependency_wait', [task.ref, dep.ref])
            estimate = read(task.estimate_ref, GovSchedulingEstimateView, False)
            clock(estimate.executed_at)
            if estimate.task_ref != task.ref or estimate.work_profile_ref != work.ref or estimate.effort.unit != work.effort_unit:
                raise ValueError('Review task borrows another original effort estimate or unit')
            if estimate.status != 'succeeded' or estimate.executed_at.offset > min(now.offset, estimate.available_at.offset) or task.work_fact_coverage != 'complete':
                return deferred('government_review_remaining_effort_unknown', [task.ref, estimate.ref])
            evidence([estimate.effort.basis_ref]); remaining = decimal_fraction(estimate.effort.value)
            if remaining <= 0:
                raise ValueError('Original review estimate must be positive')
            keys(task.work_fact_refs)
            for ref in task.work_fact_refs:
                fact = read(ref, GovSchedulingWorkFactView, False); window(fact.window)
                if (fact.task_ref != task.ref or fact.organization_id != organization or fact.investment_key in investments
                        or fact.effort.unit != work.effort_unit):
                    raise ValueError('Review work repeats original actual investment or task/unit')
                investments.add(fact.investment_key); evidence([fact.effort.basis_ref])
                if fact.status != 'committed' or fact.window.end.offset > min(now.offset, fact.available_at.offset):
                    return deferred('government_review_actual_effort_pending', [task.ref, fact.ref])
                spent = decimal_fraction(fact.effort.value)
                if spent <= 0:
                    raise ValueError('Actual review investment must be positive; waiting is not completed work')
                remaining -= spent
            declared = _known(task.remaining_effort, 'original_review_remaining_effort')
            if declared.unit != work.effort_unit or decimal_fraction(declared.value) != remaining or remaining < 0:
                raise ValueError('Declared remaining review work differs from successful estimate minus actual effort')
            evidence([declared.basis_ref])
            if remaining == 0:
                return deferred('government_review_task_complete_requires_formal_handoff', [task.ref])
            keys([share.resource_ref for share in task.resource_shares])
            shares = [decimal_fraction(share.share) for share in task.resource_shares]
            if any(share <= 0 for share in shares) or sum(shares, Fraction()) != 1:
                raise ValueError('Original reviewer shares must conserve remaining effort')
            for share, fraction in zip(task.resource_shares, shares):
                resource = resources.get(share.resource_ref.key())
                if resource is None or resource.region_id != region or not covers(resource.effective_window, planned):
                    return deferred('government_review_no_suitable_available_resource', [task.ref, calendar.ref])
                if not set(task.discipline_codes) <= set(resource.discipline_codes) or task.function_code not in resource.function_codes:
                    return deferred('government_review_no_qualified_resource', [task.ref, resource.ref])
                if authorize(resource.authority_ref, resource.actor_id, resource.function_ref,
                        task.execution_action_id, planned, eligibility=True) is None:
                    return deferred('government_review_no_authorized_reviewer_for_window', [task.ref, resource.ref])
                keys(resource.qualification_refs)
                qualifications = [read(ref, GovReviewQualificationView, False) for ref in resource.qualification_refs]
                for person in resource.personnel_ids.value:
                    for discipline in task.discipline_codes:
                        valid = [q for q in qualifications if q.organization_id == organization and q.region_id == region
                            and person in q.personnel_ids and discipline in q.discipline_codes and task.function_code in q.function_codes
                            and isinstance(q.valid, Known) and q.valid.value and covers(q.effective_window, planned)]
                        if not valid:
                            return deferred('government_review_missing_current_reviewer_qualification', [task.ref, resource.ref])
                demands.append({'resource_kind': resource.ref.id, 'region_id': region, 'unit': work.capacity_unit,
                    'amount': ExactAmount.from_fraction(remaining * fraction / (duration * productivity)),
                    'window': planned, 'basis_refs': task.evidence_refs})
            assignment = assignments.get(task.ref.key())
            items.append({'task_ref': task.ref, 'resource_ids': [share.resource_ref.id for share in task.resource_shares],
                'window': planned, 'effort': Measured(value=exact_decimal(remaining), unit=work.effort_unit, basis_ref=declared.basis_ref),
                'dependency_refs': task.dependency_refs, 'existing_assignment_ref': assignment.ref if assignment else None})
        data = CapacityInput(clock_ref=now.clock_ref, demands=demands,
            resources=[{'resource_ref': row.ref, 'resource_kind': row.ref.id, 'region_id': row.region_id,
                'total': row.total, 'effective_window': row.effective_window} for row in resources.values()],
            commitments=[row for key, row in commitments.items() if key not in reusable], source_refs=list(sources.values()))
        result = reading.calculate(CAPACITY_METHOD, data)
        if result.kind != 'ok':
            if result.kind == 'invalid_input':
                raise ValueError('Original review resource arithmetic violates declared capacity domain')
            raw = result.model_dump(mode='python')
            if result.kind == 'needs_information':
                raw['requested_refs'] = []
            raise ObservationGap(raw)
        if not result.value.feasible:
            return deferred('government_review_capacity_queue_wait', [case.ref, queue.ref, calendar.ref])
        plan = {'work_profile_ref': work.ref, 'items': items}
        if profile.choice == 'reprioritize':
            return completed('reprioritize', case_ref=case.ref, priority_basis_ref=priority.ref, plan=plan)
        return completed('assign', plan=plan)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
