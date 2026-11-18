"""Link original owner selection and architect acceptance to received A03 inputs."""
from copy import deepcopy

from integration.architect_intake_results import SavedArchitectIntake
from integration.owner_commission_results import SavedOwnerCommission
from src.actions.contracts.architect_appointment_objects import (
    ArchitectAcceptanceView, ArchitectAppointmentView, service_terms_digest,
)
from src.actions.contracts.common import EvidenceRecord, Reference, TimeWindow
from src.actions.contracts.owner_commission_objects import (
    CommissionOfferView, CommissionProviderView, CommissionTermsView,
)
from src.actions.contracts.service_objects import ServiceRequestView, ServiceTermsView
from src.coordination.tasks import TaskConflict, task_digest


def read_owner_architect_commission(prepared, *, owner_task_sha256, provider_task_sha256,
        read_decisions, validate_mapping):
    """Read explicitly selected saved parties through the application's boundary.

    The reader must use the parties' authorized original journals and actual
    reception. Local role-contract output files cannot replace these records.
    """
    if not callable(read_decisions) or not callable(validate_mapping):
        raise TaskConflict('Commission reception requires original journal reader and mapping validator')
    try:
        selected = read_decisions(context=prepared.context.model_copy(deep=True),
            owner_task_sha256=owner_task_sha256, provider_task_sha256=provider_task_sha256)
        if (not isinstance(selected, tuple) or len(selected) != 2
                or not isinstance(selected[0], SavedOwnerCommission)
                or not isinstance(selected[1], SavedArchitectIntake)):
            raise TaskConflict('Commission reader must return original saved owner and architect decisions')
        owner, provider = selected
        if owner.identity.key != owner_task_sha256 or provider.identity.key != provider_task_sha256:
            raise TaskConflict('Commission reader substituted the explicitly selected original tasks')
        validate_owner_architect_commission(owner, provider, prepared=prepared, validate_mapping=validate_mapping)
        return {'owner_task_sha256': owner.identity.key, 'provider_task_sha256': provider.identity.key,
            'owner_record_sha256': owner.record_sha256, 'provider_record_sha256': provider.record_sha256,
            'owner_result_sha256': task_digest(owner.result.model_dump(mode='json')),
            'provider_result_sha256': task_digest(provider.result.model_dump(mode='json')),
            'appointment_ref': prepared.action_input.appointment_ref.model_dump(mode='json'),
            'accepted_terms_ref': prepared.action_input.accepted_terms_ref.model_dump(mode='json'),
            'appointment_source_reading_sha256': prepared.reading_sha256}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256
                or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
            raise TaskConflict('Commission journal reader changed original appointment input or sources')


def validate_owner_architect_commission(owner, provider, *, prepared, validate_mapping):
    """Validate explicit ContractTerms→ServiceTerms mapping, never create it.

    The application independently confirms actual publication, privacy, full
    term mapping (including authority limits/conditions) and original journal
    records. Fresh qualifications/capacity and the final choice remain A03's.
    """
    context, reading = prepared.context, prepared.reading
    if (not isinstance(owner, SavedOwnerCommission) or not isinstance(provider, SavedArchitectIntake)
            or prepared.ACTION_ID != 'ARCHITECT-A03' or not callable(validate_mapping)):
        raise TaskConflict('Commission handoff requires independently saved owner and architect decisions')
    reading.check_method_context(context, 'ARCHITECT-A03')
    originals = []
    for saved, action, role in ((owner, 'OWN-A04', 'Owner'), (provider, 'ARCHITECT-A02', 'Architect')):
        if (saved.identity.action_id != action or saved.identity.role != role
                or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
                or saved.context.contract_ref.id != action
                or saved.context.execution_mode != context.execution_mode
                or saved.context.business_time.clock_ref != context.business_time.clock_ref
                or saved.context.business_time.offset > context.business_time.offset
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'accept'
                or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
                or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
                or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
            raise TaskConflict('Commission handoff changes original successful party result or chronology')
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        if any(saved.audit.get(key) != value for key, value in {
                'run_id': context.run_id, 'action_id': action, 'operation_id': saved.context.operation_id,
                'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
                'result_kind': 'completed'}.items()):
            raise TaskConflict('Commission handoff lacks original successful independent party audit')
        sources = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in sources:
                raise TaskConflict('Commission handoff repeats an original source reference')
            sources[key] = row['projection']
        originals.append(sources)
    if (provider.identity.organization_id != reading.organization_id
            or provider.context.actor_id != context.actor_id
            or provider.context.function_ref != context.function_ref
            or owner.identity.organization_id == provider.identity.organization_id):
        raise TaskConflict('External commission handoff substitutes the independently deciding parties')
    before = task_digest(reading.evidence())
    if before != prepared.reading_sha256:
        raise TaskConflict('Commission handoff changed the original appointment source snapshot')
    try:
        owner_sources, provider_sources = originals
        offer = CommissionOfferView.model_validate(owner_sources[owner.result.payload.offer_ref.key()])
        owner_terms = CommissionTermsView.model_validate(owner_sources[owner.result.payload.terms_ref.key()])
        selected = CommissionProviderView.model_validate(owner_sources[offer.provider_ref.key()])
        appointment = reading.resolve(prepared.action_input.appointment_ref)
        terms = reading.resolve(prepared.action_input.accepted_terms_ref)
        if not isinstance(appointment, ArchitectAppointmentView) or not isinstance(terms, ServiceTermsView):
            raise TaskConflict('Commission handoff lacks original received appointment and service terms')
        if appointment.acceptance_ref is None:
            raise TaskConflict('Commission handoff requires separately received provider acceptance')
        acceptance = reading.resolve(appointment.acceptance_ref)
        request = reading.resolve(appointment.request_ref)
        if (not isinstance(acceptance, ArchitectAcceptanceView) or not isinstance(request, ServiceRequestView)
                or selected.organization_id != provider.identity.organization_id
                or selected.actor_id != provider.context.actor_id
                or selected.function_ref != provider.context.function_ref
                or offer.author_actor_id != provider.context.actor_id
                or offer.author_function_ref != provider.context.function_ref
                or offer.authority_action_id != 'ARCHITECT-A02'
                or offer.terms_ref != owner_terms.ref
                or owner_terms.employer_organization_id != owner.identity.organization_id
                or owner_terms.provider_organization_id != provider.identity.organization_id
                or owner_terms.payer_organization_id != appointment.payer_organization_id
                or owner_terms.payer_actor_id != appointment.payer_id
                or owner_terms.scope_ref != terms.scope or terms.scope != prepared.action_input.scope
                or appointment.client_organization_id != owner.identity.organization_id
                or appointment.relation != 'external'
                or appointment.terms_ref != terms.ref
                or provider.result.payload.accepted_terms_ref != terms.ref
                or provider_sources.get(terms.ref.key()) != terms.model_dump(mode='json')
                or provider_sources.get(request.ref.key()) != request.model_dump(mode='json')
                or acceptance.choice != 'accept' or acceptance.action_id != 'ARCHITECT-A02'
                or acceptance.actor_id != provider.context.actor_id
                or acceptance.organization_id != provider.identity.organization_id
                or acceptance.function_ref != provider.context.function_ref
                or acceptance.request_ref != provider.action_input.request_ref
                or acceptance.accepted_terms_ref != terms.ref
                or acceptance.decided_at != provider.context.business_time
                or acceptance.scope != terms.scope
                or acceptance.terms_digest != service_terms_digest(terms)
                or appointment.terms_digest != acceptance.terms_digest):
            raise TaskConflict('Commission handoff changes selected provider or independently accepted terms')
        # A single service-terms record must cover the complete selected owner
        # scope. Multi-service offers require an explicit separate assembly.
        if (owner_terms.service_codes.state != 'known' or terms.service_code.state != 'known'
                or owner_terms.service_codes.value != [terms.service_code.value]
                or owner_terms.requested_uses != terms.requested_uses
                or owner_terms.responsibility_codes != terms.responsibility_codes
                or owner_terms.deliverable_refs != terms.deliverable_requirement_refs
                or owner_terms.fee.state != 'known' or terms.fee.state != 'known'
                or owner_terms.fee.value != terms.fee.value
                or terms.desired_window.state != 'known'
                or TimeWindow.model_validate(owner_sources[owner_terms.window_ref.key()]) != terms.desired_window.value):
            raise TaskConflict('Commission handoff drops or changes service, fee, delivery or work-window terms')
        now = context.business_time
        for point in (acceptance.received_at, appointment.received_at):
            if (point.clock_ref != now.clock_ref or point.offset > now.offset
                    or point.offset < provider.context.business_time.offset):
                raise TaskConflict('Commission reception precedes provider acceptance or lies in the future')
        if appointment.received_at.offset < owner.context.business_time.offset:
            raise TaskConflict('Appointment reception precedes the original owner selection')
        if acceptance.received_at.offset > appointment.received_at.offset:
            raise TaskConflict('Appointment reception precedes its independent acceptance receipt')
        expected = {task_digest(saved.result.model_dump(mode='json')) for saved in (owner, provider)}
        actual = set()
        for ref in appointment.evidence_refs:
            evidence = reading.resolve(ref)
            if not isinstance(evidence, EvidenceRecord):
                raise TaskConflict('Commission appointment substitutes its original evidence schema')
            if evidence.content_hash not in expected:
                continue
            if (evidence.basis_kind != 'observed'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(now)
                    or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')):
                raise TaskConflict('Commission appointment lacks lawful observed party evidence')
            actual.add(evidence.content_hash)
        if not expected <= actual:
            raise TaskConflict('Received appointment does not retain both original party result digests')
        if validate_mapping(deepcopy(owner), deepcopy(provider), appointment.model_copy(deep=True),
                terms.model_copy(deep=True), acceptance.model_copy(deep=True),
                context.model_copy(deep=True)) is not True:
            raise TaskConflict('Actual application did not confirm reception and complete original term mapping')
    finally:
        reading.recheck()
        if (task_digest(reading.evidence()) != before
                or task_digest(context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Commission mapping validation changed original appointment inputs or sources')
