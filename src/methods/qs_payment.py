"""Exact original work valuation and separately traced credits/cash."""
import hashlib
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, Measured, Money, Reference, StrictRecord, TextId, ValueState, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.pricing import decimal_fraction, exact_decimal
from src.methods.qs_cost import unknown

PAYMENT_METHOD = ref_type('Method')(kind='Method', id='micro.qs.sourced_payment_valuation', version='1')


class PaymentWorkLine(StrictRecord):
    work_key: TextId
    quantity: Measured
    rate: Money
    rate_unit: TextId
    eligible: ValueState[bool]


class PaymentValuationInput(StrictRecord):
    currency: TextId
    decimal_places: Annotated[int, Field(ge=0, le=8)]
    basis: Literal['incremental', 'cumulative']
    lines: Annotated[list[PaymentWorkLine], Field(min_length=1)]
    retention_fraction: DecimalString
    retention_cap: Money | None
    deductions: list[Money]
    advance_offsets: list[Money]
    prior_assessed: list[Money]
    prior_net: list[Money]
    prior_retention: list[Money]
    corrected_assessed: Money | None
    corrected_net: Money | None
    corrected_retention: Money | None
    paid_total: ValueState[Money]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def domain(self):
        unique_refs(self.source_refs)
        if len({r.work_key for r in self.lines}) != len(self.lines):
            raise ValueError('Payment valuation repeats original physical work')
        if not 0 <= decimal_fraction(self.retention_fraction) <= 1:
            raise ValueError('Retention fraction must be in [0,1]')
        amounts = self.deductions + self.advance_offsets
        amounts += [r for r in (self.retention_cap, self.corrected_assessed, self.corrected_net, self.corrected_retention) if r is not None]
        if self.paid_total.state == 'known':
            amounts.append(self.paid_total.value)
        for row in self.lines:
            if (row.quantity.unit != row.rate_unit or row.rate.currency != self.currency
                    or decimal_fraction(row.quantity.value) < 0 or decimal_fraction(row.rate.value) < 0):
                raise ValueError('Payment quantity/rate requires nonnegative exact units and currency')
        if any(r.currency != self.currency or decimal_fraction(r.value) < 0 for r in amounts):
            raise ValueError('Payment history and adjustments require nonnegative same-currency amounts')
        if len(self.prior_assessed) != len(self.prior_net) or len(self.prior_assessed) != len(self.prior_retention):
            raise ValueError('Prior assessed/net history must correspond one-to-one')
        if any(r.currency != self.currency for r in self.prior_assessed + self.prior_net + self.prior_retention):
            raise ValueError('Prior signed certificate contributions require the same currency')
        if any(sum((decimal_fraction(r.value) for r in rows), Fraction()) < 0 for rows in (self.prior_assessed, self.prior_net, self.prior_retention)):
            raise ValueError('Prior effective contract totals cannot be negative')
        if (self.corrected_assessed is None) != (self.corrected_net is None):
            raise ValueError('Correction requires both original assessed and net amounts')
        if (self.corrected_assessed is None) != (self.corrected_retention is None):
            raise ValueError('Correction must preserve the original retained amount')
        return self


class PaymentValuationReport(StrictRecord):
    assessed_amount: Money
    recognized_amount: ValueState[Money]
    disputed_amount: ValueState[Money]
    retention_amount: ValueState[Money]
    retention_period_delta: ValueState[Money]
    deduction_amount: Money
    advance_offset_amount: Money
    assessed_period_delta: Money
    net_amount: ValueState[Money]
    net_period_delta: ValueState[Money]
    cumulative_net: ValueState[Money]
    paid_total: ValueState[Money]
    unsettled_amount: ValueState[Money]
    overpayment: ValueState[Money]


def calculate_payment(data):
    basis = data.lines[0].quantity.basis_ref

    def rounded(value):
        scaled = value * 10 ** data.decimal_places
        integer, remainder = divmod(scaled.numerator, scaled.denominator)
        if remainder * 2 > scaled.denominator or (remainder * 2 == scaled.denominator and integer % 2):
            integer += 1
        return Fraction(integer, 10 ** data.decimal_places)

    def money(value):
        return Money(value=exact_decimal(value), currency=data.currency, basis_ref=basis)

    def known(value):
        return {'state': 'known', 'value': money(value)}

    def total(rows):
        return sum((decimal_fraction(r.value) for r in rows), Fraction())

    raw = [decimal_fraction(r.quantity.value) * decimal_fraction(r.rate.value) for r in data.lines]
    assessed = rounded(sum(raw, Fraction()))
    prior_assessed, prior_net, prior_retention = total(data.prior_assessed), total(data.prior_net), total(data.prior_retention)
    previous = prior_assessed if data.basis == 'cumulative' else (
        decimal_fraction(data.corrected_assessed.value) if data.corrected_assessed is not None else Fraction())
    deductions, advances = total(data.deductions), total(data.advance_offsets)
    report = {'assessed_amount': money(assessed), 'assessed_period_delta': money(assessed - previous),
        'deduction_amount': money(deductions), 'advance_offset_amount': money(advances), 'paid_total': data.paid_total}
    for field in ('recognized_amount', 'disputed_amount', 'retention_amount', 'retention_period_delta', 'net_amount', 'net_period_delta',
                  'cumulative_net', 'unsettled_amount', 'overpayment'):
        report[field] = unknown('payment_entitlement_or_condition_unknown')
    if all(r.eligible.state == 'known' for r in data.lines):
        recognized = rounded(sum((amount for amount, row in zip(raw, data.lines) if row.eligible.value), Fraction()))
        retained = rounded(recognized * decimal_fraction(data.retention_fraction))
        replaced_retention = decimal_fraction(data.corrected_retention.value) if data.corrected_retention is not None else Fraction()
        if data.retention_cap is not None:
            available_cap = decimal_fraction(data.retention_cap.value)
            if data.basis == 'incremental':
                available_cap -= prior_retention - replaced_retention
            if available_cap < 0:
                raise ValueError('Original retention history exceeds the contract cap')
            retained = min(retained, available_cap)
        retained_delta = retained - (prior_retention if data.basis == 'cumulative' else replaced_retention)
        net = recognized - retained - deductions - advances
        if net < 0:
            raise ValueError('Offsets exceed this valuation; excess credit/refund requires a separate decision')
        delta = net - (prior_net if data.basis == 'cumulative' else (
            decimal_fraction(data.corrected_net.value) if data.corrected_net is not None else Fraction()))
        cumulative = net if data.basis == 'cumulative' else prior_net + delta
        if cumulative < 0:
            raise ValueError('Correction exceeds the original contract net history')
        report.update(recognized_amount=known(recognized), disputed_amount=known(assessed - recognized),
            retention_amount=known(retained), retention_period_delta=known(retained_delta), net_amount=known(net),
            net_period_delta=known(delta), cumulative_net=known(cumulative))
        if data.paid_total.state == 'known':
            remaining = cumulative - decimal_fraction(data.paid_total.value.value)
            report.update(unsettled_amount=known(max(remaining, Fraction())), overpayment=known(max(-remaining, Fraction())))
        else:
            report.update(unsettled_amount=unknown('certified_cash_not_visible'), overpayment=unknown('certified_cash_not_visible'))
    return PaymentValuationReport.model_validate(report)


def register_qs_payment_method(registry):
    basis = Path(__file__).with_name('QS_PAYMENT.md')
    registry.register({'method_ref': PAYMENT_METHOD, 'namespace': 'micro_local', 'effect_kind': 'pure_calculation',
        'invocation': 'trusted_processor', 'input_schema_id': 'micro-qs-payment.v1:input', 'output_schema_id': 'micro-qs-payment.v1:report',
        'action_ids': ['QS-A08'], 'unit_rule': 'exact_declared_units_no_conversion',
        'support_domain': ['Original nonnegative work quantities and contractual rates', 'Sourced eligibility with unknown preserved',
            'Explicit retention fraction/cap and separately authorized deductions/advance credits',
            'Half-even total rounding, cumulative period differences and original incremental certificate correction',
            'Certified payment cash separated from advance cash; unknown cash remains unknown'],
        'basis_locator': 'src/methods/QS_PAYMENT.md', 'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration': 'mathematical_only', 'limitations': ['No physical measurement, FX, tax, certification, debt or cash effect',
            'Complete original histories, credit allocation and contract condition decisions require independent records',
            'No automatic refund or work suspension']}, PaymentValuationInput, PaymentValuationReport, calculate_payment)
