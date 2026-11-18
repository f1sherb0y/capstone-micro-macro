"""Exact differences of declared design-change cost and duration inputs."""
import hashlib
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from src.actions.contracts.common import Known, Measured, Money, Reference, StrictRecord, TextId, Unknown, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.pricing import decimal_fraction, exact_decimal

ARCHITECT_CHANGE_IMPACT_METHOD = ref_type('Method')(
    kind='Method', id='micro.architect.declared_change_impact', version='1')
ImpactMoneyState = Annotated[Known[Money] | Unknown, Field(discriminator='state')]
ImpactDurationState = Annotated[Known[Measured] | Unknown, Field(discriminator='state')]


class ArchitectChangeImpactArithmeticInput(StrictRecord):
    input_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    basis_ref: ref_type('DesignChangeImpactBasis')
    baseline_cost: ImpactMoneyState
    proposed_cost: ImpactMoneyState
    baseline_duration: ImpactDurationState
    proposed_duration: ImpactDurationState
    currency: TextId
    duration_unit: TextId
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def declared_domain(self):
        unique_refs(self.source_refs)
        if self.basis_ref not in self.source_refs:
            raise ValueError('Change impact input omits its original declared basis')
        if self.duration_unit not in {'s', 'min', 'h', 'day', 'week', 'month', 'year'}:
            raise ValueError('Change impact duration requires a declared supported time unit')
        for state in (self.baseline_cost, self.proposed_cost):
            if isinstance(state, Known) and (
                    state.value.currency != self.currency or decimal_fraction(state.value.value) < 0
                    or state.value.basis_ref not in self.source_refs):
                raise ValueError('Change impact costs require sourced nonnegative values in one currency')
        for state in (self.baseline_duration, self.proposed_duration):
            if isinstance(state, Known) and (
                    state.value.unit != self.duration_unit or decimal_fraction(state.value.value) < 0
                    or state.value.basis_ref not in self.source_refs):
                raise ValueError('Change impact durations require sourced nonnegative values in one exact time unit')
        return self


class ArchitectChangeImpactReport(StrictRecord):
    input_sha256: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
    cost_delta: ImpactMoneyState
    duration_delta: ImpactDurationState
    source_refs: list[Reference]


def _unknown_delta(states, reason):
    refs = {ref.key(): ref for state in states if isinstance(state, Unknown) for ref in state.missing_refs}
    return Unknown(state='unknown', reason_code=reason, missing_refs=list(refs.values()))


def calculate_declared_change_impact(data: ArchitectChangeImpactArithmeticInput):
    """Subtract declared totals; never infer missing inputs or calendar effects."""
    if isinstance(data.baseline_cost, Known) and isinstance(data.proposed_cost, Known):
        cost = Known[Money](state='known', value=Money(
            value=exact_decimal(decimal_fraction(data.proposed_cost.value.value)
                - decimal_fraction(data.baseline_cost.value.value)), currency=data.currency,
            basis_ref=data.proposed_cost.value.basis_ref))
    else:
        cost = _unknown_delta((data.baseline_cost, data.proposed_cost), 'original_change_cost_inputs_unknown')
    if isinstance(data.baseline_duration, Known) and isinstance(data.proposed_duration, Known):
        duration = Known[Measured](state='known', value=Measured(
            value=exact_decimal(decimal_fraction(data.proposed_duration.value.value)
                - decimal_fraction(data.baseline_duration.value.value)), unit=data.duration_unit,
            basis_ref=data.proposed_duration.value.basis_ref))
    else:
        duration = _unknown_delta((data.baseline_duration, data.proposed_duration), 'original_change_duration_inputs_unknown')
    return ArchitectChangeImpactReport(input_sha256=data.input_sha256, cost_delta=cost,
        duration_delta=duration, source_refs=data.source_refs)


def register_architect_change_impact_method(registry):
    basis = Path(__file__).with_name('ARCHITECT_CHANGE_IMPACT.md')
    registry.register({'method_ref': ARCHITECT_CHANGE_IMPACT_METHOD, 'namespace': 'micro_local',
        'effect_kind': 'pure_calculation', 'invocation': 'trusted_processor',
        'input_schema_id': ARCHITECT_CHANGE_IMPACT_METHOD.id + ':input',
        'output_schema_id': ARCHITECT_CHANGE_IMPACT_METHOD.id + ':report',
        'action_ids': ['ARCHITECT-A09'], 'unit_rule': 'exact_declared_units_no_conversion',
        'support_domain': ['Exact differences of independently sourced nonnegative original and proposed totals',
            'One declared currency and one exact declared time unit',
            'Cost and duration remain independently unknown when their original inputs are unknown'],
        'basis_locator': 'src/methods/ARCHITECT_CHANGE_IMPACT.md',
        'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(), 'calibration': 'mathematical_only',
        'limitations': ['No inferred prices, productivity, quantities, critical path, calendars or physical performance',
            'Original and proposed totals need independent same-scope and same-basis native verification',
            'No entitlement, fee liability, contract amendment, task allocation or permitted-use inference']},
        ArchitectChangeImpactArithmeticInput, ArchitectChangeImpactReport, calculate_declared_change_impact)
