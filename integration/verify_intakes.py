"""Freeze independent local QS/Government intake evidence after related tests."""
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


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _government_cases():
    from tests.test_government_intake import add_case, add_proxy, build_run, facts, known, ref, unknown, view
    cases = []
    for label, kind, choice in (
        ("complete", "completed", "accept_for_processing"), ("receipt_only", "completed", "acknowledge"),
        ("missing_document", "completed", "request_correction"), ("missing_signature", "completed", "request_correction"),
        ("ineligible", "completed", "decline_processing"), ("outside_matter", "completed", "decline_processing"),
        ("outside_region", "completed", "decline_processing"), ("lawful_referral", "completed", "refer"),
        ("unknown_eligibility", "needs_information", None), ("unknown_receipt", "technical_error", None),
        ("failed_receipt", "technical_error", None), ("proxy", "completed", "accept_for_processing"),
        ("invalid_proxy", "needs_information", None), ("prior_case", "completed", "accept_for_processing"),
        ("unlinked_case", "technical_error", None), ("withdrawn", "completed", "decline_processing"),
        ("unknown_jurisdiction", "needs_information", None), ("unsupported_clock", "unsupported", None),
    ):
        data = facts()
        if label == "receipt_only":
            view(data, "Procedure")["intake_mode"] = known("receipt_only")
        elif label == "missing_document":
            view(data, "Submission")["materials"] = []
        elif label == "missing_signature":
            view(data, "Submission")["signed"] = known(False)
        elif label == "ineligible":
            view(data, "Submission")["applicant_eligible"] = known(False)
        elif label in {"outside_matter", "lawful_referral"}:
            view(data, "Jurisdiction")["covered_matter_codes"] = known(["other-matter"])
            if label == "lawful_referral":
                view(data, "Jurisdiction")["referral"] = {"recipient_id": "other-government", "basis_ref": ref("Rule", "refer")}
        elif label == "outside_region":
            view(data, "Jurisdiction")["covered_project_region_ids"] = known(["GZ"])
        elif label == "unknown_eligibility":
            view(data, "Submission")["applicant_eligible"] = unknown()
        elif label in {"unknown_receipt", "failed_receipt"}:
            view(data, "Submission")["receipt_status"] = "unknown" if label == "unknown_receipt" else "failed"
        elif label in {"proxy", "invalid_proxy"}:
            add_proxy(data)
            if label == "invalid_proxy":
                view(data, "Authority")["permitted"] = known(False)
        elif label in {"prior_case", "unlinked_case"}:
            add_case(data)
            if label == "unlinked_case":
                view(data, "RegulatoryCase")["current_submission_ref"]["version"] = "0"
        elif label == "withdrawn":
            view(data, "Submission")["status"] = "withdrawn"
        elif label == "unknown_jurisdiction":
            view(data, "Jurisdiction")["covered_matter_codes"] = unknown()
        elif label == "unsupported_clock":
            view(data, "Submission")["submitted_at"]["clock_ref"]["version"] = "2"
        cases.append((label, data, kind, choice))
    return build_run, cases


def _qs_cases():
    from tests.test_qs_intake import build_run, runtime_data, view
    cases = []
    for label, options, kind, choice in (
        ("clear_accept", {}, "completed", "accept"),
        ("low_fee", {"fee": "20"}, "completed", "decline"),
        ("sourced_counteroffer", {"fee": "20", "counteroffer": True}, "completed", "counteroffer"),
        ("registered_questions", {"open_questions": True}, "completed", "clarify"),
        ("known_conflict", {"conflict": "conflict"}, "completed", "decline"),
        ("unknown_conflict", {"conflict": "unknown"}, "needs_information", None),
        ("failed_conflict", {"conflict": "failed"}, "technical_error", None),
        ("missing_check", {"include_check": False}, "needs_information", None),
        ("missing_check_counteroffer", {"include_check": False, "fee": "20", "counteroffer": True}, "completed", "counteroffer"),
        ("future_check", {}, "needs_information", None),
        ("expired_check", {}, "needs_information", None),
        ("wrong_identity", {}, "technical_error", None),
    ):
        data = runtime_data(**options)
        if label == "future_check":
            view(data, "ConflictCheck")["checked_at"]["offset"] = 11
        elif label == "expired_check":
            view(data, "ConflictCheck")["effective_window"]["end"]["offset"] = 10
        elif label == "wrong_identity":
            view(data, "ConflictCheck")["organization_id"] = "other-org"
        cases.append((label, data, kind, choice))
    return build_run, cases


def verify(action_id, output, test_xml):
    output = output.resolve()
    test_paths = [path.resolve() for path in test_xml]
    if not output.is_relative_to(ROOT) or any(not path.is_relative_to(ROOT) for path in test_paths):
        raise ValueError("Evidence and test artifacts must be in the repository")
    if len(set(test_paths)) != len(test_paths):
        raise ValueError("Duplicate test artifacts cannot inflate validation counts")
    if any(not path.with_suffix(".log").is_file() for path in test_paths):
        raise ValueError("The original test run log must accompany every XML")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Existing evidence cannot be overwritten; choose a new directory")
    role = "qs" if action_id == "QS-A02" else "government"
    trees = [ElementTree.parse(path) for path in test_paths]
    suites = [suite for tree in trees for suite in tree.getroot().findall("testsuite")]
    totals = {name: sum(int(suite.get(name, "0")) for suite in suites)
              for name in ("tests", "failures", "errors", "skipped")}
    if not totals["tests"] or any(totals[name] for name in ("failures", "errors", "skipped")):
        raise ValueError(f"Related tests must pass without skips: {totals}")
    testcases = [item for tree in trees for item in tree.getroot().findall(".//testcase")]
    unique_tests = {(item.get("classname", ""), item.get("name", "")) for item in testcases}
    role_count = sum(classname.startswith(f"tests.test_{role}_intake") for classname, _ in unique_tests)
    if role_count < (48 if role == "government" else 25):
        raise ValueError("Missing complete targeted intake test suite")
    required = {"test_action_contracts", "test_action_runner", "test_skill_runtime", "test_action_reading", "test_action_coverage"}
    if not all(any(item.get("classname", "").startswith(f"tests.{module}") for item in testcases) for module in required):
        raise ValueError("Missing shared authorization, contract, Skill or coverage tests")
    baseline = ROOT / "output/integration/plan_20261002_implementation/baseline.json"
    protected = json.loads(baseline.read_text(encoding="utf-8"))["protected_hashes"]
    changed = [path for path, digest in protected.items() if _sha(ROOT / path) != digest]
    if changed:
        raise ValueError(f"Protected files changed: {changed}")
    catalog = ContractCatalog()
    builder, variations = _qs_cases() if role == "qs" else _government_cases()
    calls, inputs = [], []
    for label, data, kind, choice in variations:
        run = builder(data, catalog=catalog, run_id=f"{output.name}:{label}")
        before = deepcopy(run.objects)
        result = run.execute()
        if result.kind != kind or (choice is not None and result.payload.choice != choice):
            raise ValueError(f"Unexpected {label} result: {result}")
        if run.objects != before:
            raise ValueError("Intake decision mutated formal projections")
        inputs.append({"case": label, "origin": "synthetic", "context": run.context.model_dump(mode="json"),
                       "input": run.input, "projections": run.objects})
        calls.append({"case": label, "result": result.model_dump(mode="json"),
                      "audit": [record.as_dict() for record in run.runner.audit_records],
                      "formal_submission": None, "macro_receipt": None, "model_calls": 0})
    expected = set(catalog.get(action_id).choices)
    actual = {row["result"]["payload"]["choice"] for row in calls if row["result"]["kind"] == "completed"}
    if expected != actual:
        raise ValueError("Evidence must exercise every source payload branch")
    paths = [f"src/actions/contracts/{role}_objects.py", f"src/actions/roles/{role}.py",
        "src/actions/processors.py", "src/actions/contracts/government.py", "src/actions/roles/service_intake.py",
        "src/actions/contracts/service_objects.py", f"tests/test_{role}_intake.py",
        "src/actions/contracts/common.py", "src/actions/contracts/references.py", "src/actions/contracts/catalog.py",
        "src/actions/runner.py", "src/actions/registry.py", "src/skills/loader.py",
        "src/actions/contracts/contractor_objects.py", "src/actions/contracts/architect_objects.py",
        "tests/test_architect_intake.py", "integration/macro_views.py",
        "tests/test_action_contracts.py", "tests/test_action_runner.py",
        f"skills/actions/{role}/{action_id}/SKILL.md", f"skills/actions/{role}/{action_id}/manifest.json",
        "integration/verify_intakes.py"]
    whitespace = subprocess.run(["git", "-c", "core.whitespace=cr-at-eol", "diff", "--check", "--", *paths],
                                cwd=ROOT, capture_output=True, text=True)
    if whitespace.returncode:
        raise ValueError(whitespace.stdout + whitespace.stderr)
    for name in paths:
        check = subprocess.run(["git", "-c", "core.whitespace=cr-at-eol", "diff", "--no-index", "--check", "/dev/null", name],
                               cwd=ROOT, capture_output=True, text=True)
        if check.stdout or check.stderr or check.returncode not in (0, 1):
            raise ValueError(f"Whitespace check failed for {name}: {check.stdout}{check.stderr}")
    indexed = subprocess.run([sys.executable, "-m", "integration.action_catalog", "--check"], cwd=ROOT, capture_output=True, text=True)
    if indexed.returncode:
        raise ValueError(indexed.stdout + indexed.stderr)
    registry = json.loads((ROOT / "config/action_registry.json").read_text(encoding="utf-8"))
    coverage = json.loads((ROOT / "宏微观衔接方案/新版方案/action_coverage.json").read_text(encoding="utf-8"))
    record = next(item for item in coverage["actions"] if item["action_id"] == action_id)
    record.update({"decision": "partial_local_verified", "method": "partial_local_verified",
        "validation": "partial_local_verified", "binding": "unverified", "feedback": "pending",
        "branches": {choice: "partial_local_verified" for choice in expected},
        "local_processor": {"processor_id": f"{role}.{'service_intake' if role == 'qs' else 'submission_intake'}.v2",
            "code": f"src/actions/roles/{role}.py", "scope": "Authorized synthetic intake decisions only"},
        "gaps": [{"kind": "formal_binding", "detail": "Actual authorized projection producer and formal intake/acceptance service remain unbound"},
                 {"kind": "feedback_recovery", "detail": "Stable formal identity, deduplicated submission, receipt query and feedback require actual macro services"},
                 {"kind": "real_method_calibration", "detail": "All business, authority, conflict and professional policy facts are synthetic; no regulatory/QS calibration or model quality evidence"}]})
    record["local_methods"] = {
        "code": "src/actions/roles/service_intake.py" if role == "qs" else "src/actions/roles/government.py",
        "support": ("Fixed-location, same-unit, half-open-window exact capacity and sourced fee/qualification screening"
                    if role == "qs" else "Exact typed checklist, document presence and explicitly sourced signature/eligibility states"),
        "registry_status": "not_registered", "calibration": "synthetic_only"}
    evidence_path = (output / "manifest.json").relative_to(ROOT).as_posix()
    record["evidence"] = list(dict.fromkeys([*record["evidence"], evidence_path]))
    limitations = ["Synthetic sourced policies and projections; no actual regulatory or QS professional calibration",
        "No formal intake/appointment/acceptance persistence, fees, resource allocation, macro receipt or feedback",
        "No real model calls or model quality evidence; all 106 actions remain in the overall goal scope",
        "Methods run locally but the planned common method registry and real calibration remain unfinished"]
    if role == "qs":
        limitations.append("Fixed region, same units, one clock, half-open windows, constant productivity; conflict conclusion is a sourced assumption")
    else:
        limitations.append("Only document presence, signature and explicit eligibility categories; no substantive regulatory review or permission")
    artifacts = {
        "inputs.json": inputs, "runtime.json": calls,
        "migration.json": {"status": "not_applicable", "reason": "Explicit synthetic typed projections; no legacy data migration in this run"},
        "binding.json": {"action_id": action_id, "status": "not_bound", "formal_submission": None, "macro_receipt": None,
            "required": ["Actual authorized projection producer", "Formal versioned intake/acceptance service",
                         "Stable identity and deduplicated receipt/query/feedback binding"], "limitations": limitations},
        "checks.json": {"tests": totals, "unique_tests": len(unique_tests), "role_tests": role_count, "catalog": json.loads(indexed.stdout),
            "protected_files": len(protected), "protected_hashes": "matched", "whitespace": "passed_for_evidence_code_paths",
            "branches": sorted(actual), "runtime_cases": len(calls), "model_calls": 0, "formal_receipts": 0},
        "coverage.json": coverage_report(registry, coverage),
        "coverage_record.json": record,
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, data in artifacts.items():
        write_new(output / name, data)
    test_artifacts = []
    for index, test_path in enumerate(test_paths):
        test_log = test_path.with_suffix(".log")
        if not test_log.is_file():
            raise ValueError("The original test run log must accompany its XML")
        prefix = "tests" if index == 0 else f"extra-tests-{index}"
        for suffix, source in (("xml", test_path), ("log", test_log)):
            name = f"{prefix}.{suffix}"
            with (output / name).open("xb") as stream:
                stream.write(source.read_bytes())
            test_artifacts.append(name)
    manifest = {"schema_version": "plan-intake-evidence.v1", "action_id": action_id, "evidence_id": output.name,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "source_sha256": catalog.get(action_id).source_sha256,
        "processor_id": f"{role}.{'service_intake' if role == 'qs' else 'submission_intake'}.v2", "skill_version": "2",
        "status": "partial_local_verified", "tests": totals, "unique_tests": len(unique_tests),
        "role_tests": role_count, "runtime_cases": len(calls),
        "branches": sorted(actual), "source_test_xml": [path.relative_to(ROOT).as_posix() for path in test_paths],
        "protected": {"unchanged": True, "files": len(protected), "baseline": baseline.relative_to(ROOT).as_posix()},
        "code_hashes": {name: _sha(ROOT / name) for name in paths},
        "artifact_hashes": {name: _sha(output / name) for name in [*artifacts, *test_artifacts]},
        "environment": {"python": sys.version, "packages": {name: version(name) for name in ("pydantic", "lark", "pytest")}},
        "methods": record["local_methods"],
        "checks": ({"CHECK-QS-002": "partial: local capability, scope, fee and capacity checks",
                    "CHECK-QS-003": "partial: exact local acceptance/counteroffer; formal appointment remains unbound",
                    "CHECK-QS-034": "partial: sourced conflict status/time/evidence; no calibrated independence method"}
                   if role == "qs" else
                   {"CHECK-GOV-003": "local checklist correction is distinct from substantive refusal",
                    "CHECK-GOV-006": "partial: receipt uncertainty/failure remain technical; formal reconciliation unbound",
                    "CHECK-GOV-030": "partial: exact prior-case chain and immutable repeated reads; formal deduplication unbound"}),
        "limitations": limitations}
    write_new(output / "manifest.json", manifest)
    print(json.dumps({"action_id": action_id, "tests": totals, "runtime_cases": len(calls), "protected": len(protected)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", required=True, choices=("QS-A02", "GOV-A02"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tests", required=True, type=Path, nargs="+")
    args = parser.parse_args()
    verify(args.action, args.output, args.tests)


if __name__ == "__main__":
    main()
