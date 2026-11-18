"""Original preliminary consultation and sourced guidance, separate from permits."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import ScopeRef, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.government_objects import (
    GovProjection, GovIntakeQuestion, GovJurisdictionView, GovMatterView,
    GovRecipientView, GovResponseRequirementView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import (
    ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView,
    ServiceScopeProjectView, ServiceWorkScopeView,
)


class GovAdviceSource(GovProjection):
    scope: ScopeRef
    available_at: TimePoint
    effective_window: TimeWindow


class GovConsultationRequestView(GovAdviceSource):
    ref: ref_type('ConsultationRequest')
    applicant_id: TextId
    recipient_organization_id: TextId
    brief_ref: ref_type('Brief') | None
    option_refs: list[ref_type('DesignOption')]
    matter_ref: ref_type('RegulatoryMatter')
    jurisdiction_ref: ref_type('Jurisdiction')
    procedure_ref: ref_type('Procedure') | None
    supplied_evidence_refs: list[ref_type('Evidence')]
    consultation_authority_ref: ref_type('Authority')
    guidance_rule_refs: list[ref_type('Rule')]
    information_requirement_refs: list[ref_type('InformationRequirement')]
    questions: list[GovIntakeQuestion]
    update_trigger_refs: list[ref_type('Trigger')]
    status: Literal['active', 'withdrawn']
    response_mode: Literal['advise', 'clarify']

    @model_validator(mode='after')
    def original_sets(self):
        for refs in (self.option_refs, self.supplied_evidence_refs, self.guidance_rule_refs,
                     self.information_requirement_refs, self.update_trigger_refs):
            unique_refs(refs)
        return self


class GovAdviceAuthorityView(GovAdviceSource):
    ref: ref_type('Authority')
    consultation_ref: ref_type('ConsultationRequest')
    applicant_id: TextId
    recipient_organization_id: TextId
    delegate_actor_id: TextId
    delegate_function_ref: ref_type('FunctionAssignment')
    permitted: ValueState[bool]
    allowed_recipient_ids: list[TextId]


class GovAdviceBriefView(GovAdviceSource):
    ref: ref_type('Brief')
    applicant_id: TextId
    option_refs: list[ref_type('DesignOption')]
    recipient_organization_ids: list[TextId]


class GovAdviceOptionView(GovAdviceSource):
    ref: ref_type('DesignOption')
    brief_ref: ref_type('Brief') | None
    applicant_id: TextId
    recipient_organization_ids: list[TextId]
    technical_status: Literal['proposed', 'incomplete', 'assessed']


class GovAdviceProcedureView(GovAdviceSource):
    ref: ref_type('Procedure')
    matter_ref: ref_type('RegulatoryMatter')
    jurisdiction_ref: ref_type('Jurisdiction')
    guidance_rule_refs: list[ref_type('Rule')]
    information_requirement_refs: list[ref_type('InformationRequirement')]


class GovAdviceRuleView(GovAdviceSource):
    ref: ref_type('Rule')
    organization_id: TextId
    consultation_ref: ref_type('ConsultationRequest')
    brief_ref: ref_type('Brief') | None
    option_refs: list[ref_type('DesignOption')]
    matter_ref: ref_type('RegulatoryMatter')
    jurisdiction_ref: ref_type('Jurisdiction')
    procedure_ref: ref_type('Procedure') | None
    purpose: Literal['advice', 'clarification', 'refer', 'outside_coverage']
    applicability: ValueState[Literal['applicable', 'not_applicable']]
    information_requirement_refs: list[ref_type('InformationRequirement')]
    recipient_ref: ref_type('RegulatoryRecipient') | None
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    explanation: TextId


class GovAdviceRequirementView(GovAdviceSource):
    ref: ref_type('InformationRequirement')
    consultation_ref: ref_type('ConsultationRequest')
    rule_ref: ref_type('Rule')
    procedure_ref: ref_type('Procedure') | None
    description: TextId


class GovAdviceTargetView(GovAdviceSource):
    ref: ref_type('EvidenceTarget')
    consultation_ref: ref_type('ConsultationRequest')
    brief_ref: ref_type('Brief') | None
    option_refs: list[ref_type('DesignOption')]


class GovAdviceTriggerView(GovAdviceSource):
    ref: ref_type('Trigger')
    consultation_ref: ref_type('ConsultationRequest')
    brief_ref: ref_type('Brief') | None
    option_refs: list[ref_type('DesignOption')]
    description: TextId


class GovAdviceRecipientView(GovRecipientView):
    organization_id: TextId
    jurisdiction_ref: ref_type('Jurisdiction')
    matter_refs: Annotated[list[ref_type('RegulatoryMatter')], Field(min_length=1)]


def government_advice_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'ConsultationRequest': GovConsultationRequestView, 'Authority': GovAdviceAuthorityView,
        'Brief': GovAdviceBriefView, 'DesignOption': GovAdviceOptionView,
        'RegulatoryMatter': GovMatterView, 'Jurisdiction': GovJurisdictionView,
        'Procedure': GovAdviceProcedureView, 'Rule': GovAdviceRuleView,
        'InformationRequirement': GovAdviceRequirementView, 'EvidenceTarget': GovAdviceTargetView,
        'Trigger': GovAdviceTriggerView, 'RegulatoryRecipient': GovAdviceRecipientView,
        'ResponseRequirement': GovResponseRequirementView, 'ClockProfile': ServiceClockView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    return registry
