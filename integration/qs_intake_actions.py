"""Assemble original QS A02 service requests and private intake sources."""
from dataclasses import dataclass
from typing import ClassVar

from integration.qs_market_actions import QSMarketActionAssembler, PreparedQSMarket
from src.actions.contracts.qs_objects import QSConflictCheckView, qs_intake_schemas
from src.actions.contracts.service_objects import (
    ServiceClarificationTargetView, ServiceCommissionAuthorityView, ServiceDeliverableRequirementView,
    ServiceFeeBasisView, ServiceFeeCalculationView, ServiceIntakeCapabilityView,
    ServiceQualificationView, ServiceRequestView, ServiceResourceCalendarView,
    ServiceResponseRequirementView, ServiceTermsView,
)
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedQSIntake(PreparedQSMarket):
    ACTION_ID: ClassVar[str] = 'QS-A02'


class QSIntakeActionAssembler(QSMarketActionAssembler):
    """Freeze original terms and pricing alternatives without accepting service.

    The application holds its current source/authorization guard. The existing
    service processor checks actual independent client/payer authority, current
    qualification, capacity, finite effort, fees and all four choices. Assembly
    creates no appointment, accepted counterpart terms, reservation or income.
    """
    ACTION_ID = 'QS-A02'
    SOURCE_SCHEMAS = staticmethod(qs_intake_schemas)

    def build(self, context, *, scope, request_ref, terms_ref, capability_ref, capacity_ref, conflict_check_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'request_ref': request_ref, 'terms_ref': terms_ref,
            'capability_ref': capability_ref, 'capacity_ref': capacity_ref, 'conflict_check_ref': conflict_check_ref},
            prepared_type=PreparedQSIntake, validate_sources=validate_qs_intake_sources)


def validate_qs_intake_sources(action_input, *, context, organization_id, sources):
    """Check original request, parties and supplied alternative provenance only."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('QS intake lacks its exact original concrete source')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('QS intake changes its original invocation scope')
    request = read(action_input.request_ref, ServiceRequestView)
    offered = read(action_input.terms_ref, ServiceTermsView)
    capability = read(action_input.capability_ref, ServiceIntakeCapabilityView)
    calendar = read(action_input.capacity_ref, ServiceResourceCalendarView)
    pricing = read(request.fee_basis_ref, ServiceFeeBasisView) if request.fee_basis_ref.key() in sources else None
    if (request.provider_organization_id != organization_id or capability.organization_id != organization_id
            or calendar.organization_id != organization_id
            or request.provider_id != context.actor_id or request.scope != context.scope
            or request.offered_terms_ref.key() != offered.ref.key()
            or pricing is not None and (pricing.organization_id != organization_id or not scope_covers(pricing.scope, context.scope))):
        raise TaskConflict('QS intake changes original provider, private sources, scope or terms version')

    def validate_terms(terms):
        if (terms.request_ref.key() != request.ref.key() or terms.scope != request.scope
                or terms.provider_id != request.provider_id or terms.client_id != request.client_id
                or terms.payer_id != request.payer_id or terms.relation != offered.relation):
            raise TaskConflict('QS service terms change the original request, scope or parties')
        for ref in terms.deliverable_requirement_refs:
            if ref.key() in sources:
                requirement = read(ref, ServiceDeliverableRequirementView)
                if requirement.request_ref.key() != request.ref.key() or requirement.scope != terms.scope:
                    raise TaskConflict('QS deliverable requirement changes its original request or scope')

    validate_terms(offered)
    for ref in (pricing.counteroffer_terms_refs if pricing is not None else []):
        if ref.key() in sources:
            validate_terms(read(ref, ServiceTermsView))
    for index, ref in enumerate(pricing.counteroffer_calculation_refs if pricing is not None else []):
        if ref.key() in sources:
            calculation = read(ref, ServiceFeeCalculationView)
            if (calculation.organization_id != organization_id or calculation.scope != context.scope
                    or calculation.fee_basis_ref.key() != pricing.ref.key()
                    or index < len(pricing.counteroffer_terms_refs)
                    and calculation.terms_ref.key() != pricing.counteroffer_terms_refs[index].key()):
                raise TaskConflict('QS fee calculation changes its original organization, terms or pricing basis')
    for ref in capability.qualification_refs:
        if ref.key() in sources and read(ref, ServiceQualificationView).organization_id != organization_id:
            raise TaskConflict('QS qualification changes its original private organization')
    for ref, party, actor in (
            (request.client_authority_ref, request.client_organization_id, request.client_id),
            (request.payer_authority_ref, request.payer_organization_id, request.payer_id)):
        if ref.key() in sources:
            authority = read(ref, ServiceCommissionAuthorityView)
            if authority.organization_id != party or authority.actor_id != actor:
                raise TaskConflict('QS service authority changes its original client or payer identity')
    for ref in request.open_question_refs:
        if ref.key() in sources:
            question = read(ref, ServiceClarificationTargetView)
            if question.request_ref.key() != request.ref.key() or question.scope != request.scope:
                raise TaskConflict('QS clarification changes its original request or scope')
            if question.response_requirement_ref.key() in sources:
                response = read(question.response_requirement_ref, ServiceResponseRequirementView)
                if response.request_ref.key() != request.ref.key() or response.scope != request.scope:
                    raise TaskConflict('QS clarification response changes its original request or scope')

    if action_input.conflict_check_ref is not None:
        conflict = read(action_input.conflict_check_ref, QSConflictCheckView)
        if (conflict.organization_id != organization_id or conflict.request_ref.key() != request.ref.key()
                or conflict.scope != action_input.scope):
            raise TaskConflict('QS conflict check changes its original organization, request or scope')
    # Original processor keeps failed/unknown/conflicting checks distinct. A null
    # check can still allow a counteroffer, without implying independent acceptance.
