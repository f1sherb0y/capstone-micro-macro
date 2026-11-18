"""Observed government feedback, work proposals and optional policy suggestions."""
from typing import Literal

from src.actions.contracts.common import DecimalString, Measured, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_objects import GovIntakeQuestion, GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.government_scheduling_objects import GovReviewCalendarView, GovReviewResourceView, GovReviewQualificationView
from src.actions.contracts.qs_cost_objects import CostSource


class GovFeedbackRequest(StrictRecord):
    scope: ScopeRef
    purpose: Literal['investigation','policy_evaluation']
    input_refs: list[Reference]
    output_requirement_refs: list[ref_type('DeliverableRequirement')]
    work_profile_ref: ref_type('WorkProfile') | None
    effort_estimate: ValueState[Measured]
    desired_window: ValueState[TimeWindow]
    authority_basis_refs: list[ref_type('Authority')]
    dependency_refs: list[ref_type('Dependency')]
    questions: list[GovIntakeQuestion]


class GovFeedbackPlanItem(StrictRecord):
    task_ref: ref_type('Task')
    resource_ids: list[TextId]
    window: TimeWindow
    effort: Measured
    dependency_refs: list[ref_type('Dependency')]
    existing_assignment_ref: ref_type('ReviewAssignment') | None


class GovFeedbackPlan(StrictRecord):
    work_profile_ref: ref_type('WorkProfile')
    items: list[GovFeedbackPlanItem]


class GovFeedbackPolicyProposal(StrictRecord):
    issue_refs: list[ref_type('Feedback')]
    statistic_refs: list[ref_type('Statistic')]
    observation_profile_ref: ref_type('ObservationProfile')
    proposed_instrument_refs: list[ref_type('PolicyInstrument')]
    target_scope: ScopeRef
    mechanism_hypothesis: TextId
    evidence_refs: list[ref_type('Evidence')]
    evaluation_request: GovFeedbackRequest


class GovObservationProfileView(GovReviewAuthored):
    monthly_policy_ref: ref_type('MonthlyRegulatoryPolicy') | None = None
    monthly_observation_ref: ref_type('MonthlyRegulatoryObservation') | None = None
    ref: ref_type('ObservationProfile')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    working_authority_ref: ref_type('Authority')
    policy_control_profile_ref: ref_type('PolicyControlProfile') | None
    business_key: TextId
    choice: Literal['record_feedback','investigate','change_work_arrangement','propose_policy']
    feedback_refs: list[ref_type('Feedback')]
    statistic_refs: list[ref_type('Statistic')]
    interpretation: TextId
    questions: list[GovIntakeQuestion]
    investigation_request: GovFeedbackRequest | None
    work_plan: GovFeedbackPlan | None
    policy_proposal: GovFeedbackPolicyProposal | None
    execution_refs: list[ref_type('GovernmentFeedbackExecution')]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class GovWorkingAuthorityView(GovReviewAuthored):
    ref: ref_type('Authority')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    permitted: ValueState[bool]
    allowed_choices: list[Literal['record_feedback','investigate','change_work_arrangement','propose_policy']]
    allowed_input_refs: list[Reference]
    allowed_output_requirement_refs: list[ref_type('DeliverableRequirement')]
    allowed_instrument_refs: list[ref_type('PolicyInstrument')]
    allowed_recipient_refs: list[ref_type('RegulatoryRecipient')]
    authorized_task_refs: list[ref_type('Task')]
    required_task_refs: list[ref_type('Task')]
    replacement_assignment_refs: list[ref_type('ReviewAssignment')]
    calendar_ref: ref_type('ResourceCalendar')
    allowed_window: TimeWindow
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint


class GovReceivedFeedbackView(GovReviewAuthored):
    ref: ref_type('Feedback')
    recipient_organization_id: TextId
    event_key: TextId
    kind: Literal['complaint','case_experience','market','service_gap']
    event_source_ref: Reference
    event_source_sha256: TextId
    observed_at: TimePoint
    received_at: TimePoint
    status: Literal['unverified','verified','unknown']


class GovVisibleStatisticView(GovReviewAuthored):
    ref: ref_type('Statistic')
    recipient_organization_id: TextId
    metric: Literal['case_count','project_count','available_project_count','demand_signal','other_reported_signal']
    measure: ValueState[Measured]
    sampling_scope: ScopeRef
    reporting_window: TimeWindow
    received_at: TimePoint
    reporting_lag_ticks: int
    source_ref: ref_type('StatisticSnapshot')
    source_sha256: TextId
    case_ids: list[TextId]
    project_ids: list[TextId]
    available_project_refs: list[ref_type('AvailableProjectObservation')]
    coverage: Literal['complete','partial','unknown']


class GovStatisticSnapshotView(GovReviewAuthored):
    ref: ref_type('StatisticSnapshot')
    metric: Literal['case_count','project_count','available_project_count','demand_signal','other_reported_signal']
    measure: ValueState[Measured]
    sampling_scope: ScopeRef
    reporting_window: TimeWindow
    case_ids: list[TextId]
    project_ids: list[TextId]
    available_project_refs: list[ref_type('AvailableProjectObservation')]
    coverage: Literal['complete','partial','unknown']


class GovAvailableProjectView(GovReviewAuthored):
    ref: ref_type('AvailableProjectObservation')
    project_id: TextId
    actual_available: ValueState[bool]
    observed_at: TimePoint


class GovFeedbackWorkView(GovReviewAuthored):
    ref: ref_type('WorkProfile')
    organization_id: TextId
    effort_unit: TextId
    capacity_unit: TextId
    effort_per_capacity_tick: Measured
    request_estimate_ref: ref_type('FeedbackRequestEstimate') | None
    method: Literal['constant_capacity_over_half_open_window_v1']


class GovFeedbackRequestEstimateView(GovReviewAuthored):
    ref: ref_type('FeedbackRequestEstimate')
    organization_id: TextId
    work_profile_ref: ref_type('WorkProfile')
    purpose: Literal['investigation','policy_evaluation']
    input_refs: list[Reference]
    output_requirement_refs: list[ref_type('DeliverableRequirement')]
    effort: Measured
    executed_at: TimePoint
    status: Literal['succeeded','unknown','failed','unsupported']


class GovFeedbackTaskView(GovReviewAuthored):
    ref: ref_type('Task')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    execution_action_id: TextId
    work_profile_ref: ref_type('WorkProfile')
    estimate_ref: ref_type('WorkEstimate')
    remaining_effort: ValueState[Measured]
    function_code: TextId
    discipline_codes: list[TextId]
    region_id: TextId
    resource_effort_shares: dict[TextId, DecimalString]
    dependency_refs: list[ref_type('Dependency')]
    existing_assignment_ref: ref_type('ReviewAssignment') | None
    status: Literal['authorized','waiting','complete','cancelled']


class GovFeedbackEstimateView(GovReviewAuthored):
    ref: ref_type('WorkEstimate')
    task_ref: ref_type('Task')
    work_profile_ref: ref_type('WorkProfile')
    remaining_effort: Measured
    executed_at: TimePoint
    status: Literal['succeeded','unknown','failed','unsupported']


class GovFeedbackDependencyView(CostSource):
    ref: ref_type('Dependency')
    task_ref: ref_type('Task')
    satisfied: ValueState[bool]


class GovFeedbackAssignmentView(CostSource):
    ref: ref_type('ReviewAssignment')
    task_ref: ref_type('Task')
    organization_id: TextId
    commitment_refs: list[ref_type('ResourceCommitment')]
    status: Literal['effective','released','unknown']


class GovFeedbackCalendarView(GovReviewCalendarView):
    commitment_assignment_refs: dict[TextId,ref_type('ReviewAssignment')]


class GovPolicyControlView(GovReviewAuthored):
    ref: ref_type('PolicyControlProfile')
    organization_id: TextId
    endogenous_control_enabled: ValueState[bool]
    allowed_instrument_refs: list[ref_type('PolicyInstrument')]
    submission_stage: Literal['suggestion_only','evaluation_only']


class GovPolicyInstrumentView(GovReviewAuthored):
    ref: ref_type('PolicyInstrument')
    organization_id: TextId
    target_scope: ScopeRef
    legal_basis_refs: list[ref_type('Rule')]
    permitted_for_proposal: ValueState[bool]
    effect: Literal['proposal_only']


class GovFeedbackRuleView(GovReviewAuthored):
    ref: ref_type('Rule')
    organization_id: TextId
    permitted: ValueState[bool]
    purpose: Literal['information_request','proposal_basis']


class GovFeedbackRequirementView(GovReviewAuthored):
    ref: ref_type('DeliverableRequirement')
    organization_id: TextId
    requested_purpose: Literal['investigation','policy_evaluation']
    criterion: TextId


class GovFeedbackExecutionView(CostSource):
    ref: ref_type('GovernmentFeedbackExecution')
    organization_id: TextId
    run_id: TextId
    business_key: TextId
    profile_ref: ref_type('ObservationProfile')
    profile_sha256: TextId
    status: Literal['pending','unknown','succeeded','failed','rejected']


def government_feedback_schemas():
    from src.actions.contracts.government_monthly_objects import GovMonthlyPolicy,GovMonthlyObservation
    return contractor_bid_schemas({'ObservationProfile':GovObservationProfileView,'Authority':GovWorkingAuthorityView,
        'MonthlyRegulatoryPolicy':GovMonthlyPolicy,'MonthlyRegulatoryObservation':GovMonthlyObservation,
        'Feedback':GovReceivedFeedbackView,'Statistic':GovVisibleStatisticView,'StatisticSnapshot':GovStatisticSnapshotView,
        'AvailableProjectObservation':GovAvailableProjectView,'WorkProfile':GovFeedbackWorkView,'Task':GovFeedbackTaskView,
        'WorkEstimate':GovFeedbackEstimateView,'FeedbackRequestEstimate':GovFeedbackRequestEstimateView,
        'Dependency':GovFeedbackDependencyView,'ReviewAssignment':GovFeedbackAssignmentView,
        'ResourceCalendar':GovFeedbackCalendarView,'Resource':GovReviewResourceView,'Qualification':GovReviewQualificationView,
        'PolicyControlProfile':GovPolicyControlView,'PolicyInstrument':GovPolicyInstrumentView,'Rule':GovFeedbackRuleView,
        'DeliverableRequirement':GovFeedbackRequirementView,'RegulatoryRecipient':GovRecipientView,
        'ResponseRequirement':GovResponseRequirementView,'GovernmentFeedbackExecution':GovFeedbackExecutionView})
