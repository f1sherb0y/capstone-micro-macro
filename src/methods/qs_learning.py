"""Exact forecast errors only for explicitly comparable original cost bases."""
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import Money, Reference, StrictRecord, TextId, ValueState, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.capacity import ExactAmount
from src.methods.pricing import decimal_fraction, exact_decimal
from src.methods.qs_cost import unknown

COMPARABILITY_METHOD = ref_type('Method')(kind='Method',id='micro.qs.original_forecast_comparability',version='1')
ERROR_METHOD = ref_type('Method')(kind='Method',id='micro.qs.comparable_forecast_error',version='1')


class QSForecastBasis(StrictRecord):
    component_keys: list[TextId] = Field(min_length=1)
    region_id: TextId
    currency: TextId
    price_date_code: TextId
    quantity_basis_code: TextId
    scope_version_code: TextId
    tax_basis_code: TextId
    price_basis_code: TextId


class QSForecastComparisonInput(StrictRecord):
    forecast_ref: ref_type('CostPlan')
    outcome_ref: ref_type('Outcome')
    forecast_basis: QSForecastBasis
    outcome_basis: QSForecastBasis
    forecast_total: ValueState[Money]
    outcome_total: ValueState[Money]
    source_refs: list[Reference] = Field(min_length=1)

    @model_validator(mode='after')
    def exact_domain(self):
        unique_refs(self.source_refs)
        for basis,value in [(self.forecast_basis,self.forecast_total),(self.outcome_basis,self.outcome_total)]:
            if len(set(basis.component_keys))!=len(basis.component_keys): raise ValueError('Forecast comparison repeats physical component')
            if value.state=='known' and (value.value.currency!=basis.currency or decimal_fraction(value.value.value)<0):
                raise ValueError('Forecast comparison changes original currency or uses negative costs')
        return self


class QSSignedExactError(ExactAmount):
    numerator: int


class QSForecastComparisonReport(StrictRecord):
    comparable: bool
    differing_fields: list[TextId]
    status: Literal['comparable','incomparable','unknown_amount']
    signed_error: ValueState[Money]
    relative_error: QSSignedExactError | None


def compare_original_forecast(data: QSForecastComparisonInput):
    fields=list(QSForecastBasis.model_fields)
    differing=[f for f in fields if (set(data.forecast_basis.component_keys)!=set(data.outcome_basis.component_keys)
        if f=='component_keys' else getattr(data.forecast_basis,f)!=getattr(data.outcome_basis,f))]
    if differing:
        return QSForecastComparisonReport(comparable=False,differing_fields=differing,status='incomparable',
            signed_error=unknown('forecast_outcome_not_comparable'),relative_error=None)
    if data.forecast_total.state!='known' or data.outcome_total.state!='known':
        return QSForecastComparisonReport(comparable=True,differing_fields=[],status='unknown_amount',
            signed_error=unknown('original_forecast_or_outcome_amount_unknown'),relative_error=None)
    forecast=decimal_fraction(data.forecast_total.value.value);actual=decimal_fraction(data.outcome_total.value.value)
    error=actual-forecast
    return QSForecastComparisonReport(comparable=True,differing_fields=[],status='comparable',
        signed_error={'state':'known','value':Money(value=exact_decimal(error),currency=data.forecast_basis.currency,
            basis_ref=data.outcome_total.value.basis_ref)},relative_error=None if forecast==0 else QSSignedExactError.from_fraction(error/forecast))


def register_qs_learning_methods(registry):
    basis=Path(__file__).resolve()
    for method,stage in [(COMPARABILITY_METHOD,'comparability'),(ERROR_METHOD,'error')]:
        registry.register({'method_ref':method,'namespace':'micro_local','effect_kind':'pure_calculation',
            'invocation':'trusted_processor','input_schema_id':'micro-qs-learning.v1:input','output_schema_id':'micro-qs-learning.v1:report',
            'action_ids':['QS-A12'],'unit_rule':'exact_declared_units_no_conversion',
            'support_domain':['Original fixed component identities, scope version, region, quantity/tax/price basis and price date',
                'Same original currency without conversion','Exact signed absolute and rational relative error; zero forecast has no relative error'],
            'basis_locator':'src/methods/qs_learning.py','basis_sha256':hashlib.sha256(basis.read_bytes()).hexdigest(),
            'calibration':'mathematical_only','limitations':['Declared comparison basis requires independent factual support',
                'No retrospective forecast rewrite or proof of effective calibration','No private-cost disclosure, capability, engineering or cash effect']},
            QSForecastComparisonInput,QSForecastComparisonReport,compare_original_forecast)
