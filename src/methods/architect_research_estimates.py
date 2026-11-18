"""Architect investigation estimates from sourced work quantities and rates."""
import hashlib
from pathlib import Path

from src.actions.contracts.common import ref_type
from src.methods.engineer_research_estimates import (
    EngineerResearchEstimateInput, EngineerResearchEstimateReport, estimate_declared_research,
)

ARCHITECT_RESEARCH_ESTIMATE_METHOD = ref_type('Method')(
    kind='Method', id='micro.architect.declared_research_estimate', version='1')


class ArchitectResearchEstimateInput(EngineerResearchEstimateInput):
    """Same exact sourced arithmetic domain with an independent Architect method."""


class ArchitectResearchEstimateReport(EngineerResearchEstimateReport):
    """Declared effort and cost; no task, resource, fee or cash effect."""


def estimate_declared_architect_research(data: ArchitectResearchEstimateInput):
    return ArchitectResearchEstimateReport.model_validate(
        estimate_declared_research(data).model_dump(mode='python'))


def register_architect_research_estimate_method(registry):
    basis = Path(__file__).with_name('ARCHITECT_RESEARCH_ESTIMATES.md')
    registry.register({'method_ref': ARCHITECT_RESEARCH_ESTIMATE_METHOD, 'namespace': 'micro_local',
        'effect_kind': 'pure_calculation', 'invocation': 'trusted_processor',
        'input_schema_id': ARCHITECT_RESEARCH_ESTIMATE_METHOD.id + ':input',
        'output_schema_id': ARCHITECT_RESEARCH_ESTIMATE_METHOD.id + ':report',
        'action_ids': ['ARCHITECT-A13'],
        'support_domain': ['Positive sourced work quantity and effort per declared work unit',
            'Nonnegative sourced effort rate and fixed cost in one exact currency',
            'Exact finite decimal multiplication and addition with retained original sources'],
        'unit_rule': 'exact_declared_units_no_conversion',
        'basis_locator': 'src/methods/ARCHITECT_RESEARCH_ESTIMATES.md',
        'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(), 'calibration': 'mathematical_only',
        'limitations': ['Work quantity, effort and rates require independent original source support',
            'No inferred productivity, site condition, duration, market calibration or feasibility',
            'No investigation task, resource reservation, incurred fee, cash effect or approval']},
        ArchitectResearchEstimateInput, ArchitectResearchEstimateReport, estimate_declared_architect_research)
