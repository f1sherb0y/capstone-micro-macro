"""Run shared regression and freeze synthetic Supplier-A01 evidence."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

from integration.action_catalog import ROOT, write_new
from integration.coverage import coverage_report
from src.actions.contracts.catalog import ContractCatalog
from src.methods.capacity import local_method_registry


CODE_PATHS = (
    "src/actions/contracts/supplier_objects.py", "src/actions/roles/supplier.py",
    "src/actions/processors.py", "src/actions/contracts/role_rules.py",
    "src/actions/contracts/contractor_objects.py", "src/actions/contracts/service_objects.py",
    "src/actions/contracts/common.py", "src/actions/contracts/references.py",
    "src/actions/contracts/catalog.py", "src/actions/runner.py", "src/actions/registry.py",
    "src/methods/__init__.py", "src/methods/models.py", "src/methods/registry.py", "src/methods/capacity.py", "src/methods/action.py",
    "src/methods/CAPACITY.md",
    "src/actions/roles/contractor.py", "src/skills/models.py",
    "integration/macro_views.py", "src/skills/loader.py", "integration/verify_supplier.py",
    "tests/test_supplier_screening.py", "tests/test_action_runner.py", "tests/test_methods.py",
    "skills/actions/supplier/SUPPLIER-A01/SKILL.md", "skills/actions/supplier/SUPPLIER-A01/manifest.json",
    "skills/actions/contractor/CONTRACTOR-A01/SKILL.md", "skills/actions/contractor/CONTRACTOR-A01/manifest.json",
)
TEST_MODULES = (
    "supplier_screening", "government_intake", "qs_intake", "action_contracts", "action_runner",
    "action_reading", "skill_runtime", "action_catalog", "action_coverage",
    "contractor_screening", "bank_intake", "owner_observation", "architect_intake", "engineer_intake",
    "methods", "action_runtime_boundaries",
)
LIMITATIONS = [
    "All facts and business policies are synthetic; no real product, factory, logistics or method calibration",
    "Fixed location, exact same units, one clock, half-open windows and constant capacity rates only",
    "No formal intent, order, stock, resource reservation, macro receipt or feedback binding",
    "No real model calls or model quality evidence; all 106 actions remain in the objective",
    "Only the fixed-location capacity method is registered; other methods, full lifecycle and remaining 98 action decisions remain unfinished",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases():
    from tests.test_supplier_screening import add_inquiry, add_line, facts, known, measured, point, view, window
    variations = []
    for label, kind, choice in (
        ("complete", "completed", "respond"), ("partial_product", "completed", "limited_scope"),
        ("clarification", "completed", "clarify"), ("market_only", "completed", "track_market"),
        ("unsupported_product", "completed", "decline"), ("capacity_conflict", "completed", "decline"),
        ("policy_decline", "completed", "decline"), ("policy_defer", "deferred", None),
        ("unknown_quantity", "needs_information", None), ("stale_capacity", "needs_information", None),
        ("future_inquiry", "needs_information", None), ("expired_response", "needs_information", None),
        ("wrong_recipient", "technical_error", None), ("wrong_requirement_version", "technical_error", None),
        ("unsupported_unit", "unsupported", None), ("competing_scopes", "needs_information", None),
        ("ambiguous_inquiries", "needs_information", None), ("prioritized_inquiries", "completed", "respond"),
        ("precise_over_capacity", "completed", "decline"), ("distinct_geographies", "completed", "respond"),
    ):
        data = facts()
        inquiry, capacity, profile = [view(data, key) for key in ("SupplyInquiry", "SupplierCapacity", "SupplyScreeningProfile")]
        if label == "partial_product":
            add_line(data, product="unavailable")
        elif label == "clarification":
            inquiry["clarification_requirement_refs"] = [view(data, "Requirement")["ref"]]
        elif label == "market_only":
            data["input"].update(inquiry_refs=[], market_refs=[view(data, "MarketObservation")["ref"]])
        elif label == "unsupported_product":
            inquiry["lines"][0]["product_code"] = known("unavailable")
        elif label == "capacity_conflict":
            capacity["commitments"][0]["quantity"] = measured("2")
        elif label in {"policy_decline", "policy_defer"}:
            profile["policy"] = "decline_new_work" if label == "policy_decline" else "defer_new_work"
        elif label == "unknown_quantity":
            inquiry["lines"][0]["quantity"] = {"state": "unknown", "reason_code": "not_supplied", "missing_refs": []}
        elif label == "stale_capacity":
            capacity["as_of"] = point(0)
        elif label == "future_inquiry":
            inquiry["received_at"] = point(2)
        elif label == "expired_response":
            inquiry["response_window"] = window(0, 1)
        elif label == "wrong_recipient":
            inquiry["recipient_id"] = "competitor"
        elif label == "wrong_requirement_version":
            view(data, "Requirement")["inquiry_ref"]["version"] = "old"
        elif label == "unsupported_unit":
            inquiry["lines"][0]["quantity"]["value"]["unit"] = "kg"
        elif label == "competing_scopes":
            add_line(data)
        elif label in {"ambiguous_inquiries", "prioritized_inquiries"}:
            add_inquiry(data)
            if label == "prioritized_inquiries":
                profile["inquiry_priorities"] = [{"inquiry_ref": item, "priority": known(index)}
                    for index, item in enumerate(data["input"]["inquiry_refs"])]
        elif label == "precise_over_capacity":
            inquiry["lines"][0]["quantity"]["value"]["value"] = "10.000000000000000000000000000000001"
        elif label == "distinct_geographies":
            view(data, "SupplierCapability")["registration_region_id"] = known("GZ")
            inquiry["lines"][0]["delivery_region_id"] = known("MO")
            view(data, "SupplierCapability")["products"][0]["delivery_region_ids"] = known(["MO"])
            view(data, "WorkMethod")["delivery_region_ids"] = ["MO"]
        variations.append((label, data, kind, choice))
    return variations


def verify(output):
    from tests.test_supplier_screening import build_run
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        raise ValueError("Choose a new evidence directory within the repository")
    baseline = ROOT / "output/integration/plan_20261002_implementation/baseline.json"
    protected = json.loads(baseline.read_text(encoding="utf-8"))["protected_hashes"]
    changed = [name for name, digest in protected.items() if sha(ROOT / name) != digest]
    if changed:
        raise ValueError(f"Protected sources changed: {changed}")
    output.mkdir(parents=True)
    code_hashes = {name: sha(ROOT / name) for name in CODE_PATHS}
    command = [sys.executable, "-u", "-m", "pytest", *[f"tests/test_{name}.py" for name in TEST_MODULES],
               "-q", "--disable-warnings", "-o", "faulthandler_timeout=60", f"--junitxml={output / 'tests.xml'}"]
    print("Running Supplier and shared regression", flush=True)
    with (output / "tests.log").open("x", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        raise ValueError(f"Regression failed; see {output / 'tests.log'}")
    tree = ElementTree.parse(output / "tests.xml")
    suites = tree.getroot().findall("testsuite")
    totals = {field: sum(int(suite.get(field, "0")) for suite in suites)
              for field in ("tests", "failures", "errors", "skipped")}
    testcases = tree.getroot().findall(".//testcase")
    unique = {(item.get("classname"), item.get("name")) for item in testcases}
    if not totals["tests"] or any(totals[field] for field in ("failures", "errors", "skipped")):
        raise ValueError(f"Tests must pass without skips: {totals}")
    role_count = sum(classname == "tests.test_supplier_screening" for classname, _ in unique)
    if role_count < 70 or len(unique) != totals["tests"]:
        raise ValueError("Incomplete or duplicate test evidence")
    catalog = ContractCatalog()
    methods = local_method_registry()
    skill = json.loads((ROOT / "skills/actions/supplier/SUPPLIER-A01/manifest.json").read_text(encoding="utf-8"))
    inputs, calls = [], []
    print("Replaying synthetic authorized Supplier calls", flush=True)
    for label, data, kind, choice in cases():
        run = build_run(data, catalog=catalog, run_id=f"{output.name}:{label}")
        before = deepcopy(run.objects)
        result = run.execute()
        if result.kind != kind or (choice and result.payload.choice != choice):
            raise ValueError(f"Unexpected {label}: {result}")
        if run.objects != before:
            raise ValueError("Screening mutated formal projections")
        audit = run.runner.audit_records[-1].as_dict()
        if audit["method_registry_digest"] != methods.content_digest:
            raise ValueError("Method registry changed during verification")
        if label in {"complete", "capacity_conflict", "precise_over_capacity"} and not audit["method_calls"]:
            raise ValueError("Capacity screening bypassed the registered method")
        inputs.append({"case": label, "origin": "synthetic", "context": run.context.model_dump(mode="json"),
                       "input": run.input, "projections": run.objects})
        calls.append({"case": label, "result": result.model_dump(mode="json"),
                      "audit": [record.as_dict() for record in run.runner.audit_records],
                      "formal_submission": None, "macro_receipt": None, "model_calls": 0})
    actual = {item["result"]["payload"]["choice"] for item in calls if item["result"]["kind"] == "completed"}
    if actual != set(catalog.get("SUPPLIER-A01").choices):
        raise ValueError("Replay must exercise every source branch")
    from tests.test_contractor_screening import build_screening_run, facts as contractor_facts, view as contractor_view
    contractor_calls = []
    for label in ("participate", "decline", "clarify"):
        data = contractor_facts()
        if label == "decline":
            contractor_view(data, "CommitmentSnapshot")["allocations"][0]["quantity"]["value"] = "2"
        elif label == "clarify":
            contractor_view(data, "ProcurementPackage")["clarification_requirement_refs"] = [contractor_view(data, "Requirement")["ref"]]
        run = build_screening_run(data, catalog=catalog, run_id=f"{output.name}:contractor:{label}")
        before = deepcopy(run.runner.references._objects)
        result = run.execute()
        audit = run.runner.audit_records[-1].as_dict()
        if result.kind != "completed" or result.payload.choice != label:
            raise ValueError(f"Contractor method regression failed: {label}")
        if run.runner.references._objects != before or audit["method_registry_digest"] != methods.content_digest:
            raise ValueError("Contractor method changed formal projections or registry")
        if label != "clarify" and not audit["method_calls"]:
            raise ValueError("Contractor capacity screening bypassed the registered method")
        contractor_calls.append({"case": label, "origin": "synthetic", "context": run.context.model_dump(mode="json"),
            "input": run.input, "result": result.model_dump(mode="json"), "audit": audit,
            "formal_submission": None, "macro_receipt": None, "model_calls": 0})
    indexed = subprocess.run([sys.executable, "-m", "integration.action_catalog", "--check"],
                             cwd=ROOT, capture_output=True, text=True)
    if indexed.returncode:
        raise ValueError(indexed.stdout + indexed.stderr)
    for name in CODE_PATHS:
        checked = subprocess.run(["git", "-c", "core.whitespace=cr-at-eol", "diff", "--no-index", "--check", "/dev/null", name],
                                 cwd=ROOT, capture_output=True, text=True)
        if checked.stdout or checked.stderr or checked.returncode not in (0, 1):
            raise ValueError(f"Whitespace error: {name}: {checked.stdout}{checked.stderr}")
    if any(sha(ROOT / name) != digest for name, digest in protected.items()):
        raise ValueError("Protected source changed during verification")
    if any(sha(ROOT / name) != digest for name, digest in code_hashes.items()):
        raise ValueError("Verified code changed during verification; choose a fresh evidence run")
    inventory = json.loads((ROOT / "config/action_registry.json").read_text(encoding="utf-8"))
    coverage = json.loads((ROOT / "宏微观衔接方案/新版方案/action_coverage.json").read_text(encoding="utf-8"))
    record = next(row for row in coverage["actions"] if row["action_id"] == "SUPPLIER-A01")
    record.update(decision="partial_local_verified", method="partial_local_verified", validation="partial_local_verified",
        binding="unverified", feedback="pending", branches={choice: "partial_local_verified" for choice in sorted(actual)},
        local_processor={"processor_id": skill["processor_id"], "code": "src/actions/roles/supplier.py",
                         "scope": "Authorized synthetic screening intent only"},
        local_methods={"code": "src/methods/capacity.py", "support": "Fixed-location same-unit constant capacity rates on exact half-open intervals",
                       "registry_status": "registered_host_method", "calibration": "mathematical_only",
                       "registry_digest": methods.content_digest},
        gaps=[{"kind": "formal_binding", "detail": "Actual projection producer and versioned inquiry/intent endpoint remain unbound; no formal order, stock or capacity effect"},
              {"kind": "feedback_recovery", "detail": "Formal receipt/query/feedback/deduplication and unknown submission recovery require macro services"},
              {"kind": "real_method_calibration", "detail": "Registered capacity method is mathematically verified only; product, production, logistics, productivity and resource policy remain synthetic"},
              {"kind": "formal_resource_entry", "detail": "No actual macro resource entry, reservation or shared capacity arbitration is bound"}])
    record["evidence"] = list(dict.fromkeys([*record["evidence"], (output / "manifest.json").relative_to(ROOT).as_posix()]))
    artifacts = {
        "inputs.json": inputs, "runtime.json": calls, "coverage_record.json": record,
        "contractor_runtime.json": contractor_calls,
        "methods.json": {"registry_digest": methods.content_digest, "catalog": methods.catalog()},
        "coverage.json": coverage_report(inventory, coverage),
        "migration.json": {"status": "not_applicable", "reason": "Explicit synthetic typed projections, no legacy migration in this run"},
        "binding.json": {"action_id": "SUPPLIER-A01", "status": "not_bound", "macro_receipt": None,
            "required": ["Actual authorized projection producer", "Versioned received inquiry/intent endpoint",
                         "Formal order/stock/capacity services", "Receipt/query/feedback/deduplication and recovery"],
            "limitations": LIMITATIONS},
        "checks.json": {"tests": totals, "unique_tests": len(unique), "role_tests": role_count,
            "catalog": json.loads(indexed.stdout), "test_command": command,
            "protected_files": len(protected), "protected_hashes": "matched", "branches": sorted(actual),
            "runtime_cases": len(calls), "model_calls": 0, "formal_receipts": 0},
    }
    for name, value in artifacts.items():
        write_new(output / name, value)
    manifest = {"schema_version": "plan-supplier-evidence.v1", "action_id": "SUPPLIER-A01", "evidence_id": output.name,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "source_sha256": catalog.get("SUPPLIER-A01").source_sha256,
        "processor_id": skill["processor_id"], "skill_version": skill["skill_version"], "status": "partial_local_verified",
        "method_registry_digest": methods.content_digest,
        "tests": totals, "unique_tests": len(unique), "role_tests": role_count, "runtime_cases": len(calls),
        "branches": sorted(actual), "protected": {"unchanged": True, "files": len(protected), "baseline": baseline.relative_to(ROOT).as_posix()},
        "contractor_method_runtime_cases": len(contractor_calls), "code_hashes": code_hashes,
        "artifact_hashes": {name: sha(output / name) for name in [*artifacts, "tests.xml", "tests.log"]},
        "environment": {"python": sys.version, "packages": {name: version(name) for name in ("pytest", "pydantic", "lark")}},
        "checks": {"CHECK-SUPPLIER-001": "partial: forecast-only intent does not mutate projections; formal effects unbound",
                   "CHECK-SUPPLIER-036": "partial: exact shared capacity screening; formal order reservation unbound",
                   "CHECK-SUPPLIER-047": "partial: registration/operation/production/delivery remain explicit and distinct; no real geographic calibration"},
        "limitations": LIMITATIONS}
    write_new(output / "manifest.json", manifest)
    print(json.dumps({"output": str(output), "tests": totals, "role_tests": role_count, "runtime_cases": len(calls), "protected": len(protected)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    verify(args.output)


if __name__ == "__main__":
    main()
