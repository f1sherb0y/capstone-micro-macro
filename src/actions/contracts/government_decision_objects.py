"""Original decision gates, signer authority and formal submission recovery."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import ScopeRef, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.government_advice_objects import GovAdviceSource
from src.actions.contracts.government_objects import GovJurisdictionView, GovMatterView, GovRecipientView
from src.actions.contracts.government_review_objects import GovReviewAuthored, GovReviewSubmissionView, GovReviewMethodView
from src.actions.contracts.government_scheduling_objects import GovSchedulingCaseView
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView

DecisionOutcome = Literal['approve', 'approve_with_conditions', 'refuse', 'defer_by_procedure']


class GovDecisionCondition(StrictRecord):
    condition_rule_ref: ref_type('Rule')
    covered_scope: ScopeRef
    responsible_party_ids: Annotated[list[TextId], Field(min_length=1)]
    verifier_binding_ref: ref_type('FunctionAssignment')
    affected_action_refs: Annotated[list[ref_type('ActionDefinition')], Field(min_length=1)]
    required_evidence_refs: Annotated[list[ref_type('EvidenceRequirement')], Field(min_length=1)]
    verification_method_ref: ref_type('Method')
    due_rule_ref: ref_type('ClockRule') | None


class GovDecisionDraft(StrictRecord):
    outcome: DecisionOutcome
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    covered_scope: ScopeRef
    decision_basis_ref: ref_type('DecisionBasis')
    assessment_refs: list[ref_type('Assessment')]
    conditions: list[GovDecisionCondition]
    reason: TextId
    effect_rule_ref: ref_type('EffectRule')
    expiry_rule_ref: ref_type('ClockRule') | None
    notification_recipient_ids: Annotated[list[TextId], Field(min_length=1)]
    prior_decision_ref: ref_type('Decision') | None
    next_procedure_refs: list[ref_type('Procedure')]


class GovDecisionCaseView(GovSchedulingCaseView):
    assessment_refs: list[ref_type('Assessment')]
    unresolved_issue_refs: list[ref_type('Issue')]
    decision_refs: list[ref_type('Decision')]
    history_coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class GovDecisionBasisView(GovReviewAuthored):
    ref: ref_type('DecisionBasis')
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    signer_actor_id: TextId
    signer_function_ref: ref_type('FunctionAssignment')
    signer_authorization_ref: ref_type('Authorization')
    decision_authority_ref: ref_type('Authority')
    procedure_ref: ref_type('Procedure')
    decision_rule_ref: ref_type('Rule')
    draft: GovDecisionDraft
    condition_basis_refs: list[ref_type('ConditionBasis')]
    command_ref: ref_type('DecisionCommand')


class GovDecisionAuthorityView(GovAdviceSource):
    ref: ref_type('Authority')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    decision_basis_ref: ref_type('DecisionBasis')
    outcomes: list[DecisionOutcome]
    permitted: ValueState[bool]


class GovDecisionProcedureView(GovAdviceSource):
    ref: ref_type('Procedure')
    # A case-specific checklist may specialize an unchanged received intake
    # procedure. Its own identity/version must not overwrite that source.
    source_procedure_ref: ref_type('Procedure') | None = None
    case_ref: ref_type('RegulatoryCase')
    required_check_refs: list[ref_type('DecisionCheck')]
    required_procedure_refs: list[ref_type('ProcedureRequirement')]
    modeled: bool


class GovDecisionRuleView(GovAdviceSource):
    ref: ref_type('Rule')
    case_ref: ref_type('RegulatoryCase')
    procedure_ref: ref_type('Procedure')
    outcome: DecisionOutcome
    permitted: ValueState[bool]
    permits_incomplete_review: bool
    required_nonconforming_check_refs: list[ref_type('DecisionCheck')]
    issue_refs: list[ref_type('Issue')]
    effect_rule_ref: ref_type('EffectRule')
    expiry_rule_ref: ref_type('ClockRule') | None
    next_procedure_refs: list[ref_type('Procedure')]


class GovDecisionCheckView(GovAdviceSource):
    ref: ref_type('DecisionCheck')
    rule_ref: ref_type('Rule')
    required_before_approval: bool


class GovDecisionFindingView(GovReviewAuthored):
    ref: ref_type('MethodResult')
    assessment_ref: ref_type('Assessment')
    check_ref: ref_type('DecisionCheck')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    finding: Literal['conforms', 'nonconforms', 'unknown', 'not_applicable']
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    verification_evidence_refs: list[ref_type('Evidence')]
    applicability_basis_ref: ref_type('ApplicabilityBasis') | None
    method_ref: ref_type('Method')
    method_descriptor_ref: ref_type('MethodDescriptor') | None = None


class GovDecisionAssessmentView(GovReviewAuthored):
    ref: ref_type('Assessment')
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    check_result_refs: list[ref_type('MethodResult')]
    reuse_basis_ref: ref_type('DecisionReuseBasis') | None
    status: Literal['valid', 'withdrawn']


class GovDecisionReuseView(GovReviewAuthored):
    ref: ref_type('DecisionReuseBasis')
    assessment_ref: ref_type('Assessment')
    original_submission_ref: ref_type('Submission')
    original_content_sha256: Digest
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    reusable_check_refs: list[ref_type('DecisionCheck')]
    affected_check_refs: list[ref_type('DecisionCheck')]
    permitted: ValueState[bool]


class GovDecisionApplicabilityView(GovReviewAuthored):
    ref: ref_type('ApplicabilityBasis')
    check_ref: ref_type('DecisionCheck')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    applicable: ValueState[bool]


class GovDecisionIssueView(GovAdviceSource):
    ref: ref_type('Issue')
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    blocks_approval: bool
    check_refs: list[ref_type('DecisionCheck')]
    status: Literal['open', 'resolved']


class GovProcedureRequirementView(GovAdviceSource):
    ref: ref_type('ProcedureRequirement')
    procedure_ref: ref_type('Procedure')


class GovProcedureVerificationView(GovReviewAuthored):
    ref: ref_type('ProcedureVerification')
    requirement_ref: ref_type('ProcedureRequirement')
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    satisfied: ValueState[bool]


class GovProcedureCompletionView(GovReviewAuthored):
    ref: ref_type('ProcedureCompletion')
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    procedure_ref: ref_type('Procedure')
    verification_refs: list[ref_type('ProcedureVerification')]
    status: Literal['complete', 'partial', 'unknown']


class GovDecisionConditionBasisView(GovReviewAuthored):
    ref: ref_type('ConditionBasis')
    decision_basis_ref: ref_type('DecisionBasis')
    condition: GovDecisionCondition
    permitted: ValueState[bool]
    deferred_check_refs: list[ref_type('DecisionCheck')]


class GovDecisionEffectView(GovAdviceSource):
    ref: ref_type('EffectRule')
    decision_rule_ref: ref_type('Rule')
    outcome: DecisionOutcome
    mode: Literal['on_signed_record', 'on_actual_delivery', 'no_permission']
    notification_recipient_ids: list[TextId]
    modeled: bool


class GovDecisionBindingView(GovAdviceSource):
    ref: ref_type('ActionDefinition') | ref_type('EvidenceRequirement') | ref_type('ClockRule')
    decision_basis_ref: ref_type('DecisionBasis')


class GovDecisionMethodView(GovAdviceSource):
    ref: ref_type('Method')
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    actor_id: TextId
    organization_id: TextId
    action_id: TextId
    supported: ValueState[bool]


class GovDecisionCommandView(GovAdviceSource):
    ref: ref_type('DecisionCommand')
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    decision_basis_ref: ref_type('DecisionBasis')
    operation_id: TextId
    business_key: TextId
    draft_sha256: Digest
    official_decision_ref: ref_type('Decision') | None
    status: Literal['not_submitted', 'submitted_unknown', 'recorded', 'failed']
    lookup_status: Literal['not_queried', 'absent', 'present', 'unknown']


class GovFormalDecisionView(GovAdviceSource):
    ref: ref_type('Decision')
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    command_ref: ref_type('DecisionCommand')
    business_key: TextId
    draft_sha256: Digest
    signer_actor_id: TextId
    signer_function_ref: ref_type('FunctionAssignment')
    notification_refs: list[ref_type('DecisionNotification')]
    effective: ValueState[bool]


class GovDecisionNotificationView(GovAdviceSource):
    ref: ref_type('DecisionNotification')
    decision_ref: ref_type('Decision')
    recipient_id: TextId
    status: Literal['sent', 'delivered', 'unknown', 'failed']
    delivered_at: TimePoint | None


def government_decision_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'RegulatoryCase': GovDecisionCaseView, 'Submission': GovReviewSubmissionView,
        'DecisionBasis': GovDecisionBasisView, 'Authority': GovDecisionAuthorityView,
        'Procedure': GovDecisionProcedureView, 'Rule': GovDecisionRuleView, 'DecisionCheck': GovDecisionCheckView,
        'Assessment': GovDecisionAssessmentView, 'MethodResult': GovDecisionFindingView,
        'DecisionReuseBasis': GovDecisionReuseView, 'ApplicabilityBasis': GovDecisionApplicabilityView,
        'Issue': GovDecisionIssueView, 'ProcedureRequirement': GovProcedureRequirementView,
        'MethodDescriptor': GovReviewMethodView,
        'ProcedureVerification': GovProcedureVerificationView, 'ProcedureCompletion': GovProcedureCompletionView,
        'ConditionBasis': GovDecisionConditionBasisView, 'EffectRule': GovDecisionEffectView,
        'ActionDefinition': GovDecisionBindingView, 'EvidenceRequirement': GovDecisionBindingView,
        'ClockRule': GovDecisionBindingView, 'Method': GovDecisionMethodView,
        'DecisionCommand': GovDecisionCommandView, 'Decision': GovFormalDecisionView,
        'DecisionNotification': GovDecisionNotificationView, 'RegulatoryRecipient': GovRecipientView,
        'Jurisdiction': GovJurisdictionView, 'RegulatoryMatter': GovMatterView,
        'ClockProfile': ServiceClockView, 'Organization': ServiceScopeOrganizationView,
        'OwnerCase': ServiceScopeCaseView, 'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    return registry
