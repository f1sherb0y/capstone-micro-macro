"""Signed, sourced change arithmetic; no entitlement or payment inference."""
import hashlib
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import Measured, Money, Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.pricing import decimal_fraction, exact_decimal

CHANGE_METHOD = ref_type('Method')(kind='Method', id='micro.qs.sourced_change_valuation', version='1')


class ChangeLine(StrictRecord):
    line_key: TextId
    coverage_key: TextId
    quantity_delta: Measured
    unit_rate: Money
    rate_unit: TextId


class ChangeArithmeticInput(StrictRecord):
    currency: TextId
    decimal_places: Annotated[int, Field(ge=0, le=8)]
    basis: Literal['incremental', 'cumulative']
    lines: Annotated[list[ChangeLine], Field(min_length=1)]
    prior_amounts: list[Money]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def domain(self):
        unique_refs(self.source_refs)
        if len({r.line_key for r in self.lines}) != len(self.lines) or len({r.coverage_key for r in self.lines}) != len(self.lines):
            raise ValueError('Change lines repeat original identity or physical coverage')
        if self.basis == 'incremental' and self.prior_amounts:
            raise ValueError('Incremental change cannot subtract prior cumulative statements')
        for row in self.lines:
            if row.quantity_delta.unit != row.rate_unit or row.unit_rate.currency != self.currency:
                raise ValueError('Change arithmetic requires exact units and currency')
            if decimal_fraction(row.unit_rate.value) < 0:
                raise ValueError('Use signed quantity differences with nonnegative original rates')
        if any(row.currency != self.currency for row in self.prior_amounts):
            raise ValueError('Prior changes require the same currency')
        return self


class ChangeArithmeticReport(StrictRecord):
    assessed_amount: Money
    period_delta: Money


def calculate_change(data):
    total = sum((decimal_fraction(r.quantity_delta.value) * decimal_fraction(r.unit_rate.value) for r in data.lines), Fraction())
    scaled = total * 10 ** data.decimal_places
    integer, remainder = divmod(scaled.numerator, scaled.denominator)
    if remainder * 2 > scaled.denominator or (remainder * 2 == scaled.denominator and integer % 2):
        integer += 1
    rounded = Fraction(integer, 10 ** data.decimal_places)
    prior = sum((decimal_fraction(r.value) for r in data.prior_amounts), Fraction())
    basis = data.lines[0].quantity_delta.basis_ref
    return ChangeArithmeticReport(
        assessed_amount=Money(value=exact_decimal(rounded), currency=data.currency, basis_ref=basis),
        period_delta=Money(value=exact_decimal(rounded - prior), currency=data.currency, basis_ref=basis))


def register_qs_change_method(registry):
    basis = Path(__file__).with_name('QS_CHANGE.md')
    registry.register({'method_ref': CHANGE_METHOD, 'namespace': 'micro_local', 'effect_kind': 'pure_calculation',
        'invocation': 'trusted_processor', 'input_schema_id': 'micro-qs-change.v1:input', 'output_schema_id': 'micro-qs-change.v1:report',
        'action_ids': ['QS-A07', 'CONTRACTOR-A09'], 'unit_rule': 'exact_declared_units_no_conversion',
        'support_domain': ['Sourced signed quantity differences times nonnegative rates', 'Disjoint physical coverage',
            'One currency with explicit precision and half-even total rounding', 'Cumulative current-period difference from complete prior incremental amounts'],
        'basis_locator': 'src/methods/QS_CHANGE.md', 'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration': 'mathematical_only', 'limitations': ['No entitlement, payer, delay model, FX, tax or work suspension inference',
            'Original measured differences, rates, prior statement completeness and authority require independent host records']},
        ChangeArithmeticInput, ChangeArithmeticReport, calculate_change)
