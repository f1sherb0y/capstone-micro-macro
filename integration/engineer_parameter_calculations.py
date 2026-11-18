"""Produce an original finite parameter execution; no professional approval effects."""
from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, Measured, Money, ref_type
from src.actions.contracts.engineer_design_objects import (
    EngineerDesignParameterPreparation, EngineerDesignMethodProjection, EngineerParameterResultView,
    EngineerDesignCheckPreparation, EngineerResearchCheckResultView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.engineer_review_objects import EngineerReviewCheckPreparation, EngineerReviewResultView
from src.actions.roles.engineer_review import prepare_engineer_review_check_input
from src.actions.contracts.engineer_research_objects import (
    EngineerResearchCheckPreparation, EngineerResearchMethodProjection,
    EngineerResearchEstimatePreparation, EngineerResearchEstimateView,
)
from src.actions.roles.engineer_research import prepare_engineer_research_check_input, prepare_engineer_research_estimate_input
from src.actions.contracts.engineer_inspection_objects import EngineerInspectionCheckPreparation, EngineerInspectionResultView
from src.actions.roles.engineer_inspection import prepare_engineer_inspection_check_input
from src.actions.contracts.engineer_change_objects import (
    EngineerChangeCheckPreparation, EngineerChangeCheckResultView, EngineerChangeMethodProjection,
    EngineerChangeParameterPreparation, EngineerChangeRevisionCheckPreparation,
)
from src.actions.roles.engineer_change import (
    prepare_engineer_change_check_input, prepare_engineer_change_parameter_input,
    prepare_engineer_change_revision_check_input,
)
from src.actions.roles.engineer_design import prepare_engineer_parameter_input, prepare_engineer_interface_check_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.engineer_parameters import PARAMETER_METHOD
from src.methods.engineer_checks import ENGINEER_INTERFACE_METHOD
from src.methods.engineer_research_estimates import ENGINEER_RESEARCH_ESTIMATE_METHOD, EngineerResearchEstimateReport
from src.organization.models import Authorization


def prepare_engineer_parameter_calculation(*, context, action_input, reading, preparation,
        author_authority_ref, validate_current):
    """Execute the fixed method once after independent original-source checks.

    Caller holds the actual source guard. Unknown/outside findings are retained
    as domain findings, never converted into successful professional designs.
    Persist and publish before consuming the predeclared result in ordinary A05.
    """
    return _prepare_engineer_design_calculation(context=context, action_input=action_input, reading=reading,
        preparation=preparation, author_authority_ref=author_authority_ref,
        validate_current=validate_current, result_kind='parameter')


def _prepare_engineer_design_calculation(*, context, action_input, reading, preparation,
        author_authority_ref, validate_current, result_kind):
    """Fixed Engineer execution proof; callers cannot select arbitrary methods."""
    action_id = 'ENGINEER-A05'
    if result_kind == 'parameter':
        model, method_ref, prepare_input = EngineerDesignParameterPreparation, PARAMETER_METHOD, prepare_engineer_parameter_input
    elif result_kind == 'interface_check':
        model, method_ref, prepare_input = EngineerDesignCheckPreparation, ENGINEER_INTERFACE_METHOD, prepare_engineer_interface_check_input
    elif result_kind == 'review_check':
        model, method_ref, prepare_input = EngineerReviewCheckPreparation, ENGINEER_INTERFACE_METHOD, prepare_engineer_review_check_input
        action_id = 'ENGINEER-A06'
    elif result_kind == 'research_check':
        model, method_ref, prepare_input = EngineerResearchCheckPreparation, ENGINEER_INTERFACE_METHOD, prepare_engineer_research_check_input
        action_id = 'ENGINEER-A13'
    elif result_kind == 'research_estimate':
        model, method_ref, prepare_input = EngineerResearchEstimatePreparation, ENGINEER_RESEARCH_ESTIMATE_METHOD, prepare_engineer_research_estimate_input
        action_id = 'ENGINEER-A13'
    elif result_kind == 'inspection_check':
        model, method_ref, prepare_input = EngineerInspectionCheckPreparation, ENGINEER_INTERFACE_METHOD, prepare_engineer_inspection_check_input
        action_id = 'ENGINEER-A08'
    elif result_kind == 'change_check':
        model, method_ref, prepare_input = EngineerChangeCheckPreparation, ENGINEER_INTERFACE_METHOD, prepare_engineer_change_check_input
        action_id = 'ENGINEER-A09'
    elif result_kind == 'change_parameter':
        model, method_ref, prepare_input = EngineerChangeParameterPreparation, PARAMETER_METHOD, prepare_engineer_change_parameter_input
        action_id = 'ENGINEER-A09'
    elif result_kind == 'change_revision_check':
        model, method_ref, prepare_input = EngineerChangeRevisionCheckPreparation, ENGINEER_INTERFACE_METHOD, prepare_engineer_change_revision_check_input
        action_id = 'ENGINEER-A09'
    else:
        raise TaskConflict('Professional production requires an explicitly supported original result kind')
    context = ActionContext.model_validate(context).model_copy(deep=True)
    action_input = action_input.model_copy(deep=True)
    preparation = model.model_validate(preparation).model_copy(deep=True)
    target = preparation.calculation_ref
    author_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    if (not isinstance(reading, ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != action_id
            or action_input.scope != context.scope or type(target.version) is not str):
        raise TaskConflict('Professional result production requires original action reading, immutable target and independent source gate')
    reading.check_method_context(context, action_id)
    mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    if reading._resolver.source_mode != mode:
        raise TaskConflict('Professional result production changes its original explicit source mode')
    before = reading.method_evidence()
    prepared = prepare_input(context, action_input, reading, preparation)
    if reading.method_evidence() != before:
        raise TaskConflict('Professional result input preparation must not execute registered methods')
    if prepared['kind'] != 'prepared':
        return prepared
    future_keys = ({target.key()} if result_kind in {'research_estimate', 'inspection_check'}
        else {ref.key() for ref in action_input.method_result_refs})

    def check_future_results():
        if future_keys.intersection(reading._reads):
            raise TaskConflict('Professional result production cannot consume reserved result outputs')

    check_future_results()
    grant = reading.resolve(author_ref)
    if (not isinstance(grant, Authorization) or author_ref != prepared['task'].authority_ref
            or author_ref not in context.authorization_refs
            or grant not in reading._organizations.grants(context, action_id, 'Engineer')
            or target not in context.visible_refs or target not in grant.readable_refs):
        raise TaskConflict('Professional result execution lacks its original current author and target read authority')
    for ref in grant.basis_refs:
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise TaskConflict('Professional result author lacks current original source evidence')
    methods = reading._methods
    registry_sha256 = methods.content_digest if methods is not None else None
    if validate_current(context=context.model_copy(deep=True), action_input=action_input.model_copy(deep=True),
            preparation=preparation.model_copy(deep=True), reading=reading) is not None:
        raise TaskConflict('Professional result production requires independent current original-source validation')
    reading.check_method_context(context, action_id)
    reading.recheck()
    check_future_results()
    if (reading.method_evidence() != before or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Professional result source gate executed a method or changed the original registry')
    if mode == 'formal' and any(row['ref']['kind'] == 'Evidence'
            and EvidenceRecord.model_validate(row['projection']).source_kind == 'synthetic' for row in reading.evidence()):
        raise TaskConflict('Formal professional result production cannot use synthetic source evidence')
    data = preparation.input
    result = reading.calculate(method_ref, data)
    executions = reading.method_evidence()
    if (len(executions) != len(before) + 1 or executions[:-1] != before
            or executions[-1]['method_ref'] != method_ref.model_dump(mode='json')
            or executions[-1]['input'] != data.model_dump(mode='json')
            or executions[-1]['result'] != result.model_dump(mode='json')
            or executions[-1]['registry_digest'] != registry_sha256 or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Professional result production lost its original single registered execution proof')
    reading.recheck()
    check_future_results()
    if result.kind != 'ok':
        return result.model_dump(mode='python')
    now, sources = context.business_time, reading.evidence()
    # "ok" records a successful invocation, not domain membership or approval.
    fields = dict(ref=target, task_ref=prepared['task'].ref, method_ref=method_ref,
        status='ok', executed_at=now, result=result.value,
        author_actor_id=context.actor_id, author_function_ref=context.function_ref,
        author_authority_ref=author_ref, author_action_id=action_id, scope=context.scope,
        available_at=now, effective_window={'start':now, 'end':now, 'bounds':'closed_closed'},
        evidence_refs=[ref_type('Evidence').model_validate(row['ref']) for row in sources if row['ref']['kind'] == 'Evidence'])
    if result_kind in {'parameter', 'change_parameter'}:
        record = EngineerParameterResultView(**fields, engineering_profile_ref=prepared['profile'].ref, input=data)
        input_sha_key = 'parameter_input_sha256'
        domain_limitation = 'Exact declared parameter membership only; unknown/outside findings remain unchanged.'
        if result_kind == 'change_parameter':
            domain_limitation = 'Original authorized revision parameter membership only; no revision registration or obligation discharge.'
    elif result_kind in {'interface_check', 'research_check'}:
        record = EngineerResearchCheckResultView(**fields, brief_ref=prepared['task'].brief_ref,
            check_spec_ref=prepared['spec'].ref, target_ref=prepared['target_ref'], input_fact_refs=prepared['input_fact_refs'])
        input_sha_key = 'check_input_sha256'
        domain_limitation = 'Declared synthetic interface-code rule only; conflict/undetermined/out_of_scope remain unchanged.'
    elif result_kind == 'research_estimate':
        report = EngineerResearchEstimateReport.model_validate(result.value)
        effort = Known[Measured](state='known', value=report.effort)
        cost = Known[Money](state='known', value=report.estimated_cost)
        request = prepared['request']
        if (report.source_refs != data.source_refs or request.estimate_ref != target
                or request.work_profile_ref != data.work_profile_ref
                or request.effort_estimate != effort or request.incremental_cost != cost):
            raise TaskConflict('Research estimate output differs from original request work, cost, basis or sources')
        # Original estimate projection keeps its transport schema. The complete
        # report and explicit A13 author action remain in the execution/context.
        fields.pop('result')
        fields.pop('author_action_id')
        record = EngineerResearchEstimateView(**fields, request_profile_ref=request.ref,
            input_refs=request.input_refs, work_profile_ref=request.work_profile_ref,
            effort_estimate=effort, incremental_cost=cost)
        input_sha_key = 'estimate_input_sha256'
        domain_limitation = 'Sourced finite cost/work arithmetic only; original request values and numeric basis must match.'
    elif result_kind == 'inspection_check':
        record = EngineerInspectionResultView(**fields, applicable_design_ref=prepared['design'].ref,
            design_content_sha256=prepared['design'].content_sha256, check_spec_ref=prepared['spec'].ref,
            observation_ref=prepared['observation'].ref, author_organization_id=reading.organization_id)
        input_sha_key = 'check_input_sha256'
        domain_limitation = 'Declared code check on original visible observation only; conflict/undetermined/out_of_scope stay intact.'
    elif result_kind in {'change_check', 'change_revision_check'}:
        checked_target = prepared['target_ref'] if result_kind == 'change_revision_check' else prepared['original'].ref
        record = EngineerChangeCheckResultView(**fields, brief_ref=prepared['original'].brief_ref,
            check_spec_ref=prepared['spec'].ref, target_ref=checked_target,
            input_fact_refs=prepared['input_fact_refs'], issue_ref=prepared['issue'].ref,
            original_content_sha256=prepared['original'].content_sha256)
        input_sha_key = 'check_input_sha256'
        domain_limitation = 'Original issue/version code recheck only; conflict/undetermined/out_of_scope do not discharge obligations.'
        if result_kind == 'change_revision_check':
            domain_limitation = 'Original revision parent-option code check only; limited findings grant no revision registration or approval.'
    else:
        record = EngineerReviewResultView(**fields, review_request_ref=prepared['request'].ref,
            target_ref=prepared['target'].ref, content_sha256=prepared['target'].content_sha256,
            check_spec_ref=prepared['spec'].ref, requested_use=prepared['request'].requested_use,
            input_fact_refs=prepared['input_fact_refs'], issue_refs=prepared['issue_refs'],
            author_organization_id=reading.organization_id)
        input_sha_key = 'check_input_sha256'
        domain_limitation = 'Scoped declared code rule only; conflict/undetermined/out_of_scope and original issues remain unchanged.'
    if result_kind in {'review_check', 'inspection_check'}:
        projection = record
    elif result_kind == 'research_check':
        projection = EngineerResearchMethodProjection(ref=target, check=record)
    elif result_kind == 'research_estimate':
        projection = EngineerResearchMethodProjection(ref=target, estimate=record)
    elif result_kind in {'change_check', 'change_parameter', 'change_revision_check'}:
        projection = EngineerChangeMethodProjection(ref=target, record=record)
    else:
        projection = EngineerDesignMethodProjection(ref=target, record=record)
    return {'kind':'prepared', 'projection':projection, 'projection_sha256':task_digest(projection.model_dump(mode='json')),
        'context_sha256':task_digest(context.model_dump(mode='json')), 'input_sha256':task_digest(action_input.model_dump(mode='json')),
        'preparation':preparation.model_dump(mode='json'), 'preparation_sha256':task_digest(preparation.model_dump(mode='json')),
        input_sha_key:task_digest(data.model_dump(mode='json')), 'source_mode':mode,
        'source_reading':sources, 'reading_sha256':task_digest(sources), 'author_authority_ref':author_ref.model_dump(mode='json'),
        'method_execution':executions[-1], 'method_registry_sha256':registry_sha256,
        'limitations':[domain_limitation,
            'No physical performance, compatibility, safety, professional approval or formal design inferred.',
            'Persist the original proof and publish at a fresh authorized read point before consuming the action result.']}
