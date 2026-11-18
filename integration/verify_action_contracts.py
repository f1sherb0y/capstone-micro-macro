"""Export complete structural schemas with reproducible regression evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
import subprocess
import sys

from integration.action_catalog import ROOT, sha256, write_new
from src.actions.contracts.catalog import ContractCatalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    catalog = ContractCatalog()
    schema_rows = []
    for action in catalog.contracts.values():
        path = args.output / "schemas" / f"{action.action_id}.json"
        write_new(path, {"action_id": action.action_id, "input": action.input_model.model_json_schema(),
                         "payload": action.payload_adapter.json_schema(), "result": action.result_adapter.json_schema()})
        schema_rows.append({"action_id": action.action_id, "source_sha256": action.source_sha256,
                            "choices": action.choices, "schema": str(path), "schema_sha256": sha256(path)})
    tests = ["tests/test_action_catalog.py", "tests/test_action_common.py", "tests/test_action_contracts.py",
             "tests/test_organization.py", "tests/test_scenario_v2.py", "tests/test_action_coverage.py"]
    command = [sys.executable, "-m", "pytest", *tests, "-q", "--disable-warnings", f"--junitxml={args.output / 'tests.xml'}"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    (args.output / "tests.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    write_new(args.output / "manifest.json", {"schema_version": "action-schema-evidence.v1",
        "status": "structural_verified" if completed.returncode == 0 else "failed", "exit_code": completed.returncode,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "python": sys.version, "command": command,
        "packages": {name: version(name) for name in ("pydantic", "pytest", "lark")}, "actions": schema_rows,
        "code_hashes": {path.relative_to(ROOT).as_posix(): sha256(path) for directory in ("src/actions", "src/organization", "src/skills", "config/roles")
                        for path in sorted((ROOT / directory).rglob("*")) if path.suffix in (".py", ".json")},
        "skill_hashes": {path.relative_to(ROOT).as_posix(): sha256(path) for path in sorted((ROOT / "skills").rglob("*"))
                         if path.is_file()},
        "integration_hashes": {name: sha256(ROOT / "integration" / name) for name in ("scenario_v2.py", "data_migrations.py", "role_fixtures.py", "macro_views.py")},
        "contract_hashes": {name: sha256(ROOT / "src/actions/contracts" / name) for name in ("common.py", "catalog.py", "role_rules.py")},
        "fixture_hashes": {"tests/fixtures/roles/eight_role_initial.v2.json": sha256(ROOT / "tests/fixtures/roles/eight_role_initial.v2.json")},
        "limitations": "Structural contracts, selected cross-field rules and initial data; no role handlers, real-model observations or macro execution claims"})
    print(completed.stdout)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
