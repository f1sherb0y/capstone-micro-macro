"""Authorized inspection tasks, actual observations and scoped enforcement evidence."""
from typing import Literal

from src.actions.contracts.common import DecimalString, Measured, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.government_advice_objects import GovAdviceSource
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.government_objects import GovIntakeQuestion, GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_permit_objects import GovPermitView
from src.actions.contracts.government_scheduling_objects import (
    GovSchedulingTaskView, GovSchedulingWorkProfileView, GovSchedulingEstimateView,
    GovSchedulingWorkFactView, GovSchedulingDependencyView, GovReviewResourceView,
    GovReviewQualificationView, GovReviewCalendarView, GovReviewAssignmentView,
)
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView
from src.methods.capacity import CapacityCommitment
from src.methods.government_rules import GovRuleReport


class GovInspectionTaskView(GovSchedulingTaskView):
    inspection_basis_ref: ref_type('Rule')
    permit_ref: ref_type('Permit') | None
    inspection_ref: ref_type('Inspection')
    observation_method_ref: ref_type('Method')
    received_observation_refs: list[ref_type('Observation')]
    prior_issue_refs: list[ref_type('Issue')]
    check_rule_refs: list[ref_type('Rule')]
    question_refs: list[ref_type('EvidenceTarget')]
    resource_calendar_ref: ref_type('ResourceCalendar') | None
    region_id: TextId
    measure_basis_ref: ref_type('MeasureBasis') | None
    choice: Literal['plan', 'report', 'require_response', 'order_measure', 'recheck']
    explanation: TextId


class GovInspectionView(GovAdviceSource):
    ref: ref_type('Inspection')
    organization_id: TextId
    task_ref: ref_type('Task')
    permit_ref: ref_type('Permit') | None


class GovInspectionRuleView(GovAdviceSource):
    ref: ref_type('Rule')
    organization_id: TextId
    task_ref: ref_type('Task')
    inspection_ref: ref_type('Inspection')
    purpose: Literal['inspection', 'check', 'question', 'measure', 'requirement']
    permitted: ValueState[bool]
    criterion: Literal['numeric_interval', 'code_equals', 'unmodeled'] | None
    applicable: ValueState[bool] | None
    applicability_basis_ref: ref_type('ApplicabilityBasis') | None
    observation_ref: ref_type('Observation') | None
    result_ref: ref_type('MethodResult') | None
    method_ref: ref_type('Method') | None
    unit: TextId | None
    minimum: DecimalString | None
    maximum: DecimalString | None
    expected_code: TextId | None
    requires_site_observation: bool


class GovInspectionApplicabilityView(GovReviewAuthored):
    ref: ref_type('ApplicabilityBasis')
    rule_ref: ref_type('Rule')
    task_ref: ref_type('Task')
    applicable: ValueState[bool]


class GovInspectionMethodView(GovAdviceSource):
    ref: ref_type('Method')
    supported: ValueState[bool]
    requires_site_access: bool
    permitted_executor_actions: list[TextId]
    permitted_executor_organization_ids: list[TextId]


class GovInspectionAccessView(GovAdviceSource):
    ref: ref_type('SiteAccess')
    task_ref: ref_type('Task')
    organization_ids: list[TextId]
    allowed: ValueState[bool]


class GovInspectionObservationView(GovReviewAuthored):
    ref: ref_type('Observation')
    task_ref: ref_type('Task')
    inspection_ref: ref_type('Inspection')
    permit_ref: ref_type('Permit') | None
    method_ref: ref_type('Method')
    access_ref: ref_type('SiteAccess') | None
    observed_window: TimeWindow
    event_id: TextId
    factual_kind: Literal['actual', 'commitment', 'assumption']
    status: Literal['executed', 'unknown', 'failed', 'unsupported']
    measured_value: ValueState[Measured] | None
    code_value: ValueState[TextId] | None


class GovInspectionResultView(GovReviewAuthored):
    ref: ref_type('MethodResult')
    task_ref: ref_type('Task')
    rule_ref: ref_type('Rule')
    observation_ref: ref_type('Observation') | None
    issue_ref: ref_type('Issue') | None
    requirement_ref: ref_type('InformationRequirement') | None
    method_ref: ref_type('Method')
    input_sha256: Digest
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    report: GovRuleReport | None


class GovInspectionQuestionView(GovAdviceSource):
    ref: ref_type('EvidenceTarget')
    task_ref: ref_type('Task')
    issue_ref: ref_type('Issue') | None
    question: GovIntakeQuestion


class GovInspectionIssueView(GovAdviceSource):
    ref: ref_type('Issue')
    task_ref: ref_type('Task')
    requirement_refs: list[ref_type('InformationRequirement')]
    response_refs: list[ref_type('Response')]
    assessment_refs: list[ref_type('Assessment')]
    verification_result_ref: ref_type('MethodResult') | None
    verification_coverage: Literal['complete', 'partial', 'unknown']
    history_coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint
    status: Literal['open', 'resolved']


class GovInspectionRequirementView(GovAdviceSource):
    ref: ref_type('InformationRequirement')
    issue_ref: ref_type('Issue')
    rule_ref: ref_type('Rule')
    content_sha256: Digest
    verified_fact_ref: ref_type('RemedyVerification') | None


class GovInspectionResponseView(GovReviewAuthored):
    ref: ref_type('Response')
    task_ref: ref_type('Task')
    issue_ref: ref_type('Issue')
    event_id: TextId
    received_at: TimePoint
    status: Literal['received', 'unknown', 'failed']
    responder_authority_ref: ref_type('RemedyResponderAuthority')
    verification_refs: list[ref_type('RemedyVerification')]


class GovRemedyVerificationView(GovReviewAuthored):
    ref: ref_type('RemedyVerification')
    task_ref: ref_type('Task')
    issue_ref: ref_type('Issue')
    response_ref: ref_type('Response')
    requirement_ref: ref_type('InformationRequirement')
    requirement_content_sha256: Digest
    observation_ref: ref_type('Observation') | None
    result_ref: ref_type('MethodResult') | None
    measured_value: ValueState[Measured] | None
    code_value: ValueState[TextId] | None
    factual_kind: Literal['actual', 'commitment', 'assumption']


class GovInspectionRequirementSnapshot(StrictRecord):
    requirement_ref: ref_type('InformationRequirement')
    content_sha256: Digest
    fact_sha256: Digest | None


class GovInspectionAssessmentView(GovReviewAuthored):
    ref: ref_type('Assessment')
    issue_ref: ref_type('Issue')
    requirement_snapshots: list[GovInspectionRequirementSnapshot]
    status: Literal['valid', 'withdrawn']


class GovRemedyResponderAuthorityView(GovAdviceSource):
    ref: ref_type('RemedyResponderAuthority')
    issue_ref: ref_type('Issue')
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    organization_id: TextId
    permitted: ValueState[bool]


class GovIssueVerificationResultView(GovInspectionResultView):
    verified_requirement_refs: list[ref_type('InformationRequirement')]


class GovInspectionMeasure(StrictRecord):
    measure_type_ref: ref_type('RegulatoryMeasureType')
    authority_basis_ref: ref_type('Authority')
    rule_ref: ref_type('Rule')
    affected_scope: ScopeRef
    affected_action_refs: list[ref_type('ActionDefinition')]
    evidence_refs: list[ref_type('Evidence')]
    effect_rule_ref: ref_type('EffectRule')
    review_trigger_ref: ref_type('Trigger')
    recipient_ids: list[TextId]


class GovMeasureBasisView(GovReviewAuthored):
    ref: ref_type('MeasureBasis')
    task_ref: ref_type('Task')
    procedure_ref: ref_type('Procedure')
    procedure_verification_ref: ref_type('MeasureProcedureVerification')
    measure: GovInspectionMeasure


class GovInspectionAuthorityView(GovAdviceSource):
    ref: ref_type('Authority')
    task_ref: ref_type('Task')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    measure_type_ref: ref_type('RegulatoryMeasureType')
    rule_ref: ref_type('Rule')
    action_refs: list[ref_type('ActionDefinition')]
    recipient_ids: list[TextId]
    permitted: ValueState[bool]


class GovMeasureTypeView(GovAdviceSource):
    ref: ref_type('RegulatoryMeasureType')
    organization_id: TextId
    permitted_action_refs: list[ref_type('ActionDefinition')]
    modeled: bool


class GovMeasureBindingView(GovAdviceSource):
    ref: ref_type('ActionDefinition') | ref_type('EffectRule') | ref_type('Trigger') | ref_type('Procedure')
    measure_basis_ref: ref_type('MeasureBasis')


class GovMeasureProcedureVerificationView(GovReviewAuthored):
    ref: ref_type('MeasureProcedureVerification')
    measure_basis_ref: ref_type('MeasureBasis')
    procedure_ref: ref_type('Procedure')
    measure_sha256: Digest
    satisfied: ValueState[bool]


def government_inspection_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'Task': GovInspectionTaskView, 'Inspection': GovInspectionView, 'Permit': GovPermitView,
        'Rule': GovInspectionRuleView, 'ApplicabilityBasis': GovInspectionApplicabilityView,
        'Method': GovInspectionMethodView, 'SiteAccess': GovInspectionAccessView,
        'Observation': GovInspectionObservationView, 'MethodResult': GovIssueVerificationResultView,
        'EvidenceTarget': GovInspectionQuestionView, 'RegulatoryRecipient': GovRecipientView,
        'ResponseRequirement': GovResponseRequirementView, 'Issue': GovInspectionIssueView,
        'InformationRequirement': GovInspectionRequirementView, 'Response': GovInspectionResponseView,
        'RemedyVerification': GovRemedyVerificationView, 'Assessment': GovInspectionAssessmentView,
        'RemedyResponderAuthority': GovRemedyResponderAuthorityView,
        'MeasureBasis': GovMeasureBasisView, 'Authority': GovInspectionAuthorityView,
        'RegulatoryMeasureType': GovMeasureTypeView, 'ActionDefinition': GovMeasureBindingView,
        'EffectRule': GovMeasureBindingView, 'Trigger': GovMeasureBindingView, 'Procedure': GovMeasureBindingView,
        'MeasureProcedureVerification': GovMeasureProcedureVerificationView,
        'WorkProfile': GovSchedulingWorkProfileView, 'WorkEstimate': GovSchedulingEstimateView,
        'WorkFact': GovSchedulingWorkFactView, 'ResourceCalendar': GovReviewCalendarView,
        'Resource': GovReviewResourceView, 'Qualification': GovReviewQualificationView,
        'Dependency': GovSchedulingDependencyView, 'ReviewAssignment': GovReviewAssignmentView,
        'ClockProfile': ServiceClockView, 'Organization': ServiceScopeOrganizationView,
        'OwnerCase': ServiceScopeCaseView, 'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    registry.register_kind('ResourceCommitment', CapacityCommitment, str, identity_field='commitment_ref')
    return registry
