"""Produce one sourced QS A13 normalization, independently from comparison use."""
from copy import deepcopy

from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type, walk_references
from src.actions.contracts.qs_research_objects import (
    QSResearchCalculationView, QSResearchMethodProjection, QSResearchProfileView,
    QSResearchTaskView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_research import prepare_qs_research_normalization_input, prepare_qs_research_ranking_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.pricing import decimal_fraction
from src.methods.qs_research import (
    RESEARCH_NORMALIZE_METHOD, RESEARCH_RANK_METHOD, ResearchNormalizationReport, ResearchRankReport,
)
from src.organization.models import Authorization


def _normalization_preparation_payload(prepared):
    """Closed source identity and typed arithmetic input for later reconstruction."""
    return {'input': prepared['input'].model_dump(mode='json'),
        **{name: prepared[name].model_dump(mode='json') for name in
            ('calculation_ref', 'task_ref', 'profile_ref', 'comparison_basis_ref')},
        **{name: [ref.model_dump(mode='json') for ref in prepared[name]] for name in
            ('plan_refs', 'normalization_basis_refs')}}


def _ranking_preparation_payload(prepared):
    return {**_normalization_preparation_payload(prepared), 'normalization_result_ref':
        prepared['normalization_result_ref'].model_dump(mode='json')
        if prepared['normalization_result_ref'] is not None else None}


def prepare_qs_research_normalization_calculation(*, context, action_input, reading,
        calculation_ref, author_authority_ref, validate_current):
    """Caller holds actual source guard; invoke only the declared normalization.

    The independent source gate validates actual complete A04 cost provenance,
    physical coverage and the scope, currency, region, time and dimension of
    each supplied adjustment. It must preserve the cache and execute no method.
    Saving and publishing at a fresh token remain separate operations.
    """
    return _prepare_qs_research_comparison_calculation(context=context, action_input=action_input,
        reading=reading, calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
        validate_current=validate_current, kind='normalization')


def _prepare_qs_research_comparison_calculation(*, context, action_input, reading,
        calculation_ref, author_authority_ref, validate_current, kind, validate_normalization_provenance=None):
    routes = {'normalization': (prepare_qs_research_normalization_input, RESEARCH_NORMALIZE_METHOD,
            ResearchNormalizationReport, _normalization_preparation_payload),
        'ranking': (prepare_qs_research_ranking_input, RESEARCH_RANK_METHOD,
            ResearchRankReport, _ranking_preparation_payload)}
    if kind not in routes or kind=='ranking' and not callable(validate_normalization_provenance):
        raise TaskConflict('Research comparison requires a fixed route and independent normalization provenance verifier for ranking')
    prepare_input, method_ref, report_model, prepare_payload = routes[kind]
    context = ActionContext.model_validate(context).model_copy(deep=True)
    action_input = action_input.model_copy(deep=True)
    target = ref_type('MethodResult').model_validate(calculation_ref).model_copy(deep=True)
    author_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    if (not isinstance(reading, ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A13'
            or action_input.scope != context.scope or type(target.version) is not str):
        raise TaskConflict('Research comparison requires original A13 reading, independent source gate and immutable target')
    reading.check_method_context(context, 'QS-A13')
    mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    if reading._resolver.source_mode != mode:
        raise TaskConflict('Research comparison changes its original explicit source mode')
    before = reading.method_evidence()
    prepared = prepare_input(context, action_input, reading)
    if reading.method_evidence() != before:
        raise TaskConflict('Research comparison input preparation executed a method')
    if prepared['kind'] != 'prepared':
        return prepared
    if prepared['calculation_ref'] != target:
        raise TaskConflict('Research comparison replaces the profile reserved result target')
    task = reading.resolve(prepared['task_ref'])
    profile = reading.resolve(prepared['profile_ref'])
    if (not isinstance(task, QSResearchTaskView) or not isinstance(profile, QSResearchProfileView)
            or task.ref != action_input.task_ref or profile.task_ref != task.ref
            or profile.comparison_basis_ref != prepared['comparison_basis_ref']
            or getattr(profile, kind + '_result_ref') != target):
        raise TaskConflict('Research comparison changes its original prepared task or comparison profile')
    future_keys = {ref.key() for ref in (profile.normalization_result_ref, profile.ranking_result_ref)
        if ref is not None and (kind=='normalization' or ref==profile.ranking_result_ref)}

    def check_future_results():
        if future_keys.intersection(reading._reads):
            raise TaskConflict('Research comparison cannot consume its future comparison outputs')

    check_future_results()
    grant = reading.resolve(author_ref)
    if (not isinstance(grant, Authorization) or author_ref != task.authority_ref
            or author_ref not in context.authorization_refs
            or grant not in reading._organizations.grants(context, 'QS-A13', 'QS')
            or target not in context.visible_refs or target not in grant.readable_refs):
        raise TaskConflict('Research comparison lacks current original QS A13 author and target read authority')
    for ref in grant.basis_refs:
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise TaskConflict('Research comparison author lacks current authority evidence')
    arithmetic = prepared['input']
    # Freeze every numeric basis before the source gate. The method registry
    # rereads these exact references; it must not introduce later evidence.
    for ref in walk_references(arithmetic):
        if ref.kind != 'Evidence':
            continue
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise TaskConflict('Research comparison numeric input lacks current original evidence')
    preparation = prepare_payload(prepared)
    methods = reading._methods
    registry_sha = methods.content_digest if methods is not None else None
    source_cache = reading.evidence()
    if mode == 'formal' and any(row['ref']['kind'] == 'Evidence'
            and EvidenceRecord.model_validate(row['projection']).source_kind == 'synthetic' for row in source_cache):
        raise TaskConflict('Formal research comparison cannot use synthetic source evidence')
    if kind=='ranking' and prepared['normalization_result_ref'] is not None:
        if validate_normalization_provenance(context=context.model_copy(deep=True),
                action_input=action_input.model_copy(deep=True), preparation=deepcopy(preparation),
                original_sources=deepcopy(source_cache), reading=reading) is not True:
            raise TaskConflict('Research ranking requires original persisted normalization execution and actual source lineage')
        check_future_results()
        if (reading.method_evidence() != before or reading.evidence() != source_cache or reading._methods is not methods
                or methods is not None and methods.content_digest != registry_sha):
            raise TaskConflict('Research ranking provenance verifier changed cache or registry, or executed a method')
    if validate_current(context=context.model_copy(deep=True), action_input=action_input.model_copy(deep=True),
            preparation=deepcopy(preparation), arithmetic_input=arithmetic.model_copy(deep=True),
            calculation_ref=target.model_copy(deep=True), original_sources=deepcopy(source_cache), reading=reading) is not None:
        raise TaskConflict('Research comparison requires independent actual cost provenance and comparison domain validation')
    check_future_results()
    if (reading.method_evidence() != before or reading.evidence() != source_cache or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha):
        raise TaskConflict('Research comparison source gate changed cache or registry, or executed a method')
    reading.check_method_context(context, 'QS-A13')
    reading.recheck()
    result = reading.calculate(method_ref, arithmetic)
    executions = reading.method_evidence()
    if (len(executions) != len(before) + 1 or executions[:-1] != before
            or executions[-1]['method_ref'] != method_ref.model_dump(mode='json')
            or executions[-1]['input'] != arithmetic.model_dump(mode='json')
            or executions[-1]['result'] != result.model_dump(mode='json')
            or executions[-1]['registry_digest'] != registry_sha or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha
            or reading.evidence() != source_cache):
        raise TaskConflict('Research comparison lost its original single method execution or source proof')
    check_future_results()
    reading.recheck()
    if result.kind != 'ok':
        return result.model_dump(mode='python')
    report = report_model.model_validate(result.value)
    if kind=='normalization' and (len(report.normalized_costs) != len(arithmetic.plans)
            or [row.plan_ref for row in report.normalized_costs] != prepared['plan_refs']
            or any(row.amount.currency != arithmetic.currency or row.amount.basis_ref != source.fx_basis_ref
                or decimal_fraction(row.amount.value) < 0
                for row, source in zip(report.normalized_costs, arithmetic.plans))):
        raise TaskConflict('Research comparison report changes original plans, currency or numeric evidence')
    if kind=='ranking':
        ranked = [ref for group in report.ranked_groups for ref in group]
        if (any(not group for group in report.ranked_groups) or len(ranked)!=len(arithmetic.options)
                or len({ref.key() for ref in ranked})!=len(ranked)
                or {ref.key() for ref in ranked}!={row.option_ref.key() for row in arithmetic.options}):
            raise TaskConflict('Research ranking report omits or repeats an original comparable option')
    now, sources = context.business_time, reading.evidence()
    comparison = QSResearchCalculationView(ref=target, kind=kind, method_ref=method_ref,
        task_ref=task.ref, profile_ref=profile.ref, comparison_basis_ref=prepared['comparison_basis_ref'],
        plan_refs=prepared['plan_refs'], normalization_basis_refs=prepared['normalization_basis_refs'],
        status='ok', normalized_costs=report.normalized_costs if kind=='normalization' else [],
        ranked_groups=report.ranked_groups if kind=='ranking' else [], calculated_at=now,
        author_actor_id=context.actor_id, author_function_ref=context.function_ref,
        author_authority_ref=author_ref, author_action_id='QS-A13', scope=context.scope, available_at=now,
        effective_window={'start': now, 'end': now, 'bounds': 'closed_closed'},
        evidence_refs=[ref_type('Evidence').model_validate(row['ref']) for row in sources if row['ref']['kind'] == 'Evidence'])
    projection = QSResearchMethodProjection(ref=target, comparison=comparison)
    return {'kind': 'prepared', 'projection': projection,
        'projection_sha256': task_digest(projection.model_dump(mode='json')),
        'context_sha256': task_digest(context.model_dump(mode='json')),
        'input_sha256': task_digest(action_input.model_dump(mode='json')),
        'preparation': preparation, 'preparation_sha256': task_digest(preparation),
        kind + '_input_sha256': task_digest(arithmetic.model_dump(mode='json')),
        'source_mode': mode, 'source_reading': sources, 'reading_sha256': task_digest(sources),
        'author_authority_ref': author_ref.model_dump(mode='json'),
        'method_execution': executions[-1], 'method_registry_sha256': registry_sha,
        'limitations': ['Original submitted scoped A04 costs and explicitly sourced transformations only.',
            ('Unknown or incompatible professional inputs remain unresolved; no ranking or new cost plan.'
                if kind=='normalization' else 'Declared comparable options only; exact ties remain grouped, with no new cost plan.'),
            'No research continuation, expenditure, fee, reservation, investment approval or cash effect.',
            'Save immutable proof and publish at a fresh authorized token before A13 comparison consumption.']}
