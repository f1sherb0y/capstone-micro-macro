"""Authenticate actual original allocation queries before proposing service changes."""
from copy import deepcopy

from pydantic import Field, model_validator

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.architect_transition_objects import ArchitectTransitionAllocationView
from src.actions.contracts.common import EvidenceRecord, StrictRecord, TextId, TimePoint, ref_type
from src.actions.roles.qs_change import content_digest
from src.actions.roles.service_transition import transition_service
from src.coordination.architect_transition_conditions import (
    ArchitectTransitionConditionReading, _TransitionInput, _ALLOCATION_CODES, _physical, _source_references,
)
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


class ArchitectTransitionAllocationQueryRecord(StrictRecord):
    query_id: TextId
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    allocation_ref: ref_type('ResourceAllocation')
    original_allocation_sha256: Digest
    queried_at: TimePoint
    allocation: ArchitectTransitionAllocationView
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)

    @model_validator(mode='after')
    def original_allocation(self):
        if (self.allocation.ref.key()[:2] != self.allocation_ref.key()[:2]
                or self.allocation.organization_id != self.organization_id
                or len({ref.key() for ref in self.evidence_refs}) != len(self.evidence_refs)):
            raise ValueError('Service allocation query substitutes original resource/firm or repeats evidence')
        return self


def _allocation_profile(read_current, validate_relation, code, *, engineer=False, qs=False):
    if engineer and qs:
        raise ValueError('Service allocation recovery requires one original role')
    action_id, role, input_type, processor, document_field = (
        'ARCHITECT-A11', 'Architect', _TransitionInput, transition_service, 'usable_deliverable_refs')
    if engineer:
        from src.coordination.engineer_transition_conditions import _EngineerTransitionInput
        from src.actions.roles.engineer_transition import transition_engineering_service
        action_id, role, input_type, processor, document_field = (
            'ENGINEER-A11', 'Engineer', _EngineerTransitionInput, transition_engineering_service, 'deliverable_refs')
    if qs:
        from src.coordination.qs_transition_conditions import _QSTransitionInput, _preserve_qs_transition_links
        from src.actions.roles.qs_transition import transition_qs_service
        action_id, role, input_type, processor, document_field = (
            'QS-A11', 'QS', _QSTransitionInput, transition_qs_service, 'deliverable_refs')
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Service allocation recovery requires guarded history and native query authentication')

    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != action_id or source['role'] != role or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != ('ResourceAllocation',)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Service allocation recovery replaces original query wait/run/organization')
        selected = read_current(deepcopy(check))
        if not isinstance(selected, ArchitectTransitionConditionReading):
            raise TaskConflict('Service allocation recovery requires original/current typed service sources')
        reading, context, original_context = selected.reading, selected.context, selected.original_context
        try:
            old_input, current_input = input_type.model_validate(selected.original_action_input), input_type.model_validate(selected.action_input)
            if (task_digest(selected.original_action_input) != source['input_sha256']
                    or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
                    or context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                    or context.contract_ref.id != action_id or context.execution_mode != 'llm'
                    or context.operation_id == source['request_id'] or context.scope != original_context.scope
                    or old_input.scope != current_input.scope or reading.organization_id != source['organization_id']
                    or reading._resolver.source_mode != 'formal' or context.business_time != check.signal.business_time
                    or context.business_time.clock_ref != original_context.business_time.clock_ref
                    or context.business_time.offset < original_context.business_time.offset):
                raise TaskConflict('Service allocation recovery substitutes invocation/scope or query time')
            reading.check_method_context(context, action_id)
            original = processor(original_context, old_input, reading)
            if (original['kind'] != 'deferred' or original['reason_code'] != code
                    or tuple(original['resume_condition']['object_refs']) != tuple(check.condition.object_refs)):
                raise TaskConflict('Service allocation recovery bypasses the original emitted allocation gate')
            old_engagement, engagement = reading.resolve(old_input.engagement_ref), reading.resolve(current_input.engagement_ref)
            old_basis, basis = reading.resolve(old_input.transition_basis_ref), reading.resolve(current_input.transition_basis_ref)
            metadata = {'ref', 'available_at', 'effective_window', 'engagement_ref', 'as_of'}
            if (old_engagement.ref.key()[:2] != engagement.ref.key()[:2] or old_basis.ref.key()[:2] != basis.ref.key()[:2]
                    or _physical(old_basis.model_dump(mode='json', exclude=metadata)) != _physical(basis.model_dump(mode='json', exclude=metadata))
                    or _physical(old_engagement.model_dump(mode='json', exclude=metadata)) != _physical(engagement.model_dump(mode='json', exclude=metadata))):
                raise TaskConflict('Service allocation recovery rewrites original service/basis/package/execution history')
            history = {ref.key()[:2]: reading.resolve(ref) for ref in engagement.execution_refs}
            if len(history) != len(engagement.execution_refs):
                raise TaskConflict('Service allocation query aliases original execution history')
            for ref in old_engagement.execution_refs:
                before, after = reading.resolve(ref), history.get(ref.key()[:2])
                if after is None or before.model_dump(exclude=metadata) != after.model_dump(exclude=metadata):
                    raise TaskConflict('Service allocation query rewrites retained execution business/disposition')
            target = check.condition.object_refs[0]
            before_target = reading.resolve(target)
            if not isinstance(before_target, ArchitectTransitionAllocationView) or before_target.ref != target or before_target.status != 'unknown':
                raise TaskConflict('Service allocation query lacks original exact uncertain allocation')
            after_target = None
            for field in ('task_refs', 'allocation_refs', document_field, 'residual_obligation_refs'):
                before_refs, after_refs = getattr(old_input, field), getattr(current_input, field)
                after_by_id = {ref.key()[:2]: ref for ref in after_refs}
                if len(after_by_id) != len(after_refs) or {ref.key()[:2] for ref in before_refs} != set(after_by_id):
                    raise TaskConflict('Service allocation recovery drops original tasks/resources/documents/debt')
                for ref in before_refs:
                    before, after = reading.resolve(ref), reading.resolve(after_by_id[ref.key()[:2]])
                    excluded = metadata
                    if field == 'allocation_refs' and ref.key()[:2] == target.key()[:2]:
                        excluded = metadata | {'status'}
                        after_target = after
                    if _physical(before.model_dump(mode='json', exclude=excluded)) != _physical(after.model_dump(mode='json', exclude=excluded)):
                        raise TaskConflict('Service allocation recovery rewrites retained work/resource identity/authorship/debt')
                    if qs:
                        _preserve_qs_transition_links(before, after, reading, field=field, metadata=metadata)
                    if engineer and field in {'task_refs', document_field}:
                        methods = {ref.key()[:2]: ref for ref in after.professional_method_refs}
                        for method_ref in before.professional_method_refs:
                            current_ref = methods.get(method_ref.key()[:2])
                            if current_ref == method_ref:
                                continue
                            previous = reading.resolve(method_ref)
                            current = None if current_ref is None else reading.resolve(current_ref)
                            if current is None or _physical(previous.model_dump(mode='json', exclude=metadata)) != _physical(current.model_dump(mode='json', exclude=metadata)):
                                raise TaskConflict('Engineering allocation recovery rewrites original professional method content')
                    if field == document_field:
                        rights = {right.key()[:2]: reading.resolve(right) for right in after.existing_use_right_refs}
                        for right in before.existing_use_right_refs:
                            previous, current = reading.resolve(right), rights.get(right.key()[:2])
                            if current is None or _physical(previous.model_dump(mode='json', exclude=metadata)) != _physical(current.model_dump(mode='json', exclude=metadata)):
                                raise TaskConflict('Service allocation query rewrites retained licensed document uses')
            if not isinstance(after_target, ArchitectTransitionAllocationView):
                raise TaskConflict('Service allocation query omits the original selected resource')
            if selected.allocation_query is None:
                return 'waiting'
            query = ArchitectTransitionAllocationQueryRecord.model_validate(deepcopy(selected.allocation_query))
            if (query.source_identity_sha256 != task_digest(source) or query.run_id != source['run_id']
                    or query.organization_id != source['organization_id'] or query.allocation_ref != target
                    or query.original_allocation_sha256 != content_digest(before_target)
                    or query.queried_at != context.business_time or query.allocation.as_of != context.business_time
                    or query.allocation.available_at.clock_ref != context.business_time.clock_ref
                    or query.allocation.available_at.offset > context.business_time.offset
                    or _physical(query.allocation.model_dump(mode='json', exclude=metadata | {'status'}))
                        != _physical(before_target.model_dump(mode='json', exclude=metadata | {'status'}))):
                raise TaskConflict('Service allocation query substitutes original physical allocation or actual observation')
            if query.allocation != after_target:
                raise TaskConflict('Current resource history conflicts with actual native allocation query')
            if query.allocation.status == 'unknown' or code == _ALLOCATION_CODES[1] and query.allocation.status != 'held':
                return 'waiting'
            if processor(context, current_input, reading)['kind'] != 'completed':
                return 'waiting'
            evidence = {}
            for ref in _source_references([*selected.transition_sources, query.model_dump(mode='json')]):
                if ref.kind == 'Evidence':
                    row = reading.resolve(ref)
                    if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                        raise TaskConflict('Service allocation query requires observed actual resource/history evidence')
                    evidence[ref.key()] = row.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), condition_code=code,
                    original_action_input=deepcopy(selected.original_action_input), action_input=deepcopy(selected.action_input),
                    original_context=original_context.model_dump(mode='json'), transition_sources=deepcopy(selected.transition_sources),
                    unavailable_targets=deepcopy(selected.unavailable_targets), evidence=list(evidence.values()),
                    allocation_query=query.model_dump(mode='json'), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Service allocation recovery lacks native original occupation/actual query/release authority validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile(action_id, code, '1', frozenset({'dependency_change'}), evaluate)


def architect_original_recall_allocation_profile(read_current, validate_relation):
    return _allocation_profile(read_current, validate_relation, _ALLOCATION_CODES[0])


def architect_original_handover_allocation_profile(read_current, validate_relation):
    return _allocation_profile(read_current, validate_relation, _ALLOCATION_CODES[1])
