"""Freeze A04 authorized formation drafts, independent resource checks and regression."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
from importlib.metadata import version
import json
import hashlib
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

from integration.action_catalog import ROOT, write_new
from integration.coverage import coverage_report
from integration.verify_supplier import sha
from integration.verify_supplier_quote import TEST_MODULES as QUOTE_TEST_MODULES
from src.actions.contracts.catalog import ContractCatalog
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.methods.capacity import local_method_registry


TEST_MODULES = (*QUOTE_TEST_MODULES, "supplier_order")
LIMITATIONS = [
    "Synthetic offers, formation policies, independent authorizations, cash, stock and constant demand rates; no real calibration",
    "Exact sourced working-capital comparison, no invented credit, receipts, finance method or unit/currency conversion",
    "Fixed pools, one clock and half-open windows; partial lines use explicit sourced prices and unique policy priorities",
    "Accept is a local independent decision; partial acceptance is a counterproposal requiring fresh buyer/payer confirmation",
    "No formal order, plan batch, inventory, reservation, obligation, payment or macro receipts",
    "Actual authorized input producers, formation submit/query, feedback and recovery remain unbound",
    "No model quality evidence; all 106 formal bindings and remaining processors remain unfinished",
]
CHECKS = {
    "CHECK-SUPPLIER-003": "partial: selected quote is not supplier acceptance; buyer/payer must independently authorize this exact agreement; formal formation unbound",
    "CHECK-SUPPLIER-004": "partial: exact offer/proposal/specification/amount/payer/terms/condition versions and active windows rechecked",
    "CHECK-SUPPLIER-005": "partial: actual usable stock minus existing commitments checked and batch use aggregated once; simultaneous formal order allocation/feedback unbound",
    "CHECK-SUPPLIER-006": "partial: simultaneous demands aggregate on existing shared pools without copying capacity; positive partial counterproposal needs fresh confirmation; formal reservation gate unbound",
    "CHECK-SUPPLIER-037": "unverified: refusal creates no new local order or reservation, but release of existing temporary reservations and preservation of other orders require formal macro binding",
}


def cases():
    from tests.test_supplier_order import facts, full_plan, partial_plan, split_order, amend_order, view, known, unknown, money, measured, point, window
    rows = []
    for label, kind, choice in (
        ("full_accept", "completed", "accept"), ("cash_partial", "completed", "accept_partial"),
        ("prefer_partial_unconfirmed", "completed", "accept_partial"), ("omit_whole_line", "completed", "accept_partial"),
        ("policy_revise", "completed", "revise"), ("cash_revise", "completed", "revise"),
        ("final_price_revise", "completed", "revise"), ("counterparty_reject", "completed", "revise"),
        ("policy_reject", "completed", "reject"), ("cash_reject", "completed", "reject"),
        ("stock_shortage", "completed", "reject"), ("capacity_conflict", "completed", "reject"),
        ("expired_offer", "completed", "reject"), ("quarantined_stock", "completed", "reject"),
        ("split_accept", "completed", "accept"), ("split_conflict", "completed", "reject"),
        ("separate_windows", "completed", "accept"), ("stock_reuse", "completed", "reject"),
        ("missing_acceptance", "needs_information", None), ("unknown_cash", "needs_information", None),
        ("unknown_working_capital", "needs_information", None), ("unconfirmed_product", "needs_information", None),
        ("stale_stock", "needs_information", None), ("future_acceptance", "needs_information", None),
        ("wrong_actor", "technical_error", None), ("old_acceptance", "technical_error", None),
        ("wrong_digest", "technical_error", None), ("foreign_run", "technical_error", None),
        ("invalid_partial", "technical_error", None), ("currency_conversion", "unsupported", None),
        ("unsupported_policy", "unsupported", None), ("window_bounds", "unsupported", None),
    ):
        data = facts()
        profile = view(data, "SupplyFormationProfile")
        if label in {"cash_partial", "cash_reject", "cash_revise"}:
            view(data, "FundingPosition")["actual_cash"] = known(money("600"))
            profile["on_conflict"] = {"cash_partial": "partial", "cash_reject": "reject", "cash_revise": "revise"}[label]
        elif label == "prefer_partial_unconfirmed":
            profile["policy"] = "prefer_partial"
            data["input"]["counterpart_acceptance_refs"] = []
        elif label == "omit_whole_line":
            split_order(data)
            profile["policy"] = "prefer_partial"
            partial_plan(data)["lines"][0]["delivery"] = deepcopy(view(data, "OrderProposal")["lines"][0]["delivery"])
        elif label == "policy_revise":
            profile["policy"] = "revise"
        elif label == "policy_reject":
            profile["policy"] = "reject_new_orders"
        elif label == "final_price_revise":
            view(data, "OrderProposal")["lines"][0]["delivery"]["price"] = money("1")
        elif label == "counterparty_reject":
            view(data, "PartyAcceptance")["choice"] = "reject"
        elif label == "stock_shortage":
            view(data, "InventorySnapshot")["lots"][0]["committed"] = measured("2", "panel")
        elif label == "capacity_conflict":
            view(data, "SupplierCapacity")["commitments"][0]["quantity"] = measured("1.5", "line")
        elif label == "expired_offer":
            next(row for row in data["objects"] if row["ref"]["id"] == "validity")["value"] = window(0, 1)
        elif label == "quarantined_stock":
            view(data, "InventorySnapshot")["lots"][0]["status"] = "quarantined"
        elif label in {"split_accept", "split_conflict", "separate_windows", "stock_reuse"}:
            split_order(data, separate=label == "separate_windows")
            if label in {"split_conflict", "separate_windows"}:
                view(data, "SupplierCapacity")["resources"][0]["total"] = known(measured("1.7", "line"))
            if label == "stock_reuse":
                full_plan(data)["lines"][1]["stock_uses"] = deepcopy(full_plan(data)["lines"][0]["stock_uses"])
        elif label == "missing_acceptance":
            data["input"]["counterpart_acceptance_refs"].pop()
        elif label == "unknown_cash":
            view(data, "FundingPosition")["actual_cash"] = unknown()
        elif label == "unknown_working_capital":
            full_plan(data)["lines"][0]["working_capital"] = unknown()
        elif label == "unconfirmed_product":
            next(row["value"] for row in data["objects"] if row["ref"]["id"] == "confirm")["satisfied"] = known(False)
        elif label == "stale_stock":
            view(data, "InventorySnapshot")["as_of"] = point(0)
        elif label == "future_acceptance":
            view(data, "PartyAcceptance")["created_at"] = point(2)
        elif label == "wrong_actor":
            view(data, "PartyAcceptance")["author_actor_id"] = "impersonator"
        elif label == "old_acceptance":
            view(data, "PartyAcceptance")["proposal_ref"]["version"] = "old"
        elif label == "wrong_digest":
            view(data, "PartyAcceptance")["agreement_sha256"] = "a" * 64
        elif label == "foreign_run":
            view(data, "PartyAcceptance")["run_id"] = "foreign"
        elif label == "invalid_partial":
            profile["policy"] = "prefer_partial"
            partial_plan(data)["lines"][0]["delivery"] = deepcopy(full_plan(data)["lines"][0]["delivery"])
        elif label == "currency_conversion":
            view(data, "FundingPosition")["actual_cash"]["value"]["currency"] = "USD"
        elif label == "unsupported_policy":
            profile["algorithm_code"] = "not_available"
        elif label == "window_bounds":
            next(row for row in data["objects"] if row["ref"]["id"] == "production-window")["value"]["bounds"] = "closed_closed"
        rows.append((label, data, kind, choice))
    for change in ("price", "quantity", "product", "delivery_window", "destination", "services", "terms", "conditions", "payer"):
        data = facts()
        amend_order(data, change)
        rows.append((f"reviewed_{change}", data, "completed", "accept"))
    data = facts()
    amend_order(data, "price")
    view(data, "SupplyFormationProfile")["reviewed_agreement_sha256"] = "a" * 64
    rows.append(("old_supplier_review", data, "technical_error", None))
    return rows


def check_resources(data, audit, payload):
    """Source-row Fraction oracle; does not call action, price or capacity methods."""
    def key(ref):
        return ref["kind"], ref["id"], ref["version"]
    objects = {key(row["ref"]): row["value"] for row in data["objects"]}
    capacity = objects[key(data["input"]["capacity_ref"])]
    inventory = objects[key(data["input"]["inventory_ref"])]
    funds = objects[key(data["input"]["funding_ref"])]
    proposal = objects[key(data["input"]["order_proposal_ref"])]
    agreement = {field: proposal[field] for field in ("ref", "offer_ref", "supplier_organization_id", "buyer_id", "payer_id", "scope", "terms_ref", "condition_refs", "lines")}
    agreement_hash = hashlib.sha256(json.dumps(agreement, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if payload.choice == "accept":
        parties = set()
        for ref in data["input"]["counterpart_acceptance_refs"]:
            acceptance = objects[key(ref)]
            if acceptance["agreement_sha256"] != agreement_hash or acceptance["choice"] != "accept":
                raise ValueError("Acceptance bypasses independent public agreement digest")
            parties.add(acceptance["party_id"])
        if not {proposal["buyer_id"], proposal["payer_id"]} <= parties:
            raise ValueError("Acceptance bypasses independent buyer/payer confirmation")
    calls = audit["method_calls"]
    if not calls or any(row["result"]["kind"] != "ok" for row in calls):
        raise ValueError("Successful acceptance bypasses its registered capacity method")
    call = calls[-1]
    plan_ref = next(ref for ref in call["input"]["source_refs"] if ref["kind"] == "SupplyCommitmentPlan")
    plan = objects[key(plan_ref)]
    if payload.model_dump(mode="json")["accepted_lines"] != [row["delivery"] for row in plan["lines"]]:
        raise ValueError("Accepted lines differ from the sourced final plan")
    needed_cash = sum((Fraction(row["working_capital"]["value"]["value"]) for row in plan["lines"]), Fraction())
    free_cash = Fraction(funds["actual_cash"]["value"]["value"]) - Fraction(funds["committed_cash"]["value"]["value"])
    if needed_cash > free_cash:
        raise ValueError("Acceptance exceeds independently computed current free cash")
    lots = {key(row["batch_ref"]): row for row in inventory["lots"]}
    pools = {key(row["resource_ref"]): row for row in capacity["resources"]}
    stock_used, demands, expected_allocations = {}, [], []
    for row in plan["lines"]:
        quantity = Fraction(row["delivery"]["product"]["quantity"]["value"])
        from_stock = sum((Fraction(use["quantity"]["value"]) for use in row["stock_uses"]), Fraction())
        for use in row["stock_uses"]:
            batch = key(use["batch_ref"])
            stock_used[batch] = stock_used.get(batch, Fraction()) + Fraction(use["quantity"]["value"])
            lot = lots[batch]
            if lot["status"] != "usable" or stock_used[batch] > Fraction(lot["actual"]["value"]) - Fraction(lot["committed"]["value"]):
                raise ValueError("Acceptance reuses unavailable physical stock")
        for use in row["resource_uses"]:
            required = Fraction(use["rate_per_product_unit"]["value"]) * (quantity - from_stock if use["source"] == "manufacture" else quantity)
            demands.append((key(use["resource_ref"]), objects[key(use["window_ref"])], required))
            expected_allocations.append((key(use["resource_ref"]), key(use["window_ref"]), row["delivery"]["product"]["destination_scope_ref"], use["rate_per_product_unit"]["unit"], required))
    actual_allocations = [(key(row.resource_ref.model_dump(mode="json")), key(row.window_ref.model_dump(mode="json")),
        row.scope_ref.model_dump(mode="json"), row.quantity.unit, Fraction(row.quantity.value)) for row in payload.proposed_allocations]
    if expected_allocations != actual_allocations:
        raise ValueError("Proposed allocations differ from independent exact sourced demand")
    points = sorted({offset for _, w, _ in demands for offset in (w["start"]["offset"], w["end"]["offset"])} |
        {offset for row in capacity["commitments"] for offset in (row["window"]["start"]["offset"], row["window"]["end"]["offset"])} |
        {offset for row in capacity["resources"] for offset in (row["effective_window"]["start"]["offset"], row["effective_window"]["end"]["offset"])})
    segments = []
    for pool_key, pool in pools.items():
        for start, end in zip(points, points[1:]):
            needed = sum((q for identity, w, q in demands if identity == pool_key and w["start"]["offset"] <= start < w["end"]["offset"]), Fraction())
            if not needed:
                continue
            used = sum((Fraction(row["quantity"]["value"]) for row in capacity["commitments"] if key(row["resource_ref"]) == pool_key
                and row["window"]["start"]["offset"] <= start < row["window"]["end"]["offset"]), Fraction())
            available = Fraction(pool["total"]["value"]["value"]) if pool["effective_window"]["start"]["offset"] <= start < pool["effective_window"]["end"]["offset"] else Fraction()
            available = max(Fraction(), available - used)
            if needed > available:
                raise ValueError("Acceptance oversells independently computed shared capacity")
            segments.append({"pool": pool_key, "start": start, "end": end, "needed": str(needed), "available": str(available)})
    return {"plan_ref": plan_ref, "needed_cash": str(needed_cash), "free_cash": str(free_cash),
        "stock_used": [{"batch": batch, "quantity": str(q)} for batch, q in stock_used.items()], "segments": segments}


def verify(output, workers=1):
    from tests.test_supplier_order import build_run
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
    paths += [ROOT / name for name in ("integration/verify_supplier_order.py", "integration/verify_supplier_quote.py",
        "integration/verify_supplier_product.py", "integration/verify_supplier.py", "integration/action_catalog.py",
        "integration/coverage.py", "integration/macro_views.py", "config/action_registry.json")]
    for directory in ("src/actions", "src/methods", "src/skills", "src/organization", "skills", "config/roles"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file() and path.suffix in {".py", ".md", ".json"})
    code_hashes = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
    output.mkdir(parents=True)
    commands = [[sys.executable, "-u", "-m", "pytest", *[f"tests/test_{name}.py" for name in TEST_MODULES[index::workers]],
        "-q", "--disable-warnings", "-o", "faulthandler_timeout=60", f"--junitxml={output / f'tests-worker-{index}.xml'}"]
        for index in range(workers)]
    print("Running supplier order and shared regression", flush=True)
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
    (output / "tests.log").write_text("\n".join((output / f"tests-worker-{index}.log").read_text(encoding="utf-8") for index in range(workers)), encoding="utf-8")
    tree = ElementTree.parse(output / "tests.xml")
    suites = tree.getroot().findall("testsuite")
    totals = {field: sum(int(suite.get(field, "0")) for suite in suites) for field in ("tests", "failures", "errors", "skipped")}
    tests = {(row.get("classname"), row.get("name")) for row in tree.getroot().findall(".//testcase")}
    role_count = sum(module == "tests.test_supplier_order" for module, _ in tests)
    if any(returncodes) or any(totals[key] for key in ("failures", "errors", "skipped")):
        raise ValueError(f"Regression must pass without skips: {totals}; see tests.log")
    if role_count < 120 or len(tests) != totals["tests"]:
        raise ValueError("Incomplete or duplicate test evidence")
    catalog, methods = ContractCatalog(), local_method_registry()
    registry = register_representative_processors(ActionRegistry(catalog=catalog))
    skill = registry.get("SUPPLIER-A04").skill.manifest
    inputs, calls, oracles = [], [], []
    print("Replaying all order branches and source-resource oracles", flush=True)
    for label, data, kind, choice in cases():
        run = build_run(data, catalog=catalog, run_id=f"{output.name}:{label}")
        before = deepcopy(run.objects)
        result = run.execute()
        if result.kind != kind or choice and result.payload.choice != choice:
            raise ValueError(f"Unexpected {label}: {result}")
        audit = run.runner.audit_records[-1].as_dict()
        if before != run.objects or audit["method_registry_digest"] != methods.content_digest:
            raise ValueError("Projection or method registry changed during verification")
        if choice in {"accept", "accept_partial"}:
            oracles.append({"case": label, "resources": check_resources(data, audit, result.payload)})
            if choice == "accept_partial" and "fresh same-version" not in result.payload.note:
                raise ValueError("Partial draft silently became an effective order")
        if choice == "reject" and set(result.payload.model_dump()) != {"choice", "note"}:
            raise ValueError("Refusal carries a phantom order")
        inputs.append({"case": label, "origin": "synthetic", "context": run.context.model_dump(mode="json"), "input": run.input, "projections": run.objects})
        calls.append({"case": label, "result": result.model_dump(mode="json"), "audit": audit, "formal_submission": None, "macro_receipt": None, "model_calls": 0})
    actual = {row["result"]["payload"]["choice"] for row in calls if row["result"]["kind"] == "completed"}
    if actual != set(catalog.get("SUPPLIER-A04").choices):
        raise ValueError("Replay did not exercise every source branch")
    indexed = subprocess.run([sys.executable, "-m", "integration.action_catalog", "--check"], cwd=ROOT, capture_output=True, text=True)
    if indexed.returncode:
        raise ValueError(indexed.stdout + indexed.stderr)
    for name in code_hashes:
        checked = subprocess.run(["git", "-c", "core.whitespace=cr-at-eol", "diff", "--no-index", "--check", "/dev/null", name], cwd=ROOT, capture_output=True, text=True)
        if checked.stdout or checked.stderr or checked.returncode not in (0, 1):
            raise ValueError(f"Whitespace error: {name}: {checked.stdout}{checked.stderr}")
    if (any(sha(ROOT / name) != value for name, value in protected.items()) or any(sha(ROOT / name) != value for name, value in code_hashes.items())):
        raise ValueError("Source changed during verification; use a fresh evidence run")
    coverage = json.loads((ROOT / "宏微观衔接方案/新版方案/action_coverage.json").read_text(encoding="utf-8"))
    record = next(row for row in coverage["actions"] if row["action_id"] == "SUPPLIER-A04")
    record.update(decision="partial_local_verified", method="partial_local_verified", validation="partial_local_verified", binding="unverified", feedback="pending",
        branches={choice: "partial_local_verified" for choice in sorted(actual)},
        local_processor={"processor_id": skill.processor_id, "code": "src/actions/roles/supplier_order.py", "scope": "Authorized synthetic independent acceptance/strict subset counterproposal only"},
        local_methods={"code": "src/methods/capacity.py", "support": "Registered exact fixed-pool capacity; sourced actual-minus-committed cash and stock", "registry_status": "registered_host_method", "calibration": "mathematical_only", "registry_digest": methods.content_digest},
        gaps=[{"kind": "formal_binding", "detail": "Actual proposal/acceptance/resource producers and formation submit/query remain unbound"},
              {"kind": "feedback_recovery", "detail": "Action receipts, feedback, deduplication and recovery remain unbound"},
              {"kind": "real_method_calibration", "detail": "Synthetic authorizations, funding, physical stock, productivity and commercial assumptions uncalibrated"},
              {"kind": "formal_formation_and_resources", "detail": "Effective orders, same-version partial confirmation and concurrent reservation require real macro core"}])
    record["evidence"] = list(dict.fromkeys([*record["evidence"], (output / "manifest.json").relative_to(ROOT).as_posix()]))
    inventory = json.loads((ROOT / "config/action_registry.json").read_text(encoding="utf-8"))
    artifacts = {"inputs.json": inputs, "runtime.json": calls, "resource_oracle.json": oracles, "coverage_record.json": record,
        "methods.json": {"registry_digest": methods.content_digest, "catalog": methods.catalog()}, "coverage.json": coverage_report(inventory, coverage),
        "skill_audit.json": registry.skill_audit(), "binding.json": {"action_id": "SUPPLIER-A04", "status": "not_bound", "macro_receipt": None, "limitations": LIMITATIONS},
        "checks.json": {"tests": totals, "unique_tests": len(tests), "role_tests": role_count, "test_commands": commands,
            "catalog": json.loads(indexed.stdout), "protected_files": len(protected), "protected_hashes": "matched", "branches": sorted(actual),
            "runtime_cases": len(calls), "source_checks": CHECKS, "model_calls": 0, "formal_receipts": 0}}
    for name, value in artifacts.items():
        write_new(output / name, value)
    write_new(output / "manifest.json", {"schema_version": "plan-supplier-order-evidence.v1", "action_id": "SUPPLIER-A04", "evidence_id": output.name,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "partial_local_verified", "source_sha256": catalog.get("SUPPLIER-A04").source_sha256,
        "processor_id": skill.processor_id, "skill_version": skill.skill_version, "method_registry_digest": methods.content_digest,
        "tests": totals, "unique_tests": len(tests), "role_tests": role_count, "runtime_cases": len(calls), "branches": sorted(actual), "checks": CHECKS,
        "protected": {"unchanged": True, "files": len(protected), "baseline": baseline.relative_to(ROOT).as_posix()}, "code_hashes": code_hashes,
        "artifact_hashes": {name: sha(output / name) for name in [*artifacts, "tests.xml", "tests.log", *[f"tests-worker-{index}.{suffix}" for index in range(workers) for suffix in ("xml", "log")]]},
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
