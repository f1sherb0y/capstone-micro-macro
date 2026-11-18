"""Freeze shared regression and sourced synthetic SUPPLIER-A02 branch evidence."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

from integration.action_catalog import ROOT, write_new
from integration.coverage import coverage_report
from integration.verify_supplier import sha, TEST_MODULES as SUPPLIER_TEST_MODULES
from src.actions.contracts.catalog import ContractCatalog
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.methods.capacity import local_method_registry
from src.methods.product import PRODUCT_METHOD


TEST_MODULES = (*SUPPLIER_TEST_MODULES, "supplier_product", "product_method", "action_common",
                "domain_contracts", "organization", "scenario_v2", "macro_views")
LIMITATIONS = [
    "Synthetic products, factories, purposes, evidence, constraints, priorities and professional authority only",
    "The method compares declared categories and inclusive numeric bounds with identical units; no engineering model or real calibration",
    "No design changes, procurement acceptance, production, installation, reservation, formal submission or macro receipts",
    "Receipt query, observation, deduplication and restoration still require a real macro binding",
    "No model calls or model quality evidence; all 106 actions remain in scope, with 97 action processors pending",
]
CHECKS = {
    "CHECK-SUPPLIER-002": "partial: explicit questions, missing evidence and unsupported interface methods remain distinct; no default usability",
    "CHECK-SUPPLIER-013": "partial: substitute proposal preserves deviations and creates no installation or production effect; formal arrival and use gates remain unbound",
    "CHECK-SUPPLIER-023": "partial: catalog comparisons retain required unresolved professional checks; no design approval",
    "CHECK-SUPPLIER-048": "partial: exact product version, factory, use and scope evidence checked independently for each line; no formal invalidation/review workflow",
    "CHECK-SUPPLIER-058": "partial: bridge, tunnel and high-rise uses outside the method domain are unsupported; no geographic or score inference",
}


def cases():
    from tests.test_supplier_product import facts, add_deviation, add_design, add_line, known, unknown, point, view
    rows = []
    for label, kind, choice in (
        ("original", "completed", "propose_original"), ("substitute", "completed", "propose_substitute"),
        ("clarification", "completed", "clarify"), ("hard_mismatch", "completed", "decline"),
        ("catalog_pending_design", "completed", "propose_original"), ("authorized_design", "completed", "propose_original"),
        ("unknown_design", "completed", "propose_original"), ("failed_design", "completed", "decline"),
        ("expired_design_authority", "needs_information", None), ("wrong_design_author", "technical_error", None),
        ("wrong_factory_evidence", "needs_information", None), ("wrong_use_evidence", "needs_information", None),
        ("future_evidence", "needs_information", None), ("old_product_evidence", "technical_error", None),
        ("missing_interface_method", "unsupported", None), ("bridge_use", "unsupported", None),
        ("undisclosed_departure", "needs_information", None), ("wrong_recipient", "technical_error", None),
        ("unknown_property", "needs_information", None), ("unknown_second_line", "needs_information", None),
        ("multiple_lines", "completed", "propose_original"), ("exact_decimal_mismatch", "completed", "decline"),
    ):
        data = facts()
        product, requirement = view(data, "ProductSpecification"), view(data, "Requirement")
        if label in {"substitute", "hard_mismatch", "undisclosed_departure", "exact_decimal_mismatch"}:
            product["properties"]["value"][1]["value"] = "29.99999999999999999999999999999999" if label == "exact_decimal_mismatch" else "29"
            if label in {"substitute", "undisclosed_departure"}:
                requirement["substitutable_property_codes"] = ["strength"]
            if label == "substitute":
                add_deviation(data)
        elif label == "clarification":
            view(data, "SupplyInquiry")["clarification_requirement_refs"] = data["input"]["requirement_refs"]
        elif label in {"catalog_pending_design", "authorized_design", "unknown_design", "failed_design", "expired_design_authority", "wrong_design_author"}:
            add_design(data, supply=label != "catalog_pending_design")
            if label == "unknown_design":
                view(data, "Deliverable")["checks"][0]["compatible"] = unknown()
            elif label == "failed_design":
                view(data, "Deliverable")["checks"][0]["compatible"] = known(False)
            elif label == "expired_design_authority":
                from tests.test_supplier_product import window
                view(data, "Authorization")["validity"] = window(0, 1)
            elif label == "wrong_design_author":
                view(data, "Deliverable")["author_actor_id"] = "supplier-actor"
        elif label == "wrong_factory_evidence":
            view(data, "ProductEvidence")["factory_id"] = "other-factory"
        elif label == "wrong_use_evidence":
            view(data, "ProductEvidence")["intended_use_code"] = "bridge"
        elif label == "future_evidence":
            view(data, "ProductEvidence")["available_at"] = point(2)
        elif label == "old_product_evidence":
            view(data, "ProductEvidence")["product_ref"]["version"] = "old"
        elif label == "missing_interface_method":
            view(data, "ProductCompatibilityMethod")["algorithm_code"] = "unprovided_interface_method"
        elif label == "bridge_use":
            requirement["intended_use_code"] = known("bridge")
        elif label == "wrong_recipient":
            view(data, "SupplyInquiry")["recipient_id"] = "other-actor"
        elif label == "unknown_property":
            product["properties"] = unknown()
        elif label in {"unknown_second_line", "multiple_lines"}:
            add_line(data)
            if label == "unknown_second_line":
                data["objects"][-1]["value"]["constraints"] = unknown()
        rows.append((label, data, kind, choice))
    return rows


def verify(output):
    from tests.test_supplier_product import build_run
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        raise ValueError("Choose a new evidence directory within the repository")
    baseline = ROOT / "output/integration/plan_20261002_implementation/baseline.json"
    protected = json.loads(baseline.read_text(encoding="utf-8"))["protected_hashes"]
    if any(sha(ROOT / name) != digest for name, digest in protected.items()):
        raise ValueError("Protected source differs from baseline")
    paths = [ROOT / f"tests/test_{name}.py" for name in TEST_MODULES]
    paths.extend(ROOT / name for name in ("integration/verify_supplier_product.py", "integration/verify_supplier.py",
        "integration/action_catalog.py", "integration/coverage.py", "integration/macro_views.py", "config/action_registry.json"))
    for directory in ("src/actions", "src/methods", "src/skills", "src/organization", "skills", "config/roles"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file() and path.suffix in {".py", ".md", ".json"})
    code_hashes = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
    output.mkdir(parents=True)
    command = [sys.executable, "-u", "-m", "pytest", *[f"tests/test_{name}.py" for name in TEST_MODULES],
        "-q", "--disable-warnings", "-o", "faulthandler_timeout=60", f"--junitxml={output / 'tests.xml'}"]
    print("Running product and shared regression", flush=True)
    with (output / "tests.log").open("x", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
    tree = ElementTree.parse(output / "tests.xml")
    suites = tree.getroot().findall("testsuite")
    totals = {field: sum(int(suite.get(field, "0")) for suite in suites) for field in ("tests", "failures", "errors", "skipped")}
    tests = {(row.get("classname"), row.get("name")) for row in tree.getroot().findall(".//testcase")}
    role_count = sum(classname == "tests.test_supplier_product" for classname, _ in tests)
    if result.returncode or not totals["tests"] or any(totals[field] for field in ("failures", "errors", "skipped")):
        raise ValueError(f"Regression must pass without skips: {totals}; see tests.log")
    if role_count < 70 or len(tests) != totals["tests"]:
        raise ValueError("Incomplete or duplicate test evidence")
    catalog, methods = ContractCatalog(), local_method_registry()
    skill = json.loads((ROOT / "skills/actions/supplier/SUPPLIER-A02/manifest.json").read_text(encoding="utf-8"))
    inputs, calls = [], []
    print("Replaying all product branches and applicability boundaries", flush=True)
    for label, data, kind, choice in cases():
        run = build_run(data, catalog=catalog, run_id=f"{output.name}:{label}")
        before = deepcopy(run.objects)
        result = run.execute()
        if result.kind != kind or (choice and result.payload.choice != choice):
            raise ValueError(f"Unexpected {label}: {result}")
        audit = run.runner.audit_records[-1].as_dict()
        if run.objects != before or audit["method_registry_digest"] != methods.content_digest:
            raise ValueError("Projection or method registry changed during verification")
        if kind == "completed" and choice != "clarify":
            if not audit["method_calls"] or any(call["method_ref"] != PRODUCT_METHOD.model_dump(mode="json")
                    or call["result"]["kind"] != "ok" for call in audit["method_calls"]):
                raise ValueError("Product comparison bypassed its registered method")
        if label in {"catalog_pending_design", "unknown_design"} and not result.payload.unresolved_refs:
            raise ValueError("Unknown professional compatibility became approval")
        if label == "authorized_design" and result.payload.unresolved_refs:
            raise ValueError("Applicable professional check did not resolve its issue")
        inputs.append({"case": label, "origin": "synthetic", "context": run.context.model_dump(mode="json"), "input": run.input, "projections": run.objects})
        calls.append({"case": label, "result": result.model_dump(mode="json"), "audit": audit,
            "formal_submission": None, "macro_receipt": None, "model_calls": 0})
    actual = {row["result"]["payload"]["choice"] for row in calls if row["result"]["kind"] == "completed"}
    if actual != set(catalog.get("SUPPLIER-A02").choices):
        raise ValueError("Replay did not exercise every source branch")
    indexed = subprocess.run([sys.executable, "-m", "integration.action_catalog", "--check"], cwd=ROOT, capture_output=True, text=True)
    if indexed.returncode:
        raise ValueError(indexed.stdout + indexed.stderr)
    for name in code_hashes:
        checked = subprocess.run(["git", "-c", "core.whitespace=cr-at-eol", "diff", "--no-index", "--check", "/dev/null", name],
            cwd=ROOT, capture_output=True, text=True)
        if checked.stdout or checked.stderr or checked.returncode not in (0, 1):
            raise ValueError(f"Whitespace error: {name}: {checked.stdout}{checked.stderr}")
    if any(sha(ROOT / name) != digest for name, digest in protected.items()) or any(sha(ROOT / name) != digest for name, digest in code_hashes.items()):
        raise ValueError("Source changed during verification; use a fresh evidence run")
    coverage = json.loads((ROOT / "宏微观衔接方案/新版方案/action_coverage.json").read_text(encoding="utf-8"))
    record = next(row for row in coverage["actions"] if row["action_id"] == "SUPPLIER-A02")
    record.update(decision="partial_local_verified", method="partial_local_verified", validation="partial_local_verified",
        binding="unverified", feedback="pending", branches={choice: "partial_local_verified" for choice in sorted(actual)},
        local_processor={"processor_id": skill["processor_id"], "code": "src/actions/roles/supplier_product.py", "scope": "Authorized synthetic product proposal only"},
        local_methods={"code": "src/methods/product.py", "support": "Declared categories and inclusive exact numeric bounds; identical units only",
            "registry_status": "registered_host_method", "calibration": "mathematical_only", "registry_digest": methods.content_digest},
        gaps=[{"kind": "formal_binding", "detail": "Actual authorized product/design/evidence producer and versioned proposal endpoint remain unbound"},
              {"kind": "feedback_recovery", "detail": "Receipt/query/feedback/deduplication and recovery remain unbound"},
              {"kind": "real_method_calibration", "detail": "Mathematical declarations only; real product qualification, interface engineering, factory/use evidence and professional authority remain unverified"},
              {"kind": "formal_approval_and_use", "detail": "Procurement/design acceptance and production/installation gates require macro services"}])
    record["evidence"] = list(dict.fromkeys([*record["evidence"], (output / "manifest.json").relative_to(ROOT).as_posix()]))
    inventory = json.loads((ROOT / "config/action_registry.json").read_text(encoding="utf-8"))
    artifacts = {"inputs.json": inputs, "runtime.json": calls, "coverage_record.json": record,
        "methods.json": {"registry_digest": methods.content_digest, "catalog": methods.catalog()},
        "coverage.json": coverage_report(inventory, coverage),
        "skill_audit.json": register_representative_processors(ActionRegistry(catalog=catalog)).skill_audit(),
        "binding.json": {"action_id": "SUPPLIER-A02", "status": "not_bound", "macro_receipt": None, "limitations": LIMITATIONS},
        "checks.json": {"tests": totals, "unique_tests": len(tests), "role_tests": role_count, "test_command": command,
            "catalog": json.loads(indexed.stdout), "protected_files": len(protected), "protected_hashes": "matched",
            "branches": sorted(actual), "runtime_cases": len(calls), "source_checks": CHECKS, "model_calls": 0, "formal_receipts": 0}}
    for name, value in artifacts.items():
        write_new(output / name, value)
    write_new(output / "manifest.json", {"schema_version": "plan-supplier-product-evidence.v1", "action_id": "SUPPLIER-A02",
        "evidence_id": output.name, "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "partial_local_verified",
        "source_sha256": catalog.get("SUPPLIER-A02").source_sha256, "processor_id": skill["processor_id"], "skill_version": skill["skill_version"],
        "method_registry_digest": methods.content_digest, "tests": totals, "unique_tests": len(tests), "role_tests": role_count,
        "runtime_cases": len(calls), "branches": sorted(actual), "checks": CHECKS,
        "protected": {"unchanged": True, "files": len(protected), "baseline": baseline.relative_to(ROOT).as_posix()},
        "code_hashes": code_hashes, "artifact_hashes": {name: sha(output / name) for name in [*artifacts, "tests.xml", "tests.log"]},
        "environment": {"python": sys.version, "packages": {name: version(name) for name in ("pytest", "pydantic", "lark")}}, "limitations": LIMITATIONS})
    print(json.dumps({"output": str(output), "tests": totals, "role_tests": role_count, "runtime_cases": len(calls), "protected": len(protected)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    verify(parser.parse_args().output)


if __name__ == "__main__":
    main()
