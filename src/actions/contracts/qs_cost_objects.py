"""Original QS cost inputs and saved calculations; no budget or payment effects."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import (
    DecimalString, Measured, Money, ScopeRef, StrictRecord, TextId,
    TimePoint, TimeWindow, ValueState, ref_type,
)
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import (
    SourcedServiceProjection, ServiceUse, ServiceClockView,
    ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView,
)


class CostSource(SourcedServiceProjection):
    scope: ScopeRef
    available_at: TimePoint
    effective_window: TimeWindow


class QSCostBriefView(CostSource):
    ref: ref_type('Brief')
    allowed_uses: list[ServiceUse]
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]


class QSCostOptionView(CostSource):
    ref: ref_type('DesignOption')
    brief_ref: ref_type('Brief')
    allowed_uses: list[ServiceUse]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    limitations: list[TextId]


class QSCostTaskView(CostSource):
    ref: ref_type('Task')
    organization_id: TextId
    function_ref: ref_type('FunctionAssignment')
    authority_ref: ref_type('Authorization')
    brief_ref: ref_type('Brief')
    option_ref: ref_type('DesignOption')
    cost_scope_ref: ref_type('CostScope')
    comparison_basis_ref: ref_type('ComparisonBasis')
    allowed_uses: list[ServiceUse]
    status: Literal['authorized', 'waiting', 'withdrawn']
    delivery_mode: Literal['request_inputs', 'limited_report']


class QSCostItem(StrictRecord):
    line_key: TextId
    covered_scope: ScopeRef
    cost_component_ref: ref_type('CostComponent')
    coverage_keys: Annotated[list[TextId], Field(min_length=1)]
    quantity_basis_ref: ref_type('QuantityBasis') | None
    price_ref: ref_type('Price') | None
    quantity_question_ref: ref_type('EvidenceTarget')
    price_question_ref: ref_type('EvidenceTarget')
    coverage_question_ref: ref_type('EvidenceTarget')
    predecessor_line_keys: list[TextId]

    @model_validator(mode='after')
    def unique_coverage(self):
        if len(set(self.coverage_keys)) != len(self.coverage_keys):
            raise ValueError('A cost line repeats an original physical coverage key')
        if len(set(self.predecessor_line_keys)) != len(self.predecessor_line_keys):
            raise ValueError('Cost predecessors repeated')
        return self


class QSCostScopeView(CostSource):
    ref: ref_type('CostScope')
    option_ref: ref_type('DesignOption')
    items: Annotated[list[QSCostItem], Field(min_length=1)]
    exclusions: list[TextId]

    @model_validator(mode='after')
    def unique_lines(self):
        if len({r.line_key for r in self.items}) != len(self.items):
            raise ValueError('Cost scope repeats a local line identity')
        return self


class QSCostComparisonBasisView(CostSource):
    ref: ref_type('ComparisonBasis')
    currency: TextId
    region_id: TextId
    delivery_code: TextId
    pricing_time: TimePoint


class QSCostComponentView(SourcedServiceProjection):
    ref: ref_type('CostComponent')
    scope: ScopeRef
    coverage_keys: Annotated[list[TextId], Field(min_length=1)]


class QSQuantityBasisView(CostSource):
    ref: ref_type('QuantityBasis')
    option_ref: ref_type('DesignOption')
    line_key: TextId
    cost_component_ref: ref_type('CostComponent')
    quantity: ValueState[Measured]
    measurement_rule_code: TextId
    mode: Literal['measured', 'proxy']
    quantity_schedule_ref: ref_type('QuantitySchedule') | None
    proxy_method_ref: ref_type('Method') | None
    limitations: list[TextId]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId

    @model_validator(mode='after')
    def declared_method(self):
        if self.mode == 'proxy' and (self.proxy_method_ref is None or not self.limitations):
            raise ValueError('Proxy quantity must declare original method and limitations')
        if self.mode == 'measured' and self.proxy_method_ref is not None:
            raise ValueError('Measured quantity cannot silently become a proxy')
        return self


class QSQuantityScheduleView(CostSource):
    ref: ref_type('QuantitySchedule')
    option_ref: ref_type('DesignOption')
    quantity_basis_refs: list[ref_type('QuantityBasis')]


class QSCostPriceView(CostSource):
    ref: ref_type('Price')
    cost_component_ref: ref_type('CostComponent')
    coverage_keys: Annotated[list[TextId], Field(min_length=1)]
    unit_rate: ValueState[Money]
    quantity_unit: TextId
    measurement_rule_code: TextId
    region_id: TextId
    delivery_code: TextId
    valid_pricing_window: TimeWindow
    source_locator: TextId
    excluded_coverage_keys: list[TextId]


class QSCostQuestionView(CostSource):
    ref: ref_type('EvidenceTarget')
    task_ref: ref_type('Task')
    line_key: TextId
    issue: Literal['quantity', 'price', 'coverage']
    question: TextId
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]
    blocking_uses: Annotated[list[ServiceUse], Field(min_length=1)]
    response_requirement_ref: ref_type('ResponseRequirement')


class QSCostResponseRequirementView(CostSource):
    ref: ref_type('ResponseRequirement')
    task_ref: ref_type('Task')
    recipient_ids: Annotated[list[TextId], Field(min_length=1)]


class QSCostMethodView(SourcedServiceProjection):
    ref: ref_type('Method')
    permitted_uses: list[ServiceUse]
    limitations: Annotated[list[TextId], Field(min_length=1)]


class QSCostSavedLine(StrictRecord):
    line_key: TextId
    quantity: ValueState[Measured]
    amount: ValueState[Money]
    basis_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]


class QSCostCalculationView(CostSource):
    ref: ref_type('MethodResult')
    method_ref: ref_type('Method')
    task_ref: ref_type('Task')
    brief_ref: ref_type('Brief')
    option_ref: ref_type('DesignOption')
    cost_scope_ref: ref_type('CostScope')
    comparison_basis_ref: ref_type('ComparisonBasis')
    quantity_basis_refs: list[ref_type('QuantityBasis')]
    price_refs: list[ref_type('Price')]
    quantity_schedule_ref: ref_type('QuantitySchedule') | None
    status: Literal['ok', 'failed', 'unsupported']
    lines: list[QSCostSavedLine]
    known_subtotal: ValueState[Money]
    complete_total: Money | None
    calculated_at: TimePoint
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['QS-A04']

    @model_validator(mode='after')
    def original_inputs(self):
        unique_refs(self.quantity_basis_refs); unique_refs(self.price_refs)
        if len({r.line_key for r in self.lines}) != len(self.lines):
            raise ValueError('Saved calculation repeats a cost line')
        if self.status != 'ok' and (self.lines or self.complete_total is not None or self.known_subtotal.state == 'known'):
            raise ValueError('Unsuccessful calculation cannot claim computed amounts')
        return self


def qs_cost_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'Brief': QSCostBriefView, 'DesignOption': QSCostOptionView,
        'Task': QSCostTaskView, 'CostScope': QSCostScopeView,
        'ComparisonBasis': QSCostComparisonBasisView, 'CostComponent': QSCostComponentView,
        'QuantityBasis': QSQuantityBasisView, 'QuantitySchedule': QSQuantityScheduleView,
        'Price': QSCostPriceView, 'MethodResult': QSCostCalculationView,
        'EvidenceTarget': QSCostQuestionView, 'ResponseRequirement': QSCostResponseRequirementView,
        'Method': QSCostMethodView, 'ClockProfile': ServiceClockView,
        'OwnerCase': ServiceScopeCaseView, 'Project': ServiceScopeProjectView,
        'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    return registry
