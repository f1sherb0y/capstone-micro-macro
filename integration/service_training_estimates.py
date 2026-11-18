"""Produce private training estimates through fixed service-role routes."""
from src.actions.contracts.architect_learning_objects import ArchitectTrainingEstimateView
from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_learning import prepare_qs_training_estimate_input
from src.actions.roles.architect_learning import prepare_architect_training_estimate_input
from src.actions.roles.engineer_learning import prepare_engineer_training_estimate_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_learning import TRAINING_METHOD
from src.organization.models import Authorization


def prepare_service_training_estimate(*, context, action_input, reading,
        estimate_ref, author_authority_ref, validate_current, action_id):
    """Call the declared work estimator once after an independent source gate.

    Caller holds the actual source/authorization guard. The independent gate
    returns None, rechecks original work, participants, outputs and authority,
    and executes no methods. Estimate production reserves no money or effort;
    proposal eligibility still needs budget, window and dependency checks.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    # Source data never selects a module, callback or role.
    if action_id == 'QS-A12':
        role, prepare_input = 'QS', prepare_qs_training_estimate_input
    elif action_id == 'ARCHITECT-A12':
        role, prepare_input = 'Architect', prepare_architect_training_estimate_input
    elif action_id == 'ENGINEER-A12':
        role, prepare_input = 'Engineer', prepare_engineer_training_estimate_input
    else:
        raise TaskConflict('Training estimate requires a supported fixed action route')
    target = ref_type('TrainingEstimate').model_validate(estimate_ref).model_copy(deep=True)
    author_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    if (not isinstance(reading, ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != action_id
            or action_input.scope != context.scope or type(target.version) is not str):
        raise TaskConflict('Training estimate requires original action reading and immutable target')
    reading.check_method_context(context, action_id)
    mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    if reading._resolver.source_mode != mode:
        raise TaskConflict('Training estimate changes its original explicit source mode')
    before = reading.method_evidence()
    prepared = prepare_input(context, action_input, reading)
    if reading.method_evidence() != before:
        raise TaskConflict('Training input preparation must not execute registered methods')
    if prepared['kind'] != 'prepared':
        return prepared
    if (prepared['estimate_ref'] != target
            or any(row['ref'] == target.model_dump(mode='json') for row in reading.evidence())):
        raise TaskConflict('Training estimate replaces a supplied report or changes its original predeclared target')
    data = prepared['input']
    grant = reading.resolve(author_ref)
    if (not isinstance(grant, Authorization) or author_ref not in context.authorization_refs
            or grant not in reading._organizations.grants(context, action_id, role)
            or target not in context.visible_refs or target not in grant.readable_refs):
        raise TaskConflict('Training estimate lacks original author and target read authority')
    for ref in grant.basis_refs:
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise TaskConflict('Training estimate author lacks current actual source evidence')
    methods = reading._methods
    registry_sha256 = methods.content_digest if methods is not None else None
    if validate_current(context=context.model_copy(deep=True), action_input=action_input.model_copy(deep=True),
            training_input=data.model_copy(deep=True), estimate_ref=target.model_copy(deep=True), reading=reading) is not None:
        raise TaskConflict('Training estimate requires independent current original source validation')
    reading.recheck()
    if (reading.method_evidence() != before or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha256
            or any(row['ref'] == target.model_dump(mode='json') for row in reading.evidence())):
        raise TaskConflict('Training source gate executed a method, changed its registry or consumed the future report')
    if mode == 'formal' and any(row['ref']['kind'] == 'Evidence'
            and EvidenceRecord.model_validate(row['projection']).source_kind == 'synthetic' for row in reading.evidence()):
        raise TaskConflict('Formal training estimate cannot use synthetic source evidence')
    result = reading.calculate(TRAINING_METHOD, data)
    executions = reading.method_evidence()
    if (len(executions) != len(before) + 1 or executions[:-1] != before
            or executions[-1]['method_ref'] != TRAINING_METHOD.model_dump(mode='json')
            or executions[-1]['input'] != data.model_dump(mode='json')
            or executions[-1]['result'] != result.model_dump(mode='json')
            or executions[-1]['registry_digest'] != registry_sha256 or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Training estimate lost its original single declared-method execution proof')
    reading.recheck()
    if result.kind != 'ok':
        return result.model_dump(mode='python')
    sources = reading.evidence()
    now = context.business_time
    projection = ArchitectTrainingEstimateView(ref=target, organization_id=reading.organization_id,
        work_profile_ref=prepared['work_profile_ref'], input_sha256=task_digest(data.model_dump(mode='json')),
        report=result.value, executed_at=now, status='ok', scope=context.scope,
        author_actor_id=context.actor_id, author_organization_id=reading.organization_id,
        author_function_ref=context.function_ref, author_authority_ref=author_ref, author_action_id=action_id,
        authored_at=now, available_at=now, effective_window={'start':now, 'end':now, 'bounds':'closed_closed'},
        evidence_refs=[ref_type('Evidence').model_validate(row['ref']) for row in sources if row['ref']['kind'] == 'Evidence'])
    return {'kind':'prepared', 'projection':projection, 'projection_sha256':task_digest(projection.model_dump(mode='json')),
        'context_sha256':task_digest(context.model_dump(mode='json')), 'input_sha256':task_digest(action_input.model_dump(mode='json')),
        'source_mode':mode, 'source_reading':sources, 'reading_sha256':task_digest(sources),
        'author_authority_ref':author_ref.model_dump(mode='json'),
        'method_execution':executions[-1], 'method_registry_sha256':registry_sha256,
        'limitations':['Declared sourced work estimate only; no measured training or capability improvement.',
            'Persist and publish before use; investment, scheduling, dependencies and independent evaluation remain separate.']}
