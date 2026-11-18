"""Produce fixed QS A13 rankings without replaying stored normalization."""
from integration.qs_research_normalization_calculations import _prepare_qs_research_comparison_calculation


def prepare_qs_research_ranking_calculation(*, context, action_input, reading,
        calculation_ref, author_authority_ref, validate_current, validate_normalization_provenance):
    """Caller holds actual source guard; produce only one declared ranking.

    Independent gates must verify current cost/criteria/risk applicability and
    retained normalization execution/source lineage in the actual journal.
    A well-shaped normalization projection alone is insufficient. Preserve
    exact tied groups, then save and publish separately before comparison use.
    """
    return _prepare_qs_research_comparison_calculation(context=context, action_input=action_input,
        reading=reading, calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
        validate_current=validate_current, validate_normalization_provenance=validate_normalization_provenance,
        kind='ranking')
