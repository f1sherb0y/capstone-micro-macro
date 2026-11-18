"""Original author references and scoped integration delegation; no approvals."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import Reference, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.architect_research_objects import ArchitectResearchOptionView
from src.actions.contracts.architect_design_objects import ArchitectDesignRegistrationView
from src.actions.contracts.service_objects import service_intake_schemas


class ArchitectIntegrationOptionView(ArchitectResearchOptionView):
    integration_profile_ref: ref_type('IntegrationProfile')


class ArchitectIntegrationProfileView(CostSource):
    ref: ref_type('IntegrationProfile')
    option_ref: ref_type('DesignOption')
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    choice: Literal['raise_interfaces', 'integrate', 'escalate', 'request_inputs']
    without_authority_choice: Literal['raise_interfaces', 'escalate', 'request_inputs']
    professional_refs: list[ref_type('Assessment')]
    cost_refs: list[ref_type('CostPlan')]
    supply_refs: list[ref_type('SupplyAdvice')]
    interface_refs: list[ref_type('Interface')]
    open_issue_refs: list[ref_type('Issue')]
    consistency_result_refs: list[ref_type('MethodResult')]
    question_refs: list[ref_type('EvidenceTarget')]
    allowed_recipient_ids: list[TextId]
    recipient_authority_ref: ref_type('Authorization') | None
    recipient_action_id: TextId | None
    reason: TextId
    coverage: Literal['complete', 'partial', 'unknown']


class ArchitectIntegrationSourceView(CostSource):
    ref: ref_type('Assessment') | ref_type('CostPlan') | ref_type('SupplyAdvice')
    option_ref: ref_type('DesignOption')
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    authored_at: TimePoint
    conclusion: ValueState[Literal['compatible', 'conflict', 'not_applicable']]
    unresolved_issue_refs: list[ref_type('Issue')]
    status: Literal['recorded', 'unknown', 'failed', 'unsupported']


class ArchitectIntegrationAuthorityView(CostSource):
    ref: ref_type('Authority')
    option_ref: ref_type('DesignOption')
    grantee_organization_id: TextId
    grantee_actor_id: TextId
    grantee_function_ref: ref_type('FunctionAssignment')
    issuer_organization_id: TextId
    issuer_actor_id: TextId
    issuer_function_ref: ref_type('FunctionAssignment')
    issuer_authority_ref: ref_type('Authorization')
    issuer_action_id: TextId
    granted_at: TimePoint
    permission: ValueState[bool]
    permitted_input_refs: list[Reference]
    permitted_interface_refs: list[ref_type('Interface')]


class ArchitectIntegrationIssueView(CostSource):
    ref: ref_type('Issue')
    option_ref: ref_type('DesignOption')
    status: Literal['open', 'closed', 'unknown']
    author_reference_refs: list[Reference]
    interface_refs: list[ref_type('Interface')]
    responsible_ids: Annotated[list[TextId], Field(min_length=1)]


class ArchitectIntegrationInterfaceView(CostSource):
    ref: ref_type('Interface')
    option_ref: ref_type('DesignOption')
    input_refs: list[Reference]
    unresolved_issue_refs: list[ref_type('Issue')]


class ArchitectIntegrationQuestionView(CostSource):
    ref: ref_type('EvidenceTarget')
    option_ref: ref_type('DesignOption')
    question: ArchitectOpportunityQuestion


class ArchitectIntegrationDigest(StrictRecord):
    input_ref: Reference
    content_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class ArchitectIntegrationConsistencyPreparation(StrictRecord):
    """Explicit original method declaration and predeclared report target."""
    calculation_ref: ref_type('MethodResult')
    method_ref: ref_type('Method')


class ArchitectRegisteredIntegrationDraft(StrictRecord):
    """Complete original integration payload retained by the native registry."""
    option_ref: ref_type('DesignOption')
    included_assessment_refs: list[ref_type('Assessment')]
    included_cost_refs: list[ref_type('CostPlan')]
    interface_refs: list[ref_type('Interface')]
    open_issue_refs: list[ref_type('Issue')]
    integration_authority_ref: ref_type('Authority')
    consistency_result_refs: list[ref_type('MethodResult')]


class ArchitectIntegrationConsistencyInput(StrictRecord):
    """Author references only; never a technical compatibility determination."""
    option_ref: ref_type('DesignOption')
    input_digests: Annotated[list[ArchitectIntegrationDigest], Field(min_length=1)]
    original_objects: Annotated[list[ArchitectIntegrationOptionView | ArchitectIntegrationSourceView
        | ArchitectIntegrationInterfaceView | ArchitectIntegrationIssueView], Field(min_length=1)]
    interface_refs: list[ref_type('Interface')]
    retained_issue_refs: list[ref_type('Issue')]
    source_refs: Annotated[list[Reference], Field(min_length=1)]
    basis_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]


class ArchitectIntegrationConsistencyReport(StrictRecord):
    option_ref: ref_type('DesignOption')
    input_digests: list[ArchitectIntegrationDigest]
    interface_refs: list[ref_type('Interface')]
    retained_issue_refs: list[ref_type('Issue')]
    status: Literal['ok', 'unknown']
    issues: list[TextId]
    technical_approval: Literal[False]


class ArchitectIntegrationConsistencyView(CostSource):
    ref: ref_type('MethodResult')
    option_ref: ref_type('DesignOption')
    method_ref: ref_type('Method')
    input_digests: list[ArchitectIntegrationDigest]
    interface_refs: list[ref_type('Interface')]
    retained_issue_refs: list[ref_type('Issue')]
    executed_at: TimePoint
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    status: Literal['ok', 'unknown', 'failed', 'unsupported']


class ArchitectIntegrationMethodView(CostSource):
    ref: ref_type('Method')
    option_ref: ref_type('DesignOption')
    purpose: Literal['original_interface_reference_consistency']
    checked_fields: list[Literal['original_option_version', 'original_author_content', 'retained_open_issues']]
    technical_approval: Literal[False]


def architect_integration_schemas():
    return service_intake_schemas(overrides={
        'DesignOption': ArchitectIntegrationOptionView, 'IntegrationProfile': ArchitectIntegrationProfileView,
        'DesignRegistration': ArchitectDesignRegistrationView,
        'Authority': ArchitectIntegrationAuthorityView, 'Issue': ArchitectIntegrationIssueView,
        'Interface': ArchitectIntegrationInterfaceView, 'EvidenceTarget': ArchitectIntegrationQuestionView,
        'MethodResult': ArchitectIntegrationConsistencyView, 'Method': ArchitectIntegrationMethodView,
        **{kind: ArchitectIntegrationSourceView for kind in ('Assessment', 'CostPlan', 'SupplyAdvice')},
    })
