"""Authenticate original Owner closeout history and preserve residual duties."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.owner_closeout_objects import (
    OwnerCloseoutOrganizationView, OwnerCloseoutCaseView, OwnerCloseoutProjectView,
    OwnerCloseoutStateView, OwnerCloseoutProfileView, OwnerCloseoutContractView, OwnerCloseoutDecisionView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


CODE = 'continue_original_owner_closeout_decision'
_TERMINAL = {'accepted', 'rejected'}
_INPUT_FIELDS = ('handover_refs', 'verification_refs', 'permit_refs', 'defect_refs', 'settlement_refs')
_HISTORY_FIELDS = (*_INPUT_FIELDS, 'contract_refs', 'obligation_refs', 'responsibility_refs', 'decision_history_refs')


def same_closeout_scope(current, original):
    """Permit an explicitly authorized new anchor version in the same work scope."""
    return (current.kind == original.kind and current.ref.key()[:2] == original.ref.key()[:2]
        and {ref.key() for ref in current.coverage_refs} == {ref.key() for ref in original.coverage_refs}
        and len(current.coverage_refs) == len(original.coverage_refs))


@dataclass(frozen=True)
class OwnerCloseoutConditionReading(ContractorCloseoutConditionReading):
    """Exact saved A12 invocation and explicitly selected actual history version."""


def check_owner_closeout_history(check, selected, validate_relation, *, terminal=False):
    source = check.source['identity']
    if (source['action_id'] != 'OWN-A12' or source['role'] != 'Owner' or source['purpose'] != 'action'
            or check.condition.condition_code != CODE or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('OwnerCloseoutDecision',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, OwnerCloseoutConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Owner closeout requires its original typed private decision wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.run_id != source['run_id']
            or context.contract_ref != original.contract_ref or context.contract_ref.id != 'OWN-A12'
            or context.execution_mode != 'llm' or not same_closeout_scope(context.scope, original.scope)
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.scope != original.scope
                or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Owner closeout changes original input, scope, time or current reading authority')
    reading.check_method_context(context, 'OWN-A12')

    def keys(refs):
        result = {ref.key() for ref in refs}
        if len(result) != len(refs) or len({ref.key()[:2] for ref in refs}) != len(refs):
            raise TaskConflict('Owner closeout repeats physical source history')
        return result

    def read(ref, schema=None, *, at=None):
        row = reading.resolve(ref)
        if (schema is not None and not isinstance(row, schema)
                or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref):
            raise TaskConflict('Owner closeout requires exact typed original/current source versions')
        if at is not None and hasattr(row, 'available_at') and (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Owner closeout imports a source unavailable at its recorded time')
        return row

    def authority(ref, actor, function_ref, organization, action, at, scope):
        grant, function = read(ref, Authorization), read(function_ref, RoleAssignment)
        roles = {'OWN': 'Owner', 'CONTRACTOR': 'Contractor', 'QS': 'QS', 'ENGINEER': 'Engineer', 'ARCHITECT': 'Architect', 'GOV': 'Government', 'BANK': 'Bank', 'SUPPLIER': 'Supplier'}
        if (grant.organization_id != organization or grant.actor_id != actor or grant.function_ref != function_ref
                or function.role != roles.get(action.split('-')[0]) or action not in grant.action_ids
                or grant.validity.start.clock_ref != at.clock_ref or grant.validity.end.clock_ref != at.clock_ref
                or not grant.validity.contains(at) or not any(scope_covers(item, scope) for item in grant.scopes)):
            raise TaskConflict('Owner closeout lacks independent historical author/action/scope authority')
        for ref in (*grant.basis_refs, *function.basis_refs):
            read(ref, EvidenceRecord)

    def author(row):
        if (row.authored_at.clock_ref != row.available_at.clock_ref or row.authored_at.offset > row.available_at.offset
                or not row.effective_window.contains(row.authored_at)):
            raise TaskConflict('Owner closeout query rewrites original author timing')
        authority(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at, row.scope)

    versions = []
    for values, invocation in ((raw, original), (current_raw, context)):
        at = original.business_time if terminal else invocation.business_time
        if values['scope_ref'] != invocation.scope.model_dump(mode='json'):
            raise TaskConflict('Owner closeout input replaces its authorized scope anchor')
        anchor = read(invocation.scope.ref, (OwnerCloseoutOrganizationView, OwnerCloseoutCaseView, OwnerCloseoutProjectView), at=at)
        state = read(anchor.closeout_state_ref, OwnerCloseoutStateView, at=at)
        profile = read(state.decision_profile_ref, OwnerCloseoutProfileView, at=at)
        contract = read(profile.contract_ref, OwnerCloseoutContractView, at=at)
        if (state.organization_id != source['organization_id'] or state.scope != invocation.scope
                or state.coverage != 'complete' or state.as_of != at or profile.state_ref != state.ref
                or profile.organization_id != source['organization_id'] or profile.scope != invocation.scope
                or profile.actor_id != invocation.actor_id or profile.function_ref != invocation.function_ref
                or (not terminal or values is raw) and profile.authority_ref not in invocation.authorization_refs
                or contract.owner_id != source['organization_id'] or contract.coverage != 'complete' or contract.as_of != at
                or not scope_covers(invocation.scope, contract.scope) or contract.ref.key() not in keys(state.contract_refs)
                or any(not row.effective_window.contains(at) for row in (state, profile, contract))):
            raise TaskConflict('Owner closeout changes complete original state, profile, contract or author')
        authority(profile.authority_ref, invocation.actor_id, invocation.function_ref, source['organization_id'], 'OWN-A12', at, invocation.scope)
        for field in _INPUT_FIELDS:
            if keys([Reference.model_validate(ref) for ref in values[field]]) != keys(getattr(state, field)):
                raise TaskConflict('Owner closeout input omits original handover, verification, permit, defect or settlement')
        if any(not keys(getattr(contract, field)) <= keys(getattr(state, field)) for field in ('handover_refs', 'settlement_refs', 'defect_refs', 'responsibility_refs')):
            raise TaskConflict('Owner closeout state omits original contract duties or history')
        for field in _HISTORY_FIELDS:
            keys(getattr(state, field))
            for ref in getattr(state, field):
                read(ref, at=at)
        versions.append(dict(state=state, profile=profile, contract=contract))
    old, current = versions
    if (old['state'].ref.key()[:2] != current['state'].ref.key()[:2]
            or old['contract'].ref.key()[:2] != current['contract'].ref.key()[:2]
            or any(getattr(old['contract'], field) != getattr(current['contract'], field) for field in ('owner_id', 'contractor_id', 'currency'))):
        raise TaskConflict('Owner closeout changes original state, contract parties or currency')
    for field in _HISTORY_FIELDS:
        if not {ref.key()[:2] for ref in getattr(old['state'], field)} <= {ref.key()[:2] for ref in getattr(current['state'], field)}:
            raise TaskConflict('Owner closeout drops original defects, debts, continuing responsibility or decision history')
    first, businesses = None, set()
    for ref in old['state'].decision_history_refs:
        row = read(ref, OwnerCloseoutDecisionView, at=original.business_time)
        author(row)
        business = (row.contract_ref.key(), row.business_key)
        if (row.state_ref.key()[:2] != old['state'].ref.key()[:2]
                or row.contract_ref.key() not in keys(old['state'].contract_refs)
                or row.author_organization_id != source['organization_id'] or business in businesses):
            raise TaskConflict('Owner closeout substitutes or duplicates original business history')
        businesses.add(business)
        if business == (old['contract'].ref.key(), old['profile'].business_key):
            first = row
            break
    if first is None or tuple(check.condition.object_refs) != (first.ref,):
        raise TaskConflict('Owner closeout wait differs from original first same-business decision')
    saved_profile = read(first.profile_ref, OwnerCloseoutProfileView, at=original.business_time)
    metadata = {'ref', 'state_ref', 'available_at', 'effective_window'}
    if (saved_profile.state_ref != first.state_ref or saved_profile.contract_ref != first.contract_ref
            or saved_profile.organization_id != first.author_organization_id or saved_profile.scope != first.scope
            or saved_profile.business_key != first.business_key or saved_profile.choice != first.choice
            or first.choice != old['profile'].choice or first.profile_sha256 != content_digest(saved_profile)
            or saved_profile.model_dump(exclude=metadata) != old['profile'].model_dump(exclude=metadata)):
        raise TaskConflict('Owner closeout wait rewrites original decision content or profile digest')
    ref = selected.history_ref
    if ref.key()[:2] != first.ref.key()[:2]:
        raise TaskConflict('Owner closeout query replaces original physical decision')
    history = read(ref, OwnerCloseoutDecisionView, at=context.business_time)
    author(history)
    excluded = {'ref', 'state_ref', 'contract_ref', 'status', 'available_at', 'effective_window', 'evidence_refs'}
    if (first.model_dump(exclude=excluded) != history.model_dump(exclude=excluded)
            or history.state_ref.key()[:2] != first.state_ref.key()[:2]
            or history.contract_ref.key()[:2] != first.contract_ref.key()[:2]
            or first.status in _TERMINAL and first.status != history.status):
        raise TaskConflict('Owner closeout query rewrites immutable decision or known disposition')
    if not history.effective_window.contains(context.business_time):
        return 'unavailable', None
    if history.status not in _TERMINAL or not history.evidence_refs:
        return 'waiting', None
    if not terminal and ref.key() not in keys(current['state'].decision_history_refs):
        raise TaskConflict('Owner closeout query is absent from actual current decision history')
    evidence = []
    for evidence_ref in history.evidence_refs:
        row = read(evidence_ref, EvidenceRecord)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Owner closeout requires independently observed actual history evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    resolution = dict(schema_version='owner-closeout-history-resolution.v1', condition_code=CODE,
        disposition=history.status, history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_state=old['state'].model_dump(mode='json'), current_state=current['state'].model_dump(mode='json'),
        sources=reading.evidence(), evidence=evidence)
    if validate_relation(source_identity=deepcopy(source), condition_code=CODE, terminal_owner_closeout_history=terminal,
            resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Owner closeout lacks native decision/remaining duty/current authority authentication')
    if not terminal and current['profile'].business_key == first.business_key:
        return 'waiting', None
    return 'ready', resolution


def owner_original_closeout_profile(read_current, validate_relation, condition_code=CODE):
    if condition_code != CODE or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Owner closeout requires original guarded history selection and independent validator')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_owner_closeout_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('OWN-A12', CODE, '2', frozenset({'dependency_change'}), evaluate)
