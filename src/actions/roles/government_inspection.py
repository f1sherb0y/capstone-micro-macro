"""GOV-A10 plans inspections and reports scoped facts without changing quality truth."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.government_inspection_objects import (
    GovInspectionTaskView, GovInspectionView, GovInspectionRuleView, GovInspectionApplicabilityView,
    GovInspectionMethodView, GovInspectionAccessView, GovInspectionObservationView, GovInspectionResultView,
    GovInspectionQuestionView, GovInspectionIssueView, GovInspectionRequirementView, GovInspectionResponseView,
    GovRemedyVerificationView, GovInspectionAssessmentView, GovIssueVerificationResultView,
    GovRemedyResponderAuthorityView,
    GovMeasureBasisView, GovInspectionAuthorityView, GovMeasureTypeView, GovMeasureBindingView,
    GovMeasureProcedureVerificationView, GovRecipientView, GovResponseRequirementView, GovPermitView,
    GovSchedulingWorkProfileView, GovSchedulingEstimateView, GovSchedulingWorkFactView,
    GovSchedulingDependencyView, GovReviewResourceView, GovReviewQualificationView, GovReviewCalendarView,
    GovReviewAssignmentView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, CapacityCommitment, ExactAmount
from src.methods.government_rules import GOV_RULE_METHOD, GovRuleInput
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def inspect_and_follow_up(context, action_input, reading):
    now, scope, org = context.business_time, action_input.scope, reading.organization_id
    sources = {}

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('government-inspection-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('government-inspection-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
            sources[ref.key()] = ref

    def read(ref, schema, historic=False, linked=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('government-inspection-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Inspection source leaves original authorized task coverage')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_inspection_record', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now):
                _needs('current_original_inspection_record', [ref])
        evidence(getattr(row, 'evidence_refs', [])); sources[ref.key()] = ref
        return row

    def covers(outer, inner):
        clock(outer.start); clock(inner.start)
        if outer.bounds != 'closed_open' or inner.bounds != 'closed_open':
            _unsupported('government-inspection-half-open-windows')
        return outer.start.offset <= inner.start.offset < inner.end.offset <= outer.end.offset

    def authorize(ref, actor, function, organization, action, at, target_scope=scope):
        grant = read(ref, Authorization, True); assignment = read(function, RoleAssignment, True)
        roles = {'GOV': 'Government', 'OWN': 'Owner', 'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer',
            'QS': 'QS', 'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier', 'BANK': 'Bank'}
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or action not in grant.action_ids or assignment.role != roles.get(action.split('-')[0])
                or not any(scope_covers(s, target_scope) for s in grant.scopes)):
            raise ValueError('Inspection substitutes actual executor/function/action or independent scope authority')
        clock(at); clock(grant.validity.start)
        evidence(grant.basis_refs + assignment.basis_refs)
        if not grant.validity.contains(at):
            _needs('original_inspection_authority_at_execution', [ref])
        return grant

    def author(row, own=False):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Inspection source predates original actual execution')
        if own and (row.author_organization_id != org or row.author_action_id != 'GOV-A10'):
            raise ValueError('Inspection substitutes the original responsible regulator')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at, row.scope)

    def bound(row):
        if row.task_ref != task.ref:
            raise ValueError('Inspection source substitutes another original task')

    def rule(ref, purpose):
        row = read(ref, GovInspectionRuleView); bound(row)
        if row.organization_id != org or row.inspection_ref != inspection.ref or row.purpose != purpose:
            raise ValueError('Inspection rule substitutes original agency/inspection/purpose')
        if not _known(row.permitted, 'original_inspection_rule_permission'):
            _needs('permitted_original_inspection_rule', [ref])
        return row

    def complete(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope': scope, **fields,
            'note': 'Only recorded scope and actual evidence are covered. Plans, notices and proposed measures do not complete inspection or remedy; formal services own assignments, measures and issue updates. Contractor/Supplier perform and fund their own remedy; hidden quality truth is unchanged.'}}

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {'trigger': 'dependency_change',
            'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def technical(code):
        raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': code}, 'retryability': 'unknown'})

    def calculate(method_ref, data):
        result = reading.calculate(method_ref, data)
        if result.kind == 'invalid_input':
            raise ValueError('Original inspection input leaves the declared method domain')
        if result.kind != 'ok':
            raw = result.model_dump(mode='python')
            if result.kind == 'needs_information':
                raw['requested_refs'] = []
            raise ObservationGap(raw)
        return result.value

    def observed(ref):
        if ref.key() not in keys(action_input.observation_refs):
            raise ValueError('Inspection invents an undeclared actual observation')
        row = read(ref, GovInspectionObservationView, True); bound(row)
        if row.inspection_ref != inspection.ref or row.permit_ref != task.permit_ref or row.method_ref != method.ref:
            raise ValueError('Observation substitutes original inspection, permit or method')
        grant = author(row)
        if (row.author_action_id not in method.permitted_executor_actions
                or row.author_organization_id not in method.permitted_executor_organization_ids):
            raise ValueError('Observation substitutes a permitted independent method executor')
        clock(row.observed_window.start); clock(row.observed_window.end)
        if (row.observed_window.end.offset > row.authored_at.offset or not covers(grant.validity, row.observed_window)):
            raise ValueError('Observation predates completed field work or leaves actual execution authority')
        if row.status == 'failed':
            technical('government-inspection-original-observation-failed')
        if row.status == 'unsupported':
            _unsupported('government-inspection-original-observation-unmodeled')
        if row.status != 'executed' or row.factual_kind != 'actual':
            _needs('actual_original_executed_observation', [ref])
        if any(reading.resolve(r).basis_kind != 'observed' for r in row.evidence_refs):
            _needs('observed_original_inspection_evidence', [ref])
        # Known contains only state/value. The numeric measurement owns its
        # basis; disclosed codes use the original observation's evidence.
        if isinstance(row.measured_value, Known) and row.measured_value.value.basis_ref not in row.evidence_refs:
            raise ValueError('Observation values borrow an undeclared original measurement basis')
        if not _known(method.supported, 'original_inspection_observation_method_support'):
            _unsupported('government-inspection-observation-method-unmodeled')
        if method.requires_site_access:
            if row.access_ref is None or action_input.access_ref != row.access_ref:
                _needs('original_actual_site_access', [ref])
            access = read(row.access_ref, GovInspectionAccessView, True); bound(access)
            if (row.author_organization_id not in access.organization_ids or not scope_covers(access.scope, row.scope)
                    or not covers(access.effective_window, row.observed_window)
                    or not _known(access.allowed, 'original_site_access_at_observation')):
                _needs('lawful_original_site_access_at_execution', [ref])
        return row

    def checked(check, fact, result_ref, issue=None, requirement=None):
        if check.criterion == 'unmodeled' or check.criterion is None or check.method_ref != GOV_RULE_METHOD:
            _unsupported('government-inspection-check-method-unmodeled')
        if check.applicable is None or check.applicability_basis_ref is None:
            _needs('original_independent_inspection_applicability')
        applicability = read(check.applicability_basis_ref, GovInspectionApplicabilityView); author(applicability, True)
        if applicability.task_ref != task.ref or applicability.rule_ref != check.ref or applicability.applicable != check.applicable:
            raise ValueError('Inspection check changes independently verified applicability')
        input_data = GovRuleInput(criterion=check.criterion, applicable=check.applicable,
            measured_value=fact.measured_value if fact else None, code_value=fact.code_value if fact else None,
            unit=check.unit, minimum=check.minimum, maximum=check.maximum, expected_code=check.expected_code,
            professional_findings=[], professional_complete=True,
            source_refs=[check.ref, applicability.ref, *([fact.ref] if fact else [])])
        if result_ref is None:
            return 'unknown', None
        result = read(result_ref, GovInspectionResultView, True); bound(result); grant = author(result, True)
        if (result.rule_ref != check.ref or result.method_ref != check.method_ref
                or result.observation_ref != (fact.ref if isinstance(fact, GovInspectionObservationView) else getattr(fact, 'observation_ref', None))
                or result.issue_ref != (issue.ref if issue else None)
                or result.requirement_ref != (requirement.ref if requirement else None)
                or result.input_sha256 != content_digest(input_data)):
            raise ValueError('Inspection result substitutes original facts, rule, issue or saved complete input')
        if (not keys(input_data.source_refs) <= keys(grant.readable_refs)
                or any(reading.resolve(ref).available_at.offset > result.authored_at.offset for ref in input_data.source_refs)):
            raise ValueError('Inspection result substitutes original readable inputs or execution time')
        if result.status == 'failed':
            technical('government-inspection-original-check-failed')
        if result.status == 'unsupported':
            _unsupported('government-inspection-original-check-unmodeled')
        if result.status != 'ok' or result.report is None:
            return 'unknown', None
        computed = calculate(GOV_RULE_METHOD, input_data)
        if computed != result.report:
            raise ValueError('Inspection saved result differs from exact sourced rule calculation')
        return computed.finding, result.ref

    try:
        task = read(action_input.task_ref, GovInspectionTaskView)
        inspection = read(task.inspection_ref, GovInspectionView); bound(inspection)
        if (task.organization_id != org or task.execution_action_id != 'GOV-A10' or task.scope != scope
                or task.inspection_basis_ref != action_input.inspection_basis_ref or task.permit_ref != action_input.permit_ref
                or task.observation_method_ref != action_input.observation_method_ref or inspection.organization_id != org
                or inspection.permit_ref != task.permit_ref or keys(task.received_observation_refs) != keys(action_input.observation_refs)
                or keys(task.prior_issue_refs) != keys(action_input.prior_issue_refs)):
            raise ValueError('Inspection changes original task, agency, permit, method or received evidence/issue set')
        if task.authority_ref not in context.authorization_refs or task.function_ref != context.function_ref:
            raise ValueError('Inspection task is absent from original acting function authority')
        authorize(task.authority_ref, context.actor_id, context.function_ref, org, 'GOV-A10', now)
        if task.status != 'authorized' or task.as_of != now:
            return wait('government-inspection-original-task-waiting', [task.ref])
        rule(action_input.inspection_basis_ref, 'inspection')
        if action_input.permit_ref is not None:
            permit = read(action_input.permit_ref, GovPermitView, True, True)
            if permit.organization_id != org or not scope_covers(permit.scope, scope):
                raise ValueError('Inspection borrows another agency or permit scope')
        method = read(action_input.observation_method_ref, GovInspectionMethodView)
        choice = task.choice
        if choice == 'plan':
            if task.resource_calendar_ref is None:
                _needs('original_inspection_resource_calendar')
            work = read(task.work_profile_ref, GovSchedulingWorkProfileView)
            calendar = read(task.resource_calendar_ref, GovReviewCalendarView)
            if work.organization_id != org or calendar.organization_id != org or calendar.coverage != 'complete' or calendar.as_of != now:
                _needs('complete_current_original_inspection_resources')
            window = task.planned_window; clock(window.start)
            duration = window.end.offset - window.start.offset
            if (duration <= 0 or window.start.offset < now.offset or duration > work.maximum_assignment_ticks
                    or not covers(work.effective_window, window) or not covers(task.effective_window, window)):
                return wait('government-inspection-finite-current-work-window', [task.ref])
            for ref in task.dependency_refs:
                dependency = read(ref, GovSchedulingDependencyView); bound(dependency)
                if dependency.as_of != now or not _known(dependency.satisfied, 'original_inspection_plan_dependency'):
                    return wait('government-inspection-plan-dependency-wait', [ref])
            estimate = read(task.estimate_ref, GovSchedulingEstimateView); bound(estimate); clock(estimate.executed_at)
            if estimate.work_profile_ref != work.ref or estimate.effort.unit != work.effort_unit:
                raise ValueError('Inspection borrows another original effort estimate or unit')
            if estimate.status == 'failed':
                technical('government-inspection-estimate-failed')
            if (estimate.status != 'succeeded' or estimate.executed_at.offset > min(now.offset, estimate.available_at.offset)
                    or task.work_fact_coverage != 'complete'):
                _needs('successful_original_inspection_estimate_and_actual_work')
            remaining = decimal_fraction(estimate.effort.value); evidence([estimate.effort.basis_ref]); investments = set()
            if remaining <= 0:
                raise ValueError('Inspection effort estimate must be positive')
            keys(task.work_fact_refs)
            for ref in task.work_fact_refs:
                fact = read(ref, GovSchedulingWorkFactView, True); bound(fact)
                if fact.organization_id != org or fact.effort.unit != work.effort_unit or fact.investment_key in investments:
                    raise ValueError('Inspection repeats original task investment or changes effort unit')
                investments.add(fact.investment_key); clock(fact.window.end); evidence([fact.effort.basis_ref])
                if fact.status != 'committed' or fact.window.end.offset > min(now.offset, fact.available_at.offset):
                    _needs('original_actual_completed_inspection_effort')
                spent = decimal_fraction(fact.effort.value)
                if spent <= 0:
                    raise ValueError('Administrative waiting is not positive actual inspection effort')
                remaining -= spent
            declared = _known(task.remaining_effort, 'original_inspection_remaining_effort')
            if declared.unit != work.effort_unit or decimal_fraction(declared.value) != remaining or remaining < 0:
                raise ValueError('Inspection remaining effort differs from successful estimate minus actual work')
            evidence([declared.basis_ref])
            if remaining == 0:
                return wait('government-inspection-completed-work-awaits-original-handoff', [task.ref])
            resources = {}; all_personnel = set()
            for embedded in calendar.resources:
                original = read(embedded.ref, GovReviewResourceView)
                if original != embedded or original.organization_id != org:
                    raise ValueError('Inspection calendar substitutes an original resource')
                evidence([original.total.basis_ref])
                personnel = _known(original.personnel_ids, 'inspection_calendar_actual_personnel')
                if len(set(personnel)) != len(personnel) or all_personnel.intersection(personnel):
                    raise ValueError('Inspection calendar aliases the same physical personnel across resources')
                all_personnel.update(personnel)
                resources[original.ref.key()] = original
            keys([row.ref for row in calendar.resources]); keys([row.commitment_ref for row in calendar.commitments])
            commitments = {row.commitment_ref.key(): read(row.commitment_ref, CapacityCommitment) for row in calendar.commitments}
            if any(commitments[row.commitment_ref.key()] != row or row.resource_ref.key() not in resources for row in calendar.commitments):
                raise ValueError('Inspection calendar substitutes original commitments or physical resources')
            for row in commitments.values():
                evidence([row.quantity.basis_ref])
            reusable = set()
            if task.existing_assignment_ref is not None:
                assignment = read(task.existing_assignment_ref, GovReviewAssignmentView); bound(assignment)
                if (assignment.organization_id != org or assignment.case_ref != task.case_ref or assignment.work_profile_ref != work.ref
                        or assignment.status != 'effective' or assignment.window != window
                        or keys(assignment.resource_refs) != keys([s.resource_ref for s in task.resource_shares])
                        or not assignment.commitment_refs):
                    raise ValueError('Inspection continuation changes original assignment identity or selected occupancy')
                reusable = keys(assignment.commitment_refs)
                for key in reusable:
                    prior = commitments.get(key)
                    if prior is None or prior.resource_ref.key() not in keys(assignment.resource_refs) or prior.window != window:
                        raise ValueError('Inspection reuses another original commitment')
            fractions = [decimal_fraction(s.share) for s in task.resource_shares]
            if any(f <= 0 for f in fractions) or sum(fractions, Fraction()) != 1:
                raise ValueError('Inspection resource shares must conserve actual remaining effort')
            keys([s.resource_ref for s in task.resource_shares]); demands = []
            productivity = decimal_fraction(work.effort_per_capacity_tick)
            if productivity <= 0:
                raise ValueError('Inspection productivity must be positive')
            physical = set()
            for share, fraction in zip(task.resource_shares, fractions):
                resource = resources.get(share.resource_ref.key())
                if resource is None or resource.region_id != task.region_id or not covers(resource.effective_window, window):
                    _needs('original_available_local_inspection_resource')
                persons = _known(resource.personnel_ids, 'inspection_actual_personnel')
                if not persons or len(set(persons)) != len(persons) or physical.intersection(persons):
                    raise ValueError('Inspection repeats or omits physical personnel across selected resources')
                physical.update(persons)
                grant = authorize(resource.authority_ref, resource.actor_id, resource.function_ref, org, 'GOV-A10', window.start)
                if not covers(grant.validity, window):
                    _needs('original_executor_authority_for_full_inspection_window')
                if task.function_code not in resource.function_codes or not set(task.discipline_codes) <= set(resource.discipline_codes):
                    _needs('original_suitable_inspection_function_and_discipline')
                keys(resource.qualification_refs)
                qualifications = [read(ref, GovReviewQualificationView) for ref in resource.qualification_refs]
                for person in persons:
                    for discipline in task.discipline_codes:
                        if not any(q.organization_id == org and q.region_id == task.region_id and person in q.personnel_ids
                                and discipline in q.discipline_codes and task.function_code in q.function_codes
                                and isinstance(q.valid, Known) and q.valid.value and covers(q.effective_window, window) for q in qualifications):
                            _needs('qualified_original_inspection_personnel')
                demands.append({'resource_kind': resource.ref.id, 'region_id': resource.region_id, 'unit': work.capacity_unit,
                    'amount': ExactAmount.from_fraction(remaining * fraction / (duration * productivity)),
                    'window': window, 'basis_refs': task.evidence_refs})
            data = CapacityInput(clock_ref=now.clock_ref, demands=demands,
                resources=[{'resource_ref': r.ref, 'resource_kind': r.ref.id, 'region_id': r.region_id, 'total': r.total,
                    'effective_window': r.effective_window} for r in resources.values()],
                commitments=[r for key, r in commitments.items() if key not in reusable], source_refs=list(sources.values()))
            if not calculate(CAPACITY_METHOD, data).feasible:
                return wait('government-inspection-resource-capacity-wait', [calendar.ref])
            return complete(choice, plan={'work_profile_ref': work.ref, 'items': [{'task_ref': task.ref,
                'resource_ids': [s.resource_ref.id for s in task.resource_shares], 'window': window, 'effort': declared,
                'dependency_refs': task.dependency_refs, 'existing_assignment_ref': task.existing_assignment_ref}]})

        if choice == 'require_response':
            if not task.question_refs:
                _needs('concrete_original_inspection_questions')
            keys(task.question_refs); questions = []
            for ref in task.question_refs:
                row = read(ref, GovInspectionQuestionView); bound(row); q = row.question
                if row.issue_ref is not None and row.issue_ref.key() not in keys(task.prior_issue_refs):
                    raise ValueError('Inspection question changes an undeclared original issue')
                if not scope_covers(scope, q.scope) or ref.key() not in keys(q.target_refs) or not q.recipient_refs:
                    raise ValueError('Inspection question changes original coverage or omits targets/recipients')
                rule(q.requirement_ref, 'question')
                response = read(q.response_requirement_ref, GovResponseRequirementView)
                if response.rule_ref != q.requirement_ref or response.scope != q.scope:
                    raise ValueError('Inspection question substitutes response requirement')
                for target in q.target_refs:
                    original = read(target, GovInspectionQuestionView); bound(original)
                    if original.question != q or original.issue_ref != row.issue_ref:
                        raise ValueError('Inspection question mixes unrelated original targets')
                for ref in q.recipient_refs:
                    recipient = read(ref, GovRecipientView)
                    if not scope_covers(recipient.scope, q.scope):
                        raise ValueError('Inspection recipient leaves original question coverage')
                keys(q.recipient_refs); evidence(q.evidence_refs); questions.append(q.model_dump(mode='python'))
            return complete(choice, questions=questions)

        if choice == 'report':
            if not task.check_rule_refs:
                _needs('original_scoped_inspection_checks')
            keys(task.check_rule_refs); observations = [observed(ref) for ref in action_input.observation_refs]
            if len({r.event_id for r in observations}) != len(observations):
                raise ValueError('Inspection repeats the same original observation event')
            checks = []
            for ref in task.check_rule_refs:
                check = rule(ref, 'check'); fact = None
                if check.observation_ref is not None:
                    fact = observed(check.observation_ref)
                    if not scope_covers(fact.scope, check.scope):
                        raise ValueError('Inspection check extends beyond actual observation coverage')
                if check.requires_site_observation and fact is None:
                    finding, result_ref = 'unknown', None
                else:
                    finding, result_ref = checked(check, fact, check.result_ref)
                checks.append({'rule_ref': check.ref, 'covered_scope': check.scope,
                    'evidence_refs': fact.evidence_refs if fact else [], 'method_result_ref': result_ref, 'finding': finding})
            return complete(choice, observation_refs=action_input.observation_refs, assessment={'target_ref': inspection.ref,
                'task_ref': task.ref, 'checks': checks, 'proposed_questions': [], 'explanation': task.explanation})

        if choice == 'order_measure':
            if task.measure_basis_ref is None:
                _needs('original_independent_measure_basis')
            basis = read(task.measure_basis_ref, GovMeasureBasisView); bound(basis); author(basis, True)
            measure = basis.measure; check = rule(measure.rule_ref, 'measure')
            if not scope_covers(scope, measure.affected_scope) or not measure.evidence_refs or not measure.affected_action_refs:
                raise ValueError('Regulatory measure lacks original local action scope or factual evidence')
            evidence(measure.evidence_refs)
            if any(reading.resolve(ref).basis_kind == 'assumed' for ref in measure.evidence_refs):
                _needs('factual_original_regulatory_measure_evidence')
            if check.requires_site_observation:
                if not action_input.observation_refs:
                    _needs('actual_observation_required_by_original_measure_rule')
                observations = [observed(ref) for ref in action_input.observation_refs]
                if not any(scope_covers(r.scope, measure.affected_scope)
                        and keys(measure.evidence_refs) <= keys(r.evidence_refs) for r in observations):
                    _needs('actual_observation_coverage_for_original_measure')
            authority = read(measure.authority_basis_ref, GovInspectionAuthorityView); bound(authority)
            if (authority.organization_id != org or authority.actor_id != context.actor_id or authority.function_ref != context.function_ref
                    or authority.measure_type_ref != measure.measure_type_ref or authority.rule_ref != measure.rule_ref
                    or not scope_covers(authority.scope, measure.affected_scope)
                    or keys(measure.affected_action_refs) != keys(authority.action_refs)
                    or set(measure.recipient_ids) != set(authority.recipient_ids)
                    or not _known(authority.permitted, 'original_independent_regulatory_measure_permission')):
                _needs('original_independent_measure_type_and_scope_authority')
            if not measure.recipient_ids or len(set(measure.recipient_ids)) != len(measure.recipient_ids):
                raise ValueError('Regulatory measure requires distinct actual recipients')
            kind = read(measure.measure_type_ref, GovMeasureTypeView)
            if not kind.modeled:
                _unsupported('government-inspection-regulatory-measure-unmodeled')
            if kind.organization_id != org or not keys(measure.affected_action_refs) <= keys(kind.permitted_action_refs):
                raise ValueError('Measure changes independently cataloged type/action authority')
            for ref in [*measure.affected_action_refs, measure.effect_rule_ref, measure.review_trigger_ref, basis.procedure_ref]:
                binding = read(ref, GovMeasureBindingView)
                if binding.measure_basis_ref != basis.ref or not scope_covers(measure.affected_scope, binding.scope):
                    raise ValueError('Measure effect/review/procedure/action binding belongs to another original basis')
            verification = read(basis.procedure_verification_ref, GovMeasureProcedureVerificationView); author(verification, True)
            if (verification.measure_basis_ref != basis.ref or verification.procedure_ref != basis.procedure_ref
                    or verification.measure_sha256 != content_digest(measure)
                    or not _known(verification.satisfied, 'original_regulatory_measure_procedure')):
                _needs('satisfied_original_measure_procedure')
            return complete(choice, measure=measure.model_dump(mode='python'))

        if not action_input.prior_issue_refs:
            _needs('original_issues_for_scoped_inspection_recheck')
        resolutions = []; response_events = set()
        for ref in action_input.prior_issue_refs:
            issue = read(ref, GovInspectionIssueView); bound(issue)
            if issue.history_coverage != 'complete' or issue.as_of != now:
                _needs('complete_current_original_inspection_issue_history')
            requirements = [read(r, GovInspectionRequirementView) for r in issue.requirement_refs]
            keys(issue.requirement_refs); keys(issue.response_refs); keys(issue.assessment_refs)
            if not requirements or any(r.issue_ref != issue.ref for r in requirements):
                raise ValueError('Inspection issue requirements substitute another original issue')
            responses = {}
            for response_ref in issue.response_refs:
                response = read(response_ref, GovInspectionResponseView, True); bound(response); author(response)
                clock(response.received_at)
                if (response.issue_ref != issue.ref or response.event_id in response_events
                        or response.author_action_id.split('-')[0] not in {'CONTRACTOR', 'SUPPLIER'}
                        or response.received_at.offset > min(now.offset, response.available_at.offset)):
                    raise ValueError('Inspection response substitutes actual responsible remedy author/event/time')
                response_events.add(response.event_id)
                delegation = read(response.responder_authority_ref, GovRemedyResponderAuthorityView, True)
                if (delegation.issue_ref != issue.ref or delegation.actor_id != response.author_actor_id
                        or delegation.function_ref != response.author_function_ref or delegation.organization_id != response.author_organization_id
                        or not delegation.effective_window.contains(response.authored_at)
                        or not _known(delegation.permitted, 'original_responsible_remedy_responder')):
                    _needs('authorized_original_issue_remedy_responder')
                if response.status == 'failed':
                    technical('government-inspection-original-response-failed')
                if response.status == 'received':
                    keys(response.verification_refs); responses[response.ref.key()] = response
            verified, verification_results, findings, fact_hashes = [], [], [], {}
            for requirement in requirements:
                check = rule(requirement.rule_ref, 'requirement'); fact = None
                finding = 'unknown'
                if requirement.verified_fact_ref is not None:
                    fact = read(requirement.verified_fact_ref, GovRemedyVerificationView); bound(fact); author(fact, True)
                    response = responses.get(fact.response_ref.key())
                    if (fact.issue_ref != issue.ref or fact.requirement_ref != requirement.ref
                            or fact.requirement_content_sha256 != requirement.content_sha256
                            or response is None or fact.ref.key() not in keys(response.verification_refs)
                            or not scope_covers(fact.scope, requirement.scope) or fact.authored_at.offset < response.received_at.offset):
                        raise ValueError('Remedy verification substitutes original received response, requirement/version or scope')
                    if fact.factual_kind != 'actual':
                        fact = None
                    elif check.requires_site_observation:
                        if fact.observation_ref is None:
                            fact = None
                        else:
                            observation = observed(fact.observation_ref)
                            if not scope_covers(observation.scope, requirement.scope):
                                raise ValueError('Partial remedy observation cannot close wider original requirement')
                            if fact.measured_value != observation.measured_value or fact.code_value != observation.code_value:
                                raise ValueError('Remedy verification changes original observed values')
                            if fact.authored_at.offset < observation.authored_at.offset:
                                raise ValueError('Remedy verification predates its actual observation')
                if fact is not None:
                    fact_hashes[requirement.ref.key()] = content_digest(fact)
                    finding, result_ref = checked(check, fact, fact.result_ref, issue, requirement)
                    if result_ref is not None:
                        verification_results.append(result_ref)
                    if finding == 'conforms' and result_ref is not None:
                        verified.append(requirement.ref)
                findings.append(finding if finding in {'conforms', 'nonconforms', 'unknown'} else 'unknown')
            retained = [r for r in issue.requirement_refs if r.key() not in keys(verified)]
            result_ref = None
            if verified and issue.verification_result_ref is not None:
                result = read(issue.verification_result_ref, GovIssueVerificationResultView); bound(result); grant = author(result, True)
                summary = GovRuleInput(criterion='professional_evidence', applicable=Known[bool](state='known', value=True),
                    measured_value=None, code_value=None, unit=None, minimum=None, maximum=None, expected_code=None,
                    professional_findings=findings, professional_complete=not retained,
                    source_refs=[issue.ref, *issue.requirement_refs, *issue.response_refs, *verification_results])
                if result.status == 'failed':
                    technical('government-inspection-original-recheck-failed')
                if result.status == 'unsupported':
                    _unsupported('government-inspection-original-recheck-unmodeled')
                if (result.issue_ref != issue.ref or result.method_ref != GOV_RULE_METHOD or result.input_sha256 != content_digest(summary)
                        or result.rule_ref != action_input.inspection_basis_ref or result.observation_ref is not None
                        or result.requirement_ref is not None or keys(result.verified_requirement_refs) != keys(verified)
                        or not keys(summary.source_refs) <= keys(grant.readable_refs)):
                    raise ValueError('Recheck summary changes original verification inputs or actual covered requirements')
                if result.status == 'ok' and result.report is not None:
                    if calculate(GOV_RULE_METHOD, summary) != result.report:
                        raise ValueError('Recheck saved summary differs from independently verified requirement findings')
                    result_ref = result.ref
            if result_ref is None:
                retained = list(issue.requirement_refs)
            resolution = 'unresolved' if result_ref is None else ('resolved' if not retained else 'partially_resolved')
            if resolution == 'resolved' and issue.verification_coverage != 'complete':
                resolution = 'unresolved'; retained = list(issue.requirement_refs); result_ref = None
            current = {r.ref.key(): r for r in requirements}; affected, reusable = [], []
            for assessment_ref in issue.assessment_refs:
                assessment = read(assessment_ref, GovInspectionAssessmentView, True)
                author(assessment)
                if assessment.issue_ref != issue.ref or not assessment.requirement_snapshots:
                    raise ValueError('Recheck assessment has no original issue/requirement coverage')
                keys([r.requirement_ref for r in assessment.requirement_snapshots])
                unchanged = assessment.status == 'valid' and all(r.requirement_ref.key() in current
                    and r.content_sha256 == current[r.requirement_ref.key()].content_sha256
                    and r.fact_sha256 == fact_hashes.get(r.requirement_ref.key()) for r in assessment.requirement_snapshots)
                (reusable if unchanged else affected).append(assessment.ref)
            resolutions.append({'issue_ref': issue.ref, 'response_refs': issue.response_refs,
                'verification_result_ref': result_ref, 'resolution': resolution, 'retained_requirement_refs': retained,
                'affected_assessment_refs': affected, 'reusable_assessment_refs': reusable})
        return complete('recheck', resolutions=resolutions)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
