"""Exact sourced contract/proposed remedy arithmetic; no debt recognition."""
import hashlib
from pathlib import Path
from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, Measured, Money, Reference, StrictRecord, TextId, ref_type
from src.methods.pricing import decimal_fraction, exact_decimal

CLAIM_METHOD = ref_type('Method')(kind='Method', id='micro.supply.contract_claim_amount', version='1')


class SupplierClaimAmountInput(StrictRecord):
    quantity: Measured
    unit_price: Money
    fixed_amount: Money
    deduction_amounts: list[Money]
    currency: TextId
    source_refs: list[Reference] = Field(min_length=1)

    @model_validator(mode='after')
    def supported_amounts(self):
        values = [self.unit_price,self.fixed_amount,*self.deduction_amounts]
        if decimal_fraction(self.quantity.value) < 0 or any(v.currency != self.currency or decimal_fraction(v.value) < 0 for v in values):
            raise ValueError('Original contract quantity/amounts must be nonnegative in one currency')
        if len({r.key() for r in self.source_refs}) != len(self.source_refs):
            raise ValueError('Claim amount source repeated')
        return self


class SupplierClaimAmountReport(StrictRecord):
    gross: DecimalString
    deductions: DecimalString
    payable: DecimalString


def calculate_claim_amount(data: SupplierClaimAmountInput):
    gross = decimal_fraction(data.quantity.value)*decimal_fraction(data.unit_price.value)+decimal_fraction(data.fixed_amount.value)
    deductions = sum((decimal_fraction(v.value) for v in data.deduction_amounts),start=decimal_fraction('0'))
    if deductions > gross:raise ValueError('Original deductions exceed positive contract node value')
    return SupplierClaimAmountReport(gross=exact_decimal(gross),deductions=exact_decimal(deductions),payable=exact_decimal(gross-deductions))


def register_supplier_payment_method(registry):
    basis = Path(__file__).resolve()
    registry.register({'method_ref':CLAIM_METHOD,'namespace':'micro_local','effect_kind':'pure_calculation',
        'invocation':'trusted_processor','input_schema_id':'micro-supply-claim.v1:input','output_schema_id':'micro-supply-claim.v1:report',
        'action_ids':['SUPPLIER-A10','SUPPLIER-A11'],'unit_rule':'exact_declared_units_no_conversion',
        'support_domain':['Original authorized contract node or proposed remedy quantity and unit price','Explicit sourced fixed amount and nonnegative deductions','Single original currency','Exact finite decimal arithmetic'],
        'basis_locator':'src/methods/supplier_payment.py','basis_sha256':hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration':'mathematical_only','limitations':['No entitlement recognition or inferred contract price','No cost markup, FX or automatic rounding','No debt, payment or cash effect']},
        SupplierClaimAmountInput,SupplierClaimAmountReport,calculate_claim_amount)
