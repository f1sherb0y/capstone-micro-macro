"""Relate original QS A13 research requests to actual authorized A03 tasks."""
from copy import deepcopy

from integration.qs_research_results import SavedQSResearch
from src.actions.contracts.qs_appointment_objects import QSTaskView, QSAppointmentView
from src.actions.contracts.qs_research_objects import (
    QSResearchTaskView, QSResearchRequestView, QSResearchAuthorityView,
    QSResearchLimitView, QSResearchTaskRegistrationView,
)
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import ServiceWorkProfileView
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization
from src.organization.registry import scope_covers


def prepare_qs_research_task_handoff(saved, *, invocation, registration_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current):
    """Read actual intake under caller's guard; create no tasks or reservations.

    An independent verifier checks task/request/appointment relations, original
    input/output/work/dependency mappings, client continuation within existing
    authority or an effective amendment, current budget/work and privacy.
    Observed continuation confirmation is separate from submission acceptance.
    A03 independently checks exact terms, functions, resources and capacity.
    """
    context, reading = invocation.context, invocation.reading
    if (not isinstance(saved, SavedQSResearch) or saved.identity.action_id != 'QS-A13'
            or saved.identity.role != 'QS' or saved.identity.run_id != context.run_id
            or saved.current_context.contract_ref.id != 'QS-A13' or context.contract_ref.id != 'QS-A03'
            or any(getattr(saved.current_context, name) != getattr(context, name) for name in
                ('run_id', 'scope', 'business_time', 'execution_mode'))
            or saved.context.scope != context.scope or saved.result.kind != 'completed'
            or saved.result.payload.choice != 'request_research'
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or not callable(validate_current) or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Research intake requires original completed A13 request and independent formal A13/A03 reads')
    reading.check_method_context(context, 'QS-A03')
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if any(saved.audit.get(name) != value for name, value in {
            'run_id': context.run_id, 'action_id': 'QS-A13', 'operation_id': saved.context.operation_id,
            'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
        raise TaskConflict('Research intake lacks original completed request audit')
    ref, native = Reference.model_validate(registration_ref), Reference.model_validate(native_evidence_ref)
    relations = [Reference.model_validate(item) for item in relation_evidence_refs]
    unique_refs(relations)
    if not relations or native in relations:
        raise TaskConflict('Research intake requires separate observed native and relation evidence')
    try:
        before = reading.method_evidence()
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        source_task = QSResearchTaskView.model_validate(originals[saved.action_input.task_ref.key()])
        if source_task.request_profile_ref is None:
            raise TaskConflict('Research intake lacks original request profile')
        request = QSResearchRequestView.model_validate(originals[source_task.request_profile_ref.key()])
        authority = QSResearchAuthorityView.model_validate(originals[saved.action_input.research_authority_ref.key()])
        limit = QSResearchLimitView.model_validate(originals[saved.action_input.expenditure_limit_ref.key()])
        payload = saved.result.model_dump(mode='json')['payload']
        proposal = payload['request']
        expected = request.model_dump(mode='json', exclude={'ref', 'task_ref', 'available_at', 'effective_window',
            'evidence_refs', 'incremental_budget'})
        expected['questions'] = payload['questions']
        registration = reading.resolve(ref)
        if (not isinstance(registration, QSResearchTaskRegistrationView) or registration.ref != ref
                or registration.run_id != context.run_id or registration.proposer_organization_id != saved.identity.organization_id
                or registration.planner_organization_id != reading.organization_id
                or registration.planner_actor_id != context.actor_id or registration.planner_function_ref != context.function_ref
                or registration.task_sha256 != saved.identity.key or registration.record_sha256 != saved.record_sha256
                or registration.result_sha256 != result_sha or registration.source_reading_sha256 != saved.source_reading_sha256
                or registration.request != request or registration.request_payload_sha256 != task_digest(proposal)
                or proposal != expected or registration.scope != context.scope
                or [row.model_dump(mode='json') for row in registration.questions] != payload['questions']
                or registration.research_authority_ref != authority.ref or registration.research_limit_ref != limit.ref
                or authority.task_ref != source_task.ref or authority.delegate_organization_id != saved.identity.organization_id
                or limit.task_ref != source_task.ref or limit.organization_id != saved.identity.organization_id
                or request.task_ref != source_task.ref or set(request.authority_basis_refs) != {authority.ref}):
            raise TaskConflict('Research intake substitutes original request, questions, delegation, limits or planner identity')
        for refs in (request.input_refs, request.output_requirement_refs, request.dependency_refs, request.authority_basis_refs):
            unique_refs(refs)
        now = context.business_time
        points = [saved.context.business_time, registration.available_at, now]
        if (any(point.clock_ref != now.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or not registration.effective_window.contains(now)):
            raise TaskConflict('Research intake changes original request or observation chronology')
        if registration.registration_status != 'registered':
            code = 'original_qs_research_task_' + registration.registration_status
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [registration.ref], 'earliest_time': None, 'condition_code': code}}
        if (registration.planning_task_ref not in invocation.action_input.task_refs
                or registration.confirmed_at is None or registration.registered_at is None
                or invocation.action_input.work_profile_ref is None):
            raise TaskConflict('Research intake lacks independently confirmed actual selected task and work profile')
        task = reading.resolve(registration.planning_task_ref)
        appointment = reading.resolve(invocation.action_input.appointment_ref)
        profile = reading.resolve(invocation.action_input.work_profile_ref)
        if (not isinstance(task, QSTaskView) or not isinstance(appointment, QSAppointmentView)
                or not isinstance(profile, ServiceWorkProfileView)
                or task.ref != registration.planning_task_ref or content_digest(task) != registration.planning_task_sha256
                or task.organization_id != reading.organization_id or task.scope != context.scope
                or appointment.provider_organization_id != reading.organization_id or appointment.provider_id != context.actor_id
                or registration.appointment_ref != appointment.ref or task.appointment_ref != appointment.ref
                or task.ref not in appointment.task_refs or task.work_profile_ref != profile.ref
                or registration.accepted_terms_ref != task.accepted_terms_ref
                or task.accepted_terms_ref != invocation.action_input.accepted_terms_ref
                or task.accepted_terms_ref != appointment.terms_ref or task.as_of != now
                or task.function_ref not in invocation.action_input.function_refs):
            raise TaskConflict('Research intake changes actual task, service appointment, terms, function or work profile')
        points = [saved.context.business_time, registration.confirmed_at, registration.registered_at,
            registration.available_at, now]
        if (any(point.clock_ref != now.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or not profile.effective_window.contains(now)):
            raise TaskConflict('Research intake changes confirmation, actual task intake or work profile chronology')
        if task.status not in {'authorized', 'waiting'}:
            code = 'original_registered_qs_research_task_not_authorized'
            return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [task.ref], 'earliest_time': None, 'condition_code': code}}
        if (decimal_fraction(registration.authorized_budget.value) < 0
                or registration.authorized_budget.currency != limit.budget_cap.currency
                or registration.authorized_effort.unit != limit.effort_cap.unit
                or registration.authorized_effort != task.total_effort
                or request.incremental_budget.state == 'known' and registration.authorized_budget != request.incremental_budget.value
                or request.effort_estimate.state == 'known' and registration.authorized_effort != request.effort_estimate.value):
            raise TaskConflict('Actual supplemental task changes independently authorized budget or effort')
        if request.desired_window.state == 'known':
            window = request.desired_window.value
            if (task.planned_window.start.clock_ref != window.start.clock_ref
                    or task.planned_window.start.offset < window.start.offset or task.planned_window.end.offset > window.end.offset):
                raise TaskConflict('Actual research task widens the original requested time window')
        grant = reading.resolve(task.authority_ref)
        if (not isinstance(grant, Authorization) or grant.actor_id != context.actor_id
                or grant.organization_id != reading.organization_id or grant.function_ref != task.function_ref
                or 'QS-A03' not in grant.action_ids or not grant.validity.contains(now)
                or not any(scope_covers(scope, context.scope) for scope in grant.scopes)):
            raise TaskConflict('Actual supplemental task lacks independent current QS function authority')
        confirmation = registration.continuation_evidence_ref
        if confirmation in [native, *relations]:
            raise TaskConflict('Research confirmation must be independent from native and relation evidence')
        evidence = {}
        for item in [native, confirmation, *relations, *registration.evidence_refs, *task.evidence_refs,
                *profile.evidence_refs, *appointment.evidence_refs, *grant.basis_refs,
                registration.authorized_budget.basis_ref, registration.authorized_effort.basis_ref]:
            row = reading.resolve(item)
            if (not isinstance(row, EvidenceRecord) or row.ref != item or row.source_kind == 'synthetic'
                    or item in [native, confirmation, *relations] and row.basis_kind != 'observed'
                    or row.effective_window is not None and not row.effective_window.contains(now)):
                raise TaskConflict('Research intake lacks actual native, confirmation, numeric or current authority evidence')
            if item in [native, confirmation, *relations]:
                evidence[item.key()] = row.model_dump(mode='json')
        if (evidence[native.key()]['content_hash'] != native_source_sha256
                or evidence[confirmation.key()]['content_hash'] != registration.continuation_sha256):
            raise TaskConflict('Research intake changes native or continuation confirmation source hash')
        cache_before = reading.evidence()
        if validate_current(saved=deepcopy(saved), registration=registration.model_copy(deep=True),
                source_task=source_task.model_copy(deep=True), request=request.model_copy(deep=True),
                authority=authority.model_copy(deep=True), limit=limit.model_copy(deep=True),
                task=task.model_copy(deep=True), appointment=appointment.model_copy(deep=True), profile=profile.model_copy(deep=True),
                evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Research intake requires actual task/service/input mapping, client continuation, budget and privacy checks')
        if reading.method_evidence() != before or reading.evidence() != cache_before:
            raise TaskConflict('Research intake source gate must preserve cache and execute no method')
        return {'kind': 'prepared', 'source_mode': 'formal', 'planning_task_ref': task.ref,
            'provenance': {'task_sha256': saved.identity.key, 'record_sha256': saved.record_sha256,
                'result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
                'registration_sha256': content_digest(registration), 'request_profile_sha256': content_digest(request),
                'planning_task_sha256': content_digest(task), 'native_source_sha256': native_source_sha256,
                'continuation_sha256': registration.continuation_sha256,
                'evidence_sha256': task_digest(list(evidence.values()))}}
    finally:
        reading.recheck()
