"""Produce an original A05 modeled area report; no design or approval effects."""
from src.actions.contracts.architect_design_objects import ArchitectDesignAreaPreparation, ArchitectDesignAreaResultView
from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type
from src.actions.contracts.references import ActionReadView
from src.actions.roles.architect_design import prepare_architect_area_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_area import AREA_METHOD
from src.organization.models import Authorization


def prepare_architect_area_calculation(*, context, action_input, reading, preparation,
        author_authority_ref, validate_current):
    """Execute the declared method once after independent original-source checks.

    Caller holds the actual source/authorization guard. The callback rechecks
    draft, finite catalog, floor identities, variable mapping, work and authority
    without invoking methods. Persist and publish before design compilation.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    action_input = action_input.model_copy(deep=True)
    preparation = ArchitectDesignAreaPreparation.model_validate(preparation).model_copy(deep=True)
    target = preparation.calculation_ref
    author_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    if (not isinstance(reading, ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ARCHITECT-A05'
            or action_input.scope != context.scope or type(target.version) is not str):
        raise TaskConflict('Area production requires original A05 reading, immutable target and independent source gate')
    reading.check_method_context(context, 'ARCHITECT-A05')
    mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    if reading._resolver.source_mode != mode:
        raise TaskConflict('Area production changes its original explicit source mode')
    before = reading.method_evidence()
    prepared = prepare_architect_area_input(context, action_input, reading, preparation)
    if reading.method_evidence() != before:
        raise TaskConflict('Area input preparation must not execute registered methods')
    if prepared['kind'] != 'prepared':
        return prepared
    future_keys = {ref.key() for ref in action_input.method_result_refs}

    def check_future_reports():
        if any((row['ref']['kind'], row['ref']['id'], row['ref']['version']) in future_keys
                for row in reading.evidence()):
            raise TaskConflict('Area production cannot consume a reserved report output')

    check_future_reports()
    grant = reading.resolve(author_ref)
    if (not isinstance(grant, Authorization) or author_ref not in context.authorization_refs
            or grant not in reading._organizations.grants(context, 'ARCHITECT-A05', 'Architect')
            or target not in context.visible_refs or target not in grant.readable_refs):
        raise TaskConflict('Area report lacks its original current author and target read authority')
    for ref in grant.basis_refs:
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise TaskConflict('Area author lacks current original source evidence')
    methods = reading._methods
    registry_sha256 = methods.content_digest if methods is not None else None
    if validate_current(context=context.model_copy(deep=True), action_input=action_input.model_copy(deep=True),
            preparation=preparation.model_copy(deep=True), reading=reading) is not None:
        raise TaskConflict('Area production requires independent current original-source validation')
    reading.check_method_context(context, 'ARCHITECT-A05')
    reading.recheck()
    check_future_reports()
    if (reading.method_evidence() != before or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Area source gate executed a method or changed the original registry')
    if mode == 'formal' and any(row['ref']['kind'] == 'Evidence'
            and EvidenceRecord.model_validate(row['projection']).source_kind == 'synthetic' for row in reading.evidence()):
        raise TaskConflict('Formal area production cannot use synthetic source evidence')
    data = preparation.input
    result = reading.calculate(AREA_METHOD, data)
    executions = reading.method_evidence()
    if (len(executions) != len(before) + 1 or executions[:-1] != before
            or executions[-1]['method_ref'] != AREA_METHOD.model_dump(mode='json')
            or executions[-1]['input'] != data.model_dump(mode='json')
            or executions[-1]['result'] != result.model_dump(mode='json')
            or executions[-1]['registry_digest'] != registry_sha256 or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Area production lost its original single registered method execution proof')
    reading.recheck()
    check_future_reports()
    if result.kind != 'ok':
        return result.model_dump(mode='python')
    now = context.business_time
    sources = reading.evidence()
    projection = ArchitectDesignAreaResultView(ref=target, task_ref=prepared['task'].ref,
        design_profile_ref=prepared['profile'].ref, draft_index=preparation.draft_index,
        method_ref=AREA_METHOD, status='ok', executed_at=now, input=data, report=result.value,
        area_variable_refs=preparation.area_variable_refs, floor_count_variable_refs=preparation.floor_count_variable_refs,
        author_actor_id=context.actor_id, author_function_ref=context.function_ref, author_authority_ref=author_ref,
        scope=context.scope, available_at=now, effective_window={'start': now, 'end': now, 'bounds': 'closed_closed'},
        evidence_refs=[ref_type('Evidence').model_validate(row['ref']) for row in sources if row['ref']['kind'] == 'Evidence'])
    return {'kind': 'prepared', 'projection': projection, 'projection_sha256': task_digest(projection.model_dump(mode='json')),
        'context_sha256': task_digest(context.model_dump(mode='json')), 'input_sha256': task_digest(action_input.model_dump(mode='json')),
        'preparation': preparation.model_dump(mode='json'), 'preparation_sha256': task_digest(preparation.model_dump(mode='json')),
        'area_input_sha256': task_digest(data.model_dump(mode='json')), 'source_mode': mode,
        'source_reading': sources, 'reading_sha256': task_digest(sources), 'author_authority_ref': author_ref.model_dump(mode='json'),
        'method_execution': executions[-1], 'method_registry_sha256': registry_sha256,
        'limitations': ['Declared modeled area arithmetic only; unknown or overlapping coverage remains unknown.',
            'No statutory area, safety, planning, design approval, physical output or resource investment inferred.',
            'Persist the original proof and publish at a fresh authorized read point before design compilation.']}
