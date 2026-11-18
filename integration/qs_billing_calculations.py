"""Produce QS service fee calculations from declared clauses and actual work."""
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type
from src.actions.contracts.qs_billing_objects import qs_billing_types
from src.actions.contracts.references import ActionReadView
from src.actions.roles.service_billing import prepare_service_fee_calculation
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization


def prepare_qs_billing_calculation(*, context, action_input, reading, calculation_ref,
        author_authority_ref, validate_current):
    """Reuse exact fixed/effort rounding and sourced advance-credit rules.

    Caller holds the actual source/authorization writer guard. The independent
    source gate runs first. This produces technical fee evidence, with no claim,
    receivable, advance consumption or cash effect; persist and publish before use.
    The existing declared billing formula is used, without a model or method API.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    calculation_ref = ref_type('FeeCalculation').model_validate(calculation_ref).model_copy(deep=True)
    author_authority_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    if (not isinstance(reading, ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A10'
            or action_input.scope != context.scope or action_input.calculation_ref is not None
            or type(calculation_ref.version) is not str):
        raise TaskConflict('QS fee production requires its original action, empty calculation and immutable target')
    reading.check_method_context(context, 'QS-A10')
    mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    if reading._resolver.source_mode != mode:
        raise TaskConflict('QS fee production changes its explicit original source mode')
    grant = reading.resolve(author_authority_ref)
    if (not isinstance(grant, Authorization) or author_authority_ref not in context.authorization_refs
            or grant not in reading._organizations.grants(context, 'QS-A10', 'QS')
            or calculation_ref not in context.visible_refs or calculation_ref not in grant.readable_refs):
        raise TaskConflict('QS fee production lacks current original author and target read authority')
    for ref in grant.basis_refs:
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise TaskConflict('QS fee production author lacks current original evidence')
    prior_methods = reading.method_evidence()
    methods = reading._methods
    registry_digest = methods.content_digest if methods is not None else None
    if validate_current(context=context.model_copy(deep=True), action_input=action_input.model_copy(deep=True),
            reading=reading, calculation_ref=calculation_ref.model_copy(deep=True)) is not None:
        raise TaskConflict('QS fee production requires independent actual source validation')
    reading.recheck()
    if (reading.method_evidence() != prior_methods or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_digest):
        raise TaskConflict('QS fee source validation changed its registry or executed a method')
    prepared = prepare_service_fee_calculation(context, action_input, reading, role='QS', action_id='QS-A10',
        billing_types=qs_billing_types(), calculation_ref=calculation_ref)
    if prepared['kind'] != 'prepared':
        return prepared
    sources = reading.evidence()
    if mode == 'formal' and any(row['ref']['kind']=='Evidence'
            and EvidenceRecord.model_validate(row['projection']).source_kind=='synthetic' for row in sources):
        raise TaskConflict('Formal QS fee production cannot use synthetic source evidence')
    return {**prepared, 'projection_sha256':task_digest(prepared['projection'].model_dump(mode='json')),
        'context_sha256':task_digest(context.model_dump(mode='json')),
        'input_sha256':task_digest(action_input.model_dump(mode='json')), 'source_mode':mode,
        'source_reading':sources, 'reading_sha256':task_digest(sources),
        'author_authority_ref':author_authority_ref.model_dump(mode='json'),
        'formula':module_factory_descriptor(prepare_service_fee_calculation, 'service_fee.declared_formula'),
        'limitations':['Declared fixed/effort half-even arithmetic and verified original advance credits only.',
            'Save and publish before use; no claim, receivable, credit consumption or cash effect.']}
