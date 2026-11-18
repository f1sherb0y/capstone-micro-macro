"""Authenticate original Bank learning state and actual same-business terminal outcomes."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.bank_learning_objects import (
    BankLearningOrganizationView, BankLearningCaseView, BankLearningProjectView,
    BankLearningStateView, BankLearningProfileView, BankLearningExecutionView,
    BankVerifiedOutcomeView, BankJudgmentView, BankHistoricalInformationView,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.bank_debt_conditions import BankDebtConditionReading
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


EXECUTION_CODE = 'query_original_bank_learning_execution'
_TERMINAL = {'succeeded', 'failed', 'rejected'}
_PROFILE_METADATA = {'ref', 'state_ref', 'available_at', 'effective_window'}


@dataclass(frozen=True)
class BankLearningTerminalReading(BankDebtConditionReading):
    queried_execution_refs: tuple[Reference, ...] = ()


def check_bank_learning_terminal(check, selected, validate_relation, *, terminal=False):
    source = check.source['identity']
    if (terminal is not True or source['action_id'] != 'BANK-A12' or source['role'] != 'Bank'
            or source['purpose'] != 'action' or check.condition.condition_code != EXECUTION_CODE
            or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('BankLearningExecution',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, BankLearningTerminalReading) or not isinstance(selected.reading, ActionReadView)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not callable(validate_relation)):
        raise TaskConflict('Bank learning terminal query requires original wait and authenticated typed reading')
    context, original_context, reading = selected.context, selected.original_context, selected.reading
    raw = selected.original_action_input.model_dump(mode='json')
    if (raw != selected.action_input.model_dump(mode='json') or task_digest(raw) != source['input_sha256']
            or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or original_context.operation_id != source['request_id'] or context.operation_id != source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original_context.contract_ref
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'BANK-A12'
            or context.scope != original_context.scope or context.actor_id != original_context.actor_id
            or context.function_ref != original_context.function_ref or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Bank learning terminal query replaces original snapshot, private firm or current authorization')
    reading.check_method_context(context, 'BANK-A12')
    rows = {}

    def read(ref, schema, *, at=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            raise TaskConflict('Bank learning terminal query lacks exact original/current sources')
        now = at or context.business_time
        if hasattr(row, 'available_at') and (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset):
            raise TaskConflict('Bank learning terminal query introduces posterior sources into original knowledge')
        rows[ref.key()] = row
        return row

    anchor = read(original_context.scope.ref, (BankLearningOrganizationView, BankLearningCaseView, BankLearningProjectView),
        at=original_context.business_time)
    state = read(anchor.learning_state_ref, BankLearningStateView, at=original_context.business_time)
    profile = read(state.profile_ref, BankLearningProfileView, at=original_context.business_time)
    if (state.organization_id != source['organization_id'] or profile.organization_id != source['organization_id']
            or state.scope != original_context.scope or profile.scope != original_context.scope
            or state.coverage != 'complete' or state.as_of != original_context.business_time
            or profile.state_ref != state.ref or profile.actor_id != original_context.actor_id
            or profile.function_ref != original_context.function_ref
            or profile.authority_ref not in original_context.authorization_refs):
        raise TaskConflict('Bank learning terminal query replaces original complete private state or decision profile')
    for field, state_field in (('observation_refs', 'observation_refs'), ('prior_judgment_refs', 'judgment_refs'),
            ('outcome_refs', 'outcome_refs'), ('allowed_strategy_refs', 'allowed_strategy_refs')):
        refs = getattr(selected.original_action_input, field)
        if len({ref.key() for ref in refs}) != len(refs) or {ref.key() for ref in refs} != {ref.key() for ref in getattr(state, state_field)}:
            raise TaskConflict('Bank learning terminal query changes original complete input/state histories')
    grant = read(profile.authority_ref, Authorization)
    function = read(profile.function_ref, RoleAssignment)
    if (grant.organization_id != source['organization_id'] or grant.actor_id != original_context.actor_id
            or grant.function_ref != original_context.function_ref or 'BANK-A12' not in grant.action_ids
            or grant.validity.start.clock_ref != original_context.business_time.clock_ref
            or grant.validity.end.clock_ref != original_context.business_time.clock_ref
            or not grant.validity.contains(original_context.business_time) or function.role != 'Bank'
            or not any(scope_covers(scope, original_context.scope) for scope in grant.scopes)):
        raise TaskConflict('Bank learning terminal query lacks original independent action authority')
    history = [read(ref, BankLearningExecutionView, at=original_context.business_time) for ref in state.execution_refs]
    if (len({row.business_key for row in history}) != len(history)
            or any(row.organization_id != source['organization_id'] or row.run_id != source['run_id'] for row in history)):
        raise TaskConflict('Bank learning terminal query duplicates or substitutes original execution history')
    original = next((row for row in history if row.business_key == profile.business_key), None)
    if original is None or tuple(check.condition.object_refs) != (original.ref,):
        raise TaskConflict('Only the original first same-business learning execution gate may be archived')
    executed_profile = read(original.profile_ref, BankLearningProfileView, at=original_context.business_time)
    if (executed_profile.organization_id != original.organization_id or executed_profile.scope != original.scope
            or executed_profile.business_key != original.business_key
            or content_digest(executed_profile) != original.profile_sha256
            or executed_profile.model_dump(exclude=_PROFILE_METADATA) != profile.model_dump(exclude=_PROFILE_METADATA)):
        raise TaskConflict('Bank learning terminal query changes original executed profile content/business digest')
    if len(selected.queried_execution_refs) != 1 or selected.queried_execution_refs[0].key()[:2] != original.ref.key()[:2]:
        raise TaskConflict('Bank learning terminal query replaces original execution identity')
    execution = read(selected.queried_execution_refs[0], BankLearningExecutionView)
    if (any(getattr(original, field) != getattr(execution, field) for field in
            ('organization_id', 'run_id', 'business_key', 'profile_ref', 'profile_sha256', 'scope'))
            or original.status in _TERMINAL and execution.status != original.status
            or len({ref.key() for ref in execution.applied_outcome_refs}) != len(execution.applied_outcome_refs)
            or not {ref.key() for ref in original.applied_outcome_refs} <= {ref.key() for ref in execution.applied_outcome_refs}):
        raise TaskConflict('Bank learning terminal query rewrites original business/disposition or drops applied outcomes')
    now = context.business_time
    if (execution.effective_window.start.clock_ref != now.clock_ref or execution.effective_window.end.clock_ref != now.clock_ref
            or not execution.effective_window.contains(now)):
        return 'unavailable', None
    if execution.status not in _TERMINAL or not execution.evidence_refs:
        return 'waiting', None
    evidence = []
    for ref in execution.evidence_refs:
        row = read(ref, EvidenceRecord)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Bank learning terminal query requires actual observed execution evidence')
        if row.effective_window is not None and (row.effective_window.start.clock_ref != now.clock_ref
                or row.effective_window.end.clock_ref != now.clock_ref or not row.effective_window.contains(now)):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    physical_outcomes = set()
    for ref in execution.applied_outcome_refs:
        outcome = read(ref, BankVerifiedOutcomeView)
        judgment = read(outcome.judgment_ref, BankJudgmentView)
        key = (outcome.physical_outcome_key, outcome.judgment_ref.key())
        if (key in physical_outcomes or outcome.lender_id != source['organization_id']
                or judgment.lender_id != source['organization_id'] or judgment.author_organization_id != source['organization_id']
                or content_digest(judgment) != outcome.judgment_sha256
                or outcome.dimension_ref != judgment.dimension_ref or outcome.event_code != judgment.event_code
                or outcome.evaluation_window != judgment.evaluation_window
                or judgment.authored_at.clock_ref != judgment.evaluation_window.start.clock_ref
                or judgment.authored_at.offset > judgment.evaluation_window.start.offset
                or not judgment.information_refs
                or len(judgment.information_refs) != len(judgment.information_sha256)):
            raise TaskConflict('Bank learning terminal query rewrites applied original outcomes/judgments')
        physical_outcomes.add(key)
        for information_ref, digest in zip(judgment.information_refs, judgment.information_sha256):
            information = read(information_ref, BankHistoricalInformationView, at=judgment.authored_at)
            if (information.recipient_organization_id != source['organization_id'] or information.content_sha256 != digest
                    or information.known_at.clock_ref != judgment.authored_at.clock_ref
                    or information.known_at.offset > judgment.authored_at.offset):
                raise TaskConflict('Bank learning terminal query injects posterior information into original judgment')
    resolution = dict(schema_version='bank-learning-execution-resolution.v1', disposition=execution.status,
        execution=execution.model_dump(mode='json'), original_action_input=raw, action_input=raw,
        original_context=original_context.model_dump(mode='json'), context=context.model_dump(mode='json'),
        sources=[row.model_dump(mode='json') for row in rows.values()], evidence=evidence)
    if validate_relation(source_identity=deepcopy(source), condition_code=EXECUTION_CODE, terminal_learning_execution=True,
            original_context=original_context.model_copy(deep=True), original_action_input=raw,
            context=context.model_copy(deep=True), resolution=deepcopy(resolution), reading=reading) is not True:
        raise TaskConflict('Bank learning terminal query lacks native original history/current authority authentication')
    return 'ready', resolution
