"""Original submission-bound rules, visible facts and scoped review records."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import DecimalString, Measured, ScopeRef, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.government_advice_objects import GovAdviceSource
from src.actions.contracts.government_objects import GovIntakeQuestion, GovJurisdictionView, GovMatterView, GovRecipientView, GovResponseRequirementView, GovSubmissionView
from src.actions.contracts.government_scheduling_objects import GovSchedulingCaseView, GovReviewAssignmentView, GovSchedulingDependencyView
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView
from src.methods.government_rules import GovRuleReport


class GovReviewSubmissionView(GovSubmissionView):
    available_at: TimePoint
    effective_window: TimeWindow
    content_sha256: Digest


class GovReviewTaskView(GovAdviceSource):
    ref: ref_type('Task')
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    assignment_ref: ref_type('ReviewAssignment')
    rule_refs: Annotated[list[ref_type('Rule')], Field(min_length=1)]
    professional_refs: list[ref_type('Assessment')]
    reuse_basis_refs: list[ref_type('ReviewReuseBasis')]
    verified_evidence_refs: list[ref_type('Evidence')]
    method_result_refs: list[ref_type('MethodResult')]
    dependency_refs: list[ref_type('Dependency')]
    question_refs: list[ref_type('EvidenceTarget')]
    condition_refs: list[ref_type('ConditionProposal')]
    verification_method_ref: ref_type('Method') | None
    choice: Literal['assess', 'request_verification', 'propose_conditions']
    explanation: TextId
    status: Literal['authorized', 'waiting', 'closed']


class GovReviewRuleView(GovAdviceSource):
    ref: ref_type('Rule')
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    jurisdiction_ref: ref_type('Jurisdiction')
    criterion: Literal['numeric_interval', 'code_equals', 'professional_evidence', 'unmodeled']
    method_ref: ref_type('Method') | None
    method_descriptor_ref: ref_type('MethodDescriptor') | None = None
    result_ref: ref_type('MethodResult') | None
    applicability_ref: ref_type('ApplicabilityBasis')
    fact_ref: ref_type('VerifiedFact') | None
    unit: TextId | None
    minimum: DecimalString | None
    maximum: DecimalString | None
    expected_code: TextId | None
    required_professions: list[Literal['Architect', 'Engineer', 'QS']]
    discipline_code: TextId
    question_refs: list[ref_type('EvidenceTarget')]


class GovReviewAuthored(GovAdviceSource):
    author_actor_id: TextId
    author_organization_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    authored_at: TimePoint


class GovReviewApplicabilityView(GovReviewAuthored):
    ref: ref_type('ApplicabilityBasis')
    rule_ref: ref_type('Rule')
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    applicable: ValueState[bool]


class GovReviewFactView(GovReviewAuthored):
    ref: ref_type('VerifiedFact')
    rule_ref: ref_type('Rule')
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    measured_value: ValueState[Measured] | None
    code_value: ValueState[TextId] | None
    verification_evidence_refs: list[ref_type('Evidence')]


class GovProfessionalFinding(GovReviewAuthored):
    ref: ref_type('ProfessionalVerification')
    assessment_ref: ref_type('Assessment')
    rule_ref: ref_type('Rule')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    method_ref: ref_type('Method')
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    finding: Literal['conforms', 'nonconforms', 'unknown']


class GovReviewReuseView(GovReviewAuthored):
    ref: ref_type('ReviewReuseBasis')
    task_ref: ref_type('Task')
    assessment_ref: ref_type('Assessment')
    rule_ref: ref_type('Rule')
    source_rule_ref: ref_type('Rule')
    source_submission_ref: ref_type('Submission')
    source_content_sha256: Digest
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    reusable: ValueState[bool]


class GovProfessionalOpinionView(GovReviewAuthored):
    ref: ref_type('Assessment')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    discipline_codes: list[TextId]
    verification_refs: list[ref_type('ProfessionalVerification')]
    status: Literal['available', 'withdrawn']


class GovReviewResultView(GovReviewAuthored):
    ref: ref_type('MethodResult')
    task_ref: ref_type('Task')
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    rule_ref: ref_type('Rule')
    method_ref: ref_type('Method')
    input_sha256: Digest
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    report: GovRuleReport | None


class GovReviewQuestionView(GovAdviceSource):
    ref: ref_type('EvidenceTarget')
    task_ref: ref_type('Task')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    question: GovIntakeQuestion


class GovReviewConditionView(GovAdviceSource):
    ref: ref_type('ConditionProposal')
    task_ref: ref_type('Task')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    condition_rule_ref: ref_type('Rule')
    responsible_party_ids: Annotated[list[TextId], Field(min_length=1)]
    verifier_binding_ref: ref_type('FunctionAssignment')
    affected_action_refs: Annotated[list[ref_type('ActionDefinition')], Field(min_length=1)]
    required_evidence_refs: Annotated[list[ref_type('EvidenceRequirement')], Field(min_length=1)]
    verification_method_ref: ref_type('Method')
    due_rule_ref: ref_type('ClockRule') | None
    proposal_authority_ref: ref_type('Authority')


class GovReviewConditionAuthorityView(GovAdviceSource):
    ref: ref_type('Authority')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    condition_ref: ref_type('ConditionProposal')
    responsible_party_ids: list[TextId]
    verifier_binding_ref: ref_type('FunctionAssignment')
    affected_action_refs: list[ref_type('ActionDefinition')]
    required_evidence_refs: list[ref_type('EvidenceRequirement')]
    verification_method_ref: ref_type('Method')
    due_rule_ref: ref_type('ClockRule') | None
    permitted: ValueState[bool]


class GovReviewMethodView(GovAdviceSource):
    ref: ref_type('Method') | ref_type('MethodDescriptor')
    calculation_method_ref: ref_type('Method') | None = None
    organization_id: TextId
    purpose: Literal['rule_check', 'verification']
    rule_refs: list[ref_type('Rule')]
    executor_function_ref: ref_type('FunctionAssignment')
    executor_authority_ref: ref_type('Authorization')
    executor_actor_id: TextId
    execution_action_id: TextId
    supported: ValueState[bool]


class GovReviewConditionBindingView(GovAdviceSource):
    ref: ref_type('ActionDefinition') | ref_type('EvidenceRequirement') | ref_type('ClockRule')
    condition_ref: ref_type('ConditionProposal')
    rule_ref: ref_type('Rule')


def government_review_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'RegulatoryCase': GovSchedulingCaseView, 'Submission': GovReviewSubmissionView,
        'Task': GovReviewTaskView, 'ReviewAssignment': GovReviewAssignmentView,
        'Dependency': GovSchedulingDependencyView, 'Rule': GovReviewRuleView,
        'ApplicabilityBasis': GovReviewApplicabilityView, 'VerifiedFact': GovReviewFactView,
        'Assessment': GovProfessionalOpinionView, 'ProfessionalVerification': GovProfessionalFinding,
        'ReviewReuseBasis': GovReviewReuseView, 'Method': GovReviewMethodView,
        'MethodDescriptor': GovReviewMethodView,
        'MethodResult': GovReviewResultView, 'EvidenceTarget': GovReviewQuestionView,
        'ConditionProposal': GovReviewConditionView, 'Authority': GovReviewConditionAuthorityView,
        'ActionDefinition': GovReviewConditionBindingView, 'EvidenceRequirement': GovReviewConditionBindingView,
        'ClockRule': GovReviewConditionBindingView,
        'RegulatoryRecipient': GovRecipientView, 'ResponseRequirement': GovResponseRequirementView,
        'Jurisdiction': GovJurisdictionView, 'RegulatoryMatter': GovMatterView,
        'ClockProfile': ServiceClockView, 'Organization': ServiceScopeOrganizationView,
        'OwnerCase': ServiceScopeCaseView, 'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    return registry
