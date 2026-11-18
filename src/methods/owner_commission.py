"""Exact fee-cap filtering and explicitly declared ordinal service selection."""
from decimal import Decimal
from fractions import Fraction
import hashlib
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from src.actions.contracts.common import Money, Reference, StrictRecord, ref_type
from src.actions.contracts.owner_study_objects import unique_refs

COMMISSION_METHOD = ref_type('Method')(kind='Method',id='micro.owner.declared_service_selection',version='1')


class ServiceSelectionCandidate(StrictRecord):
    offer_ref: ref_type('ServiceOffer')
    terms_ref: ref_type('ContractTerms')
    priority: int
    fee: Money


class ServiceSelectionInput(StrictRecord):
    fee_cap: Money
    candidates: Annotated[list[ServiceSelectionCandidate], Field(max_length=64)]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def explicit_domain(self):
        unique_refs([row.offer_ref for row in self.candidates])
        unique_refs([row.terms_ref for row in self.candidates])
        unique_refs(self.source_refs)
        amounts = [self.fee_cap,*[row.fee for row in self.candidates]]
        if any(v.currency != self.fee_cap.currency or Decimal(v.value) < 0 for v in amounts):
            raise ValueError('Service selection requires one currency and nonnegative explicit amounts')
        return self


class ServiceSelectionReport(StrictRecord):
    selected_ref: ref_type('ServiceOffer') | None
    ambiguous_refs: list[ref_type('ServiceOffer')]
    excluded_refs: list[ref_type('ServiceOffer')]

    @model_validator(mode='after')
    def coherent_partition(self):
        refs = [*self.ambiguous_refs,*self.excluded_refs]
        if self.selected_ref is not None:
            if self.ambiguous_refs:
                raise ValueError('An ambiguous comparison cannot select a service')
            refs.append(self.selected_ref)
        unique_refs(refs)
        if len(self.ambiguous_refs) == 1:
            raise ValueError('A single candidate is not an ambiguous preference')
        return self


def select_service(data: ServiceSelectionInput) -> ServiceSelectionReport:
    cap = Fraction(Decimal(data.fee_cap.value))
    feasible, excluded = [], []
    for row in data.candidates:
        if Fraction(Decimal(row.fee.value)) > cap:
            excluded.append(row.offer_ref)
        else:
            feasible.append(row)
    tied = []
    if feasible:
        priority = min(row.priority for row in feasible)
        tied = sorted((row.offer_ref for row in feasible if row.priority == priority),key=lambda ref:repr(ref.key()))
    return ServiceSelectionReport(selected_ref=tied[0] if len(tied)==1 else None,
        ambiguous_refs=tied if len(tied)>1 else [],excluded_refs=sorted(excluded,key=lambda ref:repr(ref.key())))


def register_owner_commission_method(registry):
    basis = Path(__file__).with_name('OWNER_COMMISSION.md')
    registry.register({'method_ref':COMMISSION_METHOD,'namespace':'micro_local','effect_kind':'pure_calculation',
        'invocation':'trusted_processor','input_schema_id':'micro-owner-commission.v1:input',
        'output_schema_id':'micro-owner-commission.v1:report','action_ids':['OWN-A04'],
        'support_domain':['Up to 64 explicitly supplied eligible service offers',
            'One currency and exact nonnegative fees and cap','Ascending declared ordinal priority; ties need clarification'],
        'unit_rule':'exact_declared_units_no_conversion','basis_locator':'src/methods/OWNER_COMMISSION.md',
        'basis_sha256':hashlib.sha256(basis.read_bytes()).hexdigest(),'calibration':'mathematical_only',
        'limitations':['No inferred cheapest/best-service preference, consulting fee forecast or real qualification calibration',
            'A fee cap is an authorized procurement limit, never a cash balance or a payment approval',
            'No appointment, independent counterparty acceptance, service delivery, debt or reservation is created']},
        ServiceSelectionInput,ServiceSelectionReport,select_service)
