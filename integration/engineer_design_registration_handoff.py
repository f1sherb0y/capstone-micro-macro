"""Relate saved A05 professional drafts to actual deliverable versions for A07."""
from copy import deepcopy

from integration.engineer_design_results import SavedEngineerDesign
from integration.engineer_change_results import SavedEngineerChange
from src.actions.contracts.engineer_change_objects import (
    EngineerChangeIssueView, EngineerChangeObligationView, EngineerChangeProfileView,
    EngineerChangeDeliverableView, EngineerChangeBasisView,
)
from src.actions.contracts.engineer_design_objects import EngineerDesignDraft, EngineerDesignTaskView
from src.actions.contracts.engineer_submission_objects import (
    EngineerDesignRegistrationView, EngineerRevisionRegistrationView, EngineerSubmissionDeliverableView,
)
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def prepare_engineer_design_registration_handoff(saved, *, invocation, registration_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current):
    """Inspect actual registry content under the caller's source/authority guard.

    The independent gate verifies full native content (all parameter/check/interface/quantity/question refs), artifact/task/dependency
    lineage, service authority, complete unresolved-question/issue association, receipt relation and private access. Registration
    proves no actual task completion, independent acceptance or permitted use.
    """
    return _prepare_engineer_registration_handoff(saved, source_action_id='ENGINEER-A05',
        invocation=invocation, registration_ref=registration_ref, native_evidence_ref=native_evidence_ref,
        native_source_sha256=native_source_sha256, relation_evidence_refs=relation_evidence_refs,
        validate_current=validate_current)


def _prepare_engineer_registration_handoff(saved, *, source_action_id, invocation, registration_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current):
    """Closed A05/A09 routes retain separate source contracts and native records."""
    if source_action_id == 'ENGINEER-A05':
        saved_type, choice, registration_type = SavedEngineerDesign, 'produce', EngineerDesignRegistrationView
    elif source_action_id == 'ENGINEER-A09':
        saved_type, choice, registration_type = SavedEngineerChange, 'revise', EngineerRevisionRegistrationView
    else:
        raise TaskConflict('Registration handoff requires an original design or revision source action')
    context, reading = invocation.context, invocation.reading
    if (not isinstance(saved, saved_type) or saved.identity.action_id != source_action_id
            or saved.identity.role != 'Engineer' or saved.identity.run_id != context.run_id
            or saved.identity.organization_id != reading.organization_id
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ENGINEER-A07'
            or saved.context.contract_ref.kind != 'ActionContract' or saved.context.contract_ref.id != source_action_id
            or saved.current_context.contract_ref.kind != 'ActionContract'
            or saved.current_context.contract_ref.id != source_action_id
            or any(getattr(saved.current_context, name) != getattr(context, name) for name in
                ('run_id', 'actor_id', 'function_ref', 'scope', 'business_time', 'execution_mode'))
            or saved.context.scope != context.scope or saved.result.kind != 'completed' or saved.result.payload.choice != choice
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or not callable(validate_current) or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Professional handoff requires original completed evidence and separate current A07 authority')
    reading.check_method_context(context, 'ENGINEER-A07')
    result_sha256 = task_digest(saved.result.model_dump(mode='json'))
    if any(saved.audit.get(name) != value for name, value in {
            'run_id': context.run_id, 'action_id': source_action_id, 'operation_id': saved.context.operation_id,
            'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha256, 'result_kind': 'completed'}.items()):
        raise TaskConflict('Professional design handoff lacks its original successful saved audit')
    target = Reference.model_validate(registration_ref)
    native = Reference.model_validate(native_evidence_ref)
    relations = [Reference.model_validate(ref) for ref in relation_evidence_refs]
    unique_refs(relations)
    if not relations or native in relations:
        raise TaskConflict('Professional design registration needs separate native and independent relation evidence')
    try:
        before = reading.method_evidence()
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        if source_action_id == 'ENGINEER-A05':
            task = EngineerDesignTaskView.model_validate(originals[saved.action_input.task_ref.key()])
            brief_ref, profile_ref, parent_ref = (saved.action_input.brief_ref,
                saved.action_input.engineering_profile_ref, saved.action_input.prior_option_ref)
        else:
            issue = EngineerChangeIssueView.model_validate(originals[saved.action_input.issue_ref.key()])
            obligation = EngineerChangeObligationView.model_validate(originals[saved.action_input.obligation_ref.key()])
            parent = EngineerChangeDeliverableView.model_validate(originals[saved.action_input.prior_deliverable_ref.key()])
            profile = EngineerChangeProfileView.model_validate(originals[issue.change_profile_ref.key()])
            if profile.choice != 'revise' or profile.revision_task_ref is None or profile.change_basis_ref is None:
                raise TaskConflict('Revision registration lacks its original revise task and change basis')
            task = EngineerDesignTaskView.model_validate(originals[profile.revision_task_ref.key()])
            basis = EngineerChangeBasisView.model_validate(originals[profile.change_basis_ref.key()])
            if (issue.used_deliverable_ref != parent.ref or issue.obligation_ref != obligation.ref
                    or obligation.deliverable_ref != parent.ref or obligation.organization_id != reading.organization_id
                    or profile.issue_ref != issue.ref or profile.obligation_ref != obligation.ref
                    or basis.issue_ref != issue.ref or basis.obligation_ref != obligation.ref
                    or basis.prior_deliverable_ref != parent.ref or basis.original_content_sha256 != parent.content_sha256
                    or basis.instruction_ref != saved.action_input.instruction_ref
                    or saved.result.payload.change_basis_ref != basis.ref
                    or task.organization_id != reading.organization_id or task.appointment_ref != obligation.appointment_ref
                    or task.brief_ref != parent.brief_ref or task.engineering_profile_ref != parent.engineering_profile_ref
                    or {ref.key() for ref in profile.method_result_refs} != {ref.key() for ref in saved.action_input.method_result_refs}
                    or task.draft is None or basis.draft_sha256 != content_digest(task.draft)):
                raise TaskConflict('Revision registration substitutes original issue, obligation, content or authorized draft basis')
            brief_ref, profile_ref, parent_ref = parent.brief_ref, parent.engineering_profile_ref, parent.option_ref
        draft = EngineerDesignDraft.model_validate(saved.result.payload.draft.model_dump(mode='python'))
        registration = reading.resolve(target)
        if (not isinstance(registration, registration_type) or registration.ref != target
                or registration.run_id != context.run_id or registration.organization_id != reading.organization_id
                or registration.task_sha256 != saved.identity.key or registration.record_sha256 != saved.record_sha256
                or registration.result_sha256 != result_sha256 or registration.source_reading_sha256 != saved.source_reading_sha256
                or registration.draft != draft or task.draft != draft or registration.scope != saved.context.scope
                or registration.task_ref != task.ref or registration.appointment_ref != task.appointment_ref
                or draft.brief_ref != brief_ref
                or draft.engineering_profile_ref != profile_ref
                or {ref.key() for ref in draft.method_result_refs} != {ref.key() for ref in saved.action_input.method_result_refs}
                or draft.parent_option_ref != parent_ref
                or registration.author_actor_id != saved.context.actor_id
                or registration.author_function_ref != saved.context.function_ref
                or registration.author_authority_ref != task.authority_ref
                or registration.author_authority_ref not in saved.context.authorization_refs):
            raise TaskConflict('Design registration replaces original complete draft, input versions, task, scope or author')
        if source_action_id == 'ENGINEER-A09' and (
                registration.issue_ref != issue.ref or registration.obligation_ref != obligation.ref
                or registration.prior_deliverable_ref != parent.ref
                or registration.original_content_sha256 != parent.content_sha256
                or registration.change_basis_ref != basis.ref
                or registration.instruction_ref != saved.action_input.instruction_ref
                or registration.deliverable_ref == parent.ref):
            raise TaskConflict('Revision native registration changes original lineage or overwrites its parent version')
        points = [saved.context.business_time, registration.authored_at, registration.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or not registration.effective_window.contains(context.business_time)):
            raise TaskConflict('Professional design registration changes original production or received-record chronology')
        if registration.registration_status != 'registered':
            code = 'original_engineer_design_registration_' + registration.registration_status
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [registration.ref], 'earliest_time': None, 'condition_code': code}}
        deliverable = reading.resolve(invocation.action_input.deliverable_ref)
        unique_refs(registration.dependency_refs)
        unique_refs(registration.unresolved_issue_refs)
        if (not isinstance(deliverable, EngineerSubmissionDeliverableView) or deliverable.ref != registration.deliverable_ref
                or content_digest(deliverable) != registration.deliverable_sha256
                or deliverable.content_sha256 != registration.deliverable_content_sha256
                or deliverable.task_ref != registration.task_ref or deliverable.scope != registration.scope
                or deliverable.appointment_ref != task.appointment_ref or task.discipline_code not in deliverable.discipline_codes
                or deliverable.author_organization_id != reading.organization_id
                or deliverable.author_actor_id != registration.author_actor_id
                or deliverable.author_function_ref != registration.author_function_ref
                or deliverable.author_authority_ref != registration.author_authority_ref
                or deliverable.author_action_id != source_action_id or deliverable.issue_coverage != 'complete'
                or deliverable.unresolved_issue_refs != registration.unresolved_issue_refs
                or deliverable.dependency_refs != registration.dependency_refs
                or registration.registered_at is None):
            raise TaskConflict('Registered deliverable changes original content, task, authors, issues or actual dependencies')
        unique_refs(deliverable.unresolved_issue_refs)
        points = [saved.context.business_time, deliverable.authored_at, registration.registered_at,
            deliverable.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or registration.registered_at.offset > registration.available_at.offset
                or not deliverable.effective_window.contains(context.business_time)):
            raise TaskConflict('Registered design deliverable changes actual artifact or observation chronology')
        if deliverable.status != 'compiled':
            code = 'original_registered_design_deliverable_not_compiled'
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [deliverable.ref], 'earliest_time': None, 'condition_code': code}}
        grant, assignment = reading.resolve(deliverable.author_authority_ref), reading.resolve(deliverable.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or assignment.role != 'Engineer' or assignment.function_ref != deliverable.author_function_ref
                or grant.organization_id != reading.organization_id or grant.actor_id != deliverable.author_actor_id
                or grant.function_ref != deliverable.author_function_ref or source_action_id not in grant.action_ids
                or not any(scope_covers(scope, deliverable.scope) for scope in grant.scopes)
                or not grant.validity.contains(registration.authored_at) or not grant.validity.contains(deliverable.authored_at)):
            raise TaskConflict('Registered design deliverable lacks its original independent author authority')
        evidence = {}
        for ref in [native, *relations, *registration.evidence_refs, *deliverable.evidence_refs, *grant.basis_refs, *assignment.basis_refs]:
            row = reading.resolve(ref)
            if (not isinstance(row, EvidenceRecord) or row.ref != ref or row.source_kind == 'synthetic'
                    or ref in [native, *relations] and row.basis_kind != 'observed'
                    or row.effective_window is not None and not row.effective_window.contains(context.business_time)):
                raise TaskConflict('Professional design handoff lacks current actual native, relation or author evidence')
            if ref in [native, *relations]:
                evidence[ref.key()] = row.model_dump(mode='json')
        if evidence[native.key()]['content_hash'] != native_source_sha256:
            raise TaskConflict('Professional design registration changes its actual native source hash')
        if validate_current(saved=deepcopy(saved), draft=draft.model_copy(deep=True),
                registration=registration.model_copy(deep=True), deliverable=deliverable.model_copy(deep=True),
                evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Design registration requires full native draft/task/dependency and unresolved-question/issue lineage, service authority, receipt and privacy checks')
        if reading.method_evidence() != before:
            raise TaskConflict('Professional design registration source gate must not execute methods')
        return {'kind': 'prepared', 'source_mode': 'formal', 'deliverable_ref': deliverable.ref,
            'registration_status': registration.registration_status, 'provenance': {
                'task_sha256': saved.identity.key, 'record_sha256': saved.record_sha256,
                'result_sha256': result_sha256, 'source_reading_sha256': saved.source_reading_sha256,
                'draft_sha256': content_digest(draft), 'registration_sha256': content_digest(registration),
                'deliverable_sha256': content_digest(deliverable), 'deliverable_content_sha256': deliverable.content_sha256,
                'native_source_sha256': native_source_sha256, 'evidence_sha256': task_digest(list(evidence.values()))}}
    finally:
        reading.recheck()
