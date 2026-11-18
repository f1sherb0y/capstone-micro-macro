"""Original design obligations, bounded changes and separately decided fee rights."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Money, Measured, Reference, ScopeRef, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.architect_design_objects import ArchitectDesignVariable, ArchitectDesignVariableView, ArchitectDesignReferenceView
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.service_objects import service_intake_schemas
from src.methods.architect_change_impact import ArchitectChangeImpactArithmeticInput

Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class ArchitectChangeDeliverableView(CostSource):
    ref: ref_type('Deliverable')
    content_sha256: Digest
    design_profile_ref: ref_type('DesignProfile')
    variables: list[ArchitectDesignVariable]
    dependency_refs: list[ref_type('Dependency')]
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['ARCHITECT-A05', 'ARCHITECT-A06']
    authored_at: TimePoint


class ArchitectChangeIssueView(CostSource):
    ref: ref_type('Issue')
    used_deliverable_ref: ref_type('Deliverable')
    obligation_ref: ref_type('Obligation')
    change_profile_ref: ref_type('DesignChangeProfile')
    kind: Literal['clarification', 'requirement_change', 'defect_remedy', 'interface_conflict']
    status: Literal['open', 'unknown', 'closed']


class ArchitectChangeObligationView(CostSource):
    ref: ref_type('Obligation')
    organization_id: TextId
    deliverable_ref: ref_type('Deliverable')
    contract_ref: ref_type('Contract')
    status: Literal['effective', 'disputed', 'terminated']
    permitted_choices: list[Literal['explain', 'propose_change', 'request_authority']]
    instruction_required_for_change: bool
    defect_remedy_authorized: bool
    permitted_instruction_issuer_ids: list[TextId]
    permitted_instruction_action_ids: list[TextId]
    permitted_entitlement_resolver_ids: list[TextId]
    permitted_entitlement_action_ids: list[TextId]
    variable_refs: list[ref_type('DesignVariable')]
    permitted_impact_method_refs: list[ref_type('Method')]


class ArchitectChangeProfileView(CostSource):
    ref: ref_type('DesignChangeProfile')
    issue_ref: ref_type('Issue')
    obligation_ref: ref_type('Obligation')
    authority_ref: ref_type('Authorization')
    choice: Literal['explain', 'propose_change', 'request_authority']
    response: TextId
    response_basis_refs: list[ref_type('Evidence')]
    response_preserves_content: ValueState[bool]
    affected_scope: ScopeRef
    affected_dependency_refs: list[ref_type('Dependency')]
    proposed_variable_changes: list[ArchitectDesignVariable]
    question_refs: list[ref_type('EvidenceTarget')]
    impact_question_refs: list[ref_type('EvidenceTarget')]
    fee_entitlement_ref: ref_type('EntitlementDecision') | None
    note: TextId
    impact_basis_ref: ref_type('DesignChangeImpactBasis') | None = None


class ArchitectChangeInstructionView(CostSource):
    ref: ref_type('Instruction')
    issue_ref: ref_type('Issue')
    obligation_ref: ref_type('Obligation')
    used_deliverable_ref: ref_type('Deliverable')
    contract_ref: ref_type('Contract')
    authorized_variable_refs: list[ref_type('DesignVariable')]
    issuer_organization_id: TextId
    issuer_actor_id: TextId
    issuer_function_ref: ref_type('FunctionAssignment')
    issuer_authority_ref: ref_type('Authorization')
    issuer_action_id: TextId
    issued_at: TimePoint
    status: Literal['authorized', 'proposed', 'withdrawn']


class ArchitectChangeDependencyView(CostSource):
    ref: ref_type('Dependency')
    used_deliverable_ref: ref_type('Deliverable')
    depends_on_variable_refs: list[ref_type('DesignVariable')]
    status: Literal['active', 'unknown', 'released']


class ArchitectChangeImpactMethodView(CostSource):
    ref: ref_type('Method')
    obligation_ref: ref_type('Obligation')
    supported: ValueState[bool]
    permitted_author_ids: list[TextId]
    purpose: Literal['scoped_design_change_impact']


class ArchitectChangeImpactResultView(CostSource):
    ref: ref_type('MethodResult')
    method_ref: ref_type('Method')
    input_sha256: Digest
    issue_ref: ref_type('Issue')
    used_deliverable_ref: ref_type('Deliverable')
    instruction_ref: ref_type('Instruction') | None
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    executed_at: TimePoint
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    cost_delta: ValueState[Money]
    duration_delta: ValueState[Measured]


class ArchitectChangeEntitlementView(CostSource):
    ref: ref_type('EntitlementDecision')
    issue_ref: ref_type('Issue')
    obligation_ref: ref_type('Obligation')
    contract_ref: ref_type('Contract')
    used_deliverable_ref: ref_type('Deliverable')
    cause: Literal['requirement_change', 'defect_remedy', 'interface_conflict', 'clarification']
    fee_right: ValueState[Literal['granted', 'denied']]
    resolver_organization_id: TextId
    resolver_actor_id: TextId
    resolver_function_ref: ref_type('FunctionAssignment')
    resolver_authority_ref: ref_type('Authorization')
    resolver_action_id: TextId
    decided_at: TimePoint


class ArchitectChangeQuestionView(CostSource):
    ref: ref_type('EvidenceTarget')
    issue_ref: ref_type('Issue')
    used_deliverable_ref: ref_type('Deliverable')
    question: ArchitectOpportunityQuestion


class ArchitectChangeImpactBasisView(CostSource):
    """Received original and proposed totals bound to the full change content."""
    ref: ref_type('DesignChangeImpactBasis')
    input: ArchitectChangeImpactArithmeticInput


class ArchitectChangeImpactInput(StrictRecord):
    """Exact original change content used to bind upstream impact evaluation."""
    issue_ref: ref_type('Issue')
    used_deliverable_ref: ref_type('Deliverable')
    original_content_sha256: Digest
    obligation_ref: ref_type('Obligation')
    instruction_ref: ref_type('Instruction') | None
    instruction_content: ArchitectChangeInstructionView | None
    affected_scope: ScopeRef
    affected_dependency_refs: list[ref_type('Dependency')]
    proposed_variable_changes: list[ArchitectDesignVariable]


class ArchitectChangeImpactPreparation(StrictRecord):
    """Predeclared impact result target and exact original evaluation input."""
    calculation_ref: ref_type('MethodResult')
    input: ArchitectChangeImpactInput


def architect_change_schemas():
    return service_intake_schemas(overrides={
        'Deliverable': ArchitectChangeDeliverableView, 'Issue': ArchitectChangeIssueView,
        'Obligation': ArchitectChangeObligationView, 'DesignChangeProfile': ArchitectChangeProfileView,
        'Instruction': ArchitectChangeInstructionView, 'Dependency': ArchitectChangeDependencyView,
        'Method': ArchitectChangeImpactMethodView, 'MethodResult': ArchitectChangeImpactResultView,
        'DesignChangeImpactBasis': ArchitectChangeImpactBasisView,
        'EntitlementDecision': ArchitectChangeEntitlementView, 'EvidenceTarget': ArchitectChangeQuestionView,
        'DesignVariable': ArchitectDesignVariableView, 'CatalogOption': ArchitectDesignReferenceView,
    })
