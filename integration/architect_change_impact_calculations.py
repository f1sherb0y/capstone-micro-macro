"""Produce one original A09 declared impact difference without change effects."""
from src.actions.contracts.architect_change_objects import ArchitectChangeImpactPreparation, ArchitectChangeImpactResultView
from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type
from src.actions.contracts.references import ActionReadView
from src.actions.roles.architect_change import prepare_architect_change_impact_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_change_impact import ARCHITECT_CHANGE_IMPACT_METHOD
from src.organization.models import Authorization


def prepare_architect_change_impact_calculation(*, context, action_input, reading, preparation,
        author_authority_ref, validate_current):
    """Caller holds actual source guard; execute only the declared difference method.

    Independent current-source validation must also verify numeric totals cover
    the original affected scope with consistent cost and time conventions.
    Retain unknown differences and the complete original execution proof; save
    and publish separately before ordinary A09 consumption.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    action_input = action_input.model_copy(deep=True)
    preparation = ArchitectChangeImpactPreparation.model_validate(preparation).model_copy(deep=True)
    author_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    target = preparation.calculation_ref
    if (not isinstance(reading, ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ARCHITECT-A09'
            or action_input.scope != context.scope or type(target.version) is not str
            or action_input.impact_method_ref != ARCHITECT_CHANGE_IMPACT_METHOD):
        raise TaskConflict('Impact production requires original A09 reading, fixed method and immutable result target')
    reading.check_method_context(context, 'ARCHITECT-A09')
    mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    if reading._resolver.source_mode != mode:
        raise TaskConflict('Impact production changes its original explicit source mode')
    before = reading.method_evidence()
    prepared = prepare_architect_change_impact_input(context, action_input, reading, preparation)
    if reading.method_evidence() != before:
        raise TaskConflict('Impact preparation cannot execute registered methods')
    if prepared['kind'] != 'prepared':
        return prepared
    data = prepared['arithmetic']
    if (data is None or prepared['impact_basis'] is None
            or prepared['method'].ref != ARCHITECT_CHANGE_IMPACT_METHOD
            or data.input_sha256 != prepared['input_sha256']):
        raise TaskConflict('Impact production lacks its original sourced numeric basis and evaluation binding')
    future = {ref.key() for ref in action_input.impact_result_refs}

    def check_future_results():
        if future.intersection(reading._reads):
            raise TaskConflict('Impact production cannot consume reserved result outputs')

    check_future_results()
    grant = reading.resolve(author_ref)
    if (not isinstance(grant, Authorization) or author_ref != prepared['profile'].authority_ref
            or author_ref not in context.authorization_refs
            or grant not in reading._organizations.grants(context, 'ARCHITECT-A09', 'Architect')
            or reading.organization_id not in prepared['method'].permitted_author_ids
            or target not in context.visible_refs or target not in grant.readable_refs):
        raise TaskConflict('Impact execution lacks current original A09 author or target read authority')
    for ref in grant.basis_refs:
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise TaskConflict('Impact author lacks current original source evidence')
    methods = reading._methods
    registry_sha = methods.content_digest if methods is not None else None
    if validate_current(context=context.model_copy(deep=True), action_input=action_input.model_copy(deep=True),
            preparation=preparation.model_copy(deep=True), reading=reading) is not None:
        raise TaskConflict('Impact production requires independent actual source and numeric scope validation')
    reading.check_method_context(context, 'ARCHITECT-A09')
    reading.recheck()
    check_future_results()
    if (reading.method_evidence() != before or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha):
        raise TaskConflict('Impact source gate executed a method or changed the original registry')
    if mode == 'formal' and any(row['ref']['kind'] == 'Evidence'
            and EvidenceRecord.model_validate(row['projection']).source_kind == 'synthetic' for row in reading.evidence()):
        raise TaskConflict('Formal impact production cannot use synthetic source evidence')
    result = reading.calculate(ARCHITECT_CHANGE_IMPACT_METHOD, data)
    executions = reading.method_evidence()
    if (len(executions) != len(before) + 1 or executions[:-1] != before
            or executions[-1]['method_ref'] != ARCHITECT_CHANGE_IMPACT_METHOD.model_dump(mode='json')
            or executions[-1]['input'] != data.model_dump(mode='json')
            or executions[-1]['result'] != result.model_dump(mode='json')
            or executions[-1]['registry_digest'] != registry_sha or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha):
        raise TaskConflict('Impact production lost its original single registered execution proof')
    reading.recheck()
    check_future_results()
    if result.kind != 'ok':
        return result.model_dump(mode='python')
    if result.value.input_sha256 != prepared['input_sha256'] or result.value.source_refs != data.source_refs:
        raise TaskConflict('Impact report replaces original evaluation or numeric source binding')
    now, sources = context.business_time, reading.evidence()
    projection = ArchitectChangeImpactResultView(ref=target, method_ref=ARCHITECT_CHANGE_IMPACT_METHOD,
        input_sha256=prepared['input_sha256'], issue_ref=prepared['issue'].ref,
        used_deliverable_ref=prepared['original'].ref, instruction_ref=action_input.instruction_ref,
        status='ok', executed_at=now, author_organization_id=reading.organization_id,
        author_actor_id=context.actor_id, author_function_ref=context.function_ref,
        author_authority_ref=author_ref, author_action_id='ARCHITECT-A09',
        cost_delta=result.value.cost_delta, duration_delta=result.value.duration_delta,
        scope=context.scope, available_at=now,
        effective_window={'start': now, 'end': now, 'bounds': 'closed_closed'},
        evidence_refs=[ref_type('Evidence').model_validate(row['ref']) for row in sources if row['ref']['kind'] == 'Evidence'])
    return {'kind': 'prepared', 'projection': projection,
        'projection_sha256': task_digest(projection.model_dump(mode='json')),
        'context_sha256': task_digest(context.model_dump(mode='json')),
        'input_sha256': task_digest(action_input.model_dump(mode='json')),
        'preparation': preparation.model_dump(mode='json'),
        'preparation_sha256': task_digest(preparation.model_dump(mode='json')),
        'impact_input_sha256': task_digest(data.model_dump(mode='json')), 'source_mode': mode,
        'source_reading': sources, 'reading_sha256': task_digest(sources),
        'author_authority_ref': author_ref.model_dump(mode='json'),
        'method_execution': executions[-1], 'method_registry_sha256': registry_sha,
        'limitations': ['Declared sourced cost and duration differences only; unknown inputs stay unknown.',
            'No inferred prices, calendars, critical path, change registration, fee liability or use permission.',
            'Persist the proof and publish at a fresh authorized read point before ordinary A09 consumption.']}
