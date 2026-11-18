"""Explicitly reconcile A03 after actual all-task handoff, without invoking A03."""
from copy import deepcopy

from integration.task_continuation import observation_signal_matches
from src.actions.contracts.common import EvidenceRecord, ResumeCondition, ref_type, walk_references
from src.actions.contracts.government_scheduling_objects import (
    GovSchedulingTaskView, GovReviewAssignmentView, GovSchedulingWorkProfileView, GovQueueRuleView,
)
from src.coordination.continuations import ConditionCheck, ResumeSignal
from src.coordination.government_scheduling_conditions import _BASES, _HANDOFF_CODE
from src.coordination.government_scheduling_handoff import read_government_scheduling_handoff
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def reconcile_government_scheduling_handoff(*, identity, signal, reader, dispatcher, validate_relation):
    store = reader.snapshots.store
    signal = ResumeSignal.model_validate(signal).model_copy(deep=True)
    if (identity.action_id != 'GOV-A03' or identity.role != 'Government' or identity.purpose != 'action'
            or signal.run_id != identity.run_id or signal.organization_id != identity.organization_id):
        raise TaskConflict('Government terminal handoff changes original action/run/recipient')
    rows = [row for row in dispatcher.inbox.for_organization(run_id=identity.run_id,
        organization_id=identity.organization_id) if row['event_id'] == signal.event_id]
    if len(rows) != 1:
        raise TaskConflict('Government terminal handoff requires original persisted recipient feedback')
    projected = dispatcher.project_signal(deepcopy(rows[0]))
    if not observation_signal_matches(rows[0], projected, expected=signal):
        raise TaskConflict('Government terminal handoff replaces persisted original feedback projection')
    source = store.get(identity)
    if store.continuation(identity) is not None:
        raise TaskConflict('Government handoff already has a fresh scheduling successor')
    if len(source['conditions']) != 1:
        raise TaskConflict('Government terminal handoff requires its single original emitted completion wait')
    condition = ResumeCondition.model_validate(source['conditions'][0])
    if (condition.condition_code != _HANDOFF_CODE or condition.trigger != 'dependency_change'
            or len(condition.object_refs) != 1 or condition.object_refs[0].kind != 'Task'
            or source['state'] not in {'waiting_input', 'wait_resolved'}):
        raise TaskConflict('Government terminal reconciliation replaces its original completed-task wait')
    if not dispatcher.journal._matches(condition, signal):
        raise TaskConflict('Government terminal reconciliation lacks a matching actual completion invalidation')
    selected = reader(ConditionCheck(deepcopy(source), condition, signal))
    reading, context = selected.reading, selected.context
    proof_rows, proof_refs, versions = [], [], []
    try:
        if task_digest(selected.original_action_input) != identity.input_sha256:
            raise TaskConflict('Government terminal reconciliation changes original invocation input')

        def read(ref, schema):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref != ref or row.scope != context.scope:
                raise TaskConflict('Government terminal handoff lacks exact scoped source records')
            proof_rows.append(row)
            return row

        for raw in (selected.original_action_input, selected.action_input):
            bases = {field: read(ref_type(kind).model_validate(raw[field]), schema) for field, kind, schema in _BASES}
            work = read(bases['ordering_profile_ref'].work_profile_ref, GovSchedulingWorkProfileView)
            rule = read(bases['queue_ref'].ordering_rule_ref, GovQueueRuleView)
            tasks = {ref.key()[:2]: read(ref, GovSchedulingTaskView)
                for ref in (ref_type('Task').model_validate(raw_ref) for raw_ref in raw['task_refs'])}
            assignments = {ref.key()[:2]: read(ref, GovReviewAssignmentView)
                for ref in (ref_type('ReviewAssignment').model_validate(raw_ref) for raw_ref in raw['existing_assignment_refs'])}
            case, queue, profile = (bases[field] for field in ('case_ref', 'queue_ref', 'ordering_profile_ref'))
            if (any(row.organization_id != identity.organization_id for row in (*bases.values(), work, rule))
                    or case.queue_ref != queue.ref or profile.case_ref != case.ref or profile.queue_ref != queue.ref
                    or rule.queue_ref != queue.ref or set(case.task_refs) != {row.ref for row in tasks.values()}
                    or len(tasks) != len(raw['task_refs']) or len(assignments) != len(raw['existing_assignment_refs'])):
                raise TaskConflict('Government terminal handoff substitutes original case/queue or task/assignment set')
            versions.append(dict(**bases, work=work, rule=rule, tasks=tasks, assignments=assignments))
        old, current = versions
        if not old['tasks'] or current['tasks'] or current['assignments'] or current['case_ref'].task_refs:
            raise TaskConflict('Government terminal handoff requires all original work and no active scheduling tasks')
        if (any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field, _, _ in _BASES)
                or old['work'].ref.key()[:2] != current['work'].ref.key()[:2]
                or old['rule'].ref.key()[:2] != current['rule'].ref.key()[:2]
                or old['case_ref'].matter_ref != current['case_ref'].matter_ref
                or old['case_ref'].jurisdiction_ref.key()[:2] != current['case_ref'].jurisdiction_ref.key()[:2]
                or old['ordering_profile_ref'].choice != current['ordering_profile_ref'].choice
                or current['capacity_ref'].coverage != 'complete' or current['capacity_ref'].as_of != context.business_time):
            raise TaskConflict('Government terminal handoff rewrites original case/work/choice or current full occupancy')
        completion_refs = {ref.key()[:2]: ref for ref in selected.completed_task_refs}
        if completion_refs.keys() != old['tasks'].keys():
            raise TaskConflict('Government terminal handoff requires an explicit completion version for every original task')
        waited = condition.object_refs[0]
        if old['tasks'].get(waited.key()[:2]) is None or old['tasks'][waited.key()[:2]].ref != waited:
            raise TaskConflict('Government terminal handoff differs from its original emitted task')
        grant = reading.resolve(current['ordering_profile_ref'].authority_ref)
        function = reading.resolve(context.function_ref)
        if (not isinstance(grant, Authorization) or grant.ref != current['ordering_profile_ref'].authority_ref
                or not isinstance(function, RoleAssignment) or function.function_ref != context.function_ref
                or function.role != 'Government' or grant.function_ref != context.function_ref
                or grant.actor_id != context.actor_id or grant.organization_id != identity.organization_id
                or 'GOV-A03' not in grant.action_ids or not grant.validity.contains(context.business_time)
                or not any(scope_covers(scope, context.scope) for scope in grant.scopes)):
            raise TaskConflict('Government terminal handoff lacks current actual agency reconciliation authority')
        proof_refs.extend([*grant.basis_refs, *function.basis_refs])
        handoffs, investments, original_occupancy = [], set(), set()
        for assignment in old['assignments'].values():
            keys = {ref.key()[:2] for ref in assignment.commitment_refs}
            if len(keys) != len(assignment.commitment_refs) or original_occupancy.intersection(keys):
                raise TaskConflict('Government terminal handoff duplicates original owned occupancy')
            original_occupancy.update(keys)
        for key, original_task in old['tasks'].items():
            handoff = read_government_scheduling_handoff(reading=reading, original=old, current=current,
                waited=[original_task.ref], completed_task_ref=completion_refs[key], now=context.business_time,
                read=read, terminal=True, require_original_completed=original_task.ref == waited)
            if isinstance(handoff, str):
                raise TaskConflict('Government terminal handoff still lacks complete zero-work or released-occupancy evidence')
            completion = handoff['completion']
            for fact in completion['histories']['current']['work_facts']:
                if fact['investment_key'] in investments:
                    raise TaskConflict('Government terminal handoff counts one actual investment across multiple tasks')
                investments.add(fact['investment_key'])
            proof_rows.extend(row for row, _ in completion['proof_rows'])
            proof_refs.extend(ref for ref, _ in completion['proof_refs'])
            handoffs.append(dict(completed_task=handoff['completed_task'].model_dump(mode='json'),
                released_assignment=None if handoff['released_assignment'] is None
                    else handoff['released_assignment'].model_dump(mode='json'), completed_work_history=completion['histories']))
        expected = {row.existing_assignment_ref for row in old['tasks'].values() if row.existing_assignment_ref is not None}
        if expected != {row.ref for row in old['assignments'].values()}:
            raise TaskConflict('Government terminal handoff cannot discard an unrelated original assignment')
        for row in proof_rows:
            proof_refs.extend(ref for ref in walk_references(row) if ref.kind == 'Evidence')
        evidence = {}
        for ref in proof_refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                raise TaskConflict('Government terminal handoff requires actual observed native completion evidence')
            evidence[ref.key()] = row.model_dump(mode='json')
        resolution = dict(schema_version='government-scheduling-terminal-handoff.v1',
            reason_code='original_scheduling_tasks_formally_handed_off', signal=signal.model_dump(mode='json'),
            context=context.model_dump(mode='json'), original_action_input=deepcopy(selected.original_action_input),
            current_action_input=deepcopy(selected.action_input), handoffs=handoffs,
            scheduling_sources=deepcopy(selected.scheduling_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
            evidence=list(evidence.values()))
        if validate_relation(source_identity=identity.as_dict(), original_source=deepcopy(source),
                condition_code=_HANDOFF_CODE, terminal_handoff=True, resolution=deepcopy(resolution),
                context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Government terminal handoff lacks independent native all-task/occupancy reconciliation')
        reader._check()
        reading.recheck()
        previous = store.wait_resolution(identity)
        if previous is not None:
            if previous['resolution']['handoffs'] != handoffs:
                raise TaskConflict('Government terminal reconciliation rewrites its archived completed work')
            return previous
        return store.resolve_wait(identity, source['revision'], resolution=resolution,
            validate_resolution=lambda current_source, _: current_source == source)
    finally:
        reading.recheck()
        reader._check()
