"""Relate saved A06 integration drafts to actual deliverable versions for A07."""
from copy import deepcopy

from integration.architect_integration_results import SavedArchitectIntegration
from src.actions.contracts.architect_integration_objects import (
    ArchitectIntegrationOptionView, ArchitectIntegrationProfileView, ArchitectRegisteredIntegrationDraft,
)
from src.actions.contracts.architect_submission_objects import (
    ArchitectIntegrationRegistrationView, ArchitectSubmissionDeliverableView,
)
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def prepare_architect_integration_registration_handoff(saved, *, invocation, registration_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current):
    """Inspect actual registry content under the caller's source/authority guard.

    The independent gate verifies full native content, artifact/task/dependency
    lineage, service authority, receipt relation and private access. Registration
    proves no actual task completion, independent acceptance or permitted use.
    """
    context, reading = invocation.context, invocation.reading
    if (not isinstance(saved, SavedArchitectIntegration) or saved.identity.action_id != 'ARCHITECT-A06'
            or saved.identity.role != 'Architect' or saved.identity.run_id != context.run_id
            or saved.identity.organization_id != reading.organization_id
            or context.contract_ref.id != 'ARCHITECT-A07' or saved.current_context.contract_ref.id != 'ARCHITECT-A06'
            or any(getattr(saved.current_context, name) != getattr(context, name) for name in
                ('run_id', 'actor_id', 'function_ref', 'scope', 'business_time', 'execution_mode'))
            or saved.context.scope != context.scope or saved.result.kind != 'completed' or saved.result.payload.choice != 'integrate'
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or not callable(validate_current) or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Integration handoff requires original saved integrate evidence and separate current A06/A07 authority')
    reading.check_method_context(context, 'ARCHITECT-A07')
    result_sha256 = task_digest(saved.result.model_dump(mode='json'))
    if any(saved.audit.get(name) != value for name, value in {
            'run_id': context.run_id, 'action_id': 'ARCHITECT-A06', 'operation_id': saved.context.operation_id,
            'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha256, 'result_kind': 'completed'}.items()):
        raise TaskConflict('Integration handoff lacks its original successful saved audit')
    target = Reference.model_validate(registration_ref)
    native = Reference.model_validate(native_evidence_ref)
    relations = [Reference.model_validate(ref) for ref in relation_evidence_refs]
    unique_refs(relations)
    if not relations or native in relations:
        raise TaskConflict('Integration registration needs separate native and independent relation evidence')
    try:
        before = reading.method_evidence()
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        option = ArchitectIntegrationOptionView.model_validate(originals[saved.action_input.option_ref.key()])
        profile = ArchitectIntegrationProfileView.model_validate(originals[option.integration_profile_ref.key()])
        draft = ArchitectRegisteredIntegrationDraft.model_validate(saved.result.payload.draft.model_dump(mode='python'))
        registration = reading.resolve(target)
        if (not isinstance(registration, ArchitectIntegrationRegistrationView) or registration.ref != target
                or registration.run_id != context.run_id or registration.organization_id != reading.organization_id
                or registration.task_sha256 != saved.identity.key or registration.record_sha256 != saved.record_sha256
                or registration.result_sha256 != result_sha256 or registration.source_reading_sha256 != saved.source_reading_sha256
                or registration.draft != draft or registration.scope != saved.context.scope
                or draft.option_ref != saved.action_input.option_ref
                or draft.included_assessment_refs != saved.action_input.professional_refs
                or draft.included_cost_refs != saved.action_input.cost_refs
                or draft.open_issue_refs != saved.action_input.open_issue_refs
                or draft.integration_authority_ref != saved.action_input.integration_authority_ref
                or draft.interface_refs != profile.interface_refs or draft.consistency_result_refs != profile.consistency_result_refs
                or registration.author_actor_id != saved.context.actor_id
                or registration.author_function_ref != saved.context.function_ref
                or registration.author_authority_ref != profile.authority_ref
                or registration.author_authority_ref not in saved.context.authorization_refs):
            raise TaskConflict('Integration registration replaces original draft, references, unresolved issues, scope or author')
        points = [saved.context.business_time, registration.authored_at, registration.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or not registration.effective_window.contains(context.business_time)):
            raise TaskConflict('Integration registration changes original production or received-record chronology')
        if registration.registration_status != 'registered':
            code = 'original_architect_integration_registration_' + registration.registration_status
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [registration.ref], 'earliest_time': None, 'condition_code': code}}
        deliverable = reading.resolve(invocation.action_input.deliverable_ref)
        unique_refs(registration.dependency_refs)
        if (not isinstance(deliverable, ArchitectSubmissionDeliverableView) or deliverable.ref != registration.deliverable_ref
                or content_digest(deliverable) != registration.deliverable_sha256
                or deliverable.content_sha256 != registration.deliverable_content_sha256
                or deliverable.task_ref != registration.task_ref or deliverable.scope != registration.scope
                or deliverable.author_organization_id != reading.organization_id
                or deliverable.author_actor_id != registration.author_actor_id
                or deliverable.author_function_ref != registration.author_function_ref
                or deliverable.author_authority_ref != registration.author_authority_ref
                or deliverable.author_action_id != 'ARCHITECT-A06' or deliverable.issue_coverage != 'complete'
                or deliverable.unresolved_issue_refs != draft.open_issue_refs
                or deliverable.dependency_refs != registration.dependency_refs
                or {ref.key() for ref in invocation.action_input.dependency_refs} != {ref.key() for ref in registration.dependency_refs}
                or registration.registered_at is None):
            raise TaskConflict('Registered deliverable changes original content, task, authors, issues or actual dependencies')
        unique_refs(deliverable.unresolved_issue_refs)
        points = [saved.context.business_time, deliverable.authored_at, registration.registered_at,
            deliverable.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or registration.registered_at.offset > registration.available_at.offset
                or not deliverable.effective_window.contains(context.business_time)):
            raise TaskConflict('Registered integration deliverable changes actual artifact or observation chronology')
        if deliverable.status != 'compiled':
            code = 'original_registered_integration_deliverable_not_compiled'
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [deliverable.ref], 'earliest_time': None, 'condition_code': code}}
        grant, assignment = reading.resolve(deliverable.author_authority_ref), reading.resolve(deliverable.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or assignment.role != 'Architect' or assignment.function_ref != deliverable.author_function_ref
                or grant.organization_id != reading.organization_id or grant.actor_id != deliverable.author_actor_id
                or grant.function_ref != deliverable.author_function_ref or 'ARCHITECT-A06' not in grant.action_ids
                or not any(scope_covers(scope, deliverable.scope) for scope in grant.scopes)
                or not grant.validity.contains(registration.authored_at) or not grant.validity.contains(deliverable.authored_at)):
            raise TaskConflict('Registered integration deliverable lacks its original independent author authority')
        evidence = {}
        for ref in [native, *relations, *registration.evidence_refs, *deliverable.evidence_refs, *grant.basis_refs, *assignment.basis_refs]:
            row = reading.resolve(ref)
            if (not isinstance(row, EvidenceRecord) or row.ref != ref or row.source_kind == 'synthetic'
                    or ref in [native, *relations] and row.basis_kind != 'observed'
                    or row.effective_window is not None and not row.effective_window.contains(context.business_time)):
                raise TaskConflict('Integration handoff lacks current actual native, relation or author evidence')
            if ref in [native, *relations]:
                evidence[ref.key()] = row.model_dump(mode='json')
        if evidence[native.key()]['content_hash'] != native_source_sha256:
            raise TaskConflict('Integration registration changes its actual native source hash')
        if validate_current(saved=deepcopy(saved), draft=draft.model_copy(deep=True),
                registration=registration.model_copy(deep=True), deliverable=deliverable.model_copy(deep=True),
                evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Integration registration requires actual native content/task/dependency lineage, service authority, receipt and privacy checks')
        if reading.method_evidence() != before:
            raise TaskConflict('Integration registration source gate must not execute methods')
        return {'kind': 'prepared', 'source_mode': 'formal', 'deliverable_ref': deliverable.ref,
            'registration_status': registration.registration_status, 'provenance': {
                'task_sha256': saved.identity.key, 'record_sha256': saved.record_sha256,
                'result_sha256': result_sha256, 'source_reading_sha256': saved.source_reading_sha256,
                'draft_sha256': content_digest(draft), 'registration_sha256': content_digest(registration),
                'deliverable_sha256': content_digest(deliverable), 'deliverable_content_sha256': deliverable.content_sha256,
                'native_source_sha256': native_source_sha256, 'evidence_sha256': task_digest(list(evidence.values()))}}
    finally:
        reading.recheck()
