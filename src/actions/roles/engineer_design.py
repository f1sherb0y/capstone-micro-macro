"""ENGINEER-A05 scoped finite professional drafts, saved calculations and limits."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, Measured
from src.actions.contracts.engineer_design_objects import (
    EngineerDesignTaskView, EngineerDesignProfileView, EngineerParameterCatalogView,
    EngineerValidatedParameterView, EngineerDesignMethodProjection, EngineerParameterResultView,
    EngineerDesignMethodView, EngineerDesignReferenceView, EngineerResearchCheckSpecView,
    EngineerResearchFactView, EngineerResearchGapView, EngineerResearchTargetView,
    EngineerAppointmentView, EngineerServiceTermsView, EngineerPlanningWorkFactView,
    ArchitectDesignLimitView, QSCostBriefView,
    EngineerDesignParameterPreparation, EngineerDesignCheckPreparation,
)
from src.actions.contracts.architect_appointment_objects import service_terms_digest
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import ServiceResponseRequirementView
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.engineer_parameters import PARAMETER_METHOD, EngineerParameterInput, validate_parameter
from src.methods.engineer_checks import ENGINEER_INTERFACE_METHOD, EngineerInterfaceInput, check_interface
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def compile_professional_design(context, action_input, reading, *, action_id='ENGINEER-A05'):
    return _compile_professional_design(context, action_input, reading, action_id=action_id)


def recheck_original_engineer_design_candidate_limit(context, action_input, reading):
    """Reproduce the original candidate/revision gate without producing another design."""
    result = _compile_professional_design(context, action_input, reading,
        action_id='ENGINEER-A05', original_candidate_wait_only=True)
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'original_professional_candidate_revision_limit_reached'):
        raise ValueError('Original professional sources do not reproduce the candidate/revision limit wait')
    return result


def recheck_original_engineer_design_work_limit(context, action_input, reading):
    """Reproduce actual historical effort/cost limits without producing another design."""
    result = _compile_professional_design(context, action_input, reading,
        action_id='ENGINEER-A05', original_work_wait_only=True)
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'original_professional_work_limit_reached'):
        raise ValueError('Original professional sources do not reproduce the actual work/cost limit wait')
    return result


def recheck_original_engineer_design_submission(context, action_input, reading):
    """Reproduce the original registration query without producing another design."""
    result = _compile_professional_design(context, action_input, reading,
        action_id='ENGINEER-A05', original_submission_wait_only=True)
    if (not isinstance(result, dict) or result.get('kind') != 'deferred'
            or result.get('reason_code') != 'query_original_professional_submission_before_reproduction'):
        raise ValueError('Original professional sources do not reproduce the actual prior submission query')
    return result


def prepare_engineer_parameter_input(context, action_input, reading, preparation):
    """Validate original A05 sources without reading future results or executing methods."""
    preparation = EngineerDesignParameterPreparation.model_validate(preparation).model_copy(deep=True)
    return _prepare_engineer_design_input(context, action_input, reading, parameter_preparation=preparation)


def prepare_engineer_interface_check_input(context, action_input, reading, preparation):
    """Prepare original check facts; missing/unsupported physical fields stay explicit."""
    preparation = EngineerDesignCheckPreparation.model_validate(preparation).model_copy(deep=True)
    return _prepare_engineer_design_input(context, action_input, reading, check_preparation=preparation)


def _prepare_engineer_design_input(context, action_input, reading, *, parameter_preparation=None, check_preparation=None):
    if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ENGINEER-A05':
        raise ValueError('Professional method preparation requires its original Engineer A05 contract')
    reading.check_method_context(context, 'ENGINEER-A05')
    before = reading.method_evidence()
    future_keys = {ref.key() for ref in action_input.method_result_refs}

    def check_preparation_reading():
        if reading.method_evidence() != before or future_keys.intersection(reading._reads):
            raise ValueError('Professional method preparation cannot execute methods or consume future results')

    check_preparation_reading()
    try:
        return _compile_professional_design(context, action_input, reading,
            action_id='ENGINEER-A05', parameter_preparation=parameter_preparation, check_preparation=check_preparation)
    finally:
        reading.recheck()
        check_preparation_reading()


def _compile_professional_design(context, action_input, reading, *, action_id, parameter_preparation=None, check_preparation=None,
        original_candidate_wait_only=False, original_work_wait_only=False, original_submission_wait_only=False):
    if action_id not in {'ENGINEER-A05', 'ENGINEER-A09'}: raise ValueError('Unsupported professional compilation action')
    now, organization = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('engineer-design-clock-alignment')

    def evidence(refs, historical=False):
        rows = []
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('engineer-design-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_original_professional_evidence', [ref])
            rows.append(row)
        return rows

    def read(ref, schema, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported('engineer-design-projection:' + ref.kind)
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise ValueError('Professional design input leaves original scoped task')
        for field in ('available_at', 'received_at'):
            point = getattr(row, field, None)
            if point is not None:
                clock(point)
                if point.offset > now.offset: _needs('received_original_professional_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('effective_original_professional_input', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical)
        return row

    def authorize(ref, actor, function_ref, action, at, own=False):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        clock(grant.validity.start); clock(at)
        if (grant.actor_id != actor or not same(grant.function_ref, function_ref) or action not in grant.action_ids
                or function.role != 'Engineer' or (own and grant.organization_id != organization)
                or not any(scope_covers(s, action_input.scope) for s in grant.scopes)):
            raise ValueError('Professional work lacks independent original action/function/scope authority')
        if not grant.validity.contains(at): _needs('valid_original_professional_authority', [ref])
        evidence([*grant.basis_refs, *function.basis_refs], at != now)

    def author(row, at):
        if row.author_action_id not in {'ENGINEER-A05', 'ENGINEER-A06', 'ENGINEER-A09', 'ENGINEER-A13'}:
            raise ValueError('Professional record changes original author action')
        authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref, row.author_action_id, at)

    def questions(refs):
        output = []
        for ref in refs:
            gap = read(ref, EngineerResearchGapView)
            question = gap.question
            if (not same(gap.task_ref, task.ref) or not same(gap.brief_ref, brief.ref)
                    or question.scope != action_input.scope or not question.target_refs or not question.recipient_ids
                    or ref.key() not in keys(question.target_refs)):
                raise ValueError('Professional question changes original task/brief/scope/target')
            response = read(question.response_requirement_ref, ServiceResponseRequirementView)
            if not same(response.request_ref, appointment.request_ref) or not set(question.recipient_ids) <= set(response.recipient_ids):
                raise ValueError('Investigation changes original response request/recipient authority')
            for target_ref in question.target_refs:
                target = read(target_ref, EngineerResearchGapView)
                if not same(target.task_ref, task.ref) or not same(target.brief_ref, brief.ref) or target.question != question:
                    raise ValueError('Investigation invents question target or content')
            evidence(question.evidence_refs); output.append(question.model_dump(mode='python'))
        return output

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope': action_input.scope,
            'note': 'Original professional draft or limited opinion; execution, independent review and formal use require separate authorization', **fields}}

    def deferred(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
            'trigger': 'dependency_change', 'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def method_domain(ref):
        if ref.key() not in keys(profile.permitted_method_refs): _unsupported('engineer-design-undeclared-method')
        method = read(ref, EngineerDesignMethodView)
        if (task.discipline_code not in method.discipline_codes or task.function_code not in method.function_codes
                or profile.region_id not in method.region_ids or profile.object_type not in method.object_types
                or task.requested_use not in method.allowed_uses):
            _unsupported('engineer-design-method-object-discipline-region-function-use')
        return method

    def actual_work():
        limit = read(task.design_limit_ref, ArchitectDesignLimitView)
        if not same(limit.appointment_ref, appointment.ref) or limit.as_of != now or limit.coverage != 'complete':
            _needs('complete_current_professional_engagement_limits')
        if limit.prior_submission_ref is not None: return deferred('query_original_professional_submission_before_reproduction', [limit.prior_submission_ref])
        if original_submission_wait_only:
            return None
        keys(limit.option_refs); keys(limit.work_fact_refs)
        if limit.version_branch_count < len(limit.option_refs): raise ValueError('Professional history omits existing branches')
        revision = action_input.prior_option_ref is not None
        if (len(limit.option_refs) + int(not revision) > limit.maximum_candidates
                or limit.version_branch_count + 1 > limit.maximum_versions_branches
                or limit.revision_count + int(revision) > limit.maximum_revisions):
            return deferred('original_professional_candidate_revision_limit_reached', [limit.ref])
        if original_candidate_wait_only:
            return None
        if not keys(task.work_fact_refs) <= keys(limit.work_fact_refs): _needs('professional_work_within_complete_engagement_history')
        invested, cost, current, investments = Fraction(), Fraction(), Fraction(), set()
        for ref in limit.work_fact_refs:
            fact = read(ref, EngineerPlanningWorkFactView, True); clock(fact.window.start)
            if fact.organization_id != organization or fact.investment_key in investments:
                raise ValueError('Professional work repeats investment or borrows another organization')
            investments.add(fact.investment_key)
            if fact.status != 'committed' or fact.window.end.offset > min(now.offset, fact.available_at.offset):
                _needs('actual_confirmed_professional_work')
            if fact.effort.unit != limit.maximum_effort.unit or fact.internal_cost.currency != limit.maximum_cost.currency:
                _unsupported('engineer-design-work-cost-unit-conversion')
            effort, amount = decimal_fraction(fact.effort.value), decimal_fraction(fact.internal_cost.value)
            if effort < 0 or amount < 0: raise ValueError('Actual professional investment/cost cannot be negative')
            evidence([fact.effort.basis_ref, fact.internal_cost.basis_ref], True); invested += effort; cost += amount
            if ref.key() in keys(task.work_fact_refs):
                if not same(fact.task_ref, task.ref): raise ValueError('Professional draft borrows another task investment')
                current += effort
        evidence([task.required_effort.basis_ref, limit.maximum_effort.basis_ref, limit.maximum_cost.basis_ref])
        if min(decimal_fraction(limit.maximum_effort.value), decimal_fraction(limit.maximum_cost.value)) < 0:
            raise ValueError('Professional engagement limit cannot be negative')
        if decimal_fraction(task.required_effort.value) <= 0: raise ValueError('Professional compilation requires positive original effort')
        if task.required_effort.unit != limit.maximum_effort.unit or current < decimal_fraction(task.required_effort.value):
            _needs('actual_work_for_current_professional_draft')
        if invested > decimal_fraction(limit.maximum_effort.value) or cost > decimal_fraction(limit.maximum_cost.value):
            return deferred('original_professional_work_limit_reached', [limit.ref])
        return None

    def original_draft():
        draft = task.draft
        if draft is None: _needs('original_finite_professional_draft')
        if (not same(draft.brief_ref, brief.ref) or not same(draft.engineering_profile_ref, profile.ref) or draft.scope != action_input.scope
                or (draft.parent_option_ref is None) != (action_input.prior_option_ref is None)
                or (draft.parent_option_ref is not None and not same(draft.parent_option_ref, action_input.prior_option_ref))
                or not keys(draft.evidence_refs) <= keys(action_input.evidence_refs)
                or keys(draft.method_result_refs) != keys(action_input.method_result_refs)):
            raise ValueError('Professional draft changes original brief/profile/parent/input versions')
        keys(draft.selected_parameter_refs)
        return draft

    def original_parameter_input(ref, selected_catalogs):
        parameter = read(ref, EngineerValidatedParameterView)
        if not same(parameter.task_ref, task.ref) or not same(parameter.engineering_profile_ref, profile.ref):
            raise ValueError('Professional parameter changes original task/profile')
        catalog = read(parameter.catalog_ref, EngineerParameterCatalogView)
        if (not same(catalog.engineering_profile_ref, profile.ref) or catalog.discipline_code != task.discipline_code
                or catalog.ref.key() not in keys(profile.parameter_catalog_refs) or catalog.ref.key() in selected_catalogs):
            raise ValueError('Professional parameter invents/repeats a catalog or changes discipline')
        selected_catalogs.add(catalog.ref.key()); evidence(parameter.source_refs)
        if not keys(parameter.source_refs) <= keys(action_input.evidence_refs):
            raise ValueError('Professional parameter changes original input evidence')
        if isinstance(parameter.value, Known) and isinstance(parameter.value.value, Measured):
            if parameter.value.value.basis_ref.key() not in keys(parameter.source_refs):
                raise ValueError('Parameter loses original numerical source')
        for bound in (catalog.minimum, catalog.maximum, catalog.step):
            if bound is not None:
                if bound.unit != catalog.unit: _unsupported('engineer-parameter-domain-bound-unit')
                evidence([bound.basis_ref])
        original = EngineerParameterInput(parameter_ref=parameter.ref,catalog_ref=catalog.ref,value_kind=catalog.value_kind,
            value=parameter.value,unit=catalog.unit,minimum=catalog.minimum.value if catalog.minimum else None,
            maximum=catalog.maximum.value if catalog.maximum else None,step=catalog.step.value if catalog.step else None,
            option_refs=catalog.option_refs,source_refs=[task.ref,profile.ref,catalog.ref,parameter.ref,*parameter.source_refs])
        return parameter, catalog, original

    def original_check_scope(spec, target):
        if (not same(spec.brief_ref, brief.ref) or not same(spec.target_ref, target)
                or spec.discipline_code != task.discipline_code or spec.function_code != task.function_code
                or task.requested_use not in spec.allowed_uses):
            raise ValueError('Professional check changes original target/discipline/function/use')
        coverage = read(spec.engineering_scope_ref, EngineerDesignReferenceView)
        if not same(coverage.engineering_profile_ref, profile.ref) or not same(coverage.task_ref, task.ref):
            raise ValueError('Professional check borrows another task/profile coverage')
        for ref in spec.issue_refs: read(ref, EngineerDesignReferenceView)
        return coverage

    def original_check_input(spec, target, coverage):
        facts, basis = [], []
        for ref in (spec.left_fact_ref, spec.right_fact_ref):
            if ref is None:
                facts.append(None)
                continue
            fact = read(ref, EngineerResearchFactView)
            if not same(fact.target_ref, target) or not same(fact.engineering_scope_ref, spec.engineering_scope_ref):
                raise ValueError('Professional fact changes target/scope')
            facts.append(fact); basis.extend(fact.evidence_refs)
        expected_refs = [ref for ref in (spec.left_fact_ref, spec.right_fact_ref) if ref is not None]
        states = [fact.value if fact else {'state':'unknown','reason_code':'original_fact_missing','missing_refs':[]} for fact in facts]
        sources = list({ref.key():ref for ref in [task.ref,profile.ref,spec.ref,coverage.ref,
            *expected_refs,*spec.evidence_refs,*basis,*action_input.evidence_refs]}.values())
        data = EngineerInterfaceInput(requested_check=spec.requested_check,left_code=states[0],right_code=states[1],source_refs=sources)
        return data, expected_refs, facts, basis

    try:
        if action_input.scope != context.scope: raise ValueError('Professional action changes original scope')
        task = read(action_input.task_ref, EngineerDesignTaskView)
        brief = read(action_input.brief_ref, QSCostBriefView)
        profile = read(action_input.engineering_profile_ref, EngineerDesignProfileView)
        if (task.organization_id != organization or not same(task.brief_ref, brief.ref)
                or not same(task.engineering_profile_ref, profile.ref)):
            raise ValueError('Professional work changes original task/brief/profile/organization')
        authorize(task.authority_ref, context.actor_id, context.function_ref, action_id, now, True)
        if task.status != 'authorized': return deferred('original_professional_task_waiting_or_closed', [task.ref])
        appointment = read(task.appointment_ref, EngineerAppointmentView)
        if appointment.provider_organization_id != organization or appointment.status != 'active': _needs('original_active_professional_appointment')
        terms = read(appointment.terms_ref, EngineerServiceTermsView, True)
        if service_terms_digest(terms) != appointment.terms_digest: raise ValueError('Professional work changes accepted terms content')
        if (task.discipline_code not in _known(terms.discipline_codes, 'accepted_professional_disciplines')
                or task.function_code != _known(terms.function_code, 'accepted_professional_function')
                or profile.region_id != _known(terms.region_id, 'accepted_professional_region')
                or profile.object_type != _known(terms.object_type, 'accepted_professional_object_type')):
            raise ValueError('Professional work leaves original accepted discipline/function/region/object')
        if (task.requested_use not in brief.allowed_uses or task.requested_use not in profile.allowed_uses
                or task.requested_use not in _known(terms.requested_uses, 'accepted_professional_uses')):
            raise ValueError('Professional work changes original authorized use')
        if task.discipline_code not in profile.discipline_codes or task.function_code not in profile.function_codes:
            _unsupported('engineer-design-profile-professional-domain')
        if not _known(profile.supported, 'original_professional_profile_support'): _unsupported('engineer-design-object-or-parameter-domain')
        if keys(action_input.evidence_refs) != keys(task.evidence_input_refs) or keys(action_input.method_result_refs) != keys(task.method_result_refs):
            _needs('all_original_professional_evidence_and_method_results')
        evidence(action_input.evidence_refs)
        if action_input.prior_option_ref is not None:
            parent = read(action_input.prior_option_ref, EngineerResearchTargetView, True); author(parent, parent.available_at)
            parent_grant = read(parent.author_authority_ref, Authorization)
            if not same(parent.brief_ref, brief.ref) or parent.author_action_id not in {'ENGINEER-A05', 'ENGINEER-A09'}:
                raise ValueError('Professional revision changes original own professional parent')
            if parent_grant.organization_id != organization: raise ValueError('Professional revision cannot rewrite another organization design')
        if task.choice == 'request_investigation':
            if parameter_preparation is not None or check_preparation is not None:
                raise ValueError('Method preparation cannot replace an original investigation request')
            output = questions(task.question_refs)
            if not output: _needs('specific_original_professional_investigation_questions')
            return completed('request_investigation', questions=output)
        if parameter_preparation is not None:
            if task.choice != 'produce':
                raise ValueError('Parameter preparation requires an original professional production task')
            draft = original_draft()
            work_exit = actual_work()
            if work_exit is not None: return work_exit
            method_domain(PARAMETER_METHOD)
            selected_catalogs, reserved_results, selected = set(), set(), None
            for ref in draft.selected_parameter_refs:
                parameter, catalog, original = original_parameter_input(ref, selected_catalogs)
                if (parameter.validation_result_ref.key() not in keys(action_input.method_result_refs)
                        or parameter.validation_result_ref.key() in reserved_results):
                    raise ValueError('Parameter preparation changes or repeats original reserved result identities')
                reserved_results.add(parameter.validation_result_ref.key())
                if same(parameter.ref, parameter_preparation.input.parameter_ref):
                    if (not same(parameter.validation_result_ref, parameter_preparation.calculation_ref)
                            or type(parameter_preparation.calculation_ref.version) is not str
                            or parameter_preparation.input != original):
                        raise ValueError('Parameter preparation changes original target/catalog/value/source versions')
                    selected = parameter, catalog
            if selected is None:
                raise ValueError('Parameter preparation invents a parameter outside the original draft')
            reading.recheck()
            return {'kind':'prepared', 'preparation':parameter_preparation, 'task':task, 'profile':profile,
                'parameter':selected[0], 'catalog':selected[1]}
        if check_preparation is not None:
            if task.choice not in {'produce','report_limit'}:
                raise ValueError('Check preparation requires an original production or limited-assessment task')
            mappings = task.check_result_targets
            keys([row.check_spec_ref for row in mappings]); keys([row.calculation_ref for row in mappings])
            if (not {row.check_spec_ref.key() for row in mappings} <= keys(task.check_spec_refs)
                    or not {row.calculation_ref.key() for row in mappings} <= keys(task.method_result_refs)):
                raise ValueError('Professional check target declaration leaves its original task inputs')
            selected = next((row for row in mappings if same(row.check_spec_ref, check_preparation.check_spec_ref)), None)
            if selected is None: _needs('original_declared_professional_check_result_target', [task.ref])
            if not same(selected.calculation_ref, check_preparation.calculation_ref) or type(selected.calculation_ref.version) is not str:
                raise ValueError('Check preparation changes its original immutable declared result target')
            if task.choice == 'produce':
                draft = original_draft()
                work_exit = actual_work()
                if work_exit is not None: return work_exit
                reserved_parameters = set()
                for ref in draft.selected_parameter_refs:
                    parameter = read(ref, EngineerValidatedParameterView)
                    if not same(parameter.task_ref, task.ref) or not same(parameter.engineering_profile_ref, profile.ref):
                        raise ValueError('Check preparation borrows another task parameter')
                    reserved_parameters.add(parameter.validation_result_ref.key())
                if reserved_parameters.intersection(row.calculation_ref.key() for row in mappings):
                    raise ValueError('Professional check targets cannot replace original parameter results')
            method_domain(ENGINEER_INTERFACE_METHOD)
            spec = read(selected.check_spec_ref, EngineerResearchCheckSpecView)
            target = action_input.prior_option_ref or brief.ref
            coverage = original_check_scope(spec, target)
            if spec.method_ref is None or not same(spec.method_ref, ENGINEER_INTERFACE_METHOD):
                _unsupported('engineer-design-unbound-professional-check-method')
            data, fact_refs, _, _ = original_check_input(spec, target, coverage)
            if check_preparation.input != data:
                raise ValueError('Check preparation changes original requested check, fact values or source versions')
            reading.recheck()
            return {'kind':'prepared','preparation':check_preparation,'task':task,'profile':profile,
                'spec':spec,'target_ref':target,'input_fact_refs':fact_refs}
        executions, checks = {}, {}
        for ref in task.method_result_refs:
            wrapped = read(ref, EngineerDesignMethodProjection)
            row = wrapped.record
            if not same(row.ref, ref) or not same(row.task_ref, task.ref): raise ValueError('Professional saved execution changes original identity/task')
            if not scope_covers(action_input.scope, row.scope): raise ValueError('Saved professional execution leaves task scope')
            evidence(row.evidence_refs); clock(row.executed_at); clock(row.available_at); clock(row.effective_window.start)
            if row.executed_at.offset > row.available_at.offset or row.available_at.offset > now.offset or not row.effective_window.contains(now):
                _needs('original_received_effective_professional_execution')
            author(row, row.executed_at)
            if row.status != 'ok' and row.result is not None: raise ValueError('Failed/unknown professional execution cannot retain a finding')
            method_domain(row.method_ref)
            if isinstance(row, EngineerParameterResultView):
                if not same(row.engineering_profile_ref, profile.ref) or not same(row.method_ref, PARAMETER_METHOD):
                    _unsupported('engineer-design-unbound-parameter-method')
            else:
                if not same(row.brief_ref, brief.ref): raise ValueError('Professional check changes original brief')
                if row.check_spec_ref.key() in checks: raise ValueError('Professional check repeats execution')
                checks[row.check_spec_ref.key()] = row
            executions[ref.key()] = row
        check_items, uncovered = [], []
        specs = [read(ref, EngineerResearchCheckSpecView) for ref in task.check_spec_refs]
        keys(task.check_spec_refs)
        if not set(checks) <= keys(task.check_spec_refs): raise ValueError('Professional execution invents a check specification')
        target = action_input.prior_option_ref or brief.ref
        for spec in specs:
            coverage = original_check_scope(spec, target)
            saved = checks.get(spec.ref.key()); value, missing, basis, evidence_status = None, ['method_execution'], [], 'missing'
            if saved is not None:
                if not same(saved.target_ref, target) or spec.method_ref is None or not same(saved.method_ref, spec.method_ref):
                    raise ValueError('Professional check changes original target/method')
                if saved.status == 'ok':
                    if not same(saved.method_ref, ENGINEER_INTERFACE_METHOD): _unsupported('engineer-design-unbound-professional-check-method')
                    check_input, expected_refs, facts, fact_basis = original_check_input(spec, target, coverage)
                    basis.extend(fact_basis)
                    if saved.input_fact_refs != expected_refs: raise ValueError('Professional execution changes exact input fact versions')
                    replay = check_interface(check_input)
                    if saved.result != replay: raise ValueError('Professional saved result differs from declared method/facts')
                    value, missing = replay.result, replay.missing_field_paths
                    records = evidence(basis)
                    if all(fact is not None and isinstance(fact.value, Known) for fact in facts):
                        evidence_status = 'sufficient' if all(fact.basis == 'observed' for fact in facts) and all(row.basis_kind == 'observed' for row in records) else 'assumption_based'
                else: missing = ['method_execution:' + saved.status]
            if value in {None, 'undetermined', 'out_of_scope'}:
                uncovered.append(spec.engineering_scope_ref)
            check_items.append({'check_spec_ref':spec.ref,'evidence_refs':list({ref.key():ref for ref in basis}.values()),
                'evidence_status':evidence_status,'method_result_ref':saved.ref if saved else None,'result':value,
                'missing_field_paths':missing,'issue_refs':spec.issue_refs})
        if task.choice == 'report_limit':
            findings = [row['result'] for row in check_items]
            opinion = ('revise' if 'conflict' in findings else 'investigate' if not findings or any(x in {None,'undetermined'} for x in findings)
                       else 'reserve_interpretation' if 'out_of_scope' in findings or any(row['evidence_status'] != 'sufficient' or row['issue_refs'] for row in check_items)
                       else 'support_limited_option')
            return completed('report_limit', assessment={'target_ref':target,'task_ref':task.ref,'check_items':check_items,
                'opinion':opinion,'requested_use':task.requested_use,'uncovered_scope_refs':list({ref.key():ref for ref in uncovered}.values()),
                'explanation':'Limited declared checks only; unexecuted checks and unsupported physical scope remain unresolved'})
        draft = original_draft()
        work_exit = actual_work()
        if work_exit is not None: return work_exit
        if original_candidate_wait_only or original_work_wait_only or original_submission_wait_only:
            reading.recheck()
            return None
        selected_catalogs, selected_options, used_results = set(), set(), set()
        for ref in draft.selected_parameter_refs:
            parameter, catalog, original = original_parameter_input(ref, selected_catalogs)
            saved = executions.get(parameter.validation_result_ref.key())
            if not isinstance(saved, EngineerParameterResultView): _needs('original_parameter_domain_execution')
            if saved.input != original: raise ValueError('Parameter execution changes original input/catalog/value/source versions')
            if saved.status != 'ok': _needs('successful_original_parameter_domain_execution')
            replay = validate_parameter(original)
            if saved.result != replay: raise ValueError('Saved parameter result differs from declared finite domain')
            if replay.finding != 'within_declared_domain': _needs('parameter_within_original_declared_domain')
            used_results.add(saved.ref.key())
            if catalog.value_kind == 'catalog':
                option = read(parameter.value.value, EngineerDesignReferenceView)
                if not same(option.engineering_profile_ref, profile.ref): raise ValueError('Parameter option changes profile')
                selected_options.add(parameter.value.value.key())
        keys(draft.selected_parameter_refs)
        for left,right in profile.incompatible_pairs:
            if left.key() in selected_options and right.key() in selected_options: raise ValueError('Professional candidate selects incompatible catalog options')
        output_questions = questions(task.question_refs)
        if draft.unresolved_questions != [read(ref, EngineerResearchGapView).question for ref in task.question_refs]:
            raise ValueError('Professional candidate removes or invents original unresolved questions')
        if not keys(profile.required_parameter_catalog_refs) <= selected_catalogs:
            if not keys(profile.required_parameter_catalog_refs) <= keys(profile.parameter_catalog_refs):
                raise ValueError('Profile requires parameters outside its declared catalog')
            missing_catalogs = keys(profile.required_parameter_catalog_refs) - selected_catalogs
            for ref in profile.required_parameter_catalog_refs:
                if ref.key() not in missing_catalogs: continue
                catalog = read(ref, EngineerParameterCatalogView)
                if catalog.gap_question_ref is None or catalog.gap_question_ref.key() not in keys(task.question_refs):
                    _needs('specific_unverified_candidate_parameter_questions')
        if any(row['result'] != 'satisfied' or row['evidence_status'] != 'sufficient' or row['issue_refs'] for row in check_items):
            for spec,row in zip(specs,check_items):
                if row['result'] != 'satisfied' or row['evidence_status'] != 'sufficient' or row['issue_refs']:
                    if spec.gap_question_ref is None or spec.gap_question_ref.key() not in keys(task.question_refs):
                        _needs('specific_original_unresolved_professional_check_question')
        if not checks and not output_questions: _needs('unverified_candidate_requires_specific_professional_questions')
        if not keys(draft.interface_refs) <= keys(profile.interface_refs) or not keys(draft.quantity_basis_refs) <= keys(profile.quantity_basis_refs):
            raise ValueError('Professional draft invents interface or quantity basis')
        for ref in [*draft.interface_refs,*draft.quantity_basis_refs]:
            row=read(ref,EngineerDesignReferenceView)
            if not same(row.engineering_profile_ref,profile.ref) or not same(row.task_ref,task.ref) or not keys(row.parameter_refs) <= keys(draft.selected_parameter_refs):
                raise ValueError('Professional interface/quantity basis changes original profile/task/parameters')
            if row.status=='calculated':
                _unsupported('engineer-design-unbound-physical-quantity-or-interface-method')
        if {key for key,row in executions.items() if isinstance(row,EngineerParameterResultView)} != used_results:
            raise ValueError('Professional draft includes unrelated parameter executions')
        return completed('produce',draft=draft.model_dump(mode='python'))
    except ObservationGap as gap:
        reading.recheck(); return gap.result
