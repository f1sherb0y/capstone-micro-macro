"""Recheck original Owner transition executions before scheduling fresh A13 work."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.owner_continuation_objects import OwnerContinuationExecutionView, OwnerContinuationProfileView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class OwnerContinuationExecutionConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_refs: tuple[Reference, ...]
    profile_ref: Reference | None = None


def owner_original_continuation_execution_profile(read_current, validate_relation):
    """Register the exact dependency wait emitted by the original A13 processor.

    The application supplies formal current versions of every selected original
    execution, access to the original versions and an independent native query
    validator. Events only prompt reads. Known failure/rejection can permit a
    fresh judgment; no transition, release, resubmission or action executes here.
    The caller holds its current source, authority and original journal boundary.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Owner execution wait requires current sources and independent actual query validation')
    code = 'query_original_continuation_execution'

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'OWN-A13' or source['role'] != 'Owner' or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not old_refs or any(ref.kind != 'ContinuationExecution' for ref in old_refs)
                or len({(ref.kind, ref.id) for ref in old_refs}) != len(old_refs)):
            raise TaskConflict('Owner execution wait changes original task, recipient or selected execution identities')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, OwnerContinuationExecutionConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.execution_refs, tuple)
                or any(not isinstance(ref, Reference) for ref in selected.execution_refs)):
            raise TaskConflict('Owner execution wait requires a typed current authorized reading')
        context, reading, refs = selected.context.model_copy(deep=True), selected.reading, selected.execution_refs
        if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                or context.contract_ref.id != 'OWN-A13' or context.execution_mode != 'llm'
                or reading._resolver.source_mode != 'formal' or context.business_time != check.signal.business_time
                or context.operation_id == source['request_id'] or len(refs) != len(old_refs)
                or len({(ref.kind, ref.id) for ref in refs}) != len(refs)
                or {(ref.kind, ref.id) for ref in refs} != {(ref.kind, ref.id) for ref in old_refs}):
            raise TaskConflict('Owner execution wait changes current formal context or complete original execution selection')
        reading.check_method_context(context, 'OWN-A13')
        current_refs = {(ref.kind, ref.id): ref for ref in refs}
        originals, currents, observed = [], [], {}
        businesses, events = set(), set()
        now = context.business_time
        try:
            for old_ref in old_refs:
                ref = current_refs[(old_ref.kind, old_ref.id)]
                original, current = reading.resolve(old_ref), reading.resolve(ref)
                if (not isinstance(original, OwnerContinuationExecutionView)
                        or not isinstance(current, OwnerContinuationExecutionView)
                        or original.ref.key() != old_ref.key() or current.ref.key() != ref.key()
                        or original.status in {'succeeded', 'failed', 'rejected'} and current.status != original.status
                        or original.core_event_id is not None and current.core_event_id != original.core_event_id
                        or current.organization_id != source['organization_id'] or current.run_id != source['run_id']
                        or any(getattr(original, field) != getattr(current, field) for field in (
                            'organization_id', 'run_id', 'state_ref', 'operation_id', 'business_key',
                            'profile_ref', 'profile_sha256', 'resource_refs', 'scope'))
                        or current.business_key in businesses
                        or len({resource.key() for resource in current.resource_refs}) != len(current.resource_refs)):
                    raise TaskConflict('Owner query changes original operation, profile, scope, resources or execution lineage')
                businesses.add(current.business_key)
                profile = reading.resolve(current.profile_ref)
                if (not isinstance(profile, OwnerContinuationProfileView) or profile.ref != current.profile_ref
                        or profile.state_ref != current.state_ref or profile.organization_id != current.organization_id
                        or profile.scope != current.scope or profile.business_key != current.business_key
                        or content_digest(profile) != current.profile_sha256):
                    raise TaskConflict('Owner query changes the original immutable continuation profile or execution scope')
                if profile.available_at.clock_ref != now.clock_ref or profile.available_at.offset > now.offset:
                    return 'unavailable'
                if (current.available_at.clock_ref != now.clock_ref or current.available_at.offset > now.offset
                        or not current.effective_window.contains(now)):
                    return 'unavailable'
                if current.status == 'succeeded':
                    if current.core_event_id is None or current.core_event_id in events:
                        raise TaskConflict('Owner query omits or repeats an actual transition event')
                    events.add(current.core_event_id)
                elif current.core_event_id is not None:
                    raise TaskConflict('Unconfirmed Owner execution invents an actual transition event')
                if current.status in {'unknown', 'pending'}:
                    return 'waiting'
                for evidence_ref in current.evidence_refs:
                    evidence = reading.resolve(evidence_ref)
                    if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic'
                            or evidence.basis_kind != 'observed'):
                        raise TaskConflict('Owner query lacks independent actual observed execution evidence')
                    if evidence.effective_window is not None and not evidence.effective_window.contains(now):
                        return 'unavailable'
                    observed[evidence.ref.key()] = evidence.model_dump(mode='json')
                originals.append(original.model_dump(mode='json'))
                currents.append(current.model_dump(mode='json'))
            reading.recheck()
            if not observed:
                return 'unavailable'
            if validate_relation(source_identity=deepcopy(source), original_executions=deepcopy(originals),
                    current_executions=deepcopy(currents), evidence=deepcopy(list(observed.values())),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Owner wait lacks authentic complete original native execution query evidence')
            if selected.profile_ref is not None:
                profile = reading.resolve(selected.profile_ref)
                if not isinstance(profile, OwnerContinuationProfileView) or profile.ref != selected.profile_ref:
                    raise TaskConflict('Owner execution recovery lacks the selected actual current profile')
                if any(current['business_key'] == profile.business_key for current in currents):
                    return 'waiting'
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('OWN-A13', code, '2', frozenset({'dependency_change'}), evaluate)
