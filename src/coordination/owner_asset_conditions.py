"""Authenticate original asset-operation queries before fresh OWN-A14 judgments."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.owner_asset_objects import OwnerAssetExecutionView, OwnerAssetOperationProfileView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class OwnerAssetExecutionConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_ref: Reference
    profile_ref: Reference | None = None


def owner_original_asset_execution_profile(read_current, validate_relation):
    """Resolve the exact original A14 dependency wait using actual query evidence.

    Application callbacks hold the current source/authority/journal guard and
    provide authorized original/current execution versions plus independent
    native validation. A terminal query permits a fresh judgment only. It does
    not establish asset disposition, revenue, receivable, cash receipt or use.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Owner asset wait requires actual current sources and independent native query validation')
    code = 'query_original_asset_operation'

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'OWN-A14' or source['role'] != 'Owner' or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'AssetOperationExecution'):
            raise TaskConflict('Owner asset wait changes original action, recipient or selected execution')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, OwnerAssetExecutionConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.execution_ref, Reference)):
            raise TaskConflict('Owner asset wait requires typed current authorized execution sources')
        context, reading, ref = (selected.context.model_copy(deep=True), selected.reading,
            selected.execution_ref.model_copy(deep=True))
        old_ref, now = old_refs[0], context.business_time
        if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                or context.contract_ref.id != 'OWN-A14' or context.execution_mode != 'llm'
                or reading._resolver.source_mode != 'formal' or now != check.signal.business_time
                or context.operation_id == source['request_id'] or (ref.kind, ref.id) != (old_ref.kind, old_ref.id)
                or not {ref.key(), old_ref.key()} <= {item.key() for item in context.visible_refs}):
            raise TaskConflict('Owner asset query substitutes formal context or original execution identity')
        reading.check_method_context(context, 'OWN-A14')
        try:
            original, current = reading.resolve(old_ref), reading.resolve(ref)
            if (not isinstance(original, OwnerAssetExecutionView) or not isinstance(current, OwnerAssetExecutionView)
                    or original.ref.key() != old_ref.key() or current.ref.key() != ref.key()
                    or current.organization_id != source['organization_id'] or current.run_id != source['run_id']
                    or any(getattr(original, field) != getattr(current, field) for field in (
                        'organization_id', 'run_id', 'asset_ref', 'business_key', 'profile_ref', 'profile_sha256', 'scope'))
                    or original.status in {'succeeded', 'failed', 'rejected'} and current.status != original.status):
                raise TaskConflict('Owner asset query changes original asset, business, scope, profile or final outcome')
            profile = reading.resolve(current.profile_ref)
            if (not isinstance(profile, OwnerAssetOperationProfileView)
                    or profile.ref.key() != current.profile_ref.key()
                    or profile.organization_id != current.organization_id
                    or profile.asset_ref.key() != current.asset_ref.key() or profile.scope != current.scope
                    or profile.business_key != current.business_key or content_digest(profile) != current.profile_sha256):
                raise TaskConflict('Owner asset query lacks the original immutable authorized operation profile')
            if (current.available_at.clock_ref != now.clock_ref or current.available_at.offset > now.offset
                    or not current.effective_window.contains(now)):
                return 'unavailable'
            if current.status in {'unknown', 'pending'}:
                return 'waiting'
            observations = {}
            for evidence_ref in current.evidence_refs:
                evidence = reading.resolve(evidence_ref)
                if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic'
                        or evidence.basis_kind != 'observed'):
                    raise TaskConflict('Owner asset query lacks actual observed native execution evidence')
                if evidence.effective_window is not None and not evidence.effective_window.contains(now):
                    return 'unavailable'
                observations[evidence.ref.key()] = evidence.model_dump(mode='json')
            if not observations:
                return 'unavailable'
            reading.recheck()
            if validate_relation(source_identity=deepcopy(source), original_execution=original.model_dump(mode='json'),
                    current_execution=current.model_dump(mode='json'), profile=profile.model_dump(mode='json'),
                    evidence=deepcopy(list(observations.values())), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Owner asset wait lacks authentic complete original native query coverage')
            if selected.profile_ref is not None:
                current_profile = reading.resolve(selected.profile_ref)
                if not isinstance(current_profile, OwnerAssetOperationProfileView) or current_profile.ref != selected.profile_ref:
                    raise TaskConflict('Owner asset recovery lacks the selected actual current business profile')
                if current_profile.business_key == current.business_key:
                    return 'waiting'
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('OWN-A14', code, '1', frozenset({'dependency_change'}), evaluate)
