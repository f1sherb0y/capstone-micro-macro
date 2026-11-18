"""Resume the original GOV-A12 work dependency without fabricating work or policy effects."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, ref_type, walk_references
from src.actions.contracts.government_feedback_objects import (
    GovObservationProfileView, GovWorkingAuthorityView, GovPolicyControlView,
    GovFeedbackTaskView, GovFeedbackDependencyView, GovReceivedFeedbackView, GovVisibleStatisticView,
    GovFeedbackAssignmentView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.coordination.government_feedback_assignment_query import GovernmentFeedbackAssignmentQueryRecord
from src.coordination.government_feedback_execution_query import EXECUTION_CODE
from src.coordination.government_feedback_capacity import read_feedback_capacity
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'government_feedback_work_dependency_pending'
_ASSIGNMENT_CODE = 'query_original_feedback_work_assignment'
_CAPACITY_CODE = 'government_feedback_work_capacity_unavailable'
_CODES = (_CODE, _ASSIGNMENT_CODE, EXECUTION_CODE, _CAPACITY_CODE)
_FIELDS = frozenset({'scope', 'feedback_refs', 'visible_statistic_refs', 'observation_profile_ref',
    'working_authority_ref', 'policy_control_profile_ref'})
_BASES = (('observation_profile_ref', 'ObservationProfile', GovObservationProfileView),
    ('working_authority_ref', 'Authority', GovWorkingAuthorityView))
_OPTIONAL = (('policy_control_profile_ref', 'PolicyControlProfile', GovPolicyControlView),)


@dataclass(frozen=True)
class GovernmentFeedbackConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict
    original_context: ActionContext
    feedback_sources: list[dict] | None = None
    unavailable_targets: list[dict] | None = None
    assignment_query: dict | None = None
    execution_query: dict | None = None


def government_original_feedback_dependency_profile(read_current, validate_relation):
    return _original_feedback_work_profile(read_current, validate_relation, _CODE)


def government_original_feedback_assignment_profile(read_current, validate_relation):
    return _original_feedback_work_profile(read_current, validate_relation, _ASSIGNMENT_CODE)


def government_original_feedback_capacity_profile(read_current, validate_relation):
    return _original_feedback_work_profile(read_current, validate_relation, _CAPACITY_CODE)


def _original_feedback_work_profile(read_current, validate_relation, condition_code):
    assignment_wait = condition_code == _ASSIGNMENT_CODE
    capacity_wait = condition_code == _CAPACITY_CODE
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Feedback dependency recovery requires guarded sources and independent native validation')

    def physical(value):
        if isinstance(value, dict):
            return {key: physical(item) for key, item in value.items()
                if not (key == 'version' and set(value) == {'kind', 'id', 'version'})}
        if isinstance(value, list):
            return [physical(item) for item in value]
        return value

    def identities(refs):
        keys = {ref.key()[:2] for ref in refs}
        if len(keys) != len(refs):
            raise TaskConflict('Feedback dependency recovery duplicates a physical history source')
        return keys

    def true(value):
        return isinstance(value, Known) and value.value is True

    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != 'GOV-A12' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != condition_code or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != (('ResourceCalendar',) if capacity_wait else
                    ('ReviewAssignment',) if assignment_wait else ('Dependency',))
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Feedback dependency recovery replaces original dependency/action/run/agency')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, GovernmentFeedbackConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.original_context, ActionContext) or not isinstance(selected.reading, ActionReadView)):
            raise TaskConflict('Feedback dependency recovery requires typed original/current invocation sources')
        reading, context = selected.reading, selected.context.model_copy(deep=True)
        raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
        try:
            if (set(raw) != _FIELDS or set(current_raw) != _FIELDS or task_digest(raw) != source['input_sha256']
                    or task_digest(selected.original_context.model_dump(mode='json')) != source['context_sha256']
                    or raw['scope'] != current_raw['scope'] or context.scope != selected.original_context.scope
                    or context.run_id != source['run_id'] or context.contract_ref.id != 'GOV-A12'
                    or context.execution_mode != 'llm' or context.operation_id == source['request_id']
                    or context.business_time != check.signal.business_time or reading._resolver.source_mode != 'formal'
                    or reading.organization_id != source['organization_id']
                    or context.business_time.clock_ref != selected.original_context.business_time.clock_ref
                    or context.business_time.offset < selected.original_context.business_time.offset):
                raise TaskConflict('Feedback dependency recovery changes original snapshot/scope/current invocation')
            reading.check_method_context(context, 'GOV-A12')
            versions, proof_rows, proof_refs = [], [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref:
                    raise TaskConflict('Feedback dependency recovery lacks exact original/current source versions')
                proof_rows.append(row)
                return row

            for action_input, invocation in ((raw, selected.original_context), (current_raw, context)):
                rows = {field: read(ref_type(kind).model_validate(action_input[field]), schema)
                    for field, kind, schema in (*_BASES, *_OPTIONAL) if action_input[field] is not None}
                profile, authority = rows['observation_profile_ref'], rows['working_authority_ref']
                if (profile.organization_id != source['organization_id'] or profile.actor_id != invocation.actor_id
                        or profile.function_ref != invocation.function_ref or profile.scope != invocation.scope
                        or profile.choice != 'change_work_arrangement' or profile.work_plan is None or not profile.work_plan.items
                        or profile.working_authority_ref != authority.ref or profile.coverage != 'complete'
                        or profile.as_of != invocation.business_time or authority.coverage != 'complete'
                        or authority.as_of != invocation.business_time or not true(authority.permitted)
                        or profile.choice not in authority.allowed_choices or authority.organization_id != source['organization_id']
                        or authority.actor_id != invocation.actor_id or authority.function_ref != invocation.function_ref
                        or profile.authority_ref not in invocation.authorization_refs):
                    raise TaskConflict('Feedback dependency recovery changes original complete work plan/agency/verifier authority')
                grant, function = reading.resolve(profile.authority_ref), reading.resolve(invocation.function_ref)
                if (not isinstance(grant, Authorization) or grant.ref != profile.authority_ref
                        or not isinstance(function, RoleAssignment) or function.function_ref != invocation.function_ref
                        or function.role != 'Government' or grant.actor_id != invocation.actor_id
                        or grant.organization_id != source['organization_id'] or grant.function_ref != invocation.function_ref
                        or 'GOV-A12' not in grant.action_ids or not grant.validity.contains(invocation.business_time)
                        or not any(scope_covers(covered, invocation.scope) for covered in grant.scopes)):
                    raise TaskConflict('Feedback dependency recovery lacks independent current/original working authorization')
                proof_refs.extend([*grant.basis_refs, *function.basis_refs])
                observations = {}
                for field, kind, schema, declared in (
                        ('feedback_refs', 'Feedback', GovReceivedFeedbackView, profile.feedback_refs),
                        ('visible_statistic_refs', 'Statistic', GovVisibleStatisticView, profile.statistic_refs)):
                    refs = [ref_type(kind).model_validate(ref) for ref in action_input[field]]
                    if {ref.key() for ref in refs} != {ref.key() for ref in declared}:
                        raise TaskConflict('Feedback dependency recovery substitutes original actually visible input set')
                    identities(refs)
                    observations[field] = [read(ref, schema) for ref in refs]
                identities([item.task_ref for item in profile.work_plan.items])
                if not {ref.key() for ref in authority.required_task_refs} <= {item.task_ref.key() for item in profile.work_plan.items}:
                    raise TaskConflict('Feedback dependency recovery omits original mandatory work')
                tasks, dependencies, assignments, first_pending = {}, {}, {}, None
                for item in profile.work_plan.items:
                    task = read(item.task_ref, GovFeedbackTaskView)
                    if (task.organization_id != source['organization_id'] or task.work_profile_ref != profile.work_plan.work_profile_ref
                            or task.status not in {'authorized', 'waiting'} or item.existing_assignment_ref != task.existing_assignment_ref
                            or {ref.key() for ref in item.dependency_refs} != {ref.key() for ref in task.dependency_refs}
                            or item.task_ref not in authority.authorized_task_refs):
                        raise TaskConflict('Feedback dependency recovery changes original authorized work task/dependencies/assignment')
                    identities(task.dependency_refs)
                    tasks[task.ref.key()[:2]] = task
                    for ref in task.dependency_refs:
                        dependency = read(ref, GovFeedbackDependencyView)
                        if dependency.task_ref != task.ref:
                            raise TaskConflict('Feedback dependency recovery borrows another original task dependency')
                        dependencies[ref.key()[:2]] = dependency
                        if not true(dependency.satisfied) and first_pending is None:
                            first_pending = dependency.ref
                    if item.existing_assignment_ref is not None:
                        assignment = read(item.existing_assignment_ref, GovFeedbackAssignmentView)
                        if assignment.task_ref != task.ref or assignment.organization_id != source['organization_id']:
                            raise TaskConflict('Feedback recovery borrows another original task assignment')
                        identities(assignment.commitment_refs)
                        assignments[assignment.ref.key()[:2]] = assignment
                        if assignment.status == 'unknown' and first_pending is None:
                            first_pending = assignment.ref
                versions.append(dict(**rows, tasks=tasks, dependencies=dependencies, assignments=assignments,
                    first_pending=first_pending, observations=observations))
            old, current = versions
            waited = check.condition.object_refs[0]
            original_gate_mismatch = (old['first_pending'] is not None or waited != old['working_authority_ref'].calendar_ref) if capacity_wait else old['first_pending'] != waited
            if original_gate_mismatch:
                raise TaskConflict('Feedback dependency recovery differs from original first unresolved work dependency')
            old_profile, profile = old['observation_profile_ref'], current['observation_profile_ref']
            if (any((field in old) != (field in current) or field in old and old[field].ref.key()[:2] != current[field].ref.key()[:2]
                        for field, _, _ in (*_BASES, *_OPTIONAL))
                    or old_profile.business_key != profile.business_key or old_profile.interpretation != profile.interpretation
                    or any(physical(getattr(old_profile, field).model_dump(mode='json')) != physical(
                        getattr(profile, field).model_dump(mode='json')) if getattr(old_profile, field) is not None
                        and getattr(profile, field) is not None else getattr(old_profile, field) != getattr(profile, field)
                        for field in ('investigation_request', 'policy_proposal'))
                    or physical([row.model_dump(mode='json') for row in old_profile.questions]) != physical(
                        [row.model_dump(mode='json') for row in profile.questions])
                    or physical(old_profile.work_plan.model_dump(mode='json')) != physical(profile.work_plan.model_dump(mode='json'))
                    or old['tasks'].keys() != current['tasks'].keys() or old['dependencies'].keys() != current['dependencies'].keys()
                    or old['assignments'].keys() != current['assignments'].keys()
                    or identities(old_profile.execution_refs) - identities(profile.execution_refs)
                    or old_profile.authority_ref.key()[:2] != profile.authority_ref.key()[:2]):
                raise TaskConflict('Feedback dependency recovery rewrites original business content/plan/retained execution history')
            for key, task in old['tasks'].items():
                excluded = {'ref', 'dependency_refs', 'available_at', 'effective_window', 'evidence_refs'}
                if physical(task.model_dump(exclude=excluded)) != physical(current['tasks'][key].model_dump(exclude=excluded)):
                    raise TaskConflict('Feedback dependency recovery rewrites original remaining effort, author, task or assignment')
            for key, before in old['dependencies'].items():
                after = current['dependencies'][key]
                if (before.task_ref.key()[:2] != after.task_ref.key()[:2] or before.scope != after.scope
                        or true(before.satisfied) and not true(after.satisfied)):
                    raise TaskConflict('Feedback dependency recovery rewrites prior satisfied work or dependency scope')
            for field in ('feedback_refs', 'visible_statistic_refs'):
                before = {row.ref.key()[:2]: row for row in old['observations'][field]}
                after = {row.ref.key()[:2]: row for row in current['observations'][field]}
                if before.keys() != after.keys() or any(before[key].model_dump(exclude={'ref'}) != after[key].model_dump(exclude={'ref'}) for key in before):
                    raise TaskConflict('Feedback dependency recovery rewrites actually received feedback/statistics or their authors/times/evidence')
            for key, before in old['assignments'].items():
                after = current['assignments'][key]
                if (before.task_ref.key()[:2] != after.task_ref.key()[:2] or before.scope != after.scope
                        or identities(before.commitment_refs) - identities(after.commitment_refs)):
                    raise TaskConflict('Feedback recovery drops original assignment or held commitment history')
            query = None
            capacity = None
            if capacity_wait:
                if current['first_pending'] is not None:
                    return 'waiting'
                capacity = read_feedback_capacity(reading=reading, old=old, current=current,
                    original_context=selected.original_context, context=context)
                if isinstance(capacity, str):
                    return capacity
                if not capacity['ready']:
                    return 'waiting'
                proof_rows.extend(capacity['proof_rows'])
                proof_refs.extend(capacity['proof_refs'])
                target = reading.resolve(current['working_authority_ref'].calendar_ref)
            elif assignment_wait:
                before = old['assignments'][waited.key()[:2]]
                target = current['assignments'][waited.key()[:2]]
                if before.status != 'unknown':
                    raise TaskConflict('Assignment recovery lacks original unknown assignment disposition')
                if selected.assignment_query is None:
                    return 'waiting'
                query = GovernmentFeedbackAssignmentQueryRecord.model_validate(deepcopy(selected.assignment_query))
                if (query.source_identity_sha256 != task_digest(source) or query.run_id != source['run_id']
                        or query.organization_id != source['organization_id'] or query.assignment_ref != before.ref
                        or query.task_ref != before.task_ref or query.queried_at != context.business_time):
                    raise TaskConflict('Assignment recovery changes original assignment/task or actual query time')
                if query.result == 'unknown' or target.status == 'unknown':
                    return 'waiting'
                if target.status != query.result:
                    raise TaskConflict('Assignment source conflicts with actual native query result')
                proof_refs.extend(query.evidence_refs)
            else:
                target = current['dependencies'][waited.key()[:2]]
                if not true(target.satisfied):
                    return 'waiting'
            now = context.business_time
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in (profile, current['working_authority_ref'], target)):
                return 'unavailable'
            proof_refs.extend(ref for row in proof_rows for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Feedback dependency recovery requires observed original work/feedback/history evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            extra = {} if query is None else {'assignment_query': query.model_dump(mode='json')}
            if capacity is not None:
                extra['capacity_history'] = deepcopy(capacity['history'])
            if validate_relation(source_identity=deepcopy(source), condition_code=condition_code,
                    original_action_input=raw, action_input=current_raw, original_context=selected.original_context.model_dump(mode='json'),
                    feedback_sources=deepcopy(selected.feedback_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
                    evidence=list(evidence.values()), context=context.model_copy(deep=True), reading=reading, **extra) is not True:
                raise TaskConflict('Feedback dependency recovery lacks native original emitted wait and actual dependency/history authentication')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('GOV-A12', condition_code, '1', frozenset({'dependency_change'}), evaluate)
