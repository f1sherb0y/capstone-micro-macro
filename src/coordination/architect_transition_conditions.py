"""Recover actual recipient acceptance of the original service handover package."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.architect_transition_objects import (
    ArchitectTransitionBasisView, ArchitectTransitionEngagementView, ArchitectRecallDependencyView,
    ArchitectRecallWorkProfileView,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, ScopeRef, StrictRecord, ref_type
from src.actions.contracts.references import ActionReadView
from src.actions.roles.service_transition import transition_service
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


_CODE = 'handover_waiting_independent_recipient_acceptance'
_EXECUTION_CODE = 'query_original_service_transition'
_WINDOW_CODE = 'recall_requires_new_available_window'
_ALLOCATION_CODES = ('query_original_recall_allocation', 'query_original_handover_allocation')
_DEPENDENCY_CODE = 'recall_dependency_not_ready'
_CAPACITY_CODE = 'recall_capacity_unavailable'
_CODES = (_CODE, _EXECUTION_CODE, _WINDOW_CODE, *_ALLOCATION_CODES, _DEPENDENCY_CODE, _CAPACITY_CODE)


class _TransitionInput(StrictRecord):
    scope: ScopeRef
    engagement_ref: ref_type('Engagement')
    transition_basis_ref: ref_type('ServiceTransitionBasis')
    task_refs: list[ref_type('Task')]
    allocation_refs: list[ref_type('ResourceAllocation')]
    usable_deliverable_refs: list[ref_type('Deliverable')]
    residual_obligation_refs: list[ref_type('Obligation')]


@dataclass(frozen=True)
class ArchitectTransitionConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict
    original_context: ActionContext
    transition_sources: list[dict]
    unavailable_targets: list[dict]
    execution_query: dict | None = None
    allocation_query: dict | None = None


def _physical(value):
    if isinstance(value, dict):
        return {key: _physical(item) for key, item in value.items()
            if not (key == 'version' and set(value) == {'kind', 'id', 'version'})}
    if isinstance(value, list):
        return [_physical(item) for item in value]
    return value


def _source_references(value):
    if isinstance(value, dict):
        if set(value) == {'kind', 'id', 'version'}:
            yield Reference.model_validate(value)
        else:
            for item in value.values():
                yield from _source_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _source_references(item)


def _recall_profile(read_current, validate_relation, code, *, engineer=False, qs=False):
    """Authenticate original recall work before accepting a plan or dependency update."""
    if engineer and qs:
        raise ValueError('Service recall recovery requires one original role')
    action_id, role, input_type, processor, document_field = (
        'ARCHITECT-A11', 'Architect', _TransitionInput, transition_service, 'usable_deliverable_refs')
    work_type = ArchitectRecallWorkProfileView
    if engineer:
        from src.coordination.engineer_transition_conditions import _EngineerTransitionInput
        from src.actions.roles.engineer_transition import transition_engineering_service
        from src.actions.contracts.engineer_transition_objects import EngineerRecallWorkProfileView
        work_type = EngineerRecallWorkProfileView
        action_id, role, input_type, processor, document_field = (
            'ENGINEER-A11', 'Engineer', _EngineerTransitionInput, transition_engineering_service, 'deliverable_refs')
    if qs:
        from src.coordination.qs_transition_conditions import _QSTransitionInput, _preserve_qs_transition_links
        from src.actions.roles.qs_transition import transition_qs_service
        action_id, role, input_type, processor, document_field = (
            'QS-A11', 'QS', _QSTransitionInput, transition_qs_service, 'deliverable_refs')
    window_wait = code == _WINDOW_CODE
    capacity_wait = code == _CAPACITY_CODE
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Recall window recovery requires guarded sources and native plan authentication')

    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != action_id or source['role'] != role or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != (('ServiceTransitionBasis',) if window_wait else
                    ('WorkProfile',) if capacity_wait else ('Dependency',))
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Recall window recovery replaces the original service wait')
        selected = read_current(deepcopy(check))
        if not isinstance(selected, ArchitectTransitionConditionReading):
            raise TaskConflict('Recall window recovery requires original/current typed service sources')
        context, reading, original_context = selected.context, selected.reading, selected.original_context
        try:
            old_input = input_type.model_validate(selected.original_action_input)
            current_input = input_type.model_validate(selected.action_input)
            if (not isinstance(context, ActionContext) or not isinstance(original_context, ActionContext)
                    or not isinstance(reading, ActionReadView)
                    or task_digest(selected.original_action_input) != source['input_sha256']
                    or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
                    or context.scope != original_context.scope or old_input.scope != current_input.scope
                    or context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                    or context.contract_ref.id != action_id or context.execution_mode != 'llm'
                    or context.operation_id == source['request_id'] or context.business_time != check.signal.business_time
                    or context.business_time.clock_ref != original_context.business_time.clock_ref
                    or context.business_time.offset < original_context.business_time.offset
                    or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
                raise TaskConflict('Recall window recovery changes original invocation/scope or current observation')
            reading.check_method_context(context, action_id)
            versions = []
            for inputs in (old_input, current_input):
                engagement, basis = reading.resolve(inputs.engagement_ref), reading.resolve(inputs.transition_basis_ref)
                if (not isinstance(engagement, ArchitectTransitionEngagementView) or engagement.ref != inputs.engagement_ref
                        or not isinstance(basis, ArchitectTransitionBasisView) or basis.ref != inputs.transition_basis_ref
                        or basis.choice != 'recall' or basis.engagement_ref != engagement.ref):
                    raise TaskConflict('Recall window recovery lacks exact original/current recall sources')
                versions.append((engagement, basis))
            (old_engagement, old_basis), (engagement, basis) = versions
            original_result = processor(original_context, old_input, reading)
            if (original_result['kind'] != 'deferred' or original_result['reason_code'] != code
                    or tuple(original_result['resume_condition']['object_refs']) != tuple(check.condition.object_refs)
                    or original_result['resume_condition']['earliest_time'] != check.condition.earliest_time):
                raise TaskConflict('Recall window recovery bypasses original execution/resource/document-right gates')
            metadata = {'ref', 'available_at', 'effective_window', 'engagement_ref'}
            basis_metadata = metadata | ({'recall_plan', 'selected_task_refs'} if window_wait else set())
            if (old_engagement.ref.key()[:2] != engagement.ref.key()[:2] or old_basis.ref.key()[:2] != basis.ref.key()[:2]
                    or _physical(old_basis.model_dump(mode='json', exclude=basis_metadata))
                        != _physical(basis.model_dump(mode='json', exclude=basis_metadata))
                    or old_basis.selected_task_refs and _physical([ref.model_dump(mode='json') for ref in old_basis.selected_task_refs])
                        != _physical([ref.model_dump(mode='json') for ref in basis.selected_task_refs])
                    or old_basis.recall_plan is not None and basis.recall_plan is not None
                        and old_basis.recall_plan.work_profile_ref.key()[:2] != basis.recall_plan.work_profile_ref.key()[:2]
                    or _physical(old_engagement.model_dump(mode='json', exclude=metadata | {'as_of', 'execution_refs'}))
                        != _physical(engagement.model_dump(mode='json', exclude=metadata | {'as_of', 'execution_refs'}))):
                raise TaskConflict('Recall window recovery rewrites original business/service or declared task/method selection')
            if check.condition.earliest_time is not None:
                earliest = check.condition.earliest_time
                if earliest.clock_ref != context.business_time.clock_ref:
                    raise TaskConflict('Recall window recovery changes original earliest-time clock')
                if context.business_time.offset < earliest.offset:
                    return 'waiting'
            history = {ref.key()[:2]: reading.resolve(ref) for ref in engagement.execution_refs}
            if len(history) != len(engagement.execution_refs):
                raise TaskConflict('Recall window recovery aliases original execution history')
            for ref in old_engagement.execution_refs:
                before, after = reading.resolve(ref), history.get(ref.key()[:2])
                if after is None or before.model_dump(exclude=metadata) != after.model_dump(exclude=metadata):
                    raise TaskConflict('Recall window recovery drops or rewrites original execution history')
            for field in ('task_refs', 'allocation_refs', document_field, 'residual_obligation_refs'):
                before_refs, after_refs = getattr(old_input, field), getattr(current_input, field)
                after_by_id = {ref.key()[:2]: ref for ref in after_refs}
                if len(after_by_id) != len(after_refs) or {ref.key()[:2] for ref in before_refs} != set(after_by_id):
                    raise TaskConflict('Recall window recovery drops original tasks/resources/documents/debt')
                for ref in before_refs:
                    before, after = reading.resolve(ref), reading.resolve(after_by_id[ref.key()[:2]])
                    if _physical(before.model_dump(mode='json', exclude=metadata | {'as_of'})) != _physical(after.model_dump(mode='json', exclude=metadata | {'as_of'})):
                        raise TaskConflict('Recall window recovery rewrites original work/allocation/authorship/obligations')
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
                                raise TaskConflict('Engineering recall recovery rewrites original professional method content')
                    if not window_wait and field == 'task_refs':
                        current_dependencies = {dependency.key()[:2]: dependency for dependency in after.dependency_refs}
                        for dependency in before.dependency_refs:
                            previous = reading.resolve(dependency)
                            current_ref = current_dependencies.get(dependency.key()[:2])
                            current = None if current_ref is None else reading.resolve(current_ref)
                            excluded = metadata | ({'satisfied'} if dependency == check.condition.object_refs[0] else set())
                            if (not isinstance(previous, ArchitectRecallDependencyView) or previous.ref != dependency
                                    or not isinstance(current, ArchitectRecallDependencyView) or current.ref != current_ref
                                    or _physical(previous.model_dump(mode='json', exclude=excluded))
                                        != _physical(current.model_dump(mode='json', exclude=excluded))):
                                raise TaskConflict('Recall dependency recovery replaces original task/predecessor or unrelated dependencies')
                    if field == document_field:
                        rights = {right.key()[:2]: reading.resolve(right) for right in after.existing_use_right_refs}
                        for right in before.existing_use_right_refs:
                            previous, current = reading.resolve(right), rights.get(right.key()[:2])
                            if current is None or _physical(previous.model_dump(mode='json', exclude=metadata)) != _physical(current.model_dump(mode='json', exclude=metadata)):
                                raise TaskConflict('Recall window recovery rewrites existing licensed document uses')
            if basis.recall_plan is None or not basis.recall_plan.items:
                return 'waiting'
            if code == _DEPENDENCY_CODE:
                waited = check.condition.object_refs[0]
                old_dependencies = [ref for task_ref in old_input.task_refs for ref in reading.resolve(task_ref).dependency_refs]
                if waited not in old_dependencies:
                    raise TaskConflict('Recall dependency recovery omits the exact original task dependency')
            capacity_sources = None
            if capacity_wait:
                if old_basis.recall_plan is None or old_basis.recall_plan.work_profile_ref != check.condition.object_refs[0]:
                    raise TaskConflict('Recall capacity recovery substitutes the original calendar wait')
                before_work = reading.resolve(old_basis.recall_plan.work_profile_ref)
                after_work = reading.resolve(basis.recall_plan.work_profile_ref)
                if (not isinstance(before_work, work_type)
                        or not isinstance(after_work, work_type)
                        or before_work.ref != old_basis.recall_plan.work_profile_ref or after_work.ref != basis.recall_plan.work_profile_ref
                        or before_work.ref.key()[:2] != after_work.ref.key()[:2]
                        or _physical(before_work.model_dump(mode='json', exclude=metadata | {'as_of', 'resources', 'commitments', 'commitment_allocation_refs', 'evidence_refs'}))
                            != _physical(after_work.model_dump(mode='json', exclude=metadata | {'as_of', 'resources', 'commitments', 'commitment_allocation_refs', 'evidence_refs'}))):
                    raise TaskConflict('Recall capacity recovery replaces original complete calendar/method/author')
                resources = {row.ref.key()[:2]: row for row in after_work.resources}
                if (len(resources) != len(after_work.resources)
                        or {row.ref.key()[:2] for row in before_work.resources} != set(resources)):
                    raise TaskConflict('Recall capacity recovery substitutes original personnel pools')
                for before in before_work.resources:
                    after = resources[before.ref.key()[:2]]
                    excluded = metadata | {'total', 'evidence_refs'}
                    if _physical(before.model_dump(mode='json', exclude=excluded)) != _physical(after.model_dump(mode='json', exclude=excluded)):
                        raise TaskConflict('Recall capacity recovery rewrites original personnel/functions/productivity')
                commitments = {row.commitment_ref.key()[:2]: row for row in after_work.commitments}
                if len(commitments) != len(after_work.commitments):
                    raise TaskConflict('Recall capacity recovery aliases original commitments')
                removed, updated = [], []
                for before in before_work.commitments:
                    after = commitments.get(before.commitment_ref.key()[:2])
                    allocation = before_work.commitment_allocation_refs.get(before.commitment_ref.id)
                    if after is None:
                        removed.append(dict(commitment=before.model_dump(mode='json'), allocation_ref=None if allocation is None else allocation.model_dump(mode='json')))
                    else:
                        current_allocation = after_work.commitment_allocation_refs.get(after.commitment_ref.id)
                        if allocation is None or current_allocation is None or allocation.key()[:2] != current_allocation.key()[:2]:
                            raise TaskConflict('Recall capacity recovery transfers original occupied calendar to another allocation')
                        if _physical(before.model_dump(mode='json')) != _physical(after.model_dump(mode='json')):
                            updated.append(dict(original=before.model_dump(mode='json'), current=after.model_dump(mode='json'),
                                allocation_ref=current_allocation.model_dump(mode='json')))
                capacity_sources = dict(original=before_work.model_dump(mode='json'), current=after_work.model_dump(mode='json'),
                    removed_commitments=removed, updated_commitments=updated)
            if processor(context, current_input, reading)['kind'] != 'completed':
                return 'waiting'
            evidence = {}
            for ref in _source_references(selected.transition_sources):
                if ref.kind == 'Evidence':
                    row = reading.resolve(ref)
                    if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                        raise TaskConflict('Recall window recovery requires observed work/calendar/resource evidence')
                    evidence[ref.key()] = row.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), condition_code=code,
                    original_action_input=deepcopy(selected.original_action_input), action_input=deepcopy(selected.action_input),
                    original_context=original_context.model_dump(mode='json'), transition_sources=deepcopy(selected.transition_sources),
                    unavailable_targets=deepcopy(selected.unavailable_targets), evidence=list(evidence.values()),
                    recall_plan=basis.recall_plan.model_dump(mode='json'), context=context.model_copy(deep=True), reading=reading,
                    **({'capacity_sources': deepcopy(capacity_sources)} if capacity_wait else {})) is not True:
                raise TaskConflict('Recall window recovery lacks native current plan/calendar/authority and retained-history validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile(action_id, code, '1', frozenset({'dependency_change'}), evaluate)


def architect_original_recall_window_profile(read_current, validate_relation):
    return _recall_profile(read_current, validate_relation, _WINDOW_CODE)


def architect_original_recall_dependency_profile(read_current, validate_relation):
    return _recall_profile(read_current, validate_relation, _DEPENDENCY_CODE)


def architect_original_recall_capacity_profile(read_current, validate_relation):
    return _recall_profile(read_current, validate_relation, _CAPACITY_CODE)


def architect_original_handover_acceptance_profile(read_current, validate_relation):
    return _handover_acceptance_profile(read_current, validate_relation)


def _handover_acceptance_profile(read_current, validate_relation, *, engineer=False, qs=False):
    if engineer and qs:
        raise ValueError('Service handover recovery requires one original role')
    action_id, role, input_type, processor, document_field = 'ARCHITECT-A11', 'Architect', _TransitionInput, transition_service, 'usable_deliverable_refs'
    if engineer:
        from src.coordination.engineer_transition_conditions import _EngineerTransitionInput
        from src.actions.roles.engineer_transition import transition_engineering_service
        action_id, role, input_type, processor, document_field = (
            'ENGINEER-A11', 'Engineer', _EngineerTransitionInput, transition_engineering_service, 'deliverable_refs')
    if qs:
        from src.coordination.qs_transition_conditions import _QSTransitionInput
        from src.actions.roles.qs_transition import transition_qs_service
        action_id, role, input_type, processor, document_field = (
            'QS-A11', 'QS', _QSTransitionInput, transition_qs_service, 'deliverable_refs')
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Architect handover recovery requires guarded original/current sources and native validation')

    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != action_id or source['role'] != role or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != ('ServiceTransitionBasis',)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Handover recovery replaces original recipient-acceptance wait')
        selected = read_current(deepcopy(check))
        if not isinstance(selected, ArchitectTransitionConditionReading):
            raise TaskConflict('Handover recovery requires exact original/current invocation sources')
        context, reading = selected.context, selected.reading
        try:
            old_input, current_input = input_type.model_validate(selected.original_action_input), input_type.model_validate(selected.action_input)
            if (task_digest(selected.original_action_input) != source['input_sha256']
                    or task_digest(selected.original_context.model_dump(mode='json')) != source['context_sha256']
                    or context.scope != selected.original_context.scope or old_input.scope != current_input.scope
                    or context.run_id != source['run_id'] or context.contract_ref.id != action_id or context.contract_ref.kind != 'ActionContract'
                    or context.execution_mode != 'llm' or context.operation_id == source['request_id']
                    or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time
                    or context.business_time.clock_ref != selected.original_context.business_time.clock_ref
                    or context.business_time.offset < selected.original_context.business_time.offset):
                raise TaskConflict('Handover recovery changes original snapshot/scope or independent current invocation')
            reading.check_method_context(context, action_id)
            versions = []
            for inputs, invocation in ((old_input, selected.original_context), (current_input, context)):
                basis, engagement = reading.resolve(inputs.transition_basis_ref), reading.resolve(inputs.engagement_ref)
                if (not isinstance(basis, ArchitectTransitionBasisView) or basis.ref != inputs.transition_basis_ref
                        or basis.choice not in {'handover', 'exit'} or basis.package is None
                        or not isinstance(engagement, ArchitectTransitionEngagementView) or engagement.ref != inputs.engagement_ref):
                    raise TaskConflict('Handover recovery lacks exact original service/package sources')
                result = processor(invocation, inputs, reading)
                if inputs is old_input:
                    if (result['kind'] != 'deferred' or result['reason_code'] != _CODE
                            or tuple(result['resume_condition']['object_refs']) != tuple(check.condition.object_refs)):
                        raise TaskConflict('Handover recovery bypasses original history/resource/document-right gates')
                elif result['kind'] != 'completed':
                    return 'waiting'
                versions.append((basis, engagement))
            (old_basis, old_engagement), (basis, engagement) = versions
            if (old_basis.ref.key()[:2] != basis.ref.key()[:2] or old_engagement.ref.key()[:2] != engagement.ref.key()[:2]
                    or old_basis.choice != basis.choice or old_basis.business_key != basis.business_key
                    or _physical(old_basis.package.model_dump(mode='json')) != _physical(basis.package.model_dump(mode='json'))
                    or not {ref.key()[:2] for ref in old_engagement.execution_refs} <= {ref.key()[:2] for ref in engagement.execution_refs}
                    or not {ref.key()[:2] for ref in old_basis.recipient_acceptance_refs}
                        <= {ref.key()[:2] for ref in basis.recipient_acceptance_refs}):
                raise TaskConflict('Handover recovery rewrites original business package or drops execution/acceptance history')
            for field in ('task_refs', 'allocation_refs', document_field, 'residual_obligation_refs'):
                before, after = getattr(old_input, field), getattr(current_input, field)
                current_refs = {ref.key()[:2]: ref for ref in after}
                if len(current_refs) != len(after) or {ref.key()[:2] for ref in before} != set(current_refs):
                    raise TaskConflict('Handover recovery drops original task/resource/document or fee obligation')
                for ref in before:
                    previous, current = reading.resolve(ref), reading.resolve(current_refs[ref.key()[:2]])
                    metadata = {'ref', 'available_at', 'effective_window', 'as_of', 'engagement_ref'}
                    if _physical(previous.model_dump(mode='json', exclude=metadata)) != _physical(current.model_dump(mode='json', exclude=metadata)):
                        raise TaskConflict('Handover recovery rewrites original work/allocation/document/remaining obligation content')
                    if engineer and field in {'task_refs', document_field}:
                        current_methods = {ref.key()[:2]: ref for ref in current.professional_method_refs}
                        for method_ref in previous.professional_method_refs:
                            old_method = reading.resolve(method_ref)
                            new_ref = current_methods.get(method_ref.key()[:2])
                            new_method = None if new_ref is None else reading.resolve(new_ref)
                            if new_method is None or _physical(old_method.model_dump(mode='json', exclude=metadata)) != _physical(new_method.model_dump(mode='json', exclude=metadata)):
                                raise TaskConflict('Engineering handover recovery rewrites original professional method content')
                    if qs:
                        linked_fields = ('work_estimate_ref',) if field == 'task_refs' else (
                            'price_source_refs', 'measurement_trace_refs') if field == document_field else (
                            'contract_ref',) if field == 'residual_obligation_refs' else ()
                        for linked_field in linked_fields:
                            before_refs, after_refs = getattr(previous, linked_field), getattr(current, linked_field)
                            before_refs = before_refs if isinstance(before_refs, list) else [before_refs]
                            after_refs = after_refs if isinstance(after_refs, list) else [after_refs]
                            linked = {ref.key()[:2]: ref for ref in after_refs}
                            for linked_ref in before_refs:
                                current_ref = linked.get(linked_ref.key()[:2])
                                if current_ref == linked_ref:
                                    continue
                                old_source = reading.resolve(linked_ref)
                                new_source = None if current_ref is None else reading.resolve(current_ref)
                                if new_source is None or _physical(old_source.model_dump(mode='json', exclude=metadata)) != _physical(new_source.model_dump(mode='json', exclude=metadata)):
                                    raise TaskConflict('QS handover recovery rewrites original price/measurement/estimate or debt contract')
                    if field == document_field:
                        current_rights = {ref.key()[:2]: ref for ref in current.existing_use_right_refs}
                        for right_ref in previous.existing_use_right_refs:
                            old_right = reading.resolve(right_ref)
                            new_ref = current_rights.get(right_ref.key()[:2])
                            new_right = None if new_ref is None else reading.resolve(new_ref)
                            if new_right is None or _physical(old_right.model_dump(mode='json', exclude=metadata)) != _physical(new_right.model_dump(mode='json', exclude=metadata)):
                                raise TaskConflict('Handover recovery rewrites original licensed document use')
            acceptances = {ref.key()[:2]: reading.resolve(ref) for ref in basis.recipient_acceptance_refs}
            for ref in old_basis.recipient_acceptance_refs:
                before, after = reading.resolve(ref), acceptances[ref.key()[:2]]
                metadata = {'ref', 'available_at', 'effective_window', 'accepted', 'package_sha256'}
                if before.model_dump(exclude=metadata) != after.model_dump(exclude=metadata):
                    raise TaskConflict('Handover recovery changes an existing recipient acceptance or independent author')
            evidence = {}
            for row in selected.transition_sources:
                for ref in _source_references(row):
                    if ref.kind != 'Evidence':
                        continue
                    item = reading.resolve(ref)
                    if not isinstance(item, EvidenceRecord) or item.source_kind == 'synthetic' or item.basis_kind != 'observed':
                        raise TaskConflict('Handover recovery requires observed actual acceptance/rights/obligation evidence')
                    evidence[ref.key()] = item.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), condition_code=_CODE,
                    original_action_input=deepcopy(selected.original_action_input), action_input=deepcopy(selected.action_input),
                    original_context=selected.original_context.model_dump(mode='json'), transition_sources=deepcopy(selected.transition_sources),
                    unavailable_targets=deepcopy(selected.unavailable_targets), evidence=list(evidence.values()),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Handover recovery lacks native independent recipient acceptance and preserved service/rights/debt validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile(action_id, _CODE, '1', frozenset({'dependency_change'}), evaluate)
