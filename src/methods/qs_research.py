"""Exact supplied cost adjustments and explicitly selected preliminary comparison."""
from fractions import Fraction
import hashlib
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, Measured, Money, Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_bid_objects import QSCostAdjustment, QSBidCriterion
from src.actions.contracts.qs_research_objects import QSResearchNormalizedCost
from src.methods.pricing import decimal_fraction, exact_decimal

RESEARCH_NORMALIZE_METHOD=ref_type('Method')(kind='Method',id='micro.qs.sourced_plan_normalization',version='1')
RESEARCH_RANK_METHOD=ref_type('Method')(kind='Method',id='micro.qs.declared_plan_comparison',version='1')


class ResearchCostAdjustment(StrictRecord):
    plan_ref: ref_type('CostPlan')
    original_amount: Money
    fx_rate: DecimalString
    fx_basis_ref: ref_type('Evidence')
    adjustments: list[QSCostAdjustment]


class ResearchNormalizationInput(StrictRecord):
    currency: TextId
    plans: list[ResearchCostAdjustment]
    source_refs: Annotated[list[Reference],Field(min_length=1)]

    @model_validator(mode='after')
    def sourced_domain(self):
        unique_refs(self.source_refs);unique_refs([r.plan_ref for r in self.plans])
        for row in self.plans:
            if decimal_fraction(row.original_amount.value)<0 or decimal_fraction(row.fx_rate)<=0:raise ValueError('Original cost and FX domain invalid')
            if row.original_amount.currency==self.currency and decimal_fraction(row.fx_rate)!=1:raise ValueError('Same-currency FX must be one')
            if len({r.difference_key for r in row.adjustments})!=len(row.adjustments):raise ValueError('Cost normalization repeats a difference')
            if any(r.amount.currency!=self.currency for r in row.adjustments):raise ValueError('Normalization adjustments use another currency')
        return self


class ResearchNormalizationReport(StrictRecord):
    normalized_costs: list[QSResearchNormalizedCost]


def normalize_plans(data):
    rows=[]
    for plan in data.plans:
        amount=decimal_fraction(plan.original_amount.value)*decimal_fraction(plan.fx_rate)
        amount+=sum((decimal_fraction(r.amount.value) for r in plan.adjustments),Fraction())
        if amount<0:raise ValueError('Normalized comparison cost cannot be negative')
        rows.append(QSResearchNormalizedCost(plan_ref=plan.plan_ref,amount=Money(value=exact_decimal(amount),currency=data.currency,basis_ref=plan.fx_basis_ref)))
    return ResearchNormalizationReport(normalized_costs=rows)


class ResearchComparablePlan(StrictRecord):
    option_ref: ref_type('DesignOption')
    price: Money
    risk: Measured | None


class ResearchRankInput(StrictRecord):
    criteria: Annotated[list[QSBidCriterion],Field(min_length=1)]
    options: list[ResearchComparablePlan]
    source_refs: Annotated[list[Reference],Field(min_length=1)]

    @model_validator(mode='after')
    def selected_domain(self):
        unique_refs(self.source_refs);unique_refs([r.option_ref for r in self.options])
        if len({r.metric for r in self.criteria})!=len(self.criteria):raise ValueError('Research criterion repeated')
        for criterion in self.criteria:
            if decimal_fraction(criterion.weight)<=0 or decimal_fraction(criterion.scale)<=0:raise ValueError('Weights/scales must be explicitly positive')
            for option in self.options:
                value=option.price if criterion.metric=='price' else option.risk
                if value is None:raise ValueError('Unknown uncertainty cannot be scored')
                unit=value.currency if criterion.metric=='price' else value.unit
                if unit!=criterion.unit or decimal_fraction(value.value)<0:raise ValueError('Criterion unit or amount is unsupported')
        return self


class ResearchRankReport(StrictRecord):
    ranked_groups: list[list[ref_type('DesignOption')]]


def rank_plans(data):
    scores={}
    for option in data.options:
        score=Fraction()
        for criterion in data.criteria:
            value=option.price if criterion.metric=='price' else option.risk
            score+=decimal_fraction(value.value)*decimal_fraction(criterion.weight)/decimal_fraction(criterion.scale)
        scores.setdefault(score,[]).append(option.option_ref)
    return ResearchRankReport(ranked_groups=[sorted(scores[v],key=lambda r:repr(r.key())) for v in sorted(scores)])


def register_qs_research_methods(registry):
    basis=Path(__file__).with_name('QS_RESEARCH.md')
    for method,input_model,output_model,executor,unit_rule,domain in [
        (RESEARCH_NORMALIZE_METHOD,ResearchNormalizationInput,ResearchNormalizationReport,normalize_plans,'exact_sourced_monetary_conversion',
            ['Saved complete scoped A04 costs','Explicit sourced positive FX and target-currency scope/region/time/dimension adjustments; no inferred conversion']),
        (RESEARCH_RANK_METHOD,ResearchRankInput,ResearchRankReport,rank_plans,'exact_declared_units_no_conversion',
            ['Comparable submitted cost plans and known selected uncertainty metrics','Explicit positive weights/scales; lower exact score preferred; ties preserved']),
    ]:
        registry.register({'method_ref':method,'namespace':'micro_local','effect_kind':'pure_calculation','invocation':'trusted_processor',
            'input_schema_id':method.id+':input','output_schema_id':method.id+':report','action_ids':['QS-A13'],
            'support_domain':domain,'unit_rule':unit_rule,'basis_locator':'src/methods/QS_RESEARCH.md',
            'basis_sha256':hashlib.sha256(basis.read_bytes()).hexdigest(),'calibration':'mathematical_only',
            'limitations':['No new A04 estimate, inferred prices, FX, scope allowance, professional finding or uncertainty',
                'Only verifies declared comparison arithmetic; real normalization and criteria require independent calibration',
                'No investment approval, supplier lock, capacity, incurred cost, debt or cash effect']},input_model,output_model,executor)
