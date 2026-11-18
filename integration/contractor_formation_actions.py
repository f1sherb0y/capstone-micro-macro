"""Assemble original Contractor A04 inputs without forming a contract."""
from dataclasses import dataclass
from typing import ClassVar

from integration.contractor_amendment_actions import ContractorAmendmentActionAssembler, PreparedContractorAmendment
from src.actions.contracts.contractor_amendment_objects import ContractorAmendmentBidView, ContractorAmendmentSubmissionView
from src.actions.contracts.contractor_bid_objects import (
    ContractorBidCapacityView, ContractorBidCommitmentView, ContractorBidResourceView,
)
from src.actions.contracts.contractor_formation_objects import (
    ContractorFormationAcceptanceView, ContractorFormationCashPaymentView,
    ContractorFormationCashPlanView, ContractorFormationCashSourceView,
    ContractorFormationContractPaymentView, ContractorFormationFundingView,
    ContractorFormationOfferView, ContractorFormationProfileView,
    ContractorFormationReferenceView, ContractorFormationTermsView,
    contractor_formation_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.models import Authorization


@dataclass(frozen=True)
class PreparedContractorFormation(PreparedContractorAmendment):
    ACTION_ID: ClassVar[str] = 'CONTRACTOR-A04'


class ContractorFormationActionAssembler(ContractorAmendmentActionAssembler):
    """Freeze final agreement and independently supplied capacity/cash snapshots.

    The actual application holds the current source/authorization guard. The
    processor checks agreement review, independent author authority, freshness,
    acceptance gates, cash and capacity. No accepted party, contract, resource
    reservation, receipt or payment is generated during input assembly.
    """
    ACTION_ID = 'CONTRACTOR-A04'
    SOURCE_SCHEMAS = staticmethod(contractor_formation_schemas)

    def build(self, context, *, offer_ref, terms_ref, counterpart_acceptance_refs,
            authority_ref, capacity_ref, funding_ref, formation_profile_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'offer_ref': offer_ref, 'terms_ref': terms_ref,
            'counterpart_acceptance_refs': counterpart_acceptance_refs,
            'authority_ref': authority_ref, 'capacity_ref': capacity_ref,
            'funding_ref': funding_ref, 'formation_profile_ref': formation_profile_ref},
            prepared_type=PreparedContractorFormation, validate_sources=validate_contractor_formation_sources)


def validate_contractor_formation_sources(action_input, *, context, organization_id, sources):
    """Check exact supplied identities without evaluating contract formation."""
    def read(ref, schema):
        value = sources.get(ref.key())
        if not isinstance(value, schema) or value.ref.key() != ref.key():
            raise TaskConflict('Contract formation lacks its exact original concrete source')
        return value

    offer = read(action_input.offer_ref, ContractorFormationOfferView)
    terms = read(action_input.terms_ref, ContractorFormationTermsView)
    profile = read(action_input.formation_profile_ref, ContractorFormationProfileView)
    authority = read(action_input.authority_ref, Authorization)
    capacity = read(action_input.capacity_ref, ContractorBidCapacityView)
    funding = read(action_input.funding_ref, ContractorFormationFundingView)
    if (offer.contractor_id != organization_id or offer.client_id == organization_id
            or terms.contractor_id != organization_id or terms.client_id != offer.client_id
            or terms.offer_ref.key() != offer.ref.key() or offer.terms_ref.key() != terms.ref.key()
            or terms.bid_ref.key() != offer.bid_ref.key()
            or terms.package_ref.key() != offer.package_ref.key() or terms.round_ref.key() != offer.round_ref.key()
            or profile.organization_id != organization_id or profile.offer_ref.key() != offer.ref.key()
            or profile.terms_ref.key() != terms.ref.key() or profile.authority_ref.key() != authority.ref.key()
            or capacity.organization_id != organization_id or funding.organization_id != organization_id):
        raise TaskConflict('Contract formation changes original contractor, offer, final terms, profile or snapshots')
    unique_refs(action_input.counterpart_acceptance_refs)
    for ref in action_input.counterpart_acceptance_refs:
        acceptance = read(ref, ContractorFormationAcceptanceView)
        if (acceptance.run_id != context.run_id or acceptance.party_id == organization_id
                or acceptance.party_id not in terms.required_party_ids):
            raise TaskConflict('Counterpart acceptance changes the original run or independent legal party')
        # Preserve old agreement versions, withdrawn/rejected decisions and
        # digest conflicts for original processor checks; no consent is inferred.
    bid = sources.get(offer.bid_ref.key())
    if bid is not None:
        if (not isinstance(bid, ContractorAmendmentBidView) or bid.organization_id != organization_id
                or bid.draft.package_ref.key() != offer.package_ref.key() or bid.round_ref.key() != offer.round_ref.key()):
            raise TaskConflict('Contract formation substitutes the original selected bid version')
        execution = sources.get(bid.submission_ref.key())
        if execution is not None and (not isinstance(execution, ContractorAmendmentSubmissionView)
                or execution.organization_id != organization_id or execution.bid_ref.key() != bid.ref.key()
                or execution.package_ref.key() != offer.package_ref.key() or execution.round_ref.key() != offer.round_ref.key()):
            raise TaskConflict('Contract formation changes the original submission command identity')
    for resource in capacity.resources:
        original = sources.get(resource.resource_ref.key())
        if original is not None and (not isinstance(original, ContractorBidResourceView)
                or original.organization_id != organization_id or original.total != resource.total
                or original.region_id != resource.region_id or original.resource_kind != resource.resource_kind
                or original.effective_window != resource.effective_window):
            raise TaskConflict('Contract formation changes the original physical resource snapshot')
    for use in capacity.commitments:
        original = sources.get(use.commitment_ref.key())
        if original is not None and (not isinstance(original, ContractorBidCommitmentView)
                or original.organization_id != organization_id or original.resource_ref.key() != use.resource_ref.key()
                or original.quantity != use.quantity or original.window != use.window):
            raise TaskConflict('Contract formation changes original cross-project resource occupancy')
    for refs, schema in ((funding.source_refs, ContractorFormationCashSourceView),
            ([*funding.existing_payment_refs, *funding.inflow_refs], ContractorFormationCashPaymentView)):
        for ref in refs:
            source = sources.get(ref.key())
            if source is not None and (not isinstance(source, schema) or source.organization_id != organization_id):
                raise TaskConflict('Contract formation changes original cross-project funding ownership')
    cash_flow_refs = [*funding.existing_payment_refs, *funding.inflow_refs]
    if profile.cash_plan_ref is not None:
        plan = sources.get(profile.cash_plan_ref.key())
        if plan is not None:
            if (not isinstance(plan, ContractorFormationCashPlanView) or plan.organization_id != organization_id
                    or plan.offer_ref.key() != offer.ref.key() or plan.terms_ref.key() != terms.ref.key()):
                raise TaskConflict('Contract formation changes the original agreement funding plan')
            cash_flow_refs.extend([*plan.proposed_outflow_refs, *plan.proposed_inflow_refs])
            for ref in [*plan.proposed_outflow_refs, *plan.proposed_inflow_refs]:
                flow = sources.get(ref.key())
                if flow is not None and (not isinstance(flow, ContractorFormationCashPaymentView)
                        or flow.organization_id != organization_id or flow.offer_ref is None or flow.terms_ref is None
                        or flow.offer_ref.key() != offer.ref.key() or flow.terms_ref.key() != terms.ref.key()):
                    raise TaskConflict('Contract formation substitutes another proposed agreement cash flow')
    unique_refs(cash_flow_refs)
    component_refs = []
    for ref in cash_flow_refs:
        flow = sources.get(ref.key())
        if flow is not None:
            if not isinstance(flow, ContractorFormationCashPaymentView):
                raise TaskConflict('Contract formation lacks the original supplied cash flow schema')
            component_refs.extend(flow.component_refs)
    # One liability/receipt remains one physical component when its version changes.
    # Missing optional projections retain the processor's original read handling.
    unique_refs(component_refs)
    for ref in terms.payment_refs:
        payment = sources.get(ref.key())
        if payment is not None and (not isinstance(payment, ContractorFormationContractPaymentView)
                or payment.offer_ref.key() != offer.ref.key() or payment.terms_ref.key() != terms.ref.key()
                or payment.payer_id != offer.client_id or payment.payee_id != offer.contractor_id):
            raise TaskConflict('Contract formation changes the original contractual payment parties or terms')
    for ref in [terms.contract_template_ref, *terms.clause_refs, *terms.amendment_refs,
            *profile.requirement_changes, *profile.reviewed_clause_refs]:
        source = sources.get(ref.key())
        if source is not None and (not isinstance(source, ContractorFormationReferenceView)
                or source.offer_ref.key() != offer.ref.key() or source.terms_ref.key() != terms.ref.key()
                or source.bid_ref.key() != offer.bid_ref.key()):
            raise TaskConflict('Contract formation changes the original template, clause or revision request')
