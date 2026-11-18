"""Reconcile original commercial executions before scheduling fresh A12 work.

An event only prompts a read. These conditions do not submit, retry, release
resources or treat a received event as proof of execution or business readiness.
"""
from copy import deepcopy

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.commercial_continuation_objects import (
    CommercialExecutionView, CommercialOriginalExecutionView, CommercialContinuationProfileView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_execution_objects import SupplierProductionExecutionView
from src.actions.contracts.supplier_logistics_objects import SupplierShipmentView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.coordination.commercial_execution_query import CommercialExecutionConditionReading, check_commercial_execution
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


LATE_EXECUTION_CODES = frozenset({'query_original_late_work_execution', 'query_original_late_supplier_execution'})


def _check_late_execution_history(original, current):
    """Keep known original outcomes/events while allowing shipment progress."""
    kind = original.ref.kind
    terminal = {'received', 'failed', 'rejected'} if kind == 'Shipment' else _EXECUTIONS[kind][2]
    if original.status in terminal and current.status != original.status:
        raise TaskConflict('Commercial late execution query rewrites a known original terminal outcome')
    if kind == 'Shipment':
        progress = {'dispatched': 0, 'in_transit': 1, 'arrived': 2, 'received': 3}
        if (original.status in progress and current.status not in {'failed', 'rejected'}
                and (current.status not in progress or progress[current.status] < progress[original.status])):
            raise TaskConflict('Commercial late shipment query reverses known physical dispatch progress')
    for field in ('core_event_id', 'recorded_at', 'dispatched_at'):
        before = getattr(original, field, None)
        after = getattr(current, field, None)
        if before is not None:
            if hasattr(before, 'model_dump'):
                before = before.model_dump(mode='json')
            if hasattr(after, 'model_dump'):
                after = after.model_dump(mode='json')
            if task_digest(before) != task_digest(after):
                raise TaskConflict('Commercial late execution query replaces a known original event or execution time')
    # available_at is knowledge time, never a substitute for the actual event.
    for row in (original, current):
        field = 'recorded_at' if kind == 'ProductionExecution' else 'dispatched_at' if kind == 'Shipment' else None
        at = getattr(row, field, None) if field is not None else None
        if at is not None and (at.clock_ref != row.available_at.clock_ref or at.offset > row.available_at.offset):
            raise TaskConflict('Commercial late execution source precedes its actual recorded event')


def _authenticate_formal_late_execution(check, selected, original, current, evidence, validate_relation):
    """Authenticate the original late operation, retaining both complete states."""
    from src.actions.contracts.commercial_continuation_objects import commercial_continuation_types
    from src.actions.contracts.supplier_continuation_objects import supplier_continuation_types
    from src.coordination.commercial_state_continuity import check_commercial_state_continuity

    source = check.source['identity']
    if (not isinstance(selected, CommercialExecutionConditionReading)
            or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.original_action_input, dict) or not isinstance(selected.action_input, dict)
            or not callable(validate_relation)):
        raise TaskConflict('Formal commercial late query requires original saved input/context and native authentication')
    context, reading, before = selected.context, selected.reading, selected.original_context
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (source['purpose'] != 'action' or source['role'] != {'CONTRACTOR-A12': 'Contractor', 'SUPPLIER-A12': 'Supplier'}[source['action_id']]
            or task_digest(raw) != source['input_sha256']
            or task_digest(before.model_dump(mode='json')) != source['context_sha256']
            or before.operation_id != source['request_id'] or context.operation_id == source['request_id']
            or context.execution_mode != 'llm' or before.run_id != context.run_id
            or context.contract_ref != before.contract_ref or context.scope != before.scope
            or context.actor_id != before.actor_id or context.function_ref != before.function_ref
            or context.business_time.clock_ref != before.business_time.clock_ref
            or context.business_time.offset < before.business_time.offset
            or task_digest(raw.get('scope_ref')) != task_digest(before.scope.model_dump(mode='json'))
            or task_digest(current_raw.get('scope_ref')) != task_digest(context.scope.model_dump(mode='json'))):
        raise TaskConflict('Formal commercial late query changes original identity, authority, scope or chronology')
    types = supplier_continuation_types() if source['action_id'] == 'SUPPLIER-A12' else commercial_continuation_types()
    original_profile = reading.resolve(Reference.model_validate(raw['continuation_profile_ref']))
    profile = reading.resolve(Reference.model_validate(current_raw['continuation_profile_ref']))
    if selected.profile_ref != getattr(profile, 'ref', None):
        raise TaskConflict('Formal commercial late query replaces its current profile')
    check_commercial_state_continuity(reading=reading, types=types, original_profile=original_profile,
        profile=profile, original_context=before, context=context, organization_id=source['organization_id'],
        supplier=source['action_id'] == 'SUPPLIER-A12')
    original_state, state = (reading.resolve(row.state_ref) for row in (original_profile, profile))
    def keys(refs):
        result = {ref.key() for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Commercial late query repeats closed input references')
        return result

    def evidence_refs(refs, at):
        if at.clock_ref != context.business_time.clock_ref or at.offset > context.business_time.offset:
            raise TaskConflict('Commercial late query changes actual evidence use time')
        for ref in refs:
            evidence = reading.resolve(ref)
            if not isinstance(evidence, EvidenceRecord) or evidence.ref != ref:
                raise TaskConflict('Commercial late query lacks exact typed original evidence')
            if evidence.effective_window is not None and not evidence.effective_window.contains(at):
                raise TaskConflict('Commercial late query evidence was not valid at its actual use point')

    def authorize(ref, actor, function_ref, organization, action, at, target):
        grant, function = reading.resolve(ref), reading.resolve(function_ref)
        roles = {'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier', 'OWN': 'Owner', 'BANK': 'Bank',
            'GOV': 'Government', 'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer', 'QS': 'QS'}
        if (at.clock_ref != context.business_time.clock_ref or at.offset > context.business_time.offset
                or not isinstance(grant, Authorization) or grant.ref != ref
                or not isinstance(function, RoleAssignment) or function.function_ref != function_ref
                or grant.actor_id != actor or grant.organization_id != organization or grant.function_ref != function_ref
                or function.role != roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not grant.validity.contains(at) or not any(scope_covers(scope, target) for scope in grant.scopes)):
            raise TaskConflict('Commercial late query lacks exact independent original actor/function/scope authority')
        for basis_ref in [*grant.basis_refs, *function.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence_refs([basis_ref], at)
            else:
                basis = reading.resolve(basis_ref)
                if hasattr(basis, 'available_at') and (basis.available_at.clock_ref != at.clock_ref
                        or basis.available_at.offset > at.offset):
                    raise TaskConflict('Commercial late query author basis was unavailable at actual use')
        return grant

    def author(row):
        if (row.authored_at.clock_ref != context.business_time.clock_ref
                or row.authored_at.offset > row.available_at.offset
                or not row.effective_window.contains(row.authored_at)):
            raise TaskConflict('Commercial late query source precedes actual original authorship')
        evidence_refs(row.evidence_refs, row.authored_at)
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at, row.scope)

    input_links = {'obligation_refs': 'obligation_refs', 'observation_refs': 'observation_refs'}
    input_links.update({'commitment_refs': 'commitment_refs', 'inventory_refs': 'material_refs',
        'work_in_progress_refs': 'work_in_progress_refs', 'shipment_refs': 'shipment_refs'}
        if source['action_id'] == 'SUPPLIER-A12' else
        {'resource_commitment_refs': 'commitment_refs', 'material_position_refs': 'material_refs'})
    bases = []
    for action_input, invocation, row, firm_state in (
            (raw, before, original_profile, original_state), (current_raw, context, profile, state)):
        basis = reading.resolve(row.basis_ref)
        grant, function = reading.resolve(row.authority_ref), reading.resolve(row.function_ref)
        if (not isinstance(basis, types['ContinuationBasis']) or basis.ref != row.basis_ref
                or basis.organization_id != source['organization_id'] or basis.state_ref != firm_state.ref
                or row.author_organization_id != source['organization_id']
                or row.actor_id != invocation.actor_id or row.function_ref != invocation.function_ref
                or row.authority_ref not in invocation.authorization_refs
                or not isinstance(grant, Authorization) or grant.ref != row.authority_ref
                or grant.organization_id != source['organization_id'] or grant.actor_id != invocation.actor_id
                or grant.function_ref != invocation.function_ref or source['action_id'] not in grant.action_ids
                or not grant.validity.contains(invocation.business_time)
                or not any(scope_covers(scope, invocation.scope) for scope in grant.scopes)
                or not isinstance(function, RoleAssignment) or function.function_ref != invocation.function_ref
                or function.role != source['role']
                or keys([Reference.model_validate(ref) for ref in action_input['authority_basis_refs']]) != keys(basis.evidence_refs)
                or any(keys([Reference.model_validate(ref) for ref in action_input[field]]) != keys(getattr(firm_state, state_field))
                    for field, state_field in input_links.items())):
            raise TaskConflict('Commercial late query replaces original/current profile authority, basis or closed input')
        for item in (row, basis):
            if (item.available_at.clock_ref != invocation.business_time.clock_ref
                    or item.available_at.offset > invocation.business_time.offset):
                raise TaskConflict('Commercial late query introduces a profile/basis unavailable at its original read point')
            if not item.effective_window.contains(invocation.business_time):
                raise TaskConflict('Commercial late query loses the original valid profile/basis')
            author(item)
        evidence_refs(firm_state.evidence_refs, invocation.business_time)
        evidence_refs(basis.evidence_refs, invocation.business_time)
        authorize(row.authority_ref, invocation.actor_id, invocation.function_ref, source['organization_id'],
            source['action_id'], invocation.business_time, invocation.scope)
        bases.append(basis.model_dump(mode='json'))
    if original.ref.kind == 'OriginalWorkExecution':
        linked = any(ref == original.work_record_ref
            and reading.resolve(ref).execution_ref == original.ref for ref in original_state.work_record_refs)
    elif original.ref.kind == 'ProductionExecution':
        linked = any(reading.resolve(ref).execution_ref == original.ref
            and reading.resolve(ref).task_ref == original.task_ref for ref in original_state.work_in_progress_refs)
    else:
        linked = original.ref in original_state.shipment_refs
    if not linked:
        raise TaskConflict('Commercial late query is unrelated to the original saved work or supplier goods')
    resolution = {'schema_version': 'commercial-late-execution-resolution.v1',
        'original_context': before.model_dump(mode='json'), 'context': context.model_dump(mode='json'),
        'original_action_input': raw, 'action_input': current_raw,
        'original_execution': original.model_dump(mode='json'), 'execution': current.model_dump(mode='json'),
        'original_profile': original_profile.model_dump(mode='json'), 'profile': profile.model_dump(mode='json'),
        'original_state': original_state.model_dump(mode='json'), 'state': state.model_dump(mode='json'),
        'original_basis': bases[0], 'basis': bases[1],
        'evidence': deepcopy(evidence)}
    if validate_relation(source_identity=deepcopy(source), condition_code=check.condition.condition_code,
            terminal_execution=False, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Commercial late execution query lacks actual original native operation/history authentication')


_EXECUTIONS = {
    'ContinuationExecution': (
        CommercialExecutionView,
        ('organization_id','run_id','state_ref','business_key','profile_ref','profile_sha256'),
        frozenset({'succeeded','failed','rejected'}),
    ),
    'OriginalWorkExecution': (
        CommercialOriginalExecutionView,
        ('organization_id','run_id','work_record_ref'),
        frozenset({'succeeded','failed','rejected'}),
    ),
    'ProductionExecution': (
        SupplierProductionExecutionView,
        ('organization_id','run_id','task_ref','operation_id','business_key','request_ref','request_sha256'),
        frozenset({'recorded','failed','rejected'}),
    ),
    'Shipment': (
        SupplierShipmentView,
        ('organization_id','run_id','order_ref','operation_id','command_id','business_key',
         'physical_batch_key','slice_refs','plan','request_sha256'),
        frozenset({'dispatched','in_transit','arrived','received','failed','rejected'}),
    ),
}


def commercial_execution_profiles(read_current, validate_relation=None):
    """Return five explicit A12 execution-query condition profiles.

    The trusted host supplies (fresh ActionContext, ActionReadView, current
    Reference). Both original and current object versions must be available in
    that authorized read view. The next task still needs the journal's prepare
    and revalidate callbacks and normal action checks. Missing query evidence
    leaves the task pending; this never authorizes resubmission.
    """
    if not callable(read_current):
        raise ValueError('A current authorized execution reader is required')

    def profile(action_id, code, kinds):
        def evaluate(check):
            source = check.source['identity']
            if (source['action_id'] != action_id or check.condition.condition_code != code
                    or check.condition.trigger != 'dependency_change'
                    or check.signal.run_id != source['run_id']
                    or check.signal.organization_id != source['organization_id']):
                raise TaskConflict('Commercial condition differs from its original task and recipient')
            old_refs = check.condition.object_refs
            if len(old_refs) != 1 or old_refs[0].kind not in kinds:
                raise TaskConflict('Commercial query requires one original execution reference')
            selected = read_current(check)
            if (code == 'query_original_commercial_transition_execution'
                    and isinstance(selected, CommercialExecutionConditionReading) and selected.original_context is not None):
                try:
                    return check_commercial_execution(check, selected, validate_relation)[0]
                finally:
                    selected.reading.recheck()
            context, reading, ref = selected
            if (not isinstance(context, ActionContext) or not isinstance(reading, ActionReadView)
                    or not isinstance(ref, Reference)):
                raise TaskConflict('Commercial condition requires a typed current authorized reading')
            if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != action_id
                    or context.business_time != check.signal.business_time):
                raise TaskConflict('Commercial condition changes run, organization, action or current time')
            reading.check_method_context(context, action_id)
            old_ref = old_refs[0]
            if (ref.kind, ref.id) != (old_ref.kind, old_ref.id):
                raise TaskConflict('Commercial query replaces the original execution identity')
            try:
                if ref.version == old_ref.version:
                    return 'unavailable'
                original, current = reading.resolve(old_ref), reading.resolve(ref)
                schema, identity_fields, resolved_statuses = _EXECUTIONS[ref.kind]
                if not isinstance(original, schema) or not isinstance(current, schema):
                    raise TaskConflict('Commercial execution schema differs from its registered source')
                if original.ref != old_ref or current.ref != ref:
                    raise TaskConflict('Commercial query source reference mismatch')
                if (current.organization_id != source['organization_id'] or current.run_id != source['run_id']
                        or task_digest(original.model_dump(mode='json', include=set(identity_fields) | {'scope'}))
                            != task_digest(current.model_dump(mode='json', include=set(identity_fields) | {'scope'}))):
                    raise TaskConflict('Commercial query changes original request, content, scope or execution')
                if code in LATE_EXECUTION_CODES:
                    _check_late_execution_history(original, current)
                now = context.business_time
                if ref.kind == 'ContinuationExecution':
                    executed_profile = reading.resolve(current.profile_ref)
                    if (not isinstance(executed_profile, CommercialContinuationProfileView)
                            or executed_profile.ref != current.profile_ref or executed_profile.state_ref != current.state_ref
                            or executed_profile.organization_id != current.organization_id
                            or executed_profile.scope != current.scope or executed_profile.business_key != current.business_key
                            or content_digest(executed_profile) != current.profile_sha256):
                        raise TaskConflict('Commercial query substitutes the original execution profile or state version')
                    if (executed_profile.available_at.clock_ref != now.clock_ref
                            or executed_profile.available_at.offset > now.offset):
                        return 'unavailable'
                if (current.available_at.clock_ref != now.clock_ref or current.available_at.offset > now.offset
                        or current.effective_window.start.clock_ref != now.clock_ref
                        or current.effective_window.end.clock_ref != now.clock_ref
                        or not current.effective_window.contains(now)):
                    return 'unavailable'
                if hasattr(current, 'as_of') and current.as_of != now:
                    return 'unavailable'
                formal_late = reading._resolver.source_mode == 'formal' and code in LATE_EXECUTION_CODES
                observed = []
                for evidence_ref in current.evidence_refs:
                    evidence = reading.resolve(evidence_ref)
                    if not isinstance(evidence, EvidenceRecord):
                        raise TaskConflict('Commercial execution lacks its typed source evidence')
                    if formal_late and (evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed'):
                        raise TaskConflict('Formal commercial late query requires actual observed native evidence')
                    if evidence.effective_window is not None and (
                            evidence.effective_window.start.clock_ref != now.clock_ref
                            or evidence.effective_window.end.clock_ref != now.clock_ref
                            or not evidence.effective_window.contains(now)):
                        return 'unavailable'
                    observed.append(evidence.model_dump(mode='json'))
                if current.status not in resolved_statuses:
                    return 'waiting'
                if ref.kind == 'ContinuationExecution' and isinstance(selected, CommercialExecutionConditionReading):
                    current_profile = reading.resolve(selected.profile_ref)
                    if current_profile.business_key == current.business_key:
                        return 'waiting'
                if hasattr(current, 'query_status') and current.query_status != 'present':
                    return 'unavailable'
                if current.status in {'recorded','dispatched','in_transit','arrived','received'}:
                    if current.core_event_id is None:
                        return 'unavailable'
                    at = current.recorded_at if ref.kind == 'ProductionExecution' else current.dispatched_at
                    if at is None or at.clock_ref != now.clock_ref or at.offset > now.offset:
                        return 'unavailable'
                if formal_late:
                    if not observed:
                        return 'unavailable'
                    _authenticate_formal_late_execution(check, selected, original, current, observed, validate_relation)
                # Reconciled failure/rejection also unblocks a new decision;
                # it never becomes successful work or automatic completion.
                return 'ready'
            finally:
                reading.recheck()

        version = '3'
        return ConditionProfile(action_id, code, version, frozenset({'dependency_change'}), evaluate)

    profiles = []
    for action_id in ('CONTRACTOR-A12','SUPPLIER-A12'):
        profiles.extend([
            profile(action_id, 'query_original_commercial_transition_execution', {'ContinuationExecution'}),
            profile(action_id, 'query_original_late_work_execution', {'OriginalWorkExecution'}),
        ])
    profiles.append(profile('SUPPLIER-A12', 'query_original_late_supplier_execution', {'ProductionExecution','Shipment'}))
    return profiles


def commercial_continuation_profiles(read_current, validate_relation=None):
    """Explicit execution, resources, inventory, replies and readiness for A12."""
    from src.coordination.commercial_resource_conditions import commercial_resource_profiles
    from src.coordination.commercial_material_conditions import commercial_material_profiles
    from src.coordination.commercial_acceptance_conditions import commercial_acceptance_profiles
    from src.coordination.commercial_readiness_conditions import commercial_readiness_profiles
    from src.coordination.commercial_capacity_conditions import commercial_capacity_profiles
    from src.coordination.commercial_lesson_conditions import commercial_lesson_profiles

    return [*commercial_execution_profiles(read_current, validate_relation), *commercial_resource_profiles(read_current),
            *commercial_material_profiles(read_current), *commercial_acceptance_profiles(read_current),
            *commercial_readiness_profiles(read_current), *commercial_capacity_profiles(read_current),
            *commercial_lesson_profiles(read_current)]
