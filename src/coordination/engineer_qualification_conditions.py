"""Preserve actual issuer events when recovering already-applied qualification waits."""
from copy import deepcopy
from typing import Literal

from pydantic import Field

from src.actions.contracts.architect_learning_objects import ArchitectLearningCapabilityView
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, StrictRecord, TextId, TimePoint, ref_type, walk_references
from src.actions.contracts.engineer_learning_objects import (
    EngineerLearningStrategyView, EngineerLearningStateView, EngineerLearningDecisionView,
    EngineerLearningExecutionView, EngineerQualificationView, EngineerQualificationEventView,
    EngineerQualificationUpdateBasisView, EngineerQualificationVerificationView,
)
from src.actions.roles.engineer_learning import maintain_engineering_experience
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


QUALIFICATION_CODE = 'qualification_event_already_applied'
_EVENT_METADATA = {'ref', 'qualification_ref', 'available_at', 'effective_window', 'received_at'}


class EngineerQualificationApplicationQueryRecord(StrictRecord):
    query_id: TextId
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    original_state_ref: ref_type('EngineerLearningState')
    current_strategy_ref: ref_type('Strategy')
    current_state_ref: ref_type('EngineerLearningState')
    current_qualification_ref: ref_type('Qualification')
    original_event_ref: ref_type('QualificationEvent')
    original_event_sha256: Digest
    verification_ref: ref_type('QualificationVerification')
    execution_ref: ref_type('EngineerLearningExecution')
    queried_at: TimePoint
    status: Literal['applied', 'unknown']
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)


def check_qualification_application(check, selected, validate_relation, *, terminal=False):
    from src.coordination.engineer_learning_conditions import _EngineerLearningInput, EngineerLearningConditionReading
    source = check.source['identity']
    if (source['action_id'] != 'ENGINEER-A12' or source['role'] != 'Engineer' or source['purpose'] != 'action'
            or check.condition.condition_code != QUALIFICATION_CODE or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('EngineerLearningState',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, EngineerLearningConditionReading)):
        raise TaskConflict('Qualification recovery replaces original wait or private recipient')
    context, original_context, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
            or context.contract_ref.id != 'ENGINEER-A12' or context.execution_mode != 'llm'
            or reading._resolver.source_mode != 'formal' or reading.organization_id != source['organization_id']
            or context.scope != original_context.scope or raw['scope'] != current_raw['scope']
            or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and raw != current_raw):
        raise TaskConflict('Qualification recovery changes original snapshot or current authorized invocation')
    reading.check_method_context(context, 'ENGINEER-A12')
    proof_refs = []

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Qualification recovery lacks exact actual source versions')
        proof_refs.extend(ref for ref in walk_references(row) if ref.kind == 'Evidence')
        return row

    def event_history(refs, at):
        if len({ref.key() for ref in refs}) != len(refs):
            raise TaskConflict('Qualification recovery duplicates issuer event references')
        events = {}
        for ref in refs:
            row = read(ref, EngineerQualificationEventView)
            key = (row.issuer_organization_id, row.credential_key, row.event_key)
            content = row.model_dump(exclude=_EVENT_METADATA)
            if (row.organization_id != source['organization_id'] or row.author_organization_id != row.issuer_organization_id
                    or any(point.clock_ref != at.clock_ref for point in (row.occurred_at, row.authored_at, row.available_at, row.received_at))
                    or not row.occurred_at.offset <= row.authored_at.offset <= row.available_at.offset <= row.received_at.offset <= at.offset
                    or key in events and events[key] != content):
                raise TaskConflict('Qualification recovery rewrites actual issuer/event content or knowledge chronology')
            events[key] = content
        return events

    inputs = _EngineerLearningInput.model_validate(raw)
    old_strategy = read(inputs.strategy_ref, EngineerLearningStrategyView)
    old_state = read(old_strategy.learning_state_ref, EngineerLearningStateView)
    old_decision = read(old_strategy.decision_profile_ref, EngineerLearningDecisionView)
    original_result = maintain_engineering_experience(original_context, inputs, reading)
    if (original_result['kind'] != 'deferred' or original_result['reason_code'] != QUALIFICATION_CODE
            or tuple(original_result['resume_condition']['object_refs']) != tuple(check.condition.object_refs)
            or tuple(check.condition.object_refs) != (old_state.ref,) or old_decision.choice != 'request_qualification_update'):
        raise TaskConflict('Qualification recovery bypasses original actual already-applied issuer event gate')
    old_qualification = read(old_decision.qualification_ref, EngineerQualificationView)
    old_basis = read(old_decision.qualification_update_basis_ref, EngineerQualificationUpdateBasisView)
    old_event = read(old_basis.qualification_event_ref, EngineerQualificationEventView)
    old_received = event_history(old_qualification.event_refs, original_context.business_time)
    old_applied = event_history(old_state.applied_qualification_event_refs, original_context.business_time)
    old_key = (old_event.issuer_organization_id, old_event.credential_key, old_event.event_key)
    if old_received.get(old_key) != old_applied.get(old_key) or old_key not in old_applied:
        raise TaskConflict('Qualification wait has no matching actual received/applied event')
    query = None if selected.qualification_application_query is None else EngineerQualificationApplicationQueryRecord.model_validate(
        deepcopy(selected.qualification_application_query))
    if terminal and (query is None or query.status != 'applied'):
        return 'waiting', None
    current_inputs = _EngineerLearningInput.model_validate(current_raw)
    strategy = read(query.current_strategy_ref if terminal else current_inputs.strategy_ref, EngineerLearningStrategyView)
    state = read(strategy.learning_state_ref, EngineerLearningStateView)
    decision = read(strategy.decision_profile_ref, EngineerLearningDecisionView)
    capability = read(state.capability_ref, ArchitectLearningCapabilityView)
    if (strategy.ref.key()[:2] != old_strategy.ref.key()[:2] or state.ref.key()[:2] != old_state.ref.key()[:2]
            or strategy.organization_id != source['organization_id'] or state.organization_id != source['organization_id']
            or state.strategy_ref != strategy.ref or state.scope != context.scope or state.coverage != 'complete'
            or state.as_of != context.business_time or capability.organization_id != source['organization_id']
            or not {ref.key() for ref in old_state.received_feedback_refs} <= {ref.key() for ref in state.received_feedback_refs}
            or not {ref.key() for ref in old_state.applied_feedback_refs} <= {ref.key() for ref in state.applied_feedback_refs}
            or old_strategy.judgments != strategy.judgments):
        raise TaskConflict('Qualification recovery changes original firm/scope or private judgment/feedback history')
    if (state.available_at.clock_ref != context.business_time.clock_ref or state.available_at.offset > context.business_time.offset
            or not state.effective_window.contains(context.business_time)):
        return 'unavailable', None
    credential_refs = state.qualification_refs if terminal else current_inputs.qualification_refs
    if ({ref.key() for ref in credential_refs} != {ref.key() for ref in state.qualification_refs}
            or {ref.key() for ref in credential_refs} != {ref.key() for ref in capability.qualification_refs}
            or len({ref.key()[:2] for ref in credential_refs}) != len(credential_refs)
            or {ref.key()[:2] for ref in old_state.qualification_refs} != {ref.key()[:2] for ref in state.qualification_refs}):
        raise TaskConflict('Qualification recovery replaces complete physical credential history')
    current_credentials = [read(ref, EngineerQualificationView) for ref in credential_refs]
    matches = [row for row in current_credentials if row.ref.key()[:2] == old_qualification.ref.key()[:2]]
    if len(matches) != 1:
        raise TaskConflict('Qualification recovery replaces original credential')
    qualification = matches[0]
    if (qualification.organization_id != source['organization_id'] or qualification.issuer_organization_id != old_qualification.issuer_organization_id
            or qualification.credential_key != old_qualification.credential_key or qualification.coverage != 'complete'
            or qualification.as_of != context.business_time or qualification.author_organization_id != qualification.issuer_organization_id):
        raise TaskConflict('Qualification recovery replaces actual issuer/credential or complete current facts')
    received, applied = event_history(qualification.event_refs, context.business_time), event_history(state.applied_qualification_event_refs, context.business_time)
    if (any(received.get(key) != value for key, value in old_received.items())
            or any(applied.get(key) != value for key, value in old_applied.items())):
        raise TaskConflict('Qualification recovery drops or rewrites received/applied issuer events')
    executions = {ref.key()[:2]: read(ref, EngineerLearningExecutionView) for ref in state.execution_refs}
    if len(executions) != len(state.execution_refs):
        raise TaskConflict('Qualification recovery duplicates execution history')
    for ref in old_state.execution_refs:
        old_execution = read(ref, EngineerLearningExecutionView)
        if executions.get(ref.key()[:2]) != old_execution:
            raise TaskConflict('Qualification recovery drops original execution history')
    if terminal:
        if (query.source_identity_sha256 != task_digest(source) or query.run_id != source['run_id']
                or query.organization_id != source['organization_id'] or query.original_state_ref != old_state.ref
                or query.current_state_ref != state.ref or query.current_qualification_ref != qualification.ref
                or query.original_event_ref != old_event.ref or query.original_event_sha256 != content_digest(old_event)
                or query.queried_at != context.business_time or len({ref.key() for ref in query.evidence_refs}) != len(query.evidence_refs)):
            raise TaskConflict('Qualification application query substitutes original event or current issuer observations')
        verification = read(query.verification_ref, EngineerQualificationVerificationView)
        execution = read(query.execution_ref, EngineerLearningExecutionView)
        applied_decision = read(execution.decision_ref, EngineerLearningDecisionView)
        applied_basis = read(applied_decision.qualification_update_basis_ref, EngineerQualificationUpdateBasisView)
        if (verification.status != 'verified' or verification.run_id != source['run_id']
                or verification.organization_id != source['organization_id'] or verification.issuer_organization_id != qualification.issuer_organization_id
                or verification.author_organization_id != qualification.issuer_organization_id
                or verification.qualification_event_ref != old_event.ref or verification.qualification_event_sha256 != content_digest(old_event)
                or verification.update_basis_ref != applied_basis.ref or verification.qualification_ref != applied_decision.qualification_ref
                or applied_basis.qualification_ref != applied_decision.qualification_ref
                or applied_basis.qualification_event_ref != old_event.ref
                or applied_basis.issuer_organization_id != qualification.issuer_organization_id
                or verification.verification_service_id != applied_basis.verification_service_id
                or verification.decision_ref != execution.decision_ref or verification.decision_sha256 != execution.decision_sha256
                or verification.business_key != execution.business_key or executions.get(execution.ref.key()[:2]) != execution
                or execution.status != 'succeeded' or execution.run_id != source['run_id'] or execution.organization_id != source['organization_id']
                or execution.decision_sha256 != content_digest(applied_decision) or applied_decision.choice != 'request_qualification_update'
                or execution.business_key != applied_decision.business_key
                or execution.strategy_ref.key()[:2] != strategy.ref.key()[:2]
                or old_key not in applied):
            raise TaskConflict('Qualification query lacks actual independent issuer verification and successful application')
        if any(row.available_at.clock_ref != context.business_time.clock_ref
                or row.available_at.offset > context.business_time.offset for row in (verification, execution)):
            raise TaskConflict('Qualification query introduces future verification/application evidence')
        proof_refs.extend(query.evidence_refs)
    else:
        result = maintain_engineering_experience(context, current_inputs, reading)
        if result['kind'] != 'completed' or result['payload']['choice'] != 'request_qualification_update':
            return 'waiting', None
        basis = read(decision.qualification_update_basis_ref, EngineerQualificationUpdateBasisView)
        event = read(basis.qualification_event_ref, EngineerQualificationEventView)
        key = (event.issuer_organization_id, event.credential_key, event.event_key)
        if (decision.qualification_ref != qualification.ref or key == old_key or key in applied
                or event.issuer_organization_id != old_event.issuer_organization_id or event.credential_key != old_event.credential_key):
            raise TaskConflict('Qualification recovery repeats old event or substitutes another credential')
    evidence = {}
    for ref in proof_refs:
        row = reading.resolve(ref)
        if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Qualification recovery requires observed issuer/application evidence')
        evidence[ref.key()] = row.model_dump(mode='json')
    resolution = dict(schema_version='engineer-qualification-application-resolution.v1',
        disposition='already_applied' if terminal else 'new_issuer_event_available', query=None if query is None else query.model_dump(mode='json'),
        original_event=old_event.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original_context.model_dump(mode='json'), context=context.model_dump(mode='json'),
        learning_sources=deepcopy(selected.learning_sources), unavailable_targets=deepcopy(selected.unavailable_targets), evidence=list(evidence.values()))
    if validate_relation(source_identity=deepcopy(source), condition_code=QUALIFICATION_CODE, terminal_qualification=terminal,
            resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Qualification recovery lacks native issuer authority, original request/verification/application and retained history checks')
    return 'ready', resolution


def engineer_original_qualification_application_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Qualification recovery requires guarded sources and independent issuer validation')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_qualification_application(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('ENGINEER-A12', QUALIFICATION_CODE, '1', frozenset({'dependency_change'}), evaluate)
