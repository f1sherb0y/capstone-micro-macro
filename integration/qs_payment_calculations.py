"""Produce declared QS-A08 measurement results from one original execution."""
from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type
from src.actions.contracts.qs_payment_objects import QSPaymentResultView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.actions.roles.qs_payment import prepare_payment_arithmetic
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.qs_payment import PAYMENT_METHOD
from src.organization.models import Authorization
from src.organization.registry import scope_covers


def prepare_qs_payment_calculations(*, context, action_input, reading, author_authority_ref, validate_current):
    """Calculate declared work, offsets and history once; unknown cash stays unknown.

    The original application must declare distinct future measurement result
    refs, while this production input has no saved measurement_result_refs.
    Caller holds the actual source writer guard and independently validates
    provenance. Returned projections require original execution persistence and
    new-token publication. No certificate, debt, cash or refund is created.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    author_authority_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    if (not isinstance(reading, ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A08'
            or action_input.scope != context.scope):
        raise TaskConflict('Payment production requires its original QS-A08 reading and independent validation')
    reading.check_method_context(context, 'QS-A08')
    mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    if reading._resolver.source_mode != mode:
        raise TaskConflict('Payment production changes its original explicit source mode')
    prepared = prepare_payment_arithmetic(context, action_input, reading)
    if prepared['kind'] != 'prepared':
        return prepared
    arithmetic = prepared['input']
    result_refs = prepared['result_refs']
    grant = reading.resolve(author_authority_ref)
    now = context.business_time
    if (not isinstance(grant, Authorization) or author_authority_ref not in context.authorization_refs
            or grant.organization_id != reading.organization_id or grant.actor_id != context.actor_id
            or grant.function_ref != context.function_ref or 'QS-A08' not in grant.action_ids
            or not grant.validity.contains(now) or not any(scope_covers(scope, context.scope) for scope in grant.scopes)
            or not {ref.key() for ref in [*result_refs.values(), *arithmetic.source_refs]}
                <= {ref.key() for ref in grant.readable_refs}
            or not {ref.key() for ref in result_refs.values()} <= {ref.key() for ref in context.visible_refs}
            or any(type(ref.version) is not str for ref in result_refs.values())):
        raise TaskConflict('Payment result targets and original inputs lack explicit current author/read authority')
    for ref in grant.basis_refs:
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
            raise TaskConflict('Payment calculation author lacks current original evidence')
    methods = reading._methods
    registry_sha256 = methods.content_digest if methods is not None else None
    evidence_before = reading.method_evidence()
    if validate_current(context=context.model_copy(deep=True), action_input=action_input.model_copy(deep=True),
            arithmetic_input=arithmetic.model_copy(deep=True), reading=reading,
            result_refs={kind: ref.model_copy(deep=True) for kind, ref in result_refs.items()}) is not None:
        raise TaskConflict('Actual original payment provenance requires independent current validation')
    reading.recheck()
    if (reading.method_evidence() != evidence_before or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Payment source validation changed its original registry or executed a method')
    result = reading.calculate(PAYMENT_METHOD, arithmetic)
    executions = reading.method_evidence()
    if (len(executions) != len(evidence_before) + 1 or executions[:-1] != evidence_before
            or executions[-1]['method_ref'] != PAYMENT_METHOD.model_dump(mode='json')
            or executions[-1]['input'] != arithmetic.model_dump(mode='json')
            or executions[-1]['result'] != result.model_dump(mode='json')
            or executions[-1]['registry_digest'] != registry_sha256
            or reading._methods is not methods or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Payment production lost its original registered invocation evidence')
    reading.recheck()
    if result.kind != 'ok':
        return result.model_dump(mode='python')
    source_reading = reading.evidence()
    evidence_refs = [ref_type('Evidence').model_validate(row['ref']) for row in source_reading
        if row['ref']['kind'] == 'Evidence']
    projections = [QSPaymentResultView(ref=ref, method_ref=PAYMENT_METHOD,
        contract_ref=prepared['contract_ref'], application_ref=prepared['application_ref'], result_kind=kind,
        valuation_basis=prepared['valuation_basis'], correction_of=prepared['correction_of'],
        input_sha256=content_digest(arithmetic), status='ok', report=result.value.model_copy(deep=True),
        author_actor_id=context.actor_id, author_function_ref=context.function_ref,
        author_authority_ref=author_authority_ref, author_action_id='QS-A08', authored_at=now,
        scope=context.scope, available_at=now,
        effective_window={'start': now, 'end': now, 'bounds': 'closed_closed'}, evidence_refs=evidence_refs)
        for kind, ref in result_refs.items()]
    return {'kind': 'prepared', 'projections': projections,
        'projections_sha256': task_digest([row.model_dump(mode='json') for row in projections]),
        'context_sha256': task_digest(context.model_dump(mode='json')),
        'input_sha256': task_digest(action_input.model_dump(mode='json')),
        'source_mode': mode, 'source_reading': source_reading, 'reading_sha256': task_digest(source_reading),
        'method_execution': executions[-1], 'method_registry_sha256': registry_sha256,
        'limitations': ['Declared arithmetic only; real work, rates, payment conditions and histories require independent evidence.',
            'Unknown eligibility or certified cash stays unknown; a calculation does not issue a certificate or create cash.',
            'Persist the original execution and publish all declared result refs at a fresh authorized read point.']}
