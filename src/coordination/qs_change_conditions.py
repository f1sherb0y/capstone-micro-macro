"""Rejudge the original withdrawn change claim after actual resubmission."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, ScopeRef, ref_type
from src.actions.contracts.qs_change_objects import (
    ChangeAuthored, QSChangeClaimView, QSChangeContractView, QSChangeInstructionView,
    QSChangeLineView, QSChangeStatementView, QSChangeResultView, QSChangeEntitlementView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'qs.change.original_claim_submitted'
_FIELDS = frozenset({'scope', 'claim_or_change_ref', 'contract_ref', 'instruction_ref',
    'evidence_refs', 'entitlement_ref', 'valuation_result_ref'})
_PREFIXES = {'Owner': 'OWN-', 'Contractor': 'CONTRACTOR-', 'Supplier': 'SUPPLIER-',
    'Architect': 'ARCHITECT-', 'Engineer': 'ENGINEER-', 'QS': 'QS-', 'Government': 'GOV-', 'Bank': 'BANK-'}


@dataclass(frozen=True)
class QSChangeConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict


def qs_original_change_claim_profile(read_current, validate_relation):
    """Require native resubmission/history authentication; ready grants no rights."""
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('QS change recovery requires actual sources and native resubmission validation')

    def identities(refs):
        keys = {ref.key()[:2] for ref in refs}
        if len(keys) != len(refs):
            raise TaskConflict('QS change recovery duplicates a physical source')
        return keys

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'QS-A07' or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'ChangeClaim'):
            raise TaskConflict('QS change recovery substitutes original claim wait or recipient')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, QSChangeConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.original_action_input, dict)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('QS change recovery requires typed current reading and original snapshot input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        try:
            old_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            if (set(old_input) != _FIELDS or set(action_input) != _FIELDS or task_digest(old_input) != source['input_sha256']
                    or context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A07'
                    or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                    or old_input['scope'] != action_input['scope']):
                raise TaskConflict('QS change recovery changes original snapshot, scope or current invocation')
            scope, now = TypeAdapter(ScopeRef).validate_python(action_input['scope']), context.business_time
            if context.scope != scope:
                raise TaskConflict('QS change recovery changes original valuation coverage')
            reading.check_method_context(context, 'QS-A07')
            proof_rows, proof_refs = [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or row.scope != scope:
                    raise TaskConflict('QS change recovery lacks an exact scoped original/current source')
                proof_rows.append(row)
                return row

            versions = []
            for raw in (old_input, action_input):
                claim = read(ref_type('ChangeClaim').model_validate(raw['claim_or_change_ref']), QSChangeClaimView)
                contract = read(ref_type('Contract').model_validate(raw['contract_ref']), QSChangeContractView)
                instruction_ref = None if raw['instruction_ref'] is None else ref_type('Instruction').model_validate(raw['instruction_ref'])
                if (claim.contract_ref != contract.ref or claim.instruction_ref != instruction_ref
                        or claim.claimant_id != claim.author_actor_id or claim.claimant_id not in contract.party_ids
                        or contract.valuation_organization_id != source['organization_id']):
                    raise TaskConflict('QS change recovery substitutes contract, instruction, claimant or organization')
                versions.append((claim, contract))
            original, old_contract = versions[0]; claim, contract = versions[1]
            if (original.ref != old_refs[0] or original.ref.key()[:2] != claim.ref.key()[:2]
                    or old_contract.ref.key()[:2] != contract.ref.key()[:2] or original.status != 'withdrawn'
                    or any(getattr(original, field) != getattr(claim, field) for field in ('claimant_id', 'author_actor_id', 'period', 'basis'))
                    or any(getattr(old_contract, field) != getattr(contract, field) for field in (
                        'party_ids', 'currency', 'decimal_places', 'valuation_actor_id', 'valuation_organization_id'))
                    or contract.valuation_actor_id != context.actor_id or contract.valuation_function_ref != context.function_ref
                    or contract.valuation_authority_ref not in context.authorization_refs):
                raise TaskConflict('QS change recovery substitutes original parties, period, price terms or QS authority')
            if claim.status != 'submitted':
                return 'waiting'
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in (claim, contract)):
                return 'unavailable'
            grant, function = reading.resolve(contract.valuation_authority_ref), reading.resolve(context.function_ref)
            if (not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment)
                    or function.role != 'QS' or function.function_ref != context.function_ref
                    or grant.actor_id != context.actor_id or grant.function_ref != context.function_ref
                    or grant.organization_id != source['organization_id'] or 'QS-A07' not in grant.action_ids
                    or not grant.validity.contains(now) or not any(scope_covers(s, scope) for s in grant.scopes)):
                raise TaskConflict('QS change recovery lacks the currently appointed QS valuation authority')
            proof_refs.extend([*grant.basis_refs, *function.basis_refs])

            histories = {}

            def retain(old, current, fields):
                if old.ref.key()[:2] != current.ref.key()[:2] or any(getattr(old, field) != getattr(current, field) for field in fields):
                    raise TaskConflict('QS change resubmission rewrites known original valuation facts')

            authored = ('author_actor_id', 'author_function_ref', 'author_authority_ref', 'author_action_id', 'authored_at')
            for field, schema, facts in (
                    ('line_refs', QSChangeLineView, ('calculation_line', *authored)),
                    ('prior_statement_refs', QSChangeStatementView, ('sequence', 'calculation_ref', 'period_delta', *authored))):
                old_set, current_set = getattr(original, field), getattr(claim, field)
                if not identities(old_set) <= identities(current_set):
                    raise TaskConflict('QS change resubmission drops known lines or cumulative valuation history')
                old_rows = {ref.key()[:2]: read(ref, schema) for ref in old_set}
                current_rows = {ref.key()[:2]: read(ref, schema) for ref in current_set}
                for key, old in old_rows.items():
                    retain(old, current_rows[key], facts)
                for rows, related_claim, related_contract in ((old_rows, original, old_contract), (current_rows, claim, contract)):
                    for row in rows.values():
                        if (row.contract_ref != related_contract.ref or row.claim_ref.key()[:2] != related_claim.ref.key()[:2]
                                or (field == 'line_refs' and row.claim_ref != related_claim.ref)):
                            raise TaskConflict('QS change history borrows another contract or claim')
                        if field == 'line_refs':
                            proof_refs.extend([row.calculation_line.quantity_delta.basis_ref, row.calculation_line.unit_rate.basis_ref])
                        else:
                            result = read(row.calculation_ref, QSChangeResultView)
                            if result.contract_ref != row.contract_ref or result.claim_ref != row.claim_ref:
                                raise TaskConflict('QS change prior valuation substitutes its statement claim version')
                            proof_refs.append(row.period_delta.basis_ref)
                histories[field] = {'original': [row.model_dump(mode='json') for row in old_rows.values()],
                    'current': [row.model_dump(mode='json') for row in current_rows.values()]}

            for field, kind, schema in (('instruction_ref', 'Instruction', QSChangeInstructionView),
                    ('valuation_result_ref', 'MethodResult', QSChangeResultView),
                    ('entitlement_ref', 'EntitlementDecision', QSChangeEntitlementView)):
                pair = []
                for raw, related_claim, related_contract in ((old_input, original, old_contract), (action_input, claim, contract)):
                    row = None if raw[field] is None else read(ref_type(kind).model_validate(raw[field]), schema)
                    if row is not None and (row.contract_ref != related_contract.ref or row.claim_ref != related_claim.ref):
                        raise TaskConflict('QS change successor substitutes its current instruction, result or entitlement')
                    pair.append(row)
                old, current = pair
                if field == 'instruction_ref':
                    if (old is None) != (current is None):
                        raise TaskConflict('QS change recovery replaces its original instruction selection')
                    if old is not None:
                        retain(old, current, ('instruction_authority_ref', *authored))
                # A fresh independently saved valuation/entitlement may be
                # selected. Both old and current records remain visible for
                # native lineage validation; selection cannot erase history.
                histories[field] = {'original': None if old is None else old.model_dump(mode='json'),
                    'current': None if current is None else current.model_dump(mode='json')}
            old_evidence = [ref_type('Evidence').model_validate(raw) for raw in old_input['evidence_refs']]
            current_evidence = [ref_type('Evidence').model_validate(raw) for raw in action_input['evidence_refs']]
            identities(old_evidence); identities(current_evidence)
            if not {ref.key() for ref in old_evidence} <= {ref.key() for ref in current_evidence}:
                raise TaskConflict('QS change recovery drops original supplied evidence')
            proof_refs.extend([*old_evidence, *current_evidence])
            for row in proof_rows:
                proof_refs.extend(row.evidence_refs)
                if not isinstance(row, ChangeAuthored):
                    continue
                grant, function = reading.resolve(row.author_authority_ref), reading.resolve(row.author_function_ref)
                if (not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment)
                        or function.function_ref != row.author_function_ref or grant.actor_id != row.author_actor_id
                        or grant.function_ref != row.author_function_ref or row.author_action_id not in grant.action_ids
                        or not row.author_action_id.startswith(_PREFIXES[function.role])
                        or not row.effective_window.contains(row.authored_at) or not grant.validity.contains(row.authored_at)
                        or row.authored_at.clock_ref != now.clock_ref or row.available_at.clock_ref != now.clock_ref
                        or row.authored_at.offset > row.available_at.offset or row.available_at.offset > now.offset
                        or not any(scope_covers(granted, scope) for granted in grant.scopes)):
                    raise TaskConflict('QS change recovery lacks original/current authorship authority')
                proof_refs.extend([*grant.basis_refs, *function.basis_refs])
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('QS change recovery requires actual observed native resubmission evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), original_action_input=old_input, action_input=action_input,
                    original_claim=original.model_copy(deep=True), claim=claim.model_copy(deep=True),
                    original_contract=old_contract.model_copy(deep=True), contract=contract.model_copy(deep=True),
                    valuation_history=deepcopy(histories), evidence=deepcopy(list(evidence.values())),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('QS change recovery lacks native resubmission and complete original/current history validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('QS-A07', _CODE, '1', frozenset({'dependency_change'}), evaluate)
