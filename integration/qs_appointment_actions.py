"""Assemble original QS A03 appointments and independent acceptance sources."""
from copy import deepcopy
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import ClassVar

from integration.qs_market_actions import QSMarketActionAssembler, PreparedQSMarket
from src.actions.contracts.architect_appointment_objects import ArchitectRelationshipView, ArchitectReservationView
from src.actions.contracts.qs_appointment_objects import (
    QSAcceptanceView, QSAppointmentView, QSTaskCalendarView, QSTaskView,
    QSAllocationView, QSWorkPlanView, QSTaskDependencyView, qs_appointment_schemas,
)
from src.actions.contracts.bank_credit_objects import unique_identities
from src.actions.contracts.service_objects import (
    ServiceClarificationTargetView, ServiceRequestView, ServiceWorkProfileView,
    ServiceResponseRequirementView, ServiceTermsView,
)
from src.actions.contracts.common import ActionContext
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedQSAppointment(PreparedQSMarket):
    ACTION_ID: ClassVar[str] = 'QS-A03'


class QSAppointmentActionAssembler(QSMarketActionAssembler):
    """Freeze original appointment identities without confirming or reserving work.

    The application holds its current source/authorization guard. Original
    processor checks independently recorded acceptance, exact terms digests,
    valid function authority, current commitments and original planning branches. Older
    terms, decline records, released reservations and null reservations retain
    their original state. Assembly creates no relationship or resource occupancy.
    """
    ACTION_ID = 'QS-A03'
    SOURCE_SCHEMAS = staticmethod(qs_appointment_schemas)

    def build_from_research_task(self, context, *, research_submission, research_identity,
            research_execution_versions, research_read_context, registration_ref, native_evidence_ref,
            native_source_sha256, relation_evidence_refs, read_guard, validate_history,
            validate_current, validate_receipt_relation, **source_refs):
        """Bind actual A13 investigation intake and continuation confirmation to A03 planning."""
        from integration.qs_research_task_handoff import prepare_qs_research_task_handoff
        from integration.qs_research_results import QSResearchResultWorker
        from integration.qs_submission import QSResultSubmission
        from integration.macro_views import AuthorizedMacroViewAssembler
        from src.actions.contracts.qs_research_objects import qs_research_schemas

        if (not isinstance(research_submission, QSResultSubmission)
                or research_submission.ACTION_ID != 'QS-A13'
                or not isinstance(research_submission.worker, QSResearchResultWorker)
                or research_submission.worker.registry is not self.registry
                or research_submission.worker.store.run_id != self.organizations.run_id or self.source_mode != 'formal'
                or not all(callable(callback) for callback in
                    (read_guard, validate_history, validate_current, validate_receipt_relation))):
            raise TaskConflict('Investigation task requires original A13 submission/worker and actual guarded source checks')
        context = self._context(context)
        own_context = ActionContext.model_validate(research_read_context).model_copy(deep=True)
        if (own_context.contract_ref.kind != 'ActionContract' or own_context.contract_ref.id != 'QS-A13'
                or own_context.execution_mode == 'offline_fixture'
                or any(getattr(own_context, name) != getattr(context, name) for name in
                    ('run_id', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('Investigation intake requires independently authorized A13 history at the current A03 scope/time')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(source_refs)
        with read_guard(context.model_copy(deep=True)):
            receipt = research_submission.read_receipt(research_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected investigation proposal cannot establish actual research task intake')
            own_views = AuthorizedMacroViewAssembler(self.organizations, self.provider, qs_research_schemas(),
                macro_version=self.macro_version, source_mode='formal')
            own_resolver = own_views.build_resolver(own_context, 'QS-A13', 'QS')
            own_reading = ActionReadView(own_context, own_resolver, self.organizations, 'QS-A13', 'QS')
            reading = None
            try:
                saved = research_submission.worker.read_completed(research_identity, current_context=own_context,
                    reading=own_reading, execution_versions=research_execution_versions, validate_current=validate_history)
                reading = self.build_result_reading(context)
                preflight = SimpleNamespace(context=context, action_input=action_input, reading=reading)

                def validate_link(**sources):
                    if (sources['saved'].identity.as_dict() != receipt['identity']
                            or sources['saved'].record_sha256 != receipt['record_sha256']):
                        raise TaskConflict('Investigation proposal receipt substitutes its original saved result')
                    return (validate_current(**sources) is True
                        and validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True)

                handoff = prepare_qs_research_task_handoff(saved, invocation=preflight,
                    registration_ref=registration_ref, native_evidence_ref=native_evidence_ref,
                    native_source_sha256=native_source_sha256, relation_evidence_refs=relation_evidence_refs,
                    validate_current=validate_link)
                if research_submission.read_receipt(research_identity) != receipt:
                    raise TaskConflict('Original investigation receipt changed during actual task linkage')
                if handoff['kind'] != 'prepared':
                    return handoff
                invocation = self.build(context, **source_refs)
                if any(invocation.reading._reads.get(key) != row for key, row in reading._reads.items()):
                    raise TaskConflict('Actual research task differs from the frozen A03 source snapshot')
                invocation.reading.recheck()
                if research_submission.read_receipt(research_identity) != receipt:
                    raise TaskConflict('Original investigation receipt changed before A03 assembly completed')
                return {**handoff, 'provenance': {**handoff['provenance'], 'submission': deepcopy(receipt)},
                    'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}
            finally:
                if reading is not None:
                    reading.recheck()
                own_reading.recheck()

    def build(self, context, *, scope, appointment_ref, accepted_terms_ref, function_refs,
            task_refs, capacity_ref, work_profile_ref, existing_allocation_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'appointment_ref': appointment_ref, 'accepted_terms_ref': accepted_terms_ref,
            'function_refs': function_refs, 'task_refs': task_refs, 'capacity_ref': capacity_ref,
            'work_profile_ref': work_profile_ref, 'existing_allocation_refs': existing_allocation_refs},
            prepared_type=PreparedQSAppointment, validate_sources=validate_qs_appointment_sources)


def validate_qs_appointment_sources(action_input, *, context, organization_id, sources):
    """Check original parties and related sources without evaluating compatibility."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('QS appointment lacks its exact original concrete source')
        return row

    if not scope_covers(context.scope, action_input.scope):
        raise TaskConflict('QS appointment input leaves its original authorized scope')
    unique_identities(action_input.function_refs)
    appointment = read(action_input.appointment_ref, QSAppointmentView)
    terms = read(action_input.accepted_terms_ref, ServiceTermsView)
    if (appointment.provider_organization_id != organization_id or appointment.provider_id != context.actor_id
            or terms.provider_id != context.actor_id or appointment.scope != action_input.scope
            or terms.scope != action_input.scope or terms.request_ref.key() != appointment.request_ref.key()
            or terms.client_id != appointment.client_id or terms.payer_id != appointment.payer_id
            or terms.relation != appointment.relation):
        raise TaskConflict('QS appointment changes original provider, request, parties or scope')
    if appointment.request_ref.key() in sources:
        request = read(appointment.request_ref, ServiceRequestView)
        if (request.scope != action_input.scope
                or any(getattr(request, name) != getattr(appointment, name) for name in (
                    'provider_id', 'provider_organization_id', 'client_id', 'client_organization_id',
                    'payer_id', 'payer_organization_id', 'client_authority_ref', 'payer_authority_ref'))):
            raise TaskConflict('QS appointment changes its original service request or parties')
    if appointment.acceptance_ref is not None and appointment.acceptance_ref.key() in sources:
        acceptance = read(appointment.acceptance_ref, QSAcceptanceView)
        if (acceptance.actor_id != context.actor_id or acceptance.organization_id != organization_id
                or acceptance.scope != action_input.scope or acceptance.request_ref.key() != appointment.request_ref.key()):
            raise TaskConflict('QS appointment borrows another provider acceptance or request')
        # Its original choice, accepted version and digest remain processor inputs.
    if appointment.capacity_ref.key() in sources:
        read(appointment.capacity_ref, QSTaskCalendarView)
    if appointment.reservation_ref is not None and appointment.reservation_ref.key() in sources:
        reservation = read(appointment.reservation_ref, ArchitectReservationView)
        if (reservation.organization_id != organization_id or reservation.scope != action_input.scope
                or reservation.appointment_ref.key() != appointment.ref.key()):
            raise TaskConflict('QS reservation changes its original organization, appointment or scope')
        # Preserve old terms and actual occupancy; never convert or release here.
    if appointment.service_relationship_ref is not None and appointment.service_relationship_ref.key() in sources:
        relationship = read(appointment.service_relationship_ref, ArchitectRelationshipView)
        if (relationship.organization_id != organization_id or relationship.scope != action_input.scope
                or relationship.appointment_ref.key() != appointment.ref.key()):
            raise TaskConflict('QS service relationship changes its original organization, appointment or scope')
    for ref in appointment.amendment_target_refs:
        if ref.key() in sources:
            question = read(ref, ServiceClarificationTargetView)
            if question.request_ref.key() != appointment.request_ref.key() or question.scope != action_input.scope:
                raise TaskConflict('QS amendment changes its original request or scope')
            if question.response_requirement_ref.key() in sources:
                response = read(question.response_requirement_ref, ServiceResponseRequirementView)
                if response.request_ref.key() != appointment.request_ref.key() or response.scope != action_input.scope:
                    raise TaskConflict('QS amendment response changes its original request or scope')

    unique_identities(action_input.task_refs)
    unique_identities(action_input.existing_allocation_refs)
    read(action_input.capacity_ref, QSTaskCalendarView)
    if action_input.work_profile_ref is not None:
        read(action_input.work_profile_ref, ServiceWorkProfileView)
    prior = None
    if appointment.prior_plan_ref is not None and appointment.prior_plan_ref.key() in sources:
        prior = read(appointment.prior_plan_ref, QSWorkPlanView)
        if prior.organization_id != organization_id or prior.appointment_ref.key() != appointment.ref.key():
            raise TaskConflict('QS task plan changes its original organization or appointment')
    for ref in action_input.task_refs:
        task = read(ref, QSTaskView)
        if (task.organization_id != organization_id or task.appointment_ref.key() != appointment.ref.key()
                or task.scope != action_input.scope):
            raise TaskConflict('QS task changes its original organization, appointment or scope')
        for dependency_ref in task.dependency_refs:
            if dependency_ref.key() in sources:
                dependency = read(dependency_ref, QSTaskDependencyView)
                if dependency.task_ref.key() != task.ref.key() or dependency.scope != task.scope:
                    raise TaskConflict('QS task dependency changes its original task or scope')
    for ref in action_input.existing_allocation_refs:
        allocation = read(ref, QSAllocationView)
        if (allocation.organization_id != organization_id or allocation.appointment_ref.key() != appointment.ref.key()
                or allocation.scope != action_input.scope
                or prior is not None and allocation.work_plan_ref.key() != prior.ref.key()):
            raise TaskConflict('QS allocation changes its original organization, appointment, scope or plan')
    # Original processor owns acceptance/version/conflict gates and exact task,
    # method, dependency and allocation completeness; assembly never occupies resources.
