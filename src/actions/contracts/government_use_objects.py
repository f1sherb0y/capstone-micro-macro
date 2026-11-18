"""Current use applications, actual completion and independently scoped use procedures."""
from typing import Literal
from pydantic import model_validator

from src.actions.contracts.common import Measured, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.government_advice_objects import GovAdviceSource
from src.actions.contracts.government_review_objects import GovReviewAuthored, GovReviewSubmissionView
from src.actions.contracts.government_decision_objects import (
    GovDecisionCaseView, GovDecisionDraft, GovDecisionAuthorityView, GovDecisionRuleView,
    GovDecisionCheckView, GovDecisionFindingView, GovDecisionAssessmentView, GovDecisionApplicabilityView,
    GovProcedureCompletionView, GovProcedureVerificationView, GovProcedureRequirementView,
    GovDecisionConditionBasisView, GovDecisionEffectView, GovDecisionBindingView, GovDecisionMethodView,
    GovDecisionIssueView,
)
from src.actions.contracts.government_objects import GovIntakeQuestion, GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_permit_objects import GovPermitView
from src.actions.contracts.government_scheduling_objects import (
    GovSchedulingTaskView, GovSchedulingWorkProfileView, GovSchedulingEstimateView,
    GovSchedulingDependencyView, GovReviewCalendarView, GovReviewResourceView,
    GovReviewQualificationView, GovReviewAssignmentView,
)
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView
from src.methods.capacity import CapacityInput, CapacityReport, CapacityCommitment


class GovUseApplicationView(GovReviewSubmissionView):
    ref: ref_type('RegulatoryApplication')
    submission_ref: ref_type('Submission')
    application_authority_ref: ref_type('UseApplicationAuthority')
    case_ref: ref_type('RegulatoryCase')
    use_codes: list[TextId]
    completed_scope_refs: list[ref_type('WorkFact')]
    professional_proof_refs: list[ref_type('Assessment')]
    test_result_refs: list[ref_type('MethodResult')]
    permit_refs: list[ref_type('Permit')]
    remaining_condition_refs: list[ref_type('PermitCondition')]
    history_coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class GovUseCaseView(GovDecisionCaseView):
    review_assignment_refs: list[ref_type('ReviewAssignment')]


class GovUseApplicationAuthorityView(GovAdviceSource):
    ref: ref_type('UseApplicationAuthority')
    application_ref: ref_type('RegulatoryApplication')
    applicant_id: TextId
    submitter_id: TextId
    actor_id: TextId
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authorization_ref: ref_type('Authorization')
    action_id: TextId
    permitted: ValueState[bool]


class GovUseProcedureView(GovAdviceSource):
    ref: ref_type('Procedure')
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    application_ref: ref_type('RegulatoryApplication')
    content_sha256: Digest
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authorization_ref: ref_type('Authorization')
    permitted: ValueState[bool]
    use_codes: list[TextId]
    required_completed_scope_refs: list[ref_type('WorkScope')]
    required_check_refs: list[ref_type('DecisionCheck')]
    required_procedure_refs: list[ref_type('ProcedureRequirement')]
    completion_ref: ref_type('ProcedureCompletion') | None
    question_refs: list[ref_type('EvidenceTarget')]
    plan_ref: ref_type('UseVerificationPlan') | None
    decision_basis_ref: ref_type('DecisionBasis') | None
    choice: Literal['request_evidence', 'plan_verification', 'propose_use_decision', 'continue_supervision']
    modeled: bool


class GovUseWorkFactView(GovReviewAuthored):
    ref: ref_type('WorkFact')
    task_ref: ref_type('Task')
    case_ref: ref_type('RegulatoryCase')
    work_kind: Literal['completed_scope', 'review_effort']
    completed_scope_refs: list[ref_type('WorkScope')]
    actual_verified: ValueState[bool]
    investment_key: TextId
    core_event_id: TextId
    effort: Measured
    window: TimeWindow
    status: Literal['committed', 'unknown', 'failed']


class GovUseConditionView(GovAdviceSource):
    ref: ref_type('PermitCondition')
    permit_ref: ref_type('Permit')
    condition_rule_ref: ref_type('Rule')
    required_before_use: bool
    status: Literal['pending', 'satisfied', 'released', 'unknown']
    supervision_task_refs: list[ref_type('Task')]


class GovUseDecisionBasisView(GovReviewAuthored):
    ref: ref_type('DecisionBasis')
    application_ref: ref_type('RegulatoryApplication')
    content_sha256: Digest
    decision_rule_ref: ref_type('Rule')
    authority_ref: ref_type('Authority')
    signer_authorization_ref: ref_type('Authorization')
    signer_actor_id: TextId
    signer_function_ref: ref_type('FunctionAssignment')
    retained_condition_refs: list[ref_type('PermitCondition')]
    release_assignment_refs: list[ref_type('ReviewAssignment')]
    retained_assignment_refs: list[ref_type('ReviewAssignment')]
    condition_basis_refs: list[ref_type('ConditionBasis')]
    draft: GovDecisionDraft


class GovUseRuleView(GovAdviceSource):
    ref: ref_type('Rule')
    application_ref: ref_type('RegulatoryApplication')
    condition_ref: ref_type('PermitCondition') | None
    condition_basis_ref: ref_type('ConditionBasis') | None
    question_ref: ref_type('EvidenceTarget') | None
    check_ref: ref_type('DecisionCheck') | None
    decision: GovDecisionRuleView | None
    permitted: ValueState[bool]

    @model_validator(mode='after')
    def one_purpose(self):
        if sum(value is not None for value in (self.condition_ref, self.condition_basis_ref, self.question_ref, self.check_ref, self.decision)) != 1:
            raise ValueError('Use rule must have exactly one original decision, condition or question purpose')
        if self.decision is not None and self.decision.ref != self.ref:
            raise ValueError('Nested use decision rule changes original rule identity')
        return self


class GovUseQuestionView(GovAdviceSource):
    ref: ref_type('EvidenceTarget')
    application_ref: ref_type('RegulatoryApplication')
    question: GovIntakeQuestion


class GovUsePlanItem(StrictRecord):
    task_ref: ref_type('Task')
    resource_ids: list[TextId]
    window: TimeWindow
    effort: Measured
    dependency_refs: list[ref_type('Dependency')]
    existing_assignment_ref: ref_type('ReviewAssignment') | None


class GovUseTaskPlan(StrictRecord):
    work_profile_ref: ref_type('WorkProfile')
    items: list[GovUsePlanItem]


class GovUsePlanView(GovReviewAuthored):
    ref: ref_type('UseVerificationPlan')
    application_ref: ref_type('RegulatoryApplication')
    content_sha256: Digest
    purpose: Literal['use_verification', 'continuing_supervision']
    task_refs: list[ref_type('Task')]
    resource_calendar_ref: ref_type('ResourceCalendar')
    capacity_result_ref: ref_type('CapacityEvaluation')
    plan: GovUseTaskPlan


class GovUseCapacityResultView(GovReviewAuthored):
    ref: ref_type('CapacityEvaluation')
    plan_ref: ref_type('UseVerificationPlan')
    method_ref: ref_type('Method')
    plan_sha256: Digest
    data: CapacityInput
    report: CapacityReport | None
    status: Literal['ok', 'unknown', 'failed', 'unsupported']


def government_use_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'RegulatoryCase': GovUseCaseView, 'RegulatoryApplication': GovUseApplicationView,
        'Submission': GovReviewSubmissionView, 'Procedure': GovUseProcedureView, 'WorkFact': GovUseWorkFactView,
        'UseApplicationAuthority': GovUseApplicationAuthorityView,
        'Permit': GovPermitView, 'PermitCondition': GovUseConditionView, 'DecisionBasis': GovUseDecisionBasisView,
        'Authority': GovDecisionAuthorityView, 'Rule': GovUseRuleView, 'Assessment': GovDecisionAssessmentView,
        'DecisionCheck': GovDecisionCheckView, 'MethodResult': GovDecisionFindingView,
        'ApplicabilityBasis': GovDecisionApplicabilityView, 'ProcedureCompletion': GovProcedureCompletionView,
        'Issue': GovDecisionIssueView,
        'ProcedureVerification': GovProcedureVerificationView, 'ProcedureRequirement': GovProcedureRequirementView,
        'ConditionBasis': GovDecisionConditionBasisView, 'EffectRule': GovDecisionEffectView,
        'ActionDefinition': GovDecisionBindingView, 'EvidenceRequirement': GovDecisionBindingView,
        'ClockRule': GovDecisionBindingView, 'Method': GovDecisionMethodView,
        'EvidenceTarget': GovUseQuestionView, 'RegulatoryRecipient': GovRecipientView,
        'ResponseRequirement': GovResponseRequirementView, 'UseVerificationPlan': GovUsePlanView,
        'CapacityEvaluation': GovUseCapacityResultView, 'Task': GovSchedulingTaskView,
        'WorkProfile': GovSchedulingWorkProfileView, 'WorkEstimate': GovSchedulingEstimateView,
        'Dependency': GovSchedulingDependencyView, 'ResourceCalendar': GovReviewCalendarView,
        'Resource': GovReviewResourceView, 'Qualification': GovReviewQualificationView,
        'ReviewAssignment': GovReviewAssignmentView, 'ClockProfile': ServiceClockView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    registry.register_kind('ResourceCommitment', CapacityCommitment, str, identity_field='commitment_ref')
    return registry
