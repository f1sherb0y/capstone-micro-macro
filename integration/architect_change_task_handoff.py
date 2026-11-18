"""Link original A09 change proposals to actual authorized A05 revision tasks."""
from copy import deepcopy

from integration.architect_change_results import SavedArchitectChange
from src.actions.contracts.architect_change_objects import (
    ArchitectChangeDeliverableView, ArchitectChangeIssueView, ArchitectChangeObligationView,
    ArchitectChangeProfileView,
)
from src.actions.contracts.architect_design_objects import (
    ArchitectChangeTaskRegistrationView, ArchitectDesignTaskView,
)
from src.actions.contracts.architect_research_objects import ArchitectResearchOptionView
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization
from src.organization.registry import scope_covers


def prepare_architect_change_task_handoff(saved, *, invocation, registration_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current):
    """Read actual intake under the caller's guard; create no task or design.

    The actual verifier independently checks proposal/native/task correspondence,
    original deliverable to parent option content, service authority and privacy.
    Historical A09 reads and current A05 authority remain independent. A05 still
    checks catalog, work investment, area reports and engagement limits itself.
    """
    context, reading = invocation.context, invocation.reading
    if (not isinstance(saved, SavedArchitectChange) or saved.identity.action_id != 'ARCHITECT-A09'
            or saved.identity.role != 'Architect' or saved.identity.run_id != context.run_id
            or saved.current_context.contract_ref.id != 'ARCHITECT-A09' or context.contract_ref.id != 'ARCHITECT-A05'
            or any(getattr(saved.current_context, name) != getattr(context, name) for name in
                ('run_id', 'scope', 'business_time', 'execution_mode'))
            or saved.context.scope != context.scope or saved.result.kind != 'completed'
            or saved.result.payload.choice != 'propose_change'
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or not callable(validate_current) or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Change intake requires original completed A09 proposal and independent formal A09/A05 reads')
    reading.check_method_context(context, 'ARCHITECT-A05')
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if any(saved.audit.get(name) != value for name, value in {
            'run_id': context.run_id, 'action_id': 'ARCHITECT-A09', 'operation_id': saved.context.operation_id,
            'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
        raise TaskConflict('Change intake lacks original completed proposal audit')
    ref, native = Reference.model_validate(registration_ref), Reference.model_validate(native_evidence_ref)
    relations = [Reference.model_validate(item) for item in relation_evidence_refs]
    unique_refs(relations)
    if not relations or native in relations:
        raise TaskConflict('Change intake requires separate observed native and relation evidence')
    try:
        before = reading.method_evidence()
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        original = ArchitectChangeDeliverableView.model_validate(originals[saved.action_input.used_deliverable_ref.key()])
        issue = ArchitectChangeIssueView.model_validate(originals[saved.action_input.issue_ref.key()])
        obligation = ArchitectChangeObligationView.model_validate(originals[saved.action_input.obligation_ref.key()])
        profile = ArchitectChangeProfileView.model_validate(originals[issue.change_profile_ref.key()])
        proposal = saved.result.model_dump(mode='json')['payload']['draft']
        registration = reading.resolve(ref)
        if (not isinstance(registration, ArchitectChangeTaskRegistrationView) or registration.ref != ref
                or registration.run_id != context.run_id or registration.proposer_organization_id != saved.identity.organization_id
                or registration.designer_organization_id != reading.organization_id
                or registration.designer_actor_id != context.actor_id or registration.designer_function_ref != context.function_ref
                or registration.task_sha256 != saved.identity.key or registration.record_sha256 != saved.record_sha256
                or registration.result_sha256 != result_sha or registration.source_reading_sha256 != saved.source_reading_sha256
                or registration.proposal_sha256 != task_digest(proposal)
                or registration.issue_ref != issue.ref or issue.used_deliverable_ref != original.ref
                or registration.obligation_ref != obligation.ref or issue.obligation_ref != obligation.ref
                or obligation.deliverable_ref != original.ref or obligation.organization_id != saved.identity.organization_id
                or profile.issue_ref != issue.ref or profile.obligation_ref != obligation.ref
                or registration.prior_deliverable_ref != original.ref
                or registration.original_content_sha256 != original.content_sha256
                or registration.instruction_ref != saved.action_input.instruction_ref
                or registration.scope != context.scope
                or proposal['prior_deliverable_ref'] != original.ref.model_dump(mode='json')
                or proposal['instruction_ref'] != (registration.instruction_ref.model_dump(mode='json')
                    if registration.instruction_ref is not None else None)
                or proposal['affected_scope'] != profile.affected_scope.model_dump(mode='json')
                or proposal['affected_dependency_refs'] != [item.model_dump(mode='json') for item in profile.affected_dependency_refs]
                or proposal['proposed_variable_changes'] != [item.model_dump(mode='json') for item in profile.proposed_variable_changes]):
            raise TaskConflict('Change intake substitutes proposal, original issue/obligation/content or designer identity')
        now = context.business_time
        points = [saved.context.business_time, registration.available_at, now]
        if (any(point.clock_ref != now.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or not registration.effective_window.contains(now)):
            raise TaskConflict('Change intake changes original proposal or observation chronology')
        if registration.registration_status != 'registered':
            code = 'original_architect_change_task_' + registration.registration_status
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [registration.ref], 'earliest_time': None, 'condition_code': code}}
        if invocation.action_input.prior_option_ref is None:
            raise TaskConflict('Change intake requires an explicit original parent option version')
        task = reading.resolve(invocation.action_input.task_ref)
        parent = reading.resolve(invocation.action_input.prior_option_ref)
        if (not isinstance(task, ArchitectDesignTaskView) or not isinstance(parent, ArchitectResearchOptionView)
                or task.ref != registration.design_task_ref or content_digest(task) != registration.design_task_sha256
                or parent.ref != registration.parent_option_ref or content_digest(parent) != registration.parent_option_sha256
                or task.organization_id != reading.organization_id or task.choice != 'produce'
                or task.brief_ref != invocation.action_input.brief_ref or parent.brief_ref != task.brief_ref
                or task.design_profile_ref != original.design_profile_ref or parent.design_profile_ref != original.design_profile_ref
                or task.design_profile_ref != invocation.action_input.design_profile_ref or task.scope != context.scope
                or not scope_covers(parent.scope, context.scope) or parent.compilation_status != 'completed'
                or registration.registered_at is None or not task.drafts):
            raise TaskConflict('Change intake replaces actual revision task, original parent, catalog or scope')
        points = [saved.context.business_time, registration.registered_at, task.available_at, now]
        if (any(point.clock_ref != now.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or registration.registered_at.offset > registration.available_at.offset
                or parent.available_at.clock_ref != now.clock_ref or parent.available_at.offset > now.offset
                or not task.effective_window.contains(now) or not parent.effective_window.contains(now)):
            raise TaskConflict('Change intake changes actual task or parent chronology')
        if task.status != 'authorized':
            code = 'original_registered_architect_change_task_not_authorized'
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [task.ref], 'earliest_time': None, 'condition_code': code}}
        original_variables = {item.variable_ref.key(): item for item in original.variables}
        changes = {item.variable_ref.key(): item for item in profile.proposed_variable_changes}
        if len(original_variables) != len(original.variables) or len(changes) != len(profile.proposed_variable_changes):
            raise TaskConflict('Change intake repeats original or proposed variables')
        expected = {**original_variables, **changes}
        unresolved = task_digest(proposal['unresolved_questions'])
        for draft in task.drafts:
            variables = {item.variable_ref.key(): item for item in draft.variables}
            if (draft.relation != 'revision' or draft.parent_option_ref != parent.ref
                    or draft.brief_ref != task.brief_ref or draft.design_profile_ref != original.design_profile_ref
                    or draft.scope != context.scope or len(variables) != len(draft.variables) or variables != expected
                    or task_digest([item.model_dump(mode='json') for item in draft.unresolved_questions]) != unresolved):
                raise TaskConflict('Actual revision changes the proposed variables, untouched content or unresolved questions')
        grant = reading.resolve(task.authority_ref)
        if not isinstance(grant, Authorization) or grant not in reading._organizations.grants(context, 'ARCHITECT-A05', 'Architect'):
            raise TaskConflict('Actual revision task lacks independent current A05 authority')
        evidence = {}
        for item in [native, *relations, *registration.evidence_refs, *task.evidence_refs, *parent.evidence_refs, *grant.basis_refs]:
            row = reading.resolve(item)
            if (not isinstance(row, EvidenceRecord) or row.ref != item or row.source_kind == 'synthetic'
                    or item in [native, *relations] and row.basis_kind != 'observed'
                    or row.effective_window is not None and not row.effective_window.contains(now)):
                raise TaskConflict('Change intake lacks actual current native, relation or task authority evidence')
            if item in [native, *relations]:
                evidence[item.key()] = row.model_dump(mode='json')
        if evidence[native.key()]['content_hash'] != native_source_sha256:
            raise TaskConflict('Change task substitutes original native intake source hash')
        cache_before = reading.evidence()
        if validate_current(saved=deepcopy(saved), registration=registration.model_copy(deep=True),
                original=original.model_copy(deep=True), issue=issue.model_copy(deep=True),
                obligation=obligation.model_copy(deep=True), profile=profile.model_copy(deep=True),
                proposal=deepcopy(proposal), task=task.model_copy(deep=True), parent=parent.model_copy(deep=True),
                evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Change intake requires actual native task relation, parent content, service authority and privacy checks')
        if reading.method_evidence() != before or reading.evidence() != cache_before:
            raise TaskConflict('Change intake gate must preserve source cache and execute no method')
        return {'kind': 'prepared', 'source_mode': 'formal', 'design_task_ref': task.ref,
            'provenance': {'task_sha256': saved.identity.key, 'record_sha256': saved.record_sha256,
                'result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
                'proposal_sha256': task_digest(proposal), 'registration_sha256': content_digest(registration),
                'design_task_sha256': content_digest(task), 'parent_option_sha256': content_digest(parent),
                'native_source_sha256': native_source_sha256, 'evidence_sha256': task_digest(list(evidence.values()))}}
    finally:
        reading.recheck()
