"""Query the original service execution without replaying an existing business."""
from copy import deepcopy

from pydantic import Field, model_validator

from src.actions.contracts.architect_transition_objects import (
    ArchitectTransitionBasisView, ArchitectTransitionEngagementView, ArchitectTransitionExecutionView,
)
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import ActionContext, EvidenceRecord, StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.actions.roles.service_transition import transition_service
from src.coordination.architect_transition_conditions import (
    ArchitectTransitionConditionReading, _TransitionInput, _EXECUTION_CODE, _physical, _source_references,
)
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


EXECUTION_CODE = _EXECUTION_CODE
_TERMINAL = {'succeeded', 'failed', 'rejected'}
_METADATA = {'ref', 'available_at', 'effective_window'}
_BASIS_METADATA = _METADATA | {'engagement_ref'}


class ArchitectTransitionExecutionQueryRecord(StrictRecord):
    query_id: TextId
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    execution_ref: ref_type('ServiceTransitionExecution')
    business_key: TextId
    basis_sha256: Digest
    queried_at: TimePoint
    execution: ArchitectTransitionExecutionView
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)

    @model_validator(mode='after')
    def original_execution(self):
        row = self.execution
        if (row.ref.key()[:2] != self.execution_ref.key()[:2]
                or row.run_id != self.run_id or row.organization_id != self.organization_id
                or row.business_key != self.business_key or row.basis_sha256 != self.basis_sha256
                or len({ref.key() for ref in self.evidence_refs}) != len(self.evidence_refs)):
            raise ValueError('Service query replaces original execution/business/basis or repeats evidence')
        return self


def check_transition_execution(check, selected, validate_relation, *, terminal=False, engineer=False, qs=False):
    if engineer and qs:
        raise ValueError('Service execution query requires one original role')
    action_id, role, input_type, processor, document_field, query_type = (
        'ARCHITECT-A11', 'Architect', _TransitionInput, transition_service,
        'usable_deliverable_refs', ArchitectTransitionExecutionQueryRecord)
    if engineer:
        from src.coordination.engineer_transition_conditions import _EngineerTransitionInput
        from src.coordination.engineer_transition_execution_query import EngineerTransitionExecutionQueryRecord
        from src.actions.roles.engineer_transition import transition_engineering_service
        action_id, role, input_type, processor, document_field, query_type = (
            'ENGINEER-A11', 'Engineer', _EngineerTransitionInput, transition_engineering_service,
            'deliverable_refs', EngineerTransitionExecutionQueryRecord)
    if qs:
        from src.coordination.qs_transition_conditions import _QSTransitionInput
        from src.coordination.qs_transition_execution_query import QSTransitionExecutionQueryRecord
        from src.actions.roles.qs_transition import transition_qs_service
        action_id, role, input_type, processor, document_field, query_type = (
            'QS-A11', 'QS', _QSTransitionInput, transition_qs_service,
            'deliverable_refs', QSTransitionExecutionQueryRecord)
    source = check.source['identity']
    if (source['action_id'] != action_id or source['role'] != role or source['purpose'] != 'action'
            or check.condition.condition_code != EXECUTION_CODE or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('ServiceTransitionExecution',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ArchitectTransitionConditionReading)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView)):
        raise TaskConflict('Service execution query replaces original wait or typed authorized sources')
    reading, context, original_context = selected.reading, selected.context, selected.original_context
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    old_input, current_input = input_type.model_validate(raw), input_type.model_validate(current_raw)
    if (task_digest(raw) != source['input_sha256']
            or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
            or context.contract_ref.id != action_id or context.execution_mode != 'llm'
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'
            or context.scope != original_context.scope or old_input.scope != current_input.scope
            or context.actor_id != original_context.actor_id or context.function_ref != original_context.function_ref
            or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and raw != current_raw):
        raise TaskConflict('Service execution query changes original invocation/scope or current observation')
    reading.check_method_context(context, action_id)

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Service execution query lacks exact typed original/current history')
        return row

    original_result = processor(original_context, old_input, reading)
    if (original_result['kind'] != 'deferred' or original_result['reason_code'] != EXECUTION_CODE
            or tuple(original_result['resume_condition']['object_refs']) != tuple(check.condition.object_refs)):
        raise TaskConflict('Service execution query bypasses the original first execution gate')
    versions = []
    for inputs, invocation in ((old_input, original_context), (current_input, context)):
        engagement = read(inputs.engagement_ref, ArchitectTransitionEngagementView)
        basis = read(inputs.transition_basis_ref, ArchitectTransitionBasisView)
        history = [read(ref, ArchitectTransitionExecutionView) for ref in engagement.execution_refs]
        if (engagement.organization_id != source['organization_id'] or engagement.coverage != 'complete'
                or basis.engagement_ref != engagement.ref
                or len({row.ref.key()[:2] for row in history}) != len(history)
                or len({row.business_key for row in history}) != len(history)
                or any(row.organization_id != source['organization_id'] or row.run_id != source['run_id']
                    or row.engagement_ref.key()[:2] != engagement.ref.key()[:2]
                    or row.available_at.clock_ref != invocation.business_time.clock_ref
                    or row.available_at.offset > invocation.business_time.offset for row in history)):
            raise TaskConflict('Service execution query substitutes service or repeats execution history')
        versions.append((engagement, basis, history))
    (old_engagement, old_basis, old_history), (engagement, basis, history) = versions
    first = read(check.condition.object_refs[0], ArchitectTransitionExecutionView)
    executed_basis = read(first.basis_ref, ArchitectTransitionBasisView)
    same_business = first.business_key == old_basis.business_key
    if (first.basis_sha256 != content_digest(executed_basis)
            or executed_basis.business_key != first.business_key
            or executed_basis.engagement_ref != first.engagement_ref or executed_basis.scope != first.scope
            or same_business and executed_basis.model_dump(exclude=_BASIS_METADATA) != old_basis.model_dump(exclude=_BASIS_METADATA)
            or old_engagement.ref.key()[:2] != engagement.ref.key()[:2]
            or old_basis.ref.key()[:2] != basis.ref.key()[:2]
            or _physical(old_basis.model_dump(mode='json', exclude=_BASIS_METADATA)) != _physical(basis.model_dump(mode='json', exclude=_BASIS_METADATA))
            or _physical(old_engagement.model_dump(mode='json', exclude=_METADATA | {'as_of', 'execution_refs'}))
                != _physical(engagement.model_dump(mode='json', exclude=_METADATA | {'as_of', 'execution_refs'}))):
        raise TaskConflict('Service execution query rewrites original basis/service/business content')
    if (executed_basis.available_at.clock_ref != original_context.business_time.clock_ref
            or executed_basis.available_at.offset > original_context.business_time.offset):
        raise TaskConflict('Service execution query introduces a basis unavailable at the original waiting point')
    current_by_id = {row.ref.key()[:2]: row for row in history}
    for before in old_history:
        after = current_by_id.get(before.ref.key()[:2])
        if (after is None or before.model_dump(exclude=_METADATA | {'status'}) != after.model_dump(exclude=_METADATA | {'status'})
                or before.status in _TERMINAL and before.status != after.status):
            raise TaskConflict('Service execution query drops or rewrites retained history/disposition')
    for field in ('task_refs', 'allocation_refs', document_field, 'residual_obligation_refs'):
        before_refs, after_refs = getattr(old_input, field), getattr(current_input, field)
        after_by_id = {ref.key()[:2]: ref for ref in after_refs}
        if len(after_by_id) != len(after_refs) or {ref.key()[:2] for ref in before_refs} != set(after_by_id):
            raise TaskConflict('Service execution query drops original work/resource/document/obligation')
        for ref in before_refs:
            before, after = reading.resolve(ref), reading.resolve(after_by_id[ref.key()[:2]])
            metadata = _METADATA | {'as_of', 'engagement_ref'}
            if _physical(before.model_dump(mode='json', exclude=metadata)) != _physical(after.model_dump(mode='json', exclude=metadata)):
                raise TaskConflict('Service execution query rewrites retained work/resource/document/debt')
            if engineer and field in {'task_refs', document_field}:
                for linked_field in ('professional_method_refs', 'dependency_refs', 'missing_dependency_refs', 'input_refs'):
                    current_refs = {ref.key()[:2]: ref for ref in getattr(after, linked_field, ())}
                    for linked_ref in getattr(before, linked_field, ()):
                        if linked_ref.kind not in {'ProfessionalMethod', 'Dependency', 'Qualification', 'SiteAccess'}:
                            continue
                        current_ref = current_refs.get(linked_ref.key()[:2])
                        if current_ref == linked_ref:
                            continue
                        previous = reading.resolve(linked_ref)
                        current = None if current_ref is None else reading.resolve(current_ref)
                        if current is None or _physical(previous.model_dump(mode='json', exclude=metadata)) != _physical(current.model_dump(mode='json', exclude=metadata)):
                            raise TaskConflict('Engineering service query rewrites original methods/qualification or missing dependency sources')
            if field == document_field:
                rights = {right.key()[:2]: reading.resolve(right) for right in after.existing_use_right_refs}
                for right in before.existing_use_right_refs:
                    previous, current = reading.resolve(right), rights.get(right.key()[:2])
                    if current is None or _physical(previous.model_dump(mode='json', exclude=_METADATA)) != _physical(current.model_dump(mode='json', exclude=_METADATA)):
                        raise TaskConflict('Service execution query rewrites retained document use rights')
            if qs:
                linked_fields = ('work_estimate_ref',) if field == 'task_refs' else (
                    'price_source_refs', 'measurement_trace_refs') if field == document_field else (
                    'contract_ref',) if field == 'residual_obligation_refs' else ()
                for linked_field in linked_fields:
                    previous_refs, current_refs = getattr(before, linked_field), getattr(after, linked_field)
                    previous_refs = previous_refs if isinstance(previous_refs, list) else [previous_refs]
                    current_refs = current_refs if isinstance(current_refs, list) else [current_refs]
                    current_by_ref = {ref.key()[:2]: ref for ref in current_refs}
                    for linked_ref in previous_refs:
                        current_ref = current_by_ref.get(linked_ref.key()[:2])
                        if current_ref == linked_ref:
                            continue
                        previous = reading.resolve(linked_ref)
                        current = None if current_ref is None else reading.resolve(current_ref)
                        if current is None or _physical(previous.model_dump(mode='json', exclude=metadata)) != _physical(current.model_dump(mode='json', exclude=metadata)):
                            raise TaskConflict('QS service query rewrites original quantity/price/estimate or debt contract')
    if selected.execution_query is None:
        return 'waiting', None
    query = query_type.model_validate(deepcopy(selected.execution_query))
    if (query.source_identity_sha256 != task_digest(source) or query.execution_ref != first.ref
            or query.run_id != source['run_id'] or query.organization_id != source['organization_id']
            or query.business_key != first.business_key or query.basis_sha256 != first.basis_sha256
            or query.queried_at != context.business_time
            or query.execution.model_dump(exclude=_METADATA | {'status'}) != first.model_dump(exclude=_METADATA | {'status'})
            or query.execution.available_at.clock_ref != context.business_time.clock_ref
            or query.execution.available_at.offset > context.business_time.offset
            or first.status in _TERMINAL and first.status != query.execution.status):
        raise TaskConflict('Service execution lookup substitutes original execution/basis or actual query time')
    if query.execution.status not in _TERMINAL:
        return 'waiting', None
    if terminal:
        if not same_business:
            raise TaskConflict('Only original same-business service execution may be archived terminally')
    else:
        if same_business:
            return 'waiting', None
        if current_by_id[first.ref.key()[:2]] != query.execution:
            raise TaskConflict('Current service history conflicts with the actual original execution query')
        if processor(context, current_input, reading)['kind'] != 'completed':
            return 'waiting', None
    evidence = {}
    for ref in _source_references([*selected.transition_sources, query.model_dump(mode='json')]):
        if ref.kind == 'Evidence':
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                raise TaskConflict('Service execution query requires observed actual source/query evidence')
            evidence[ref.key()] = row.model_dump(mode='json')
    resolution = dict(schema_version=f'{role.lower()}-transition-execution-resolution.v1', disposition=query.execution.status,
        query=query.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original_context.model_dump(mode='json'), context=context.model_dump(mode='json'),
        transition_sources=deepcopy(selected.transition_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
        evidence=list(evidence.values()))
    if validate_relation(source_identity=deepcopy(source), condition_code=EXECUTION_CODE,
            terminal_execution=terminal, resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Service execution query lacks native authorization and original execution/history authentication')
    return 'ready', resolution


def architect_original_transition_execution_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Service execution recovery requires guarded sources and native query authentication')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_transition_execution(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('ARCHITECT-A11', EXECUTION_CODE, '2', frozenset({'dependency_change'}), evaluate)
