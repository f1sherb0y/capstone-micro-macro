"""ARCHITECT-A05 finite drafts and scoped comparisons; no approval effects."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, Measured
from src.actions.contracts.architect_design_objects import (
    ArchitectDesignTaskView, ArchitectDesignProfileView, ArchitectDesignVariableView, ArchitectDesignCoverageView,
    ArchitectDesignLimitView, ArchitectDesignAreaPreparation, ArchitectDesignAreaResultView, ArchitectDesignReferenceView,
    ArchitectResearchOptionView, ArchitectResearchAssessmentView, ArchitectResearchScopeView,
    ArchitectResearchMethodView, ArchitectResearchGapView, QSResearchCostPlanView,
    QSCostBriefView, ArchitectAppointmentView, ArchitectPlanningWorkFactView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import ServiceResponseRequirementView
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.architect_area import AREA_METHOD, calculate_area_schedule
from src.methods.architect_research import ARCHITECT_COMPARE_METHOD, ArchitectComparisonInput
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def compile_design(context, action_input, reading):
    return _compile_design(context, action_input, reading)


def recheck_original_architect_design_candidate_limit(context, action_input, reading):
    """Reproduce the original finite-candidate limit before comparison or production."""
    result = _compile_design(context, action_input, reading, original_limit_wait_only=True)
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'original_design_engagement_candidate_or_revision_limit_reached'):
        raise ValueError('Original design sources do not reproduce the actual candidate/revision limit wait')
    return result


def recheck_original_architect_design_work_limit(context, action_input, reading):
    """Reproduce original actual effort/cost limits without comparison, area work or production."""
    result = _compile_design(context, action_input, reading, original_work_wait_only=True)
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'original_design_engagement_work_limit_reached'):
        raise ValueError('Original design sources do not reproduce the actual work/expense limit wait')
    return result


def recheck_original_architect_design_submission(context, action_input, reading):
    """Reproduce original submission query before comparing or producing another draft."""
    result = _compile_design(context, action_input, reading, original_submission_wait_only=True)
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'query_original_design_submission_before_duplicate_production'):
        raise ValueError('Original design sources do not reproduce the actual prior submission query')
    return result


def prepare_architect_area_input(context, action_input, reading, preparation):
    """Validate sourced draft input without executing or consuming its future report.

    The caller supplies an authorized reading directly. Ordinary design assembly
    still requires saved method results; this helper does not relax that path.
    """
    preparation = ArchitectDesignAreaPreparation.model_validate(preparation)
    return _compile_design(context, action_input, reading, area_preparation=preparation)


def _compile_design(context, action_input, reading, *, area_preparation=None, original_limit_wait_only=False,
        original_work_wait_only=False, original_submission_wait_only=False):
    now, organization = context.business_time, reading.organization_id
    sources = {}

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('architect-design-clock-alignment')

    def evidence(refs, historical=False):
        keys(refs)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('architect-design-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_original_design_evidence', [ref])

    def read(ref, schema, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'architect-design-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise ValueError('Design input leaves original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_design_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('current_original_design_input', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical); sources[ref.key()] = ref
        return row

    def authorize(ref, actor, function_ref, action, at, own=False):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        expected_role = 'QS' if action == 'QS-A04' else 'Engineer' if action.startswith('ENGINEER-') else 'Architect'
        if (grant.actor_id != actor or grant.function_ref != function_ref or action not in grant.action_ids
                or function.role != expected_role or (own and grant.organization_id != organization)
                or not any(scope_covers(scope, action_input.scope) for scope in grant.scopes)):
            raise ValueError('Design input lacks independent original author/action/scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('valid_original_design_author_authority', [ref])
        evidence([*grant.basis_refs, *function.basis_refs], at != now)

    def authored(row, action):
        authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref, action, row.available_at)

    def questions(rows):
        output = []
        for question in rows:
            if question.scope != action_input.scope or not question.target_refs or not question.recipient_ids:
                raise ValueError('Design question changes original scope or lacks specific targets/recipients')
            keys(question.target_refs); evidence(question.evidence_refs)
            response = read(question.response_requirement_ref, ServiceResponseRequirementView)
            if not set(question.recipient_ids) <= set(response.recipient_ids): raise ValueError('Design question exceeds original response recipients')
            for ref in question.target_refs:
                gap = read(ref, ArchitectResearchGapView)
                if gap.brief_ref.key() != brief.ref.key() or gap.question != question:
                    raise ValueError('Design question changes its original registered question')
            output.append(question.model_dump(mode='python'))
        return output

    def validate_area_input(data, area_refs, floor_refs, draft, group_map):
        if data.unit != 'm²': _unsupported('architect-design-modeled-area-unit')
        variables = {row.variable_ref.key(): row.value for row in draft.variables}
        group_keys = {row.local_key for row in data.groups}
        if (len(group_keys) != len(data.groups)
                or group_keys != {key for key, row in group_map.items() if row.floor_keys}):
            raise ValueError('Area input omits or repeats original modeled floor coverage')
        if set(area_refs) != group_keys or set(floor_refs) != group_keys:
            raise ValueError('Area variable mappings must exactly cover the original floor groups')
        evidence([data.total_basis_ref])
        for area_group in data.groups:
            coverage = group_map[area_group.local_key]
            if area_group.floor_keys != coverage.floor_keys:
                raise ValueError('Area input changes original draft floor coverage')
            area_ref, floor_ref = area_refs[area_group.local_key], floor_refs[area_group.local_key]
            if area_ref.key() not in variables or variables[area_ref.key()] != area_group.area_per_floor:
                raise ValueError('Area input changes original draft per-floor area')
            evidence(area_group.missing_evidence_refs)
            if isinstance(area_group.area_per_floor, Known): evidence([area_group.area_per_floor.value.basis_ref])
            count = variables.get(floor_ref.key())
            if (not isinstance(count, Known) or not isinstance(count.value, Measured)
                    or decimal_fraction(count.value.value) != len(area_group.floor_keys)):
                raise ValueError('Area input changes original declared floor count')
        input_keys = keys(data.source_refs)
        if not {task.ref.key(), profile.ref.key()} <= input_keys:
            raise ValueError('Area method loses its original task/profile input versions')
        if area_preparation is not None and input_keys.intersection(keys(task.method_result_refs)):
            raise ValueError('Area preparation cannot depend on its future method reports')
        for ref in data.source_refs: reading.resolve(ref)

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'scope': action_input.scope,
            'note': 'Original scoped architectural work; approvals and formal effects require separate authorized submission', **fields}}

    def deferred(code, refs):
        reading.recheck(); return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
            'trigger': 'dependency_change', 'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    try:
        if action_input.scope != context.scope: raise ValueError('Design action changes original authorized scope')
        task = read(action_input.task_ref, ArchitectDesignTaskView)
        brief = read(action_input.brief_ref, QSCostBriefView)
        profile = read(action_input.design_profile_ref, ArchitectDesignProfileView)
        if area_preparation is not None:
            if task.choice != 'produce':
                raise ValueError('Area preparation requires original produce work; comparisons are separate')
            if area_preparation.draft_index >= len(task.drafts):
                raise ValueError('Area preparation selects a draft outside the original task')
            if AREA_METHOD.key() not in keys(profile.permitted_method_refs):
                _unsupported('architect-design-area-method-domain')
            if any(ref.key() in keys(task.method_result_refs) for ref in task.required_input_refs):
                raise ValueError('Area preparation cannot require its future method reports as inputs')
        if (task.organization_id != organization or not same(task.brief_ref, brief.ref)
                or not same(task.design_profile_ref, profile.ref)): raise ValueError('Design task changes original organization/brief/catalog')
        authorize(task.authority_ref, context.actor_id, context.function_ref, 'ARCHITECT-A05', now, True)
        if (original_limit_wait_only or original_work_wait_only or original_submission_wait_only) and task.choice != 'produce':
            reading.recheck()
            return None
        if task.status != 'authorized': return deferred('original_design_task_not_authorized_for_work', [task.ref])
        appointment = read(task.appointment_ref, ArchitectAppointmentView)
        if appointment.provider_organization_id != organization or appointment.status != 'active': _needs('original_active_design_appointment')
        if task.requested_use not in brief.allowed_uses or task.requested_use not in profile.allowed_uses:
            raise ValueError('Design work changes original authorized deliverable use')
        for name in ('available_option_refs', 'professional_refs', 'cost_refs', 'method_result_refs'):
            if keys(getattr(task, name)) != keys(getattr(action_input, name)): _needs(f'all_original_design_{name}')
        evidence(action_input.basis_refs)
        for ref in task.required_input_refs: reading.resolve(ref)
        if task.choice == 'request_inputs':
            gaps = [read(ref, ArchitectResearchGapView) for ref in task.question_refs]
            result = questions([gap.question for gap in gaps])
            if not result: _needs('specific_original_design_input_questions')
            return completed('request_inputs', questions=result)
        if task.choice == 'compare':
            if action_input.comparison_scope_ref is None: _needs('original_comparison_scope_for_saved_design_options')
            comparison_scope = read(action_input.comparison_scope_ref, ArchitectResearchScopeView)
            if not same(comparison_scope.brief_ref, brief.ref) or not same(comparison_scope.task_ref, task.ref):
                raise ValueError('Design comparison changes original brief/task/scope')
            method = None
            if action_input.comparison_method_ref is not None:
                method = read(action_input.comparison_method_ref, ArchitectResearchMethodView); authored(method, 'ARCHITECT-A05')
                if (not same(method.task_ref, task.ref) or not same(method.comparison_scope_ref, comparison_scope.ref)
                        or method.method_ref.key() != ARCHITECT_COMPARE_METHOD.key()): _unsupported('architect-design-original-comparison-method')
                if task.requested_use not in method.allowed_uses: _unsupported('architect-design-comparison-method-use')
            unresolved, values, limitations = [], [], []
            assessments = [read(ref, ArchitectResearchAssessmentView) for ref in task.professional_refs]
            costs = [read(ref, QSResearchCostPlanView) for ref in task.cost_refs]
            for assessment in assessments: authored(assessment, assessment.author_action_id)
            for cost in costs: authored(cost, 'QS-A04')
            options = [read(ref, ArchitectResearchOptionView) for ref in task.available_option_refs]
            def dimensions(rows):
                data = {row.code: row.value for row in rows}
                return len(data) == len(rows) and all(row.value.state == 'known' and data.get(row.code) == row.value for row in comparison_scope.required_dimensions)
            def metric(rows, code):
                found = [row.value for row in rows if row.code == code]
                if len(found) != 1 or not isinstance(found[0], Known): return None
                evidence([found[0].value.basis_ref]); return found[0].value
            for option in options:
                authored(option, 'ARCHITECT-A05')
                if not same(option.brief_ref, brief.ref): raise ValueError('Design comparison borrows another brief option')
                unresolved.extend(questions(option.unresolved_questions))
                if (option.compilation_status != 'completed' or not dimensions(option.dimensions)
                        or option.object_type != profile.object_type or option.region_id != profile.region_id
                        or task.requested_use not in option.allowed_uses):
                    limitations.append('Original option compilation or comparison dimensions incomplete')
                professional = [row for row in assessments if same(row.option_ref, option.ref)]
                covered = set()
                for row in professional:
                    if not same(row.brief_ref, brief.ref) or not same(row.comparison_scope_ref, comparison_scope.ref):
                        raise ValueError('Professional comparison changes original option version or comparison scope')
                    if row.status == 'ok' and row.finding == 'compatible' and task.requested_use in row.allowed_uses: covered.update(row.coverage_keys)
                    else: limitations.append('Original professional issue remains unresolved')
                if not set(comparison_scope.required_professional_coverage_keys) <= covered: limitations.append('Required professional coverage incomplete')
                valid_costs = []
                for row in costs:
                    if not same(row.draft.option_ref, option.ref): continue
                    if not same(row.brief_ref, brief.ref): raise ValueError('Cost comparison changes original brief')
                    total = row.draft.complete_total
                    if (row.status != 'submitted' or total is None or row.draft.missing_items or not dimensions(row.comparison_dimensions)
                            or row.draft.calculation_ref is None or not row.draft.lines): continue
                    if any(line.amount.state != 'known' or line.amount.value.currency != total.currency or line.calculation_ref != row.draft.calculation_ref for line in row.draft.lines): continue
                    if sum((decimal_fraction(line.amount.value.value) for line in row.draft.lines), Fraction()) != decimal_fraction(total.value):
                        raise ValueError('Original scoped cost total differs from calculated line amounts')
                    valid_costs.append(row)
                if comparison_scope.require_costs and len(valid_costs) != 1: limitations.append('Complete scoped costs missing or ambiguous')
                selected = []
                if method is not None:
                    for criterion in method.criteria:
                        value = None
                        if criterion.source == 'option': value = metric(option.metrics, criterion.code)
                        elif criterion.source == 'professional':
                            available = [metric(row.metrics, criterion.code) for row in professional if row.status == 'ok']
                            available = [row for row in available if row is not None]
                            if len(available) == 1: value = available[0]
                        elif criterion.code == 'complete_total' and len(valid_costs) == 1:
                            total = valid_costs[0].draft.complete_total
                            value = Measured(value=total.value, unit=total.currency, basis_ref=total.basis_ref)
                        if value is None or value.unit != criterion.unit: limitations.append('Selected comparison metric unknown or incompatible')
                        else: evidence([value.basis_ref]); selected.append(value)
                values.append({'option_ref': option.ref, 'values': selected})
            if any(not any(same(row.option_ref, option.ref) for option in options) for row in assessments):
                raise ValueError('Professional input includes another option version')
            if any(not any(same(row.draft.option_ref, option.ref) for option in options) for row in costs):
                raise ValueError('Cost input includes another option version')
            recommended = []
            if method is not None and options and not unresolved and not limitations:
                result = reading.calculate(ARCHITECT_COMPARE_METHOD, ArchitectComparisonInput(criteria=method.criteria, options=values, source_refs=list(sources.values())))
                if result.kind != 'ok':
                    if result.kind == 'invalid_input': _unsupported('architect-design-comparison-domain')
                    raw = result.model_dump(mode='python')
                    if result.kind == 'needs_information': raw['requested_refs'] = []
                    raise ObservationGap(raw)
                recommended = result.value.recommended_option_refs
            return completed('compare', comparison={'option_refs': task.available_option_refs, 'comparable_scope_ref': comparison_scope.ref,
                'professional_refs': task.professional_refs, 'cost_refs': task.cost_refs, 'recommended_option_refs': recommended,
                'unresolved_questions': unresolved, 'comparison_method_ref': action_input.comparison_method_ref,
                'reason': '; '.join(sorted(set(limitations))) or ('Original declared comparable metrics' if recommended else 'No supported recommendation from the available inputs')})
        if not _known(profile.supported, 'original_design_template_support'): _unsupported('architect-design-template-object-or-height-domain')
        limit = read(task.design_limit_ref, ArchitectDesignLimitView)
        if not same(limit.appointment_ref, appointment.ref) or limit.as_of != now or limit.coverage != 'complete':
            _needs('complete_current_engagement_wide_design_limits')
        if limit.prior_submission_ref is not None: return deferred('query_original_design_submission_before_duplicate_production', [limit.prior_submission_ref])
        if original_submission_wait_only:
            reading.recheck()
            return None
        keys(limit.option_refs); keys(limit.work_fact_refs)
        if limit.version_branch_count < len(limit.option_refs): raise ValueError('Design version history omits existing candidate branches')
        new_candidates = sum(draft.relation != 'revision' for draft in task.drafts)
        revision = int(any(draft.relation == 'revision' for draft in task.drafts))
        if (len(limit.option_refs) + new_candidates > limit.maximum_candidates or limit.version_branch_count + len(task.drafts) > limit.maximum_versions_branches
                or limit.revision_count + revision > limit.maximum_revisions):
            return deferred('original_design_engagement_candidate_or_revision_limit_reached', [limit.ref, task.ref])
        if original_limit_wait_only:
            reading.recheck()
            return None
        if not task.drafts: _needs('original_nonempty_authorized_design_drafts')
        invested, cost, current_effort, investments = Fraction(), Fraction(), Fraction(), set()
        if not keys(task.work_fact_refs) <= keys(limit.work_fact_refs): _needs('current_design_work_within_complete_original_engagement_history')
        for ref in limit.work_fact_refs:
            fact = read(ref, ArchitectPlanningWorkFactView, True)
            if fact.organization_id != organization or fact.investment_key in investments: raise ValueError('Design work repeats an investment or borrows another organization')
            investments.add(fact.investment_key); clock(fact.window.start)
            if fact.status != 'committed' or fact.window.end.offset > min(now.offset, fact.available_at.offset): _needs('confirmed_actual_design_work_before_production')
            if fact.effort.unit != limit.maximum_effort.unit or fact.internal_cost.currency != limit.maximum_cost.currency: _unsupported('architect-design-effort-cost-conversion')
            effort, amount = decimal_fraction(fact.effort.value), decimal_fraction(fact.internal_cost.value)
            if effort < 0 or amount < 0: raise ValueError('Actual design work/cost cannot be negative')
            evidence([fact.effort.basis_ref, fact.internal_cost.basis_ref], True); invested += effort; cost += amount
            if ref.key() in keys(task.work_fact_refs):
                if not same(fact.task_ref, task.ref): raise ValueError('Design draft borrows another task investment')
                current_effort += effort
        evidence([task.required_effort.basis_ref, limit.maximum_effort.basis_ref, limit.maximum_cost.basis_ref])
        if decimal_fraction(task.required_effort.value) <= 0: raise ValueError('Design compilation requires positive original workload')
        if task.required_effort.unit != limit.maximum_effort.unit or current_effort < decimal_fraction(task.required_effort.value):
            _needs('actual_work_investment_for_current_design_drafts')
        if invested > decimal_fraction(limit.maximum_effort.value) or cost > decimal_fraction(limit.maximum_cost.value):
            return deferred('original_design_engagement_work_limit_reached', [limit.ref])
        if original_work_wait_only:
            reading.recheck()
            return None
        results = [] if area_preparation is not None else [read(ref, ArchitectDesignAreaResultView) for ref in task.method_result_refs]
        used_results, output = set(), []
        draft_contents = set()
        for index, draft in enumerate(task.drafts):
            content = draft.model_dump_json()
            if content in draft_contents: raise ValueError('Design compilation repeats the same candidate draft')
            draft_contents.add(content)
            if (not same(draft.brief_ref, brief.ref) or not same(draft.design_profile_ref, profile.ref) or draft.scope != action_input.scope
                    or not keys(draft.basis_refs) <= keys(action_input.basis_refs)):
                raise ValueError('Design draft changes original brief/catalog/scope/basis')
            if draft.relation == 'original':
                if draft.parent_option_ref is not None: raise ValueError('Original design cannot borrow an undeclared parent')
            else:
                if draft.parent_option_ref is None or action_input.prior_option_ref is None or not same(draft.parent_option_ref, action_input.prior_option_ref):
                    raise ValueError('Revision/alternative must retain the original input parent version')
                parent = read(draft.parent_option_ref, ArchitectResearchOptionView); authored(parent, 'ARCHITECT-A05')
                if not same(parent.brief_ref, brief.ref): raise ValueError('Design revision changes original brief')
            variable_keys = keys([row.variable_ref for row in draft.variables])
            if not keys(profile.required_variable_refs) <= variable_keys or not variable_keys <= keys(profile.variable_refs):
                raise ValueError('Design draft omits required or invents undeclared variables')
            selected_refs = set()
            for row in draft.variables:
                catalog = read(row.variable_ref, ArchitectDesignVariableView)
                if not same(catalog.design_profile_ref, profile.ref): raise ValueError('Design variable belongs to another catalog')
                evidence(row.source_refs)
                if row.value.state == 'unknown':
                    if not catalog.allow_unknown: _needs('original_required_design_variable', row.value.missing_refs)
                    continue
                if not isinstance(row.value, Known): _unsupported('architect-design-variable-value-state')
                if catalog.value_kind == 'measured':
                    value = row.value.value
                    if not isinstance(value, Measured) or value.unit != catalog.unit: _unsupported('architect-design-variable-type-or-unit')
                    if value.basis_ref.key() not in keys(row.source_refs): raise ValueError('Design variable loses its original numerical basis')
                    number = decimal_fraction(value.value)
                    if catalog.minimum is None or catalog.maximum is None or catalog.step is None: _needs('original_numeric_design_catalog_bounds_and_precision')
                    for bound in (catalog.minimum, catalog.maximum, catalog.step):
                        if bound.unit != value.unit: _unsupported('architect-design-bound-unit')
                        evidence([bound.basis_ref])
                    low, high, step = (decimal_fraction(bound.value) for bound in (catalog.minimum, catalog.maximum, catalog.step))
                    if step <= 0 or low > high or not low <= number <= high or ((number - low) / step).denominator != 1:
                        raise ValueError('Design number leaves original finite range or precision')
                else:
                    value = row.value.value
                    if not hasattr(value, 'kind') or value.kind != 'CatalogOption' or value.key() not in keys(catalog.catalog_option_refs):
                        raise ValueError('Design selection invents an option outside the original finite catalog')
                    selected = read(value, ArchitectDesignReferenceView)
                    if not same(selected.design_profile_ref, profile.ref): raise ValueError('Design selection changes its original catalog')
                    selected_refs.add(value.key())
            coverage_keys = set(); group_map = {}
            for group in draft.component_groups:
                coverage = read(group.coverage_ref, ArchitectDesignCoverageView)
                if (not scope_covers(action_input.scope, group.scope) or not same(coverage.design_profile_ref, profile.ref)
                        or group.coverage_ref.key() not in keys(profile.coverage_refs) or group.function_ref.key() not in keys(coverage.function_refs)):
                    raise ValueError('Design component changes original scope/coverage/function catalog')
                if len(set(coverage.physical_keys)) != len(coverage.physical_keys) or coverage_keys.intersection(coverage.physical_keys):
                    raise ValueError('Design component groups overlap original physical coverage')
                coverage_keys.update(coverage.physical_keys); group_map[coverage.ref.id] = coverage
                selected_refs.add(group.function_ref.key())
                function = read(group.function_ref, ArchitectDesignReferenceView)
                if not same(function.design_profile_ref, profile.ref): raise ValueError('Design function changes original catalog')
                if isinstance(group.system_option, Known):
                    if group.system_option.value.key() not in keys(coverage.system_option_refs): raise ValueError('Design system leaves original coverage catalog')
                    system = read(group.system_option.value, ArchitectDesignReferenceView)
                    if not same(system.design_profile_ref, profile.ref): raise ValueError('Design system changes original catalog')
                    selected_refs.add(group.system_option.value.key())
                elif group.system_option.state != 'unknown': _unsupported('architect-design-system-value-state')
                if not keys(group.interface_refs) <= keys(coverage.interface_refs): raise ValueError('Design group invents an undeclared interface')
                for ref in group.interface_refs:
                    interface = read(ref, ArchitectDesignReferenceView)
                    if not same(interface.design_profile_ref, profile.ref): raise ValueError('Design interface changes original catalog')
                    selected_refs.add(ref.key())
            if any(left.key() in selected_refs and right.key() in selected_refs for left, right in profile.incompatible_pairs):
                raise ValueError('Design combines original catalog options declared incompatible')
            if not keys(draft.method_result_refs) <= keys(task.method_result_refs): raise ValueError('Design draft invents an unexecuted method result')
            if area_preparation is not None:
                targets = keys(draft.method_result_refs)
                if len(targets) > 1 or (profile.required_area_method and not targets):
                    _needs('single_predeclared_original_area_schedule_target_per_draft')
                if used_results.intersection(targets):
                    raise ValueError('Area preparation repeats a result target across original drafts')
                if index == area_preparation.draft_index:
                    if targets != {area_preparation.calculation_ref.key()}:
                        raise ValueError('Area preparation changes the original draft result target')
                    validate_area_input(area_preparation.input, area_preparation.area_variable_refs,
                        area_preparation.floor_count_variable_refs, draft, group_map)
                used_results.update(targets)
                questions(draft.unresolved_questions)
                continue
            area_results = [row for row in results if row.ref.key() in keys(draft.method_result_refs)]
            if profile.required_area_method and not area_results: _needs('original_executed_area_schedule_for_draft')
            if len(area_results) > 1: _needs('single_complete_original_area_schedule_per_draft')
            for result in area_results:
                authored(result, 'ARCHITECT-A05'); clock(result.executed_at)
                if (not same(result.task_ref, task.ref) or not same(result.design_profile_ref, profile.ref) or result.draft_index != index
                        or result.executed_at.offset > min(now.offset, result.available_at.offset)):
                    raise ValueError('Area method result changes original task/draft/version or executed time')
                if result.status == 'unsupported' or result.method_ref.key() != AREA_METHOD.key() or result.method_ref.key() not in keys(profile.permitted_method_refs):
                    _unsupported('architect-design-area-method-domain')
                if result.status != 'ok': _needs('original_successful_design_area_method')
                validate_area_input(result.input, result.area_variable_refs, result.floor_count_variable_refs, draft, group_map)
                if calculate_area_schedule(result.input) != result.report: raise ValueError('Saved area report differs from original deterministic arithmetic')
                used_results.add(result.ref.key())
            questions(draft.unresolved_questions)
            output.append(draft.model_dump(mode='python'))
        if used_results != keys(task.method_result_refs): raise ValueError('Design input includes a result outside the produced drafts')
        if area_preparation is not None:
            reading.recheck()
            return {'kind': 'prepared', 'preparation': area_preparation, 'task': task, 'profile': profile,
                'source_refs': list(sources.values())}
        return completed('produce', options=output)
    except ObservationGap as gap:
        reading.recheck(); return gap.result
