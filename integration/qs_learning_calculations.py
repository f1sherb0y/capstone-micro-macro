"""Produce QS-A12 comparable-forecast reports from immutable authorized sources."""
from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type
from src.actions.contracts.qs_learning_objects import QSComparisonResultView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_learning import prepare_qs_forecast_comparison_input, prepare_qs_forecast_error_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.qs_learning import COMPARABILITY_METHOD, ERROR_METHOD
from src.organization.models import Authorization


def prepare_qs_forecast_comparability(*, context, action_input, reading,
        calculation_ref, author_authority_ref, validate_current):
    """Invoke the original pure method once after independent actual-source checks.

    Caller holds the current source/authorization guard. The report preserves
    incomparable/unknown-amount results and changes no prediction, learned
    judgment, private access, capability or cash. Persist and publish before use.
    """
    return _prepare_qs_forecast_calculation(context=context,action_input=action_input,reading=reading,
        calculation_ref=calculation_ref,author_authority_ref=author_authority_ref,
        validate_current=validate_current,method_ref=COMPARABILITY_METHOD)


def prepare_qs_forecast_error(*, context, action_input, reading,
        calculation_ref, author_authority_ref, validate_current):
    """Produce error once using an independently saved same-input comparable report.

    The actual source gate must check the original comparison's durable method
    execution provenance. No comparability method is rerun. Caller holds its
    source writer guard; this report applies no judgment, training or capability.
    """
    return _prepare_qs_forecast_calculation(context=context,action_input=action_input,reading=reading,
        calculation_ref=calculation_ref,author_authority_ref=author_authority_ref,
        validate_current=validate_current,method_ref=ERROR_METHOD)


def _prepare_qs_forecast_calculation(*, context, action_input, reading,
        calculation_ref, author_authority_ref, validate_current, method_ref):
    context = ActionContext.model_validate(context).model_copy(deep=True)
    calculation_ref = ref_type('MethodResult').model_validate(calculation_ref).model_copy(deep=True)
    author_authority_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    if (not isinstance(reading, ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A12'
            or action_input.scope != context.scope
            or method_ref == COMPARABILITY_METHOD and action_input.comparability_result_ref is not None
            or method_ref == ERROR_METHOD and (action_input.comparability_result_ref is None
                or calculation_ref == action_input.comparability_result_ref)
            or type(calculation_ref.version) is not str):
        raise TaskConflict('Forecast production requires original QS-A12, an empty comparison and an immutable target')
    reading.check_method_context(context, 'QS-A12')
    mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    if reading._resolver.source_mode != mode:
        raise TaskConflict('Forecast production substitutes its original explicit source mode')
    prepare = prepare_qs_forecast_comparison_input if method_ref == COMPARABILITY_METHOD else prepare_qs_forecast_error_input
    prior_methods = reading.method_evidence()
    prepared = prepare(context, action_input, reading)
    if reading.method_evidence() != prior_methods:
        raise TaskConflict('Forecast input preparation must not rerun a saved comparison method')
    if prepared['kind'] != 'prepared':
        return prepared
    if method_ref == ERROR_METHOD and (
            prepared['error_result_ref'] is not None and prepared['error_result_ref'] != calculation_ref
            or any(row['ref'] == calculation_ref.model_dump(mode='json') for row in reading.evidence())):
        raise TaskConflict('Error production must match its predeclared target without replacing a supplied report')
    data = prepared['input']
    grant = reading.resolve(author_authority_ref)
    if (not isinstance(grant, Authorization) or author_authority_ref not in context.authorization_refs
            or grant not in reading._organizations.grants(context, 'QS-A12', 'QS')
            or calculation_ref not in context.visible_refs or calculation_ref not in grant.readable_refs):
        raise TaskConflict('Forecast report lacks current original QS author and target read authority')
    for ref in grant.basis_refs:
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise TaskConflict('Forecast report author lacks current original evidence')
    methods = reading._methods
    registry_sha256 = methods.content_digest if methods is not None else None
    before = reading.method_evidence()
    dependencies = {} if method_ref == COMPARABILITY_METHOD else {
        'comparison_dependency':prepared['comparison_dependency'].model_copy(deep=True)}
    if validate_current(context=context.model_copy(deep=True), action_input=action_input.model_copy(deep=True),
            comparison_input=data.model_copy(deep=True), calculation_ref=calculation_ref.model_copy(deep=True),
            reading=reading, **dependencies) is not None:
        raise TaskConflict('Forecast production requires independent actual frozen-source and outcome validation')
    reading.recheck()
    if (reading.method_evidence() != before or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Forecast source gate executed a method or changed the original registry')
    source_reading = reading.evidence()
    if mode == 'formal' and any(row['ref']['kind'] == 'Evidence'
            and EvidenceRecord.model_validate(row['projection']).source_kind == 'synthetic' for row in source_reading):
        raise TaskConflict('Formal forecast reports cannot use synthetic sources')
    result = reading.calculate(method_ref, data)
    executions = reading.method_evidence()
    if (len(executions) != len(before)+1 or executions[:-1] != before
            or executions[-1]['input'] != data.model_dump(mode='json')
            or executions[-1]['result'] != result.model_dump(mode='json')
            or executions[-1]['registry_digest'] != registry_sha256
            or reading._methods is not methods or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Forecast production lost its original registered method execution evidence')
    reading.recheck()
    if result.kind != 'ok':
        return result.model_dump(mode='python')
    if method_ref == ERROR_METHOD and result.value != prepared['comparison_dependency'].report:
        raise TaskConflict('Error output differs from the independently saved original comparison report')
    source_reading = reading.evidence()
    now = context.business_time
    projection = QSComparisonResultView(ref=calculation_ref, organization_id=reading.organization_id,
        method_ref=method_ref, data=data, input_sha256=task_digest(data.model_dump(mode='json')),
        report=result.value, executed_at=now, status='ok', scope=context.scope,
        author_actor_id=context.actor_id, author_organization_id=reading.organization_id,
        author_function_ref=context.function_ref, author_authority_ref=author_authority_ref,
        author_action_id='QS-A12', authored_at=now, available_at=now,
        effective_window={'start':now,'end':now,'bounds':'closed_closed'},
        evidence_refs=[ref_type('Evidence').model_validate(row['ref']) for row in source_reading if row['ref']['kind']=='Evidence'])
    return {'kind':'prepared', 'projection':projection, **{
        name:dependency.model_dump(mode='json') for name,dependency in dependencies.items()},
        'projection_sha256':task_digest(projection.model_dump(mode='json')),
        'context_sha256':task_digest(context.model_dump(mode='json')),
        'input_sha256':task_digest(action_input.model_dump(mode='json')), 'source_mode':mode,
        'source_reading':source_reading, 'reading_sha256':task_digest(source_reading),
        'author_authority_ref':author_authority_ref.model_dump(mode='json'),
        'method_execution':executions[-1], 'method_registry_sha256':registry_sha256,
        'limitations':['Original explicit cost bases only; incomparable and unknown amounts are preserved.',
            'Persist and publish before use; no posterior forecast rewrite or learning/capability/cash effect.']}
