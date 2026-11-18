"""Produce original QS-A09 reconciliation without declaring obligations cleared."""
from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type
from src.actions.contracts.qs_final_account_objects import QSFinalResultView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.actions.roles.qs_final_account import prepare_final_account_arithmetic
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.qs_final_account import FINAL_ACCOUNT_METHOD
from src.organization.models import Authorization
from src.organization.registry import scope_covers


def prepare_qs_final_account_calculation(*, context, action_input, reading, calculation_ref,
        author_authority_ref, validate_current):
    """Reconcile complete original price/certificate/cash histories once.

    Caller holds its actual source and authorization writer guard and supplies
    an independent current-source validator. Returned original execution and
    projection require persistence and new-token publication before use. An
    unknown amount stays unknown; signed balances preserve overpayment. No
    legal final-price determination, dispute settlement or clearance is made.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    calculation_ref = ref_type('MethodResult').model_validate(calculation_ref).model_copy(deep=True)
    author_authority_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    if (not isinstance(reading, ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A09'
            or type(calculation_ref.version) is not str or action_input.scope != context.scope):
        raise TaskConflict('Final reconciliation requires original QS-A09 sources, target and independent validation')
    reading.check_method_context(context, 'QS-A09')
    mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    if reading._resolver.source_mode != mode:
        raise TaskConflict('Final reconciliation changes its original explicit source mode')
    prepared = prepare_final_account_arithmetic(context, action_input, reading)
    if prepared['kind'] != 'prepared':
        return prepared
    arithmetic = prepared['input']
    grant = reading.resolve(author_authority_ref)
    now = context.business_time
    if (not isinstance(grant, Authorization) or author_authority_ref not in context.authorization_refs
            or grant.organization_id != reading.organization_id or grant.actor_id != context.actor_id
            or grant.function_ref != context.function_ref or 'QS-A09' not in grant.action_ids
            or not grant.validity.contains(now) or not any(scope_covers(scope, context.scope) for scope in grant.scopes)
            or calculation_ref not in context.visible_refs or calculation_ref not in grant.readable_refs
            or not {ref.key() for ref in arithmetic.source_refs} <= {ref.key() for ref in grant.readable_refs}):
        raise TaskConflict('Final reconciliation target and original histories lack current author/read authority')
    for ref in grant.basis_refs:
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
            raise TaskConflict('Final reconciliation author lacks current original evidence')
    methods = reading._methods
    registry_sha256 = methods.content_digest if methods is not None else None
    evidence_before = reading.method_evidence()
    if validate_current(context=context.model_copy(deep=True), action_input=action_input.model_copy(deep=True),
            arithmetic_input=arithmetic.model_copy(deep=True), reading=reading,
            calculation_ref=calculation_ref.model_copy(deep=True)) is not None:
        raise TaskConflict('Actual original settlement provenance requires independent current validation')
    reading.recheck()
    if (reading.method_evidence() != evidence_before or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Final-account source validation changed its original registry or executed a method')
    result = reading.calculate(FINAL_ACCOUNT_METHOD, arithmetic)
    executions = reading.method_evidence()
    if (len(executions) != len(evidence_before) + 1 or executions[:-1] != evidence_before
            or executions[-1]['method_ref'] != FINAL_ACCOUNT_METHOD.model_dump(mode='json')
            or executions[-1]['input'] != arithmetic.model_dump(mode='json')
            or executions[-1]['result'] != result.model_dump(mode='json')
            or executions[-1]['registry_digest'] != registry_sha256
            or reading._methods is not methods or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Final reconciliation lost its original registered method execution evidence')
    reading.recheck()
    if result.kind != 'ok':
        return result.model_dump(mode='python')
    source_reading = reading.evidence()
    evidence_refs = [ref_type('Evidence').model_validate(row['ref']) for row in source_reading
        if row['ref']['kind'] == 'Evidence']
    projection = QSFinalResultView(ref=calculation_ref, method_ref=FINAL_ACCOUNT_METHOD,
        contract_ref=prepared['contract_ref'], input_sha256=content_digest(arithmetic),
        data=arithmetic, report=result.value, status='ok', executed_at=now,
        author_actor_id=context.actor_id, author_organization_id=reading.organization_id,
        author_function_ref=context.function_ref, author_authority_ref=author_authority_ref,
        author_action_id='QS-A09', authored_at=now, scope=context.scope, available_at=now,
        effective_window={'start':now,'end':now,'bounds':'closed_closed'}, evidence_refs=evidence_refs)
    return {'kind':'prepared','projection':projection,
        'projection_sha256':task_digest(projection.model_dump(mode='json')),
        'context_sha256':task_digest(context.model_dump(mode='json')),
        'input_sha256':task_digest(action_input.model_dump(mode='json')),
        'source_mode':mode,'source_reading':source_reading,'reading_sha256':task_digest(source_reading),
        'method_execution':executions[-1],'method_registry_sha256':registry_sha256,
        'limitations':['Declared reconciliation only; complete original histories and independent authorities remain necessary.',
            'Unknown price/cash stays unknown; signed balance may include retained/disputed obligations or overpayment.',
            'Persist original execution and publish at a fresh authorized read point; no clearance or legal determination inferred.']}
