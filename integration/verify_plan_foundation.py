"""Persist P0 inventory and P1 foundation checks in a new evidence directory."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys

from integration.action_catalog import ROOT, build_catalog, sha256, validate_coverage, write_new
from integration.plan_baseline import protected_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    catalog = build_catalog()
    recorded = json.loads((ROOT / "config/action_registry.json").read_text(encoding="utf-8"))
    if recorded != catalog:
        raise ValueError("Source inventory mismatch")
    coverage_path = ROOT / "宏微观衔接方案/新版方案/action_coverage.json"
    validate_coverage(catalog, json.loads(coverage_path.read_text(encoding="utf-8")))
    original = json.loads(args.baseline.read_text(encoding="utf-8"))["protected_hashes"]
    current = protected_hashes()
    changed = sorted(key for key in set(original) | set(current) if original.get(key) != current.get(key))
    if changed:
        raise ValueError(f"Protected sources changed: {changed}")
    command = [sys.executable, "-m", "pytest", "tests/test_action_catalog.py", "tests/test_action_common.py",
               "tests/test_organization.py", "-q", "--disable-warnings", f"--junitxml={args.output / 'tests.xml'}"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    (args.output / "tests.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    write_new(args.output / "manifest.json", {
        "schema_version": "plan-foundation-evidence.v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "packages": {name: version(name) for name in ("pydantic", "pytest")},
        "command": command, "exit_code": completed.returncode,
        "inventory": {"actions": 106, "counts": catalog["counts"], "registry_sha256": sha256(ROOT / "config/action_registry.json"),
                      "coverage_sha256": sha256(coverage_path)},
        "protected": {"unchanged": True, "files": len(current), "baseline": str(args.baseline), "baseline_sha256": sha256(args.baseline)},
        "code_hashes": {str(path.relative_to(ROOT)): sha256(path) for directory in ("src/organization", "src/actions/contracts", "config/roles")
                        for path in sorted((ROOT / directory).rglob("*")) if path.suffix in (".py", ".json")},
        "scope": "P0 registration and P1 common types/organization only; no role handler or macro execution claim",
    })
    print(completed.stdout)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
