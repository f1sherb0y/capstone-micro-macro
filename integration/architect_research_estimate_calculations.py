"""Produce one original A13 sourced investigation estimate without task effects."""
from src.actions.contracts.architect_research_objects import (
    ArchitectResearchEstimatePreparation, ArchitectResearchEstimateView,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type
from src.actions.contracts.references import ActionReadView
from src.actions.roles.architect_research import prepare_architect_research_estimate_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_research_estimates import (
    ARCHITECT_RESEARCH_ESTIMATE_METHOD, ArchitectResearchEstimateReport,
)
from src.organization.models import Authorization


def prepare_architect_research_estimate_calculation(*, context, action_input, reading, preparation,
        author_authority_ref, validate_current):
    """Caller holds actual source guard; execute only the fixed work estimate.

    Independent current validation must verify actual work quantity and rate
    coverage and conventions. The estimate must retain the original requested
    effort, cost and numeric basis exactly. Save and publish separately before
    A13 consumes the result. This creates no task, work, fee or reservation.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    action_input = action_input.model_copy(deep=True)
    preparation = ArchitectResearchEstimatePreparation.model_validate(preparation).model_copy(deep=True)
    author_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    target = preparation.calculation_ref
    if (not isinstance(reading, ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ARCHITECT-A13'
            or action_input.scope != context.scope or type(target.version) is not str):
        raise TaskConflict('Research estimate requires original A13 reading, source validator and immutable result target')
    reading.check_method_context(context, 'ARCHITECT-A13')
    mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    if reading._resolver.source_mode != mode:
        raise TaskConflict('Research estimate changes its original explicit source mode')
    before = reading.method_evidence()
    prepared = prepare_architect_research_estimate_input(context, action_input, reading, preparation)
    if reading.method_evidence() != before:
        raise TaskConflict('Research input preparation cannot execute registered methods')
    if prepared['kind'] != 'prepared':
        return prepared
    task, request = prepared['task'], prepared['request']
    if (prepared['method'].ref != ARCHITECT_RESEARCH_ESTIMATE_METHOD
            or prepared['work'].estimate_basis.method_ref != ARCHITECT_RESEARCH_ESTIMATE_METHOD
            or request.estimate_ref != target or request.ref != preparation.request_profile_ref):
        raise TaskConflict('Research estimate changes original method, work basis or request result target')

    def check_future_result():
        if target.key() in reading._reads:
            raise TaskConflict('Research estimate cannot consume its reserved result output')

    check_future_result()
    grant = reading.resolve(author_ref)
    if (not isinstance(grant, Authorization) or author_ref != task.authority_ref
            or author_ref not in context.authorization_refs
            or grant not in reading._organizations.grants(context, 'ARCHITECT-A13', 'Architect')
            or target not in context.visible_refs or target not in grant.readable_refs):
        raise TaskConflict('Research estimate lacks current original A13 author and target read authority')
    for ref in grant.basis_refs:
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise TaskConflict('Research estimate author lacks current original authority evidence')
    methods = reading._methods
    registry_sha = methods.content_digest if methods is not None else None
    source_cache = reading.evidence()
    if validate_current(context=context.model_copy(deep=True), action_input=action_input.model_copy(deep=True),
            preparation=preparation.model_copy(deep=True), reading=reading) is not None:
        raise TaskConflict('Research estimate requires independent actual source and numeric scope validation')
    reading.check_method_context(context, 'ARCHITECT-A13')
    reading.recheck()
    check_future_result()
    if (reading.method_evidence() != before or reading.evidence() != source_cache or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha):
        raise TaskConflict('Research source gate changed original cache or registry, or executed a method')
    if mode == 'formal' and any(row['ref']['kind'] == 'Evidence'
            and EvidenceRecord.model_validate(row['projection']).source_kind == 'synthetic' for row in source_cache):
        raise TaskConflict('Formal research estimate cannot use synthetic source evidence')
    result = reading.calculate(ARCHITECT_RESEARCH_ESTIMATE_METHOD, preparation.input)
    executions = reading.method_evidence()
    if (len(executions) != len(before) + 1 or executions[:-1] != before
            or executions[-1]['method_ref'] != ARCHITECT_RESEARCH_ESTIMATE_METHOD.model_dump(mode='json')
            or executions[-1]['input'] != preparation.input.model_dump(mode='json')
            or executions[-1]['result'] != result.model_dump(mode='json')
            or executions[-1]['registry_digest'] != registry_sha or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha):
        raise TaskConflict('Research estimate lost its original single registered execution proof')
    reading.recheck()
    check_future_result()
    if result.kind != 'ok':
        return result.model_dump(mode='python')
    report = ArchitectResearchEstimateReport.model_validate(result.value)
    if (report.source_refs != preparation.input.source_refs
            or request.effort_estimate.state != 'known' or request.incremental_cost.state != 'known'
            or report.effort != request.effort_estimate.value
            or report.estimated_cost != request.incremental_cost.value):
        raise TaskConflict('Research estimate changes original requested effort, cost, basis or source references')
    now, sources = context.business_time, reading.evidence()
    projection = ArchitectResearchEstimateView(ref=target, task_ref=task.ref, request_profile_ref=request.ref,
        input_refs=request.input_refs, work_profile_ref=request.work_profile_ref,
        effort_estimate={'state': 'known', 'value': report.effort},
        incremental_cost={'state': 'known', 'value': report.estimated_cost},
        status='ok', method_ref=ARCHITECT_RESEARCH_ESTIMATE_METHOD,
        author_actor_id=context.actor_id, author_function_ref=context.function_ref, author_authority_ref=author_ref,
        scope=context.scope, available_at=now,
        effective_window={'start': now, 'end': now, 'bounds': 'closed_closed'},
        evidence_refs=[ref_type('Evidence').model_validate(row['ref']) for row in sources if row['ref']['kind'] == 'Evidence'])
    return {'kind': 'prepared', 'projection': projection,
        'projection_sha256': task_digest(projection.model_dump(mode='json')),
        'context_sha256': task_digest(context.model_dump(mode='json')),
        'input_sha256': task_digest(action_input.model_dump(mode='json')),
        'preparation': preparation.model_dump(mode='json'),
        'preparation_sha256': task_digest(preparation.model_dump(mode='json')),
        'estimate_input_sha256': task_digest(preparation.input.model_dump(mode='json')), 'source_mode': mode,
        'source_reading': sources, 'reading_sha256': task_digest(sources),
        'author_authority_ref': author_ref.model_dump(mode='json'),
        'method_execution': executions[-1], 'method_registry_sha256': registry_sha,
        'limitations': ['Sourced work quantity, effort, exact effort rate and fixed cost only.',
            'No inferred productivity, site condition, duration, investigation task, reservation, fee or cash.',
            'Persist the original proof and publish under a fresh authorized read token before A13 consumption.']}
