"""Contract-bound notices, scoped change proposals and independently sourced impacts."""
from typing import Literal
from pydantic import Field

from src.actions.contracts.common import Money, ScopeRef, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.methods.qs_change import ChangeArithmeticInput, ChangeArithmeticReport
from src.methods.qs_change import ChangeLine


class ContractorClaimContractView(CostSource):
    ref: ref_type('Contract')
    contractor_id: TextId
    client_id: TextId
    currency: TextId
    decimal_places: int = Field(ge=0, le=8)
    design_refs: list[ref_type('Deliverable')]
    task_refs: list[ref_type('Task')]
    claim_refs: list[ref_type('Claim')]
    claim_history_complete: bool
    as_of: TimePoint
    effective: ValueState[bool]


class ContractorClaimProfileView(CostSource):
    ref: ref_type('ClaimProfile')
    contract_ref: ref_type('Contract')
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    choice: Literal['clarify', 'respond', 'propose_change', 'submit_claim', 'dispute']
    design_refs: list[ref_type('Deliverable')]
    instruction_refs: list[ref_type('ContractInstruction')]
    issue_refs: list[ref_type('InterfaceIssue')]
    actual_cost_refs: list[ref_type('CostRecord')]
    procedure_ref: ref_type('ClaimProcedure')
    change_ref: ref_type('ContractorChangeProposal') | None
    claim_ref: ref_type('Claim') | None
    amount_result_ref: ref_type('MethodResult') | None
    proposed_amount: ValueState[Money]
    time_impact: ValueState[ref_type('TimeImpactAssessment')]
    note: TextId


class ContractorClaimProcedureView(CostSource):
    ref: ref_type('ClaimProcedure')
    contract_ref: ref_type('Contract')
    permitted_choices: list[TextId]
    recipient_ids: list[TextId]
    permitted: ValueState[bool]
    deadline: TimePoint | None
    late_notice_permitted: ValueState[bool]
    existing_work_effect: Literal['preserve_existing_obligations']


class ContractorClaimDesignView(GovReviewAuthored):
    ref: ref_type('Deliverable')
    contract_ref: ref_type('Contract')
    content_sha256: Digest
    task_refs: list[ref_type('Task')]


class ContractorClaimTaskView(CostSource):
    ref: ref_type('Task')
    contract_ref: ref_type('Contract')
    organization_id: TextId
    design_refs: list[ref_type('Deliverable')]


class ContractorClaimInstructionView(GovReviewAuthored):
    ref: ref_type('ContractInstruction')
    contract_ref: ref_type('Contract')
    authority_ref: ref_type('InstructionAuthority')
    affected_task_refs: list[ref_type('Task')]
    design_refs: list[ref_type('Deliverable')]
    status: Literal['issued', 'withdrawn', 'proposal']


class ContractorInstructionAuthorityView(CostSource):
    ref: ref_type('InstructionAuthority')
    contract_ref: ref_type('Contract')
    actor_id: TextId
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    permitted: ValueState[bool]


class ContractorInterfaceIssueView(CostSource):
    ref: ref_type('InterfaceIssue')
    contract_ref: ref_type('Contract')
    requirement_ref: ref_type('Requirement')
    affected_task_refs: list[ref_type('Task')]
    design_refs: list[ref_type('Deliverable')]
    responsible: ValueState[TextId]
    disposition: Literal['investigate', 'clarify', 'isolate', 'rectify', 'dispute']


class ContractorClaimRequirementView(CostSource):
    ref: ref_type('Requirement')
    issue_ref: ref_type('InterfaceIssue')
    contract_ref: ref_type('Contract')


class ContractorChangeProposalView(GovReviewAuthored):
    ref: ref_type('ContractorChangeProposal')
    contract_ref: ref_type('Contract')
    design_refs: list[ref_type('Deliverable')]
    instruction_refs: list[ref_type('ContractInstruction')]
    issue_refs: list[ref_type('InterfaceIssue')]
    affected_task_refs: list[ref_type('Task')]
    unaffected_task_refs: list[ref_type('Task')]
    changed_scope: ScopeRef
    change_description: TextId
    business_key: TextId
    status: Literal['proposal', 'withdrawn']


class ContractorActualCostView(GovReviewAuthored):
    ref: ref_type('CostRecord')
    contract_ref: ref_type('Contract')
    task_ref: ref_type('Task')
    event_id: TextId
    cost_component_key: TextId
    amount: Money
    status: Literal['incurred', 'estimate', 'unknown']


class ContractorClaimAmountView(GovReviewAuthored):
    ref: ref_type('MethodResult')
    change_ref: ref_type('ContractorChangeProposal')
    method_ref: ref_type('Method')
    data: ChangeArithmeticInput
    input_sha256: Digest
    report: ChangeArithmeticReport | None
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    cost_record_refs: list[ref_type('CostRecord')]
    amount_kind: Literal['estimate', 'actual_cost_based']
    line_refs: list[ref_type('ClaimCostLine')]


class ContractorClaimCostLineView(GovReviewAuthored):
    ref: ref_type('ClaimCostLine')
    change_ref: ref_type('ContractorChangeProposal')
    task_ref: ref_type('Task')
    line: ChangeLine
    kind: Literal['estimate', 'actual_cost']
    cost_record_refs: list[ref_type('CostRecord')]


class ContractorClaimMethodView(CostSource):
    ref: ref_type('Method')
    supported: ValueState[bool]
    allowed_author_action_ids: list[TextId]


class ContractorTimeImpactView(GovReviewAuthored):
    ref: ref_type('TimeImpactAssessment')
    change_ref: ref_type('ContractorChangeProposal')
    affected_task_refs: list[ref_type('Task')]
    method_ref: ref_type('Method')
    supported: ValueState[bool]
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    source_refs: list[ref_type('ContractInstruction') | ref_type('InterfaceIssue') | ref_type('Task')]
    finding: Literal['estimated_impact']


class ContractorClaimView(GovReviewAuthored):
    ref: ref_type('Claim')
    contract_ref: ref_type('Contract')
    claimant_id: TextId
    change_ref: ref_type('ContractorChangeProposal')
    business_key: TextId
    status: Literal['submitted', 'pending', 'recognized', 'disputed', 'withdrawn']


def contractor_claim_schemas():
    return contractor_bid_schemas({
        'Contract': ContractorClaimContractView, 'ClaimProfile': ContractorClaimProfileView,
        'ClaimProcedure': ContractorClaimProcedureView, 'Deliverable': ContractorClaimDesignView,
        'Task': ContractorClaimTaskView, 'ContractInstruction': ContractorClaimInstructionView,
        'InstructionAuthority': ContractorInstructionAuthorityView, 'InterfaceIssue': ContractorInterfaceIssueView,
        'Requirement': ContractorClaimRequirementView, 'ContractorChangeProposal': ContractorChangeProposalView,
        'CostRecord': ContractorActualCostView, 'MethodResult': ContractorClaimAmountView,
        'TimeImpactAssessment': ContractorTimeImpactView, 'Claim': ContractorClaimView,
        'ClaimCostLine': ContractorClaimCostLineView, 'Method': ContractorClaimMethodView,
    })
