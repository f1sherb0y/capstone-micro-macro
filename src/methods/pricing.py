"""Exact supplied-cost aggregation and explicit monetary ceiling rounding."""
from decimal import Decimal
from fractions import Fraction
import hashlib
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, EvidenceRef, Measured, Money, Reference, StrictRecord, ref_type
from src.methods.capacity import ExactAmount


PRICING_METHOD = ref_type("Method")(kind="Method", id="micro.supply.declared_cost_markup", version="1")


def decimal_fraction(value):
    return Fraction(Decimal(value))


def exact_decimal(value: Fraction) -> str:
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValueError("Quantity has no exact finite decimal representation")
    places = max(twos, fives)
    integer = value.numerator * 2 ** (places - twos) * 5 ** (places - fives)
    sign, digits = ("-" if integer < 0 else ""), str(abs(integer)).rjust(places + 1, "0")
    return sign + (digits[:-places] + "." + digits[-places:] if places else digits)


class SupplyPriceInput(StrictRecord):
    quantity: Measured
    quantity_unit: str
    unit_costs: Annotated[list[Money], Field(min_length=1)]
    fixed_costs: list[Money]
    markup_rate: DecimalString
    currency: str
    minor_places: Annotated[int, Field(ge=0, le=8)]
    policy_basis_refs: Annotated[list[EvidenceRef], Field(min_length=1)]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode="after")
    def positive_same_units(self):
        if self.quantity.unit != self.quantity_unit or Decimal(self.quantity.value) <= 0:
            raise ValueError("Positive quantity in the declared costing unit is required")
        if not self.currency.strip() or not self.quantity_unit.strip() or Decimal(self.markup_rate) < 0:
            raise ValueError("Currency, costing unit and nonnegative markup must be explicit")
        if any(row.currency != self.currency or Decimal(row.value) < 0 for row in self.unit_costs + self.fixed_costs):
            raise ValueError("Nonnegative costs must use one declared currency; no FX conversion")
        if len({ref.key() for ref in self.source_refs}) != len(self.source_refs):
            raise ValueError("Pricing source repeated")
        return self


class SupplyPriceReport(StrictRecord):
    cost: ExactAmount
    unrounded_price: ExactAmount
    rounded_price: DecimalString
    minor_places: Annotated[int, Field(ge=0, le=8)]

    @model_validator(mode="after")
    def exact_ceiling(self):
        raw, rounded = self.unrounded_price.fraction(), decimal_fraction(self.rounded_price)
        step = Fraction(1, 10 ** self.minor_places)
        if raw < self.cost.fraction() or rounded < raw or rounded - raw >= step or (rounded / step).denominator != 1:
            raise ValueError("Price must be the exact declared minor-unit ceiling of cost plus markup")
        return self


def calculate_supply_price(data):
    cost = decimal_fraction(data.quantity.value) * sum((decimal_fraction(row.value) for row in data.unit_costs), Fraction())
    cost += sum((decimal_fraction(row.value) for row in data.fixed_costs), Fraction())
    price = cost * (1 + decimal_fraction(data.markup_rate))
    scale = 10 ** data.minor_places
    scaled = price * scale
    ticks = -(-scaled.numerator // scaled.denominator)
    return SupplyPriceReport(cost=ExactAmount.from_fraction(cost), unrounded_price=ExactAmount.from_fraction(price),
                             rounded_price=exact_decimal(Fraction(ticks, scale)), minor_places=data.minor_places)


def register_pricing_method(registry):
    basis = Path(__file__).with_name("PRICING.md")
    registry.register({"method_ref": PRICING_METHOD, "namespace": "micro_local", "effect_kind": "pure_calculation",
        "invocation": "trusted_processor", "input_schema_id": "micro-supply-price.v1:input", "output_schema_id": "micro-supply-price.v1:report",
        "action_ids": ["SUPPLIER-A03"], "unit_rule": "exact_declared_units_no_conversion",
        "support_domain": ["Nonnegative sourced unit and batch-fixed costs", "One quantity unit and currency",
                           "Explicit nonnegative cost markup", "Explicit minor-unit ceiling rounding"],
        "basis_locator": "src/methods/PRICING.md", "basis_sha256": hashlib.sha256(basis.read_bytes()).hexdigest(),
        "calibration": "mathematical_only", "limitations": ["No inferred market price, tax rate, FX, production cost or logistics feasibility",
            "Pricing policy and costs are supplied facts requiring their own evidence", "No binding quote submission or resource reservation"]},
        SupplyPriceInput, SupplyPriceReport, calculate_supply_price)
