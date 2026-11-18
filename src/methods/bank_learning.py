"""Exact error summaries for explicit probability predictions and verified outcomes."""
from fractions import Fraction
import hashlib
from pathlib import Path
from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, Reference, StrictRecord, ref_type
from src.methods.capacity import ExactAmount
from src.methods.pricing import decimal_fraction

LEARNING_METHOD=ref_type('Method')(kind='Method',id='micro.bank.verified_prediction_error',version='1')


class BankLearningSample(StrictRecord):
    judgment_ref: ref_type('BankJudgment')
    outcome_ref: ref_type('VerifiedOutcome')
    dimension_ref: ref_type('RiskDimension')
    predicted_probability: DecimalString
    occurred: bool


class BankLearningInput(StrictRecord):
    samples: list[BankLearningSample] = Field(min_length=1,max_length=256)
    source_refs: list[Reference] = Field(min_length=1)

    @model_validator(mode='after')
    def explicit_domain(self):
        if any(not 0<=decimal_fraction(s.predicted_probability)<=1 for s in self.samples):
            raise ValueError('Error summary requires original probabilities in [0,1]')
        identities=[(s.judgment_ref.key(),s.outcome_ref.key(),s.dimension_ref.key()) for s in self.samples]
        if len(set(identities))!=len(identities) or len({r.key() for r in self.source_refs})!=len(self.source_refs):
            raise ValueError('Learning repeats original prediction/outcome/dimension or source')
        return self


class BankDimensionError(StrictRecord):
    dimension_ref: ref_type('RiskDimension')
    sample_count: int = Field(gt=0)
    mean_squared_error: ExactAmount


class BankLearningReport(StrictRecord):
    dimensions: list[BankDimensionError]


def summarize_prediction_error(data: BankLearningInput):
    groups={}
    for sample in data.samples:
        difference=decimal_fraction(sample.predicted_probability)-(1 if sample.occurred else 0)
        ref,errors=groups.setdefault(sample.dimension_ref.key(),(sample.dimension_ref,[]));errors.append(difference*difference)
    return BankLearningReport(dimensions=[BankDimensionError(dimension_ref=ref,sample_count=len(errors),
        mean_squared_error=ExactAmount.from_fraction(sum(errors,Fraction())/len(errors))) for ref,errors in groups.values()])


def register_bank_learning_method(registry):
    basis=Path(__file__).resolve()
    registry.register({'method_ref':LEARNING_METHOD,'namespace':'micro_local','effect_kind':'pure_calculation',
        'invocation':'trusted_processor','input_schema_id':'micro-bank-learning.v1:input','output_schema_id':'micro-bank-learning.v1:report',
        'action_ids':['BANK-A12'],'unit_rule':'exact_declared_units_no_conversion',
        'support_domain':['Original explicit probability in [0,1]','Mature independently verified binary event outcome','Exact mean squared error by original risk dimension'],
        'basis_locator':'src/methods/bank_learning.py','basis_sha256':hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration':'mathematical_only','limitations':['Error summary does not calibrate risk or prove effective learning','Only comparable declared event/dimension/horizon predictions','No posterior rewriting of judgments, loans, cash or other banks knowledge']},
        BankLearningInput,BankLearningReport,summarize_prediction_error)
