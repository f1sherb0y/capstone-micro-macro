"""ARCHITECT-A13 finite report and separately authorized investigation request."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Measured
from src.actions.contracts.architect_research_objects import (
    ArchitectResearchAuthorityView, ArchitectResearchDecisionView, ArchitectResearchTaskView,
    ArchitectResearchProfileView, ArchitectResearchOptionView, ArchitectResearchAssessmentView,
    ArchitectResearchScopeView, ArchitectResearchMethodView, ArchitectResearchGapView,
    ArchitectResearchRequestView, ArchitectResearchReferenceView, ArchitectResearchLimitView,
    ArchitectResearchEstimateView, ArchitectResearchEstimateMethodView,
    ArchitectResearchEstimatePreparation, ArchitectResearchWorkView,
)
from src.actions.contracts.qs_cost_objects import QSCostBriefView
from src.actions.contracts.qs_research_objects import QSResearchExpenseView, QSResearchCostFactView, QSResearchCostPlanView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.architect_research import ARCHITECT_COMPARE_METHOD, ArchitectComparisonInput
from src.methods.architect_research_estimates import (
    ARCHITECT_RESEARCH_ESTIMATE_METHOD, ArchitectResearchEstimateInput, estimate_declared_architect_research,
)
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def compare_preliminary_options(context, action_input, reading):
    return _compare_preliminary_options(context, action_input, reading)


def recheck_original_architect_research_wait(context, action_input, reading):
    """Reproduce the original task wait before comparison or investigation preparation."""
    result = _compare_preliminary_options(context, action_input, reading, original_wait_only=True)
    if (not isinstance(result, dict) or result.get('resume_condition', {}).get('condition_code') != 'architect.research.task_ready'):
        raise ValueError('Original research sources do not reproduce the actual task readiness wait')
    return result


def prepare_architect_research_estimate_input(context, action_input, reading, preparation):
    """Reuse original research gates without executing comparison or estimate."""
    preparation = ArchitectResearchEstimatePreparation.model_validate(preparation).model_copy(deep=True)
    if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ARCHITECT-A13':
        raise ValueError('Research estimate requires its original Architect A13 contract')
    reading.check_method_context(context, 'ARCHITECT-A13')
    before = reading.method_evidence()

    def check_preparation():
        if reading.method_evidence() != before or preparation.calculation_ref.key() in reading._reads:
            raise ValueError('Research preparation cannot execute methods or consume its future estimate')

    check_preparation()
    try:
        return _compare_preliminary_options(context, action_input, reading, estimate_preparation=preparation)
    finally:
        reading.recheck()
        check_preparation()


def _compare_preliminary_options(context, action_input, reading, *, estimate_preparation=None, original_wait_only=False):
    scope, now, sources = action_input.scope, context.business_time, {}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('architect-research-clock-alignment')

    def current(window, at=now):
        clock(window.start); clock(at)
        if not window.contains(at):
            _needs('current_original_research_input_or_authority')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('architect-research-evidence-schema')
            if row.effective_window is not None: current(row.effective_window)
            sources[ref.key()] = ref

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'architect-research-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(row.scope, scope):
            raise ValueError('Research input does not cover the authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_research_input', [ref])
            current(row.effective_window)
        evidence(getattr(row, 'evidence_refs', [])); sources[ref.key()] = ref
        return row

    def authorized(ref, actor, function, action, roles, organization=None, at=now):
        grant = read(ref, Authorization); assignment = read(function, RoleAssignment)
        if (grant.actor_id != actor or grant.function_ref != function or assignment.role not in roles
                or (organization is not None and grant.organization_id != organization)
                or action not in grant.action_ids or not any(scope_covers(s, scope) for s in grant.scopes)):
            raise ValueError('Research author/delegate lacks original independent action and scope authority')
        current(grant.validity, at); evidence([*grant.basis_refs, *assignment.basis_refs])

    def author(row, action='ARCHITECT-A13', roles={'Architect'}):
        authorized(row.author_authority_ref, row.author_actor_id, row.author_function_ref, action, roles)

    def questions(rows):
        for question in rows:
            if question.scope != scope or not question.target_refs or not question.recipient_ids:
                raise ValueError('Research question lacks original scoped target and recipient')
            if not set(question.recipient_ids) <= set(grant.allowed_recipient_ids):
                raise ValueError('Research question names an independently unauthorized recipient')
            if not set(question.blocking_uses) <= {'research'}:
                raise ValueError('Research question borrows an undeclared delivery purpose')
            unique_refs(question.target_refs)
            for ref in question.target_refs:
                target = read(ref, ArchitectResearchGapView)
                if (target.task_ref != task.ref or target.brief_ref != brief.ref
                        or (target.option_ref is not None and target.option_ref not in task.available_option_refs)):
                    raise ValueError('Research question changes original task, brief or option')
            response = read(question.response_requirement_ref, ArchitectResearchReferenceView)
            if response.task_ref != task.ref: raise ValueError('Research response requirement changes task')
            evidence(question.evidence_refs)
        return rows

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope': scope,
            'note': 'Finite original-version research only; no investment, permit, fee accrual or further appointment', **fields}}

    def technical(code):
        reading.recheck()
        return {'kind': 'technical_error', 'error': {'kind': 'unrecorded', 'correlation_id': context.operation_id,
                'code': code}, 'retryability': 'unknown'}

    def dimensions(rows):
        if len({r.code for r in rows}) != len(rows): raise ValueError('Research repeats a comparison dimension')
        values = {r.code: r.value for r in rows}
        return all(r.value.state == 'known' and r.code in values and values[r.code].state == 'known'
                   and values[r.code].value == r.value.value for r in comparison_scope.required_dimensions)

    def metric(rows, code):
        if len({r.code for r in rows}) != len(rows): raise ValueError('Research repeats an original metric')
        values = [r.value for r in rows if r.code == code]
        if len(values) != 1 or values[0].state != 'known': return None
        evidence([values[0].value.basis_ref]); return values[0].value

    try:
        if scope != context.scope: raise ValueError('Research changes invocation scope')
        brief = read(action_input.brief_ref, QSCostBriefView)
        task = read(action_input.task_ref, ArchitectResearchTaskView)
        grant = read(action_input.research_authority_ref, ArchitectResearchAuthorityView)
        limit = read(action_input.expenditure_limit_ref, ArchitectResearchLimitView)
        profile = read(action_input.design_profile_ref, ArchitectResearchProfileView)
        comparison_scope = read(action_input.comparison_scope_ref, ArchitectResearchScopeView)
        if (task.organization_id != reading.organization_id or task.function_ref != context.function_ref
                or task.brief_ref != brief.ref or task.design_profile_ref != profile.ref
                or task.expenditure_limit_ref != limit.ref or task.comparison_scope_ref != comparison_scope.ref
                or task.comparison_method_ref != action_input.comparison_method_ref
                or comparison_scope.task_ref != task.ref or comparison_scope.brief_ref != brief.ref
                or grant.task_ref != task.ref or grant.brief_ref != brief.ref
                or grant.delegate_actor_id != context.actor_id or grant.delegate_function_ref != context.function_ref
                or grant.delegate_organization_id != reading.organization_id
                or limit.task_ref != task.ref or limit.organization_id != reading.organization_id):
            raise ValueError('Research changes original delegation, task, brief, profile, comparison or spending limit')
        authorized(task.authority_ref, context.actor_id, context.function_ref, 'ARCHITECT-A13', {'Architect'}, reading.organization_id)
        authorized(limit.authority_ref, context.actor_id, context.function_ref, 'ARCHITECT-A13', {'Architect'}, reading.organization_id)
        clock(grant.granted_at)
        if grant.granted_at.offset > grant.available_at.offset: raise ValueError('Research delegation receipt precedes grant')
        authorized(grant.client_authority_ref, grant.client_actor_id, grant.client_function_ref, grant.client_action_id,
                   {'Owner'}, grant.client_organization_id, grant.granted_at)
        if not _known(grant.permission, 'independent_client_research_permission'):
            _needs('independent_client_research_permission')
        if ('research' not in grant.allowed_uses or 'research' not in brief.allowed_uses
                or context.actor_id not in brief.recipient_ids or 'research' not in profile.allowed_uses):
            _needs('authorized_original_research_use_and_recipient')
        author(profile)
        for ref, action, choice in [(grant.acceptance_ref, 'ARCHITECT-A02', 'accept'),
                                   (grant.confirmation_ref, 'ARCHITECT-A03', 'confirm')]:
            decision = read(ref, ArchitectResearchDecisionView)
            if (decision.action_id != action or decision.choice != choice or decision.actor_id != context.actor_id
                    or decision.organization_id != reading.organization_id or decision.function_ref != context.function_ref
                    or decision.service_request_ref != grant.service_request_ref
                    or decision.accepted_terms_ref != grant.accepted_terms_ref or decision.terms_digest != grant.terms_digest
                    or (action == 'ARCHITECT-A03' and decision.appointment_ref != grant.appointment_ref)):
                raise ValueError('Research lacks exact independently accepted and confirmed appointment/terms')
            clock(decision.decided_at)
            if decision.decided_at.offset > decision.available_at.offset: raise ValueError('Research acceptance receipt precedes decision')
            authorized(decision.authority_ref, decision.actor_id, decision.function_ref, action, {'Architect'},
                       reading.organization_id, decision.decided_at)
        for field in ('available_option_refs', 'professional_refs', 'cost_refs'):
            unique_refs(getattr(action_input, field)); unique_refs(getattr(task, field))
            if set(getattr(action_input, field)) != set(getattr(task, field)):
                _needs('complete_original_research_' + field, getattr(task, field))
        if limit.as_of != now: _needs('current_original_research_limit_snapshot')
        evidence([limit.budget_cap.basis_ref, limit.effort_cap.basis_ref])
        cap, work_cap = decimal_fraction(limit.budget_cap.value), decimal_fraction(limit.effort_cap.value)
        if cap < 0 or work_cap < 0: raise ValueError('Research limits are negative')
        used, worked, facts = Fraction(), Fraction(), {}
        unique_refs(limit.expense_refs)
        for ref in limit.expense_refs:
            expense = read(ref, QSResearchExpenseView); fact = read(expense.cost_fact_ref, QSResearchCostFactView)
            if (expense.task_ref != task.ref or fact.task_ref != task.ref or fact.organization_id != reading.organization_id
                    or expense.amount != fact.amount or expense.effort != fact.effort or expense.status != fact.status):
                raise ValueError('Research expense changes actual work/cost fact identity or state')
            evidence([fact.amount.basis_ref, fact.effort.basis_ref])
            if fact.amount.currency != limit.budget_cap.currency or fact.effort.unit != limit.effort_cap.unit:
                _unsupported('architect-research-actual-cost-or-effort-conversion')
            amount, effort = decimal_fraction(fact.amount.value), decimal_fraction(fact.effort.value)
            if amount < 0 or effort < 0: raise ValueError('Actual research cost or work is negative')
            key = (fact.ref.kind, fact.ref.id)
            actual = (amount, effort, fact.status)
            if key in facts:
                if facts[key] != actual: _needs('current_single_original_research_cost_fact')
                continue
            facts[key] = actual; used += amount; worked += effort
        at_limit = (task.status == 'closed' or limit.status != 'active' or used >= cap or worked >= work_cap)
        if limit.deadline is not None:
            clock(limit.deadline); at_limit = at_limit or now.offset >= limit.deadline.offset
        if task.status == 'waiting' and not at_limit:
            reading.recheck()
            return {'kind': 'deferred', 'reason_code': 'architect_research_waiting', 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [task.ref], 'earliest_time': None,
                'condition_code': 'architect.research.task_ready'}}
        if original_wait_only:
            reading.recheck()
            return None
        if estimate_preparation is not None:
            if at_limit:
                _needs('architect_investigation_within_original_remaining_limits')
            if comparison_scope.missing_policy != 'request' or task.request_profile_ref is None:
                _needs('original_architect_investigation_request')
            request = read(task.request_profile_ref, ArchitectResearchRequestView)
            if (request.ref != estimate_preparation.request_profile_ref or request.task_ref != task.ref
                    or request.scope != scope or request.authority_basis_refs != [grant.ref]
                    or request.purpose not in grant.allowed_purposes
                    or not set(request.input_refs) <= set(grant.allowed_input_refs)):
                raise ValueError('Estimate changes original request, purpose, task or delegated inputs')
            if request.estimate_ref != estimate_preparation.calculation_ref or type(request.estimate_ref.version) is not str:
                raise ValueError('Estimate replaces original immutable request result target')
            if request.work_profile_ref is None:
                _needs('sourced_original_architect_investigation_work_profile')
            work = read(request.work_profile_ref, ArchitectResearchWorkView)
            if work.task_ref != task.ref:
                raise ValueError('Research work basis borrows another task')
            basis = work.estimate_basis
            if basis is None:
                _needs('sourced_original_architect_investigation_work_estimate')
            if (basis.method_ref != ARCHITECT_RESEARCH_ESTIMATE_METHOD
                    or request.purpose not in basis.allowed_purposes
                    or not profile.object_types or not set(profile.object_types) <= set(basis.allowed_object_types)
                    or not profile.region_ids or not set(profile.region_ids) <= set(basis.allowed_region_ids)):
                _unsupported('architect-investigation-work-estimate-support-domain')
            method = read(basis.method_ref, ArchitectResearchEstimateMethodView)
            if method.design_profile_ref != profile.ref or request.purpose not in method.allowed_purposes:
                _unsupported('architect-investigation-estimate-method-domain')
            numeric_refs = [basis.quantity.basis_ref, basis.effort_per_unit.basis_ref,
                basis.cost_per_effort.basis_ref, basis.fixed_cost.basis_ref]
            evidence(numeric_refs)
            amount = _known(request.incremental_cost, 'original_architect_investigation_cost')
            effort = _known(request.effort_estimate, 'supported_architect_investigation_effort')
            evidence([amount.basis_ref, effort.basis_ref])
            if (amount.currency != limit.budget_cap.currency or amount.currency != basis.cost_per_effort.currency
                    or effort.unit != limit.effort_cap.unit or effort.unit != basis.effort_per_unit.unit):
                _unsupported('architect-investigation-estimate-unit-currency-conversion')
            if min(decimal_fraction(amount.value), decimal_fraction(effort.value)) < 0:
                raise ValueError('Original investigation cost/work estimates are negative')
            if decimal_fraction(amount.value) > cap - used or decimal_fraction(effort.value) > work_cap - worked:
                _needs('architect_investigation_within_original_remaining_limits')
            if request.desired_window.state == 'known':
                window = request.desired_window.value
                clock(window.start)
                if window.start.offset < now.offset:
                    _needs('future_architect_investigation_window')
                if limit.deadline is not None and window.end.offset > limit.deadline.offset:
                    _needs('architect_investigation_within_original_deadline')
            for refs in (request.input_refs, request.output_requirement_refs, request.dependency_refs):
                unique_refs(refs)
                for ref in refs:
                    reading.resolve(ref)
            for ref in [*request.output_requirement_refs, *request.dependency_refs]:
                if read(ref, ArchitectResearchReferenceView).task_ref != task.ref:
                    raise ValueError('Research estimate borrows another task requirements or dependencies')
            source_refs = list({ref.key(): ref for ref in [task.ref, brief.ref, grant.ref, limit.ref,
                profile.ref, comparison_scope.ref, request.ref, work.ref, method.ref, *numeric_refs,
                amount.basis_ref, effort.basis_ref, *request.input_refs, *request.output_requirement_refs,
                *request.dependency_refs, *task.evidence_refs, *grant.evidence_refs, *request.evidence_refs,
                *work.evidence_refs, *method.evidence_refs]}.values())
            original = ArchitectResearchEstimateInput(work_profile_ref=work.ref, quantity=basis.quantity,
                effort_per_unit=basis.effort_per_unit, effort_quantity_unit=basis.effort_quantity_unit,
                cost_per_effort=basis.cost_per_effort, cost_effort_unit=basis.cost_effort_unit,
                fixed_cost=basis.fixed_cost, source_refs=source_refs)
            if estimate_preparation.input != original:
                raise ValueError('Estimate preparation changes original sourced quantities, rates or inputs')
            reading.recheck()
            return {'kind': 'prepared', 'preparation': estimate_preparation, 'task': task, 'brief': brief,
                'grant': grant, 'request': request, 'work': work, 'method': method}
        unresolved = []
        unique_refs(task.question_refs)
        for ref in task.question_refs:
            gap = read(ref, ArchitectResearchGapView)
            if gap.task_ref != task.ref or gap.brief_ref != brief.ref: raise ValueError('Research gap changes task or brief')
            unresolved.extend(questions([gap.question]))
        options, assessments, costs = [], [], []
        limitations, notes = [], []
        for ref in task.available_option_refs:
            option = read(ref, ArchitectResearchOptionView); author(option, 'ARCHITECT-A05')
            if (option.brief_ref != brief.ref or option.design_profile_ref != profile.ref or option.task_ref != task.ref):
                raise ValueError('Research option changes original brief/profile/task')
            options.append(option); unresolved.extend(questions(option.unresolved_questions)); notes.extend(option.limitations)
            if (option.compilation_status != 'completed' or 'research' not in option.allowed_uses
                    or option.object_type not in profile.object_types or option.region_id not in profile.region_ids
                    or not dimensions(option.dimensions)):
                limitations.append('Option compilation, support, original use or comparison dimensions incomplete')
        for ref in task.professional_refs:
            row = read(ref, ArchitectResearchAssessmentView)
            if row.brief_ref != brief.ref or row.option_ref not in task.available_option_refs:
                raise ValueError('Professional input changes original brief or candidate')
            assignment = read(row.author_function_ref, RoleAssignment)
            allowed_actions = {'Engineer': {'ENGINEER-A05', 'ENGINEER-A06', 'ENGINEER-A13'},
                               'Architect': {'ARCHITECT-A05', 'ARCHITECT-A08', 'ARCHITECT-A13'}}
            if row.author_action_id not in allowed_actions.get(assignment.role, set()):
                _unsupported('architect-research-professional-source-action')
            author(row, row.author_action_id, {assignment.role}); assessments.append(row); notes.extend(row.limitations)
            if row.comparison_scope_ref != comparison_scope.ref or 'research' not in row.allowed_uses:
                limitations.append('Professional comparison coverage/use incompatible')
            if row.status != 'ok' or row.finding != 'compatible':
                limitations.append('Professional conflict, unknown finding or unsupported/failed check retained')
        for ref in task.cost_refs:
            row = read(ref, QSResearchCostPlanView); author(row, 'QS-A04', {'QS'})
            if row.brief_ref != brief.ref or row.draft.option_ref not in task.available_option_refs:
                raise ValueError('Submitted cost changes original brief or candidate')
            costs.append(row)
        if unresolved: limitations.append('Original research questions remain unresolved')
        if not options: limitations.append('No registered candidate is available')
        recommended = []
        method = None
        if action_input.comparison_method_ref is not None:
            method = read(action_input.comparison_method_ref, ArchitectResearchMethodView); author(method)
            if method.task_ref != task.ref or method.comparison_scope_ref != comparison_scope.ref:
                raise ValueError('Comparison method changes original task or scope')
            if method.method_ref != ARCHITECT_COMPARE_METHOD or 'research' not in method.allowed_uses:
                limitations.append('Selected comparison method does not support this finite research')
        else: limitations.append('No applicable comparison method is available')
        metric_options = []
        for option in options:
            professional = [r for r in assessments if r.option_ref == option.ref]
            coverage = {key for row in professional if row.status == 'ok' and row.finding == 'compatible'
                        and row.comparison_scope_ref == comparison_scope.ref for key in row.coverage_keys}
            if not set(comparison_scope.required_professional_coverage_keys) <= coverage:
                limitations.append('Professional comparison coverage incomplete')
            option_costs = [r for r in costs if r.draft.option_ref == option.ref]
            valid_costs = []
            for row in option_costs:
                total = row.draft.complete_total
                if (row.status != 'submitted' or total is None or row.draft.missing_items
                        or not dimensions(row.comparison_dimensions) or row.draft.calculation_ref is None): continue
                lines = row.draft.lines
                if len(set(row.coverage_keys)) != len(row.coverage_keys) or len({r.line_key for r in lines}) != len(lines):
                    raise ValueError('Saved scoped cost repeats physical coverage or original line identity')
                if row.draft.known_subtotal.state != 'known' or row.draft.known_subtotal.value != total:
                    raise ValueError('Saved complete cost differs from its original calculated subtotal')
                if (not lines or any(r.amount.state != 'known' or r.calculation_ref != row.draft.calculation_ref
                                     or r.amount.value.currency != total.currency for r in lines)): continue
                if sum((decimal_fraction(r.amount.value.value) for r in lines), Fraction()) != decimal_fraction(total.value):
                    raise ValueError('Saved cost total differs from original calculated lines')
                evidence([total.basis_ref]); valid_costs.append(row)
            if comparison_scope.require_costs and not valid_costs: limitations.append('Submitted scoped costs incomplete')
            values = []
            if method is not None:
                for criterion in method.criteria:
                    value = None
                    if criterion.source == 'option': value = metric(option.metrics, criterion.code)
                    elif criterion.source == 'professional':
                        candidates = [metric(row.metrics, criterion.code) for row in professional]
                        candidates = [v for v in candidates if v is not None]
                        if len(candidates) == 1: value = candidates[0]
                    elif criterion.code == 'complete_total' and len(valid_costs) == 1:
                        total = valid_costs[0].draft.complete_total
                        value = Measured(value=total.value, unit=total.currency, basis_ref=total.basis_ref)
                    if value is None or value.unit != criterion.unit:
                        limitations.append('Selected metric is unknown, ambiguous or uses incompatible units')
                    else: values.append(value)
            metric_options.append({'option_ref': option.ref, 'values': values})
        if not at_limit and not limitations and method is not None:
            result = reading.calculate(ARCHITECT_COMPARE_METHOD, ArchitectComparisonInput(
                criteria=method.criteria, options=metric_options, source_refs=list(sources.values())))
            if result.kind != 'ok':
                if result.kind == 'invalid_input': _unsupported('architect-research-comparison-domain')
                raw = result.model_dump(mode='python')
                if result.kind == 'needs_information': raw['requested_refs'] = []
                raise ObservationGap(raw)
            recommended = result.value.recommended_option_refs
        comparison = {'option_refs': task.available_option_refs, 'comparable_scope_ref': comparison_scope.ref,
            'professional_refs': task.professional_refs, 'cost_refs': task.cost_refs,
            'recommended_option_refs': recommended, 'unresolved_questions': unresolved,
            'comparison_method_ref': action_input.comparison_method_ref,
            'reason': ('; '.join(dict.fromkeys(limitations)) or 'Declared nondominated alternatives; equal values/tradeoffs retained without a strict ranking')
                      + ('; original assumptions/limits: ' + '; '.join(dict.fromkeys(notes)) if notes else '')}
        if at_limit: return completed('deliver_at_limit', comparison=comparison, remaining_questions=unresolved)
        if not recommended and unresolved and comparison_scope.missing_policy == 'request' and task.request_profile_ref is not None:
            request = read(task.request_profile_ref, ArchitectResearchRequestView)
            if (request.task_ref != task.ref or request.scope != scope or request.authority_basis_refs != [grant.ref]
                    or request.purpose not in grant.allowed_purposes):
                raise ValueError('Investigation request changes original task, scope or independent purpose authorization')
            if not set(request.input_refs) <= set(grant.allowed_input_refs):
                raise ValueError('Investigation request contains independently unauthorized inputs')
            if request.estimate_ref is None: _needs('saved_supported_incremental_research_estimate')
            estimate = read(request.estimate_ref, ArchitectResearchEstimateView); author(estimate)
            if (estimate.task_ref != task.ref or estimate.request_profile_ref != request.ref
                    or set(estimate.input_refs) != set(request.input_refs) or estimate.work_profile_ref != request.work_profile_ref
                    or estimate.incremental_cost != request.incremental_cost or estimate.effort_estimate != request.effort_estimate):
                raise ValueError('Incremental estimate changes original request, inputs or work profile')
            unique_refs(estimate.input_refs)
            if estimate.status == 'failed': return technical('architect_research_estimate_failed')
            if estimate.status != 'ok': _unsupported('architect-research-incremental-estimate-method')
            estimate_method = read(estimate.method_ref, ArchitectResearchEstimateMethodView)
            if estimate_method.design_profile_ref != profile.ref or request.purpose not in estimate_method.allowed_purposes:
                _unsupported('architect-research-estimate-support-domain')
            if estimate.method_ref == ARCHITECT_RESEARCH_ESTIMATE_METHOD:
                if request.work_profile_ref is None:
                    _needs('sourced_original_architect_investigation_work_profile')
                work = read(request.work_profile_ref, ArchitectResearchWorkView)
                if (work.task_ref != task.ref or estimate.author_authority_ref != task.authority_ref
                        or estimate.author_actor_id != context.actor_id or estimate.author_function_ref != context.function_ref):
                    raise ValueError('Local research estimate changes original work task or producing author')
                basis = work.estimate_basis
                if basis is None:
                    _needs('sourced_original_architect_investigation_work_estimate')
                if (basis.method_ref != ARCHITECT_RESEARCH_ESTIMATE_METHOD
                        or request.purpose not in basis.allowed_purposes
                        or not profile.object_types or not set(profile.object_types) <= set(basis.allowed_object_types)
                        or not profile.region_ids or not set(profile.region_ids) <= set(basis.allowed_region_ids)):
                    _unsupported('architect-investigation-work-estimate-support-domain')
                numeric_refs = [basis.quantity.basis_ref, basis.effort_per_unit.basis_ref,
                    basis.cost_per_effort.basis_ref, basis.fixed_cost.basis_ref]
                evidence(numeric_refs)
                local_input = ArchitectResearchEstimateInput(work_profile_ref=work.ref, quantity=basis.quantity,
                    effort_per_unit=basis.effort_per_unit, effort_quantity_unit=basis.effort_quantity_unit,
                    cost_per_effort=basis.cost_per_effort, cost_effort_unit=basis.cost_effort_unit,
                    fixed_cost=basis.fixed_cost, source_refs=list({ref.key(): ref for ref in [work.ref, *numeric_refs]}.values()))
                expected = estimate_declared_architect_research(local_input)
                cost = _known(estimate.incremental_cost, 'original_architect_investigation_cost')
                effort = _known(estimate.effort_estimate, 'supported_architect_investigation_effort')
                if cost != expected.estimated_cost or effort != expected.effort:
                    raise ValueError('Saved local research estimate differs from original work quantity, rates or basis')
            amount = _known(request.incremental_cost, 'original_incremental_research_cost')
            evidence([amount.basis_ref])
            if amount.currency != limit.budget_cap.currency: _unsupported('architect-research-request-currency-conversion')
            if decimal_fraction(amount.value) < 0: raise ValueError('Incremental research estimate is negative')
            if decimal_fraction(amount.value) > cap - used:
                return completed('no_recommendation', comparison=comparison, reason='Supplement would exceed original remaining budget')
            if request.effort_estimate.state == 'known':
                effort = request.effort_estimate.value; evidence([effort.basis_ref])
                if effort.unit != limit.effort_cap.unit: _unsupported('architect-research-request-effort-conversion')
                if decimal_fraction(effort.value) < 0: raise ValueError('Incremental work estimate is negative')
                if decimal_fraction(effort.value) > work_cap - worked:
                    return completed('no_recommendation', comparison=comparison, reason='Supplement would exceed original remaining work allowance')
            elif request.work_profile_ref is not None: _needs('supported_incremental_research_effort_estimate')
            if request.desired_window.state == 'known':
                window = request.desired_window.value; clock(window.start)
                if window.start.offset < now.offset: _needs('future_incremental_research_window')
                if limit.deadline is not None and window.end.offset > limit.deadline.offset:
                    return completed('no_recommendation', comparison=comparison, reason='Supplement would exceed original research deadline')
            for refs in (request.input_refs, request.output_requirement_refs, request.dependency_refs):
                unique_refs(refs)
                for ref in refs: reading.resolve(ref)
            if request.work_profile_ref is not None: reading.resolve(request.work_profile_ref)
            payload_request = request.model_dump(exclude={'ref', 'task_ref', 'available_at', 'effective_window',
                                                         'evidence_refs', 'incremental_cost', 'estimate_ref'})
            payload_request['questions'] = unresolved
            return completed('recommend_investigation', questions=unresolved, request=payload_request)
        if not recommended:
            return completed('no_recommendation', comparison=comparison, reason=comparison['reason'])
        return completed('compare', comparison=comparison)
    except ObservationGap as gap:
        reading.recheck(); return gap.result
