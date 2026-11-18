"""Exact sourced cost adjustments and explicitly weighted bid comparisons."""
from fractions import Fraction
import hashlib
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, Measured, Money, Reference, StrictRecord, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_bid_objects import QSCostAdjustment, QSBidCriterion, QSBidSavedValue
from src.methods.pricing import decimal_fraction, exact_decimal

NORMALIZE_METHOD = ref_type('Method')(kind='Method', id='micro.qs.sourced_bid_normalization', version='1')
RANK_METHOD = ref_type('Method')(kind='Method', id='micro.qs.declared_bid_comparison', version='1')


class NormalizeBid(StrictRecord):
    bid_ref: ref_type('Bid')
    original_price: Money
    fx_rate: DecimalString
    fx_basis_ref: ref_type('Evidence')
    adjustments: list[QSCostAdjustment]


class NormalizeInput(StrictRecord):
    currency: str
    bids: list[NormalizeBid]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def exact_domain(self):
        unique_refs(self.source_refs); unique_refs([r.bid_ref for r in self.bids])
        for row in self.bids:
            if decimal_fraction(row.fx_rate) <= 0 or decimal_fraction(row.original_price.value) < 0:
                raise ValueError('Bid normalization needs positive explicit FX and nonnegative price')
            if row.original_price.currency == self.currency and decimal_fraction(row.fx_rate) != 1:
                raise ValueError('Same-currency normalization cannot invent an exchange adjustment')
            if len({r.difference_key for r in row.adjustments}) != len(row.adjustments): raise ValueError('Cost difference counted twice')
            if any(r.amount.currency != self.currency for r in row.adjustments): raise ValueError('Adjustments require the declared target currency')
        return self


class NormalizeReport(StrictRecord):
    prices: list[QSBidSavedValue]


def normalize_bids(data):
    prices=[]
    for row in data.bids:
        value=decimal_fraction(row.original_price.value)*decimal_fraction(row.fx_rate)
        value+=sum((decimal_fraction(r.amount.value) for r in row.adjustments),Fraction())
        if value < 0: raise ValueError('Declared normalization yields a negative comparison price')
        prices.append(QSBidSavedValue(bid_ref=row.bid_ref, normalized_price=Money(
            value=exact_decimal(value),currency=data.currency,basis_ref=row.fx_basis_ref)))
    return NormalizeReport(prices=prices)


class ComparableBid(StrictRecord):
    bid_ref: ref_type('Bid')
    price: Money
    risk: Measured | None


class BidRankInput(StrictRecord):
    criteria: Annotated[list[QSBidCriterion], Field(min_length=1)]
    bids: list[ComparableBid]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def declared_comparison(self):
        unique_refs(self.source_refs);unique_refs([r.bid_ref for r in self.bids])
        if len({r.metric for r in self.criteria})!=len(self.criteria):raise ValueError('Comparison repeats a metric')
        for criterion in self.criteria:
            if decimal_fraction(criterion.weight)<=0 or decimal_fraction(criterion.scale)<=0:raise ValueError('Comparison weights and scales must be positive')
            for bid in self.bids:
                value=bid.price if criterion.metric=='price' else bid.risk
                if value is None:raise ValueError('Unknown risk cannot be ranked')
                unit=value.currency if criterion.metric=='price' else value.unit
                if unit!=criterion.unit or decimal_fraction(value.value)<0:raise ValueError('Comparison metric is negative or uses another unit')
        return self


class BidRankReport(StrictRecord):
    ranked_groups: list[list[ref_type('Bid')]]


def rank_bids(data):
    groups={}
    for bid in data.bids:
        score=Fraction()
        for criterion in data.criteria:
            metric=bid.price if criterion.metric=='price' else bid.risk
            score+=decimal_fraction(metric.value)*decimal_fraction(criterion.weight)/decimal_fraction(criterion.scale)
        groups.setdefault(score,[]).append(bid.bid_ref)
    return BidRankReport(ranked_groups=[sorted(groups[score],key=lambda r:repr(r.key())) for score in sorted(groups)])


def register_qs_bid_methods(registry):
    basis=Path(__file__).with_name('QS_BID.md')
    for method,input_model,output_model,executor,domain in [
        (NORMALIZE_METHOD,NormalizeInput,NormalizeReport,normalize_bids,['Original nonnegative prices; explicit positive FX coefficient','Exactly declared signed target-currency scope/region/time adjustments; no inferred conversion']),
        (RANK_METHOD,BidRankInput,BidRankReport,rank_bids,['Known eligible comparison prices and supplied nonnegative risk metrics','Explicit positive weights and scales; lower exact weighted sum preferred; equal scores remain tied']),
    ]:
        registry.register({'method_ref':method,'namespace':'micro_local','effect_kind':'pure_calculation','invocation':'trusted_processor',
            'input_schema_id':method.id+':input','output_schema_id':method.id+':report','action_ids':['QS-A06'],
            'support_domain':domain,'unit_rule':'exact_sourced_monetary_conversion' if method==NORMALIZE_METHOD else 'exact_declared_units_no_conversion','basis_locator':'src/methods/QS_BID.md',
            'basis_sha256':hashlib.sha256(basis.read_bytes()).hexdigest(),'calibration':'mathematical_only',
            'limitations':['No inferred FX, regional/time uplift, scope valuation, qualification, compliance or risk judgment',
                'Conversion/adjustment coefficients and criteria require original evidence and separate real calibration',
                'Normalization never reprices the saved bid; ranking is advice, with no award, contract or payment effect']},
            input_model,output_model,executor)
