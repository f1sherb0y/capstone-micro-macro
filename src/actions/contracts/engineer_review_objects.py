"""Original scoped professional reviews, saved interface checks and coordination."""
from typing import Literal

from src.actions.contracts.common import StrictRecord, TextId, TimePoint, ref_type
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.architect_review_objects import (
    Digest, ArchitectReviewTargetView, ArchitectReviewIndependenceView, ArchitectReviewIssueView,
)
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.engineer_appointment_objects import EngineerAppointmentView
from src.actions.contracts.engineer_objects import EngineerServiceTermsView, EngineerIndependenceRequirementView, EngineerOrganizationRelationsView
from src.actions.contracts.engineer_research_objects import EngineerResearchFactView
from src.actions.contracts.service_objects import ServiceUse, service_intake_schemas
from src.methods.engineer_checks import EngineerInterfaceInput, EngineerInterfaceReport


class EngineerReviewFactView(EngineerResearchFactView):
    content_sha256: Digest


class EngineerReviewTargetView(ArchitectReviewTargetView):
    author_action_id: TextId


class EngineerReviewCheckTarget(StrictRecord):
    check_spec_ref: ref_type('CheckSpec')
    calculation_ref: ref_type('MethodResult')


class EngineerReviewCheckPreparation(StrictRecord):
    calculation_ref: ref_type('MethodResult')
    check_spec_ref: ref_type('CheckSpec')
    input: EngineerInterfaceInput


class EngineerReviewTaskView(CostSource):
    ref: ref_type('Task')
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    function_ref: ref_type('FunctionAssignment')
    appointment_ref: ref_type('Appointment')
    review_request_ref: ref_type('ReviewRequest')
    target_ref: ref_type('Deliverable')
    discipline_code: TextId
    function_code: TextId
    requested_use: ServiceUse
    status: Literal['authorized', 'waiting', 'closed']
    check_result_targets: list[EngineerReviewCheckTarget] = []


class EngineerReviewRequestView(CostSource):
    ref: ref_type('ReviewRequest')
    task_ref: ref_type('Task')
    appointment_ref: ref_type('Appointment')
    target_ref: ref_type('Deliverable')
    content_sha256: Digest
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    requested_use: ServiceUse
    choice: Literal['assess', 'request_evidence', 'request_coordination']
    required_check_refs: list[ref_type('CheckSpec')]
    received_method_result_refs: list[ref_type('MethodResult')]
    interface_refs: list[ref_type('Interface')]
    engineering_scope_refs: list[ref_type('EngineeringScope')]
    reviewer_personnel_ids: list[TextId]
    independence_check_ref: ref_type('IndependenceCheck') | None
    question_refs: list[ref_type('EvidenceTarget')]
    coordination_issue_refs: list[ref_type('Issue')]
    coordination_recipient_id: TextId | None
    coordination_requirement_ref: ref_type('ResponseRequirement') | None
    explanation: TextId
    status: Literal['authorized', 'withdrawn']


class EngineerReviewSpecView(CostSource):
    ref: ref_type('CheckSpec')
    review_request_ref: ref_type('ReviewRequest')
    target_ref: ref_type('Deliverable')
    content_sha256: Digest
    engineering_scope_ref: ref_type('EngineeringScope')
    discipline_code: TextId
    function_code: TextId
    requested_use: ServiceUse
    requested_check: TextId
    method_ref: ref_type('Method') | None
    left_fact_ref: ref_type('EngineeringFact') | None
    right_fact_ref: ref_type('EngineeringFact') | None
    interface_refs: list[ref_type('Interface')]
    issue_refs: list[ref_type('Issue')]


class EngineerReviewMethodView(CostSource):
    ref: ref_type('Method')
    discipline_codes: list[TextId]
    function_codes: list[TextId]
    region_ids: list[TextId]
    object_types: list[TextId]
    allowed_uses: list[ServiceUse]


class EngineerReviewResultView(CostSource):
    ref: ref_type('MethodResult')
    review_request_ref: ref_type('ReviewRequest')
    task_ref: ref_type('Task')
    target_ref: ref_type('Deliverable')
    content_sha256: Digest
    check_spec_ref: ref_type('CheckSpec')
    method_ref: ref_type('Method')
    requested_use: ServiceUse
    status: Literal['ok', 'unknown', 'failed', 'unsupported']
    result: EngineerInterfaceReport | None
    input_fact_refs: list[ref_type('EngineeringFact')]
    issue_refs: list[ref_type('Issue')]
    executed_at: TimePoint
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['ENGINEER-A05', 'ENGINEER-A06', 'ENGINEER-A13']


class EngineerReviewIndependenceView(ArchitectReviewIndependenceView):
    requirement_ref: ref_type('IndependenceRequirement')


class EngineerReviewInterfaceView(CostSource):
    ref: ref_type('Interface')
    review_request_ref: ref_type('ReviewRequest')
    target_ref: ref_type('Deliverable')
    content_sha256: Digest
    engineering_scope_ref: ref_type('EngineeringScope')
    check_spec_refs: list[ref_type('CheckSpec')]
    issue_refs: list[ref_type('Issue')]


class EngineerReviewScopeView(CostSource):
    ref: ref_type('EngineeringScope')
    review_request_ref: ref_type('ReviewRequest')
    target_ref: ref_type('Deliverable')
    content_sha256: Digest
    discipline_code: TextId


class EngineerReviewQuestionView(CostSource):
    ref: ref_type('EvidenceTarget')
    review_request_ref: ref_type('ReviewRequest')
    target_ref: ref_type('Deliverable')
    question: ArchitectOpportunityQuestion


def engineer_review_schemas():
    return service_intake_schemas(overrides={
        'Deliverable': EngineerReviewTargetView, 'ReviewRequest': EngineerReviewRequestView,
        'Task': EngineerReviewTaskView, 'Appointment': EngineerAppointmentView, 'ServiceTerms': EngineerServiceTermsView,
        'CheckSpec': EngineerReviewSpecView, 'Method': EngineerReviewMethodView, 'MethodResult': EngineerReviewResultView,
        'EngineeringFact': EngineerReviewFactView, 'EngineeringScope': EngineerReviewScopeView,
        'IndependenceCheck': EngineerReviewIndependenceView, 'IndependenceRequirement': EngineerIndependenceRequirementView,
        'OrganizationRelations': EngineerOrganizationRelationsView, 'Interface': EngineerReviewInterfaceView,
        'Issue': ArchitectReviewIssueView, 'EvidenceTarget': EngineerReviewQuestionView,
    })
