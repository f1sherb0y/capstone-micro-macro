"""Assemble authorized OWN-A04 professional commission inputs."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_commission_objects import (
    CommissionCaseView, CommissionInternalPlanView, CommissionManagementView, CommissionOfferView,
    CommissionOrganizationView, CommissionProfileView, CommissionProjectView, CommissionProviderView,
    CommissionResourceView, CommissionServiceScopeView, owner_commission_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.models import Authorization
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedOwnerCommission(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A04'


class OwnerCommissionActionAssembler(OwnerObservationActionAssembler):
    """Preserve the complete input and each provider's independent offer.

    The application holds its actual source/authorization guard. Preparation
    forms no appointment, contract, internal task or resource reservation.
    Qualification, fees, current authority and choices remain in A04.
    """
    ACTION_ID = 'OWN-A04'
    SOURCE_SCHEMAS = staticmethod(owner_commission_schemas)

    def build(self, context, *, scope_ref, procurement_profile_ref, service_scope_ref,
            candidate_provider_refs, candidates, authority_ref, capacity_ref):
        return self._prepare_supplied_snapshot(context,
            input_values={'scope_ref': scope_ref, 'procurement_profile_ref': procurement_profile_ref,
                'service_scope_ref': service_scope_ref, 'candidate_provider_refs': candidate_provider_refs,
                'candidates': candidates, 'authority_ref': authority_ref, 'capacity_ref': capacity_ref},
            prepared_type=PreparedOwnerCommission, validate_sources=self._validate_commission_sources)

    @staticmethod
    def _validate_commission_sources(action_input, *, context, reading):
        validate_owner_commission_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_commission_sources(action_input, *, context, organization_id, sources):
    """Validate original identities; evaluate eligibility and commitments in A04."""
    profile = sources.get(action_input.procurement_profile_ref.key())
    service = sources.get(action_input.service_scope_ref.key())
    capacity = sources.get(action_input.capacity_ref.key())
    authority = sources.get(action_input.authority_ref.key())
    if (not isinstance(profile, CommissionProfileView) or not isinstance(service, CommissionServiceScopeView)
            or not isinstance(capacity, CommissionManagementView) or not isinstance(authority, Authorization)
            or profile.organization_id != organization_id or service.employer_organization_id != organization_id
            or capacity.organization_id != organization_id
            or profile.service_scope_ref.key() != service.ref.key()
            or profile.scope_ref != action_input.scope_ref or service.scope_ref != action_input.scope_ref
            or not scope_covers(context.scope, service.scope_ref)):
        raise TaskConflict('Owner commission changes its original owner, service/profile or invocation scope')
    unique_refs(action_input.candidate_provider_refs)
    unique_refs(action_input.candidates)
    parent = sources.get(service.scope_ref.ref.key())
    parent_schema, owner_field = {
        'organization': (CommissionOrganizationView, 'organization_id'),
        'assessment_case': (CommissionCaseView, 'organization_id'),
        'project': (CommissionProjectView, 'owner_organization_id'),
    }[service.scope_ref.kind]
    if not isinstance(parent, parent_schema) or getattr(parent, owner_field) != organization_id:
        raise TaskConflict('Owner commission service belongs to another owner parent scope')
    for ref in action_input.candidate_provider_refs:
        if not isinstance(sources.get(ref.key()), CommissionProviderView):
            raise TaskConflict('Owner commission candidate changes its original provider projection')
    for ref in action_input.candidates:
        offer = sources.get(ref.key())
        if not isinstance(offer, CommissionOfferView) or offer.service_scope_ref.key() != service.ref.key():
            raise TaskConflict('Owner commission offer changes the original requested service version')
    # Only validate output dependencies actually provided. The original
    # processor retains reject/retender/defer and missing-input decisions.
    for ref in capacity.resource_refs:
        pool = sources.get(ref.key())
        if pool is not None and (not isinstance(pool, CommissionResourceView) or pool.organization_id != organization_id):
            raise TaskConflict('Owner commission imports another organization private resource pool')
    if profile.internal_plan_ref is not None:
        plan = sources.get(profile.internal_plan_ref.key())
        if plan is not None and (not isinstance(plan, CommissionInternalPlanView)
                or plan.organization_id != organization_id or plan.service_scope_ref.key() != service.ref.key()):
            raise TaskConflict('Owner commission internal plan changes the original owner or service')
