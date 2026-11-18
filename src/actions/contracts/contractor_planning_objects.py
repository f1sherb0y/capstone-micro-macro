"""Original work mandates, sourced plans and same-offer supply commitments."""
from typing import Literal

from src.actions.contracts.common import Measured, Money, ScopeRef, StrictRecord, TextId, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import (
    ContractorBidTask, ContractorBidCapacityView, ContractorBidResourceView, ContractorBidCommitmentView,
    ContractorBidMethodView, contractor_bid_schemas,
)
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.government_review_objects import GovReviewAuthored


class ContractorWorkMandateView(CostSource):
    ref: ref_type('Contract') | ref_type('WorkAuthorization')
    organization_id: TextId
    mandate_kind: Literal['contract', 'preparation']
    effective: ValueState[bool]
    planning_profile_ref: ref_type('WorkPlanningProfile')
    allowed_task_purposes: list[Literal['preparation', 'construction']]
    allow_quote: ValueState[bool]
    allow_supply_acceptance: ValueState[bool]
    procurement_limit: ValueState[Money]
    procurement_used: ValueState[Money]
    procurement_history_refs: list[ref_type('SupplyCommitment')]
    procurement_history_complete: bool
    region_id: TextId
    object_type: TextId
    work_type: TextId
    special_condition_codes: list[TextId]
    required_qualification_codes: list[TextId]
    dependency_refs: list[ref_type('Dependency')]
    design_refs: list[ref_type('ReleasedDeliverable')]
    method_refs: list[ref_type('WorkMethod')]


class ContractorWorkPlanView(GovReviewAuthored):
    ref: ref_type('WorkPlan')
    mandate_ref: ref_type('Contract') | ref_type('WorkAuthorization')
    purpose: Literal['preparation', 'construction']
    design_refs: list[ref_type('ReleasedDeliverable')]
    tasks: list[ContractorBidTask]
    status: Literal['proposed', 'effective', 'superseded']
    commitment_refs: list[ref_type('ResourceCommitment')]


class ContractorPlanningProfileView(CostSource):
    ref: ref_type('WorkPlanningProfile')
    mandate_ref: ref_type('Contract') | ref_type('WorkAuthorization')
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    choice: Literal['plan', 'revise_plan', 'request_quote', 'accept_supply_offer']
    plan_ref: ref_type('WorkPlan') | None
    prior_plan_ref: ref_type('WorkPlan') | None
    requirement_refs: list[ref_type('SupplyRequirement')]
    supplier_refs: list[ref_type('SupplySupplier')]
    selected_offer_ref: ref_type('SupplyOffer') | None
    receiving_window_ref: ref_type('TimeWindow') | None
    procurement_authority_ref: ref_type('ProcurementAuthority') | None
    note: TextId
    monthly_supplier_policy_ref: ref_type('SupplierRelationshipReviewPolicy') | None = None
    monthly_supplier_observation_ref: ref_type('SupplierRelationshipReviewObservation') | None = None
    negative_selection_observation_ref: ref_type('NativeSupplySelectionObservation') | None = None


class ContractorPlanDependencyView(CostSource):
    ref: ref_type('Dependency')
    mandate_ref: ref_type('Contract') | ref_type('WorkAuthorization')
    responsible_organization_id: TextId
    dependent_task_key: TextId
    predecessor_task_keys: list[TextId]
    satisfied: ValueState[bool]
    planning_permitted: ValueState[bool]


class ContractorPlanDesignView(GovReviewAuthored):
    ref: ref_type('ReleasedDeliverable')
    mandate_ref: ref_type('Contract') | ref_type('WorkAuthorization')
    content_sha256: TextId
    allowed_uses: list[Literal['preparation', 'construction']]
    status: Literal['released', 'draft', 'withdrawn']


class ContractorSupplyRequirementView(CostSource):
    ref: ref_type('SupplyRequirement')
    mandate_ref: ref_type('Contract') | ref_type('WorkAuthorization')
    product_ref: ref_type('ProductSpecification')
    quantity: Measured
    delivery_window_ref: ref_type('TimeWindow')
    receiving_window_ref: ref_type('TimeWindow')
    destination_ref: ref_type('Location')
    inspection_rule_ref: ref_type('InspectionRule')
    payment_rule_ref: ref_type('PaymentRule')
    allowed_supplier_ids: list[TextId]
    substitution_authority_ref: ref_type('SubstitutionAuthority') | None


class ContractorSupplyLine(StrictRecord):
    local_key: TextId
    requirement_ref: ref_type('SupplyRequirement')
    product_ref: ref_type('ProductSpecification')
    quantity: Measured
    batch_price: Money


class ContractorSupplyOfferView(GovReviewAuthored):
    ref: ref_type('SupplyOffer')
    supplier_id: TextId
    buyer_id: TextId
    payer_id: TextId
    terms_ref: ref_type('SupplyTerms')
    requirement_refs: list[ref_type('SupplyRequirement')]
    lines: list[ContractorSupplyLine]
    status: Literal['active', 'withdrawn', 'superseded']


class ContractorSupplyTermsView(CostSource):
    ref: ref_type('SupplyTerms')
    offer_ref: ref_type('SupplyOffer')
    supplier_id: TextId
    buyer_id: TextId
    payer_id: TextId
    requirement_refs: list[ref_type('SupplyRequirement')]
    lines: list[ContractorSupplyLine]
    receiving_window_ref: ref_type('TimeWindow')
    delivery_window_ref: ref_type('TimeWindow')
    destination_ref: ref_type('Location')
    inspection_rule_ref: ref_type('InspectionRule')
    payment_rule_ref: ref_type('PaymentRule')
    gross_price: Money
    binding_ref: ref_type('SupplyBinding')


class ContractorProcurementAuthorityView(CostSource):
    ref: ref_type('ProcurementAuthority')
    mandate_ref: ref_type('Contract') | ref_type('WorkAuthorization')
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    organization_id: TextId
    permitted: ValueState[bool]
    offer_ref: ref_type('SupplyOffer')
    terms_ref: ref_type('SupplyTerms')
    terms_sha256: TextId


class ContractorSupplyReferenceView(CostSource):
    ref: ref_type('ProductSpecification') | ref_type('Location') | ref_type('InspectionRule') | ref_type('PaymentRule') | ref_type('SubstitutionAuthority') | ref_type('SupplyBinding')
    requirement_refs: list[ref_type('SupplyRequirement')]
    offer_ref: ref_type('SupplyOffer') | None
    terms_ref: ref_type('SupplyTerms') | None
    permitted: ValueState[bool]


class ContractorSupplySupplierView(CostSource):
    ref: ref_type('SupplySupplier')
    organization_id: TextId
    accepts_inquiries: ValueState[bool]
    requirement_refs: list[ref_type('SupplyRequirement')]


class ContractorSupplyCommitmentView(CostSource):
    ref: ref_type('SupplyCommitment')
    mandate_ref: ref_type('Contract') | ref_type('WorkAuthorization')
    offer_ref: ref_type('SupplyOffer')
    terms_ref: ref_type('SupplyTerms')
    business_key: TextId
    amount: Money
    status: Literal['committed', 'paid', 'released']


def contractor_planning_schemas():
    from src.actions.contracts.contractor_negative_selection import NativeSupplySelectionObservation
    from src.actions.contracts.contractor_supplier_review import SupplierRelationshipReviewPolicy, SupplierRelationshipReviewObservation
    return contractor_bid_schemas({
        'NativeSupplySelectionObservation': NativeSupplySelectionObservation,
        'SupplierRelationshipReviewPolicy': SupplierRelationshipReviewPolicy,
        'SupplierRelationshipReviewObservation': SupplierRelationshipReviewObservation,
        'Contract': ContractorWorkMandateView, 'WorkAuthorization': ContractorWorkMandateView,
        'WorkPlanningProfile': ContractorPlanningProfileView, 'WorkPlan': ContractorWorkPlanView,
        'Dependency': ContractorPlanDependencyView, 'ReleasedDeliverable': ContractorPlanDesignView,
        'SupplyRequirement': ContractorSupplyRequirementView, 'SupplyOffer': ContractorSupplyOfferView,
        'SupplyTerms': ContractorSupplyTermsView, 'SupplySupplier': ContractorSupplySupplierView,
        'ProcurementAuthority': ContractorProcurementAuthorityView, 'SupplyCommitment': ContractorSupplyCommitmentView,
        **{kind: ContractorSupplyReferenceView for kind in ('ProductSpecification', 'Location', 'InspectionRule',
            'PaymentRule', 'SubstitutionAuthority', 'SupplyBinding')},
    })
