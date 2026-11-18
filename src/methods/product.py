"""Exact comparison of declared product properties, without engineering approval."""
from decimal import Decimal
from fractions import Fraction
import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import (
    DecimalString, EvidenceRef, Reference, StrictRecord, TextId, ref_type,
)


PRODUCT_METHOD = ref_type("Method")(kind="Method", id="micro.product.declared_constraints", version="1")


class CategoryConstraint(StrictRecord):
    kind: Literal["category"]
    property_code: TextId
    allowed_values: Annotated[list[TextId], Field(min_length=1)]
    basis_refs: Annotated[list[EvidenceRef], Field(min_length=1)]


class RangeConstraint(StrictRecord):
    kind: Literal["range"]
    property_code: TextId
    unit: TextId
    minimum: DecimalString | None
    maximum: DecimalString | None
    basis_refs: Annotated[list[EvidenceRef], Field(min_length=1)]

    @model_validator(mode="after")
    def bounded(self):
        if self.minimum is None and self.maximum is None:
            raise ValueError("A range needs an explicit bound")
        if self.minimum is not None and self.maximum is not None and Decimal(self.minimum) > Decimal(self.maximum):
            raise ValueError("Minimum exceeds maximum")
        return self


PropertyConstraint = Annotated[CategoryConstraint | RangeConstraint, Field(discriminator="kind")]


class CategoryValue(StrictRecord):
    kind: Literal["category"]
    property_code: TextId
    value: TextId
    basis_refs: Annotated[list[EvidenceRef], Field(min_length=1)]


class NumericValue(StrictRecord):
    kind: Literal["range"]
    property_code: TextId
    unit: TextId
    value: DecimalString
    basis_refs: Annotated[list[EvidenceRef], Field(min_length=1)]


PropertyValue = Annotated[CategoryValue | NumericValue, Field(discriminator="kind")]


class ProductComparisonInput(StrictRecord):
    constraints: Annotated[list[PropertyConstraint], Field(min_length=1)]
    properties: Annotated[list[PropertyValue], Field(min_length=1)]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode="after")
    def supported(self):
        for rows in (self.constraints, self.properties):
            codes = [row.property_code for row in rows]
            if len(set(codes)) != len(codes):
                raise ValueError("Product property code repeated")
        if len({ref.key() for ref in self.source_refs}) != len(self.source_refs):
            raise ValueError("Product comparison source repeated")
        values = {row.property_code: row for row in self.properties}
        for constraint in self.constraints:
            value = values.get(constraint.property_code)
            if value is None or value.kind != constraint.kind:
                raise ValueError("Every constraint needs the same declared property type")
            if value.kind == "range" and value.unit != constraint.unit:
                raise ValueError("Product method does not convert units")
        return self


class PropertyCheck(StrictRecord):
    property_code: TextId
    matches: bool
    constraint: PropertyConstraint
    actual: PropertyValue


class ProductComparisonReport(StrictRecord):
    matches: bool
    checks: Annotated[list[PropertyCheck], Field(min_length=1)]

    @model_validator(mode="after")
    def consistent(self):
        if self.matches != all(check.matches for check in self.checks):
            raise ValueError("Product conclusion differs from property evidence")
        return self


def compare_product(data: ProductComparisonInput) -> ProductComparisonReport:
    values = {row.property_code: row for row in data.properties}
    checks = []
    for constraint in data.constraints:
        actual = values[constraint.property_code]
        if constraint.kind == "category":
            matches = actual.value in constraint.allowed_values
        else:
            value = Fraction(Decimal(actual.value))
            matches = ((constraint.minimum is None or value >= Fraction(Decimal(constraint.minimum)))
                       and (constraint.maximum is None or value <= Fraction(Decimal(constraint.maximum))))
        checks.append(PropertyCheck(property_code=constraint.property_code, matches=matches,
                                    constraint=constraint, actual=actual))
    return ProductComparisonReport(matches=all(row.matches for row in checks), checks=checks)


def register_product_method(registry):
    basis = Path(__file__).with_name("PRODUCT.md")
    registry.register({"method_ref": PRODUCT_METHOD, "namespace": "micro_local", "effect_kind": "pure_calculation",
        "invocation": "trusted_processor", "input_schema_id": "micro-product.v1:input",
        "output_schema_id": "micro-product.v1:report", "action_ids": ["SUPPLIER-A02"],
        "support_domain": ["Explicit categorical sets", "Inclusive exact decimal bounds", "Identical declared units"],
        "unit_rule": "exact_declared_units_no_conversion", "basis_locator": "src/methods/PRODUCT.md",
        "basis_sha256": hashlib.sha256(basis.read_bytes()).hexdigest(), "calibration": "mathematical_only",
        "limitations": ["No inferred properties, standards, structural analysis or unit conversions",
            "Comparing supplied facts does not establish real test validity or professional compatibility",
            "No design, substitution, production or installation approval"]},
        ProductComparisonInput, ProductComparisonReport, compare_product)
