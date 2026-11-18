"""Produce sourced QS-A06 comparison prices without changing original bids."""
from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type
from src.actions.contracts.qs_bid_objects import QSBidMethodResultView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_bid import prepare_bid_normalization, prepare_bid_ranking
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.qs_bid import NORMALIZE_METHOD, RANK_METHOD
from src.organization.models import Authorization
from src.organization.registry import scope_covers


def prepare_qs_bid_normalization(*, context, action_input, reading, calculation_ref,
        author_authority_ref, validate_current):
    """Produce one normalization execution under the actual source writer guard."""
    return _prepare_qs_bid_calculation(context=context, action_input=action_input, reading=reading,
        calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
        validate_current=validate_current, kind='normalization')


def prepare_qs_bid_ranking(*, context, action_input, reading, calculation_ref,
        author_authority_ref, validate_current):
    """Rank original comparable bids once; saved normalization provenance is mandatory.

    The independent validate_current gate must check actual saved normalization
    provenance, not just accept well-shaped prices. Unknown eligibility/risk is
    never supplied as zero and exact ties remain tied by the registered method.
    """
    return _prepare_qs_bid_calculation(context=context, action_input=action_input, reading=reading,
        calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
        validate_current=validate_current, kind='ranking')


def _prepare_qs_bid_calculation(*, context, action_input, reading, calculation_ref,
        author_authority_ref, validate_current, kind):
    """Invoke the selected comparison method once after actual source validation.

    Caller holds the actual source/authorization writer guard. Original bidder
    prices and unknown eligibility stay unchanged. The result must be durably
    saved and exposed at a fresh authorized token before evaluation use; it
    creates no exclusion, award, contract or payment effect.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    calculation_ref = ref_type('MethodResult').model_validate(calculation_ref).model_copy(deep=True)
    author_authority_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    if (not isinstance(reading, ActionReadView) or not callable(validate_current)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A06'
            or type(calculation_ref.version) is not str or action_input.scope != context.scope):
        raise TaskConflict('Bid normalization requires original QS-A06 sources, target and independent validation')
    reading.check_method_context(context, 'QS-A06')
    mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    if reading._resolver.source_mode != mode:
        raise TaskConflict('Bid normalization changes its original explicit source mode')
    prepare, method_ref = {'normalization': (prepare_bid_normalization, NORMALIZE_METHOD),
        'ranking': (prepare_bid_ranking, RANK_METHOD)}[kind]
    prepared = prepare(context, action_input, reading)
    if prepared['kind'] != 'prepared':
        return prepared
    if prepared['calculation_ref'] != calculation_ref:
        raise TaskConflict('Bid normalization replaces the profile declared original calculation target')
    arithmetic = prepared['input']
    grant = reading.resolve(author_authority_ref)
    now = context.business_time
    if (not isinstance(grant, Authorization) or author_authority_ref not in context.authorization_refs
            or grant.organization_id != reading.organization_id or grant.actor_id != context.actor_id
            or grant.function_ref != context.function_ref or 'QS-A06' not in grant.action_ids
            or not grant.validity.contains(now) or not any(scope_covers(scope, context.scope) for scope in grant.scopes)
            or calculation_ref not in context.visible_refs or calculation_ref not in grant.readable_refs
            or not {ref.key() for ref in arithmetic.source_refs} <= {ref.key() for ref in grant.readable_refs}):
        raise TaskConflict('Bid normalization lacks current original author, target or source read authority')
    for ref in grant.basis_refs:
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or mode == 'formal' and evidence.source_kind == 'synthetic'
                or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
            raise TaskConflict('Bid normalization author lacks current original evidence')
    if mode == 'formal' and any(row['ref']['kind'] == 'Evidence'
            and EvidenceRecord.model_validate(row['projection']).source_kind == 'synthetic'
            for row in reading.evidence()):
        raise TaskConflict('Formal bid normalization cannot use synthetic source evidence')
    methods = reading._methods
    registry_sha256 = methods.content_digest if methods is not None else None
    evidence_before = reading.method_evidence()
    if validate_current(context=context.model_copy(deep=True), action_input=action_input.model_copy(deep=True),
            arithmetic_input=arithmetic.model_copy(deep=True), reading=reading,
            calculation_ref=calculation_ref.model_copy(deep=True)) is not None:
        raise TaskConflict('Bid normalization requires independent current original source validation')
    reading.recheck()
    if (reading.method_evidence() != evidence_before or reading._methods is not methods
            or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Bid source validation changed its registry or executed a method')
    result = reading.calculate(method_ref, arithmetic)
    executions = reading.method_evidence()
    if (len(executions) != len(evidence_before) + 1 or executions[:-1] != evidence_before
            or executions[-1]['method_ref'] != method_ref.model_dump(mode='json')
            or executions[-1]['input'] != arithmetic.model_dump(mode='json')
            or executions[-1]['result'] != result.model_dump(mode='json')
            or executions[-1]['registry_digest'] != registry_sha256
            or reading._methods is not methods or methods is not None and methods.content_digest != registry_sha256):
        raise TaskConflict('Bid normalization lost original registered method invocation evidence')
    reading.recheck()
    if result.kind != 'ok':
        return result.model_dump(mode='python')
    sources = reading.evidence()
    evidence_refs = [ref_type('Evidence').model_validate(row['ref']) for row in sources if row['ref']['kind'] == 'Evidence']
    projection = QSBidMethodResultView(ref=calculation_ref, kind=kind, method_ref=method_ref,
        round_ref=prepared['round_ref'], document_ref=prepared['document_ref'], profile_ref=prepared['profile_ref'],
        bid_refs=[row.bid_ref for row in arithmetic.bids], basis_refs=prepared['basis_refs'], status='ok',
        prices=result.value.prices if kind == 'normalization' else [],
        ranked_groups=result.value.ranked_groups if kind == 'ranking' else [], calculated_at=now,
        author_actor_id=context.actor_id, author_function_ref=context.function_ref,
        author_authority_ref=author_authority_ref, author_action_id='QS-A06', scope=context.scope,
        available_at=now, effective_window={'start':now, 'end':now, 'bounds':'closed_closed'}, evidence_refs=evidence_refs)
    return {'kind':'prepared', 'projection':projection,
        'projection_sha256':task_digest(projection.model_dump(mode='json')),
        'context_sha256':task_digest(context.model_dump(mode='json')),
        'input_sha256':task_digest(action_input.model_dump(mode='json')),
        'source_mode':mode, 'source_reading':sources, 'reading_sha256':task_digest(sources),
        'method_execution':executions[-1], 'method_registry_sha256':registry_sha256,
        'limitations':['Explicit sourced comparison only; original bidder prices remain unchanged.',
            'Unknown eligibility is unresolved; no exclusion, award, contract or cash effect.',
            'Save the original execution and publish at a fresh authorized read point before evaluation.']}
