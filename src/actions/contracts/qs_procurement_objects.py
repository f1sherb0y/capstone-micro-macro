"""Original procurement tasks, quantity documents and independent publication grants."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import (
    Measured, ScopeRef, StrictRecord, TextId, TimePoint, ValueState, ref_type,
)
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.service_objects import (
    SourcedServiceProjection, ServiceUse, ServiceClockView,
    ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView,
)
from src.methods.pricing import decimal_fraction


class QSProcurementQuestion(StrictRecord):
    scope: ScopeRef
    target_refs: list[ref_type('EvidenceTarget')]
    question: str
    recipient_ids: list[TextId]
    evidence_refs: list[ref_type('Evidence')]
    blocking_uses: list[ServiceUse]
    response_requirement_ref: ref_type('ResponseRequirement')


class QSProcurementDraft(StrictRecord):
    procurement_scope_ref: ref_type('ProcurementScope')
    design_refs: list[ref_type('Deliverable')]
    quantity_schedule_ref: ref_type('QuantitySchedule')
    measurement_rule_ref: ref_type('MeasurementRule')
    pricing_rule_ref: ref_type('PricingRule')
    exclusions: list[ref_type('CostScope')]
    open_questions: list[QSProcurementQuestion]
    prior_document_ref: ref_type('ProcurementDocument') | None


class QSProcurementScopeView(CostSource):
    ref: ref_type('ProcurementScope')
    task_ref: ref_type('Task')
    round_ref: ref_type('ProcurementRound')
    template_ref: ref_type('ProcurementTemplate')
    buyer_id: TextId
    buyer_organization_id: TextId
    design_refs: Annotated[list[ref_type('Deliverable')], Field(min_length=1)]
    measurement_rule_ref: ref_type('MeasurementRule')
    quantity_schedule_ref: ref_type('QuantitySchedule') | None
    pricing_rule_ref: ref_type('PricingRule')
    exclusions: list[ref_type('CostScope')]
    saved_document_ref: ref_type('ProcurementDocument') | None
    prior_document_ref: ref_type('ProcurementDocument') | None
    revision_impact_ref: ref_type('RevisionImpact') | None
    question_refs: list[ref_type('EvidenceTarget')]

    @model_validator(mode='after')
    def original_versions(self):
        unique_refs(self.design_refs); unique_refs(self.exclusions); unique_refs(self.question_refs)
        if self.saved_document_ref is not None and self.saved_document_ref == self.prior_document_ref:
            raise ValueError('Saved procurement document cannot be its own predecessor')
        return self


class QSProcurementTaskView(CostSource):
    ref: ref_type('Task')
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    procurement_scope_ref: ref_type('ProcurementScope')
    round_ref: ref_type('ProcurementRound')
    operation: Literal['compile', 'publication']
    status: Literal['authorized', 'waiting', 'withdrawn']


class QSProcurementRoundView(CostSource):
    ref: ref_type('ProcurementRound')
    procurement_scope_ref: ref_type('ProcurementScope')
    buyer_id: TextId
    buyer_organization_id: TextId
    template_ref: ref_type('ProcurementTemplate')
    status: Literal['preparation', 'open', 'closed', 'cancelled']


class QSProcurementTemplateView(CostSource):
    ref: ref_type('ProcurementTemplate')
    procurement_mode: Literal['fixed_quantity', 'provisional_quantity']
    measurement_rule_refs: list[ref_type('MeasurementRule')]
    pricing_rule_refs: list[ref_type('PricingRule')]
    allowed_uses: list[ServiceUse]


class QSProcurementDesignView(CostSource):
    ref: ref_type('Deliverable')
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    allowed_uses: list[ServiceUse]
    coverage_keys: Annotated[list[TextId], Field(min_length=1)]
    limitations: list[TextId]


class QSMeasurementRuleView(CostSource):
    ref: ref_type('MeasurementRule')
    supported_units: Annotated[list[TextId], Field(min_length=1)]
    provisional_quantities_supported: bool
    allowed_uses: list[ServiceUse]


class QSPricingRuleView(CostSource):
    ref: ref_type('PricingRule')
    round_ref: ref_type('ProcurementRound')
    design_refs: list[ref_type('Deliverable')]
    quantity_schedule_ref: ref_type('QuantitySchedule') | None
    measurement_rule_ref: ref_type('MeasurementRule')
    currency: TextId
    included_coverage_keys: list[TextId]
    excluded_scope_refs: list[ref_type('CostScope')]
    assumptions: list[TextId]
    provisional_quantities_supported: bool
    allowed_uses: list[ServiceUse]


class QSProcurementQuantityLine(StrictRecord):
    line_key: TextId
    covered_scope: ScopeRef
    design_ref: ref_type('Deliverable')
    coverage_keys: Annotated[list[TextId], Field(min_length=1)]
    quantity: ValueState[Measured]
    basis_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    provisional_question_ref: ref_type('EvidenceTarget') | None
    predecessor_line_keys: list[TextId]


class QSProcurementQuantityView(CostSource):
    ref: ref_type('QuantitySchedule')
    procurement_scope_ref: ref_type('ProcurementScope')
    round_ref: ref_type('ProcurementRound')
    design_refs: list[ref_type('Deliverable')]
    measurement_rule_ref: ref_type('MeasurementRule')
    lines: Annotated[list[QSProcurementQuantityLine], Field(min_length=1)]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['QS-A04', 'QS-A05']

    @model_validator(mode='after')
    def distinct_original_lines(self):
        unique_refs(self.design_refs)
        if len({r.line_key for r in self.lines}) != len(self.lines):
            raise ValueError('Quantity schedule repeats an original line')
        for row in self.lines:
            if row.quantity.state == 'known' and decimal_fraction(row.quantity.value.value) < 0:
                raise ValueError('Original procurement quantity cannot be negative')
            if len(set(row.coverage_keys)) != len(row.coverage_keys):
                raise ValueError('Quantity line repeats physical coverage')
        return self


class QSProcurementGapView(CostSource):
    ref: ref_type('EvidenceTarget')
    procurement_scope_ref: ref_type('ProcurementScope')
    round_ref: ref_type('ProcurementRound')
    issue: Literal['design', 'measurement', 'quantity', 'pricing', 'revision', 'publication']
    line_key: TextId | None
    question: TextId
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]
    blocking_uses: Annotated[list[ServiceUse], Field(min_length=1)]
    response_requirement_ref: ref_type('ResponseRequirement')


class QSProcurementResponseView(CostSource):
    ref: ref_type('ResponseRequirement')
    procurement_scope_ref: ref_type('ProcurementScope')
    round_ref: ref_type('ProcurementRound')
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]


class QSProcurementExclusionView(SourcedServiceProjection):
    ref: ref_type('CostScope')
    scope: ScopeRef
    coverage_keys: Annotated[list[TextId], Field(min_length=1)]


class QSProcurementPackageView(CostSource):
    ref: ref_type('ProcurementPackage')
    procurement_scope_ref: ref_type('ProcurementScope')
    round_ref: ref_type('ProcurementRound')


class QSQuantityRevision(StrictRecord):
    package_ref: ref_type('ProcurementPackage')
    previous_line_key: TextId
    current_line_keys: list[TextId]


class QSProcurementRevisionView(CostSource):
    ref: ref_type('RevisionImpact')
    procurement_scope_ref: ref_type('ProcurementScope')
    round_ref: ref_type('ProcurementRound')
    prior_document_ref: ref_type('ProcurementDocument')
    design_refs: list[ref_type('Deliverable')]
    quantity_schedule_ref: ref_type('QuantitySchedule')
    pricing_rule_ref: ref_type('PricingRule')
    changes: Annotated[list[QSQuantityRevision], Field(min_length=1)]


class QSProcurementDocumentView(CostSource):
    ref: ref_type('ProcurementDocument')
    round_ref: ref_type('ProcurementRound')
    draft: QSProcurementDraft
    status: Literal['saved', 'published', 'withdrawn']
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['QS-A05']


class QSPublicationBasisView(CostSource):
    ref: ref_type('PublicationBasis')
    procurement_scope_ref: ref_type('ProcurementScope')
    round_ref: ref_type('ProcurementRound')
    document_ref: ref_type('ProcurementDocument')
    document_digest: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    permitted: ValueState[bool]
    checker_actor_id: TextId
    checker_function_ref: ref_type('FunctionAssignment')
    checker_authority_ref: ref_type('Authorization')
    checked_at: TimePoint


class QSProcurementPublicationAuthorityView(CostSource):
    ref: ref_type('Authority')
    procurement_scope_ref: ref_type('ProcurementScope')
    round_ref: ref_type('ProcurementRound')
    document_ref: ref_type('ProcurementDocument')
    publication_basis_ref: ref_type('PublicationBasis')
    delegate_actor_id: TextId
    delegate_organization_id: TextId
    delegate_function_ref: ref_type('FunctionAssignment')
    buyer_actor_id: TextId
    buyer_organization_id: TextId
    buyer_function_ref: ref_type('FunctionAssignment')
    buyer_authority_ref: ref_type('Authorization')
    granted_at: TimePoint
    permission: ValueState[bool]


def procurement_document_digest(draft):
    import hashlib, json
    value = draft.model_dump(mode='json') if hasattr(draft, 'model_dump') else draft
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def qs_procurement_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'ProcurementScope': QSProcurementScopeView, 'Task': QSProcurementTaskView,
        'ProcurementRound': QSProcurementRoundView, 'ProcurementTemplate': QSProcurementTemplateView,
        'Deliverable': QSProcurementDesignView, 'MeasurementRule': QSMeasurementRuleView,
        'PricingRule': QSPricingRuleView, 'QuantitySchedule': QSProcurementQuantityView,
        'EvidenceTarget': QSProcurementGapView, 'ResponseRequirement': QSProcurementResponseView,
        'CostScope': QSProcurementExclusionView, 'ProcurementPackage': QSProcurementPackageView,
        'RevisionImpact': QSProcurementRevisionView, 'ProcurementDocument': QSProcurementDocumentView,
        'PublicationBasis': QSPublicationBasisView, 'Authority': QSProcurementPublicationAuthorityView,
        'ClockProfile': ServiceClockView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items(): registry.register_kind(kind, schema, str)
    return registry
