"""Authorized SUPPLIER-A02 projections, with factory/use/version applicability."""
from typing import Annotated

from pydantic import Field, model_validator

from src.actions.contracts.common import (
    ScopeRef, TextId, TimePoint, TimeWindow, ValueState, ref_type,
)
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.supplier_objects import SupplierProjection, SupplyInquiryView
from src.actions.contracts.service_objects import (
    ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView,
)
from src.methods.product import PropertyConstraint, PropertyValue


class DesignDependency(SupplierProjection):
    issue_ref: ref_type("Issue")
    check_code: TextId


class ProductRequirementView(SupplierProjection):
    ref: ref_type("Requirement")
    inquiry_ref: ref_type("SupplyInquiry")
    scope: ScopeRef
    intended_use_code: ValueState[TextId]
    allowed_factory_ids: ValueState[list[TextId]]
    constraints: ValueState[list[PropertyConstraint]]
    substitutable_property_codes: list[TextId]
    allow_product_substitution: bool
    design_dependencies: list[DesignDependency]

    @model_validator(mode="after")
    def unique_checks(self):
        if self.constraints.state == "known":
            codes = [row.property_code for row in self.constraints.value]
            if len(set(codes)) != len(codes):
                raise ValueError("Requirement property repeated")
            if not set(self.substitutable_property_codes) <= set(codes):
                raise ValueError("Substitution property must be a declared constraint")
        checks = [row.check_code for row in self.design_dependencies]
        issues = [(row.issue_ref.kind, row.issue_ref.id) for row in self.design_dependencies]
        if len(set(checks)) != len(checks) or len(set(issues)) != len(issues):
            raise ValueError("Design dependency repeated")
        return self


class ProductSpecificationView(SupplierProjection):
    ref: ref_type("ProductSpecification")
    supplier_organization_id: TextId
    product_code: ValueState[TextId]
    factory_id: ValueState[TextId]
    use_codes: ValueState[list[TextId]]
    quantity_unit: TextId
    effective_window: TimeWindow
    properties: ValueState[list[PropertyValue]]
    product_evidence_refs: list[ref_type("ProductEvidence")]
    deviation_refs: list[ref_type("SpecificationDeviation")]

    @model_validator(mode="after")
    def unique_properties(self):
        if self.properties.state == "known":
            codes = [row.property_code for row in self.properties.value]
            if len(set(codes)) != len(codes):
                raise ValueError("Specification property repeated")
        return self


class ProductEvidenceView(SupplierProjection):
    ref: ref_type("ProductEvidence")
    product_ref: ref_type("ProductSpecification")
    factory_id: TextId
    intended_use_code: TextId
    scope: ScopeRef
    property_codes: list[TextId]
    effective_window: TimeWindow
    available_at: TimePoint


class ProductDeviationView(SupplierProjection):
    ref: ref_type("SpecificationDeviation")
    inquiry_ref: ref_type("SupplyInquiry")
    requirement_ref: ref_type("Requirement")
    product_ref: ref_type("ProductSpecification")
    factory_id: TextId
    intended_use_code: TextId
    scope: ScopeRef
    property_code: TextId
    description: TextId
    effective_window: TimeWindow


class ProductIssueView(SupplierProjection):
    ref: ref_type("Issue")
    inquiry_ref: ref_type("SupplyInquiry")
    requirement_ref: ref_type("Requirement")
    scope: ScopeRef
    check_code: TextId
    description: TextId


class ProductDesignCheck(SupplierProjection):
    requirement_ref: ref_type("Requirement")
    product_ref: ref_type("ProductSpecification")
    factory_id: TextId
    intended_use_code: TextId
    check_code: TextId
    compatible: ValueState[bool]


class ProductDesignView(SupplierProjection):
    ref: ref_type("Deliverable")
    inquiry_ref: ref_type("SupplyInquiry")
    scope: ScopeRef
    author_actor_id: TextId
    author_organization_id: TextId
    author_function_ref: ref_type("FunctionAssignment")
    authorization_ref: ref_type("Authorization")
    authority_action_id: TextId
    effective_window: TimeWindow
    available_at: TimePoint
    allowed_purpose: TextId
    checks: Annotated[list[ProductDesignCheck], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_checks(self):
        keys = [(row.requirement_ref.key(), row.product_ref.key(), row.factory_id,
                 row.intended_use_code, row.check_code) for row in self.checks]
        if len(set(keys)) != len(keys):
            raise ValueError("Design check repeated")
        return self


class ProductPriority(SupplierProjection):
    product_ref: ref_type("ProductSpecification")
    priority: ValueState[int]


class ProductCompatibilityMethodView(SupplierProjection):
    ref: ref_type("ProductCompatibilityMethod")
    organization_id: TextId
    effective_window: TimeWindow
    algorithm_code: TextId
    supported_use_codes: list[TextId]
    supported_factory_ids: list[TextId]
    supported_property_codes: list[TextId]
    design_action_ids: list[TextId]
    selection_priorities: list[ProductPriority]

    @model_validator(mode="after")
    def unique_priorities(self):
        keys = [(row.product_ref.kind, row.product_ref.id) for row in self.selection_priorities]
        if len(set(keys)) != len(keys):
            raise ValueError("Product priority identity repeated across versions")
        return self


def supplier_product_schemas():
    registry = common_projection_schemas()
    # Each action uses its own strict projection for the same object kind.
    # The registry is run-local, so A01 keeps its smaller requirement schema.
    for kind, schema in (
        ("Requirement", ProductRequirementView), ("ProductSpecification", ProductSpecificationView),
        ("ProductCompatibilityMethod", ProductCompatibilityMethodView), ("ProductEvidence", ProductEvidenceView),
        ("SpecificationDeviation", ProductDeviationView), ("Issue", ProductIssueView),
        ("Deliverable", ProductDesignView), ("SupplyInquiry", SupplyInquiryView),
        ("OwnerCase", ServiceScopeCaseView), ("Organization", ServiceScopeOrganizationView),
        ("Project", ServiceScopeProjectView), ("WorkScope", ServiceWorkScopeView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
