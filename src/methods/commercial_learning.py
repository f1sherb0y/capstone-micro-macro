"""Finite received-event lesson summary; no automatic capacity improvement."""
import hashlib
from pathlib import Path

from pydantic import Field, model_validator

from src.actions.contracts.common import Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.owner_study_objects import unique_refs

LESSON_METHOD = ref_type('Method')(kind='Method',id='micro.commercial.verified_lesson_summary',version='1')


class CommercialLessonSample(StrictRecord):
    observation_ref: ref_type('Observation')
    event_key: TextId
    outcome_code: TextId


class CommercialLessonInput(StrictRecord):
    samples: list[CommercialLessonSample] = Field(min_length=1,max_length=256)
    outcome_catalog: dict[TextId,TextId]
    source_refs: list[Reference] = Field(min_length=1)

    @model_validator(mode='after')
    def finite_original_domain(self):
        unique_refs(self.source_refs)
        if len({s.event_key for s in self.samples})!=len(self.samples): raise ValueError('Lesson repeats physical received event')
        if not self.outcome_catalog or any(s.outcome_code not in self.outcome_catalog for s in self.samples):
            raise ValueError('Lesson uses outcomes outside original finite catalog')
        return self


class CommercialLessonReport(StrictRecord):
    counts_by_lesson: dict[TextId,int]
    applied_observation_refs: list[ref_type('Observation')]


def summarize_verified_lessons(data: CommercialLessonInput):
    counts={}
    for sample in data.samples:
        code=data.outcome_catalog[sample.outcome_code];counts[code]=counts.get(code,0)+1
    return CommercialLessonReport(counts_by_lesson=counts,applied_observation_refs=[s.observation_ref for s in data.samples])


def register_commercial_learning_method(registry):
    basis=Path(__file__).resolve()
    registry.register({'method_ref':LESSON_METHOD,'namespace':'micro_local','effect_kind':'pure_calculation',
        'invocation':'trusted_processor','input_schema_id':'micro-commercial-learning.v1:input',
        'output_schema_id':'micro-commercial-learning.v1:report','action_ids':['CONTRACTOR-A12','SUPPLIER-A12'],
        'unit_rule':'exact_declared_units_no_conversion','support_domain':['Unique original verified received events','Explicit finite outcome-to-lesson catalog'],
        'basis_locator':'src/methods/commercial_learning.py','basis_sha256':hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration':'mathematical_only','limitations':['Counts do not prove effective learning or improved capacity',
            'No historical work, contract, cash, inventory, obligation or other party knowledge effect']},
        CommercialLessonInput,CommercialLessonReport,summarize_verified_lessons)
