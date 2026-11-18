"""Declared indicative supply ranges, with explicit uncertainty and time ticks."""
import hashlib
from pathlib import Path

from pydantic import model_validator

from src.actions.contracts.common import Measured, Money, Reference, StrictRecord, TextId, ValueState, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.pricing import decimal_fraction, exact_decimal

SUPPLIER_ADVICE_METHOD = ref_type('Method')(kind='Method', id='micro.supplier.declared_advice_estimates', version='1')


class SupplierAdviceEstimateInput(StrictRecord):
    quantity_lower: ValueState[Measured]
    quantity_upper: ValueState[Measured]
    unit_price_lower: ValueState[Money]
    unit_price_upper: ValueState[Money]
    fixed_price_lower: ValueState[Money]
    fixed_price_upper: ValueState[Money]
    effective_throughput: ValueState[Measured]
    throughput_quantity_unit: TextId
    duration_unit: TextId
    duration_tick: Measured
    result_basis_ref: ref_type('Evidence')
    source_refs: list[Reference]

    @model_validator(mode='after')
    def exact_domain(self):
        if not self.source_refs: raise ValueError('Supply estimate needs original declared sources')
        unique_refs(self.source_refs)
        for lower, upper in ((self.quantity_lower, self.quantity_upper), (self.unit_price_lower, self.unit_price_upper),
                             (self.fixed_price_lower, self.fixed_price_upper)):
            for bound in (lower, upper):
                if bound.state == 'known' and decimal_fraction(bound.value.value) < 0:
                    raise ValueError('Indicative quantity/price bounds cannot be negative')
            if lower.state == upper.state == 'known':
                if decimal_fraction(lower.value.value) > decimal_fraction(upper.value.value): raise ValueError('Original indicative bounds are inverted')
                if getattr(lower.value, 'unit', getattr(lower.value, 'currency', None)) != getattr(upper.value, 'unit', getattr(upper.value, 'currency', None)):
                    raise ValueError('Original indicative bounds mix units/currencies')
        currencies = {bound.value.currency for bound in (self.unit_price_lower, self.unit_price_upper,
            self.fixed_price_lower, self.fixed_price_upper) if bound.state == 'known'}
        if len(currencies) > 1: raise ValueError('Indicative price cannot infer currency conversion')
        for bound in (self.quantity_lower, self.quantity_upper):
            if bound.state == 'known' and bound.value.unit != self.throughput_quantity_unit:
                raise ValueError('Estimate quantity differs from the declared rate denominator')
        if self.duration_tick.unit != self.duration_unit or decimal_fraction(self.duration_tick.value) <= 0:
            raise ValueError('Manufacturing estimate needs an explicit positive time quantum')
        if self.effective_throughput.state == 'known' and (self.effective_throughput.value.unit != self.throughput_quantity_unit
                or decimal_fraction(self.effective_throughput.value.value) <= 0):
            raise ValueError('Declared throughput must be positive in the original quantity unit per declared time unit')
        return self


class SupplierAdviceEstimateReport(StrictRecord):
    quantity_lower: ValueState[Measured]
    quantity_upper: ValueState[Measured]
    price_lower: ValueState[Money]
    price_upper: ValueState[Money]
    manufacturing_duration: ValueState[Measured]


def unresolved(states):
    for kind in ('not_supported', 'not_applicable'):
        for state in states:
            if state.state == kind: return state
    missing = {ref.key(): ref for state in states if state.state == 'unknown' for ref in state.missing_refs}
    if any(state.state == 'unknown' for state in states):
        return {'state': 'unknown', 'reason_code': 'original_supply_estimate_input_unknown', 'missing_refs': list(missing.values())}
    return None


def estimate_supply(data):
    prices = []
    for quantity, rate, fixed in ((data.quantity_lower, data.unit_price_lower, data.fixed_price_lower),
                                  (data.quantity_upper, data.unit_price_upper, data.fixed_price_upper)):
        gap = unresolved((quantity, rate, fixed))
        prices.append(gap if gap is not None else {'state': 'known', 'value': Money(value=exact_decimal(
            decimal_fraction(quantity.value.value) * decimal_fraction(rate.value.value) + decimal_fraction(fixed.value.value)),
            currency=rate.value.currency, basis_ref=data.result_basis_ref)})
    duration = unresolved((data.quantity_upper, data.effective_throughput))
    if duration is None:
        ticks = decimal_fraction(data.quantity_upper.value.value) / decimal_fraction(data.effective_throughput.value.value) / decimal_fraction(data.duration_tick.value)
        rounded = (ticks.numerator + ticks.denominator - 1) // ticks.denominator
        duration = {'state': 'known', 'value': Measured(value=exact_decimal(rounded * decimal_fraction(data.duration_tick.value)),
                    unit=data.duration_unit, basis_ref=data.result_basis_ref)}
    return SupplierAdviceEstimateReport(quantity_lower=data.quantity_lower, quantity_upper=data.quantity_upper,
        price_lower=prices[0], price_upper=prices[1], manufacturing_duration=duration)


def register_supplier_advice_method(registry):
    basis = Path(__file__).with_name('SUPPLIER_ADVICE.md')
    registry.register({'method_ref': SUPPLIER_ADVICE_METHOD, 'namespace': 'micro_local', 'effect_kind': 'pure_calculation',
        'invocation': 'trusted_processor', 'input_schema_id': SUPPLIER_ADVICE_METHOD.id + ':input',
        'output_schema_id': SUPPLIER_ADVICE_METHOD.id + ':report', 'action_ids': ['SUPPLIER-A13'],
        'support_domain': ['Original nonnegative quantity/unit-price/fixed-price bounds in one currency and exact quantity unit',
            'Declared positive effective throughput per declared time unit; upper-quantity time rounded upward to original time quantum',
            'Unknown, not applicable and not supported states stay explicit'],
        'unit_rule': 'exact_declared_units_no_conversion', 'basis_locator': 'src/methods/SUPPLIER_ADVICE.md',
        'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(), 'calibration': 'mathematical_only',
        'limitations': ['Declared quantities, throughput, prices and assumptions are not independently forecast/calibrated',
            'No competing customer schedules, shared capacity, inventory, site receiving or installation inferred',
            'No order, reservation, binding quote, superiority score or actual delivery commitment']},
        SupplierAdviceEstimateInput, SupplierAdviceEstimateReport, estimate_supply)
