"""Rejudge final-account waits after authentic original execution queries."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, ScopeRef, ref_type
from src.actions.contracts.qs_final_account_objects import (
    QSFinalContractView, QSFinalProfileView, QSFinalExecutionView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'query_original_final_account_execution'
_FIELDS = frozenset({'scope', 'contract_ref', 'determined_change_refs', 'certificate_refs',
    'payment_receipt_refs', 'unresolved_claim_refs', 'reconciliation_result_ref'})
_HISTORIES = (('determined_change_refs', 'determined_change_refs', 'EntitlementDecision'),
    ('certificate_refs', 'all_certificate_refs', 'Certificate'),
    ('payment_receipt_refs', 'receipt_refs', 'PaymentReceipt'),
    ('unresolved_claim_refs', 'unresolved_claim_refs', 'ChangeClaim'))


@dataclass(frozen=True)
class QSFinalAccountConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict
    original_context: ActionContext
    settlement_sources: list[dict] | None = None
    unavailable_targets: list[dict] | None = None


def qs_original_final_account_execution_profile(read_current, validate_relation):
    """A terminal query allows fresh judgment, never replay of its business key."""
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('QS final-account recovery requires actual sources and native execution/history validation')

    def evaluate(check):
        source, waited = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'QS-A09' or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(waited) != 1 or waited[0].kind != 'FinalAccountExecution'):
            raise TaskConflict('QS final-account recovery replaces its original execution wait or recipient')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, QSFinalAccountConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.original_action_input, dict)
                or not isinstance(selected.action_input, dict) or not isinstance(selected.original_context, ActionContext)):
            raise TaskConflict('QS final-account recovery requires typed current sources and original snapshot input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        original_context = selected.original_context.model_copy(deep=True)
        try:
            old_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            if (set(old_input) != _FIELDS or set(action_input) != _FIELDS
                    or task_digest(old_input) != source['input_sha256'] or old_input['scope'] != action_input['scope']
                    or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
                    or original_context.run_id != source['run_id'] or original_context.operation_id != source['request_id']
                    or original_context.contract_ref.kind != 'ActionContract' or original_context.contract_ref.id != 'QS-A09'
                    or context.scope != original_context.scope
                    or context.business_time.clock_ref != original_context.business_time.clock_ref
                    or context.business_time.offset < original_context.business_time.offset
                    or context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A09'
                    or context.execution_mode != 'llm' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']):
                raise TaskConflict('QS final-account recovery changes original snapshot, scope or current invocation')
            scope = TypeAdapter(ScopeRef).validate_python(action_input['scope'])
            if context.scope != scope:
                raise TaskConflict('QS final-account recovery changes original settlement coverage')
            reading.check_method_context(context, 'QS-A09')
            rows, versions, histories = [], [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or row.scope != scope:
                    raise TaskConflict('QS final-account recovery lacks exact scoped original/current sources')
                rows.append(row)
                return row

            for raw, invocation in ((old_input, original_context), (action_input, context)):
                contract_ref = ref_type('Contract').model_validate(raw['contract_ref'])
                contract = read(contract_ref, QSFinalContractView)
                profile = read(contract.final_profile_ref, QSFinalProfileView)
                if (contract.valuation_organization_id != source['organization_id'] or contract.valuation_actor_id != invocation.actor_id
                        or contract.valuation_function_ref != invocation.function_ref
                        or profile.contract_ref != contract.ref or profile.actor_id != invocation.actor_id
                        or profile.function_ref != invocation.function_ref
                        or profile.author_organization_id != source['organization_id']):
                    raise TaskConflict('QS final-account recovery changes original valuation party or profile')
                if raw is old_input and (contract.as_of != invocation.business_time or contract.coverage != 'complete'
                        or any(row.available_at.clock_ref != invocation.business_time.clock_ref
                            or row.available_at.offset > invocation.business_time.offset for row in (contract, profile))):
                    raise TaskConflict('QS final-account recovery substitutes sources unavailable at the original wait')
                history = {}
                for input_field, contract_field, kind in _HISTORIES:
                    refs = [ref_type(kind).model_validate(value) for value in raw[input_field]]
                    declared = getattr(contract, contract_field)
                    if len({ref.key() for ref in refs}) != len(refs) or set(refs) != set(declared):
                        raise TaskConflict('QS final-account recovery input omits its complete declared contract history')
                    history[input_field] = [ref.model_dump(mode='json') for ref in refs]
                executions = [read(ref, QSFinalExecutionView) for ref in contract.execution_refs]
                if (len({row.ref.key()[:2] for row in executions}) != len(executions)
                        or len({row.business_key for row in executions}) != len(executions)
                        or any(row.contract_ref.key()[:2] != contract.ref.key()[:2] or row.run_id != source['run_id']
                            or row.available_at.clock_ref != invocation.business_time.clock_ref
                            or row.available_at.offset > invocation.business_time.offset for row in executions)):
                    raise TaskConflict('QS final-account recovery repeats or substitutes original execution identities')
                versions.append((contract, profile, executions)); histories.append(history)
            old_contract, old_profile, originals = versions[0]
            contract, profile, executions = versions[1]
            if (old_contract.ref.key()[:2] != contract.ref.key()[:2]
                    or any(getattr(old_contract, field) != getattr(contract, field) for field in (
                        'party_ids', 'payer_id', 'beneficiary_id', 'currency', 'decimal_places', 'base_component_key',
                        'retention_fraction', 'retention_cap', 'valuation_actor_id', 'valuation_organization_id'))):
                raise TaskConflict('QS final-account recovery rewrites original contract parties, valuation or monetary basis')
            old_execution = next((row for row in originals if row.ref == waited[0]), None)
            current_execution = next((row for row in executions if row.ref.key()[:2] == waited[0].key()[:2]), None)
            if old_execution is None or current_execution is None:
                raise TaskConflict('QS final-account recovery drops its original waited execution')
            first_wait = next((row for row in originals if row.business_key == old_profile.business_key
                or row.status in {'pending', 'unknown'}), None)
            if first_wait is None or first_wait.ref != waited[0]:
                raise TaskConflict('QS final-account recovery replaces the original processor first execution wait')
            old_index = {row.ref.key()[:2]: row for row in originals}
            current_index = {row.ref.key()[:2]: row for row in executions}
            if not old_index.keys() <= current_index.keys():
                raise TaskConflict('QS final-account recovery drops original business execution history')
            for key, original in old_index.items():
                current = current_index[key]
                if (any(getattr(original, field) != getattr(current, field) for field in (
                        'run_id', 'contract_ref', 'business_key', 'profile_ref', 'profile_sha256', 'reconciliation_result_ref'))
                        or original.status in {'succeeded', 'failed', 'rejected'} and current.status != original.status):
                    raise TaskConflict('QS final-account query rewrites original execution content or a known terminal outcome')
                original_profile = read(original.profile_ref, QSFinalProfileView)
                if (original.profile_sha256 != content_digest(original_profile)
                        or original_profile.business_key != original.business_key
                        or original_profile.contract_ref != original.contract_ref
                        or original_profile.scope != original.scope
                        or original_profile.author_organization_id != source['organization_id']):
                    raise TaskConflict('QS final-account query changes the original execution profile digest or business key')
                if (original_profile.available_at.clock_ref != original_context.business_time.clock_ref
                        or original_profile.available_at.offset > original_context.business_time.offset):
                    raise TaskConflict('QS final-account query introduces a profile unavailable at the original wait')
                if original.business_key == old_profile.business_key:
                    metadata = {'ref', 'contract_ref', 'available_at', 'effective_window'}
                    if original_profile.model_dump(exclude=metadata) != old_profile.model_dump(exclude=metadata):
                        raise TaskConflict('QS final-account original wait rewrites content under its existing business key')
            if old_execution.business_key != old_profile.business_key and old_execution.status not in {'pending', 'unknown'}:
                raise TaskConflict('QS final-account wait does not match the original processor execution query')
            if (current_execution.status in {'pending', 'unknown'} or profile.business_key in {row.business_key for row in executions}
                    or any(row.status in {'pending', 'unknown'} for row in executions)):
                return 'waiting'
            now = context.business_time
            if (contract.as_of != now or contract.coverage != 'complete'
                    or any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                        or not row.effective_window.contains(now) for row in (contract, profile, current_execution))):
                return 'unavailable'
            grant, function = reading.resolve(profile.authority_ref), reading.resolve(profile.function_ref)
            if (not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment)
                    or function.role != 'QS' or function.function_ref != profile.function_ref
                    or profile.function_ref != context.function_ref or contract.valuation_function_ref != context.function_ref
                    or profile.authority_ref not in context.authorization_refs or grant.actor_id != context.actor_id
                    or grant.organization_id != source['organization_id'] or grant.function_ref != profile.function_ref
                    or 'QS-A09' not in grant.action_ids or not grant.validity.contains(now)
                    or not any(scope_covers(s, scope) for s in grant.scopes)):
                raise TaskConflict('QS final-account recovery lacks current original QS judgment authority')
            evidence = {}
            proof_refs = [*grant.basis_refs, *function.basis_refs, *[ref for row in rows for ref in row.evidence_refs]]
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('QS final-account recovery requires actual observed query/history evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), original_action_input=old_input, action_input=action_input,
                    original_contract=old_contract.model_copy(deep=True), contract=contract.model_copy(deep=True),
                    original_profile=old_profile.model_copy(deep=True), profile=profile.model_copy(deep=True),
                    original_executions=[row.model_dump(mode='json') for row in originals],
                    current_executions=[row.model_dump(mode='json') for row in executions],
                    settlement_history=dict(original=histories[0], current=histories[1]),
                    settlement_sources=deepcopy(selected.settlement_sources),
                    unavailable_targets=deepcopy(selected.unavailable_targets),
                    evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('QS final-account recovery lacks native query coverage and complete settlement history validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('QS-A09', _CODE, '2', frozenset({'dependency_change'}), evaluate)
