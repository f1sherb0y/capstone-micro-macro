"""Limited original supply opinions, finite work authority and disclosure controls."""
from typing import Literal

from src.actions.contracts.common import Measured, Money, Reference, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.contractor_advice_objects import (
    ContractorAdviceBriefView, ContractorAdviceOptionView, ContractorAdviceDimension,
    ContractorAdviceAuthorityView, ContractorAdviceTaskView, ContractorAdviceExecutionView,
    ContractorAdviceFeeView, ContractorAdviceProposalView,
)
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.supplier_product_objects import ProductSpecificationView, ProductEvidenceView
from src.methods.supplier_advice import SupplierAdviceEstimateInput


class SupplierAdviceRequestView(CostSource):
    ref: ref_type('AdvisoryRequest')
    brief_ref: ref_type('OwnerBrief')
    option_refs: list[ref_type('ProjectOption')]
    requirement_refs: list[ref_type('Requirement')]
    allowed_professional_advice_refs: list[ref_type('ProfessionalAdvice')]
    production_window_ref: ref_type('TimeWindow')
    recipient_organization_id: TextId
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId


class SupplierAdviceDisclosureView(CostSource):
    ref: ref_type('DisclosureProfile')
    organization_id: TextId
    request_ref: ref_type('AdvisoryRequest')
    authority_ref: ref_type('Authorization')
    choice: Literal['indicative_advice', 'limited_disclosure', 'propose_study', 'decline']
    case_refs: list[ref_type('SupplyAdvice')]
    withheld_requirement_refs: list[ref_type('Requirement')]
    unresolved_refs: list[ref_type('Issue')]
    allowed_source_refs: list[Reference]
    disclosable_evidence_refs: list[ref_type('Evidence')]
    allowed_recipient_ids: list[TextId]
    proposal_ref: ref_type('ServiceProposal') | None
    note: TextId


class SupplierAdviceCapabilityView(CostSource):
    ref: ref_type('SupplierCapability')
    organization_id: TextId
    as_of: TimePoint
    region_ids: list[TextId]
    object_types: list[TextId]
    special_condition_codes: list[TextId]
    product_refs: list[ref_type('ProductSpecification')]
    method_refs: list[ref_type('SupplyFeasibilityMethod')]
    coverage: Literal['complete', 'partial', 'unknown']
    disclosure_commitment_coverage: Literal['complete', 'partial', 'unknown']
    commitment_refs: list[ref_type('SupplyCommitment')]


class SupplierAdviceCommitmentView(CostSource):
    ref: ref_type('SupplyCommitment')
    organization_id: TextId
    required_disclosure_refs: list[ref_type('Requirement')]
    status: Literal['effective', 'released']
    disposition_basis_ref: ref_type('Evidence')


class SupplierAdviceProfessionalView(CostSource):
    ref: ref_type('ProfessionalAdvice')
    basis_ref: ref_type('OwnerBrief') | ref_type('ProjectOption')
    allowed_uses: list[Literal['preliminary_advice']]
    issue_refs: list[ref_type('Issue')]
    status: Literal['ok', 'failed', 'unsupported']
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId


class SupplierAdviceMethodView(CostSource):
    ref: ref_type('SupplyFeasibilityMethod')
    local_method_ref: ref_type('Method')
    region_ids: list[TextId]
    object_types: list[TextId]
    special_condition_codes: list[TextId]
    quantity_method_ref: ref_type('QuantityEstimationMethod')
    price_method_ref: ref_type('PriceEstimationMethod')
    delivery_price_method_ref: ref_type('PriceEstimationMethod')


class SupplierAdviceReferenceView(CostSource):
    ref: Reference
    request_ref: ref_type('AdvisoryRequest')
    basis_refs: list[ref_type('OwnerBrief') | ref_type('ProjectOption')]
    allowed: ValueState[bool]
    allowed_uses: list[Literal['preliminary_advice']]
    recipient_ids: list[TextId]
    condition_refs: list[ref_type('Requirement')]
    assumption_refs: list[ref_type('Assumption')]
    commercial_stance: Literal['supplier_product_interest']
    purpose: Literal['method', 'limitation', 'use', 'condition', 'requirement', 'route']
    withheld_field_codes: list[Literal['quantity', 'indicative_price', 'manufacturing_duration', 'logistics']]


class SupplierAdviceIssueView(CostSource):
    ref: ref_type('Issue')
    request_ref: ref_type('AdvisoryRequest')
    basis_ref: ref_type('OwnerBrief') | ref_type('ProjectOption')
    code: Literal['unknown_information', 'product_unverified', 'logistics', 'site_receiving', 'installation', 'unsupported', 'professional_interface']
    evidence_refs_to_disclose: list[ref_type('Evidence')]


class SupplierAdviceCaseView(CostSource):
    ref: ref_type('SupplyAdvice')
    organization_id: TextId
    task_ref: ref_type('Task')
    request_ref: ref_type('AdvisoryRequest')
    basis_ref: ref_type('OwnerBrief') | ref_type('ProjectOption')
    input_dimensions: list[ContractorAdviceDimension]
    production_window_ref: ref_type('TimeWindow')
    product_refs: list[ref_type('ProductSpecification')]
    professional_advice_refs: list[ref_type('ProfessionalAdvice')]
    feasibility_method_ref: ref_type('SupplyFeasibilityMethod')
    estimate: SupplierAdviceEstimateInput
    route_refs: list[ref_type('TransportRoute')]
    logistics_duration: ValueState[Measured]
    delivery_price_lower: ValueState[Money]
    delivery_price_upper: ValueState[Money]
    logistics_condition_refs: list[ref_type('Requirement')]
    logistics_unresolved_refs: list[ref_type('Issue')]
    interface_issue_refs: list[ref_type('Issue')]
    evidence_refs_to_disclose: list[ref_type('Evidence')]
    permitted_use_ref: ref_type('PermittedUse')
    status: Literal['ok', 'failed', 'unsupported']


def supplier_advice_schemas():
    return contractor_bid_schemas({
        'OwnerBrief': ContractorAdviceBriefView, 'ProjectOption': ContractorAdviceOptionView,
        'AdvisoryRequest': SupplierAdviceRequestView, 'DisclosureProfile': SupplierAdviceDisclosureView,
        'SupplierCapability': SupplierAdviceCapabilityView, 'SupplyCommitment': SupplierAdviceCommitmentView,
        'ProfessionalAdvice': SupplierAdviceProfessionalView, 'SupplyAdvice': SupplierAdviceCaseView,
        'SupplyFeasibilityMethod': SupplierAdviceMethodView, 'Issue': SupplierAdviceIssueView,
        'ProductSpecification': ProductSpecificationView, 'ProductEvidence': ProductEvidenceView,
        'AdvisoryAuthorization': ContractorAdviceAuthorityView, 'Task': ContractorAdviceTaskView,
        'WorkExecution': ContractorAdviceExecutionView, 'Obligation': ContractorAdviceFeeView,
        'ServiceProposal': ContractorAdviceProposalView,
        **{kind: SupplierAdviceReferenceView for kind in ('QuantityEstimationMethod', 'PriceEstimationMethod',
            'Requirement', 'PermittedUse', 'Assumption', 'TransportRoute', 'Rule', 'Capability')},
    })
