"""Clearly synthetic eight-role initial data for local contract validation."""
from __future__ import annotations

import argparse
from pathlib import Path

from integration.data_migrations import MigrationBuilder, MigrationSelection
from integration.scenario_v2 import ScenarioV2


def eight_role_scenario(run_id="synthetic-eight-role-v1") -> ScenarioV2:
    roles = ["Owner", "Bank", "Architect", "Engineer", "QS", "Government", "Contractor", "Supplier"]
    mapping = {f"synthetic:{role}": f"fixture-{role.lower()}" for role in roles}
    selection = MigrationSelection.model_validate({"run_id": run_id, "project_ids": [], "project_owner_ids": {},
        "identities": [{"source_id": source, "organization_id": key, "actor_id": key + "-actor", "roles": [role],
                        "assignment_note": "Synthetic role institution with fixture-only functions; no claim about real qualification"}
                       for (source, key), role in zip(mapping.items(), roles)],
        "manifest": {"data_version": "eight-role-fixture.v1", "schema_version": "scenario.v2", "macro_version": "unbound",
                     "method_versions": {}, "skill_versions": {}, "prompt_versions": {}, "model_provider": "offline_fixture",
                     "model_name": "none", "model_configuration_hash": "0" * 64, "seed": 42, "mode": "role_contract",
                     "identity_mapping": mapping, "source_hashes": {}}})
    builder = MigrationBuilder(selection, {}, fixture=True)
    organizations = []
    for identity in selection.identities:
        organization = builder.organization(identity, identity.roles[0] + " fixture", "Synthetic test institution", "synthetic:role-fixtures")
        organizations.append(organization)
    parameters = builder.missing_parameters(mapping.values())
    for record in builder.evidence:
        record["source_kind"] = "synthetic"
        record["basis_kind"] = "assumed"
    snapshot, _ = builder.finish(organizations, [], parameters)
    return ScenarioV2.model_validate({**snapshot.model_dump(mode="json"), "fixture": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--refresh-test-fixture", action="store_true")
    args = parser.parse_args()
    scenario = eight_role_scenario()
    if args.refresh_test_fixture:
        fixture_root = Path(__file__).resolve().parents[1] / "tests/fixtures/roles"
        if not args.output.resolve().is_relative_to(fixture_root.resolve()):
            raise ValueError("Only repository test fixtures can be refreshed")
        args.output.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")
    else:
        scenario.save_new(args.output)
    print(scenario.digest)


if __name__ == "__main__":
    main()
