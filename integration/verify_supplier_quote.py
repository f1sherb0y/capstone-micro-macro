"""Freeze authorized A03 quotes, independent price checks and shared regression."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

from integration.action_catalog import ROOT, write_new
from integration.coverage import coverage_report
from integration.verify_supplier import sha
from integration.verify_supplier_product import TEST_MODULES as PRODUCT_TEST_MODULES
from src.actions.contracts.catalog import ContractCatalog
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.methods.capacity import local_method_registry
from src.methods.pricing import PRICING_METHOD


TEST_MODULES = (*PRODUCT_TEST_MODULES, "supplier_quote", "pricing_method")
LIMITATIONS = [
    "Synthetic costs, stock, product proposals, pricing policy and logistics; no real calibration",
    "Batch-total declared cost markup and explicit upward minor-unit rounding; no FX, tax or unit inference",
    "Constant sourced demand rates on fixed pools, one clock and nonempty half-open windows only",
    "No formal quote, order, inventory movement, production, reservation or macro receipts",
    "Real input producers, submit/query, feedback and action recovery remain unbound",
    "No model calls or model quality evidence; 96 remaining processors and all 106 formal bindings remain unfinished",
]
CHECKS = {
    "CHECK-SUPPLIER-004": "partial: exact proposal/cost/terms versions and current validity checked; order acceptance remains unbound",
    "CHECK-SUPPLIER-022": "partial: indicative costs cannot become binding without revalidation; pure price/capacity methods are audited",
    "CHECK-SUPPLIER-024": "partial: every batch requires complete sourced included-service responsibility and costs",
    "CHECK-SUPPLIER-036": "partial: quotes propose allocations only; formal shared commitment conflict gate remains unbound",
    "CHECK-SUPPLIER-049": "partial: shared pool demands aggregate with existing commitments; no new physical capacity or reservation",
}


def cases():
    from tests.test_supplier_quote import facts, split_batches, add_alternative, known, unknown, measured, point, view, window
    rows = []
    for label, kind, choice in (
        ("pending_confirmation", "completed", "quote"), ("confirmed", "completed", "quote"),
        ("policy_decline", "completed", "decline_quote"), ("rejected_proposal", "completed", "decline_quote"),
        ("logistics_decline", "completed", "decline_quote"), ("stock_shortage", "completed", "decline_quote"),
        ("capacity_conflict", "completed", "decline_quote"), ("split_batches", "completed", "quote"),
        ("split_conflict", "completed", "decline_quote"), ("separate_windows", "completed", "quote"),
        ("ambiguous_alternatives", "needs_information", None), ("priority_alternative", "completed", "quote"),
        ("unknown_cost", "needs_information", None), ("unknown_logistics", "needs_information", None),
        ("indicative_cost", "needs_information", None), ("future_cost", "needs_information", None),
        ("stale_capacity", "needs_information", None), ("expired_validity", "needs_information", None),
        ("missing_service", "needs_information", None), ("missing_cost", "needs_information", None),
        ("wrong_recipient", "technical_error", None), ("old_product_cost", "technical_error", None),
        ("wrong_payer", "technical_error", None), ("wrong_confirmation", "technical_error", None),
        ("currency_conversion", "unsupported", None), ("unsupported_method", "unsupported", None),
    ):
        data = facts()
        if label == "confirmed":
            view(data, "ProductProposal").update(status="confirmed", confirmation_requirement_ref=None)
        elif label == "policy_decline":
            view(data, "SupplyPricingProfile")["policy"] = "decline_new_quotes"
        elif label == "rejected_proposal":
            view(data, "ProductProposal")["status"] = "rejected"
        elif label == "logistics_decline":
            view(data, "LogisticsAssessment")["feasible"] = known(False)
        elif label == "stock_shortage":
            view(data, "InventorySnapshot")["lots"][0]["committed"] = measured("2", "panel")
        elif label == "capacity_conflict":
            view(data, "SupplierCapacity")["commitments"][0]["quantity"] = measured("1.3", "line")
        elif label in {"split_batches", "split_conflict", "separate_windows"}:
            split_batches(data, overlap=label != "separate_windows")
            if label != "split_batches":
                view(data, "SupplierCapacity")["resources"][0]["total"] = known(measured("1.7", "line"))
        elif label in {"ambiguous_alternatives", "priority_alternative"}:
            alternative = add_alternative(data)
            if label == "priority_alternative":
                view(data, "SupplyPricingProfile")["proposal_priorities"] = [
                    {"proposal_ref": data["input"]["product_proposal_refs"][0], "priority": 2},
                    {"proposal_ref": alternative, "priority": 1}]
        elif label == "unknown_cost":
            view(data, "CostBasis")["unit_cost"] = unknown()
        elif label == "unknown_logistics":
            view(data, "LogisticsAssessment")["feasible"] = unknown()
        elif label == "indicative_cost":
            view(data, "CostBasis")["purpose"] = "indicative_only"
        elif label == "future_cost":
            view(data, "CostBasis")["available_at"] = point(2)
        elif label == "stale_capacity":
            view(data, "SupplierCapacity")["as_of"] = point(0)
        elif label == "expired_validity":
            next(row for row in data["objects"] if row["ref"]["id"] == "validity")["value"] = window(0, 1)
        elif label == "missing_service":
            view(data, "LogisticsAssessment")["deliveries"][0]["included_service_refs"].pop()
        elif label == "missing_cost":
            data["input"]["cost_basis_refs"] = []
        elif label == "wrong_recipient":
            view(data, "SupplyInquiry")["recipient_id"] = "competitor"
        elif label == "old_product_cost":
            view(data, "CostBasis")["product_ref"]["version"] = "old"
        elif label == "wrong_payer":
            view(data, "SupplyTerms")["payer_id"] = "owner-not-payer"
        elif label == "wrong_confirmation":
            next(row["value"] for row in data["objects"] if row["ref"]["id"] == "confirm")["product_proposal_ref"]["version"] = "old"
        elif label == "currency_conversion":
            view(data, "CostBasis")["unit_cost"]["value"]["currency"] = "USD"
        elif label == "unsupported_method":
            view(data, "SupplyPricingProfile")["algorithm_code"] = "not_provided"
        rows.append((label, data, kind, choice))
    return rows


def check_prices(data, audit, offer):
    """Recompute prices from frozen source rows, independent of method code."""
    profile = next(row["value"] for row in data["objects"] if row["ref"]["kind"] == "SupplyPricingProfile")
    calls = [row for row in audit["method_calls"] if row["method_ref"] == PRICING_METHOD.model_dump(mode="json")]
    if len(calls) != len(offer.lines):
        raise ValueError("Every quoted batch must have a pricing method invocation")
    costs = {json.dumps(row["ref"], sort_keys=True): row["value"] for row in data["objects"] if row["ref"]["kind"] == "CostBasis"}
    checks = []
    for call, line in zip(calls, offer.lines):
        inputs, report = call["input"], call["result"]["value"]
        source_costs = [costs[json.dumps(ref, sort_keys=True)] for ref in inputs["source_refs"] if ref["kind"] == "CostBasis"]
        if not source_costs or inputs["quantity"] != line.product.quantity.model_dump(mode="json"):
            raise ValueError("Pricing source or batch quantity mismatch")
        cost = Fraction(line.product.quantity.value) * sum((Fraction(row["unit_cost"]["value"]["value"]) for row in source_costs), Fraction())
        cost += sum((Fraction(row["per_batch_cost"]["value"]["value"]) for row in source_costs), Fraction())
        raw = cost * (1 + Fraction(profile["markup_rate"]["value"]))
        scale = 10 ** profile["minor_places"]
        numerator = raw.numerator * scale
        ticks = (numerator + raw.denominator - 1) // raw.denominator
        expected = Fraction(ticks, scale)
        if (Fraction(line.price.value) != expected or Fraction(report["rounded_price"]) != expected
                or Fraction(report["cost"]["numerator"], report["cost"]["denominator"]) != cost):
            raise ValueError("Quote disagrees with independent source-cost oracle")
        checks.append({"cost": str(cost), "unrounded_price": str(raw), "expected_price": str(expected), "actual_price": line.price.value})
    return checks


def verify(output, workers=1):
    from tests.test_supplier_quote import build_run
    if not 1 <= workers <= 4:
        raise ValueError("Use one to four independent regression processes")
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        raise ValueError("Choose a new evidence directory within the repository")
    baseline = ROOT / "output/integration/plan_20261002_implementation/baseline.json"
    protected = json.loads(baseline.read_text(encoding="utf-8"))["protected_hashes"]
    if any(sha(ROOT / name) != value for name, value in protected.items()):
        raise ValueError("Protected source differs from baseline")
    paths = [ROOT / f"tests/test_{name}.py" for name in TEST_MODULES]
    paths += [ROOT / name for name in ("integration/verify_supplier_quote.py", "integration/verify_supplier_product.py",
        "integration/verify_supplier.py", "integration/action_catalog.py", "integration/coverage.py", "integration/macro_views.py", "config/action_registry.json")]
    for directory in ("src/actions", "src/methods", "src/skills", "src/organization", "skills", "config/roles"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file() and path.suffix in {".py", ".md", ".json"})
    code_hashes = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
    output.mkdir(parents=True)
    commands = [[sys.executable, "-u", "-m", "pytest", *[f"tests/test_{name}.py" for name in TEST_MODULES[index::workers]],
        "-q", "--disable-warnings", "-o", "faulthandler_timeout=60", f"--junitxml={output / f'tests-worker-{index}.xml'}"]
        for index in range(workers)]
    print("Running supplier quote and shared regression", flush=True)
    def run_worker(index):
        with (output / f"tests-worker-{index}.log").open("x", encoding="utf-8") as log:
            result = subprocess.run(commands[index], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
        print(f"Regression worker {index} finished with status {result.returncode}", flush=True)
        return result.returncode

    with ThreadPoolExecutor(max_workers=workers) as executor:
        returncodes = list(executor.map(run_worker, range(workers)))
    combined = ElementTree.Element("testsuites")
    for index in range(workers):
        combined.extend(ElementTree.parse(output / f"tests-worker-{index}.xml").getroot().findall("testsuite"))
    ElementTree.ElementTree(combined).write(output / "tests.xml", encoding="utf-8", xml_declaration=True)
    (output / "tests.log").write_text("\n".join((output / f"tests-worker-{index}.log").read_text(encoding="utf-8")
        for index in range(workers)), encoding="utf-8")
    tree = ElementTree.parse(output / "tests.xml")
    suites = tree.getroot().findall("testsuite")
    totals = {field: sum(int(suite.get(field, "0")) for suite in suites) for field in ("tests", "failures", "errors", "skipped")}
    tests = {(row.get("classname"), row.get("name")) for row in tree.getroot().findall(".//testcase")}
    role_count = sum(module == "tests.test_supplier_quote" for module, _ in tests)
    if any(returncodes) or any(totals[key] for key in ("failures", "errors", "skipped")):
        raise ValueError(f"Regression must pass without skips: {totals}; see tests.log")
    if role_count < 70 or len(tests) != totals["tests"]:
        raise ValueError("Incomplete or duplicate test evidence")
    catalog, methods = ContractCatalog(), local_method_registry()
    registry = register_representative_processors(ActionRegistry(catalog=catalog))
    skill = registry.get("SUPPLIER-A03").skill.manifest
    inputs, calls, oracles = [], [], []
    print("Replaying quote branches and independent source-price checks", flush=True)
    for label, data, kind, choice in cases():
        run = build_run(data, catalog=catalog, run_id=f"{output.name}:{label}")
        before = deepcopy(run.objects)
        result = run.execute()
        if result.kind != kind or choice and result.payload.choice != choice:
            raise ValueError(f"Unexpected {label}: {result}")
        audit = run.runner.audit_records[-1].as_dict()
        if before != run.objects or audit["method_registry_digest"] != methods.content_digest:
            raise ValueError("Projection or method registry changed during verification")
        if choice == "quote":
            if any(call["result"]["kind"] != "ok" for call in audit["method_calls"]):
                raise ValueError("Quote bypassed a successful registered method")
            oracles.append({"case": label, "prices": check_prices(data, audit, result.payload.offer)})
            if label == "pending_confirmation" and not result.payload.offer.condition_refs:
                raise ValueError("Pending product became an unconditional quote")
        if choice == "decline_quote" and set(result.payload.model_dump()) != {"choice", "note"}:
            raise ValueError("Refusal carries a phantom quote")
        inputs.append({"case": label, "origin": "synthetic", "context": run.context.model_dump(mode="json"), "input": run.input, "projections": run.objects})
        calls.append({"case": label, "result": result.model_dump(mode="json"), "audit": audit,
            "formal_submission": None, "macro_receipt": None, "model_calls": 0})
    actual = {row["result"]["payload"]["choice"] for row in calls if row["result"]["kind"] == "completed"}
    if actual != set(catalog.get("SUPPLIER-A03").choices):
        raise ValueError("Replay did not exercise every source branch")
    indexed = subprocess.run([sys.executable, "-m", "integration.action_catalog", "--check"], cwd=ROOT, capture_output=True, text=True)
    if indexed.returncode:
        raise ValueError(indexed.stdout + indexed.stderr)
    for name in code_hashes:
        checked = subprocess.run(["git", "-c", "core.whitespace=cr-at-eol", "diff", "--no-index", "--check", "/dev/null", name],
            cwd=ROOT, capture_output=True, text=True)
        if checked.stdout or checked.stderr or checked.returncode not in (0, 1):
            raise ValueError(f"Whitespace error: {name}: {checked.stdout}{checked.stderr}")
    if (any(sha(ROOT / name) != value for name, value in protected.items())
            or any(sha(ROOT / name) != value for name, value in code_hashes.items())):
        raise ValueError("Source changed during verification; use a fresh evidence run")
    coverage = json.loads((ROOT / "宏微观衔接方案/新版方案/action_coverage.json").read_text(encoding="utf-8"))
    record = next(row for row in coverage["actions"] if row["action_id"] == "SUPPLIER-A03")
    record.update(decision="partial_local_verified", method="partial_local_verified", validation="partial_local_verified",
        binding="unverified", feedback="pending", branches={choice: "partial_local_verified" for choice in sorted(actual)},
        local_processor={"processor_id": skill.processor_id, "code": "src/actions/roles/supplier_quote.py", "scope": "Authorized synthetic conditional quotation only"},
        local_methods={"code": "src/methods/pricing.py", "support": "Declared sourced cost markup and exact minor-unit ceiling; fixed-pool capacity",
            "registry_status": "registered_host_method", "calibration": "mathematical_only", "registry_digest": methods.content_digest},
        gaps=[{"kind": "formal_binding", "detail": "Actual cost/stock/logistics producers and versioned quote submit/query remain unbound"},
              {"kind": "feedback_recovery", "detail": "Action receipt/query/feedback/deduplication and recovery remain unbound"},
              {"kind": "real_method_calibration", "detail": "Synthetic costs, payment policy, rates, physical inventory and logistics are uncalibrated"},
              {"kind": "formal_order_and_resources", "detail": "Buyer acceptance, current commitment conflict checks, inventory/resource effects require macro services"}])
    record["evidence"] = list(dict.fromkeys([*record["evidence"], (output / "manifest.json").relative_to(ROOT).as_posix()]))
    inventory = json.loads((ROOT / "config/action_registry.json").read_text(encoding="utf-8"))
    artifacts = {"inputs.json": inputs, "runtime.json": calls, "price_oracle.json": oracles, "coverage_record.json": record,
        "methods.json": {"registry_digest": methods.content_digest, "catalog": methods.catalog()},
        "coverage.json": coverage_report(inventory, coverage), "skill_audit.json": registry.skill_audit(),
        "binding.json": {"action_id": "SUPPLIER-A03", "status": "not_bound", "macro_receipt": None, "limitations": LIMITATIONS},
        "checks.json": {"tests": totals, "unique_tests": len(tests), "role_tests": role_count, "test_commands": commands,
            "catalog": json.loads(indexed.stdout), "protected_files": len(protected), "protected_hashes": "matched",
            "branches": sorted(actual), "runtime_cases": len(calls), "source_checks": CHECKS, "model_calls": 0, "formal_receipts": 0}}
    for name, value in artifacts.items():
        write_new(output / name, value)
    write_new(output / "manifest.json", {"schema_version": "plan-supplier-quote-evidence.v1", "action_id": "SUPPLIER-A03",
        "evidence_id": output.name, "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "partial_local_verified",
        "source_sha256": catalog.get("SUPPLIER-A03").source_sha256, "processor_id": skill.processor_id, "skill_version": skill.skill_version,
        "method_registry_digest": methods.content_digest, "tests": totals, "unique_tests": len(tests), "role_tests": role_count,
        "runtime_cases": len(calls), "branches": sorted(actual), "checks": CHECKS,
        "protected": {"unchanged": True, "files": len(protected), "baseline": baseline.relative_to(ROOT).as_posix()},
        "code_hashes": code_hashes, "artifact_hashes": {name: sha(output / name) for name in [*artifacts, "tests.xml", "tests.log",
            *[f"tests-worker-{index}.{suffix}" for index in range(workers) for suffix in ("xml", "log")]]},
        "environment": {"python": sys.version, "packages": {name: version(name) for name in ("pytest", "pydantic", "lark")}}, "limitations": LIMITATIONS})
    print(json.dumps({"output": str(output), "tests": totals, "role_tests": role_count, "runtime_cases": len(calls), "protected": len(protected)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    verify(args.output, args.workers)


if __name__ == "__main__":
    main()
