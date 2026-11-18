"""Finite preliminary advice, actual study records and version-bound sources."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Measured, Money, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import ContractorBidMethodView, contractor_bid_schemas
from src.actions.contracts.qs_cost_objects import CostSource
from src.methods.contractor_advice import ContractorDurationActivity


class ContractorAdviceDimension(StrictRecord):
    code: TextId
    value: ValueState[Measured]


class ContractorAdviceBriefView(CostSource):
    ref: ref_type('OwnerBrief')
    purpose: TextId
    region_id: TextId
    object_type: TextId
    special_condition_codes: list[TextId]
    dimensions: list[ContractorAdviceDimension]
    desired_delivery_at: ValueState[TimePoint]
    allowed_uses: list[Literal['preliminary_advice']]


class ContractorAdviceOptionView(ContractorAdviceBriefView):
    ref: ref_type('ProjectOption')
    brief_ref: ref_type('OwnerBrief')
    source_refs: list[Reference]


class ContractorAdviceProfileView(CostSource):
    ref: ref_type('ContractorAdviceProfile')
    organization_id: TextId
    request_ref: ref_type('AdvisoryRequest')
    authority_ref: ref_type('Authorization')
    choice: Literal['provide_advice', 'propose_paid_study', 'decline']
    case_refs: list[ref_type('ConstructabilityAssessment')]
    proposal_ref: ref_type('ServiceProposal') | None
    note: TextId


class ContractorAdviceRequestView(CostSource):
    ref: ref_type('AdvisoryRequest')
    brief_ref: ref_type('OwnerBrief')
    option_refs: list[ref_type('ProjectOption')]
    recipient_organization_ids: list[TextId]
    allowed_supplier_evidence_refs: list[ref_type('SupplyAdvice')]
    profile_ref: ref_type('ContractorAdviceProfile')
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId


class ContractorAdviceCapabilityView(CostSource):
    ref: ref_type('ContractorCapability')
    organization_id: TextId
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    region_ids: list[TextId]
    object_types: list[TextId]
    special_condition_codes: list[TextId]
    method_refs: list[ref_type('ConstructabilityMethod')]


class ContractorAdviceAuthorityView(CostSource):
    ref: ref_type('AdvisoryAuthorization')
    request_ref: ref_type('AdvisoryRequest')
    organization_id: TextId
    delegate_actor_id: TextId
    delegate_function_ref: ref_type('FunctionAssignment')
    issuer_organization_id: TextId
    issuer_actor_id: TextId
    issuer_function_ref: ref_type('FunctionAssignment')
    issuer_authority_ref: ref_type('Authorization')
    issuer_action_id: TextId
    mode: Literal['paid', 'explicit_free']
    allowed_input_refs: list[Reference]
    task_ref: ref_type('Task')
    max_effort: ValueState[Measured]
    max_internal_cost: ValueState[Money]
    fee_obligation_ref: ref_type('Obligation') | None
    allowed_recipient_ids: list[TextId]


class ContractorAdviceTaskView(CostSource):
    ref: ref_type('Task')
    organization_id: TextId
    authority_ref: ref_type('AdvisoryAuthorization')
    request_ref: ref_type('AdvisoryRequest')
    input_refs: list[Reference]
    status: Literal['completed', 'pending', 'failed']
    execution_refs: Annotated[list[ref_type('WorkExecution')], Field(min_length=1)]
    execution_coverage: Literal['complete', 'partial', 'unknown']


class ContractorAdviceExecutionView(CostSource):
    ref: ref_type('WorkExecution')
    task_ref: ref_type('Task')
    authority_ref: ref_type('AdvisoryAuthorization')
    organization_id: TextId
    status: Literal['completed', 'pending', 'failed']
    effort: ValueState[Measured]
    internal_cost: ValueState[Money]
    execution_window: TimeWindow
    purpose: Literal['bounded_preliminary_advice']


class ContractorAdviceFeeView(CostSource):
    ref: ref_type('Obligation')
    authority_ref: ref_type('AdvisoryAuthorization')
    creditor_id: TextId
    debtor_id: TextId
    agreed_fee: ValueState[Money]
    status: Literal['effective', 'withdrawn']


class ContractorAdviceMethodView(CostSource):
    ref: ref_type('ConstructabilityMethod')
    region_ids: list[TextId]
    object_types: list[TextId]
    special_condition_codes: list[TextId]
    required_dimension_codes: list[TextId]
    allowed_duration_method_refs: list[ref_type('DurationEstimationMethod')]
    allowed_work_method_refs: list[ref_type('WorkMethod')]
    purpose: Literal['bounded_preliminary_advice']


class ContractorAdviceDurationMethodView(CostSource):
    ref: ref_type('DurationEstimationMethod')
    local_method_ref: ref_type('Method')
    unit: TextId
    independent_resources_assumption_ref: ref_type('Assumption')


class ContractorAdviceIssue(StrictRecord):
    scope_ref: ScopeRef
    requirement_ref: ref_type('Requirement')
    evidence_refs: list[ref_type('Evidence')]
    disposition: Literal['investigate', 'clarify', 'isolate', 'rectify', 'dispute']
    responsible: ValueState[TextId]


class ContractorAdviceIssueView(CostSource):
    ref: ref_type('InterfaceIssue')
    request_ref: ref_type('AdvisoryRequest')
    basis_ref: ref_type('OwnerBrief') | ref_type('ProjectOption')
    code: Literal['site_receiving', 'other_interface', 'unassessed_scope']
    issue: ContractorAdviceIssue


class ContractorAdviceSupplierView(CostSource):
    ref: ref_type('SupplyAdvice')
    basis_ref: ref_type('OwnerBrief') | ref_type('ProjectOption')
    source_kind: Literal['supplier_advice', 'contractor_estimate']
    manufacturing_ready: ValueState[bool]
    site_receiving_ready: ValueState[bool]
    assumption_refs: Annotated[list[ref_type('Assumption')], Field(min_length=1)]
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')


class ContractorAdviceCaseView(CostSource):
    ref: ref_type('ConstructabilityAssessment')
    organization_id: TextId
    task_ref: ref_type('Task')
    request_ref: ref_type('AdvisoryRequest')
    basis_ref: ref_type('OwnerBrief') | ref_type('ProjectOption')
    constructability_method_ref: ref_type('ConstructabilityMethod')
    duration_method_ref: ref_type('DurationEstimationMethod')
    input_dimensions: list[ContractorAdviceDimension]
    work_method_refs: list[ref_type('WorkMethod')]
    supplier_evidence_refs: list[ref_type('SupplyAdvice')]
    activities: list[ContractorDurationActivity]
    issue_refs: list[ref_type('InterfaceIssue')]
    assumption_refs: list[ref_type('Assumption')]
    permitted_use_ref: ref_type('PermittedUse')
    validity_condition_refs: list[ref_type('Requirement')]
    result_basis_ref: ref_type('Evidence')
    status: Literal['ok', 'failed', 'unsupported']


class ContractorAdviceReferenceView(CostSource):
    ref: Reference
    request_ref: ref_type('AdvisoryRequest')
    basis_refs: list[ref_type('OwnerBrief') | ref_type('ProjectOption')]
    allowed: ValueState[bool]
    allowed_uses: list[Literal['preliminary_advice']]
    recipient_ids: list[TextId]


class ContractorAdviceProposalView(CostSource):
    ref: ref_type('ServiceProposal')
    request_ref: ref_type('AdvisoryRequest')
    organization_id: TextId
    effort: ValueState[Measured]
    proposed_fee: ValueState[Money]
    condition_refs: Annotated[list[ref_type('Requirement')], Field(min_length=1)]
    estimate_basis_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]


def contractor_advice_schemas():
    return contractor_bid_schemas({
        'OwnerBrief': ContractorAdviceBriefView, 'ProjectOption': ContractorAdviceOptionView,
        'AdvisoryRequest': ContractorAdviceRequestView, 'AdvisoryAuthorization': ContractorAdviceAuthorityView,
        'ContractorCapability': ContractorAdviceCapabilityView, 'ContractorAdviceProfile': ContractorAdviceProfileView,
        'Task': ContractorAdviceTaskView, 'WorkExecution': ContractorAdviceExecutionView, 'Obligation': ContractorAdviceFeeView,
        'ConstructabilityMethod': ContractorAdviceMethodView, 'DurationEstimationMethod': ContractorAdviceDurationMethodView,
        'ConstructabilityAssessment': ContractorAdviceCaseView, 'InterfaceIssue': ContractorAdviceIssueView,
        'SupplyAdvice': ContractorAdviceSupplierView, 'ServiceProposal': ContractorAdviceProposalView,
        'WorkMethod': ContractorBidMethodView,
        **{kind: ContractorAdviceReferenceView for kind in ('Assumption', 'PermittedUse', 'Requirement')},
    })
