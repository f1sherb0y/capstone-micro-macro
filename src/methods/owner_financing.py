"""Exact declared finance schedules and ordinal choice, without loan creation."""
import hashlib
from fractions import Fraction
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from src.actions.contracts.common import Money, Reference, StrictRecord, TimeWindow, ref_type
from src.actions.contracts.owner_financing_objects import FinancingPayment
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.owner_investment import (
    CashCalendarInput, CashCalendarReport, SignedExact, check_cash_calendar,
)
from src.methods.pricing import decimal_fraction

FINANCING_CASH_METHOD = ref_type('Method')(kind='Method', id='micro.owner.financing_cash_calendar', version='1')
FINANCING_METHOD = ref_type('Method')(kind='Method', id='micro.owner.declared_financing_selection', version='1')


class FinancingCandidate(StrictRecord):
    offer_ref: ref_type('FinanceOffer')
    priority: int
    principal: Money
    tenor: TimeWindow
    disbursements: Annotated[list[FinancingPayment], Field(min_length=1)]
    repayments: Annotated[list[FinancingPayment], Field(min_length=1)]
    costs: list[FinancingPayment]

    @model_validator(mode='after')
    def exact_schedule(self):
        payments = self.disbursements + self.repayments + self.costs
        keys = [row.local_key for row in payments]
        if len(set(keys)) != len(keys):
            raise ValueError('One offer cannot count a payment twice')
        principal = decimal_fraction(self.principal.value)
        if principal <= 0 or any(row.amount.currency != self.principal.currency for row in payments):
            raise ValueError('Financing requires positive principal in one exact currency')
        if any(not self.tenor.contains(row.time) for row in payments):
            raise ValueError('Financing payments must remain in the exact tenor')
        drawn = sum((decimal_fraction(row.amount.value) for row in self.disbursements), Fraction())
        paid = sum((decimal_fraction(row.amount.value) for row in self.repayments), Fraction())
        if drawn != principal or paid != principal:
            raise ValueError('The declared full-draw schedule must conserve quoted principal')
        for time in {row.time.offset for row in self.disbursements + self.repayments}:
            outstanding = sum((decimal_fraction(row.amount.value) for row in self.disbursements if row.time.offset <= time), Fraction())
            outstanding -= sum((decimal_fraction(row.amount.value) for row in self.repayments if row.time.offset <= time), Fraction())
            if outstanding < 0:
                raise ValueError('Principal cannot be repaid before it is drawn')
        return self


class FinancingSelectionInput(StrictRecord):
    cost_cap: Money
    candidates: Annotated[list[FinancingCandidate], Field(max_length=64)]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def declared_domain(self):
        unique_refs(self.source_refs)
        unique_refs([row.offer_ref for row in self.candidates])
        if decimal_fraction(self.cost_cap.value) < 0:
            raise ValueError('Financing cost cap cannot be negative')
        if any(row.principal.currency != self.cost_cap.currency for row in self.candidates):
            raise ValueError('Financing comparison cannot convert currencies')
        return self


class FinancingCost(StrictRecord):
    offer_ref: ref_type('FinanceOffer')
    principal: SignedExact
    nominal_cost: SignedExact


class FinancingSelectionReport(StrictRecord):
    selected_ref: ref_type('FinanceOffer') | None
    ambiguous_refs: list[ref_type('FinanceOffer')]
    excluded_refs: list[ref_type('FinanceOffer')]
    costs: list[FinancingCost]

    @model_validator(mode='after')
    def partition(self):
        targets = self.ambiguous_refs + self.excluded_refs
        if self.selected_ref is not None:
            if self.ambiguous_refs:
                raise ValueError('An ambiguous preference cannot select an offer')
            targets.append(self.selected_ref)
        unique_refs(targets)
        unique_refs([row.offer_ref for row in self.costs])
        if len(self.ambiguous_refs) == 1:
            raise ValueError('One offer cannot form an ambiguous preference')
        if not set(targets) <= {row.offer_ref for row in self.costs}:
            raise ValueError('Selection refers outside the cost report')
        return self


def select_financing(data):
    costs, feasible, excluded = [], [], []
    for row in data.candidates:
        cost = sum((decimal_fraction(item.amount.value) for item in row.costs), Fraction())
        costs.append(FinancingCost(offer_ref=row.offer_ref, principal=SignedExact.of(decimal_fraction(row.principal.value)),
                                   nominal_cost=SignedExact.of(cost)))
        if cost > decimal_fraction(data.cost_cap.value):
            excluded.append(row.offer_ref)
        else:
            feasible.append(row)
    tied = []
    if feasible:
        priority = min(row.priority for row in feasible)
        tied = sorted((row.offer_ref for row in feasible if row.priority == priority), key=lambda ref: repr(ref.key()))
    return FinancingSelectionReport(selected_ref=tied[0] if len(tied) == 1 else None,
        ambiguous_refs=tied if len(tied) > 1 else [], excluded_refs=excluded, costs=costs)


def register_owner_financing_methods(registry):
    basis = Path(__file__).with_name('OWNER_FINANCING.md')
    common = {'namespace': 'micro_local', 'effect_kind': 'pure_calculation', 'invocation': 'trusted_processor',
        'action_ids': ['OWN-A05'], 'unit_rule': 'exact_declared_units_no_conversion',
        'basis_locator': 'src/methods/OWNER_FINANCING.md', 'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration': 'mathematical_only'}
    registry.register({**common, 'method_ref': FINANCING_CASH_METHOD,
        'input_schema_id': 'micro-cash-calendar.v1:input', 'output_schema_id': 'micro-cash-calendar.v1:report',
        'support_domain': ['Up to 64 distinct funding sources and one currency and clock',
            'Exact cumulative opening free cash and sourced future releases less existing and proposed payments',
            'Same-time flows settle together; hypothetical offered releases stay conditional planning flows'],
        'limitations': ['No pooling between accounts, FX conversion or source replication',
            'No release, loan, payment, reservation or formal acceptance is created',
            'Cash-flow completeness and lawful release conditions must be checked by the authorized processor']},
        CashCalendarInput, CashCalendarReport, check_cash_calendar)
    registry.register({**common, 'method_ref': FINANCING_METHOD,
        'input_schema_id': 'micro-financing-selection.v1:input', 'output_schema_id': 'micro-financing-selection.v1:report',
        'support_domain': ['Up to 64 fully declared fixed cash schedules in one currency',
            'Full-draw principal conservation and positive scheduled payments inside the exact tenor',
            'Exclude nominal interest and fees above the declared cap, then ascending declared ordinal priority',
            'Ties need explicit clarification; no fabricated cheapest/preferred-bank decision'],
        'limitations': ['No rate forecasting, discounting, NPV, rolling draw or automatic refinancing',
            'Variable or incomplete pricing requires a separately registered method',
            'Ordinal priority is sourced owner preference, not an empirically calibrated finance recommendation',
            'Loan acceptance is conditional and does not create an arrangement, principal or cash']},
        FinancingSelectionInput, FinancingSelectionReport, select_financing)
