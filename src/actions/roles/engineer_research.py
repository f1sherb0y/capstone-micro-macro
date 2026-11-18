"""ENGINEER-A13 original checks and bounded reports without favorable-result bias."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.engineer_research_objects import (
    EngineerResearchAuthorityView, EngineerResearchDecisionView, EngineerResearchTaskView,
    EngineerResearchIndependenceView, EngineerResearchTargetView, EngineerResearchScopeView,
    EngineerResearchFactView, EngineerResearchCheckSpecView, EngineerResearchAssessmentView, EngineerResearchAssessment,
    EngineerResearchMethodProjection, EngineerResearchMethodView, EngineerResearchGapView,
    EngineerResearchCheckPreparation,
    EngineerResearchEstimatePreparation, EngineerResearchWorkView,
)
from src.actions.contracts.architect_research_objects import (
    ArchitectResearchLimitView, ArchitectResearchRequestView, ArchitectResearchReferenceView,
)
from src.actions.contracts.qs_cost_objects import QSCostBriefView
from src.actions.contracts.qs_research_objects import QSResearchExpenseView, QSResearchCostFactView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.engineer_checks import ENGINEER_INTERFACE_METHOD, EngineerInterfaceInput, check_interface
from src.methods.engineer_research_estimates import (
    ENGINEER_RESEARCH_ESTIMATE_METHOD, EngineerResearchEstimateInput, estimate_declared_research,
)
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers
from src.methods.pricing import decimal_fraction


def assess_preliminary_options(context, action_input, reading):
    return _assess_preliminary_options(context, action_input, reading)


def recheck_original_engineer_research_wait(context, action_input, reading):
    """Reproduce original delegation and task wait before research or preparation."""
    before = reading.method_evidence()
    try:
        result = _assess_preliminary_options(context, action_input, reading, original_wait_only=True)
        if (not isinstance(result, dict)
                or result.get('resume_condition', {}).get('condition_code') != 'engineer.research.ready'):
            raise ValueError('Original engineering research sources do not reproduce their actual task wait')
        return result
    finally:
        reading.recheck()
        if reading.method_evidence() != before:
            raise ValueError('Historical research wait recheck cannot execute a professional method')


def prepare_engineer_research_check_input(context, action_input, reading, preparation):
    """Reuse original delegation/work gates without reading future findings."""
    preparation = EngineerResearchCheckPreparation.model_validate(preparation).model_copy(deep=True)
    return _prepare_engineer_research_input(context, action_input, reading, check_preparation=preparation)


def prepare_engineer_research_estimate_input(context, action_input, reading, preparation):
    """Prepare sourced investigation cost/work without executing the estimate."""
    preparation = EngineerResearchEstimatePreparation.model_validate(preparation).model_copy(deep=True)
    return _prepare_engineer_research_input(context, action_input, reading, estimate_preparation=preparation)


def _prepare_engineer_research_input(context, action_input, reading, *, check_preparation=None, estimate_preparation=None):
    if (check_preparation is None) == (estimate_preparation is None):
        raise ValueError('Research preparation requires exactly one fixed input kind')
    preparation = check_preparation if check_preparation is not None else estimate_preparation
    if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ENGINEER-A13':
        raise ValueError('Research check preparation requires its original Engineer A13 contract')
    reading.check_method_context(context, 'ENGINEER-A13')
    before = reading.method_evidence()
    future = {preparation.calculation_ref.key()}
    if check_preparation is not None:
        future.update(ref.key() for ref in action_input.method_result_refs)

    def recheck_preparation():
        if reading.method_evidence() != before or future.intersection(reading._reads):
            raise ValueError('Research preparation cannot execute methods or consume future results')

    recheck_preparation()
    try:
        return _assess_preliminary_options(context, action_input, reading,
            check_preparation=check_preparation, estimate_preparation=estimate_preparation)
    finally:
        reading.recheck()
        recheck_preparation()


def _assess_preliminary_options(context, action_input, reading, *, check_preparation=None,
        estimate_preparation=None, original_wait_only=False):
    scope, now = action_input.scope, context.business_time

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('engineer-research-clock-alignment')

    def current(window, at=now):
        clock(window.start); clock(at)
        if not window.contains(at): _needs('current_original_engineer_research_record')

    def evidence(refs):
        rows = []
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('engineer-research-evidence-schema')
            if row.effective_window is not None: current(row.effective_window)
            rows.append(row)
        return rows

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'engineer-research-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(row.scope, scope):
            raise ValueError('Engineering research projection changes authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_engineering_research_input', [ref])
            current(row.effective_window)
        evidence(getattr(row, 'evidence_refs', [])); return row

    def authorized(ref, actor, function, action, roles, organization=None, at=now):
        grant = read(ref, Authorization); assignment = read(function, RoleAssignment)
        if (grant.actor_id != actor or grant.function_ref != function or assignment.role not in roles
                or (organization is not None and grant.organization_id != organization)
                or action not in grant.action_ids or not any(scope_covers(s, scope) for s in grant.scopes)):
            raise ValueError('Original independent engineering author/delegate authority is incompatible')
        current(grant.validity, at); evidence([*grant.basis_refs, *assignment.basis_refs])

    def author(row, action=None, roles={'Engineer'}):
        authorized(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
                   action or getattr(row, 'author_action_id', 'ENGINEER-A13'), roles)

    def questions(rows):
        for question in rows:
            if question.scope != scope or not question.target_refs or not question.recipient_ids:
                raise ValueError('Engineering investigation lacks original scoped targets or recipients')
            if not set(question.recipient_ids) <= set(grant.allowed_recipient_ids):
                raise ValueError('Engineering research discloses inputs to an unauthorized question recipient')
            if not set(question.blocking_uses) <= {'research'}:
                raise ValueError('Engineering research question borrows another delivery use')
            for ref in question.target_refs:
                gap = read(ref, EngineerResearchGapView)
                if gap.task_ref != task.ref or gap.brief_ref != brief.ref:
                    raise ValueError('Engineering investigation target changes original task or brief')
            response = read(question.response_requirement_ref, ArchitectResearchReferenceView)
            if response.task_ref != task.ref: raise ValueError('Investigation response requirement changes task')
            evidence(question.evidence_refs)
        return rows

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope': scope,
            'note': 'Finite research report/request; no hidden facts, whole-project approval, appointment or fee accrual', **fields}}

    def technical(code):
        reading.recheck()
        return {'kind': 'technical_error', 'error': {'kind': 'unrecorded', 'correlation_id': context.operation_id,
                'code': code}, 'retryability': 'unknown'}

    def method_domain(ref):
        if ref != ENGINEER_INTERFACE_METHOD:
            _unsupported('engineer-research-unbound-professional-method')
        method = read(ref, EngineerResearchMethodView)
        if (task.discipline_code not in method.allowed_discipline_codes
                or task.function_code not in method.allowed_function_codes
                or 'synthetic_interface_code_equality' not in method.purposes):
            _unsupported('engineer-research-method-support-domain')

    def original_facts(spec):
        original, basis = [], []
        for ref in [spec.left_fact_ref, spec.right_fact_ref]:
            if ref is None:
                original.append(None)
                continue
            fact = read(ref, EngineerResearchFactView)
            if fact.target_ref.key() != spec.target_ref.key() or fact.engineering_scope_ref != spec.engineering_scope_ref:
                raise ValueError('Check evidence changes original target or engineering coverage')
            original.append(fact)
            basis.extend(fact.evidence_refs)
        refs = [ref for ref in (spec.left_fact_ref, spec.right_fact_ref) if ref is not None]
        states = [row.value if row is not None else {'state': 'unknown',
            'reason_code': 'original_interface_code_missing', 'missing_refs': []} for row in original]
        return original, basis, refs, states

    try:
        if scope != context.scope: raise ValueError('Engineering research changes invocation scope')
        brief = read(action_input.brief_ref, QSCostBriefView)
        grant = read(action_input.research_authority_ref, EngineerResearchAuthorityView)
        task = read(action_input.task_ref, EngineerResearchTaskView)
        limit = read(action_input.expenditure_limit_ref, ArchitectResearchLimitView)
        if (grant.brief_ref != brief.ref or grant.task_ref != task.ref or task.brief_ref != brief.ref
                or task.organization_id != reading.organization_id or task.function_ref != context.function_ref
                or grant.delegate_actor_id != context.actor_id or grant.delegate_function_ref != context.function_ref
                or grant.delegate_organization_id != reading.organization_id or task.expenditure_limit_ref != limit.ref
                or limit.task_ref != task.ref or limit.organization_id != reading.organization_id):
            raise ValueError('Engineering research changes original delegation, task, brief or limit')
        authorized(task.authority_ref, context.actor_id, context.function_ref, 'ENGINEER-A13', {'Engineer'}, reading.organization_id)
        authorized(limit.authority_ref, context.actor_id, context.function_ref, 'ENGINEER-A13', {'Engineer'}, reading.organization_id)
        clock(grant.granted_at)
        if grant.granted_at.offset > grant.available_at.offset: raise ValueError('Research receipt precedes independent delegation')
        authorized(grant.client_authority_ref, grant.client_actor_id, grant.client_function_ref, grant.client_action_id,
                   {'Owner'}, grant.client_organization_id, grant.granted_at)
        if not _known(grant.permission, 'independent_engineering_research_permission'):
            _needs('independent_engineering_research_permission')
        if ('research' not in grant.allowed_uses or 'research' not in brief.allowed_uses or context.actor_id not in brief.recipient_ids
                or task.discipline_code not in grant.allowed_discipline_codes or task.function_code not in grant.allowed_function_codes):
            _needs('authorized_engineering_research_discipline_function_and_use')
        for ref, action, choice in [(grant.acceptance_ref, 'ENGINEER-A02', 'accept'), (grant.confirmation_ref, 'ENGINEER-A03', 'confirm')]:
            row = read(ref, EngineerResearchDecisionView)
            if (row.action_id != action or row.choice != choice or row.actor_id != context.actor_id
                    or row.organization_id != reading.organization_id or row.function_ref != context.function_ref
                    or row.service_request_ref != grant.service_request_ref or row.accepted_terms_ref != grant.accepted_terms_ref
                    or row.terms_digest != grant.terms_digest or (action == 'ENGINEER-A03' and row.appointment_ref != grant.appointment_ref)):
                raise ValueError('Finite research lacks exact independent acceptance and confirmation')
            clock(row.decided_at)
            if row.decided_at.offset > row.available_at.offset: raise ValueError('Engineering acceptance receipt precedes decision')
            authorized(row.authority_ref, row.actor_id, row.function_ref, action, {'Engineer'}, reading.organization_id, row.decided_at)
        if grant.independence_required:
            if grant.independence_check_ref is None: _needs('original_required_research_independence_check')
            independence = read(grant.independence_check_ref, EngineerResearchIndependenceView); author(independence, 'ENGINEER-A03')
            if (independence.appointment_ref != grant.appointment_ref or independence.accepted_terms_ref != grant.accepted_terms_ref
                    or independence.organization_id != reading.organization_id):
                raise ValueError('Research independence check changes appointment, terms or legal organization')
            reading.resolve(independence.requirement_ref)
            unique_refs(independence.checked_resource_refs)
            for ref in [*independence.checked_resource_refs, *independence.conflict_refs]: reading.resolve(ref)
            if independence.status != 'verified' or independence.conflict_refs:
                _needs('independent_research_scope_or_valid_amendment')
        fields = {'option_refs': 'option_refs', 'check_spec_refs': 'check_spec_refs', 'evidence_refs': 'input_evidence_refs',
                  'available_assessment_refs': 'available_assessment_refs', 'method_result_refs': 'method_result_refs'}
        for input_name, task_name in fields.items():
            unique_refs(getattr(action_input, input_name)); unique_refs(getattr(task, task_name))
            if set(getattr(action_input, input_name)) != set(getattr(task, task_name)):
                _needs('complete_original_engineering_research_' + input_name, getattr(task, task_name))
        evidence(task.input_evidence_refs)
        if limit.as_of != now: _needs('current_original_engineering_research_limit')
        evidence([limit.budget_cap.basis_ref, limit.effort_cap.basis_ref])
        cap, work_cap = decimal_fraction(limit.budget_cap.value), decimal_fraction(limit.effort_cap.value)
        if cap < 0 or work_cap < 0: raise ValueError('Research limits are negative')
        used, worked, facts = Fraction(), Fraction(), {}
        unique_refs(limit.expense_refs)
        for ref in limit.expense_refs:
            expense = read(ref, QSResearchExpenseView); fact = read(expense.cost_fact_ref, QSResearchCostFactView)
            if (expense.task_ref != task.ref or fact.task_ref != task.ref or fact.organization_id != reading.organization_id
                    or expense.amount != fact.amount or expense.effort != fact.effort or expense.status != fact.status):
                raise ValueError('Research expense changes original actual cost/work identity or state')
            evidence([fact.amount.basis_ref, fact.effort.basis_ref])
            if fact.amount.currency != limit.budget_cap.currency or fact.effort.unit != limit.effort_cap.unit:
                _unsupported('engineer-research-cost-work-conversion')
            amount, effort = decimal_fraction(fact.amount.value), decimal_fraction(fact.effort.value)
            if amount < 0 or effort < 0: raise ValueError('Actual research cost or work is negative')
            key, actual = (fact.ref.kind, fact.ref.id), (amount, effort, fact.status)
            if key in facts:
                if facts[key] != actual: _needs('current_single_engineering_research_cost_fact')
                continue
            facts[key] = actual; used += amount; worked += effort
        at_limit = task.status == 'closed' or limit.status != 'active' or used >= cap or worked >= work_cap
        if limit.deadline is not None:
            clock(limit.deadline); at_limit = at_limit or now.offset >= limit.deadline.offset
        if (check_preparation is not None or estimate_preparation is not None) and at_limit:
            reading.recheck()
            return {'kind': 'deferred', 'reason_code': 'engineer_research_check_limit_reached', 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [task.ref, limit.ref], 'earliest_time': None,
                'condition_code': 'engineer.research.check_authorized_within_limits'}}
        if task.status == 'waiting' and not at_limit:
            reading.recheck()
            return {'kind': 'deferred', 'reason_code': 'engineer_research_waiting', 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [task.ref], 'earliest_time': None, 'condition_code': 'engineer.research.ready'}}
        if original_wait_only:
            reading.recheck()
            return None
        targets = [brief.ref, *task.option_refs]
        for ref in task.option_refs:
            row = read(ref, EngineerResearchTargetView)
            if row.brief_ref != brief.ref or 'research' not in row.allowed_uses:
                raise ValueError('Engineering research candidate changes original brief or authorized use')
            assignment = read(row.author_function_ref, RoleAssignment)
            allowed = {'Architect': {'ARCHITECT-A05'}, 'Engineer': {'ENGINEER-A05'}}
            if row.author_action_id not in allowed.get(assignment.role, set()): _unsupported('engineer-research-candidate-author-action')
            author(row, row.author_action_id, {assignment.role})
        unresolved = []
        unique_refs(task.question_refs)
        for ref in task.question_refs:
            gap = read(ref, EngineerResearchGapView)
            if gap.task_ref != task.ref or gap.brief_ref != brief.ref: raise ValueError('Research gap changes original task or brief')
            unresolved.extend(questions([gap.question]))
        specs, results = {}, {}
        for ref in task.check_spec_refs:
            spec = read(ref, EngineerResearchCheckSpecView)
            if (spec.brief_ref != brief.ref or spec.target_ref not in targets or spec.discipline_code != task.discipline_code
                    or spec.function_code != task.function_code or 'research' not in spec.allowed_uses):
                raise ValueError('Research check spec changes target, brief, discipline, function or allowed use')
            reading.resolve(spec.engineering_scope_ref)
            for issue in spec.issue_refs: reading.resolve(issue)
            specs[ref.key()] = spec
        if estimate_preparation is not None:
            if task.missing_policy != 'request' or task.request_profile_ref is None:
                _needs('original_engineering_investigation_request')
            request = read(task.request_profile_ref, ArchitectResearchRequestView)
            if (request.ref != estimate_preparation.request_profile_ref or request.task_ref != task.ref
                    or request.scope != scope or request.authority_basis_refs != [grant.ref]
                    or request.purpose not in grant.allowed_purposes
                    or not set(request.input_refs) <= set(grant.allowed_input_refs)):
                raise ValueError('Research estimate changes original request, task, purpose or permitted inputs')
            if (request.estimate_ref != estimate_preparation.calculation_ref
                    or type(estimate_preparation.calculation_ref.version) is not str
                    or estimate_preparation.calculation_ref in task.method_result_refs):
                raise ValueError('Research estimate replaces original independent versioned estimate target')
            if request.work_profile_ref is None:
                _needs('sourced_original_engineering_investigation_work_profile')
            work = read(request.work_profile_ref, EngineerResearchWorkView)
            if work.task_ref != task.ref:
                raise ValueError('Research estimate borrows another task work profile')
            basis = work.estimate_basis
            if basis is None:
                _needs('sourced_original_engineering_investigation_work_estimate')
            if (basis.method_ref != ENGINEER_RESEARCH_ESTIMATE_METHOD
                    or task.discipline_code not in basis.allowed_discipline_codes
                    or task.function_code not in basis.allowed_function_codes
                    or request.purpose not in basis.allowed_purposes):
                _unsupported('engineer-investigation-work-estimate-support-domain')
            method = read(basis.method_ref, EngineerResearchMethodView)
            if ('bounded_research_estimate' not in method.purposes
                    or task.discipline_code not in method.allowed_discipline_codes
                    or task.function_code not in method.allowed_function_codes):
                _unsupported('engineer-investigation-estimate-domain')
            numeric_refs = [basis.quantity.basis_ref, basis.effort_per_unit.basis_ref,
                basis.cost_per_effort.basis_ref, basis.fixed_cost.basis_ref]
            evidence(numeric_refs)
            amount = _known(request.incremental_cost, 'original_engineering_investigation_cost')
            effort = _known(request.effort_estimate, 'supported_engineering_investigation_effort')
            evidence([amount.basis_ref, effort.basis_ref])
            if (amount.currency != limit.budget_cap.currency or amount.currency != basis.cost_per_effort.currency
                    or effort.unit != limit.effort_cap.unit or effort.unit != basis.effort_per_unit.unit):
                _unsupported('engineer-investigation-estimate-unit-currency-conversion')
            if min(decimal_fraction(amount.value), decimal_fraction(effort.value)) < 0:
                raise ValueError('Original investigation cost/work estimates are negative')
            if decimal_fraction(amount.value) > cap - used or decimal_fraction(effort.value) > work_cap - worked:
                _needs('engineering_investigation_within_original_remaining_limits')
            if request.desired_window.state == 'known':
                window = request.desired_window.value
                clock(window.start)
                if window.start.offset < now.offset:
                    _needs('future_engineering_investigation_window')
                if limit.deadline is not None and window.end.offset > limit.deadline.offset:
                    _needs('engineering_investigation_within_original_deadline')
            for refs in (request.input_refs, request.output_requirement_refs, request.dependency_refs):
                unique_refs(refs)
                for ref in refs:
                    reading.resolve(ref)
            for ref in [*request.output_requirement_refs, *request.dependency_refs]:
                if read(ref, ArchitectResearchReferenceView).task_ref != task.ref:
                    raise ValueError('Research estimate borrows another task requirements or dependencies')
            source_refs = list({ref.key(): ref for ref in [task.ref, brief.ref, grant.ref, limit.ref,
                request.ref, work.ref, method.ref, *numeric_refs, amount.basis_ref, effort.basis_ref,
                *request.input_refs, *request.output_requirement_refs, *request.dependency_refs,
                *task.evidence_refs, *grant.evidence_refs, *request.evidence_refs, *work.evidence_refs,
                *method.evidence_refs]}.values())
            original = EngineerResearchEstimateInput(work_profile_ref=work.ref, quantity=basis.quantity,
                effort_per_unit=basis.effort_per_unit, effort_quantity_unit=basis.effort_quantity_unit,
                cost_per_effort=basis.cost_per_effort, cost_effort_unit=basis.cost_effort_unit,
                fixed_cost=basis.fixed_cost, source_refs=source_refs)
            if estimate_preparation.input != original:
                raise ValueError('Research estimate preparation changes original sourced work, rates or inputs')
            reading.recheck()
            return {'kind': 'prepared', 'preparation': estimate_preparation, 'task': task, 'brief': brief,
                'grant': grant, 'request': request, 'work': work}
        if check_preparation is not None:
            mappings = task.check_result_targets
            unique_refs([row.check_spec_ref for row in mappings])
            unique_refs([row.calculation_ref for row in mappings])
            if (not {row.check_spec_ref.key() for row in mappings} <= set(specs)
                    or not {row.calculation_ref.key() for row in mappings} <= {ref.key() for ref in task.method_result_refs}):
                raise ValueError('Research check mapping leaves original task/spec/result inputs')
            selected = next((row for row in mappings if row.check_spec_ref == check_preparation.check_spec_ref), None)
            if selected is None:
                _needs('original_declared_research_check_result_target', [task.ref])
            if selected.calculation_ref != check_preparation.calculation_ref or type(selected.calculation_ref.version) is not str:
                raise ValueError('Research preparation replaces original versioned result target')
            spec = specs[selected.check_spec_ref.key()]
            method_domain(spec.method_ref)
            coverage = read(spec.engineering_scope_ref, ArchitectResearchReferenceView)
            if coverage.task_ref != task.ref:
                raise ValueError('Research preparation borrows engineering coverage from another task')
            _, basis, fact_refs, states = original_facts(spec)
            evidence(basis)
            source_refs = list({ref.key(): ref for ref in [task.ref, brief.ref, grant.ref, limit.ref,
                spec.ref, spec.target_ref, coverage.ref, *fact_refs, *basis, *spec.evidence_refs,
                *task.evidence_refs, *brief.evidence_refs, *grant.evidence_refs, *limit.evidence_refs]}.values())
            original = EngineerInterfaceInput(requested_check=spec.requested_check,
                left_code=states[0], right_code=states[1], source_refs=source_refs)
            if check_preparation.input != original:
                raise ValueError('Research preparation changes original facts, task, target or input provenance')
            reading.recheck()
            return {'kind': 'prepared', 'preparation': check_preparation, 'task': task, 'brief': brief,
                'grant': grant, 'spec': spec, 'target_ref': spec.target_ref, 'input_fact_refs': fact_refs}
        for ref in task.method_result_refs:
            wrapped = read(ref, EngineerResearchMethodProjection)
            if wrapped.check is None: _unsupported('engineer-research-check-result-schema')
            result = wrapped.check; evidence(result.evidence_refs); author(result)
            clock(result.executed_at); clock(result.available_at); current(result.effective_window)
            if result.executed_at.offset > result.available_at.offset or result.available_at.offset > now.offset:
                _needs('received_original_engineering_method_execution')
            spec = specs.get(result.check_spec_ref.key())
            if (spec is None or result.brief_ref != brief.ref or result.task_ref != task.ref
                    or result.target_ref.key() != spec.target_ref.key() or result.method_ref != spec.method_ref):
                raise ValueError('Saved engineering check changes original execution inputs, spec, task or method')
            if result.check_spec_ref.key() in results: raise ValueError('Research repeats an original check execution across versions')
            results[result.check_spec_ref.key()] = result
        items = {ref.key(): [] for ref in targets}; uncovered = {ref.key(): [] for ref in targets}
        for key, spec in specs.items():
            saved = results.get(key); result_value, missing, basis = None, [], []
            evidence_status = 'missing'
            if saved is not None and saved.status == 'ok':
                method_domain(saved.method_ref)
                original, basis, expected_refs, code_states = original_facts(spec)
                if saved.input_fact_refs != expected_refs: raise ValueError('Saved check changes exact original input facts')
                replay = check_interface(EngineerInterfaceInput(requested_check=spec.requested_check,
                    left_code=code_states[0], right_code=code_states[1], source_refs=expected_refs))
                if saved.result is None or saved.result != replay:
                    raise ValueError('Saved check output differs from original declared method and facts')
                result_value, missing = replay.result, replay.missing_field_paths
                records = evidence(basis)
                if any(row is not None and row.basis != 'observed' for row in original) or any(row.basis_kind != 'observed' for row in records):
                    evidence_status = 'assumption_based'
                elif all(row is not None and row.value.state == 'known' for row in original): evidence_status = 'sufficient'
            else:
                missing = ['method_execution'] if saved is None else ['method_execution:' + saved.status]
                if saved is not None and saved.result is not None: raise ValueError('Failed/unsupported execution cannot have substantive findings')
            if result_value in {None, 'undetermined', 'out_of_scope'}:
                uncovered[spec.target_ref.key()].append(spec.engineering_scope_ref)
                if spec.gap_question_ref is not None:
                    gap = read(spec.gap_question_ref, EngineerResearchGapView)
                    if gap.task_ref != task.ref or gap.brief_ref != brief.ref: raise ValueError('Check gap changes original research task')
                    unresolved.extend(questions([gap.question]))
            basis = list({ref.key(): ref for ref in basis}.values())
            items[spec.target_ref.key()].append({'check_spec_ref': spec.ref, 'evidence_refs': basis,
                'evidence_status': evidence_status, 'method_result_ref': None if saved is None else saved.ref,
                'result': result_value, 'missing_field_paths': missing, 'issue_refs': spec.issue_refs})
        assessments = []
        for target in targets:
            target_items = items[target.key()]
            if not target_items: continue
            findings = [row['result'] for row in target_items]
            opinion = ('revise' if 'conflict' in findings else 'investigate' if any(r in {None, 'undetermined'} for r in findings)
                       else 'reserve_interpretation' if 'out_of_scope' in findings or any(row['evidence_status'] != 'sufficient' for row in target_items)
                       else 'support_limited_option')
            assessments.append({'target_ref': target, 'task_ref': task.ref, 'check_items': target_items,
                'opinion': opinion, 'requested_use': 'research',
                'uncovered_scope_refs': list({ref.key(): ref for ref in uncovered[target.key()]}.values()),
                'explanation': 'Original saved execution findings; conflicts and unknowns coexist; interface-code rule implies no real engineering safety or whole-project approval'})
        for ref in task.available_assessment_refs:
            saved = read(ref, EngineerResearchAssessmentView); author(saved)
            assessment = saved.assessment
            if assessment.target_ref not in targets or assessment.task_ref != task.ref or assessment.requested_use != 'research':
                raise ValueError('Reusable assessment changes original target, task or use')
            # Only reuse the exact reconstructed assessment; cannot silently inherit another author verdict.
            rebuilt = next((row for row in assessments if row['target_ref'] == assessment.target_ref), None)
            normalized = None if rebuilt is None else EngineerResearchAssessment.model_validate(rebuilt)
            if normalized is None or assessment.model_dump(exclude={'explanation'}) != normalized.model_dump(exclude={'explanation'}):
                _needs('reusable_assessment_exact_original_check_and_interpretation', [ref])
            assessments[assessments.index(rebuilt)] = {**rebuilt, 'explanation': assessment.explanation}
        if at_limit: return completed('deliver_at_limit', assessments=assessments, remaining_questions=unresolved)
        if unresolved and task.missing_policy == 'request' and task.request_profile_ref is not None:
            request = read(task.request_profile_ref, ArchitectResearchRequestView)
            if (request.task_ref != task.ref or request.scope != scope or request.authority_basis_refs != [grant.ref]
                    or request.purpose not in grant.allowed_purposes or not set(request.input_refs) <= set(grant.allowed_input_refs)):
                raise ValueError('Engineering investigation changes original task, purpose, authority or permitted inputs')
            if request.estimate_ref is None: _needs('saved_original_engineering_investigation_estimate')
            wrapped = read(request.estimate_ref, EngineerResearchMethodProjection)
            estimate = wrapped.estimate
            if estimate is None: _unsupported('engineer-investigation-estimate-schema')
            author(estimate)
            clock(estimate.executed_at); clock(estimate.available_at); current(estimate.effective_window)
            if estimate.executed_at.offset > estimate.available_at.offset or estimate.available_at.offset > now.offset:
                _needs('received_original_engineering_investigation_estimate')
            if (estimate.task_ref != task.ref or estimate.request_profile_ref != request.ref
                    or set(estimate.input_refs) != set(request.input_refs) or estimate.work_profile_ref != request.work_profile_ref
                    or estimate.incremental_cost != request.incremental_cost or estimate.effort_estimate != request.effort_estimate):
                raise ValueError('Investigation estimate changes original inputs or estimated work/cost')
            if estimate.status == 'failed': return technical('engineering_investigation_estimate_failed')
            if estimate.status != 'ok': _unsupported('engineer-investigation-estimate-method')
            method = read(estimate.method_ref, EngineerResearchMethodView)
            if ('bounded_research_estimate' not in method.purposes or task.discipline_code not in method.allowed_discipline_codes
                    or task.function_code not in method.allowed_function_codes): _unsupported('engineer-investigation-estimate-domain')
            if estimate.method_ref == ENGINEER_RESEARCH_ESTIMATE_METHOD:
                if request.work_profile_ref is None:
                    _needs('sourced_original_engineering_investigation_work_profile')
                work = read(request.work_profile_ref, EngineerResearchWorkView)
                if (work.task_ref != task.ref or estimate.author_authority_ref != task.authority_ref
                        or estimate.author_actor_id != context.actor_id or estimate.author_function_ref != context.function_ref):
                    raise ValueError('Local research estimate changes original work task or producing author')
                basis = work.estimate_basis
                if basis is None:
                    _needs('sourced_original_engineering_investigation_work_estimate')
                if (basis.method_ref != ENGINEER_RESEARCH_ESTIMATE_METHOD
                        or task.discipline_code not in basis.allowed_discipline_codes
                        or task.function_code not in basis.allowed_function_codes
                        or request.purpose not in basis.allowed_purposes):
                    _unsupported('engineer-investigation-work-estimate-support-domain')
                numeric_refs = [basis.quantity.basis_ref, basis.effort_per_unit.basis_ref,
                    basis.cost_per_effort.basis_ref, basis.fixed_cost.basis_ref]
                evidence(numeric_refs)
                local_input = EngineerResearchEstimateInput(work_profile_ref=work.ref, quantity=basis.quantity,
                    effort_per_unit=basis.effort_per_unit, effort_quantity_unit=basis.effort_quantity_unit,
                    cost_per_effort=basis.cost_per_effort, cost_effort_unit=basis.cost_effort_unit,
                    fixed_cost=basis.fixed_cost, source_refs=list({ref.key(): ref for ref in [work.ref, *numeric_refs]}.values()))
                expected = estimate_declared_research(local_input)
                cost = _known(estimate.incremental_cost, 'original_engineering_investigation_cost')
                effort = _known(estimate.effort_estimate, 'supported_engineering_investigation_effort')
                if cost != expected.estimated_cost or effort != expected.effort:
                    raise ValueError('Saved local research estimate differs from original work quantity, rates or basis')
            amount = _known(request.incremental_cost, 'original_engineering_investigation_cost'); evidence([amount.basis_ref])
            if amount.currency != limit.budget_cap.currency: _unsupported('engineer-investigation-currency-conversion')
            if decimal_fraction(amount.value) < 0: raise ValueError('Incremental research cost is negative')
            if decimal_fraction(amount.value) > cap - used:
                return completed('no_recommendation', assessments=assessments, reason='Investigation exceeds original remaining budget')
            if request.effort_estimate.state == 'known':
                effort = request.effort_estimate.value; evidence([effort.basis_ref])
                if effort.unit != limit.effort_cap.unit: _unsupported('engineer-investigation-effort-conversion')
                if decimal_fraction(effort.value) < 0: raise ValueError('Incremental work is negative')
                if decimal_fraction(effort.value) > work_cap - worked:
                    return completed('no_recommendation', assessments=assessments, reason='Investigation exceeds original remaining effort allowance')
            elif request.work_profile_ref is not None: _needs('supported_engineering_investigation_effort')
            if request.desired_window.state == 'known':
                window = request.desired_window.value; clock(window.start)
                if window.start.offset < now.offset: _needs('future_engineering_investigation_window')
                if limit.deadline is not None and window.end.offset > limit.deadline.offset:
                    return completed('no_recommendation', assessments=assessments, reason='Investigation exceeds original research deadline')
            for refs in (request.input_refs, request.output_requirement_refs, request.dependency_refs):
                unique_refs(refs)
                for ref in refs: reading.resolve(ref)
            if request.work_profile_ref is not None: reading.resolve(request.work_profile_ref)
            payload = request.model_dump(exclude={'ref', 'task_ref', 'available_at', 'effective_window',
                                                  'evidence_refs', 'incremental_cost', 'estimate_ref'})
            payload['questions'] = unresolved
            return completed('recommend_investigation', questions=unresolved, request=payload)
        if task.comparison_scope_ref is not None and assessments:
            comparison = read(task.comparison_scope_ref, EngineerResearchScopeView)
            if (comparison.brief_ref != brief.ref or comparison.task_ref != task.ref
                    or {ref.key() for ref in comparison.target_refs} != {row['target_ref'].key() for row in assessments}
                    or set(comparison.check_spec_refs) != set(task.check_spec_refs)):
                raise ValueError('Engineering comparison changes original covered targets or checks')
            return completed('compare', assessments=assessments, comparable_scope_ref=comparison.ref)
        return completed('no_recommendation', assessments=assessments,
                         reason='No registered covered comparison is available; finite findings and missing/failed checks are preserved')
    except ObservationGap as gap:
        reading.recheck(); return gap.result
