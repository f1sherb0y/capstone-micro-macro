"""Assemble original Engineer A02 service requests and private intake sources."""
from dataclasses import dataclass
from typing import ClassVar

from integration.engineer_opportunity_actions import EngineerOpportunityActionAssembler, PreparedEngineerOpportunity
from src.actions.contracts.service_objects import (
    ServiceClarificationTargetView, ServiceCommissionAuthorityView, ServiceDeliverableRequirementView,
    ServiceFeeBasisView, ServiceFeeCalculationView, ServiceResponseRequirementView,
)
from src.actions.contracts.engineer_objects import (
    EngineerIntakeCapabilityView, EngineerQualificationView, EngineerServiceRequestView,
    EngineerResourceCalendarView, EngineerServiceTermsView, EngineerIndependenceRequirementView,
    EngineerOrganizationRelationsView, EngineerAuthoredTargetView, engineer_intake_schemas,
)
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedEngineerIntake(PreparedEngineerOpportunity):
    ACTION_ID: ClassVar[str] = 'ENGINEER-A02'


class EngineerIntakeActionAssembler(EngineerOpportunityActionAssembler):
    """Freeze original terms and pricing alternatives without accepting service.

    The application holds its current source/authorization guard. The existing
    service processor checks actual independent client/payer authority, current
    qualification, capacity, finite effort, fees and all four choices. Assembly
    creates no appointment, accepted counterpart terms, reservation or income.
    Unknown professional scope and independence remain original processor decisions.
    """
    ACTION_ID = 'ENGINEER-A02'
    SOURCE_SCHEMAS = staticmethod(engineer_intake_schemas)

    def build(self, context, *, scope, request_ref, terms_ref, capability_ref, capacity_ref, independence_requirement_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'request_ref': request_ref, 'terms_ref': terms_ref,
            'capability_ref': capability_ref, 'capacity_ref': capacity_ref, 'independence_requirement_ref': independence_requirement_ref},
            prepared_type=PreparedEngineerIntake, validate_sources=validate_engineer_intake_sources)


def validate_engineer_intake_sources(action_input, *, context, organization_id, sources):
    """Check original request, parties and supplied alternative provenance only."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Engineer intake lacks its exact original concrete source')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Engineer intake changes its original invocation scope')
    request = read(action_input.request_ref, EngineerServiceRequestView)
    offered = read(action_input.terms_ref, EngineerServiceTermsView)
    capability = read(action_input.capability_ref, EngineerIntakeCapabilityView)
    calendar = read(action_input.capacity_ref, EngineerResourceCalendarView)
    pricing = read(request.fee_basis_ref, ServiceFeeBasisView) if request.fee_basis_ref.key() in sources else None
    if (request.provider_organization_id != organization_id or capability.organization_id != organization_id
            or calendar.organization_id != organization_id
            or request.provider_id != context.actor_id or request.scope != context.scope
            or request.offered_terms_ref.key() != offered.ref.key()
            or pricing is not None and (pricing.organization_id != organization_id or not scope_covers(pricing.scope, context.scope))):
        raise TaskConflict('Engineer intake changes original provider, private sources, scope or terms version')

    def validate_terms(terms):
        if (terms.request_ref.key() != request.ref.key() or terms.scope != request.scope
                or terms.provider_id != request.provider_id or terms.client_id != request.client_id
                or terms.payer_id != request.payer_id or terms.relation != offered.relation):
            raise TaskConflict('Engineer service terms change the original request, scope or parties')
        for ref in terms.deliverable_requirement_refs:
            if ref.key() in sources:
                requirement = read(ref, ServiceDeliverableRequirementView)
                if requirement.request_ref.key() != request.ref.key() or requirement.scope != terms.scope:
                    raise TaskConflict('Engineer deliverable requirement changes its original request or scope')

    def validate_independence(requirement):
        if requirement.request_ref.key() != request.ref.key() or requirement.scope != request.scope:
            raise TaskConflict('Engineer independence requirement changes its original request or scope')
        if requirement.relations_ref.key() in sources:
            relations = read(requirement.relations_ref, EngineerOrganizationRelationsView)
            if relations.organization_id != organization_id:
                raise TaskConflict('Engineer independence relations change their original firm')
        for ref in requirement.target_refs:
            if ref.key() in sources and read(ref, EngineerAuthoredTargetView).scope != request.scope:
                raise TaskConflict('Engineer independence target changes its original service scope')

    validate_terms(offered)
    if offered.independence_requirement_ref is not None and offered.independence_requirement_ref.key() in sources:
        validate_independence(read(offered.independence_requirement_ref, EngineerIndependenceRequirementView))
    for ref in (pricing.counteroffer_terms_refs if pricing is not None else []):
        if ref.key() in sources:
            validate_terms(read(ref, EngineerServiceTermsView))
    for index, ref in enumerate(pricing.counteroffer_calculation_refs if pricing is not None else []):
        if ref.key() in sources:
            calculation = read(ref, ServiceFeeCalculationView)
            if (calculation.organization_id != organization_id or calculation.scope != context.scope
                    or calculation.fee_basis_ref.key() != pricing.ref.key()
                    or index < len(pricing.counteroffer_terms_refs)
                    and calculation.terms_ref.key() != pricing.counteroffer_terms_refs[index].key()):
                raise TaskConflict('Engineer fee calculation changes its original organization, terms or pricing basis')
    for ref in capability.qualification_refs:
        if ref.key() in sources and read(ref, EngineerQualificationView).organization_id != organization_id:
            raise TaskConflict('Engineer qualification changes its original private organization')
    for ref, party, actor in (
            (request.client_authority_ref, request.client_organization_id, request.client_id),
            (request.payer_authority_ref, request.payer_organization_id, request.payer_id)):
        if ref.key() in sources:
            authority = read(ref, ServiceCommissionAuthorityView)
            if authority.organization_id != party or authority.actor_id != actor:
                raise TaskConflict('Engineer service authority changes its original client or payer identity')
    for ref in request.open_question_refs:
        if ref.key() in sources:
            question = read(ref, ServiceClarificationTargetView)
            if question.request_ref.key() != request.ref.key() or question.scope != request.scope:
                raise TaskConflict('Engineer clarification changes its original request or scope')
            if question.response_requirement_ref.key() in sources:
                response = read(question.response_requirement_ref, ServiceResponseRequirementView)
                if response.request_ref.key() != request.ref.key() or response.scope != request.scope:
                    raise TaskConflict('Engineer clarification response changes its original request or scope')

    if action_input.independence_requirement_ref is not None:
        validate_independence(read(action_input.independence_requirement_ref, EngineerIndependenceRequirementView))
