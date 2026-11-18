"""Assemble Contractor A01 input with source-reconciled enterprise capacity."""
from collections import Counter
from decimal import Decimal
from fractions import Fraction

from integration.bindings.gba_v1_capacity import GbaCapacityMappingView, prepare_gba_capacity_input
from src.actions.contracts.common import EvidenceRecord, Known, Reference, walk_references
from src.actions.contracts.contractor_objects import (
    CommitmentSnapshotView, ContractorCapabilityView, InvitationView,
    OpportunityScreeningProfileView, ProcurementPackageView, QualificationView,
    contractor_screening_schemas,
)
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import task_digest
from src.methods.capacity import CapacityCommitment, CapacityDemand, CapacityResource, ExactAmount


def gba_contractor_screening_source_schemas():
    """Keep A01's original closed schemas; add only the explicit source mapping."""
    schemas = contractor_screening_schemas()
    schemas.register_kind('GbaCapacityMapping', GbaCapacityMappingView, str)
    from integration.bindings.gba_v1_screening_resources import GbaScreeningEnterpriseFactsView
    schemas.register_kind('GbaScreeningEnterpriseFacts', GbaScreeningEnterpriseFactsView, str)
    return schemas


def _same_rows(left, right):
    # Demand order is immaterial, but repeated rows must not disappear.
    return Counter(task_digest(row.model_dump(mode='json')) for row in left) == Counter(
        task_digest(row.model_dump(mode='json')) for row in right)


def prepare_gba_contractor_screening_input(source, *, context, reading, registration,
        package_ref, capability_ref, commitments_ref, screening_profile_ref,
        qualification_refs=(), invitation_refs=(), mapping_ref=None):
    """Produce typed input from exact authorized refs without running A01.

    The host supplies procurement, qualification and policy facts independently.
    Their existing resource projections must exactly match the current GBA
    source-backed calendar, including every commitment and demand. This function
    does not replace immutable projections, convert physical units, calculate
    feasibility, choose participation or submit any intention to the macro.
    """
    if (not isinstance(reading, ActionReadView) or registration.action_id != 'CONTRACTOR-A01'
            or context.contract_ref.kind != 'ActionContract'
            or context.contract_ref.id != registration.action_id
            or not registration.implemented or registration.skill is None):
        raise ValueError('Source-backed screening requires the actual registered Contractor A01 and reading')
    reading.check_method_context(context, registration.action_id)
    if mapping_ref is not None:
        mapping_ref = Reference.model_validate(mapping_ref)

    def missing(field, refs=()):
        return {'kind': 'needs_information', 'missing_fields': [field], 'requested_refs': list(refs)}

    def unsupported(identity):
        return {'kind': 'unsupported', 'capability_ref': {
            'kind': 'Capability', 'id': identity, 'version': '1'}}

    def read(ref, schema):
        value = reading.resolve(ref)
        if not isinstance(value, schema) or value.ref != ref:
            raise ValueError('Screening source input lacks its exact concrete projection schema')
        for evidence_ref in value.evidence_refs:
            evidence = reading.resolve(evidence_ref)
            if not isinstance(evidence, EvidenceRecord):
                raise ValueError('Screening projection lacks typed authorized source evidence')
        return value

    try:
        action_input = registration.contract.validate_input({
            'package_ref': package_ref, 'capability_ref': capability_ref,
            'commitments_ref': commitments_ref, 'screening_profile_ref': screening_profile_ref,
            'qualification_refs': list(qualification_refs), 'invitation_refs': list(invitation_refs)})
        unique_refs(action_input.qualification_refs)
        unique_refs(action_input.invitation_refs)
        for ref in walk_references(action_input):
            reading.resolve(ref)
        package = read(action_input.package_ref, ProcurementPackageView)
        capability = read(action_input.capability_ref, ContractorCapabilityView)
        commitments = read(action_input.commitments_ref, CommitmentSnapshotView)
        profile = read(action_input.screening_profile_ref, OpportunityScreeningProfileView)
        if (capability.organization_ref != commitments.organization_ref
                or capability.organization_ref != profile.organization_ref
                or capability.organization_ref.id != reading.organization_id
                or context.scope.kind == 'organization' and context.scope.ref != capability.organization_ref
                or context.scope.kind != 'organization' and context.scope != package.scope):
            raise ValueError('Screening source refs change the original enterprise or procurement scope')
        for ref in action_input.qualification_refs:
            if read(ref, QualificationView).organization_ref != capability.organization_ref:
                raise ValueError('Screening qualification belongs to another enterprise')
        for ref in action_input.invitation_refs:
            invite = read(ref, InvitationView)
            if (invite.package_ref != package.ref or invite.issuer_ref != package.employer_ref
                    or invite.recipient_actor_id != context.actor_id):
                raise ValueError('Screening invitation changes the original procurement recipient')
        candidates = reading.resolve(context.candidate_set_ref)
        if not isinstance(candidates, CandidateSet):
            raise ValueError('Screening input requires a typed current authorized candidate set')
        candidates.check_context(context, registration.contract.choices)
        if package.ref.key() not in {row.ref.key() for row in candidates.candidates}:
            raise ValueError('Screening package is outside the current authorized candidates')
        now = context.business_time
        if (not capability.effective_window.contains(now) or not profile.effective_window.contains(now)
                or commitments.as_of != now):
            return missing('current_screening_capability_policy_and_commitments',
                           [capability.ref, profile.ref, commitments.ref])
        if capability.resource_coverage != 'complete' or commitments.coverage != 'complete':
            return missing('complete_source_backed_screening_resources', [capability.ref, commitments.ref])

        prepared = prepare_gba_capacity_input(source, context=context, reading=reading, mapping_ref=mapping_ref)
        if prepared['kind'] != 'prepared':
            return prepared
        data = prepared['data']
        mapping = reading.resolve(mapping_ref)
        provenance = {mapping.source_evidence_ref.key(), *[ref.key() for ref in mapping.calendar_evidence_refs]}
        if any(not provenance <= {ref.key() for ref in row.evidence_refs}
               for row in (capability, commitments)):
            return missing('screening_projections_linked_to_actual_source_and_calendar',
                           [capability.ref, commitments.ref])
        if any(resource.resource_ref.kind != 'Resource' for resource in data.resources):
            return unsupported('gba-screening-resource-pool-reference')
        resources = []
        for row in capability.resources:
            if not isinstance(row.region_id, Known) or not isinstance(row.total, Known):
                return missing('known_source_backed_screening_resource_location_and_total', [capability.ref])
            resources.append(CapacityResource(resource_ref=row.resource_ref, resource_kind=row.resource_kind,
                region_id=row.region_id.value, total=row.total.value, effective_window=row.effective_window))
        allocations = [CapacityCommitment.model_validate(row.model_dump(mode='python'))
                       for row in commitments.allocations]
        if not _same_rows(resources, data.resources) or not _same_rows(allocations, data.commitments):
            return missing('screening_resource_calendar_reconciled_with_actual_source',
                           [capability.ref, commitments.ref, mapping.ref])
        if not isinstance(package.resource_demands, Known):
            if package.resource_demands.state == 'not_supported':
                return {'kind': 'unsupported', 'capability_ref': package.resource_demands.capability_ref}
            return missing('known_authorized_procurement_resource_demands', [package.ref])
        if not package.resource_demands.value:
            return unsupported('gba-screening-nonempty-capacity-demand')
        demands = [CapacityDemand(resource_kind=row.resource_kind, region_id=row.region_id,
            unit=row.quantity.unit, amount=ExactAmount.from_fraction(Fraction(Decimal(row.quantity.value))),
            window=row.window, basis_refs=[row.quantity.basis_ref]) for row in package.resource_demands.value]
        if not _same_rows(demands, data.demands):
            return missing('capacity_mapping_for_exact_original_procurement_demands', [package.ref, mapping.ref])
        reading.recheck()
        return {'kind': 'prepared', 'action_id': registration.action_id, 'input': action_input,
                'input_sha256': task_digest(action_input.model_dump(mode='json')),
                'context_sha256': task_digest(context.model_dump(mode='json')),
                'source_record_sha256': prepared['source_record_sha256'],
                'capacity_input_sha256': prepared['input_sha256'],
                'read_sha256': task_digest(reading.evidence()), 'source_mode': prepared['source_mode'],
                'limitations': ['Input assembly only; registered A01 business checks still required.',
                                'GBA normalized capacity is preserved without physical unit conversion.',
                                'Procurement, qualifications, invitations and policy require independent host facts.',
                                'No participation decision, capacity calculation, reservation or macro submission.']}
    finally:
        reading.recheck()
