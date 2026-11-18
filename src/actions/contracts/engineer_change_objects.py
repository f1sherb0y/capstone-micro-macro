"""Original professional remedy obligations, revision authority and saved rechecks."""
from typing import Literal

from src.actions.contracts.common import Measured, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.architect_review_objects import ArchitectReviewIndependenceView
from src.actions.contracts.architect_opportunity_objects import ArchitectOpportunityQuestion
from src.actions.contracts.engineer_design_objects import (
    EngineerDesignReferenceView, EngineerDesignDraft, EngineerDesignMethodView, EngineerDesignSubmissionView,
    EngineerResearchGapView, EngineerResearchCheckSpecView, EngineerParameterResultView,
    EngineerDesignMethodProjection, EngineerDesignParameterPreparation, EngineerDesignCheckPreparation, engineer_design_schemas,
)
from src.actions.contracts.engineer_research_objects import EngineerResearchCheckResultView
from src.methods.engineer_checks import EngineerInterfaceInput
from pydantic import model_serializer
from src.actions.contracts.common import ActionContext
from src.actions.contracts.engineer_submission_objects import EngineerSubmissionDeliverableView, EngineerRevisionRegistrationView


class EngineerChangeParameterPreparation(EngineerDesignParameterPreparation):
    """Original revision parameter input and its reserved versioned result."""


class EngineerChangeRevisionCheckPreparation(EngineerDesignCheckPreparation):
    """Original revision interface spec and its reserved versioned result."""


class EngineerChangeCheckPreparation(StrictRecord):
    """Original reassessment spec, reserved result and sourced code input."""
    calculation_ref: ref_type('MethodResult')
    check_spec_ref: ref_type('CheckSpec')
    input: EngineerInterfaceInput


class EngineerChangeDeliverableView(CostSource):
    ref: ref_type('Deliverable')
    content_sha256: Digest
    brief_ref: ref_type('Brief')
    option_ref: ref_type('DesignOption')
    engineering_profile_ref: ref_type('EngineeringProfile')
    parameter_refs: list[ref_type('ValidatedEngineeringParameter')]
    dependency_refs: list[ref_type('Dependency')]
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    authored_at: TimePoint
    author_personnel_ids: list[TextId]
    author_handoff_ref: ref_type('ChangeAuthorHandoff') | None = None

    @model_serializer(mode='wrap')
    def preserve_original_projection(self, handler):
        result = handler(self)
        if self.author_handoff_ref is None:
            result.pop('author_handoff_ref', None)
        return result


class EngineerChangeAuthorHandoffView(CostSource):
    """Actual native receipt of separately authorized original-author/integrator work."""
    ref: ref_type('ChangeAuthorHandoff')
    run_id: TextId
    source_organization_id: TextId
    source_request_id: TextId
    source_task_sha256: Digest
    source_context_sha256: Digest
    source_input_sha256: Digest
    issue_ref: ref_type('Issue')
    obligation_ref: ref_type('Obligation')
    prior_deliverable_ref: ref_type('Deliverable')
    original_content_sha256: Digest
    handoff_kind: Literal['original_author', 'authorized_integrator']
    target_organization_id: TextId
    target_action_id: TextId
    target_context: ActionContext
    target_task_ref: ref_type('Task')
    target_input_refs: list[Reference]
    target_input_sha256: Digest
    target_task_sha256: Digest
    target_authority_ref: ref_type('Authorization')
    integrator_mandate_ref: ref_type('Authorization') | None
    native_service_id: TextId
    native_submission_id: TextId
    native_record_sha256: Digest
    accepted_at: TimePoint | None
    as_of: TimePoint
    status: Literal['pending', 'unknown', 'accepted', 'rejected', 'failed']


class EngineerRevisionSubmissionView(EngineerDesignSubmissionView):
    """Actual A09 command query retaining revision lineage and full native deliverables."""
    issue_ref: ref_type('Issue')
    obligation_ref: ref_type('Obligation')
    prior_deliverable_ref: ref_type('Deliverable')
    original_content_sha256: Digest
    change_basis_ref: ref_type('ChangeBasis')
    instruction_ref: ref_type('Instruction') | None
    registration_refs: list[ref_type('EngineerRevisionRegistration')]
    registered_deliverables: list[EngineerSubmissionDeliverableView]


class EngineerChangeIssueView(EngineerDesignReferenceView):
    ref: ref_type('Issue')
    used_deliverable_ref: ref_type('Deliverable')
    obligation_ref: ref_type('Obligation')
    change_profile_ref: ref_type('EngineeringChangeProfile')
    kind: Literal['defect', 'commissioning_anomaly', 'requirement_change', 'interface_conflict']
    issue_status: Literal['open', 'unknown', 'closed']


class EngineerChangeObligationView(CostSource):
    ref: ref_type('Obligation')
    organization_id: TextId
    appointment_ref: ref_type('Appointment')
    contract_ref: ref_type('Contract')
    deliverable_ref: ref_type('Deliverable')
    status: Literal['effective', 'disputed', 'terminated']
    permitted_choices: list[Literal['propose_remedy', 'revise', 'reassess', 'request_test']]
    discipline_codes: list[TextId]
    function_codes: list[TextId]
    requested_uses: list[TextId]
    remedy_authority_ref: ref_type('Authority')
    instruction_required_for_revision: bool
    defect_remedy_authorized: bool
    permitted_instruction_issuer_ids: list[TextId]
    permitted_instruction_action_ids: list[TextId]
    permitted_parameter_catalog_refs: list[ref_type('EngineeringParameterCatalog')]
    permitted_affected_deliverable_refs: list[ref_type('Deliverable')]
    fee_status: Literal['undetermined', 'disputed', 'agreed']
    independence_rule: Literal['no_requirement', 'different_personnel', 'unrelated_organization_and_personnel']


class EngineerRemedyRequest(StrictRecord):
    scope: ScopeRef
    purpose: Literal['remedy', 'investigation']
    input_refs: list[Reference]
    output_requirement_refs: list[ref_type('DeliverableRequirement')]
    work_profile_ref: ref_type('WorkProfile') | None
    effort_estimate: ValueState[Measured]
    desired_window: ValueState[TimeWindow]
    authority_basis_refs: list[ref_type('Authority')]
    dependency_refs: list[ref_type('Dependency')]
    questions: list[ArchitectOpportunityQuestion]


class EngineerChangeProfileView(CostSource):
    ref: ref_type('EngineeringChangeProfile')
    issue_ref: ref_type('Issue')
    obligation_ref: ref_type('Obligation')
    authority_ref: ref_type('Authorization')
    choice: Literal['propose_remedy', 'revise', 'reassess', 'request_test']
    discipline_code: TextId
    function_code: TextId
    requested_use: TextId
    input_evidence_refs: list[ref_type('Evidence')]
    method_result_refs: list[ref_type('MethodResult')]
    affected_refs: list[ref_type('Deliverable')]
    affected_dependency_refs: list[ref_type('Dependency')]
    remedy_request: EngineerRemedyRequest | None
    revision_task_ref: ref_type('Task') | None
    change_basis_ref: ref_type('ChangeBasis') | None
    reassessment_task_ref: ref_type('Task') | None
    reassessment_scope_refs: list[ref_type('EngineeringScope')]
    reassessment_check_refs: list[ref_type('CheckSpec')]
    reassessment_independence_ref: ref_type('IndependenceCheck') | None
    reviewer_personnel_ids: list[TextId]
    question_refs: list[ref_type('EvidenceTarget')]
    test_method_ref: ref_type('Method') | None
    note: TextId


class EngineerChangeInstructionView(CostSource):
    ref: ref_type('Instruction')
    issue_ref: ref_type('Issue')
    obligation_ref: ref_type('Obligation')
    used_deliverable_ref: ref_type('Deliverable')
    original_content_sha256: Digest
    contract_ref: ref_type('Contract')
    permitted_parameter_catalog_refs: list[ref_type('EngineeringParameterCatalog')]
    affected_deliverable_refs: list[ref_type('Deliverable')]
    issuer_organization_id: TextId
    issuer_actor_id: TextId
    issuer_function_ref: ref_type('FunctionAssignment')
    issuer_authority_ref: ref_type('Authorization')
    issuer_action_id: TextId
    issued_at: TimePoint
    status: Literal['authorized', 'proposed', 'withdrawn']


class EngineerChangeBasisView(CostSource):
    ref: ref_type('ChangeBasis')
    issue_ref: ref_type('Issue')
    obligation_ref: ref_type('Obligation')
    prior_deliverable_ref: ref_type('Deliverable')
    original_content_sha256: Digest
    instruction_ref: ref_type('Instruction') | None
    draft_sha256: Digest
    authorized: ValueState[bool]
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    verified_at: TimePoint


class EngineerChangeQuestionView(EngineerResearchGapView):
    task_ref: ref_type('Task') | None
    brief_ref: ref_type('Brief') | None
    issue_ref: ref_type('Issue')
    used_deliverable_ref: ref_type('Deliverable')


class EngineerChangeCheckView(EngineerResearchCheckSpecView):
    target_ref: ref_type('Brief') | ref_type('DesignOption') | ref_type('Deliverable')
    original_content_sha256: Digest


class EngineerChangeCheckResultView(EngineerResearchCheckResultView):
    issue_ref: ref_type('Issue')
    original_content_sha256: Digest
    author_action_id: Literal['ENGINEER-A09']


class EngineerChangeMethodProjection(EngineerDesignMethodProjection):
    record: EngineerParameterResultView | EngineerResearchCheckResultView | EngineerChangeCheckResultView


class EngineerChangeScopeView(EngineerDesignReferenceView):
    ref: ref_type('EngineeringScope')
    used_deliverable_ref: ref_type('Deliverable')
    discipline_code: TextId
    physical_keys: list[TextId]


class EngineerRemedyAuthorityView(CostSource):
    ref: ref_type('Authority')
    organization_id: TextId
    actor_id: TextId
    issue_ref: ref_type('Issue')
    obligation_ref: ref_type('Obligation')
    permitted_purposes: list[Literal['remedy', 'investigation']]
    permitted_input_refs: list[Reference]
    permission: ValueState[bool]


class EngineerChangeIndependenceView(ArchitectReviewIndependenceView):
    issue_ref: ref_type('Issue')
    review_request_ref: ref_type('ReviewRequest') | None


class EngineerChangeMethodView(EngineerDesignMethodView):
    purpose: Literal['parameter_domain', 'professional_check', 'test']


class EngineerChangeDependencyView(CostSource):
    ref: ref_type('Dependency')
    used_deliverable_ref: ref_type('Deliverable')
    dependent_deliverable_ref: ref_type('Deliverable')
    parameter_catalog_refs: list[ref_type('EngineeringParameterCatalog')]
    status: Literal['active', 'unknown', 'released']


def engineer_change_schemas():
    return engineer_design_schemas({
        'Deliverable': EngineerChangeDeliverableView, 'Issue': EngineerChangeIssueView,
        'Obligation': EngineerChangeObligationView, 'EngineeringChangeProfile': EngineerChangeProfileView,
        'Instruction': EngineerChangeInstructionView, 'ChangeBasis': EngineerChangeBasisView,
        'EvidenceTarget': EngineerChangeQuestionView, 'CheckSpec': EngineerChangeCheckView,
        'Method': EngineerChangeMethodView, 'Dependency': EngineerChangeDependencyView,
        'MethodResult': EngineerChangeMethodProjection,
        'EngineeringScope': EngineerChangeScopeView,
        'Authority': EngineerRemedyAuthorityView,
        'IndependenceCheck': EngineerChangeIndependenceView,
        'ChangeAuthorHandoff': EngineerChangeAuthorHandoffView,
        'Submission': EngineerRevisionSubmissionView,
        'EngineerRevisionRegistration': EngineerRevisionRegistrationView,
    })
