from copy import deepcopy

import pytest

from integration.action_catalog import build_catalog, initial_coverage, validate_coverage


def test_complete_source_inventory_and_dependencies():
    catalog = build_catalog()
    assert len(catalog["actions"]) == 106
    assert set(a["implementation_batch"] for a in catalog["actions"]) == {"P4", "P5", "P6"}
    for action in catalog["actions"]:
        assert action["checks"] and action["role_checks"]
        assert action["local_type_definitions"] and action["role_method_dependencies"]
        assert set(action["binding_gaps"]) == set(action["choices"])
        assert all(gap["status"] == "unverified" for gap in action["binding_gaps"].values())
    validate_coverage(catalog, initial_coverage(catalog))


@pytest.mark.parametrize("mutation", ["duplicate", "source", "batch", "branch"])
def test_coverage_cannot_hide_missing_or_stale_action(mutation):
    catalog = build_catalog()
    coverage = deepcopy(initial_coverage(catalog))
    if mutation == "duplicate":
        coverage["actions"][1] = deepcopy(coverage["actions"][0])
    elif mutation == "source":
        coverage["actions"][0]["source_sha256"] = "stale"
    elif mutation == "batch":
        coverage["actions"][0]["implementation_batch"] = "P6"
    else:
        coverage["actions"][0]["branches"].pop("ignore")
    with pytest.raises(ValueError):
        validate_coverage(catalog, coverage)
