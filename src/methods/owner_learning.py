"""Exact declared score smoothing; evidence of learning effectiveness is separate."""
import hashlib
from pathlib import Path
from pydantic import Field, model_validator

from src.actions.contracts.common import DecimalString, Reference, StrictRecord, TextId, ref_type
from src.methods.pricing import decimal_fraction, exact_decimal

LEARNING_METHOD = ref_type('Method')(kind='Method',id='micro.owner.declared_evidence_update',version='1')


class OwnerLearningSample(StrictRecord):
    observation_ref: ref_type('Observation')
    dimension_code: TextId
    outcome_score: DecimalString
    learning_rate: DecimalString


class OwnerLearningInput(StrictRecord):
    previous_scores: dict[TextId,DecimalString]
    samples: list[OwnerLearningSample] = Field(min_length=1,max_length=256)
    source_refs: list[Reference] = Field(min_length=1)

    @model_validator(mode='after')
    def declared_domain(self):
        if not self.previous_scores or len(self.previous_scores)>64:
            raise ValueError('Learning requires a finite declared preference domain')
        pairs=[(s.observation_ref.key(),s.dimension_code) for s in self.samples]
        if len(set(pairs))!=len(pairs) or len({r.key() for r in self.source_refs})!=len(self.source_refs):
            raise ValueError('Learning evidence/dimension or source repeated')
        values=[*self.previous_scores.values(),*[s.outcome_score for s in self.samples],*[s.learning_rate for s in self.samples]]
        if any(not 0<=decimal_fraction(v)<=1 for v in values) or any(s.dimension_code not in self.previous_scores for s in self.samples):
            raise ValueError('Learning scores/rates must lie in [0,1] in original dimensions')
        return self


class OwnerLearningReport(StrictRecord):
    updated_scores: dict[TextId,DecimalString]
    applied_observation_refs: list[ref_type('Observation')]


def update_declared_scores(data: OwnerLearningInput):
    scores={key:decimal_fraction(value) for key,value in data.previous_scores.items()};applied={}
    for sample in data.samples:
        prior=scores[sample.dimension_code]
        scores[sample.dimension_code]=prior+decimal_fraction(sample.learning_rate)*(decimal_fraction(sample.outcome_score)-prior)
        applied[sample.observation_ref.key()]=sample.observation_ref
    return OwnerLearningReport(updated_scores={key:exact_decimal(value) for key,value in scores.items()},applied_observation_refs=list(applied.values()))


def register_owner_learning_method(registry):
    basis=Path(__file__).resolve()
    registry.register({'method_ref':LEARNING_METHOD,'namespace':'micro_local','effect_kind':'pure_calculation',
        'invocation':'trusted_processor','input_schema_id':'micro-owner-learning.v1:input','output_schema_id':'micro-owner-learning.v1:report',
        'action_ids':['OWN-A15'],'unit_rule':'exact_declared_units_no_conversion',
        'support_domain':['Explicit chronologically ordered verified outcome scores','Declared scores and smoothing rates in [0,1]','Original finite preference dimensions','Exact finite decimal updates'],
        'basis_locator':'src/methods/owner_learning.py','basis_sha256':hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration':'mathematical_only','limitations':['Scenario-declared scores are not calibrated investment performance','No proof of improved decisions or causal learning','No historical, cash, debt or resource effect']},
        OwnerLearningInput,OwnerLearningReport,update_declared_scores)
