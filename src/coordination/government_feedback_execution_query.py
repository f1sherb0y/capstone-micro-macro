"""Native execution lookup separates original-result reconciliation from fresh feedback work."""
from copy import deepcopy

from pydantic import Field, model_validator

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, StrictRecord, TextId, TimePoint, ref_type, walk_references
from src.actions.contracts.government_feedback_objects import GovFeedbackExecutionView, GovObservationProfileView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


EXECUTION_CODE = 'query_original_government_feedback_execution'
_TERMINAL = {'succeeded', 'failed', 'rejected'}
_METADATA = {'ref', 'execution_refs', 'available_at', 'effective_window', 'as_of'}


class GovernmentFeedbackExecutionQueryRecord(StrictRecord):
    query_id: TextId
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    execution_ref: ref_type('GovernmentFeedbackExecution')
    business_key: TextId
    profile_sha256: Digest
    queried_at: TimePoint
    execution: GovFeedbackExecutionView
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)

    @model_validator(mode='after')
    def original_execution(self):
        if (self.execution.ref.key()[:2] != self.execution_ref.key()[:2]
                or self.execution.run_id != self.run_id or self.execution.organization_id != self.organization_id
                or self.execution.business_key != self.business_key or self.execution.profile_sha256 != self.profile_sha256
                or len({ref.key() for ref in self.evidence_refs}) != len(self.evidence_refs)):
            raise ValueError('Execution query replaces original run/agency/business/profile or repeats evidence')
        return self


def check_feedback_execution(check, selected, validate_relation, *, terminal=False):
    """Return readiness plus authenticated resolution; terminal failure is preserved as failure."""
    from src.coordination.government_feedback_conditions import GovernmentFeedbackConditionReading, _FIELDS
    source = check.source['identity']
    if (source['action_id'] != 'GOV-A12' or source['role'] != 'Government' or source['purpose'] != 'action'
            or check.condition.condition_code != EXECUTION_CODE or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('GovernmentFeedbackExecution',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, GovernmentFeedbackConditionReading)):
        raise TaskConflict('Feedback execution query replaces original execution wait or agency')
    reading, context, original_context = selected.reading, selected.context, selected.original_context
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (set(raw) != _FIELDS or set(current_raw) != _FIELDS or task_digest(raw) != source['input_sha256']
            or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or context.run_id != source['run_id'] or context.contract_ref.id != 'GOV-A12' or context.execution_mode != 'llm'
            or reading._resolver.source_mode != 'formal' or reading.organization_id != source['organization_id']
            or context.scope != original_context.scope or raw['scope'] != current_raw['scope']
            or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and raw != current_raw):
        raise TaskConflict('Feedback execution query changes original snapshot/scope or selected invocation')
    rows = []

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Feedback execution query lacks exact original/current source history')
        rows.append(row)
        return row

    profiles, histories = [], []
    for action_input, invocation in ((raw, original_context), (current_raw, context)):
        profile = read(ref_type('ObservationProfile').model_validate(action_input['observation_profile_ref']), GovObservationProfileView)
        if (profile.organization_id != source['organization_id'] or profile.scope != invocation.scope
                or profile.actor_id != invocation.actor_id or profile.function_ref != invocation.function_ref
                or profile.coverage != 'complete' or (not terminal or action_input is raw) and profile.as_of != invocation.business_time):
            raise TaskConflict('Feedback execution query replaces complete original agency/actor/profile snapshot')
        history = [read(ref, GovFeedbackExecutionView) for ref in profile.execution_refs]
        if (len({row.ref.key()[:2] for row in history}) != len(history)
                or len({row.business_key for row in history}) != len(history)
                or any(row.organization_id != source['organization_id'] or row.run_id != source['run_id']
                    or row.available_at.clock_ref != invocation.business_time.clock_ref
                    or row.available_at.offset > invocation.business_time.offset for row in history)):
            raise TaskConflict('Feedback execution query duplicates or borrows business execution history')
        profiles.append(profile)
        histories.append(history)
    old_profile, profile = profiles
    old_history, history = histories
    first = next((row for row in old_history if row.business_key == old_profile.business_key
        or row.status in {'unknown', 'pending'}), None)
    if first is None or tuple(check.condition.object_refs) != (first.ref,):
        raise TaskConflict('Feedback execution query differs from original first same-business/uncertain execution gate')
    original = read(first.profile_ref, GovObservationProfileView)
    if (original.organization_id != first.organization_id or original.scope != first.scope
            or original.business_key != first.business_key or first.profile_sha256 != content_digest(original)):
        raise TaskConflict('Feedback execution query rewrites original executed profile agency, scope, business or digest')
    if (original.available_at.clock_ref != original_context.business_time.clock_ref
            or original.available_at.offset > original_context.business_time.offset):
        raise TaskConflict('Feedback execution query introduces a profile unavailable at the original waiting point')
    same_business = first.business_key == old_profile.business_key
    if same_business and original.model_dump(exclude=_METADATA) != old_profile.model_dump(exclude=_METADATA):
        raise TaskConflict('Feedback execution query changes content under original business identity')
    if (old_profile.ref.key()[:2] != profile.ref.key()[:2]
            or old_profile.model_dump(exclude=_METADATA) != profile.model_dump(exclude=_METADATA)
            or raw['policy_control_profile_ref'] != current_raw['policy_control_profile_ref']
            or any(raw[field] != current_raw[field] for field in ('feedback_refs', 'visible_statistic_refs'))
            or not {row.ref.key()[:2] for row in old_history} <= {row.ref.key()[:2] for row in history}):
        raise TaskConflict('Feedback execution query rewrites original business content or drops observed history')
    if selected.execution_query is None:
        return 'waiting', None
    query = GovernmentFeedbackExecutionQueryRecord.model_validate(deepcopy(selected.execution_query))
    if (query.source_identity_sha256 != task_digest(source) or query.run_id != source['run_id']
            or query.organization_id != source['organization_id'] or query.execution_ref != first.ref
            or query.business_key != first.business_key or query.profile_sha256 != first.profile_sha256
            or query.queried_at != context.business_time or query.execution.profile_ref != first.profile_ref
            or query.execution.scope != first.scope or query.execution.available_at.clock_ref != context.business_time.clock_ref
            or query.execution.available_at.offset > context.business_time.offset):
        raise TaskConflict('Feedback execution lookup replaces original execution identity, profile or actual observation time')
    current_by_id = {row.ref.key()[:2]: row for row in history}
    for before in old_history:
        after = current_by_id[before.ref.key()[:2]]
        if (any(getattr(before, field) != getattr(after, field) for field in
                ('business_key', 'run_id', 'organization_id', 'profile_ref', 'profile_sha256', 'scope'))
                or before.status in _TERMINAL and before.status != after.status):
            raise TaskConflict('Feedback execution query rewrites retained execution disposition/content')
    if first.status in _TERMINAL and query.execution.status != first.status:
        raise TaskConflict('Feedback execution query rewrites original terminal disposition')
    if query.execution.status not in _TERMINAL:
        return 'waiting', None
    if terminal:
        if not same_business:
            raise TaskConflict('Only the same original business execution can terminally resolve this wait')
    else:
        if same_business:
            return 'waiting', None
        if current_by_id[first.ref.key()[:2]] != query.execution:
            raise TaskConflict('Current execution history conflicts with actual native query')
        if any(row.business_key == profile.business_key or row.status not in _TERMINAL for row in history):
            return 'waiting', None
        reading.check_method_context(context, 'GOV-A12')
    rows.append(query.execution)
    proof_refs = [*query.evidence_refs, *(ref for row in rows for ref in walk_references(row) if ref.kind == 'Evidence')]
    evidence = {}
    for ref in proof_refs:
        row = reading.resolve(ref)
        if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Feedback execution query requires observed original profile and actual execution evidence')
        evidence[ref.key()] = row.model_dump(mode='json')
    resolution = dict(schema_version='government-feedback-execution-resolution.v1',
        disposition=query.execution.status, query=query.model_dump(mode='json'),
        original_action_input=raw, action_input=current_raw, original_context=original_context.model_dump(mode='json'),
        context=context.model_dump(mode='json'), feedback_sources=deepcopy(selected.feedback_sources),
        unavailable_targets=deepcopy(selected.unavailable_targets), evidence=list(evidence.values()))
    if validate_relation(source_identity=deepcopy(source), condition_code=EXECUTION_CODE,
            terminal_execution=terminal, resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Feedback execution query lacks native current read/working authority and original execution/history authentication')
    return 'ready', resolution


def government_original_feedback_execution_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Feedback execution recovery requires guarded sources and native query authentication')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_feedback_execution(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('GOV-A12', EXECUTION_CODE, '2', frozenset({'dependency_change'}), evaluate)
