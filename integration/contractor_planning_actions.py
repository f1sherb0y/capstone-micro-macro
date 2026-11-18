"""Assemble original Contractor A05 plans and procurement inputs."""
from dataclasses import dataclass
from typing import ClassVar

from integration.contractor_amendment_actions import ContractorAmendmentActionAssembler, PreparedContractorAmendment
from src.actions.contracts.contractor_bid_objects import ContractorBidCapacityView, ContractorBidCommitmentView, ContractorBidResourceView
from src.actions.contracts.contractor_planning_objects import (
    ContractorPlanDependencyView, ContractorPlanDesignView, ContractorPlanningProfileView,
    ContractorProcurementAuthorityView, ContractorSupplyCommitmentView,
    ContractorSupplyOfferView, ContractorSupplyRequirementView, ContractorSupplyTermsView,
    ContractorWorkMandateView, ContractorWorkPlanView, contractor_planning_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedContractorPlanning(PreparedContractorAmendment):
    ACTION_ID: ClassVar[str] = 'CONTRACTOR-A05'


class ContractorPlanningActionAssembler(ContractorAmendmentActionAssembler):
    """Freeze original mandate, scope, capacity and explicit supply selections.

    The application holds its current source/authorization guard. Preparation
    authorization remains distinct from a construction contract. Original
    processor checks permission, dependencies, design use, capacity, receiving
    windows, independent supplier authority and procurement limits. Assembly
    creates no work plan, reservation, order, supplier acceptance or inventory.
    """
    ACTION_ID = 'CONTRACTOR-A05'
    SOURCE_SCHEMAS = staticmethod(contractor_planning_schemas)

    def build(self, context, *, work_basis, authorized_scope_ref, dependency_refs,
            design_refs, capacity_ref, supplier_offer_refs, work_method_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'work_basis': work_basis, 'authorized_scope_ref': authorized_scope_ref,
            'dependency_refs': dependency_refs, 'design_refs': design_refs,
            'capacity_ref': capacity_ref, 'supplier_offer_refs': supplier_offer_refs,
            'work_method_refs': work_method_refs}, prepared_type=PreparedContractorPlanning,
            validate_sources=validate_contractor_planning_sources)


def validate_contractor_planning_sources(action_input, *, context, organization_id, sources):
    """Check supplied identities without inferring mandate or supplier permissions."""
    def read(ref, schema):
        source = sources.get(ref.key())
        if not isinstance(source, schema) or source.ref.key() != ref.key():
            raise TaskConflict('Work planning lacks its exact original concrete source')
        return source

    def authored(row):
        points = (row.authored_at, row.available_at, row.effective_window.start, row.effective_window.end)
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or row.authored_at.offset > row.available_at.offset
                or row.available_at.offset > context.business_time.offset
                or not row.effective_window.contains(row.authored_at)):
            raise TaskConflict('Work planning source changes its original signing time or availability')

    def original_inputs(row, refs):
        for ref in refs:
            source = sources.get(ref.key())
            if source is not None and hasattr(source, 'available_at') and (
                    source.available_at.clock_ref != row.authored_at.clock_ref
                    or source.available_at.offset > row.authored_at.offset):
                raise TaskConflict('Work planning source predates an originally referenced input')

    for refs in (action_input.dependency_refs, action_input.design_refs,
            action_input.supplier_offer_refs, action_input.work_method_refs):
        unique_refs(refs)
    basis = action_input.work_basis
    mandate_ref = basis.contract_ref if basis.kind == 'contract' else basis.authorization_ref
    mandate = read(mandate_ref, ContractorWorkMandateView)
    capacity = read(action_input.capacity_ref, ContractorBidCapacityView)
    if (mandate.mandate_kind != basis.kind or mandate.organization_id != organization_id
            or capacity.organization_id != organization_id
            or not scope_covers(context.scope, action_input.authorized_scope_ref)
            or not scope_covers(mandate.scope, action_input.authorized_scope_ref)):
        raise TaskConflict('Work planning changes original contractor, contract/preparation mandate or authorized scope')
    for refs, schema in ((action_input.dependency_refs, ContractorPlanDependencyView),
            (action_input.design_refs, ContractorPlanDesignView)):
        for ref in refs:
            source = read(ref, schema)
            if source.mandate_ref.key() != mandate.ref.key():
                raise TaskConflict('Work planning changes the original dependency or design mandate')
            if isinstance(source, ContractorPlanDesignView):
                authored(source)
    offers = {}
    for ref in action_input.supplier_offer_refs:
        offer = read(ref, ContractorSupplyOfferView)
        authored(offer)
        original_inputs(offer, [offer.terms_ref, *offer.requirement_refs])
        if offer.buyer_id != organization_id or offer.payer_id != organization_id:
            raise TaskConflict('Work planning supply offer changes original buyer or payer')
        offers[ref.key()] = offer
        terms = sources.get(offer.terms_ref.key())
        if terms is not None and (not isinstance(terms, ContractorSupplyTermsView)
                or terms.ref != offer.terms_ref
                or terms.offer_ref.key() != offer.ref.key() or terms.supplier_id != offer.supplier_id
                or terms.buyer_id != offer.buyer_id or terms.payer_id != offer.payer_id):
            raise TaskConflict('Work planning mixes original supplier, offer or terms parties')
        if terms is not None and (terms.effective_window.start.clock_ref != offer.authored_at.clock_ref
                or terms.effective_window.end.clock_ref != offer.authored_at.clock_ref
                or not terms.effective_window.contains(offer.authored_at)):
            raise TaskConflict('Work planning changes the original signed offer terms window')
    # Original statuses, coverage and missing output dependencies remain visible
    # to processor branches; supplied dependencies must keep their identities.
    profile = sources.get(mandate.planning_profile_ref.key())
    if profile is not None:
        if (not isinstance(profile, ContractorPlanningProfileView)
                or profile.mandate_ref.key() != mandate.ref.key() or profile.organization_id != organization_id):
            raise TaskConflict('Work planning changes the original contractor planning profile')
        for ref in (profile.plan_ref, profile.prior_plan_ref):
            if ref is None:
                continue
            plan = sources.get(ref.key())
            if plan is not None and (not isinstance(plan, ContractorWorkPlanView)
                    or plan.ref != ref
                    or plan.mandate_ref.key() != mandate.ref.key()
                    or plan.author_organization_id != organization_id):
                raise TaskConflict('Work planning changes the original plan mandate or author organization')
            if plan is not None:
                authored(plan)
                if ref == profile.plan_ref:
                    original_inputs(plan, [mandate.ref, *plan.design_refs, *action_input.dependency_refs])
                for task in plan.tasks:
                    if ref == profile.plan_ref and (not scope_covers(action_input.authorized_scope_ref, task.scope_ref)
                            or not scope_covers(plan.scope, task.scope_ref)):
                        raise TaskConflict('Work planning task changes its original signed plan or authorized scope')
        for ref in profile.requirement_refs:
            requirement = sources.get(ref.key())
            if requirement is not None and (not isinstance(requirement, ContractorSupplyRequirementView)
                    or requirement.mandate_ref.key() != mandate.ref.key()):
                raise TaskConflict('Work planning supply requirement changes the original mandate')
        if profile.procurement_authority_ref is not None:
            authority = sources.get(profile.procurement_authority_ref.key())
            if authority is not None and (not isinstance(authority, ContractorProcurementAuthorityView)
                    or authority.mandate_ref.key() != mandate.ref.key()
                    or authority.organization_id != organization_id
                    or not scope_covers(authority.scope, action_input.authorized_scope_ref)):
                raise TaskConflict('Work planning procurement authority changes original mandate or organization')
            selected = offers.get(profile.selected_offer_ref.key()) if profile.selected_offer_ref is not None else None
            if authority is not None and selected is not None and (
                    authority.offer_ref.key() != selected.ref.key()
                    or authority.terms_ref.key() != selected.terms_ref.key()):
                raise TaskConflict('Work planning procurement authority changes the selected offer/terms version')
    for ref in mandate.procurement_history_refs:
        commitment = sources.get(ref.key())
        if commitment is not None and (not isinstance(commitment, ContractorSupplyCommitmentView)
                or commitment.mandate_ref.key() != mandate.ref.key()):
            raise TaskConflict('Work planning changes the original mandate procurement history')
    for resource in capacity.resources:
        original = sources.get(resource.resource_ref.key())
        if original is not None and (not isinstance(original, ContractorBidResourceView)
                or original.organization_id != organization_id or original.total != resource.total
                or original.region_id != resource.region_id or original.resource_kind != resource.resource_kind
                or original.effective_window != resource.effective_window):
            raise TaskConflict('Work planning changes original physical resource or location')
    for use in capacity.commitments:
        original = sources.get(use.commitment_ref.key())
        if original is not None and (not isinstance(original, ContractorBidCommitmentView)
                or original.organization_id != organization_id or original.resource_ref.key() != use.resource_ref.key()
                or original.quantity != use.quantity or original.window != use.window):
            raise TaskConflict('Work planning changes original cross-project resource occupancy')
