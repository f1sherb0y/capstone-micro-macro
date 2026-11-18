"""Authenticate original commercial execution gates and archive actual outcomes."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.commercial_continuation_objects import commercial_continuation_types
from src.actions.contracts.supplier_continuation_objects import supplier_continuation_types
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


EXECUTION_CODE = 'query_original_commercial_transition_execution'
TERMINAL = frozenset({'succeeded', 'failed', 'rejected'})
_PROFILE_METADATA = {'ref', 'state_ref', 'available_at', 'effective_window'}
_EXECUTION_METADATA = {'ref', 'available_at', 'effective_window', 'status', 'evidence_refs'}
_STATE_LINKS = ('contract_refs', 'commitment_refs', 'material_refs', 'obligation_refs',
    'observation_refs', 'work_record_refs', 'document_refs', 'responsibility_refs',
    'execution_refs', 'applied_observation_refs')


@dataclass(frozen=True)
class CommercialExecutionConditionReading:
    context: ActionContext
    reading: ActionReadView
    current_ref: Reference
    profile_ref: Reference
    original_context: ActionContext | None = None
    original_action_input: dict | None = None
    action_input: dict | None = None

    def __iter__(self):
        return iter((self.context, self.reading, self.current_ref))


def check_commercial_execution(check, selected, validate_relation, *, terminal=False):
    """Only a natively authenticated same-business outcome resolves a wait terminally."""
    source = check.source['identity']
    action_id = source['action_id']
    role = {'CONTRACTOR-A12': 'Contractor', 'SUPPLIER-A12': 'Supplier'}.get(action_id)
    if (role is None or source['role'] != role or source['purpose'] != 'action'
            or check.condition.condition_code != EXECUTION_CODE or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('ContinuationExecution',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, CommercialExecutionConditionReading)
            or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
            or not callable(validate_relation)):
        raise TaskConflict('Commercial execution query requires the original wait and authenticated formal reading')
    context, reading, original_context = selected.context, selected.reading, selected.original_context
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256']
            or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or original_context.operation_id != source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original_context.contract_ref
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != action_id
            or context.execution_mode != 'llm' or reading._resolver.source_mode != 'formal'
            or reading.organization_id != source['organization_id'] or context.scope != original_context.scope
            or context.actor_id != original_context.actor_id or context.function_ref != original_context.function_ref
            or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and raw != current_raw):
        raise TaskConflict('Commercial execution query replaces original snapshot, authority, scope or invocation')
    reading.check_method_context(context, action_id)
    types = supplier_continuation_types() if role == 'Supplier' else commercial_continuation_types()
    rows = {}

    def read(ref, schema):
        row = reading.resolve(ref)
        actual_ref = getattr(row, 'ref', getattr(row, 'function_ref', None))
        if not isinstance(row, schema) or actual_ref != ref:
            raise TaskConflict('Commercial execution query lacks exact typed original/current sources')
        rows[ref.key()] = row
        return row

    def keys(refs):
        result = {ref.key() for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Commercial execution query repeats original source references')
        return result

    def available(row, at):
        if (at.clock_ref != context.business_time.clock_ref or at.offset > context.business_time.offset
                or row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Commercial execution query introduces sources unavailable at the read point')

    def evidence_refs(refs, *, at=None, historic=False):
        point = context.business_time if at is None else at
        if point.clock_ref != context.business_time.clock_ref or point.offset > context.business_time.offset:
            raise TaskConflict('Commercial execution query changes the actual evidence use point')
        for ref in refs:
            evidence = read(ref, EvidenceRecord)
            if evidence.effective_window is not None:
                if (evidence.effective_window.start.clock_ref != point.clock_ref
                        or evidence.effective_window.start.offset > context.business_time.offset
                        or (at is not None or not historic) and not evidence.effective_window.contains(point)):
                    raise TaskConflict('Commercial execution evidence was not valid at its actual use point')

    def authorize(ref, actor, function_ref, organization, action, at, target):
        grant, function = read(ref, Authorization), read(function_ref, RoleAssignment)
        roles = {'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier', 'OWN': 'Owner', 'BANK': 'Bank',
            'GOV': 'Government', 'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer', 'QS': 'QS'}
        if (at.clock_ref != context.business_time.clock_ref or at.offset > context.business_time.offset
                or grant.organization_id != organization or grant.actor_id != actor or grant.function_ref != function_ref
                or function.function_ref != function_ref or function.role != roles.get(action.split('-')[0])
                or action not in grant.action_ids or not grant.validity.contains(at)
                or not any(scope_covers(scope, target) for scope in grant.scopes)):
            raise TaskConflict('Commercial execution query lacks exact original actor/function/scope authority')
        for basis_ref in [*grant.basis_refs, *function.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence_refs([basis_ref], at=at)
            else:
                basis = reading.resolve(basis_ref)
                if hasattr(basis, 'available_at'):
                    available(basis, at)
        return grant

    def author(row, at):
        available(row, at)
        if (row.authored_at.clock_ref != at.clock_ref or row.authored_at.offset > row.available_at.offset
                or not row.effective_window.contains(row.authored_at)):
            raise TaskConflict('Commercial execution query source precedes original actual authorship')
        evidence_refs(row.evidence_refs, at=row.authored_at)
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at, row.scope)

    versions = []
    for action_input, invocation in ((raw, original_context), (current_raw, context)):
        profile_ref = Reference.model_validate(action_input['continuation_profile_ref'])
        profile = read(profile_ref, types['ContinuationProfile'])
        state = read(profile.state_ref, types['ContinuationState'])
        basis = read(profile.basis_ref, types['ContinuationBasis'])
        at = original_context.business_time if terminal else invocation.business_time
        if (profile.organization_id != source['organization_id'] or profile.author_organization_id != source['organization_id']
                or state.organization_id != source['organization_id'] or state.run_id != source['run_id']
                or profile.scope != invocation.scope or state.scope != invocation.scope
                or profile.actor_id != invocation.actor_id or profile.function_ref != invocation.function_ref
                or state.coverage != 'complete' or state.as_of != at
                or basis.organization_id != source['organization_id'] or basis.state_ref != state.ref
                or action_input['scope_ref'] != invocation.scope.model_dump(mode='json')
                or keys([Reference.model_validate(ref) for ref in action_input['authority_basis_refs']]) != keys(basis.evidence_refs)):
            raise TaskConflict('Commercial execution query changes complete original firm state/profile/basis')
        author(profile, at)
        author(basis, at)
        available(state, at)
        for row in (profile, basis, state):
            if not row.effective_window.contains(at):
                raise TaskConflict('Commercial execution query loses original valid state/profile/basis')
        evidence_refs(state.evidence_refs, at=at)
        # The selected basis is also used as current action authority, separate
        # from the historical authorship of its signed record.
        evidence_refs(basis.evidence_refs, at=at)
        authority_context = original_context if terminal else invocation
        if profile.authority_ref not in authority_context.authorization_refs:
            raise TaskConflict('Commercial execution query lacks original action authority')
        authorize(profile.authority_ref, invocation.actor_id, invocation.function_ref,
            source['organization_id'], action_id, at, invocation.scope)
        input_links = {'obligation_refs': 'obligation_refs', 'observation_refs': 'observation_refs'}
        input_links.update({'commitment_refs': 'commitment_refs', 'inventory_refs': 'material_refs',
            'work_in_progress_refs': 'work_in_progress_refs', 'shipment_refs': 'shipment_refs'} if role == 'Supplier'
            else {'resource_commitment_refs': 'commitment_refs', 'material_position_refs': 'material_refs'})
        if any(keys([Reference.model_validate(ref) for ref in action_input[field]]) != keys(getattr(state, state_field))
                for field, state_field in input_links.items()):
            raise TaskConflict('Commercial execution query omits original closed input/state sources')
        history = [read(ref, types['ContinuationExecution']) for ref in state.execution_refs]
        if (len({row.ref.key()[:2] for row in history}) != len(history)
                or len({row.business_key for row in history}) != len(history)
                or any(row.organization_id != source['organization_id'] or row.run_id != source['run_id']
                    or row.state_ref.key()[:2] != state.ref.key()[:2] for row in history)):
            raise TaskConflict('Commercial execution query substitutes or repeats original business history')
        for row in history:
            available(row, at)
            # Status updates have no independent actual occurrence field.
            # Retain original unknown/terminal history without guessing one.
            evidence_refs(row.evidence_refs, historic=True)
        versions.append((profile, state, history))
    old_profile, old_state, old_history = versions[0]
    profile, state, history = versions[1]
    if selected.profile_ref != profile.ref or old_state.ref.key()[:2] != state.ref.key()[:2]:
        raise TaskConflict('Commercial execution query replaces original state or selected current profile')
    first = next((row for row in old_history if row.business_key == old_profile.business_key
        or row.status in {'pending', 'unknown'}), None)
    if first is None or tuple(check.condition.object_refs) != (first.ref,):
        raise TaskConflict('Commercial execution query differs from the original first execution gate')
    executed_profile = read(first.profile_ref, types['ContinuationProfile'])
    if (first.profile_sha256 != content_digest(executed_profile)
            or executed_profile.organization_id != first.organization_id or executed_profile.scope != first.scope
            or executed_profile.business_key != first.business_key
            or executed_profile.state_ref != first.state_ref):
        raise TaskConflict('Commercial execution query rewrites the original executed profile digest/business')
    author(executed_profile, original_context.business_time)
    same_business = first.business_key == old_profile.business_key
    if same_business and executed_profile.model_dump(exclude=_PROFILE_METADATA) != old_profile.model_dump(exclude=_PROFILE_METADATA):
        raise TaskConflict('Commercial execution query changes content under the original business identity')
    links = (*_STATE_LINKS, *('work_in_progress_refs', 'shipment_refs', 'production_line_commitment_refs')) if role == 'Supplier' else _STATE_LINKS
    if any(not {ref.key()[:2] for ref in getattr(old_state, field)} <= {ref.key()[:2] for ref in getattr(state, field)} for field in links):
        raise TaskConflict('Commercial execution query drops original obligations/resources/materials/history')
    by_id = {row.ref.key()[:2]: row for row in history}
    for before in old_history:
        after = by_id[before.ref.key()[:2]]
        if (before.model_dump(exclude=_EXECUTION_METADATA) != after.model_dump(exclude=_EXECUTION_METADATA)
                or before.status in TERMINAL and before.status != after.status):
            raise TaskConflict('Commercial execution query rewrites retained execution content/disposition')
    ref = selected.current_ref
    if ref.key()[:2] != first.ref.key()[:2]:
        raise TaskConflict('Commercial execution query replaces the original execution identity')
    execution = read(ref, types['ContinuationExecution'])
    if (execution.model_dump(exclude=_EXECUTION_METADATA) != first.model_dump(exclude=_EXECUTION_METADATA)
            or first.status in TERMINAL and execution.status != first.status):
        raise TaskConflict('Commercial execution query changes original content or actual terminal disposition')
    available(execution, context.business_time)
    if (execution.effective_window.start.clock_ref != context.business_time.clock_ref
            or execution.effective_window.end.clock_ref != context.business_time.clock_ref
            or not execution.effective_window.contains(context.business_time)):
        return 'unavailable', None
    if execution.status not in TERMINAL:
        return 'waiting', None
    if terminal and not same_business:
        raise TaskConflict('Only the original same-business execution can resolve this wait terminally')
    if not execution.evidence_refs:
        return 'waiting', None
    for evidence_ref in execution.evidence_refs:
        evidence = read(evidence_ref, EvidenceRecord)
        if evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed':
            raise TaskConflict('Commercial terminal execution requires actual observed query evidence')
        if evidence.effective_window is not None and (
                evidence.effective_window.start.clock_ref != context.business_time.clock_ref
                or evidence.effective_window.end.clock_ref != context.business_time.clock_ref
                or not evidence.effective_window.contains(context.business_time)):
            return 'unavailable', None
    resolution = dict(schema_version='commercial-execution-resolution.v1', disposition=execution.status,
        execution=execution.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original_context.model_dump(mode='json'), context=context.model_dump(mode='json'),
        sources=[row.model_dump(mode='json') for row in rows.values()])
    if validate_relation(source_identity=deepcopy(source), condition_code=EXECUTION_CODE,
            terminal_execution=terminal, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Commercial execution query lacks native query/history/current authorization authentication')
    if not terminal:
        if same_business or any(row.business_key == profile.business_key or row.status not in TERMINAL for row in history):
            return 'waiting', None
        if by_id[first.ref.key()[:2]] != execution:
            raise TaskConflict('Commercial current execution history conflicts with actual query')
    return 'ready', resolution
