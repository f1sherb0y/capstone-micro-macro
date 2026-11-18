"""Exact critical-path bounds from declared original operation intervals."""
import hashlib
from fractions import Fraction
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from src.actions.contracts.common import Measured, Reference, StrictRecord, TextId, ValueState, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.pricing import decimal_fraction, exact_decimal

CONTRACTOR_DURATION_METHOD = ref_type('Method')(kind='Method', id='micro.contractor.declared_duration_bounds', version='1')


class ContractorDurationActivity(StrictRecord):
    local_key: TextId
    predecessor_keys: list[TextId]
    lower: ValueState[Measured]
    upper: ValueState[Measured]
    source_ref: ref_type('Evidence')


class ContractorDurationInput(StrictRecord):
    activities: Annotated[list[ContractorDurationActivity], Field(min_length=1, max_length=64)]
    unit: TextId
    result_basis_ref: ref_type('Evidence')
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def declared_domain(self):
        unique_refs(self.source_refs)
        ids = {row.local_key for row in self.activities}
        if len(ids) != len(self.activities): raise ValueError('Duration schedule repeats an original operation')
        for row in self.activities:
            if len(set(row.predecessor_keys)) != len(row.predecessor_keys) or not set(row.predecessor_keys) <= ids:
                raise ValueError('Duration dependency is repeated or has no original operation')
            for bound in (row.lower, row.upper):
                if bound.state == 'known' and (bound.value.unit != self.unit or decimal_fraction(bound.value.value) < 0):
                    raise ValueError('Duration bounds require one exact time unit and nonnegative amounts')
            if row.lower.state == row.upper.state == 'known' and decimal_fraction(row.lower.value.value) > decimal_fraction(row.upper.value.value):
                raise ValueError('Duration lower bound exceeds original upper bound')
        remaining, ordered = {row.local_key: set(row.predecessor_keys) for row in self.activities}, set()
        while remaining:
            ready = [key for key, predecessors in remaining.items() if predecessors <= ordered]
            if not ready: raise ValueError('Declared duration dependencies contain a cycle')
            for key in ready: ordered.add(key); del remaining[key]
        return self


class ContractorDurationReport(StrictRecord):
    lower: ValueState[Measured]
    upper: ValueState[Measured]


def duration_bounds(data):
    if any(bound.state != 'known' for row in data.activities for bound in (row.lower, row.upper)):
        gap = {'state': 'unknown', 'reason_code': 'original_operation_duration_unknown',
               'missing_refs': [row.source_ref for row in data.activities if row.lower.state != 'known' or row.upper.state != 'known']}
        return ContractorDurationReport(lower=gap, upper=gap)
    remaining, bounds = {row.local_key: row for row in data.activities}, {}
    while remaining:
        ready = [key for key, row in remaining.items() if set(row.predecessor_keys) <= set(bounds)]
        for key in ready:
            row = remaining.pop(key)
            bounds[key] = tuple(max((bounds[p][i] for p in row.predecessor_keys), default=Fraction())
                                + decimal_fraction(bound.value.value) for i, bound in enumerate((row.lower, row.upper)))
    values = [max(pair[i] for pair in bounds.values()) for i in (0, 1)]
    return ContractorDurationReport(**{name: {'state': 'known', 'value': Measured(value=exact_decimal(value),
        unit=data.unit, basis_ref=data.result_basis_ref)} for name, value in zip(('lower', 'upper'), values)})


def register_contractor_advice_method(registry):
    basis = Path(__file__).with_name('CONTRACTOR_ADVICE.md')
    registry.register({'method_ref': CONTRACTOR_DURATION_METHOD, 'namespace': 'micro_local',
        'effect_kind': 'pure_calculation', 'invocation': 'trusted_processor',
        'input_schema_id': CONTRACTOR_DURATION_METHOD.id + ':input', 'output_schema_id': CONTRACTOR_DURATION_METHOD.id + ':report',
        'action_ids': ['CONTRACTOR-A13'], 'support_domain': ['1 to 64 original operations with explicit acyclic dependencies',
            'Declared nonnegative operation duration intervals in one exact unit', 'Independent-resource assumption; maximum path bounds only'],
        'unit_rule': 'exact_declared_units_no_conversion', 'basis_locator': 'src/methods/CONTRACTOR_ADVICE.md',
        'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(), 'calibration': 'mathematical_only',
        'limitations': ['Unknown operation bounds remain unknown; no invented productivity or durations',
            'No crew competition, manufacturing capacity, transport, installation or logistics inferred',
            'Input durations and dependency completeness need original evidence and explicit conditions',
            'Planning estimate only, no construction release, formal delivery date or supply commitment']},
        ContractorDurationInput, ContractorDurationReport, duration_bounds)
