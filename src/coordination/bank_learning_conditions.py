"""Authenticate original Bank learning executions before fresh A12 judgments."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.bank_learning_objects import BankLearningExecutionView, BankVerifiedOutcomeView, BankLearningProfileView
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class BankLearningExecutionConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_ref: Reference
    profile_ref: Reference | None = None


def bank_original_learning_execution_profile(read_current, validate_relation):
    """Resolve the exact query wait emitted by the original BANK-A12 processor.

    Current formal sources must retain original business/profile identity and
    already applied outcome records. An independent native validator confirms
    actual query coverage; a signal never becomes learning or model evidence.
    Read under the application's current source/authorization boundary. Ready
    permits only a freshly prepared judgment, with no repeated policy update.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Bank learning wait requires current authorized sources and actual native query validation')
    code = 'query_original_bank_learning_execution'

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'BANK-A12' or source['role'] != 'Bank' or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'BankLearningExecution'):
            raise TaskConflict('Bank learning wait changes original task, recipient or execution selection')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, BankLearningExecutionConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.execution_ref, Reference)):
            raise TaskConflict('Bank learning wait requires typed current authorized execution sources')
        context, reading, ref = selected.context.model_copy(deep=True), selected.reading, selected.execution_ref.model_copy(deep=True)
        if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                or context.contract_ref.id != 'BANK-A12' or context.execution_mode != 'llm'
                or reading._resolver.source_mode != 'formal' or context.business_time != check.signal.business_time
                or context.operation_id == source['request_id']
                or (ref.kind, ref.id) != (old_refs[0].kind, old_refs[0].id)):
            raise TaskConflict('Bank learning wait substitutes current context or original execution identity')
        reading.check_method_context(context, 'BANK-A12')
        now = context.business_time
        try:
            original, current = reading.resolve(old_refs[0]), reading.resolve(ref)
            if (not isinstance(original, BankLearningExecutionView) or not isinstance(current, BankLearningExecutionView)
                    or original.ref.key() != old_refs[0].key() or current.ref.key() != ref.key()
                    or current.organization_id != source['organization_id'] or current.run_id != source['run_id']
                    or any(getattr(original, field) != getattr(current, field) for field in (
                        'organization_id', 'run_id', 'business_key', 'profile_ref', 'profile_sha256', 'scope'))
                    or len({item.key() for item in current.applied_outcome_refs}) != len(current.applied_outcome_refs)
                    or not {item.key() for item in original.applied_outcome_refs}
                        <= {item.key() for item in current.applied_outcome_refs}):
                raise TaskConflict('Bank learning query changes original profile, business, scope or already applied outcomes')
            if original.status in {'succeeded', 'failed', 'rejected'} and current.status != original.status:
                raise TaskConflict('Bank learning query changes original terminal execution disposition')
            executed_profile = reading.resolve(current.profile_ref)
            if (not isinstance(executed_profile, BankLearningProfileView) or executed_profile.ref != current.profile_ref
                    or executed_profile.organization_id != current.organization_id or executed_profile.scope != current.scope
                    or executed_profile.business_key != current.business_key
                    or content_digest(executed_profile) != current.profile_sha256):
                raise TaskConflict('Bank learning query substitutes the original execution profile or scope')
            if (executed_profile.available_at.clock_ref != now.clock_ref
                    or executed_profile.available_at.offset > now.offset):
                return 'unavailable'
            if (current.available_at.clock_ref != now.clock_ref or current.available_at.offset > now.offset
                    or not current.effective_window.contains(now)):
                return 'unavailable'
            if current.status in {'unknown', 'pending'}:
                return 'waiting'
            outcomes, observations, physical_outcomes = [], [], set()
            for outcome_ref in current.applied_outcome_refs:
                outcome = reading.resolve(outcome_ref)
                if (not isinstance(outcome, BankVerifiedOutcomeView) or outcome.ref.key() != outcome_ref.key()
                        or outcome.lender_id != source['organization_id']
                        or (outcome.physical_outcome_key, outcome.judgment_ref.key()) in physical_outcomes):
                    raise TaskConflict('Bank learning query substitutes or repeats an actually applied original outcome')
                physical_outcomes.add((outcome.physical_outcome_key, outcome.judgment_ref.key()))
                if outcome.available_at.clock_ref != now.clock_ref or outcome.available_at.offset > now.offset:
                    return 'unavailable'
                outcomes.append(outcome.model_dump(mode='json'))
            for evidence_ref in current.evidence_refs:
                evidence = reading.resolve(evidence_ref)
                if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic'
                        or evidence.basis_kind != 'observed'):
                    raise TaskConflict('Bank learning query lacks independent actual observed execution evidence')
                if evidence.effective_window is not None and not evidence.effective_window.contains(now):
                    return 'unavailable'
                observations.append(evidence.model_dump(mode='json'))
            reading.recheck()
            if not observations:
                return 'waiting'
            if validate_relation(source_identity=deepcopy(source), original_execution=original.model_dump(mode='json'),
                    current_execution=current.model_dump(mode='json'), applied_outcomes=deepcopy(outcomes),
                    evidence=deepcopy(observations), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Bank learning wait lacks authentic complete original native query coverage')
            if selected.profile_ref is not None:
                profile = reading.resolve(selected.profile_ref)
                if (not isinstance(profile, BankLearningProfileView) or profile.ref != selected.profile_ref
                        or profile.organization_id != source['organization_id'] or profile.scope != context.scope):
                    raise TaskConflict('Bank learning recovery lacks the selected actual current profile')
                if profile.business_key == current.business_key:
                    return 'waiting'
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('BANK-A12', code, '2', frozenset({'dependency_change'}), evaluate)
