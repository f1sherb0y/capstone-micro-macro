"""Exact per-dimension risk intervals and hypothetical affordability bounds."""
from fractions import Fraction
import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.bank_credit_objects import (
    CreditLoanFactor, CreditMeasuredInterval, CreditMoneyInterval, unique_identities,
)
from src.actions.contracts.common import (
    EvidenceRef, Measured, Money, Reference, StrictRecord, TextId, TimePoint,
    TimeWindow, ValueState, ref_type,
)
from src.methods.owner_investment import SignedExact
from src.methods.pricing import decimal_fraction, exact_decimal


CREDIT_RISK_METHOD = ref_type('Method')(kind='Method', id='micro.bank.declared_risk_intervals', version='1')
CREDIT_CASH_METHOD = ref_type('Method')(kind='Method', id='micro.bank.indicative_cash_bounds', version='1')


class CreditRiskInputDimension(StrictRecord):
    dimension_ref: ref_type('RiskDimension')
    predicate: Literal['at_most', 'at_least']
    threshold: Measured
    interval: ValueState[CreditMeasuredInterval]

    @model_validator(mode='after')
    def explicit_units(self):
        if self.interval.state == 'known' and self.interval.value.lower.unit != self.threshold.unit:
            raise ValueError('Risk observation and threshold must use the exact same unit')
        return self


class CreditRiskInput(StrictRecord):
    dimensions: Annotated[list[CreditRiskInputDimension], Field(min_length=1, max_length=64)]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def distinct_sources_dimensions(self):
        unique_identities(self.source_refs)
        unique_identities([row.dimension_ref for row in self.dimensions])
        return self


class CreditRiskResult(StrictRecord):
    dimension_ref: ref_type('RiskDimension')
    conclusion: Literal['acceptable', 'unacceptable', 'unknown']


class CreditRiskReport(StrictRecord):
    findings: Annotated[list[CreditRiskResult], Field(min_length=1)]

    @model_validator(mode='after')
    def distinct_dimensions(self):
        unique_identities([row.dimension_ref for row in self.findings])
        return self


def evaluate_credit_risk(data):
    findings = []
    for row in data.dimensions:
        conclusion = 'unknown'
        if row.interval.state == 'known':
            lower, upper = (decimal_fraction(value.value) for value in
                            (row.interval.value.lower, row.interval.value.upper))
            threshold = decimal_fraction(row.threshold.value)
            if row.predicate == 'at_most':
                conclusion = 'acceptable' if upper <= threshold else 'unacceptable' if lower > threshold else 'unknown'
            else:
                conclusion = 'acceptable' if lower >= threshold else 'unacceptable' if upper < threshold else 'unknown'
        findings.append(CreditRiskResult(dimension_ref=row.dimension_ref, conclusion=conclusion))
    return CreditRiskReport(findings=findings)


class CreditOpeningCash(StrictRecord):
    account_ref: ref_type('Account')
    unrestricted: Money

    @model_validator(mode='after')
    def actual_free_cash(self):
        if decimal_fraction(self.unrestricted.value) < 0:
            raise ValueError('Opening unrestricted cash cannot be negative')
        return self


class CreditCashMovement(StrictRecord):
    local_key: TextId
    account_ref: ref_type('Account')
    time: TimePoint
    direction: Literal['inflow', 'outflow']
    amount: CreditMoneyInterval


class CreditCashInput(StrictRecord):
    as_of: TimePoint
    horizon: TimeWindow
    currency: TextId
    minor_places: Annotated[int, Field(ge=0, le=8)]
    minimum: Money
    maximum: Money
    requested: Money
    opening: Annotated[list[CreditOpeningCash], Field(min_length=1, max_length=64)]
    movements: Annotated[list[CreditCashMovement], Field(max_length=512)]
    loan_account_ref: ref_type('Account')
    loan_schedule: Annotated[list[CreditLoanFactor], Field(min_length=2, max_length=256)]
    basis_refs: Annotated[list[EvidenceRef], Field(min_length=1)]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def exact_declared_domain(self):
        unique_identities(self.source_refs)
        unique_identities(self.basis_refs)
        accounts = [row.account_ref for row in self.opening]
        unique_identities(accounts)
        if self.loan_account_ref not in accounts or any(row.account_ref not in accounts for row in self.movements):
            raise ValueError('Cash constraints cannot use an undeclared account')
        if (self.horizon.start.clock_ref != self.as_of.clock_ref or not self.horizon.contains(self.as_of)
                or self.horizon.end.offset <= self.as_of.offset):
            raise ValueError('Credit horizon must contain the review point and extend into the future')
        if any(not self.horizon.contains(row.time) or row.time.offset < self.as_of.offset
               for row in self.movements + self.loan_schedule):
            raise ValueError('Credit events must use the declared clock and remaining horizon')
        amounts = [self.minimum, self.maximum, self.requested] + [row.unrestricted for row in self.opening]
        amounts += [money for row in self.movements for money in (row.amount.lower, row.amount.upper)]
        if any(row.currency != self.currency for row in amounts):
            raise ValueError('Credit bounds cannot convert currencies')
        if (decimal_fraction(self.minimum.value) < 0
                or decimal_fraction(self.maximum.value) < decimal_fraction(self.minimum.value)
                or decimal_fraction(self.requested.value) <= 0):
            raise ValueError('Credit bounds require a positive request and ordered nonnegative product limits')
        for rows in (self.movements, self.loan_schedule):
            keys = [row.local_key for row in rows]
            if len(set(keys)) != len(keys):
                raise ValueError('Credit calendar repeats a cash event')
        draw = sum((decimal_fraction(row.factor) for row in self.loan_schedule if row.kind == 'draw'), Fraction())
        principal = sum((decimal_fraction(row.factor) for row in self.loan_schedule if row.kind == 'principal'), Fraction())
        if draw != 1 or principal != 1:
            raise ValueError('Hypothetical full-draw schedule must conserve one unit of principal')
        for point in {row.time.offset for row in self.loan_schedule}:
            outstanding = sum((decimal_fraction(row.factor) * (1 if row.kind == 'draw' else -1)
                               for row in self.loan_schedule if row.time.offset <= point and row.kind != 'cost'), Fraction())
            if outstanding < 0:
                raise ValueError('Hypothetical repayment cannot precede cumulative draw')
        return self


class CreditCashConstraint(StrictRecord):
    account_ref: ref_type('Account')
    time: TimePoint
    ordinary_free_cash: SignedExact
    loan_coefficient: SignedExact


class CreditCashReport(StrictRecord):
    feasible: bool
    exact_lower: SignedExact
    exact_upper: SignedExact
    rounded_lower: Money | None
    rounded_upper: Money | None
    constraints: Annotated[list[CreditCashConstraint], Field(min_length=1)]

    @model_validator(mode='after')
    def usable_positive_interval(self):
        if self.feasible:
            if self.rounded_lower is None or self.rounded_upper is None:
                raise ValueError('Feasible credit interval requires both monetary endpoints')
            lo, hi = decimal_fraction(self.rounded_lower.value), decimal_fraction(self.rounded_upper.value)
            if (self.rounded_lower.currency != self.rounded_upper.currency or lo <= 0 or lo > hi
                    or lo < self.exact_lower.fraction() or hi > self.exact_upper.fraction()):
                raise ValueError('Rounded credit interval must lie inside positive exact bounds')
        elif self.rounded_lower is not None or self.rounded_upper is not None:
            raise ValueError('Infeasible review cannot invent a lending range')
        return self


def calculate_credit_cash_bounds(data):
    lower = decimal_fraction(data.minimum.value)
    upper = min(decimal_fraction(data.maximum.value), decimal_fraction(data.requested.value))
    feasible, constraints = True, []
    points = sorted({data.as_of.offset, data.horizon.end.offset,
                     *(row.time.offset for row in data.movements + data.loan_schedule)})
    for account in sorted(data.opening, key=lambda row: repr(row.account_ref.key())):
        for point in points:
            free = decimal_fraction(account.unrestricted.value)
            for row in data.movements:
                if row.account_ref == account.account_ref and row.time.offset <= point:
                    value = row.amount.lower if row.direction == 'inflow' else row.amount.upper
                    free += decimal_fraction(value.value) * (1 if row.direction == 'inflow' else -1)
            coefficient = Fraction()
            if account.account_ref == data.loan_account_ref:
                coefficient = sum((decimal_fraction(row.factor) * (1 if row.kind == 'draw' else -1)
                                   for row in data.loan_schedule if row.time.offset <= point), Fraction())
            constraints.append(CreditCashConstraint(account_ref=account.account_ref,
                time=TimePoint(clock_ref=data.as_of.clock_ref, offset=point),
                ordinary_free_cash=SignedExact.of(free), loan_coefficient=SignedExact.of(coefficient)))
            if coefficient > 0:
                lower = max(lower, -free / coefficient)
            elif coefficient < 0:
                upper = min(upper, -free / coefficient)
            elif free < 0:
                feasible = False
    scale = 10 ** data.minor_places
    lower_ticks = max(1, -(-(lower * scale).numerator // (lower * scale).denominator))
    upper_ticks = (upper * scale).numerator // (upper * scale).denominator
    feasible = feasible and lower_ticks <= upper_ticks
    make_money = lambda ticks: Money(value=exact_decimal(Fraction(ticks, scale)), currency=data.currency,
                                     basis_ref=data.basis_refs[0])
    return CreditCashReport(feasible=feasible, exact_lower=SignedExact.of(lower), exact_upper=SignedExact.of(upper),
        rounded_lower=make_money(lower_ticks) if feasible else None,
        rounded_upper=make_money(upper_ticks) if feasible else None, constraints=constraints)


def register_bank_credit_methods(registry):
    basis = Path(__file__).with_name('BANK_CREDIT.md')
    common = {'namespace': 'micro_local', 'effect_kind': 'pure_calculation', 'invocation': 'trusted_processor',
        'action_ids': ['BANK-A03', 'BANK-A04', 'BANK-A13'], 'unit_rule': 'exact_declared_units_no_conversion',
        'basis_locator': 'src/methods/BANK_CREDIT.md', 'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration': 'mathematical_only'}
    registry.register({**common, 'method_ref': CREDIT_RISK_METHOD,
        'input_schema_id': 'micro-credit-risk-intervals.v1:input', 'output_schema_id': 'micro-credit-risk-intervals.v1:report',
        'support_domain': ['Up to 64 supplied risk intervals and explicit thresholds in exact matching units',
            'Independent at-most or at-least comparisons with interval uncertainty retained'],
        'limitations': ['No aggregate score, inferred threshold, probability or calibrated credit rating',
            'Hard dimensions and conditional remedies must be checked by the authorized processor']},
        CreditRiskInput, CreditRiskReport, evaluate_credit_risk)
    registry.register({**common, 'method_ref': CREDIT_CASH_METHOD,
        'input_schema_id': 'micro-credit-cash-bounds.v1:input', 'output_schema_id': 'micro-credit-cash-bounds.v1:report',
        'support_domain': ['One currency and clock, 64 original accounts, 512 ordinary flows and 256 loan factors',
            'Exact intersection of every cumulative cash inequality and supplied product/request limits',
            'Conservative interval flows and explicit inward monetary rounding of indicative principal bounds'],
        'limitations': ['Forecasts and hypothetical financing never create actual balances or commitments',
            'No pooling, currency conversion, partial or revolving draws, floating rates or automatic refinance',
            'The processor must establish full disclosed debt coverage, authority and lawful account paths']},
        CreditCashInput, CreditCashReport, calculate_credit_cash_bounds)
    return registry
