"""Recover actual original claim/procedure queries while preserving existing duties."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, ref_type
from src.actions.contracts.contractor_claim_objects import (
    ContractorClaimContractView, ContractorClaimProfileView, ContractorClaimProcedureView,
    ContractorChangeProposalView, ContractorClaimView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles import contractor_claim as claim_role
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


CLAIM_CODE = 'contractor-claim-existing-original-claim-continuation'
DEADLINE_CODE = 'contractor-claim-original-notice-deadline-procedure'
_KINDS = {CLAIM_CODE: 'Claim', DEADLINE_CODE: 'ClaimProcedure'}
_TERMINAL = {'recognized', 'withdrawn'}
_INPUT_FIELDS = ('baseline_design_refs', 'instruction_refs', 'issue_refs', 'actual_cost_refs')
_CLAIM_METADATA = {'ref', 'contract_ref', 'change_ref', 'status', 'available_at', 'effective_window', 'evidence_refs'}


@dataclass(frozen=True)
class ContractorClaimConditionReading(ContractorCloseoutConditionReading):
    contract: ActionContract | None = None


def check_contractor_claim_history(check, selected, validate_relation, *, terminal=False):
    source, code = check.source['identity'], check.condition.condition_code
    if (source['action_id'] != 'CONTRACTOR-A09' or source['role'] != 'Contractor' or source['purpose'] != 'action'
            or code not in _KINDS or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != (_KINDS.get(code),)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ContractorClaimConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)
            or terminal and code != CLAIM_CODE):
        raise TaskConflict('Claim recovery requires original typed claim/procedure wait and private Contractor')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.run_id != source['run_id']
            or context.contract_ref != original.contract_ref or context.contract_ref.id != 'CONTRACTOR-A09'
            or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Claim recovery changes original snapshot, scope, time or current read authority')
    reading.check_method_context(context, 'CONTRACTOR-A09')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'CONTRACTOR-A09' or contract.role != 'Contractor':
        raise TaskConflict('Claim recovery lacks its actual registered action contract')

    now = context.business_time

    def evidence(refs, *, at=None):
        if at is not None and (at.clock_ref != now.clock_ref or at.offset > now.offset):
            raise TaskConflict('Claim recovery changes actual evidence-use clock or time')
        for evidence_ref in refs:
            row = reading.resolve(evidence_ref)
            if not isinstance(row, EvidenceRecord) or row.ref != evidence_ref:
                raise TaskConflict('Claim recovery lacks exact original/current Evidence')
            window = row.effective_window
            if window is not None and (window.start.clock_ref != now.clock_ref or window.end.clock_ref != now.clock_ref
                    or window.start.offset > now.offset or at is not None and not window.contains(at)):
                raise TaskConflict('Claim recovery evidence is unavailable or invalid at actual use')

    def read(ref, schema=None, *, at, evidence_at=None):
        row = reading.resolve(ref)
        if getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref or schema is not None and not isinstance(row, schema):
            raise TaskConflict('Claim recovery lacks exact typed original/current sources')
        if hasattr(row, 'available_at') and (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Claim recovery injects unavailable or unrelated-clock evidence')
        evidence(getattr(row, 'evidence_refs', []), at=evidence_at)
        return row

    def keys(refs):
        result = {ref.key() for ref in refs}
        if len(result) != len(refs) or len({ref.key()[:2] for ref in refs}) != len(refs):
            raise TaskConflict('Claim recovery repeats physical source history')
        return result

    def same_claim(before, after):
        return (before.model_dump(exclude=_CLAIM_METADATA) == after.model_dump(exclude=_CLAIM_METADATA)
            and before.contract_ref.key()[:2] == after.contract_ref.key()[:2]
            and before.change_ref.key()[:2] == after.change_ref.key()[:2]
            and (before.status not in _TERMINAL or before.status == after.status))

    versions = []
    for values, invocation in ((raw, original), (current_raw, context)):
        at = original.business_time if terminal else invocation.business_time
        agreement = read(ref_type('Contract').model_validate(values['contract_ref']), ContractorClaimContractView, at=at)
        if agreement.as_of == at:
            evidence(agreement.evidence_refs, at=at)
        profile = read(ref_type('ClaimProfile').model_validate(values['claim_profile_ref']), ContractorClaimProfileView, at=at, evidence_at=at)
        if (agreement.contractor_id != source['organization_id'] or profile.organization_id != source['organization_id']
                or profile.contract_ref != agreement.ref or profile.scope != invocation.scope):
            raise TaskConflict('Claim recovery substitutes original Contractor/contract/profile scope')
        procedure = read(profile.procedure_ref, ContractorClaimProcedureView, at=at, evidence_at=at)
        if procedure.contract_ref != agreement.ref:
            raise TaskConflict('Claim recovery borrows another contract notice procedure')
        if any(row.effective_window.start.clock_ref != at.clock_ref or row.effective_window.end.clock_ref != at.clock_ref
                or not row.effective_window.contains(at) for row in (profile, procedure)):
            raise TaskConflict('Claim recovery changes actual profile/procedure validity at its invocation')
        keys(agreement.claim_refs)
        versions.append(dict(agreement=agreement, profile=profile, procedure=procedure))
    old, current = versions
    if (old['agreement'].ref.key()[:2] != current['agreement'].ref.key()[:2]
            or any(getattr(old['agreement'], field) != getattr(current['agreement'], field)
                for field in ('contractor_id', 'client_id', 'currency', 'decimal_places'))
            or old['profile'].choice != current['profile'].choice
            or old['profile'].ref.key()[:2] != current['profile'].ref.key()[:2]
            or old['procedure'].ref.key()[:2] != current['procedure'].ref.key()[:2]):
        raise TaskConflict('Claim recovery substitutes original contract parties, currency, choice or procedure')
    for field in ('design_refs', 'task_refs', 'claim_refs'):
        before, after = getattr(old['agreement'], field), getattr(current['agreement'], field)
        keys(before); keys(after)
        if not {ref.key()[:2] for ref in before} <= {ref.key()[:2] for ref in after}:
            raise TaskConflict('Claim recovery drops original baseline, work duties or claim history')
    for field in _INPUT_FIELDS:
        before = [Reference.model_validate(ref) for ref in raw[field]]
        after = [Reference.model_validate(ref) for ref in current_raw[field]]
        keys(before); keys(after)
        if not {ref.key()[:2] for ref in before} <= {ref.key()[:2] for ref in after}:
            raise TaskConflict('Claim recovery drops original baseline, instructions, interface issues or incurred cost versions')
        actual = {ref.key()[:2]: ref for ref in after}
        for before_ref in before:
            before_row = read(before_ref, at=original.business_time)
            after_row = read(actual[before_ref.key()[:2]], at=original.business_time if terminal else context.business_time)
            excluded = {'ref', 'contract_ref', 'available_at', 'effective_window', 'evidence_refs'}
            if before_row.model_dump(exclude=excluded) != after_row.model_dump(exclude=excluded):
                raise TaskConflict('Claim recovery rewrites original design content, instruction, issue or incurred costs')
    before_change, after_change = old['profile'].change_ref, current['profile'].change_ref
    if (before_change is None) != (after_change is None):
        raise TaskConflict('Claim recovery changes the original proposal presence')
    if before_change is not None:
        before = read(before_change, ContractorChangeProposalView, at=original.business_time)
        after = read(after_change, ContractorChangeProposalView, at=original.business_time if terminal else context.business_time)
        excluded = {'ref', 'contract_ref', 'design_refs', 'instruction_refs', 'issue_refs',
            'affected_task_refs', 'unaffected_task_refs', 'available_at', 'effective_window', 'evidence_refs'}
        if (before.ref.key()[:2] != after.ref.key()[:2] or before.model_dump(exclude=excluded) != after.model_dump(exclude=excluded)
                or before.contract_ref != old['agreement'].ref or after.contract_ref != current['agreement'].ref):
            raise TaskConflict('Claim recovery rewrites original business, concrete change, affected or unaffected tasks')
        for field in ('design_refs', 'instruction_refs', 'issue_refs', 'affected_task_refs', 'unaffected_task_refs'):
            if {ref.key()[:2] for ref in getattr(before, field)} != {ref.key()[:2] for ref in getattr(after, field)}:
                raise TaskConflict('Claim recovery substitutes original proposal basis or affected/unaffected work partition')
    before_claim, after_claim = old['profile'].claim_ref, current['profile'].claim_ref
    if ((before_claim is None) != (after_claim is None)
            or before_claim is not None and before_claim.key()[:2] != after_claim.key()[:2]):
        raise TaskConflict('Claim recovery substitutes original selected dispute claim')
    # Both emitted waits precede any valuation method call. Authenticate the
    # exact first original gate using the existing processor and old context.
    original_input = contract.validate_input(raw)
    original_gate = claim_role.recheck_original_contractor_claim_wait(original, original_input, reading)
    if (original_gate.get('kind') != 'deferred' or original_gate.get('reason_code') != code
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Claim wait differs from the actual original first claim/procedure gate')
    first_ref, ref = check.condition.object_refs[0], selected.history_ref
    if ref.key()[:2] != first_ref.key()[:2]:
        raise TaskConflict('Claim query substitutes the original physical claim/procedure')
    schema = ContractorClaimView if code == CLAIM_CODE else ContractorClaimProcedureView
    first = read(first_ref, schema, at=original.business_time)
    history = read(ref, schema, at=context.business_time)
    if history.contract_ref.key()[:2] != old['agreement'].ref.key()[:2]:
        raise TaskConflict('Claim query borrows another original physical contract')
    query_contract = read(history.contract_ref, ContractorClaimContractView, at=context.business_time)
    if any(getattr(query_contract, field) != getattr(old['agreement'], field)
            for field in ('contractor_id', 'client_id', 'currency', 'decimal_places')):
        raise TaskConflict('Claim query substitutes original contract parties or money units')
    if code == CLAIM_CODE:
        if not same_claim(first, history) or history.claimant_id != source['organization_id']:
            raise TaskConflict('Claim query rewrites original business, author, proposal or known disposition')
        if history.status not in _TERMINAL:
            return 'waiting', None
        if not terminal and (ref.key() not in keys(current['agreement'].claim_refs)
                or history.contract_ref != current['agreement'].ref):
            raise TaskConflict('Claim query is absent from actual current complete contract history')
    elif ref != current['procedure'].ref or history.contract_ref != current['agreement'].ref:
        raise TaskConflict('Notice query is not the actual current selected contract procedure')
    if (history.effective_window.start.clock_ref != now.clock_ref or history.effective_window.end.clock_ref != now.clock_ref
            or not history.effective_window.contains(now)):
        return 'unavailable', None
    if not history.evidence_refs:
        return 'waiting', None
    if not terminal:
        actual, businesses = {}, set()
        for claim_ref in current['agreement'].claim_refs:
            claim = read(claim_ref, ContractorClaimView, at=context.business_time)
            if claim.contract_ref != current['agreement'].ref or claim.claimant_id != source['organization_id'] or claim.business_key in businesses:
                raise TaskConflict('Claim recovery repeats or borrows current original-business claim history')
            businesses.add(claim.business_key)
            actual[claim_ref.key()[:2]] = claim
        for claim_ref in old['agreement'].claim_refs:
            before = read(claim_ref, ContractorClaimView, at=original.business_time)
            after = actual[claim_ref.key()[:2]]
            if not same_claim(before, after):
                raise TaskConflict('Claim recovery rewrites existing claim identity, proposal or established disposition')
    native_evidence = []
    for evidence_ref in history.evidence_refs:
        row = read(evidence_ref, EvidenceRecord, at=context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Claim query requires actual observed independent native evidence')
        if row.effective_window is not None and (row.effective_window.start.clock_ref != now.clock_ref
                or row.effective_window.end.clock_ref != now.clock_ref or not row.effective_window.contains(now)):
            return 'unavailable', None
        native_evidence.append(row.model_dump(mode='json'))
    current_result = None
    if not terminal:
        current_input = contract.validate_input(current_raw)
        current_result = claim_role.handle_interfaces_and_claims(context, current_input, reading)
        if current_result.get('kind') != 'completed':
            return 'waiting', None
        contract.validate_decision(current_input, current_result['payload'])
        current_result = contract.result_adapter.validate_python(current_result).model_dump(mode='json')
    resolution = dict(schema_version='contractor-claim-history-resolution.v1', condition_code=code,
        disposition=history.status if code == CLAIM_CODE else 'current_authorized_notice_procedure',
        history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_contract=old['agreement'].model_dump(mode='json'), current_contract=current['agreement'].model_dump(mode='json'),
        original_procedure=old['procedure'].model_dump(mode='json'), current_procedure=current['procedure'].model_dump(mode='json'),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'),
        current_result=current_result, sources=reading.evidence(), evidence=native_evidence)
    if validate_relation(source_identity=deepcopy(source), condition_code=code, terminal_claim_history=terminal,
            resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Claim recovery lacks native notice deadline/claim authority/remaining duty/current input authentication')
    return 'ready', resolution


def contractor_original_claim_profile(read_current, validate_relation, condition_code=CLAIM_CODE):
    if condition_code not in _KINDS or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Claim recovery requires original guarded reader and independent native validator')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_contractor_claim_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('CONTRACTOR-A09', condition_code, '2', frozenset({'dependency_change'}), evaluate)
