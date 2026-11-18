"""Authenticate actual same-business asset operation and preserve original source history."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, walk_references
from src.actions.contracts.owner_asset_objects import OwnerAssetView, OwnerAssetOperationProfileView, OwnerAssetExecutionView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.owner_continuation_terminal import OwnerContinuationTerminalReading
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


EXECUTION_CODE = 'query_original_asset_operation'
_TERMINAL = {'succeeded', 'failed', 'rejected'}
_PROFILE_METADATA = {'ref', 'asset_ref', 'available_at', 'effective_window'}


@dataclass(frozen=True)
class OwnerAssetTerminalReading(OwnerContinuationTerminalReading):
    """Original exact asset input with an independently selected actual execution version."""


def check_owner_asset_terminal(check, selected, validate_relation, *, terminal=False):
    source = check.source['identity']
    if (terminal is not True or source['action_id'] != 'OWN-A14' or source['role'] != 'Owner'
            or source['purpose'] != 'action' or check.condition.condition_code != EXECUTION_CODE
            or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('AssetOperationExecution',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, OwnerAssetTerminalReading) or not isinstance(selected.reading, ActionReadView)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not callable(validate_relation)):
        raise TaskConflict('Asset terminal archive requires original same-business wait and typed actual query sources')
    context, original_context, reading = selected.context, selected.original_context, selected.reading
    action_input = selected.original_action_input
    raw = action_input.model_dump(mode='json')
    if (task_digest(raw) != source['input_sha256'] or raw != selected.action_input.model_dump(mode='json')
            or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or original_context.operation_id != source['request_id'] or context.operation_id != source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original_context.contract_ref
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'OWN-A14'
            or context.scope != original_context.scope or context.actor_id != original_context.actor_id
            or context.function_ref != original_context.function_ref or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Asset terminal archive replaces original input, private actor or current read authorization')
    reading.check_method_context(context, 'OWN-A14')

    def read(ref, schema, *, original=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            raise TaskConflict('Asset terminal archive lacks exact typed original/query sources')
        at = original_context.business_time if original else context.business_time
        if hasattr(row, 'available_at') and (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Asset terminal archive injects a source unavailable at original/query time')
        return row

    asset = read(action_input.asset_ref, OwnerAssetView, original=True)
    profile = read(action_input.operating_profile_ref, OwnerAssetOperationProfileView, original=True)
    if (asset.coverage != 'complete' or asset.producer != 'core' or asset.as_of != original_context.business_time
            or profile.organization_id != source['organization_id'] or profile.asset_ref != asset.ref
            or profile.actor_id != original_context.actor_id or profile.function_ref != original_context.function_ref
            or profile.authority_ref not in original_context.authorization_refs or profile.scope != original_context.scope
            or not scope_covers(asset.scope, original_context.scope)
            or not scope_covers(original_context.scope, profile.scope_choice.scope_ref)):
        raise TaskConflict('Asset terminal archive changes original complete core asset, profile or affected scope')
    for field in ('right_refs', 'market_refs', 'transaction_refs', 'receipt_refs'):
        refs = getattr(action_input, field)
        if len({ref.key() for ref in refs}) != len(refs) or {ref.key() for ref in refs} != {ref.key() for ref in getattr(asset, field)}:
            raise TaskConflict('Asset terminal archive drops original rights/market/transaction/receipt history')
    grant = read(profile.authority_ref, Authorization)
    function = read(profile.function_ref, RoleAssignment)
    if (grant.organization_id != source['organization_id'] or grant.actor_id != original_context.actor_id
            or grant.function_ref != original_context.function_ref or 'OWN-A14' not in grant.action_ids
            or grant.validity.start.clock_ref != original_context.business_time.clock_ref
            or grant.validity.end.clock_ref != original_context.business_time.clock_ref
            or not grant.validity.contains(original_context.business_time) or function.role != 'Owner'
            or not any(scope_covers(scope, original_context.scope) for scope in grant.scopes)):
        raise TaskConflict('Asset terminal archive lacks original independent Owner action authority')
    businesses, first = set(), None
    for ref in asset.execution_refs:
        execution = read(ref, OwnerAssetExecutionView, original=True)
        if (execution.asset_ref.key()[:2] != asset.ref.key()[:2] or execution.organization_id != source['organization_id']
                or execution.run_id != source['run_id'] or execution.business_key in businesses):
            raise TaskConflict('Asset terminal archive duplicates or substitutes original asset/run/business history')
        businesses.add(execution.business_key)
        if execution.business_key == profile.business_key:
            first = execution
            break
    if first is None or tuple(check.condition.object_refs) != (first.ref,):
        raise TaskConflict('Asset terminal archive differs from original first same-business execution gate')
    executed_profile = read(first.profile_ref, OwnerAssetOperationProfileView, original=True)
    if (executed_profile.asset_ref != first.asset_ref or executed_profile.organization_id != first.organization_id
            or executed_profile.scope != first.scope or executed_profile.business_key != first.business_key
            or content_digest(executed_profile) != first.profile_sha256
            or executed_profile.model_dump(exclude=_PROFILE_METADATA) != profile.model_dump(exclude=_PROFILE_METADATA)):
        raise TaskConflict('Asset terminal archive rewrites original executed profile digest/business content')
    if selected.execution_ref.key()[:2] != first.ref.key()[:2]:
        raise TaskConflict('Asset terminal archive replaces original physical execution identity')
    current = read(selected.execution_ref, OwnerAssetExecutionView)
    if (any(getattr(first, field) != getattr(current, field) for field in
            ('organization_id', 'run_id', 'asset_ref', 'business_key', 'profile_ref', 'profile_sha256', 'scope'))
            or first.status in _TERMINAL and first.status != current.status):
        raise TaskConflict('Asset terminal archive changes original operation content or actual terminal outcome')
    now = context.business_time
    if (current.effective_window.start.clock_ref != now.clock_ref or current.effective_window.end.clock_ref != now.clock_ref
            or not current.effective_window.contains(now)):
        return 'unavailable', None
    if current.status not in _TERMINAL or not current.evidence_refs:
        return 'waiting', None
    evidence = []
    for ref in current.evidence_refs:
        row = read(ref, EvidenceRecord)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Asset terminal archive requires actual independently observed execution query evidence')
        if row.effective_window is not None and (row.effective_window.start.clock_ref != now.clock_ref
                or row.effective_window.end.clock_ref != now.clock_ref or not row.effective_window.contains(now)):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    for ref in (*walk_references(action_input), *walk_references(asset)):
        reading.resolve(ref)
    resolution = dict(schema_version='owner-asset-execution-resolution.v1', disposition=current.status,
        execution=current.model_dump(mode='json'), original_action_input=raw, action_input=raw,
        original_context=original_context.model_dump(mode='json'), context=context.model_dump(mode='json'),
        sources=reading.evidence(), evidence=evidence)
    if validate_relation(source_identity=deepcopy(source), condition_code=EXECUTION_CODE, terminal_asset_execution=True,
            original_context=original_context.model_copy(deep=True), original_action_input=raw,
            context=context.model_copy(deep=True), resolution=deepcopy(resolution), reading=reading) is not True:
        raise TaskConflict('Asset terminal archive lacks native original asset/right/transaction/current authority authentication')
    return 'ready', resolution
