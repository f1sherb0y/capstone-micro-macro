"""Original transition rules and independently authorized changes to existing decisions."""
from typing import Literal

from src.actions.contracts.common import ScopeRef, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.government_advice_objects import GovAdviceSource
from src.actions.contracts.government_review_objects import GovReviewAuthored, GovReviewSubmissionView
from src.actions.contracts.government_decision_objects import (
    GovDecisionDraft, GovFormalDecisionView, GovDecisionCommandView, GovDecisionNotificationView,
    GovDecisionAssessmentView, GovDecisionFindingView, GovDecisionCheckView,
    GovDecisionConditionBasisView, GovDecisionBindingView, GovDecisionMethodView, GovDecisionCondition,
    GovProcedureCompletionView, GovProcedureVerificationView, GovProcedureRequirementView,
)
from src.actions.contracts.government_objects import GovIntakeQuestion, GovRecipientView, GovResponseRequirementView
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView

ChangeOutcome = Literal['renew', 'suspend', 'revoke', 'restore']
TransitionChoice = Literal['confirm_coverage', 'open_review', 'renew', 'suspend', 'revoke', 'restore', 'record_scheduled_expiry']


class GovChangeDraft(GovDecisionDraft):
    outcome: ChangeOutcome


class GovTransitionDecisionView(GovFormalDecisionView):
    organization_id: TextId
    applicant_id: TextId
    outcome: TextId
    permit_ref: ref_type('Permit') | None
    effect_rule_ref: ref_type('EffectRule')
    changeable: ValueState[bool]
    conditions: list[GovDecisionCondition]
    history_refs: list[ref_type('Decision')]
    history_coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class GovTransitionPermitView(GovAdviceSource):
    ref: ref_type('Permit')
    organization_id: TextId
    decision_ref: ref_type('Decision')
    status: Literal['valid', 'expired', 'suspended', 'revoked', 'unknown']
    effective: ValueState[bool]
    as_of: TimePoint
    expiry_rule_ref: ref_type('Rule') | None
    expiry_event_ref: ref_type('PermitExpiryFact') | None


class GovTransitionApplicationView(GovReviewAuthored):
    ref: ref_type('RegulatoryApplication')
    applicant_id: TextId
    recipient_organization_id: TextId
    prior_decision_ref: ref_type('Decision')
    permit_ref: ref_type('Permit') | None
    affected_submission_ref: ref_type('Submission') | None
    content_sha256: Digest | None
    submitter_authority_ref: ref_type('ApplicationAuthority')
    status: Literal['received', 'withdrawn']


class GovTransitionApplicantAuthorityView(GovAdviceSource):
    ref: ref_type('ApplicationAuthority')
    application_ref: ref_type('RegulatoryApplication')
    applicant_id: TextId
    submitter_actor_id: TextId
    submitter_function_ref: ref_type('FunctionAssignment')
    submitter_organization_id: TextId
    permitted: ValueState[bool]


class GovTransitionRuleView(GovAdviceSource):
    ref: ref_type('Rule')
    organization_id: TextId
    prior_decision_ref: ref_type('Decision')
    permit_ref: ref_type('Permit') | None
    application_ref: ref_type('RegulatoryApplication') | None
    affected_submission_ref: ref_type('Submission') | None
    content_sha256: Digest | None
    purpose: Literal['transition', 'coverage', 'review', 'outcome', 'expiry', 'question', 'condition']
    permitted: ValueState[bool]
    published_at: TimePoint
    policy_effective_at: TimePoint
    transition_scope: ScopeRef
    applicability: Literal['current', 'grandfathered', 'future', 'unmodeled']
    choice: TransitionChoice | None
    coverage_rule_refs: list[ref_type('Rule')]
    review_rule_ref: ref_type('Rule') | None
    question_refs: list[ref_type('EvidenceTarget')]
    decision_basis_ref: ref_type('DecisionBasis') | None
    expiry_rule_ref: ref_type('Rule') | None


class GovChangeBasisView(GovReviewAuthored):
    ref: ref_type('DecisionBasis')
    transition_rule_ref: ref_type('Rule')
    outcome_rule_ref: ref_type('Rule')
    application_ref: ref_type('RegulatoryApplication') | None
    content_sha256: Digest
    authority_ref: ref_type('Authority')
    signer_authorization_ref: ref_type('Authorization')
    procedure_ref: ref_type('Procedure')
    command_ref: ref_type('DecisionCommand')
    condition_basis_refs: list[ref_type('ConditionBasis')]
    removed_condition_rule_refs: list[ref_type('Rule')]
    draft: GovChangeDraft


class GovChangeCheckView(GovDecisionCheckView):
    decision_basis_ref: ref_type('DecisionBasis')
    allowed_findings: list[Literal['conforms', 'nonconforms']]


class GovChangeAuthorityView(GovAdviceSource):
    ref: ref_type('Authority')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    prior_decision_ref: ref_type('Decision')
    permit_ref: ref_type('Permit') | None
    decision_basis_ref: ref_type('DecisionBasis')
    outcomes: list[ChangeOutcome]
    permitted: ValueState[bool]


class GovChangeProcedureView(GovAdviceSource):
    ref: ref_type('Procedure')
    decision_basis_ref: ref_type('DecisionBasis')
    required_check_refs: list[ref_type('DecisionCheck')]
    required_procedure_refs: list[ref_type('ProcedureRequirement')]
    completion_ref: ref_type('ProcedureCompletion')
    modeled: bool


class GovChangeEffectView(GovAdviceSource):
    ref: ref_type('EffectRule')
    outcome: TextId
    decision_basis_ref: ref_type('DecisionBasis') | None
    decision_ref: ref_type('Decision') | None
    mode: Literal['on_signed_record', 'on_actual_delivery']
    notification_recipient_ids: list[TextId]
    expiry_rule_ref: ref_type('ClockRule') | None
    next_procedure_refs: list[ref_type('Procedure')]


class GovExpiryFactView(GovAdviceSource):
    ref: ref_type('PermitExpiryFact')
    permit_ref: ref_type('Permit')
    prior_decision_ref: ref_type('Decision')
    expiry_rule_ref: ref_type('Rule')
    producer: Literal['core']
    occurred_at: TimePoint
    event_id: TextId


class GovTransitionQuestionView(GovAdviceSource):
    ref: ref_type('EvidenceTarget')
    prior_decision_ref: ref_type('Decision')
    question: GovIntakeQuestion


def government_transition_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'Decision': GovTransitionDecisionView, 'Permit': GovTransitionPermitView,
        'RegulatoryApplication': GovTransitionApplicationView, 'Submission': GovReviewSubmissionView,
        'ApplicationAuthority': GovTransitionApplicantAuthorityView,
        'Rule': GovTransitionRuleView, 'DecisionBasis': GovChangeBasisView, 'Authority': GovChangeAuthorityView,
        'Procedure': GovChangeProcedureView, 'EffectRule': GovChangeEffectView,
        'DecisionCommand': GovDecisionCommandView, 'DecisionNotification': GovDecisionNotificationView,
        'Assessment': GovDecisionAssessmentView, 'MethodResult': GovDecisionFindingView,
        'DecisionCheck': GovChangeCheckView, 'ProcedureCompletion': GovProcedureCompletionView,
        'ProcedureRequirement': GovProcedureRequirementView, 'ProcedureVerification': GovProcedureVerificationView,
        'PermitExpiryFact': GovExpiryFactView, 'EvidenceTarget': GovTransitionQuestionView,
        'RegulatoryRecipient': GovRecipientView, 'ResponseRequirement': GovResponseRequirementView,
        'ConditionBasis': GovDecisionConditionBasisView, 'ActionDefinition': GovDecisionBindingView,
        'EvidenceRequirement': GovDecisionBindingView, 'ClockRule': GovDecisionBindingView, 'Method': GovDecisionMethodView,
        'ClockProfile': ServiceClockView, 'Organization': ServiceScopeOrganizationView,
        'OwnerCase': ServiceScopeCaseView, 'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    return registry
