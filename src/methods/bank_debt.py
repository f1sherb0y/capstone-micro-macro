"""Exact simple accrual over sourced balance, reset and calendar partitions."""
import hashlib
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, Money, Reference, StrictRecord, TextId, TimeWindow, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.pricing import decimal_fraction, exact_decimal

DEBT_METHOD = ref_type('Method')(kind='Method', id='micro.bank.sourced_debt_accrual', version='1')


class DebtBalanceSegment(StrictRecord):
    window: TimeWindow
    balance: Money
    effective_event_refs: Annotated[list[Reference], Field(min_length=1)]


class DebtRateSegment(StrictRecord):
    window: TimeWindow
    annual_rate: DecimalString
    basis_ref: ref_type('Evidence')
    reset_ref: ref_type('RateReset') | None


class DebtCalendarSegment(StrictRecord):
    window: TimeWindow
    ticks_per_year: Annotated[int, Field(gt=0)]
    basis_ref: ref_type('Evidence')
    calendar_ref: ref_type('DebtCalendar')


class DebtAccrualLine(StrictRecord):
    debt_component_ref: ref_type('DebtComponent')
    balance_source_ref: Reference
    base_kind: Literal['actual_principal', 'undrawn_commitment']
    rate_mode: Literal['fixed', 'floating']
    balances: Annotated[list[DebtBalanceSegment], Field(min_length=1)]
    rates: Annotated[list[DebtRateSegment], Field(min_length=1)]
    calendars: Annotated[list[DebtCalendarSegment], Field(min_length=1)]


class DebtPriorAccrual(StrictRecord):
    posting_ref: ref_type('LedgerPosting')
    business_key: TextId
    debt_component_ref: ref_type('DebtComponent')
    kind: Literal['accrual', 'correction']
    window: TimeWindow
    amount: Money


class DebtAccrualInput(StrictRecord):
    currency: TextId
    window: TimeWindow
    lines: Annotated[list[DebtAccrualLine], Field(min_length=1)]
    minor_places: Annotated[int, Field(ge=0, le=8)]
    rounding: Literal['half_even', 'floor', 'ceiling']
    prior_postings: list[DebtPriorAccrual]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def complete_partitions(self):
        unique_refs(self.source_refs)
        unique_refs([line.debt_component_ref for line in self.lines])
        unique_refs([row.posting_ref for row in self.prior_postings])
        if len({row.business_key for row in self.prior_postings}) != len(self.prior_postings):
            raise ValueError('Debt calculation repeats an original accrual business key')
        for row in self.prior_postings:
            if row.amount.currency != self.currency or (row.kind == 'accrual' and decimal_fraction(row.amount.value) < 0):
                raise ValueError('Original accrual postings need same-currency amounts')
            if row.window.start.clock_ref != self.window.start.clock_ref:
                raise ValueError('Original accrual postings need the original calculation clock')
            if row.window != self.window and max(row.window.start.offset, self.window.start.offset) < min(row.window.end.offset, self.window.end.offset):
                raise ValueError('Overlapping original accrual periods require an explicit correction partition')
        if self.window.bounds != 'closed_open' or self.window.start.offset >= self.window.end.offset:
            raise ValueError('Debt accrual needs a nonempty half-open original interval')
        for line in self.lines:
            for rows in (line.balances, line.rates, line.calendars):
                cursor = self.window.start.offset
                for row in rows:
                    if (row.window.bounds != 'closed_open' or row.window.start.clock_ref != self.window.start.clock_ref
                            or row.window.start.offset != cursor or row.window.end.offset <= cursor):
                        raise ValueError('Debt inputs must partition the original interval without gaps or overlap')
                    cursor = row.window.end.offset
                if cursor != self.window.end.offset: raise ValueError('Incomplete original debt calculation period')
            if any(row.balance.currency != self.currency or decimal_fraction(row.balance.value) < 0 for row in line.balances):
                raise ValueError('Debt balances require nonnegative actual amounts in one currency')
            for row in line.balances: unique_refs(row.effective_event_refs)
            if any(decimal_fraction(row.annual_rate) < 0 for row in line.rates):
                raise ValueError('Negative rate products need an explicit credit/refund method')
            if line.rate_mode == 'fixed' and len({decimal_fraction(row.annual_rate) for row in line.rates}) != 1:
                raise ValueError('Fixed debt rates cannot change with new market quotations')
            if line.rate_mode == 'floating' and any(row.reset_ref is None for row in line.rates):
                raise ValueError('Floating debt rates need original reset observations')
        return self


class DebtAccrualResultLine(StrictRecord):
    debt_component_ref: ref_type('DebtComponent')
    exact_numerator: Annotated[int, Field(ge=0)]
    exact_denominator: Annotated[int, Field(gt=0)]
    accrued: DecimalString
    previously_posted: DecimalString
    adjustment: DecimalString


class DebtAccrualReport(StrictRecord):
    lines: list[DebtAccrualResultLine]


def calculate_debt_accrual(data):
    output = []
    for line in data.lines:
        points = sorted({point.offset for rows in (line.balances, line.rates, line.calendars)
                         for row in rows for point in (row.window.start, row.window.end)})
        total = Fraction()
        for start, end in zip(points, points[1:]):
            balance = next(row for row in line.balances if row.window.start.offset <= start < row.window.end.offset)
            rate = next(row for row in line.rates if row.window.start.offset <= start < row.window.end.offset)
            calendar = next(row for row in line.calendars if row.window.start.offset <= start < row.window.end.offset)
            total += decimal_fraction(balance.balance.value) * decimal_fraction(rate.annual_rate) * Fraction(end - start, calendar.ticks_per_year)
        scale = 10 ** data.minor_places
        scaled = total * scale
        integer, remainder = divmod(scaled.numerator, scaled.denominator)
        if data.rounding == 'ceiling' and remainder: integer += 1
        if data.rounding == 'half_even' and (2 * remainder > scaled.denominator or (2 * remainder == scaled.denominator and integer % 2)):
            integer += 1
        accrued = Fraction(integer, scale)
        previous = sum((decimal_fraction(row.amount.value) for row in data.prior_postings
                        if row.debt_component_ref.key() == line.debt_component_ref.key() and row.window == data.window), Fraction())
        if previous < 0: raise ValueError('Original accrued total including corrections cannot be negative')
        output.append(DebtAccrualResultLine(debt_component_ref=line.debt_component_ref,
            exact_numerator=total.numerator, exact_denominator=total.denominator,
            accrued=exact_decimal(accrued), previously_posted=exact_decimal(previous), adjustment=exact_decimal(accrued - previous)))
    return DebtAccrualReport(lines=output)


def register_bank_debt_method(registry):
    basis = Path(__file__).with_name('BANK_DEBT.md')
    registry.register({'method_ref': DEBT_METHOD, 'namespace': 'micro_local', 'effect_kind': 'pure_calculation',
        'invocation': 'trusted_processor', 'input_schema_id': 'micro-bank-debt.v1:input', 'output_schema_id': 'micro-bank-debt.v1:report',
        'action_ids': ['BANK-A09'], 'unit_rule': 'exact_declared_units_no_conversion',
        'support_domain': ['Simple interest on verified actual principal partitions', 'Separate undrawn commitment fee partitions',
                           'Original fixed rates or explicit floating reset segments', 'Declared linear calendar segments and final minor-unit rounding'],
        'basis_locator': 'src/methods/BANK_DEBT.md', 'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration': 'mathematical_only', 'limitations': ['No inferred rate/calendar/FX, compounding or automatic capitalization',
            'Product inputs and effective cash times require independent original evidence', 'No ledger mutation or refunds']},
        DebtAccrualInput, DebtAccrualReport, calculate_debt_accrual)
