"""Original procurement inputs and bounded contractor pricing/programme proposals."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import DecimalString, Measured, Money, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.contractor_objects import QualificationView
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView
from src.methods.capacity import CapacityResource, CapacityCommitment


class ContractorBidAllocation(StrictRecord):
    resource_ref: ref_type('ResourcePool')
    task_scope_ref: ScopeRef
    window_ref: ref_type('TimeWindow')
    quantity: Measured


class ContractorBidTask(StrictRecord):
    local_key: TextId
    scope_ref: ScopeRef
    work_method_ref: ref_type('WorkMethod')
    target_quantities: list[Measured]
    dependency_refs: list[ref_type('Dependency')]
    allocations: list[ContractorBidAllocation]
    window_ref: ref_type('TimeWindow')


class ContractorBidPackageView(CostSource):
    ref: ref_type('ProcurementPackage')
    round_ref: ref_type('TenderRound')
    recipient_organization_ids: list[TextId]
    status: Literal['open', 'closed', 'superseded']
    submission_window_ref: ref_type('TimeWindow')
    region_id: TextId
    object_type: TextId
    work_type: TextId
    special_condition_codes: list[TextId]
    coverage_keys: Annotated[list[TextId], Field(min_length=1)]
    deliverable_refs: list[ref_type('ReleasedDeliverable')]
    quantity_refs: list[ref_type('QuantityBasis')]
    required_qualification_codes: list[TextId]
    permitted_maturities: list[Literal['performance_requirement', 'tender_design', 'construction_release']]
    allowed_method_refs: list[ref_type('WorkMethod')]
    allowed_exclusion_refs: list[ref_type('Requirement')]
    allow_limited_bid: bool


class ContractorBidDeliverableView(CostSource):
    ref: ref_type('ReleasedDeliverable')
    package_ref: ref_type('ProcurementPackage')
    allowed_uses: list[TextId]
    maturity: Literal['performance_requirement', 'tender_design', 'construction_release']
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['ARCHITECT-A07', 'ENGINEER-A07', 'QS-A05']


class ContractorBidQuantityLine(StrictRecord):
    local_key: TextId
    coverage_keys: Annotated[list[TextId], Field(min_length=1)]
    quantity: ValueState[Measured]


class ContractorBidQuantityView(CostSource):
    ref: ref_type('QuantityBasis')
    package_ref: ref_type('ProcurementPackage')
    deliverable_refs: list[ref_type('ReleasedDeliverable')]
    lines: list[ContractorBidQuantityLine]
    measurement_rule_ref: ref_type('MeasurementRule')
    status: Literal['ok', 'failed', 'unsupported']


class ContractorBidCostView(CostSource):
    ref: ref_type('CostBasis')
    organization_id: TextId
    package_ref: ref_type('ProcurementPackage')
    quantity_basis_ref: ref_type('QuantityBasis')
    quantity_line_key: TextId
    unit_rate: ValueState[Money]
    quantity_unit: TextId
    region_id: TextId
    coverage_keys: list[TextId]
    method_ref: ref_type('Method')
    status: Literal['ok', 'failed', 'unsupported']
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')


class ContractorBidQuantityTarget(StrictRecord):
    quantity_basis_ref: ref_type('QuantityBasis')
    quantity_line_key: TextId


class ContractorBidPlannedTask(ContractorBidTask):
    quantity_sources: list[ContractorBidQuantityTarget]


class ContractorBidProgrammeView(CostSource):
    ref: ref_type('ProgrammeProposal')
    organization_id: TextId
    package_ref: ref_type('ProcurementPackage')
    quantity_refs: list[ref_type('QuantityBasis')]
    tasks: list[ContractorBidPlannedTask]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')


class ContractorBidMethodView(CostSource):
    ref: ref_type('WorkMethod')
    region_ids: list[TextId]
    object_types: list[TextId]
    work_types: list[TextId]
    special_condition_codes: list[TextId]
    quantity_unit: TextId
    capacity_unit: TextId
    resource_kind: TextId
    quantity_per_capacity_tick: ValueState[DecimalString]
    productivity_basis_ref: ref_type('Evidence')
    output_quantity_basis_refs: list[ref_type('QuantityBasis')]


class ContractorBidCapacityView(CostSource):
    ref: ref_type('ContractorCapacity')
    organization_id: TextId
    as_of: TimePoint
    coverage: Literal['complete', 'partial', 'unknown']
    resources: list[CapacityResource]
    commitments: list[CapacityCommitment]
    qualification_refs: list[ref_type('Qualification')]
    qualification_coverage: Literal['complete', 'partial', 'unknown']


class ContractorBidProfileView(CostSource):
    ref: ref_type('ContractorPricingProfile')
    organization_id: TextId
    package_ref: ref_type('ProcurementPackage')
    authority_ref: ref_type('Authorization')
    choice: Literal['submit_bid', 'decline_bid']
    currency: TextId
    markup_fraction: DecimalString
    markup_basis_ref: ref_type('Evidence')
    commercial_allowance: Money
    programme_ref: ref_type('ProgrammeProposal')
    terms_ref: ref_type('ContractTerms')
    validity_ref: ref_type('TimeWindow')
    exclusion_refs: list[ref_type('Requirement')]
    decline_reason: TextId


class ContractorBidReferenceView(CostSource):
    ref: Reference
    package_ref: ref_type('ProcurementPackage')
    organization_id: TextId | None
    allowed: ValueState[bool]
    excluded_coverage_keys: list[TextId] = Field(default_factory=list)


class ContractorBidResourceView(CostSource):
    ref: ref_type('ResourcePool')
    organization_id: TextId
    resource_kind: TextId
    region_id: TextId
    total: Measured


class ContractorBidCommitmentView(CostSource):
    ref: ref_type('ResourceCommitment')
    organization_id: TextId
    resource_ref: ref_type('ResourcePool')
    quantity: Measured
    window: TimeWindow


def contractor_bid_schemas(overrides=None):
    registry = common_projection_schemas()
    schemas = {
        'ProcurementPackage': ContractorBidPackageView, 'ReleasedDeliverable': ContractorBidDeliverableView,
        'QuantityBasis': ContractorBidQuantityView, 'CostBasis': ContractorBidCostView,
        'ContractorCapacity': ContractorBidCapacityView, 'ContractorPricingProfile': ContractorBidProfileView,
        'ProgrammeProposal': ContractorBidProgrammeView, 'WorkMethod': ContractorBidMethodView,
        'Qualification': QualificationView, 'ClockProfile': ServiceClockView,
        'ResourcePool': ContractorBidResourceView, 'ResourceCommitment': ContractorBidCommitmentView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }
    for kind in ('Requirement', 'Dependency', 'ContractTerms', 'Method', 'MeasurementRule', 'TenderRound'):
        schemas[kind] = ContractorBidReferenceView
    schemas.update(overrides or {})
    for kind, schema in schemas.items(): registry.register_kind(kind, schema, str)
    return registry
