"""Closed Architect/Engineer investigation intake across original A13/A04 authorities."""
from copy import deepcopy

from integration.architect_research_results import SavedArchitectResearch
from src.actions.contracts.architect_planning_objects import (
    ArchitectInvestigationTaskRegistrationView, ArchitectPlanningTaskView, ArchitectPlanningProfileView,
)
from src.actions.contracts.architect_research_objects import (
    ArchitectResearchTaskView, ArchitectResearchRequestView, ArchitectResearchAuthorityView,
    ArchitectResearchEstimateView, ArchitectResearchLimitView,
)
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization


def prepare_service_investigation_task_handoff(saved, *, invocation, registration_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current, action_id):
    """Inspect actual task under caller's guard, with separate A13/A04 authority.

    An actual verifier checks intake/request/task relations, original input,
    output and dependency mappings, remaining budget/work, and continuation
    within the original client authority or an effective amendment. Observed
    confirmation is independent from submission acceptance. A04 separately
    checks resources, investment, capacity and service terms. No task is created.
    """
    if action_id == 'ARCHITECT-A13':
        saved_type, registration_type = SavedArchitectResearch, ArchitectInvestigationTaskRegistrationView
        task_type, profile_type = ArchitectPlanningTaskView, ArchitectPlanningProfileView
        source_task_type, authority_type = ArchitectResearchTaskView, ArchitectResearchAuthorityView
        planning_action, role = 'ARCHITECT-A04', 'Architect'
        estimate_projection_type = None
    elif action_id == 'ENGINEER-A13':
        from integration.engineer_research_results import SavedEngineerResearch
        from src.actions.contracts.engineer_planning_objects import (
            EngineerInvestigationTaskRegistrationView, EngineerPlanningTaskView, EngineerPlanningProfileView,
        )
        from src.actions.contracts.engineer_research_objects import (
            EngineerResearchTaskView, EngineerResearchAuthorityView, EngineerResearchMethodProjection,
        )
        saved_type, registration_type = SavedEngineerResearch, EngineerInvestigationTaskRegistrationView
        task_type, profile_type = EngineerPlanningTaskView, EngineerPlanningProfileView
        source_task_type, authority_type = EngineerResearchTaskView, EngineerResearchAuthorityView
        planning_action, role = 'ENGINEER-A04', 'Engineer'
        estimate_projection_type = EngineerResearchMethodProjection
    else:
        raise TaskConflict('Investigation intake requires an original supported fixed role route')
    context, reading = invocation.context, invocation.reading
    if (not isinstance(saved, saved_type) or saved.identity.action_id != action_id
            or saved.identity.role != role or saved.identity.run_id != context.run_id
            or saved.current_context.contract_ref.id != action_id or context.contract_ref.id != planning_action
            or any(getattr(saved.current_context, name) != getattr(context, name) for name in
                ('run_id', 'scope', 'business_time', 'execution_mode'))
            or saved.context.scope != context.scope or saved.result.kind != 'completed'
            or saved.result.payload.choice != 'recommend_investigation'
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or not callable(validate_current) or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Investigation intake requires completed A13 request and independent formal A13/A04 reads')
    reading.check_method_context(context, planning_action)
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if any(saved.audit.get(name) != value for name, value in {
            'run_id': context.run_id, 'action_id': action_id, 'operation_id': saved.context.operation_id,
            'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
        raise TaskConflict('Investigation intake lacks original completed request audit')
    ref, native = Reference.model_validate(registration_ref), Reference.model_validate(native_evidence_ref)
    relations = [Reference.model_validate(item) for item in relation_evidence_refs]
    unique_refs(relations)
    if not relations or native in relations:
        raise TaskConflict('Investigation intake requires separate observed native and relation evidence')
    try:
        before = reading.method_evidence()
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        source_task = source_task_type.model_validate(originals[saved.action_input.task_ref.key()])
        if source_task.request_profile_ref is None:
            raise TaskConflict('Investigation intake lacks original request profile')
        request = ArchitectResearchRequestView.model_validate(originals[source_task.request_profile_ref.key()])
        authority = authority_type.model_validate(originals[saved.action_input.research_authority_ref.key()])
        limit = ArchitectResearchLimitView.model_validate(originals[saved.action_input.expenditure_limit_ref.key()])
        payload = saved.result.model_dump(mode='json')['payload']
        proposal = payload['request']
        expected = request.model_dump(mode='json', exclude={'ref', 'task_ref', 'available_at', 'effective_window',
            'evidence_refs', 'incremental_cost', 'estimate_ref'})
        expected['questions'] = payload['questions']
        registration = reading.resolve(ref)
        if (not isinstance(registration, registration_type) or registration.ref != ref
                or registration.run_id != context.run_id or registration.proposer_organization_id != saved.identity.organization_id
                or registration.planner_organization_id != reading.organization_id
                or registration.planner_actor_id != context.actor_id or registration.planner_function_ref != context.function_ref
                or registration.task_sha256 != saved.identity.key or registration.record_sha256 != saved.record_sha256
                or registration.result_sha256 != result_sha or registration.source_reading_sha256 != saved.source_reading_sha256
                or registration.source_task_ref != source_task.ref or registration.request_profile_ref != request.ref
                or registration.request_profile_sha256 != content_digest(request)
                or registration.request_payload_sha256 != task_digest(proposal) or proposal != expected
                or registration.research_authority_ref != authority.ref or registration.research_limit_ref != limit.ref
                or authority.task_ref != source_task.ref or authority.delegate_organization_id != saved.identity.organization_id
                or limit.task_ref != source_task.ref or limit.organization_id != saved.identity.organization_id
                or request.task_ref != source_task.ref or request.authority_basis_refs != [authority.ref]
                or registration.purpose != request.purpose or registration.input_refs != request.input_refs
                or registration.output_requirement_refs != request.output_requirement_refs
                or registration.source_work_profile_ref != request.work_profile_ref
                or registration.source_dependency_refs != request.dependency_refs
                or [row.model_dump(mode='json') for row in registration.questions] != payload['questions']
                or registration.effort_estimate != request.effort_estimate
                or registration.incremental_cost != request.incremental_cost
                or registration.desired_window != request.desired_window or registration.scope != context.scope):
            raise TaskConflict('Investigation intake replaces original request, questions, limits or planner identity')
        for refs in (registration.input_refs, registration.output_requirement_refs, registration.source_dependency_refs):
            unique_refs(refs)
        if role == 'Engineer' and (registration.discipline_code != source_task.discipline_code
                or registration.function_code != source_task.function_code):
            raise TaskConflict('Investigation intake substitutes original engineering discipline or function')
        now = context.business_time
        points = [saved.context.business_time, registration.available_at, now]
        if (any(point.clock_ref != now.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or not registration.effective_window.contains(now)):
            raise TaskConflict('Investigation intake changes original request or observation chronology')
        if registration.registration_status != 'registered':
            code = 'original_' + role.lower() + '_investigation_task_' + registration.registration_status
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [registration.ref], 'earliest_time': None, 'condition_code': code}}
        if (registration.planning_task_ref not in invocation.action_input.task_refs
                or registration.confirmed_at is None or registration.registered_at is None):
            raise TaskConflict('Investigation intake lacks independently confirmed actual selected task')
        task = reading.resolve(registration.planning_task_ref)
        profile = reading.resolve(invocation.action_input.work_profile_ref)
        if (not isinstance(task, task_type) or not isinstance(profile, profile_type)
                or task.ref != registration.planning_task_ref or content_digest(task) != registration.planning_task_sha256
                or task.organization_id != reading.organization_id or profile.organization_id != reading.organization_id
                or task.ref not in profile.task_refs or task.scope != context.scope
                or task.work_profile_ref != profile.ref or task.appointment_ref != profile.appointment_ref
                or task.appointment_ref != authority.appointment_ref or task.accepted_terms_ref != authority.accepted_terms_ref
                or task.as_of != now):
            raise TaskConflict('Investigation intake changes actual task, original engagement or planning profile')
        if role == 'Engineer' and (task.function_code != source_task.function_code
                or source_task.discipline_code not in task.discipline_codes
                or not set(task.discipline_codes) <= set(authority.allowed_discipline_codes)
                or source_task.discipline_code not in profile.discipline_codes):
            raise TaskConflict('Actual investigation task widens the original engineering discipline or function')
        points = [saved.context.business_time, registration.confirmed_at, registration.registered_at, task.available_at, now]
        if (any(point.clock_ref != now.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or registration.registered_at.offset > registration.available_at.offset
                or not task.effective_window.contains(now) or not profile.effective_window.contains(now)):
            raise TaskConflict('Investigation intake changes continuation confirmation or actual task chronology')
        if task.status not in {'authorized', 'waiting'}:
            code = 'original_registered_' + role.lower() + '_investigation_task_not_authorized'
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [task.ref], 'earliest_time': None, 'condition_code': code}}
        if request.desired_window.state == 'known':
            window = request.desired_window.value
            if (task.planned_window.start.clock_ref != window.start.clock_ref
                    or task.planned_window.start.offset < window.start.offset or task.planned_window.end.offset > window.end.offset):
                raise TaskConflict('Actual investigation task widens the original requested time window')
        if request.estimate_ref is None:
            raise TaskConflict('Investigation intake lacks original supported cost/work estimate')
        if estimate_projection_type is None:
            estimate = ArchitectResearchEstimateView.model_validate(originals[request.estimate_ref.key()])
        else:
            wrapped = estimate_projection_type.model_validate(originals[request.estimate_ref.key()])
            if wrapped.ref != request.estimate_ref or wrapped.estimate is None:
                raise TaskConflict('Engineering investigation intake lacks the original estimate projection')
            estimate = wrapped.estimate
        if (estimate.status != 'ok' or estimate.task_ref != source_task.ref or estimate.request_profile_ref != request.ref
                or estimate.incremental_cost != request.incremental_cost or estimate.effort_estimate != request.effort_estimate):
            raise TaskConflict('Investigation intake substitutes original estimate or budget/work amounts')
        grant = reading.resolve(profile.authority_ref)
        if not isinstance(grant, Authorization) or grant not in reading._organizations.grants(context, planning_action, role):
            raise TaskConflict('Actual investigation planning lacks independent current A04 authority')
        confirmation = registration.continuation_evidence_ref
        if confirmation in [native, *relations]:
            raise TaskConflict('Investigation confirmation must be independent from native and relation evidence')
        evidence = {}
        for item in [native, confirmation, *relations, *registration.evidence_refs, *task.evidence_refs,
                *profile.evidence_refs, *grant.basis_refs]:
            row = reading.resolve(item)
            if (not isinstance(row, EvidenceRecord) or row.ref != item or row.source_kind == 'synthetic'
                    or item in [native, confirmation, *relations] and row.basis_kind != 'observed'
                    or row.effective_window is not None and not row.effective_window.contains(now)):
                raise TaskConflict('Investigation intake lacks actual native, confirmation or current authority evidence')
            if item in [native, confirmation, *relations]:
                evidence[item.key()] = row.model_dump(mode='json')
        if (evidence[native.key()]['content_hash'] != native_source_sha256
                or evidence[confirmation.key()]['content_hash'] != registration.continuation_sha256):
            raise TaskConflict('Investigation intake changes original native or continuation confirmation source hash')
        cache_before = reading.evidence()
        if validate_current(saved=deepcopy(saved), registration=registration.model_copy(deep=True),
                source_task=source_task.model_copy(deep=True), request=request.model_copy(deep=True),
                authority=authority.model_copy(deep=True), limit=limit.model_copy(deep=True),
                estimate=estimate.model_copy(deep=True), task=task.model_copy(deep=True), profile=profile.model_copy(deep=True),
                evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Investigation intake requires actual task/input/dependency mapping, client continuation, budget and privacy checks')
        if reading.method_evidence() != before or reading.evidence() != cache_before:
            raise TaskConflict('Investigation source gate must preserve cache and execute no method')
        return {'kind': 'prepared', 'source_mode': 'formal', 'planning_task_ref': task.ref,
            'provenance': {'task_sha256': saved.identity.key, 'record_sha256': saved.record_sha256,
                'result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
                'registration_sha256': content_digest(registration), 'request_profile_sha256': content_digest(request),
                'planning_task_sha256': content_digest(task), 'native_source_sha256': native_source_sha256,
                'continuation_sha256': registration.continuation_sha256,
                'evidence_sha256': task_digest(list(evidence.values()))}}
    finally:
        reading.recheck()
