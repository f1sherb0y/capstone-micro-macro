"""Pareto comparison of known, explicitly selected original metrics."""
import hashlib
from pathlib import Path

from pydantic import model_validator

from src.actions.contracts.common import Measured, Reference, StrictRecord, ref_type
from src.actions.contracts.architect_research_objects import ArchitectResearchCriterion
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.pricing import decimal_fraction

ARCHITECT_COMPARE_METHOD = ref_type('Method')(kind='Method', id='micro.architect.declared_option_comparison', version='1')


class ArchitectComparableOption(StrictRecord):
    option_ref: ref_type('DesignOption')
    values: list[Measured]


class ArchitectComparisonInput(StrictRecord):
    criteria: list[ArchitectResearchCriterion]
    options: list[ArchitectComparableOption]
    source_refs: list[Reference]

    @model_validator(mode='after')
    def exact_domain(self):
        if not self.criteria or not self.options or not self.source_refs:
            raise ValueError('Comparison needs declared criteria, options and sources')
        if len({(row.source, row.code) for row in self.criteria}) != len(self.criteria):
            raise ValueError('Comparison repeats a selected criterion')
        unique_refs([row.option_ref for row in self.options]); unique_refs(self.source_refs)
        for option in self.options:
            if len(option.values) != len(self.criteria):
                raise ValueError('Comparison needs each selected original metric')
            if any(value.unit != criterion.unit for value, criterion in zip(option.values, self.criteria)):
                raise ValueError('Comparison does not infer unit/currency conversions')
        return self


class ArchitectComparisonReport(StrictRecord):
    recommended_option_refs: list[ref_type('DesignOption')]


def compare_options(data):
    values = [[decimal_fraction(row.value) * (1 if criterion.direction == 'minimize' else -1)
               for row, criterion in zip(option.values, data.criteria)] for option in data.options]
    recommended = []
    for i, option in enumerate(data.options):
        if not any(j != i and all(a <= b for a, b in zip(other, values[i]))
                   and any(a < b for a, b in zip(other, values[i])) for j, other in enumerate(values)):
            recommended.append(option.option_ref)
    return ArchitectComparisonReport(recommended_option_refs=recommended)


def register_architect_research_method(registry):
    basis = Path(__file__).with_name('ARCHITECT_RESEARCH.md')
    registry.register({'method_ref': ARCHITECT_COMPARE_METHOD, 'namespace': 'micro_local',
        'effect_kind': 'pure_calculation', 'invocation': 'trusted_processor',
        'input_schema_id': ARCHITECT_COMPARE_METHOD.id + ':input', 'output_schema_id': ARCHITECT_COMPARE_METHOD.id + ':report',
        'action_ids': ['ARCHITECT-A13', 'ARCHITECT-A05'], 'support_domain': ['Known selected metrics in exact declared units',
            'Explicit minimize/maximize directions; Pareto nondominance retains equal and conflicting alternatives'],
        'unit_rule': 'exact_declared_units_no_conversion', 'basis_locator': 'src/methods/ARCHITECT_RESEARCH.md',
        'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(), 'calibration': 'mathematical_only',
        'limitations': ['No guessed weights, scalar score, strict ranking, unit conversion or inferred site condition',
            'No design, professional, cost, investment or permit approval; source metrics require independent calibration']},
        ArchitectComparisonInput, ArchitectComparisonReport, compare_options)
