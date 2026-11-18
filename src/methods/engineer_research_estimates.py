"""Sourced inputs for finite research work estimates in exact declared units."""
import hashlib
from pathlib import Path

from pydantic import Field, model_validator

from src.actions.contracts.common import Measured, Money, Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.pricing import decimal_fraction, exact_decimal

ENGINEER_RESEARCH_ESTIMATE_METHOD = ref_type('Method')(
    kind='Method', id='micro.engineer.declared_research_estimate', version='1')


class EngineerResearchEstimateInput(StrictRecord):
    work_profile_ref: ref_type('WorkProfile')
    quantity: Measured
    effort_per_unit: Measured
    effort_quantity_unit: TextId
    cost_per_effort: Money
    cost_effort_unit: TextId
    fixed_cost: Money
    source_refs: list[Reference] = Field(min_length=1)

    @model_validator(mode='after')
    def exact_sourced_units(self):
        unique_refs(self.source_refs)
        if (self.quantity.unit != self.effort_quantity_unit
                or self.effort_per_unit.unit != self.cost_effort_unit
                or self.cost_per_effort.currency != self.fixed_cost.currency
                or decimal_fraction(self.quantity.value) <= 0 or decimal_fraction(self.effort_per_unit.value) <= 0
                or decimal_fraction(self.cost_per_effort.value) < 0 or decimal_fraction(self.fixed_cost.value) < 0):
            raise ValueError('Research estimate requires positive sourced work and exact nonnegative compatible costs')
        if not {self.work_profile_ref, self.quantity.basis_ref, self.effort_per_unit.basis_ref,
                self.cost_per_effort.basis_ref, self.fixed_cost.basis_ref} <= set(self.source_refs):
            raise ValueError('Research estimate input omits original work or numeric basis references')
        return self


class EngineerResearchEstimateReport(StrictRecord):
    effort: Measured
    estimated_cost: Money
    source_refs: list[Reference]


def estimate_declared_research(data: EngineerResearchEstimateInput):
    """Multiply original sourced quantities and rates without inferred inputs."""
    effort = decimal_fraction(data.quantity.value) * decimal_fraction(data.effort_per_unit.value)
    cost = effort * decimal_fraction(data.cost_per_effort.value) + decimal_fraction(data.fixed_cost.value)
    return EngineerResearchEstimateReport(
        effort=Measured(value=exact_decimal(effort), unit=data.effort_per_unit.unit,
            basis_ref=data.effort_per_unit.basis_ref),
        estimated_cost=Money(value=exact_decimal(cost), currency=data.cost_per_effort.currency,
            basis_ref=data.cost_per_effort.basis_ref),
        source_refs=data.source_refs)


def register_engineer_research_estimate_method(registry):
    basis = Path(__file__).with_name('ENGINEER_RESEARCH_ESTIMATES.md')
    registry.register({'method_ref': ENGINEER_RESEARCH_ESTIMATE_METHOD, 'namespace': 'micro_local',
        'effect_kind': 'pure_calculation', 'invocation': 'trusted_processor',
        'input_schema_id': ENGINEER_RESEARCH_ESTIMATE_METHOD.id + ':input',
        'output_schema_id': ENGINEER_RESEARCH_ESTIMATE_METHOD.id + ':report',
        'action_ids': ['ENGINEER-A13'],
        'support_domain': ['Sourced positive work quantity and effort per declared work unit',
            'Nonnegative sourced effort rate and fixed cost in one exact currency',
            'Exact finite decimal multiplication and addition with retained source references'],
        'unit_rule': 'exact_declared_units_no_conversion',
        'basis_locator': 'src/methods/ENGINEER_RESEARCH_ESTIMATES.md',
        'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(), 'calibration': 'mathematical_only',
        'limitations': ['Work quantities, effort and rates require independent original source support',
            'No inferred productivity, observed site work, market calibration, duration or feasibility',
            'No investigation task, budget reservation, incurred fee, cash effect or professional approval']},
        EngineerResearchEstimateInput, EngineerResearchEstimateReport, estimate_declared_research)
