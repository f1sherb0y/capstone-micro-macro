"""Exact original final-price reconciliation, preserving unknown cash and rights."""
import hashlib
from fractions import Fraction
from pathlib import Path

from pydantic import Field, model_validator

from src.actions.contracts.common import EvidenceRef, Money, Reference, StrictRecord, TextId, ValueState, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.pricing import decimal_fraction, exact_decimal
from src.methods.qs_cost import unknown

FINAL_ACCOUNT_METHOD = ref_type('Method')(kind='Method',id='micro.qs.original_final_account',version='1')


class FinalAccountComponent(StrictRecord):
    component_key: TextId
    amount: ValueState[Money]
    direction: int = Field(ge=-1,le=1)


class FinalAccountInput(StrictRecord):
    currency: TextId
    money_basis_ref: EvidenceRef
    base_component_key: TextId
    base_amount: ValueState[Money]
    changes: list[FinalAccountComponent]
    price_deductions: list[FinalAccountComponent]
    certificate_contributions: list[Money]
    received_cash: ValueState[Money]
    cash_refunds: list[FinalAccountComponent]
    noncash_satisfied: list[FinalAccountComponent]
    source_refs: list[Reference] = Field(min_length=1)

    @model_validator(mode='after')
    def original_domain(self):
        unique_refs(self.source_refs)
        components=self.changes+self.price_deductions+self.cash_refunds+self.noncash_satisfied
        if (len({c.component_key for c in components})!=len(components) or any(c.direction==0 for c in components)
                or self.base_component_key in {c.component_key for c in components}):
            raise ValueError('Final account repeats an original price/cash/offset component')
        if any(c.direction!=1 for c in self.price_deductions+self.cash_refunds+self.noncash_satisfied):
            raise ValueError('Deductions, actual refunds and satisfied noncash obligations use positive original amounts')
        values=[self.base_amount,self.received_cash,*[c.amount for c in self.price_deductions+self.cash_refunds+self.noncash_satisfied]]
        for value in values:
            if value.state=='known' and (value.value.currency!=self.currency or decimal_fraction(value.value.value)<0):
                raise ValueError('Final account requires compatible nonnegative original amounts')
        for component in self.changes:
            if component.amount.state=='known' and (component.amount.value.currency!=self.currency
                    or decimal_fraction(component.amount.value.value)<0 and component.direction!=1):
                raise ValueError('Signed original change cannot be negated again or change currency')
        if any(m.currency!=self.currency for m in self.certificate_contributions):
            raise ValueError('Certified final account history changes original currency')
        return self


class FinalAccountReport(StrictRecord):
    determined_total: ValueState[Money]
    certified_total: ValueState[Money]
    paid_total: ValueState[Money]
    unsettled_amount: ValueState[Money]


def reconcile_final_account(data: FinalAccountInput):
    basis=data.money_basis_ref

    def money(number):
        return {'state':'known','value':Money(value=exact_decimal(number),currency=data.currency,basis_ref=basis)}

    def sum_components(rows):
        if any(c.amount.state!='known' for c in rows): return None
        return sum((c.direction*decimal_fraction(c.amount.value.value) for c in rows),Fraction())

    changes,deductions,refunds,offsets=map(sum_components,(data.changes,data.price_deductions,data.cash_refunds,data.noncash_satisfied))
    determined=None if data.base_amount.state!='known' or changes is None or deductions is None else decimal_fraction(data.base_amount.value.value)+changes-deductions
    paid=None if data.received_cash.state!='known' or refunds is None else decimal_fraction(data.received_cash.value.value)-refunds
    if determined is not None and determined<0: raise ValueError('Original final price cannot be negative')
    if paid is not None and paid<0: raise ValueError('Refund exceeds complete original received cash')
    certified=sum((decimal_fraction(m.value) for m in data.certificate_contributions),Fraction())
    if certified<0: raise ValueError('Original corrected certified total cannot be negative')
    return FinalAccountReport(determined_total=unknown('original_final_price_not_known') if determined is None else money(determined),
        certified_total=money(certified),paid_total=unknown('actual_final_cash_not_known') if paid is None else money(paid),
        unsettled_amount=unknown('original_final_balance_not_known') if determined is None or paid is None or offsets is None else money(determined-paid-offsets))


def register_final_account_method(registry):
    basis=Path(__file__).resolve()
    registry.register({'method_ref':FINAL_ACCOUNT_METHOD,'namespace':'micro_local','effect_kind':'pure_calculation',
        'invocation':'trusted_processor','input_schema_id':'micro-qs-final-account.v1:input','output_schema_id':'micro-qs-final-account.v1:report',
        'action_ids':['QS-A09'],'unit_rule':'exact_declared_units_no_conversion',
        'support_domain':['Original base price and independently determined signed changes','Active original certificate delta contributions',
            'Verified received cash, separately authorized actual refunds/setoffs and price deductions','Unknown money remains unknown; signed balance may show overpayment'],
        'basis_locator':'src/methods/qs_final_account.py','basis_sha256':hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration':'mathematical_only','limitations':['No legal determination from arithmetic','Balance does not determine present maturity, dispute outcome or loan clearance',
            'No cash, obligation, dispute or contract effect']},FinalAccountInput,FinalAccountReport,reconcile_final_account)
