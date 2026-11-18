"""Owner applications and responses to original jurisdiction-bound notices."""
from typing import Annotated, Literal

from pydantic import StringConstraints, model_validator

from src.actions.contracts.common import Reference, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_design_objects import OwnerDesignScopeChoice
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView


class OwnerRegulatoryRequirementView(CostSource):
    ref: ref_type('RegulatoryRequirement')
    applicant_id: TextId
    project_region_id: TextId
    matter_refs: list[ref_type('RegulatoryMatter')]
    decision_profile_ref: ref_type('OwnerRegulatoryProfile')


class OwnerRegulatoryQuestion(StrictRecord):
    local_key: TextId
    subject_ref: ref_type('BusinessObject')
    issue_ref: ref_type('Issue') | None
    request: str
    requirement_refs: list[ref_type('Requirement')]
    evidence_refs: list[ref_type('Evidence')]


class OwnerRegulatoryProfileView(CostSource):
    ref: ref_type('OwnerRegulatoryProfile')
    organization_id: TextId
    requirement_ref: ref_type('RegulatoryRequirement')
    authority_ref: ref_type('Authorization')
    choice: Literal['authorize_agent', 'submit', 'supplement', 'withdraw', 'request_review']
    competent_authority_ref: ref_type('CompetentAuthority') | None
    case_ref: ref_type('RegulatoryCase') | None
    submission_refs: list[ref_type('DeliverableSubmission')]
    evidence_refs_to_submit: list[ref_type('Evidence')]
    requested_matter_refs: list[ref_type('RegulatoryMatter')]
    delegate_id: TextId | None
    delegated_scope: OwnerDesignScopeChoice
    agency_authority_ref: ref_type('RegulatoryAgencyAuthorization') | None
    response_items: list[OwnerRegulatoryQuestion]
    withdrawal_basis_refs: list[ref_type('Evidence')]
    prior_execution_ref: ref_type('RegulatorySubmissionExecution') | None
    note: TextId


class OwnerRegulatoryAgencyView(CostSource):
    ref: ref_type('RegulatoryAgencyAuthorization')
    applicant_id: TextId
    delegate_id: TextId
    requirement_ref: ref_type('RegulatoryRequirement')
    matter_refs: list[ref_type('RegulatoryMatter')]
    permitted_choices: list[Literal['submit', 'supplement', 'withdraw', 'request_review']]
    permission: ValueState[bool]
    issuer_actor_id: TextId
    issuer_function_ref: ref_type('FunctionAssignment')
    issuer_authority_ref: ref_type('Authorization')
    status: Literal['effective', 'proposed', 'revoked']


class OwnerRegulatoryAuthorityView(CostSource):
    ref: ref_type('CompetentAuthority')
    organization_id: TextId
    jurisdiction_ref: ref_type('Jurisdiction')
    matter_refs: list[ref_type('RegulatoryMatter')]
    procedure_ref: ref_type('Procedure')


class OwnerRegulatoryJurisdictionView(CostSource):
    ref: ref_type('Jurisdiction')
    organization_id: TextId
    region_ids: list[TextId]
    matter_refs: list[ref_type('RegulatoryMatter')]
    permission: ValueState[bool]


class OwnerRegulatoryMatterView(CostSource):
    ref: ref_type('RegulatoryMatter')
    requirement_ref: ref_type('RegulatoryRequirement')
    region_id: TextId
    authority_ref: ref_type('CompetentAuthority')
    required_material_refs: list[ref_type('InformationRequirement')]


class OwnerRegulatoryMaterialView(CostSource):
    ref: ref_type('InformationRequirement')
    matter_ref: ref_type('RegulatoryMatter')
    evidence_ref: ref_type('Evidence')
    submission_refs: list[ref_type('DeliverableSubmission')]
    verified: ValueState[bool]


class OwnerRegulatoryProcedureView(CostSource):
    ref: ref_type('Procedure')
    authority_ref: ref_type('CompetentAuthority')
    matter_refs: list[ref_type('RegulatoryMatter')]
    applicant_ids: list[TextId]
    permitted_choices: list[Literal['submit', 'supplement', 'withdraw', 'request_review']]
    response_windows: dict[Literal['submit', 'supplement', 'withdraw', 'request_review'], TimeWindow]
    allowed_submission_maturities: list[Literal['research', 'performance_requirement', 'tender_design', 'construction_release']]
    professional_submission_required: bool


class OwnerRegulatorySubmissionView(CostSource):
    ref: ref_type('DeliverableSubmission')
    applicant_id: TextId
    requirement_ref: ref_type('RegulatoryRequirement')
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    maturity: Literal['research', 'performance_requirement', 'tender_design', 'construction_release']
    allowed_use_codes: list[Literal['regulatory_submission']]
    status: Literal['submitted', 'superseded', 'withdrawn']


class OwnerRegulatoryCaseView(CostSource):
    ref: ref_type('RegulatoryCase')
    applicant_id: TextId
    requirement_ref: ref_type('RegulatoryRequirement')
    authority_ref: ref_type('CompetentAuthority')
    matter_refs: list[ref_type('RegulatoryMatter')]
    submission_refs: list[ref_type('DeliverableSubmission')]
    open_notice_refs: list[ref_type('RegulatoryNotice')]
    status: Literal['received', 'pending', 'decided', 'withdrawn', 'closed']
    permitted_choices: list[Literal['supplement', 'withdraw', 'request_review']]


class OwnerRegulatoryNoticeView(CostSource):
    ref: ref_type('RegulatoryNotice')
    case_ref: ref_type('RegulatoryCase')
    authority_ref: ref_type('CompetentAuthority')
    applicant_id: TextId
    required_response_refs: list[ref_type('Requirement')]
    subject_refs: list[ref_type('BusinessObject')]
    issue_refs: list[ref_type('Issue')]
    purpose: Literal['supplement', 'review', 'decision']
    response_window: TimeWindow
    issuer_actor_id: TextId
    issuer_function_ref: ref_type('FunctionAssignment')
    issuer_authority_ref: ref_type('Authorization')
    issuer_action_id: TextId


class OwnerRegulatoryResponseSourceView(CostSource):
    ref: Reference
    requirement_ref: ref_type('RegulatoryRequirement')
    case_ref: ref_type('RegulatoryCase') | None
    notice_ref: ref_type('RegulatoryNotice') | None
    applicant_id: TextId
    permitted: ValueState[bool]


class OwnerRegulatoryExecutionView(CostSource):
    ref: ref_type('RegulatorySubmissionExecution')
    organization_id: TextId
    applicant_id: TextId
    requirement_ref: ref_type('RegulatoryRequirement')
    command_id: TextId
    case_ref: ref_type('RegulatoryCase') | None
    status: Literal['unknown', 'pending', 'received', 'failed', 'rejected']
    result_basis_ref: ref_type('Evidence')


RegulatoryDigest = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]


class OwnerRegulatoryRecoveryDispositionView(CostSource):
    """Read-only projection of an actual separately authorized native disposition.

    The native source owns this record and its legal effect. The adapter never
    issues it or infers a permit, a deadline extension or correction authority.
    """
    ref: ref_type('RegulatoryRecoveryDisposition')
    native_disposition_key: TextId
    recipient_organization_id: TextId
    applicant_id: TextId
    original_request_id: TextId
    original_input_sha256: RegulatoryDigest
    original_condition_code: TextId
    original_requirement_ref: ref_type('RegulatoryRequirement')
    requirement_ref: ref_type('RegulatoryRequirement')
    original_dependency_ref: Reference
    current_dependency_ref: Reference
    current_profile_ref: ref_type('OwnerRegulatoryProfile')
    command_id: TextId | None
    disposition_kind: Literal['authorized_correction', 'case_action', 'procedure_action', 'notice_response']
    permitted_choice: Literal['submit', 'supplement', 'withdraw', 'request_review']
    permitted: ValueState[bool]
    issuer_organization_id: TextId
    issuer_actor_id: TextId
    issuer_function_ref: ref_type('FunctionAssignment')
    issuer_authority_ref: ref_type('Authorization')
    issuer_action_id: TextId
    issued_at: TimePoint

    @model_validator(mode='after')
    def original_native_identity(self):
        if (self.original_dependency_ref.key()[:2] != self.current_dependency_ref.key()[:2]
                or self.original_requirement_ref.key()[:2] != self.requirement_ref.key()[:2]
                or (self.disposition_kind == 'authorized_correction') != (self.command_id is not None)):
            raise ValueError('Regulatory disposition changes the original dependency, requirement or correction command')
        return self


def owner_regulatory_schemas():
    registry = common_projection_schemas()
    schemas = {
        'RegulatoryRequirement': OwnerRegulatoryRequirementView, 'OwnerRegulatoryProfile': OwnerRegulatoryProfileView,
        'RegulatoryAgencyAuthorization': OwnerRegulatoryAgencyView, 'CompetentAuthority': OwnerRegulatoryAuthorityView,
        'Jurisdiction': OwnerRegulatoryJurisdictionView, 'RegulatoryMatter': OwnerRegulatoryMatterView,
        'InformationRequirement': OwnerRegulatoryMaterialView, 'Procedure': OwnerRegulatoryProcedureView,
        'DeliverableSubmission': OwnerRegulatorySubmissionView, 'RegulatoryCase': OwnerRegulatoryCaseView,
        'RegulatoryNotice': OwnerRegulatoryNoticeView, 'RegulatorySubmissionExecution': OwnerRegulatoryExecutionView,
        'RegulatoryRecoveryDisposition': OwnerRegulatoryRecoveryDispositionView,
        **{kind: OwnerRegulatoryResponseSourceView for kind in ('BusinessObject', 'Issue', 'Requirement')},
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView, 'ClockProfile': ServiceClockView,
    }
    for kind, schema in schemas.items(): registry.register_kind(kind, schema, str)
    return registry
