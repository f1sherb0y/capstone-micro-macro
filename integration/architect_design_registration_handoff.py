"""Relate saved A05 drafts to actual registered options supplied to A06."""
from copy import deepcopy

from integration.architect_design_results import SavedArchitectDesign
from src.actions.contracts.architect_design_objects import (
    ArchitectDesignDraft, ArchitectDesignProfileView, ArchitectDesignRegistrationView, ArchitectDesignTaskView,
)
from src.actions.contracts.architect_integration_objects import ArchitectIntegrationOptionView
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import QSCostBriefView
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def prepare_architect_design_registration_handoff(saved, *, invocation, registration_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current):
    """Inspect native registration under the caller's source/authorization guard.

    The independent host gate checks actual registry/service authorship, full
    native draft content, receipt relation and private access. This creates no
    option and proves no Engineer/QS agreement, integration authority or approval.
    """
    context, reading = invocation.context, invocation.reading
    if (not isinstance(saved, SavedArchitectDesign) or saved.identity.action_id != 'ARCHITECT-A05'
            or saved.identity.role != 'Architect' or saved.identity.run_id != context.run_id
            or saved.identity.organization_id != reading.organization_id
            or context.contract_ref.id != 'ARCHITECT-A06' or saved.current_context.contract_ref.id != 'ARCHITECT-A05'
            or any(getattr(saved.current_context, name) != getattr(context, name) for name in
                ('run_id', 'actor_id', 'function_ref', 'scope', 'business_time', 'execution_mode'))
            or saved.context.scope != context.scope or saved.result.kind != 'completed' or saved.result.payload.choice != 'produce'
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or not callable(validate_current) or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Design handoff requires original saved produce evidence and separate current A05/A06 authority')
    reading.check_method_context(context, 'ARCHITECT-A06')
    result_sha256 = task_digest(saved.result.model_dump(mode='json'))
    if any(saved.audit.get(name) != value for name, value in {
            'run_id': context.run_id, 'action_id': 'ARCHITECT-A05', 'operation_id': saved.context.operation_id,
            'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha256, 'result_kind': 'completed'}.items()):
        raise TaskConflict('Design handoff lacks its original successful saved audit')
    target = Reference.model_validate(registration_ref)
    native = Reference.model_validate(native_evidence_ref)
    relations = [Reference.model_validate(ref) for ref in relation_evidence_refs]
    unique_refs(relations)
    if not relations or native in relations:
        raise TaskConflict('Design registration needs separate native and independent relation evidence')
    try:
        before_methods = reading.method_evidence()
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        task = ArchitectDesignTaskView.model_validate(originals[saved.action_input.task_ref.key()])
        profile = ArchitectDesignProfileView.model_validate(originals[saved.action_input.design_profile_ref.key()])
        brief = QSCostBriefView.model_validate(originals[saved.action_input.brief_ref.key()])
        registration = reading.resolve(target)
        if (not isinstance(registration, ArchitectDesignRegistrationView) or registration.ref != target
                or registration.run_id != context.run_id or registration.organization_id != reading.organization_id
                or registration.task_sha256 != saved.identity.key or registration.record_sha256 != saved.record_sha256
                or registration.result_sha256 != result_sha256 or registration.source_reading_sha256 != saved.source_reading_sha256
                or registration.source_task_ref != task.ref or registration.scope != saved.context.scope
                or registration.draft_index >= len(saved.result.payload.options)
                or registration.draft_index >= len(task.drafts)
                or registration.author_actor_id != saved.context.actor_id
                or registration.author_function_ref != saved.context.function_ref
                or registration.author_authority_ref != task.authority_ref
                or registration.author_authority_ref not in saved.context.authorization_refs):
            raise TaskConflict('Design registration substitutes original task, result, draft index, private scope or author')
        draft = ArchitectDesignDraft.model_validate(saved.result.payload.options[registration.draft_index].model_dump(mode='python'))
        if registration.draft != draft or draft != task.drafts[registration.draft_index]:
            raise TaskConflict('Design registration changes original variables, components, parent, evidence or unresolved questions')
        points = [saved.context.business_time, registration.authored_at, registration.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or not registration.effective_window.contains(context.business_time)):
            raise TaskConflict('Design registration changes original production or received-record chronology')
        if registration.registration_status != 'registered':
            code = 'original_architect_design_registration_' + registration.registration_status
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [registration.ref], 'earliest_time': None, 'condition_code': code}}
        option = reading.resolve(invocation.action_input.option_ref)
        if (not isinstance(option, ArchitectIntegrationOptionView) or option.ref != registration.option_ref
                or content_digest(option) != registration.option_sha256 or option.brief_ref != brief.ref
                or option.design_profile_ref != profile.ref or option.task_ref != task.ref or option.scope != draft.scope
                or option.object_type != profile.object_type or option.region_id != profile.region_id
                or option.compilation_status != 'completed' or option.unresolved_questions != draft.unresolved_questions
                or task.requested_use not in option.allowed_uses
                or not set(option.allowed_uses) <= set(brief.allowed_uses).intersection(profile.allowed_uses)
                or option.author_actor_id != registration.author_actor_id
                or option.author_function_ref != registration.author_function_ref
                or option.author_authority_ref != registration.author_authority_ref
                or registration.registered_at is None or registration.registered_at.clock_ref != context.business_time.clock_ref
                or not registration.authored_at.offset <= registration.registered_at.offset <= registration.available_at.offset
                or option.available_at.clock_ref != context.business_time.clock_ref
                or not registration.registered_at.offset <= option.available_at.offset <= context.business_time.offset
                or not option.effective_window.contains(context.business_time)):
            raise TaskConflict('Registered option changes the original full draft, option digest, allowed use or author/time')
        grant, assignment = reading.resolve(option.author_authority_ref), reading.resolve(option.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or assignment.role != 'Architect' or assignment.function_ref != option.author_function_ref
                or grant.organization_id != reading.organization_id or grant.actor_id != option.author_actor_id
                or grant.function_ref != option.author_function_ref or 'ARCHITECT-A05' not in grant.action_ids
                or not any(scope_covers(scope, draft.scope) for scope in grant.scopes)
                or not grant.validity.contains(registration.authored_at) or not grant.validity.contains(option.available_at)):
            raise TaskConflict('Registered design option lacks original independent Architect author authority')
        evidence = []
        for ref in [native, *relations, *registration.evidence_refs, *option.evidence_refs, *grant.basis_refs, *assignment.basis_refs]:
            row = reading.resolve(ref)
            if (not isinstance(row, EvidenceRecord) or row.ref != ref or row.source_kind == 'synthetic'
                    or ref in [native, *relations] and row.basis_kind != 'observed'
                    or row.effective_window is not None and not row.effective_window.contains(context.business_time)):
                raise TaskConflict('Design handoff lacks current actual native, relation or author evidence')
            if ref in [native, *relations]:
                evidence.append(row.model_dump(mode='json'))
        # Evidence lists can overlap; retain one copy in native/relation order.
        evidence = list({Reference.model_validate(row['ref']).key(): row for row in evidence}.values())
        if evidence[0]['content_hash'] != native_source_sha256:
            raise TaskConflict('Design registration changes its actual native source hash')
        if validate_current(saved=deepcopy(saved), task=task.model_copy(deep=True), draft=draft.model_copy(deep=True),
                registration=registration.model_copy(deep=True), option=option.model_copy(deep=True), evidence=deepcopy(evidence),
                context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Design registration requires actual full native content, registry authority, receipt relation and privacy checks')
        if reading.method_evidence() != before_methods:
            raise TaskConflict('Design registration source gate must not execute methods')
        return {'kind': 'prepared', 'source_mode': 'formal', 'option_ref': option.ref,
            'registration_status': registration.registration_status, 'provenance': {
                'task_sha256': saved.identity.key, 'record_sha256': saved.record_sha256,
                'result_sha256': result_sha256, 'source_reading_sha256': saved.source_reading_sha256,
                'draft_sha256': content_digest(draft), 'registration_sha256': content_digest(registration),
                'option_sha256': content_digest(option), 'native_source_sha256': native_source_sha256,
                'evidence_sha256': task_digest(evidence)}}
    finally:
        reading.recheck()
