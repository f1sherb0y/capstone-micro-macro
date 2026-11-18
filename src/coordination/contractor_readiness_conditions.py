"""Recover actual task cycles and query original release/terminal states."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.contractor_readiness_objects import (
    ContractorReadyTaskView, ContractorReadyProfileView, ContractorReadyRequirementView, ContractorWorkMandateView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles import contractor_readiness as readiness_role
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


CYCLE_CODE = 'contractor-readiness-original-circular-dependency'
REPLACEMENT_CODE = 'contractor-readiness-replacement-task-dependency-cycle'
STATE_CODE = 'contractor-readiness-original-task-already-released-or-terminal'
_CODES = {CYCLE_CODE, REPLACEMENT_CODE, STATE_CODE}
_STATES = {'released', 'working', 'complete', 'cancelled'}
_NEXT_STATES = {'planned': {'planned', 'blocked', *_STATES}, 'blocked': {'planned', 'blocked', *_STATES},
    'released': {'released', 'working', 'complete', 'cancelled'}, 'working': {'working', 'complete', 'cancelled'},
    'complete': {'complete'}, 'cancelled': {'cancelled'}}
_FIELDS = ('readiness_requirement_refs', 'permit_refs', 'design_release_refs', 'site_refs', 'input_allocation_refs')


@dataclass(frozen=True)
class ContractorReadinessConditionReading(ContractorCloseoutConditionReading):
    contract: ActionContract | None = None


def check_contractor_readiness_history(check, selected, validate_relation, *, terminal=False):
    source, code = check.source['identity'], check.condition.condition_code
    if (source['action_id'] != 'CONTRACTOR-A06' or source['role'] != 'Contractor' or source['purpose'] != 'action'
            or code not in _CODES or check.condition.trigger != 'dependency_change' or not check.condition.object_refs
            or len(check.condition.object_refs) != 1 and code != CYCLE_CODE
            or any(ref.kind != 'Task' for ref in check.condition.object_refs)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ContractorReadinessConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)
            or terminal and code != STATE_CODE):
        raise TaskConflict('Readiness recovery requires original typed task wait and private Contractor')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.run_id != source['run_id']
            or context.contract_ref != original.contract_ref or context.contract_ref.id != 'CONTRACTOR-A06'
            or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Readiness recovery changes original snapshot, scope, time or actual current authority')
    reading.check_method_context(context, 'CONTRACTOR-A06')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'CONTRACTOR-A06' or contract.role != 'Contractor':
        raise TaskConflict('Readiness recovery lacks its actual registered original action contract')
    original_input, current_input = contract.validate_input(raw), contract.validate_input(current_raw)

    def validate_evidence(refs, at):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                raise TaskConflict('Readiness recovery substitutes an exact Evidence source')
            if row.effective_window is not None:
                window = row.effective_window
                if (window.start.clock_ref != at.clock_ref or window.end.clock_ref != at.clock_ref
                        or not window.contains(at)):
                    raise TaskConflict('Readiness recovery evidence is not valid at its original invocation time')

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Readiness recovery lacks exact typed original/current sources')
        if row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset:
            raise TaskConflict('Readiness recovery injects a future or unrelated-clock source')
        if row.effective_window.start.clock_ref != at.clock_ref or row.effective_window.end.clock_ref != at.clock_ref:
            raise TaskConflict('Readiness recovery changes original source window clock')
        validate_evidence(row.evidence_refs, at)
        return row

    def physical(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Readiness recovery repeats physical task/gate/source histories')
        return result

    def same_task(before, after):
        if (before.ref.key()[:2] != after.ref.key()[:2] or before.organization_id != after.organization_id
                or before.mandate_ref.key()[:2] != after.mandate_ref.key()[:2] or before.purpose != after.purpose
                or before.action_ref.key()[:2] != after.action_ref.key()[:2] or before.scope != after.scope
                or after.state not in _NEXT_STATES[before.state]
                or before.state in _STATES and before.execution_window != after.execution_window
                or not set(physical(before.requirement_refs)) <= set(physical(after.requirement_refs))):
            raise TaskConflict('Readiness query rewrites original task, mandate, purpose, gates or established execution state')

    versions = []
    for values, invocation in ((original_input, original), (current_input, context)):
        at = original.business_time if terminal else invocation.business_time
        task = read(values.task_ref, ContractorReadyTaskView, at)
        profile = read(values.readiness_profile_ref, ContractorReadyProfileView, at)
        mandate = read(task.mandate_ref, ContractorWorkMandateView, at)
        if (task.organization_id != source['organization_id'] or task.scope != invocation.scope
                or profile.task_ref != task.ref or profile.ref != task.readiness_profile_ref
                or profile.organization_id != source['organization_id'] or mandate.organization_id != source['organization_id']):
            raise TaskConflict('Readiness recovery borrows another task, Contractor or authorized profile')
        versions.append(dict(task=task, profile=profile, mandate=mandate))
    old, current = versions
    same_task(old['task'], current['task'])
    if old['mandate'].mandate_kind != current['mandate'].mandate_kind or old['profile'].choice != current['profile'].choice:
        raise TaskConflict('Readiness recovery promotes preparation authority or replaces the original action choice')
    for field in _FIELDS:
        if not set(physical(getattr(original_input, field))) <= set(physical(getattr(current_input, field))):
            raise TaskConflict('Readiness recovery drops original necessary gates, permits, design, site or allocations')
    old_replacements = physical(old['profile'].replacement_task_refs)
    current_replacements = physical(current['profile'].replacement_task_refs)
    if not set(old_replacements) <= set(current_replacements):
        raise TaskConflict('Readiness recovery drops original independent replacement task history')
    if not terminal:
        before_requirements = physical(old['task'].requirement_refs)
        after_requirements = physical(current['task'].requirement_refs)
        for key, ref in before_requirements.items():
            before = read(ref, ContractorReadyRequirementView, original.business_time)
            after = read(after_requirements[key], ContractorReadyRequirementView, context.business_time)
            if (before.task_ref != old['task'].ref or after.task_ref != current['task'].ref
                    or before.scope != after.scope or any(getattr(before, field) != getattr(after, field)
                        for field in ('category', 'necessary', 'minimum_quantity', 'verifier_organization_id', 'verifier_action_id'))):
                raise TaskConflict('Readiness recovery weakens original gate categories, quantities or independent verifier identity')
    original_gate = readiness_role.check_task_readiness(original, original_input, reading)
    if (original_gate.get('kind') != 'deferred' or original_gate.get('reason_code') != code
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Readiness wait differs from the actual original first task-state/dependency gate')
    physical(list(check.condition.object_refs))
    first_ref, ref = check.condition.object_refs[0], selected.history_ref
    if ref.key()[:2] != first_ref.key()[:2]:
        raise TaskConflict('Readiness query substitutes the original waited physical task')
    first = read(first_ref, ContractorReadyTaskView, original.business_time)
    history = read(ref, ContractorReadyTaskView, context.business_time)
    same_task(first, history)
    query_mandate = read(history.mandate_ref, ContractorWorkMandateView, context.business_time)
    if (query_mandate.organization_id != history.organization_id
            or query_mandate.mandate_kind != ('contract' if history.mandate_ref.kind == 'Contract' else 'preparation')):
        raise TaskConflict('Readiness query borrows another task organization or promotes preparation authority')
    if history.history_coverage != 'complete' or history.as_of != context.business_time:
        return 'waiting', None
    if not history.effective_window.contains(context.business_time):
        return 'unavailable', None
    changes, graph_records = [], []

    def graph(root, at, *, current_graph=False):
        rows, visiting, visited, cycle, complete = {}, set(), set(), False, True
        def visit(row):
            nonlocal cycle, complete
            key = row.ref.key()[:2]
            if key in rows and rows[key].ref != row.ref:
                raise TaskConflict('Readiness graph aliases one physical task through different versions')
            rows[key] = row
            if current_graph and (row.history_coverage != 'complete' or row.as_of != at):
                complete = False
            if key in visiting:
                cycle = True
                return
            if key in visited:
                return
            visiting.add(key)
            for predecessor_ref in physical(row.predecessor_task_refs).values():
                visit(read(predecessor_ref, ContractorReadyTaskView, at))
            visiting.remove(key); visited.add(key)
        visit(root)
        return rows, cycle, complete

    if code == STATE_CODE:
        if history.ref.key()[:2] != old['task'].ref.key()[:2] or history.state not in _STATES:
            raise TaskConflict('Original released/terminal task cannot be reset or replaced for another release')
    else:
        old_root = old['task'] if code == CYCLE_CODE else first
        new_root = current['task'] if code == CYCLE_CODE else history
        if code == REPLACEMENT_CODE and ref != current_replacements[first_ref.key()[:2]]:
            raise TaskConflict('Replacement query is not the actual original selected independent replacement')
        before_graph, was_cyclic, _ = graph(old_root, original.business_time)
        after_graph, is_cyclic, complete = graph(new_root, context.business_time, current_graph=True)
        if not was_cyclic:
            raise TaskConflict('Original readiness dependency graph does not contain its actual recorded cycle')
        if is_cyclic or not complete:
            return 'waiting', None
        for key, before in before_graph.items():
            after = after_graph.get(key)
            if after is not None:
                same_task(before, after)
                if set(physical(before.predecessor_task_refs)) != set(physical(after.predecessor_task_refs)):
                    if not after.evidence_refs:
                        return 'waiting', None
                    changes.append(dict(original=before.model_dump(mode='json'), current=after.model_dump(mode='json')))
        if not changes:
            return 'waiting', None
        graph_records = [dict(original=[row.model_dump(mode='json') for row in before_graph.values()],
            current=[row.model_dump(mode='json') for row in after_graph.values()])]
    evidence_refs = {value.key(): value for value in history.evidence_refs}
    for change in changes:
        evidence_refs.update({value.key(): value for value in
            [Reference.model_validate(raw_ref) for raw_ref in change['current']['evidence_refs']]})
    if not evidence_refs:
        return 'waiting', None
    evidence = []
    for evidence_ref in evidence_refs.values():
        row = reading.resolve(evidence_ref)
        if (not isinstance(row, EvidenceRecord) or row.ref != evidence_ref
                or row.source_kind == 'synthetic' or row.basis_kind != 'observed'):
            raise TaskConflict('Readiness recovery requires actual observed native task/independent cycle-resolution evidence')
        if row.effective_window is not None:
            if (row.effective_window.start.clock_ref != context.business_time.clock_ref
                    or row.effective_window.end.clock_ref != context.business_time.clock_ref
                    or not row.effective_window.contains(context.business_time)):
                return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    current_result = None
    if not terminal:
        current_result = readiness_role.check_task_readiness(context, current_input, reading)
        if current_result.get('kind') != 'completed':
            return 'waiting', None
        contract.validate_decision(current_input, current_result['payload'])
        current_result = contract.result_adapter.validate_python(current_result).model_dump(mode='json')
    resolution = dict(schema_version='contractor-readiness-history-resolution.v1', condition_code=code,
        disposition=history.state if code == STATE_CODE else 'actual_independent_readiness_cycle_resolution',
        history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_task=old['task'].model_dump(mode='json'), current_task=current['task'].model_dump(mode='json'),
        graphs=graph_records, dependency_changes=changes, evidence=evidence, sources=reading.evidence(),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'), current_result=current_result)
    if validate_relation(source_identity=deepcopy(source), condition_code=code, terminal_readiness_history=terminal,
            resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Readiness recovery lacks native task state/cycle resolution/remaining gate/current authority authentication')
    return 'ready', resolution


def contractor_original_readiness_profile(read_current, validate_relation, condition_code=STATE_CODE):
    if condition_code not in _CODES or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Readiness recovery requires original guarded task query and actual native validator')
    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_contractor_readiness_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()
    return ConditionProfile('CONTRACTOR-A06', condition_code, '2', frozenset({'dependency_change'}), evaluate)
