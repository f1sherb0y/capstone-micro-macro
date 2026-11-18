"""Exact declared option intervals and per-source cumulative cash calendars."""
from decimal import Decimal
from fractions import Fraction
import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import ClockRef, DecimalString, Measured, Money, Reference, StrictRecord, TextId, TimePoint, ref_type

COMPARISON_METHOD = ref_type('Method')(kind='Method', id='micro.owner.declared_option_intervals', version='1')
CASH_METHOD = ref_type('Method')(kind='Method', id='micro.owner.declared_cash_calendar', version='1')


class SignedExact(StrictRecord):
    numerator: int
    denominator: Annotated[int, Field(gt=0)]

    @classmethod
    def of(cls, value):
        return cls(numerator=value.numerator, denominator=value.denominator)

    def fraction(self):
        return Fraction(self.numerator, self.denominator)


class OptionCriterion(StrictRecord):
    code: TextId
    direction: Literal['maximize', 'minimize']
    weight: DecimalString
    scale: Measured


class OptionMetric(StrictRecord):
    code: TextId
    lower: Measured
    upper: Measured


class ComparableOption(StrictRecord):
    option_ref: ref_type('ProjectOption')
    metrics: Annotated[list[OptionMetric], Field(min_length=1)]


class OptionComparisonInput(StrictRecord):
    criteria: Annotated[list[OptionCriterion], Field(min_length=1, max_length=32)]
    options: Annotated[list[ComparableOption], Field(min_length=1, max_length=64)]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def exact_domain(self):
        codes = {row.code for row in self.criteria}
        if len(codes) != len(self.criteria): raise ValueError('Comparison criterion repeated')
        if len({(row.option_ref.kind, row.option_ref.id) for row in self.options}) != len(self.options):
            raise ValueError('Comparison option repeated across versions')
        if any(Decimal(row.weight) <= 0 or Decimal(row.scale.value) <= 0 for row in self.criteria):
            raise ValueError('Comparison weights and normalization scales must be positive')
        if len({(ref.kind, ref.id) for ref in self.source_refs}) != len(self.source_refs): raise ValueError('Comparison source identity repeated')
        for option in self.options:
            metrics = {row.code: row for row in option.metrics}
            if len(metrics) != len(option.metrics) or set(metrics) != codes:
                raise ValueError('Every option must supply the same complete criterion set')
            for criterion in self.criteria:
                metric = metrics[criterion.code]
                if metric.lower.unit != criterion.scale.unit or metric.upper.unit != criterion.scale.unit:
                    raise ValueError('Comparison cannot convert units')
                if Decimal(metric.lower.value) > Decimal(metric.upper.value):
                    raise ValueError('Forecast interval bounds reversed')
        return self


class OptionScore(StrictRecord):
    option_ref: ref_type('ProjectOption')
    conservative: SignedExact
    optimistic: SignedExact

    @model_validator(mode='after')
    def interval_order(self):
        if self.conservative.fraction() > self.optimistic.fraction(): raise ValueError('Score interval reversed')
        return self


class OptionComparisonReport(StrictRecord):
    scores: Annotated[list[OptionScore], Field(min_length=1)]
    preferred_refs: list[ref_type('ProjectOption')]

    @model_validator(mode='after')
    def coherent_preference(self):
        if len({row.option_ref.key() for row in self.scores}) != len(self.scores): raise ValueError('Score option repeated')
        best = max(row.conservative.fraction() for row in self.scores)
        expected = {row.option_ref for row in self.scores if row.conservative.fraction() == best}
        if len(set(self.preferred_refs)) != len(self.preferred_refs) or set(self.preferred_refs) != expected:
            raise ValueError('Preference differs from complete conservative score comparison')
        return self


def compare_option_intervals(data):
    scores = []
    for option in data.options:
        metrics = {row.code: row for row in option.metrics}
        low, high = Fraction(), Fraction()
        for criterion in data.criteria:
            metric = metrics[criterion.code]
            factor = Fraction(Decimal(criterion.weight)) / Fraction(Decimal(criterion.scale.value))
            lower, upper = Fraction(Decimal(metric.lower.value)), Fraction(Decimal(metric.upper.value))
            if criterion.direction == 'minimize': lower, upper = -upper, -lower
            low += lower * factor
            high += upper * factor
        scores.append(OptionScore(option_ref=option.option_ref, conservative=SignedExact.of(low), optimistic=SignedExact.of(high)))
    best = max(row.conservative.fraction() for row in scores)
    return OptionComparisonReport(scores=scores, preferred_refs=[row.option_ref for row in scores if row.conservative.fraction() == best])


class CashAccount(StrictRecord):
    source_ref: ref_type('FundingSource')
    opening_available: Money


class CashFlow(StrictRecord):
    local_key: TextId
    source_ref: ref_type('FundingSource')
    time: TimePoint
    amount: Money


class CashCalendarInput(StrictRecord):
    clock_ref: ClockRef
    as_of: TimePoint
    accounts: Annotated[list[CashAccount], Field(min_length=1, max_length=64)]
    inflows: list[CashFlow]
    existing_outflows: list[CashFlow]
    proposed_outflows: list[CashFlow]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def exact_domain(self):
        accounts = {row.source_ref.key(): row for row in self.accounts}
        if len({(row.source_ref.kind, row.source_ref.id) for row in self.accounts}) != len(self.accounts):
            raise ValueError('One funding source cannot be copied across versions')
        if self.as_of.clock_ref != self.clock_ref: raise ValueError('Cash calendar clock differs')
        if len({(ref.kind, ref.id) for ref in self.source_refs}) != len(self.source_refs): raise ValueError('Cash source identity repeated')
        flows = self.inflows + self.existing_outflows + self.proposed_outflows
        if len({row.local_key for row in flows}) != len(flows): raise ValueError('Cash flow identity repeated')
        currency = self.accounts[0].opening_available.currency
        if any(row.opening_available.currency != currency or Decimal(row.opening_available.value) < 0 for row in self.accounts):
            raise ValueError('Cash accounts require one currency and nonnegative available amounts')
        for row in flows:
            if row.source_ref.key() not in accounts or row.amount.currency != currency or Decimal(row.amount.value) < 0:
                raise ValueError('Cash flow changes account, currency or amount domain')
            if row.time.clock_ref != self.clock_ref or row.time.offset < self.as_of.offset:
                raise ValueError('Cash calendar cannot credit a different clock or past flow twice')
        return self


class CashCheckpoint(StrictRecord):
    source_ref: ref_type('FundingSource')
    time: TimePoint
    available: SignedExact


class CashCalendarReport(StrictRecord):
    feasible: bool
    checkpoints: Annotated[list[CashCheckpoint], Field(min_length=1)]

    @model_validator(mode='after')
    def recomputed_feasibility(self):
        if self.feasible != all(row.available.numerator >= 0 for row in self.checkpoints):
            raise ValueError('Cash conclusion differs from checkpoints')
        return self


def check_cash_calendar(data):
    checkpoints = []
    for account in data.accounts:
        source = account.source_ref
        points = sorted({data.as_of.offset, *[flow.time.offset for flow in data.inflows + data.existing_outflows + data.proposed_outflows if flow.source_ref == source]})
        for point in points:
            available = Fraction(Decimal(account.opening_available.value))
            available += sum((Fraction(Decimal(row.amount.value)) for row in data.inflows if row.source_ref == source and row.time.offset <= point), Fraction())
            available -= sum((Fraction(Decimal(row.amount.value)) for row in data.existing_outflows + data.proposed_outflows if row.source_ref == source and row.time.offset <= point), Fraction())
            checkpoints.append(CashCheckpoint(source_ref=source, time=data.as_of.model_copy(update={'offset': point}), available=SignedExact.of(available)))
    return CashCalendarReport(feasible=all(row.available.numerator >= 0 for row in checkpoints), checkpoints=checkpoints)


def register_owner_investment_methods(registry):
    basis = Path(__file__).with_name('OWNER_INVESTMENT.md')
    common = {'namespace': 'micro_local', 'effect_kind': 'pure_calculation', 'invocation': 'trusted_processor',
        'action_ids': ['OWN-A03'], 'unit_rule': 'exact_declared_units_no_conversion',
        'basis_locator': 'src/methods/OWNER_INVESTMENT.md', 'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration': 'mathematical_only'}
    registry.register({**common, 'method_ref': COMPARISON_METHOD, 'input_schema_id': 'micro-option-intervals.v1:input',
        'output_schema_id': 'micro-option-intervals.v1:report', 'support_domain': ['Up to 64 explicitly comparable options and 32 declared criteria',
            'Positive declared weights and scales, exact same units, interval uncertainty retained', 'Maximize conservative normalized weighted utility; ties explicitly returned'],
        'limitations': ['No inferred weights, forecast production or probability assumptions', 'Scores cannot create funds, rights, approval or investment authority']},
        OptionComparisonInput, OptionComparisonReport, compare_option_intervals)
    registry.register({**common, 'method_ref': CASH_METHOD, 'action_ids': ['OWN-A03', 'CONTRACTOR-A04'], 'input_schema_id': 'micro-cash-calendar.v1:input',
        'output_schema_id': 'micro-cash-calendar.v1:report', 'support_domain': ['Up to 64 unique funding sources, one currency and exact clock',
            'Opening free balances plus sourced timed inflows less all existing and proposed outflows', 'At each declared time same-time inflows and outflows settle together; no early use of future inflows'],
        'limitations': ['Future contractual availability is a planning assumption, never received cash or payment execution',
            'No cross-source pooling, currency conversion, loan origination or formal reservation', 'All debt and commitments require complete current host projections']},
        CashCalendarInput, CashCalendarReport, check_cash_calendar)
