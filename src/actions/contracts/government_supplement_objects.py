"""Original issues, responses, local revision coverage and explicit delay rules."""
from typing import Literal

from src.actions.contracts.common import DecimalString, Measured, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.government_advice_objects import GovAdviceSource
from src.actions.contracts.government_objects import GovIntakeQuestion, GovRecipientView, GovResponseRequirementView, GovJurisdictionView, GovMatterView
from src.actions.contracts.government_review_objects import GovReviewAuthored, GovReviewSubmissionView
from src.actions.contracts.government_scheduling_objects import GovSchedulingCaseView
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView
from src.methods.government_rules import GovRuleReport


class GovSupplementCaseView(GovSchedulingCaseView):
    supplement_profile_ref: ref_type('SupplementProfile')


class GovSupplementSubmissionView(GovReviewSubmissionView):
    component_refs: list[ref_type('SubmissionComponent')]


class GovSubmissionComponentView(GovAdviceSource):
    ref: ref_type('SubmissionComponent')
    submission_ref: ref_type('Submission')
    component_key: TextId
    content_sha256: Digest


class GovSupplementProfileView(GovAdviceSource):
    ref: ref_type('SupplementProfile')
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    authority_ref: ref_type('Authorization')
    original_submission_ref: ref_type('Submission')
    current_submission_ref: ref_type('Submission')
    revision_basis_ref: ref_type('RevisionBasis') | None
    issue_refs: list[ref_type('Issue')]
    response_refs: list[ref_type('Response')]
    authorized_response_actor_ids: list[TextId]
    assessment_refs: list[ref_type('Assessment')]
    clock_rule_ref: ref_type('ClockRule')
    choice: Literal['request_supplement', 'verify_response', 'process_delay']
    delay_rule_ref: ref_type('Rule') | None
    next_trigger_ref: ref_type('Trigger') | None
    coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class GovSupplementIssueView(GovAdviceSource):
    ref: ref_type('Issue')
    case_ref: ref_type('RegulatoryCase')
    original_submission_ref: ref_type('Submission')
    requirement_refs: list[ref_type('InformationRequirement')]
    question_refs: list[ref_type('EvidenceTarget')]
    verification_result_ref: ref_type('MethodResult') | None
    opened_at: TimePoint
    status: Literal['open', 'resolved']


class GovSupplementRequirementView(GovAdviceSource):
    ref: ref_type('InformationRequirement')
    issue_ref: ref_type('Issue')
    rule_ref: ref_type('Rule')
    component_key: TextId
    criterion: Literal['numeric_interval', 'code_equals', 'unmodeled']
    unit: TextId | None
    minimum: DecimalString | None
    maximum: DecimalString | None
    expected_code: TextId | None


class GovSupplementRuleView(GovAdviceSource):
    ref: ref_type('Rule')
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    purpose: Literal['supplement', 'delay']
    permitted: ValueState[bool]
    issue_refs: list[ref_type('Issue')]
    delay_effect: Literal['retain_queue', 'schedule_followup'] | None
    delay_authority_ref: ref_type('Authority') | None


class GovSupplementResponseView(GovReviewAuthored):
    ref: ref_type('Response')
    case_ref: ref_type('RegulatoryCase')
    issue_ref: ref_type('Issue')
    original_submission_ref: ref_type('Submission')
    current_submission_ref: ref_type('Submission')
    current_content_sha256: Digest
    event_id: TextId
    received_at: TimePoint
    fact_refs: list[ref_type('ResponseFact')]
    status: Literal['received', 'unknown', 'failed']


class GovResponseFactView(GovReviewAuthored):
    ref: ref_type('ResponseFact')
    response_ref: ref_type('Response')
    requirement_ref: ref_type('InformationRequirement')
    component_ref: ref_type('SubmissionComponent')
    measured_value: ValueState[Measured] | None
    code_value: ValueState[TextId] | None


class GovSupplementResultView(GovReviewAuthored):
    ref: ref_type('MethodResult')
    issue_ref: ref_type('Issue')
    current_submission_ref: ref_type('Submission')
    current_content_sha256: Digest
    response_refs: list[ref_type('Response')]
    method_ref: ref_type('Method')
    input_sha256s: dict[TextId, Digest]
    reports: dict[TextId, GovRuleReport]
    status: Literal['ok', 'unknown', 'failed', 'unsupported']


class GovSupplementAssessmentView(GovReviewAuthored):
    ref: ref_type('Assessment')
    case_ref: ref_type('RegulatoryCase')
    submission_ref: ref_type('Submission')
    content_sha256: Digest
    component_refs: list[ref_type('SubmissionComponent')]
    status: Literal['valid', 'withdrawn']


class GovSupplementRevisionView(GovReviewAuthored):
    ref: ref_type('RevisionBasis')
    case_ref: ref_type('RegulatoryCase')
    original_submission_ref: ref_type('Submission')
    original_content_sha256: Digest
    current_submission_ref: ref_type('Submission')
    current_content_sha256: Digest
    procedure_ref: ref_type('Procedure')
    route: Literal['continue_scoped_review', 'new_case', 'formal_reassessment', 'unmodeled']


class GovSupplementQuestionView(GovAdviceSource):
    ref: ref_type('EvidenceTarget')
    issue_ref: ref_type('Issue')
    question: GovIntakeQuestion


class GovSupplementClockView(GovAdviceSource):
    ref: ref_type('ClockRule')
    case_ref: ref_type('RegulatoryCase')
    procedure_ref: ref_type('Procedure')
    issue_refs: list[ref_type('Issue')]
    deadline: TimePoint | None


class GovSupplementDelayAuthorityView(GovAdviceSource):
    ref: ref_type('Authority')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    case_ref: ref_type('RegulatoryCase')
    rule_ref: ref_type('Rule')
    clock_rule_ref: ref_type('ClockRule')
    next_trigger_ref: ref_type('Trigger')
    issue_refs: list[ref_type('Issue')]
    permitted: ValueState[bool]


class GovSupplementTriggerView(GovAdviceSource):
    ref: ref_type('Trigger')
    case_ref: ref_type('RegulatoryCase')
    rule_ref: ref_type('Rule')
    issue_refs: list[ref_type('Issue')]
    next_at: TimePoint | None
    kind: Literal['response_received', 'scheduled_followup']


def government_supplement_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'RegulatoryCase': GovSupplementCaseView, 'Submission': GovSupplementSubmissionView,
        'SubmissionComponent': GovSubmissionComponentView, 'SupplementProfile': GovSupplementProfileView,
        'Issue': GovSupplementIssueView, 'InformationRequirement': GovSupplementRequirementView,
        'Rule': GovSupplementRuleView, 'Response': GovSupplementResponseView, 'ResponseFact': GovResponseFactView,
        'MethodResult': GovSupplementResultView, 'Assessment': GovSupplementAssessmentView,
        'RevisionBasis': GovSupplementRevisionView,
        'EvidenceTarget': GovSupplementQuestionView, 'ClockRule': GovSupplementClockView,
        'Authority': GovSupplementDelayAuthorityView, 'Trigger': GovSupplementTriggerView,
        'RegulatoryRecipient': GovRecipientView, 'ResponseRequirement': GovResponseRequirementView,
        'Jurisdiction': GovJurisdictionView, 'RegulatoryMatter': GovMatterView,
        'ClockProfile': ServiceClockView, 'Organization': ServiceScopeOrganizationView,
        'OwnerCase': ServiceScopeCaseView, 'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    return registry
