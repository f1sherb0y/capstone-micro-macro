"""Declared feedback rules and training estimates; no claim of improved ability."""
import hashlib
from pathlib import Path

from pydantic import Field, model_validator

from src.actions.contracts.common import Measured, Money, Reference, StrictRecord, TextId, ref_type
from src.methods.pricing import decimal_fraction, exact_decimal

LEARNING_METHOD = ref_type('Method')(kind='Method', id='micro.architect.declared_feedback_rules', version='1')
TRAINING_METHOD = ref_type('Method')(kind='Method', id='micro.architect.declared_training_estimate', version='1')


class ArchitectFeedbackSample(StrictRecord):
    feedback_ref: ref_type('Feedback')
    event_key: TextId
    dimension_ref: ref_type('JudgmentDimension')
    outcome_code: TextId


class ArchitectFeedbackRule(StrictRecord):
    rule_ref: ref_type('LearningRule')
    dimension_ref: ref_type('JudgmentDimension')
    outcome_codes: list[TextId] = Field(min_length=1)
    selected_value_ref: ref_type('JudgmentValue')
    minimum_samples: int = Field(ge=1)
    priority: int = Field(ge=0)


class ArchitectFeedbackInput(StrictRecord):
    samples: list[ArchitectFeedbackSample] = Field(min_length=1, max_length=256)
    rules: list[ArchitectFeedbackRule] = Field(min_length=1, max_length=128)
    source_refs: list[Reference] = Field(min_length=1)

    @model_validator(mode='after')
    def finite_domain(self):
        pairs=[(s.event_key,s.dimension_ref.key()) for s in self.samples]
        priorities=[(r.dimension_ref.key(),r.priority) for r in self.rules]
        if (len(set(pairs))!=len(pairs) or len(set(priorities))!=len(priorities)
                or len({r.rule_ref.key() for r in self.rules})!=len(self.rules)
                or len({r.key() for r in self.source_refs})!=len(self.source_refs)):
            raise ValueError('Feedback repeats physical event/dimension, rule priority or source')
        if any(len(set(r.outcome_codes))!=len(r.outcome_codes) for r in self.rules):
            raise ValueError('Feedback rule repeats an outcome code')
        return self


class ArchitectFeedbackSelection(StrictRecord):
    rule_ref: ref_type('LearningRule')
    dimension_ref: ref_type('JudgmentDimension')
    selected_value_ref: ref_type('JudgmentValue')
    feedback_refs: list[ref_type('Feedback')]


class ArchitectFeedbackReport(StrictRecord):
    selections: list[ArchitectFeedbackSelection]


def apply_declared_feedback_rules(data: ArchitectFeedbackInput):
    selected={}
    for rule in sorted(data.rules,key=lambda r:r.priority):
        key=rule.dimension_ref.key()
        if key in selected: continue
        samples=[s for s in data.samples if s.dimension_ref==rule.dimension_ref and s.outcome_code in rule.outcome_codes]
        if len(samples)<rule.minimum_samples: continue
        refs={s.feedback_ref.key():s.feedback_ref for s in samples}
        selected[key]=ArchitectFeedbackSelection(rule_ref=rule.rule_ref,dimension_ref=rule.dimension_ref,
            selected_value_ref=rule.selected_value_ref,feedback_refs=list(refs.values()))
    return ArchitectFeedbackReport(selections=list(selected.values()))


class ArchitectTrainingInput(StrictRecord):
    work_profile_ref: ref_type('WorkProfile')
    participant_ids: list[TextId] = Field(min_length=1, max_length=256)
    sessions: int = Field(ge=1, le=256)
    per_participant_effort: Measured
    cost_per_effort: Money
    cost_effort_unit: TextId
    fixed_cost: Money
    source_refs: list[Reference] = Field(min_length=1)

    @model_validator(mode='after')
    def sourced_estimate_domain(self):
        if (len(set(self.participant_ids))!=len(self.participant_ids)
                or len({r.key() for r in self.source_refs})!=len(self.source_refs)
                or self.per_participant_effort.unit!=self.cost_effort_unit
                or self.cost_per_effort.currency!=self.fixed_cost.currency
                or decimal_fraction(self.per_participant_effort.value)<=0
                or decimal_fraction(self.cost_per_effort.value)<0 or decimal_fraction(self.fixed_cost.value)<0):
            raise ValueError('Training estimate requires unique participants, positive sourced effort and compatible nonnegative costs')
        return self


class ArchitectTrainingReport(StrictRecord):
    effort: Measured
    estimated_cost: Money


def estimate_declared_training(data: ArchitectTrainingInput):
    effort=decimal_fraction(data.per_participant_effort.value)*len(data.participant_ids)*data.sessions
    cost=effort*decimal_fraction(data.cost_per_effort.value)+decimal_fraction(data.fixed_cost.value)
    return ArchitectTrainingReport(effort=Measured(value=exact_decimal(effort),unit=data.per_participant_effort.unit,
        basis_ref=data.per_participant_effort.basis_ref),estimated_cost=Money(value=exact_decimal(cost),
        currency=data.cost_per_effort.currency,basis_ref=data.cost_per_effort.basis_ref))


def register_architect_learning_methods(registry):
    basis=Path(__file__).resolve()
    for ref,code,inputs,outputs,executor,domain in (
        (LEARNING_METHOD,'feedback',ArchitectFeedbackInput,ArchitectFeedbackReport,apply_declared_feedback_rules,
         ['Finite authorized dimension/value/outcome catalogs','Unique verified physical feedback events','Explicit per-dimension rule priorities and sample thresholds']),
        (TRAINING_METHOD,'training',ArchitectTrainingInput,ArchitectTrainingReport,estimate_declared_training,
         ['Explicit participants and sessions','Sourced effort per participant/session and compatible cost rates','Exact finite decimal cost and effort estimates'])):
        registry.register({'method_ref':ref,'namespace':'micro_local','effect_kind':'pure_calculation',
            'invocation':'trusted_processor','input_schema_id':f'micro-architect-learning.v1:{code}-input',
            'output_schema_id':f'micro-architect-learning.v1:{code}-report','action_ids':['ARCHITECT-A12','ENGINEER-A12','QS-A12'],
            'unit_rule':'exact_declared_units_no_conversion','support_domain':domain,
            'basis_locator':'src/methods/architect_learning.py','basis_sha256':hashlib.sha256(basis.read_bytes()).hexdigest(),
            'calibration':'mathematical_only','limitations':['Declared rules and rates require independent factual support',
                'No proof of safety, market laws, qualifications or improved capability',
                'No historical engineering, resource, cash or qualification effect']},inputs,outputs,executor)
