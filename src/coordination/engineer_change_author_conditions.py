"""Observe actual delegated author work without allowing the requester to revise it."""
from copy import deepcopy

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.engineer_change_objects import (
    EngineerChangeDeliverableView, EngineerChangeIssueView, EngineerChangeObligationView,
    EngineerChangeProfileView, EngineerChangeAuthorHandoffView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.engineer_change import handle_professional_change
from src.coordination.engineer_change_conditions import AUTHOR_HANDOFF_CODE, EngineerChangeConditionReading
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_ROLES = {'ENGINEER': 'Engineer', 'ARCHITECT': 'Architect', 'QS': 'QS', 'CONTRACTOR': 'Contractor',
    'OWN': 'Owner', 'GOV': 'Government', 'SUPPLIER': 'Supplier', 'BANK': 'Bank'}


def check_engineer_change_author_handoff(check, selected, validate_relation, *, terminal=False):
    source = check.source['identity']
    if (source['action_id'] != 'ENGINEER-A09' or source['role'] != 'Engineer' or source['purpose'] != 'action'
            or check.condition.condition_code != AUTHOR_HANDOFF_CODE or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('Deliverable', 'Issue')
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, EngineerChangeConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Author handoff requires its original private other-author revision wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.run_id != source['run_id']
            or context.contract_ref != original.contract_ref or context.contract_ref.id != 'ENGINEER-A09'
            or context.execution_mode != 'llm' or context.scope != original.scope
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'
            or terminal and (raw != current_raw or context.operation_id != source['request_id']
                or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or not terminal and context.operation_id == source['request_id']):
        raise TaskConflict('Author handoff substitutes original snapshot, scope, time or private read authority')
    reading.check_method_context(context, 'ENGINEER-A09')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'ENGINEER-A09' or contract.role != 'Engineer':
        raise TaskConflict('Author handoff lacks the original registered A09 contract')
    action_input = contract.validate_input(raw)
    if list(check.condition.object_refs) != [action_input.prior_deliverable_ref, action_input.issue_ref]:
        raise TaskConflict('Author handoff replaces original design and issue selection')

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            raise TaskConflict('Author handoff lacks exact typed original or native sources')
        available = getattr(row, 'available_at', None)
        if available is not None and (available.clock_ref != at.clock_ref or available.offset > at.offset):
            raise TaskConflict('Author handoff introduces sources unavailable at their original/observation time')
        return row

    parent = read(action_input.prior_deliverable_ref, EngineerChangeDeliverableView, original.business_time)
    issue = read(action_input.issue_ref, EngineerChangeIssueView, original.business_time)
    obligation = read(action_input.obligation_ref, EngineerChangeObligationView, original.business_time)
    profile = read(issue.change_profile_ref, EngineerChangeProfileView, original.business_time)
    if (profile.choice != 'revise' or profile.issue_ref != issue.ref or profile.obligation_ref != obligation.ref
            or issue.used_deliverable_ref != parent.ref or issue.obligation_ref != obligation.ref
            or obligation.deliverable_ref != parent.ref or obligation.organization_id != source['organization_id']
            or parent.author_organization_id == source['organization_id'] and parent.author_action_id in {'ENGINEER-A05', 'ENGINEER-A09'}):
        raise TaskConflict('Author handoff does not reproduce its original other-author design gate')
    # This validated gate precedes revision instruction, parameter work and design methods.
    original_gate = handle_professional_change(original, action_input, reading)
    if (original_gate.get('resume_condition', {}).get('condition_code') != AUTHOR_HANDOFF_CODE
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Author handoff differs from the original processor wait')
    if not terminal:
        # A native author task is separate work; it cannot enable the requester's A09 revision.
        return 'waiting', None
    history = read(selected.history_ref, EngineerChangeDeliverableView, context.business_time)
    excluded = {'ref', 'available_at', 'effective_window', 'evidence_refs', 'author_handoff_ref'}
    if (history.ref.key()[:2] != parent.ref.key()[:2] or history.ref == parent.ref and history != parent
            or history.model_dump(exclude=excluded) != parent.model_dump(exclude=excluded)
            or not {ref.key() for ref in parent.evidence_refs} <= {ref.key() for ref in history.evidence_refs}):
        raise TaskConflict('Author handoff rewrites original design, authorship, parameters or dependencies')
    if history.author_handoff_ref is None:
        return 'waiting', None
    handoff = read(history.author_handoff_ref, EngineerChangeAuthorHandoffView, context.business_time)
    if (handoff.run_id != source['run_id'] or handoff.source_organization_id != source['organization_id']
            or handoff.source_request_id != source['request_id'] or handoff.source_task_sha256 != task_digest(source)
            or handoff.source_context_sha256 != source['context_sha256'] or handoff.source_input_sha256 != source['input_sha256']
            or handoff.issue_ref != issue.ref or handoff.obligation_ref != obligation.ref
            or handoff.prior_deliverable_ref != parent.ref or handoff.original_content_sha256 != parent.content_sha256
            or handoff.scope != original.scope):
        raise TaskConflict('Author handoff borrows another source invocation, issue, obligation or design version')
    if handoff.status != 'accepted' or handoff.accepted_at is None:
        return 'waiting', None
    if handoff.as_of != context.business_time or not handoff.effective_window.contains(context.business_time):
        return 'unavailable', None
    target = handoff.target_context
    role = _ROLES.get(handoff.target_action_id.split('-')[0])
    if (target.run_id != context.run_id or target.scope != original.scope or target.execution_mode == 'offline_fixture'
            or target.operation_id == original.operation_id or target.task_ref == original.task_ref
            or target.read_token == original.read_token
            or target.contract_ref.kind != 'ActionContract' or target.contract_ref.id != handoff.target_action_id
            or role is None or handoff.target_authority_ref not in target.authorization_refs
            or parent.ref not in handoff.target_input_refs or handoff.target_task_ref not in handoff.target_input_refs
            or not {ref.key() for ref in handoff.target_input_refs} <= {ref.key() for ref in target.visible_refs}
            or len({ref.key()[:2] for ref in handoff.target_input_refs}) != len(handoff.target_input_refs)):
        raise TaskConflict('Author handoff lacks a distinct actual authorized native target task and original input lineage')
    points = [original.business_time, target.business_time, handoff.accepted_at, handoff.available_at, context.business_time]
    if any(point.clock_ref != context.business_time.clock_ref for point in points) or any(
            left.offset > right.offset for left, right in zip(points, points[1:])):
        raise TaskConflict('Author handoff lacks actual original, target, acceptance and receipt chronology')
    if handoff.handoff_kind == 'original_author':
        if (handoff.target_organization_id != parent.author_organization_id
                or role != _ROLES.get(parent.author_action_id.split('-')[0]) or handoff.integrator_mandate_ref is not None):
            raise TaskConflict('Author handoff substitutes the original professional author or role')
    elif handoff.integrator_mandate_ref is None or handoff.integrator_mandate_ref == handoff.target_authority_ref:
        raise TaskConflict('Integrator handoff requires a separately authenticated actual integration mandate')

    def authority(ref):
        grant = read(ref, Authorization, context.business_time)
        assignment = read(target.function_ref, RoleAssignment, context.business_time)
        if (grant.organization_id != handoff.target_organization_id or grant.actor_id != target.actor_id
                or grant.function_ref != target.function_ref or assignment.role != role
                or handoff.target_action_id not in grant.action_ids or not grant.validity.contains(target.business_time)
                or not any(scope_covers(scope, target.scope) for scope in grant.scopes)):
            raise TaskConflict('Author handoff lacks independent actual target author/function/scope authority')
        return grant.model_dump(mode='json'), assignment.model_dump(mode='json')

    target_grant, target_assignment = authority(handoff.target_authority_ref)
    mandate = None if handoff.integrator_mandate_ref is None else authority(handoff.integrator_mandate_ref)[0]
    evidence = []
    for ref in handoff.evidence_refs:
        row = read(ref, EvidenceRecord, context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Author handoff requires actual observed native acceptance evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    if not evidence:
        return 'unavailable', None
    resolution = dict(schema_version='engineer-change-author-handoff-resolution.v1', condition_code=AUTHOR_HANDOFF_CODE,
        disposition='actual_separate_author_task_accepted', history=handoff.model_dump(mode='json'),
        original_action_input=raw, action_input=current_raw, original_context=original.model_dump(mode='json'),
        context=context.model_dump(mode='json'), original_deliverable=parent.model_dump(mode='json'),
        current_deliverable=history.model_dump(mode='json'), original_issue=issue.model_dump(mode='json'),
        remaining_obligation=obligation.model_dump(mode='json'), original_profile=profile.model_dump(mode='json'),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'),
        target_authority=target_grant, target_function=target_assignment, integrator_mandate=mandate,
        evidence=evidence, sources=reading.evidence())
    if validate_relation(source_identity=deepcopy(source), condition_code=AUTHOR_HANDOFF_CODE, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Author handoff lacks independent native receipt/task/input, author rights and remaining-duty authentication')
    return 'ready', resolution
