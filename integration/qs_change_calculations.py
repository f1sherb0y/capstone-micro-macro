"""Produce original QS-A07 signed arithmetic without determining entitlement."""
from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type
from src.actions.contracts.qs_change_objects import QSChangeResultView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest, prepare_change_arithmetic
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.qs_change import CHANGE_METHOD
from src.organization.models import Authorization
from src.organization.registry import scope_covers


def prepare_qs_change_calculation(*, context, action_input, reading, calculation_ref,
        author_authority_ref, validate_current):
    """Calculate once from original claim lines and complete prior statements.

    The caller holds its actual source writer guard. An independent current
    provenance callback must succeed before the registered method is invoked.
    The returned projection and execution must be saved and published at a new
    authorized reading boundary before valuation use. This does not decide
    entitlement, select a payer, issue a determination or submit anything.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    calculation_ref = ref_type('MethodResult').model_validate(calculation_ref).model_copy(deep=True)
    author_authority_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    if (not isinstance(reading, ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A07'
            or type(calculation_ref.version) is not str or action_input.scope != context.scope):
        raise TaskConflict('Change calculation requires original QS-A07 sources, target and independent validation')
    reading.check_method_context(context, 'QS-A07')
    mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    if reading._resolver.source_mode != mode:
        raise TaskConflict('Change production changes its original explicit source mode')
    prepared = prepare_change_arithmetic(context, action_input, reading, calculation_ref=calculation_ref)
    if prepared['kind'] != 'prepared':
        return prepared
    arithmetic = prepared['input']
    grant = reading.resolve(author_authority_ref)
    now = context.business_time
    if (not isinstance(grant, Authorization) or author_authority_ref not in context.authorization_refs
            or grant.organization_id != reading.organization_id or grant.actor_id != context.actor_id
            or grant.function_ref != context.function_ref or 'QS-A07' not in grant.action_ids
            or not grant.validity.contains(now) or not any(scope_covers(scope, context.scope) for scope in grant.scopes)
            or calculation_ref not in context.visible_refs or calculation_ref not in grant.readable_refs
            or not {ref.key() for ref in arithmetic.source_refs} <= {ref.key() for ref in grant.readable_refs}):
        raise TaskConflict('Change calculation target and original sources lack explicit current author/read authority')
    for ref in grant.basis_refs:
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
            raise TaskConflict('Change calculation author lacks current original evidence')
    methods = reading._methods
    registry_sha256 = methods.content_digest if methods is not None else None
    evidence_before = reading.method_evidence()
    if validate_current(context=context.model_copy(deep=True), action_input=action_input.model_copy(deep=True),
            arithmetic_input=arithmetic.model_copy(deep=True), reading=reading,
            calculation_ref=calculation_ref.model_copy(deep=True)) is not None:
        raise TaskConflict('Actual original change provenance requires independent current validation')
    reading.recheck()
    if (reading.method_evidence() != evidence_before or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Change source validation changed its original registry or executed a method')
    result = reading.calculate(CHANGE_METHOD, arithmetic)
    executions = reading.method_evidence()
    if (len(executions) != len(evidence_before) + 1 or executions[:-1] != evidence_before
            or executions[-1]['method_ref'] != CHANGE_METHOD.model_dump(mode='json')
            or executions[-1]['input'] != arithmetic.model_dump(mode='json')
            or executions[-1]['result'] != result.model_dump(mode='json')
            or executions[-1]['registry_digest'] != registry_sha256
            or reading._methods is not methods or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Change production lost its original registered method invocation evidence')
    reading.recheck()
    if result.kind != 'ok':
        return result.model_dump(mode='python')
    source_reading = reading.evidence()
    evidence_refs = [ref_type('Evidence').model_validate(row['ref']) for row in source_reading
        if row['ref']['kind'] == 'Evidence']
    projection = QSChangeResultView(ref=calculation_ref, method_ref=CHANGE_METHOD,
        contract_ref=prepared['contract_ref'], claim_ref=prepared['claim_ref'],
        input_sha256=content_digest(arithmetic), status='ok',
        assessed_amount=result.value.assessed_amount, period_delta=result.value.period_delta,
        author_actor_id=context.actor_id, author_function_ref=context.function_ref,
        author_authority_ref=author_authority_ref, author_action_id='QS-A07', authored_at=now,
        scope=context.scope, available_at=now,
        effective_window={'start': now, 'end': now, 'bounds': 'closed_closed'}, evidence_refs=evidence_refs)
    return {'kind': 'prepared', 'projection': projection,
        'projection_sha256': task_digest(projection.model_dump(mode='json')),
        'context_sha256': task_digest(context.model_dump(mode='json')),
        'input_sha256': task_digest(action_input.model_dump(mode='json')),
        'source_mode': mode, 'source_reading': source_reading, 'reading_sha256': task_digest(source_reading),
        'method_execution': executions[-1], 'method_registry_sha256': registry_sha256,
        'limitations': ['Declared signed arithmetic only; original measurement and rates require independent evidence.',
            'Cumulative delta subtracts the complete original prior statements; it does not recognize debt or payment.',
            'Save original execution and publish at a fresh authorized read point before valuation use.']}
