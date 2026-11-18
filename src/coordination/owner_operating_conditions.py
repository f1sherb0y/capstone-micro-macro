"""Authenticate original owner-operating queries before fresh OWN-A15 judgments."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.owner_operating_objects import (
    OwnerOperatingExecutionView, OwnerOperatingObservationView, OwnerOperatingProfileView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class OwnerOperatingExecutionConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_ref: Reference
    profile_ref: Reference | None = None


def owner_original_operating_execution_profile(read_current, validate_relation):
    """Resolve the exact original A15 dependency wait using actual query evidence.

    Application callbacks hold the current source/authority/journal guard and
    provide authorized original/current execution versions plus independent
    native validation. A terminal query permits a fresh judgment only. It does
    not revise preferences, replace commitments, change budgets or settle dues.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Owner operating wait requires actual current sources and independent native query validation')
    code = 'query_original_owner_operating_execution'

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'OWN-A15' or source['role'] != 'Owner' or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'OwnerOperatingExecution'):
            raise TaskConflict('Owner operating wait changes original action, recipient or selected execution')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, OwnerOperatingExecutionConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.execution_ref, Reference)):
            raise TaskConflict('Owner operating wait requires typed current authorized execution sources')
        context, reading, ref = (selected.context.model_copy(deep=True), selected.reading,
            selected.execution_ref.model_copy(deep=True))
        old_ref, now = old_refs[0], context.business_time
        if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                or context.contract_ref.id != 'OWN-A15' or context.execution_mode != 'llm'
                or reading._resolver.source_mode != 'formal' or now != check.signal.business_time
                or context.operation_id == source['request_id'] or (ref.kind, ref.id) != (old_ref.kind, old_ref.id)
                or not {ref.key(), old_ref.key()} <= {item.key() for item in context.visible_refs}):
            raise TaskConflict('Owner operating query substitutes formal context or original execution identity')
        reading.check_method_context(context, 'OWN-A15')
        try:
            original, current = reading.resolve(old_ref), reading.resolve(ref)
            if (not isinstance(original, OwnerOperatingExecutionView) or not isinstance(current, OwnerOperatingExecutionView)
                    or original.ref.key() != old_ref.key() or current.ref.key() != ref.key()
                    or current.organization_id != source['organization_id'] or current.run_id != source['run_id']
                    or any(getattr(original, field) != getattr(current, field) for field in (
                        'organization_id', 'run_id', 'business_key', 'profile_ref', 'profile_sha256', 'scope'))
                    or original.status in {'succeeded', 'failed', 'rejected'} and current.status != original.status):
                raise TaskConflict('Owner operating query changes original operating business, scope, profile or final outcome')
            if (len({item.key() for item in current.applied_observation_refs}) != len(current.applied_observation_refs)
                    or not {item.key() for item in original.applied_observation_refs}
                        <= {item.key() for item in current.applied_observation_refs}):
                raise TaskConflict('Owner operating query repeats or drops an already applied observation version')
            profile = reading.resolve(current.profile_ref)
            if (not isinstance(profile, OwnerOperatingProfileView)
                    or profile.ref.key() != current.profile_ref.key()
                    or profile.organization_id != current.organization_id
                    or profile.scope != current.scope
                    or profile.business_key != current.business_key or content_digest(profile) != current.profile_sha256):
                raise TaskConflict('Owner operating query lacks the original immutable authorized operation profile')
            if (current.available_at.clock_ref != now.clock_ref or current.available_at.offset > now.offset
                    or not current.effective_window.contains(now)):
                return 'unavailable'
            if current.status in {'unknown', 'pending'}:
                return 'waiting'
            applied, events, physical = [], set(), set()
            for observation_ref in current.applied_observation_refs:
                observation = reading.resolve(observation_ref)
                identity = (observation_ref.kind, observation_ref.id)
                if (not isinstance(observation, OwnerOperatingObservationView)
                        or observation.ref.key() != observation_ref.key()
                        or observation.recipient_organization_id != source['organization_id']
                        or observation.event_id in events or identity in physical):
                    raise TaskConflict('Owner operating query substitutes or repeats an actually applied private observation')
                events.add(observation.event_id)
                physical.add(identity)
                if (any(point.clock_ref != now.clock_ref for point in (
                            observation.observed_at, observation.authored_at, observation.available_at))
                        or not observation.observed_at.offset <= observation.authored_at.offset
                            <= observation.available_at.offset <= now.offset
                        or not observation.effective_window.contains(observation.authored_at)):
                    return 'unavailable'
                applied.append(observation.model_dump(mode='json'))
            observations = {}
            for evidence_ref in current.evidence_refs:
                evidence = reading.resolve(evidence_ref)
                if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic'
                        or evidence.basis_kind != 'observed'):
                    raise TaskConflict('Owner operating query lacks actual observed native execution evidence')
                if evidence.effective_window is not None and not evidence.effective_window.contains(now):
                    return 'unavailable'
                observations[evidence.ref.key()] = evidence.model_dump(mode='json')
            if not observations:
                return 'unavailable'
            reading.recheck()
            if validate_relation(source_identity=deepcopy(source), original_execution=original.model_dump(mode='json'),
                    current_execution=current.model_dump(mode='json'), profile=profile.model_dump(mode='json'),
                    applied_observations=deepcopy(applied), evidence=deepcopy(list(observations.values())), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Owner operating wait lacks authentic complete original native query coverage')
            if selected.profile_ref is not None:
                current_profile = reading.resolve(selected.profile_ref)
                if (not isinstance(current_profile, OwnerOperatingProfileView) or current_profile.ref != selected.profile_ref
                        or current_profile.organization_id != source['organization_id'] or current_profile.scope != context.scope):
                    raise TaskConflict('Owner operating recovery lacks the selected actual current business profile')
                if current_profile.business_key == current.business_key:
                    return 'waiting'
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('OWN-A15', code, '1', frozenset({'dependency_change'}), evaluate)
