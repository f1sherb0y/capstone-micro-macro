"""Prepare an actual registered QS arithmetic result from original authorized sources."""
from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type
from src.actions.contracts.qs_cost_objects import QSCostCalculationView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_cost import prepare_cost_arithmetic
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.qs_cost import COST_METHOD
from src.organization.models import Authorization
from src.organization.registry import scope_covers


def prepare_qs_cost_calculation(*, context, action_input, reading, calculation_ref,
        author_authority_ref, validate_current):
    """Calculate declared quantities/rates only; caller holds its actual source guard.

    Independent host validation of real input provenance is mandatory. The
    original processor's same authority/quantity/price/coverage checks assemble
    the arithmetic. Unknown inputs and overlapping coverage stay unknown.
    This returns a projection and original execution evidence, without writing
    an old reading, publishing a result, submitting a cost plan or invoking a
    model. The host must retain and publish at a fresh authorized read point.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    calculation_ref = ref_type('MethodResult').model_validate(calculation_ref).model_copy(deep=True)
    author_authority_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    if (not isinstance(reading, ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A04'
            or type(calculation_ref.version) is not str):
        raise TaskConflict('Cost calculation requires original QS-A04 reading, target and independent source validation')
    reading.check_method_context(context, 'QS-A04')
    mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    if reading._resolver.source_mode != mode:
        raise TaskConflict('Cost production changes its original explicit source mode')
    prepared = prepare_cost_arithmetic(context, action_input, reading)
    if prepared['kind'] != 'prepared':
        return prepared
    arithmetic = prepared['input']
    grant = reading.resolve(author_authority_ref)
    now = context.business_time
    if (not isinstance(grant, Authorization) or author_authority_ref not in context.authorization_refs
            or grant.organization_id != reading.organization_id or grant.actor_id != context.actor_id
            or grant.function_ref != context.function_ref or 'QS-A04' not in grant.action_ids
            or not grant.validity.contains(now) or not any(scope_covers(scope, context.scope) for scope in grant.scopes)
            or calculation_ref not in context.visible_refs or calculation_ref not in grant.readable_refs):
        raise TaskConflict('Cost calculation target lacks explicit current original author and read authority')
    for ref in grant.basis_refs:
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
            raise TaskConflict('Cost calculation author lacks current original evidence')
    methods = reading._methods
    registry_sha256 = methods.content_digest if methods is not None else None
    if validate_current(context=context.model_copy(deep=True), action_input=action_input.model_copy(deep=True),
            arithmetic_input=arithmetic.model_copy(deep=True), reading=reading) is not None:
        raise TaskConflict('Actual original cost quantity/price provenance requires independent current validation')
    reading.recheck()
    if reading._methods is not methods or methods is not None and methods.content_digest != registry_sha256:
        raise TaskConflict('Cost calculation registry changed before its actual invocation')
    evidence_before = reading.method_evidence()
    result = reading.calculate(COST_METHOD, arithmetic)
    executions = reading.method_evidence()
    if (len(executions) != len(evidence_before) + 1 or executions[:-1] != evidence_before
            or executions[-1]['input'] != arithmetic.model_dump(mode='json')
            or executions[-1]['result'] != result.model_dump(mode='json')
            or executions[-1]['registry_digest'] != registry_sha256
            or reading._methods is not methods or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Cost production lost its original registered method invocation evidence')
    reading.recheck()
    if result.kind != 'ok':
        return result.model_dump(mode='python')
    report = result.value
    source_reading = reading.evidence()
    evidence_refs = [ref_type('Evidence').model_validate(row['ref']) for row in source_reading
        if row['ref']['kind'] == 'Evidence']
    projection = QSCostCalculationView(ref=calculation_ref, method_ref=COST_METHOD,
        task_ref=action_input.task_ref, brief_ref=action_input.brief_ref, option_ref=action_input.option_ref,
        cost_scope_ref=action_input.cost_scope_ref, comparison_basis_ref=action_input.comparison_basis_ref,
        quantity_basis_refs=list(action_input.quantity_basis_refs), price_refs=list(action_input.price_refs),
        quantity_schedule_ref=prepared['quantity_schedule_ref'], status='ok',
        lines=[{'line_key': line.line_key, 'quantity': line.quantity, 'amount': line.amount,
            'basis_refs': line.basis_refs} for line in report.lines],
        known_subtotal=report.known_subtotal, complete_total=report.complete_total, calculated_at=now,
        author_actor_id=context.actor_id, author_function_ref=context.function_ref,
        author_authority_ref=author_authority_ref, author_action_id='QS-A04', scope=context.scope,
        available_at=now, effective_window={'start': now, 'end': now, 'bounds': 'closed_closed'},
        evidence_refs=evidence_refs)
    return {'kind': 'prepared', 'projection': projection, 'projection_sha256': task_digest(projection.model_dump(mode='json')),
        'context_sha256': task_digest(context.model_dump(mode='json')),
        'input_sha256': task_digest(action_input.model_dump(mode='json')),
        'source_mode': mode, 'source_reading': source_reading, 'reading_sha256': task_digest(source_reading),
        'method_execution': executions[-1], 'method_registry_sha256': registry_sha256,
        'limitations': ['Declared arithmetic only; no measurement, price calibration, conversion or physical work inferred.',
            'Partial subtotal is not a complete cost, approved budget, debt or payment.',
            'Persist original execution and publish at a fresh authorized read point before cost-plan use.']}
