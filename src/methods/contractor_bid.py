"""Exact declared quantity/rate pricing, separate from internal cost subtotal."""
import hashlib
from fractions import Fraction
from pathlib import Path

from pydantic import model_validator

from src.actions.contracts.common import DecimalString, Measured, Money, Reference, StrictRecord, TextId, ref_type
from src.methods.pricing import decimal_fraction, exact_decimal

CONTRACTOR_BID_METHOD = ref_type('Method')(kind='Method', id='micro.contractor.declared_bid_price', version='1')


class ContractorPriceLine(StrictRecord):
    coverage_keys: list[TextId]
    quantity: Measured
    unit_rate: Money
    quantity_unit: TextId


class ContractorPriceInput(StrictRecord):
    lines: list[ContractorPriceLine]
    markup_fraction: DecimalString
    markup_basis_ref: ref_type('Evidence')
    allowance: Money
    source_refs: list[Reference]

    @model_validator(mode='after')
    def sourced_domain(self):
        if not self.lines or not self.source_refs: raise ValueError('Pricing requires original lines and sources')
        seen = set()
        for row in self.lines:
            if not row.coverage_keys or len(set(row.coverage_keys)) != len(row.coverage_keys) or seen.intersection(row.coverage_keys):
                raise ValueError('Pricing repeats original physical cost coverage')
            seen.update(row.coverage_keys)
            if row.quantity.unit != row.quantity_unit or row.unit_rate.currency != self.allowance.currency:
                raise ValueError('Pricing does not infer quantity/currency conversion')
            if decimal_fraction(row.quantity.value) <= 0 or decimal_fraction(row.unit_rate.value) < 0:
                raise ValueError('Pricing requires positive quantities and nonnegative original rates')
        if decimal_fraction(self.markup_fraction) <= -1 or decimal_fraction(self.allowance.value) < 0:
            raise ValueError('Commercial factor or declared allowance is invalid')
        return self


class ContractorPriceReport(StrictRecord):
    internal_cost_subtotal: Money
    offered_price: Money


def price_bid(data):
    subtotal = sum((decimal_fraction(row.quantity.value) * decimal_fraction(row.unit_rate.value) for row in data.lines), Fraction())
    price = subtotal * (1 + decimal_fraction(data.markup_fraction)) + decimal_fraction(data.allowance.value)
    if price <= 0: raise ValueError('A bid must have a positive priced amount')
    return ContractorPriceReport(internal_cost_subtotal=Money(value=exact_decimal(subtotal), currency=data.allowance.currency,
        basis_ref=data.markup_basis_ref), offered_price=Money(value=exact_decimal(price), currency=data.allowance.currency,
        basis_ref=data.markup_basis_ref))


def register_contractor_bid_method(registry):
    basis = Path(__file__).with_name('CONTRACTOR_BID.md')
    registry.register({'method_ref': CONTRACTOR_BID_METHOD, 'namespace': 'micro_local', 'effect_kind': 'pure_calculation',
        'invocation': 'trusted_processor', 'input_schema_id': CONTRACTOR_BID_METHOD.id + ':input',
        'output_schema_id': CONTRACTOR_BID_METHOD.id + ':report', 'action_ids': ['CONTRACTOR-A02', 'CONTRACTOR-A03'],
        'support_domain': ['Disjoint original known quantities/rates and exact units/currency',
            'Explicit original commercial factor and fixed allowance; positive offered total'],
        'unit_rule': 'exact_declared_units_no_conversion', 'basis_locator': 'src/methods/CONTRACTOR_BID.md',
        'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(), 'calibration': 'mathematical_only',
        'limitations': ['No guessed productivity, prices, FX, technical compatibility or omitted cost components',
            'Internal cost prediction and offered commercial amount remain separate',
            'No task execution, permanent crew locking, award, safety release, contract or cash effect']},
        ContractorPriceInput, ContractorPriceReport, price_bid)
