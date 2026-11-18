"""Authenticate actual original Owner transition disposition and retain its sources."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.actions.contracts.owner_continuation_objects import (
    OwnerContinuationProfileView, OwnerContinuationStateView, OwnerContinuationExecutionView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


EXECUTION_CODE = 'query_original_continuation_execution'
_TERMINAL = {'succeeded', 'failed', 'rejected'}
_PROFILE_METADATA = {'ref', 'state_ref', 'available_at', 'effective_window'}


@dataclass(frozen=True)
class OwnerContinuationTerminalReading:
    context: ActionContext
    reading: ActionReadView
    original_context: ActionContext
    original_action_input: object
    action_input: object
    execution_ref: Reference


def check_owner_continuation_terminal(check, selected, validate_relation, *, terminal=False):
    source = check.source['identity']
    if (terminal is not True or source['action_id'] != 'OWN-A13' or source['role'] != 'Owner'
            or source['purpose'] != 'action' or check.condition.condition_code != EXECUTION_CODE
            or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('ContinuationExecution',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, OwnerContinuationTerminalReading) or not isinstance(selected.reading, ActionReadView)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.execution_ref, Reference) or not callable(validate_relation)):
        raise TaskConflict('Owner terminal archive requires original same-business wait and typed actual query reading')
    context, original_context, reading = selected.context, selected.original_context, selected.reading
    action_input = selected.original_action_input
    raw = action_input.model_dump(mode='json')
    if (task_digest(raw) != source['input_sha256'] or raw != selected.action_input.model_dump(mode='json')
            or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or original_context.operation_id != source['request_id'] or context.operation_id != source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original_context.contract_ref
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'OWN-A13'
            or context.scope != original_context.scope or context.actor_id != original_context.actor_id
            or context.function_ref != original_context.function_ref or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Owner terminal archive replaces original snapshot, private owner or current authority')
    reading.check_method_context(context, 'OWN-A13')
    rows = {}

    def read(ref, schema, *, original=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            raise TaskConflict('Owner terminal archive lacks exact typed original/query sources')
        at = original_context.business_time if original else context.business_time
        if hasattr(row, 'available_at') and (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Owner terminal archive injects sources unavailable at original/query time')
        rows[ref.key()] = row
        return row

    profile = read(action_input.continuation_profile_ref, OwnerContinuationProfileView, original=True)
    state = read(profile.state_ref, OwnerContinuationStateView, original=True)
    if (profile.organization_id != source['organization_id'] or state.organization_id != source['organization_id']
            or profile.actor_id != original_context.actor_id or profile.function_ref != original_context.function_ref
            or profile.authority_ref not in original_context.authorization_refs
            or profile.scope != original_context.scope or state.scope != original_context.scope
            or action_input.scope_ref != original_context.scope or state.coverage != 'complete'
            or state.producer != 'core' or state.as_of != original_context.business_time
            or {ref.key() for ref in profile.retained_obligation_refs} != {ref.key() for ref in state.obligation_refs}):
        raise TaskConflict('Owner terminal archive replaces original complete state, profile or retained debt')
    for field in ('risk_refs', 'contract_refs', 'resource_refs', 'obligation_refs'):
        refs = getattr(action_input, field)
        if len({ref.key() for ref in refs}) != len(refs) or {ref.key() for ref in refs} != {ref.key() for ref in getattr(state, field)}:
            raise TaskConflict('Owner terminal archive drops original risk, contracts, resources or obligations')
    grant = read(profile.authority_ref, Authorization)
    function = read(profile.function_ref, RoleAssignment)
    if (grant.organization_id != source['organization_id'] or grant.actor_id != original_context.actor_id
            or grant.function_ref != original_context.function_ref or 'OWN-A13' not in grant.action_ids
            or grant.validity.start.clock_ref != original_context.business_time.clock_ref
            or grant.validity.end.clock_ref != original_context.business_time.clock_ref
            or not grant.validity.contains(original_context.business_time) or function.role != 'Owner'
            or not any(scope_covers(scope, original_context.scope) for scope in grant.scopes)):
        raise TaskConflict('Owner terminal archive lacks original independent action authority')
    history = []
    business, events = set(), set()
    for ref in state.execution_refs:
        row = read(ref, OwnerContinuationExecutionView, original=True)
        if (row.organization_id != source['organization_id'] or row.run_id != source['run_id']
                or row.state_ref.key()[:2] != state.ref.key()[:2] or row.business_key in business
                or len({ref.key() for ref in row.resource_refs}) != len(row.resource_refs)
                or not {ref.key() for ref in row.resource_refs} <= {ref.key() for ref in state.resource_refs}
                or row.status == 'succeeded' and (row.core_event_id is None or row.core_event_id in events)
                or row.status != 'succeeded' and row.core_event_id is not None):
            raise TaskConflict('Owner terminal archive changes original run/business/resource/core-event history')
        business.add(row.business_key)
        if row.core_event_id is not None:
            events.add(row.core_event_id)
        history.append(row)
        # The processor returns at the first matching business before reading
        # later history. Keep precisely that original first waiting gate.
        if row.business_key == profile.business_key:
            break
    first = next((row for row in history if row.business_key == profile.business_key), None)
    if first is None or tuple(check.condition.object_refs) != (first.ref,):
        raise TaskConflict('Owner terminal archive differs from original first same-business execution gate')
    executed_profile = read(first.profile_ref, OwnerContinuationProfileView, original=True)
    if (executed_profile.state_ref != first.state_ref or executed_profile.organization_id != first.organization_id
            or executed_profile.scope != first.scope or executed_profile.business_key != first.business_key
            or content_digest(executed_profile) != first.profile_sha256
            or executed_profile.model_dump(exclude=_PROFILE_METADATA) != profile.model_dump(exclude=_PROFILE_METADATA)):
        raise TaskConflict('Owner terminal archive changes original executed profile digest or business content')
    if selected.execution_ref.key()[:2] != first.ref.key()[:2]:
        raise TaskConflict('Owner terminal archive replaces original execution identity')
    execution = read(selected.execution_ref, OwnerContinuationExecutionView)
    if (any(getattr(first, field) != getattr(execution, field) for field in
            ('organization_id', 'run_id', 'state_ref', 'operation_id', 'business_key', 'profile_ref', 'profile_sha256', 'resource_refs', 'scope'))
            or first.status in _TERMINAL and first.status != execution.status
            or first.core_event_id is not None and first.core_event_id != execution.core_event_id):
        raise TaskConflict('Owner terminal archive rewrites original operation/resources or known disposition')
    now = context.business_time
    if (execution.effective_window.start.clock_ref != now.clock_ref or execution.effective_window.end.clock_ref != now.clock_ref
            or not execution.effective_window.contains(now)):
        return 'unavailable', None
    if execution.status not in _TERMINAL or not execution.evidence_refs:
        return 'waiting', None
    if (execution.status == 'succeeded' and (execution.core_event_id is None
            or execution.core_event_id in events and execution.core_event_id != first.core_event_id)
            or execution.status != 'succeeded' and execution.core_event_id is not None):
        raise TaskConflict('Owner terminal archive invents or repeats actual core execution effects')
    evidence = []
    for ref in execution.evidence_refs:
        row = read(ref, EvidenceRecord)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Owner terminal archive requires independently observed original execution evidence')
        if row.effective_window is not None and (row.effective_window.start.clock_ref != now.clock_ref
                or row.effective_window.end.clock_ref != now.clock_ref or not row.effective_window.contains(now)):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    for ref in (*walk_references(action_input), *walk_references(state)):
        reading.resolve(ref)
    resolution = dict(schema_version='owner-continuation-execution-resolution.v1', disposition=execution.status,
        execution=execution.model_dump(mode='json'), original_action_input=raw, action_input=raw,
        original_context=original_context.model_dump(mode='json'), context=context.model_dump(mode='json'),
        sources=reading.evidence(), evidence=evidence)
    if validate_relation(source_identity=deepcopy(source), condition_code=EXECUTION_CODE, terminal_continuation_execution=True,
            original_context=original_context.model_copy(deep=True), original_action_input=raw,
            context=context.model_copy(deep=True), resolution=deepcopy(resolution), reading=reading) is not True:
        raise TaskConflict('Owner terminal archive lacks native original execution/debt/resource/current authority authentication')
    return 'ready', resolution
