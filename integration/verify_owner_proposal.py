"""Freeze OWN-A16 branches, independent budget/scale checks and shared regression."""
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
from integration.verify_supplier_order import TEST_MODULES as ORDER_TEST_MODULES
from src.actions.contracts.catalog import ContractCatalog
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.methods.capacity import local_method_registry

TEST_MODULES = (*ORDER_TEST_MODULES, "owner_proposal", "owner_proposal_methods")
CHECKS = {
    "CHECK-OWN-021": "partial: no forced project count; bounded new-build/alter/extend/non-build alternatives and no_proposal tested; formal private record and investment continuation unbound",
    "CHECK-OWN-022": "partial: independent owners/runs can retain similar private drafts without rights or reservations; actual exclusive-right conflicts and formal commitments unbound",
    "CHECK-OWN-029": "partial: purpose/region/scale/delivery suffice with no technology selected; permission, need and unresolved rights retained; actual assessment continuation unbound",
    "CHECK-OWN-048": "partial: own-use requires the specific owner's exact internal need and available review resources; public demand cannot substitute; actual input producers unbound",
    "CHECK-OWN-067": "partial: road/bridge use explicit purpose/asset/scale units, public-service template and non-applicability rules; no invented housing area or sales; real methods uncalibrated",
}
LIMITATIONS = [
    "All inputs are explicitly synthetic; no calibrated demand forecasting, engineering scale, valuation or financial feasibility",
    "At most 64 explicitly bounded candidates, exact inclusive units, one clock, ordinal priorities and point-in-time review budgets",
    "Committed and restricted cash deductions must explicitly be disjoint; no inferred financing or future cash receipts",
    "Private drafts only; no demand, land rights, financing, project, expenditure, reservation or formal receipt created",
    "Real authorized case/need/candidate producers and private record submit/query, feedback and recovery remain unbound",
    "106-action goal, remaining processors, formal bindings and real model quality remain unfinished",
]


def cases():
    from tests.test_owner_proposal import (facts, set_template, set_non_applicable, add_prior, add_candidate,
        add_issue, add_rights, view, known, unknown)
    rows = []
    for template in ("investment_return", "own_use", "public_service"):
        data = facts()
        set_template(data, template)
        rows.append((template, data, "completed", "propose"))
    for label, kind, choice in (
        ("revise", "completed", "revise"), ("unchanged_revision", "completed", "no_proposal"),
        ("alter", "completed", "propose"), ("extend", "completed", "propose"),
        ("non_build", "completed", "propose"), ("non_applicable", "completed", "propose"),
        ("unknown_scale", "completed", "propose"), ("unknown_scale_no_issue", "needs_information", None),
        ("road", "completed", "propose"), ("bridge", "completed", "propose"),
        ("prospective_rights", "completed", "propose"), ("policy_stop", "completed", "no_proposal"),
        ("empty_space", "completed", "no_proposal"), ("zero_limit", "completed", "no_proposal"),
        ("low_need", "completed", "no_proposal"), ("cash_shortage", "completed", "no_proposal"),
        ("effort_shortage", "completed", "no_proposal"), ("two_candidates", "completed", "propose"),
        ("ordinal_selection", "completed", "propose"), ("ambiguous_tie", "needs_information", None),
        ("missing_limit", "unsupported", None), ("missing_method", "unsupported", None),
        ("missing_own_need", "needs_information", None), ("unknown_cash", "needs_information", None),
        ("unknown_deductions", "needs_information", None), ("stale_funding", "needs_information", None),
        ("future_candidate", "needs_information", None), ("stale_demand", "needs_information", None),
        ("foreign_candidate", "technical_error", None), ("old_case", "technical_error", None),
        ("other_right_holder", "technical_error", None), ("currency", "unsupported", None),
        ("unit", "unsupported", None), ("duplicate_brief", "technical_error", None),
    ):
        data = facts()
        candidate, space = view(data, "ProposalCandidate"), view(data, "ProposalSpace")
        if label in {"revise", "unchanged_revision"}: add_prior(data, unchanged=label == "unchanged_revision")
        elif label in {"alter", "extend", "non_build"}: candidate["brief"]["intervention"] = label
        elif label == "non_applicable": set_non_applicable(data)
        elif label.startswith("unknown_scale"):
            candidate["brief"]["scale"]["upper"] = unknown()
            if label == "unknown_scale": add_issue(data, "scale_upper")
        elif label in {"road", "bridge"}:
            set_template(data, "public_service")
            view(data, "PurposeProfile")["asset_kind"] = view(data, "ScaleMethod")["asset_kind"] = label
            unit = "km" if label == "road" else "crossings"
            for state in [view(data, "ScaleMethod")[field] for field in ("minimum", "maximum")] + [candidate["brief"]["scale"][field] for field in ("lower", "upper")]:
                state["value"]["unit"] = unit
        elif label == "prospective_rights": add_rights(data)
        elif label == "policy_stop": space["policy"] = "no_proposal"
        elif label == "empty_space": space["candidate_refs"] = []
        elif label == "zero_limit": space["maximum_briefs"] = known(0)
        elif label == "low_need": view(data, "DemandObservation")["measure"]["value"]["value"] = "9"
        elif label == "cash_shortage": candidate["review_cost"]["value"]["value"] = "50.000000000000000000000000000001"
        elif label == "effort_shortage": candidate["review_effort"]["value"]["value"] = "1.000000000000000000000000000001"
        elif label in {"two_candidates", "ordinal_selection", "ambiguous_tie", "duplicate_brief"}:
            other = add_candidate(data, priority=1 if label == "ambiguous_tie" else 2)
            if label in {"ordinal_selection", "ambiguous_tie"}: other["review_cost"]["value"]["value"] = "41"
            if label == "duplicate_brief": other["brief"] = deepcopy(candidate["brief"])
        elif label == "missing_limit": space["maximum_briefs"] = unknown()
        elif label == "missing_method": space["algorithm_code"] = "unprovided"
        elif label == "missing_own_need":
            set_template(data, "own_use")
            data["input"]["internal_need_refs"] = candidate["internal_need_refs"] = []
        elif label == "unknown_cash": view(data, "FundingPosition")["actual_cash"] = unknown()
        elif label == "unknown_deductions": view(data, "FundingPosition")["deduction_policy"] = unknown()
        elif label == "stale_funding": view(data, "FundingPosition")["as_of"]["offset"] = 9
        elif label == "future_candidate": candidate["available_at"]["offset"] = 11
        elif label == "stale_demand": view(data, "DemandObservation")["observed_at"]["offset"] = 4
        elif label == "foreign_candidate": candidate["organization_id"] = "other-owner"
        elif label == "old_case": candidate["case_ref"]["version"] = "2"
        elif label == "other_right_holder": add_rights(data).update(status="current_right", holder_organization_id=known("other-owner"))
        elif label == "currency": candidate["review_cost"]["value"]["currency"] = "USD"
        elif label == "unit": candidate["review_effort"]["value"]["unit"] = "hours"
        rows.append((label, data, kind, choice))
    return rows


def check_draft(data, audit, payload):
    """Recompute from raw source rows; never invoke a method or action helper."""
    def key(ref): return ref["kind"], ref["id"], ref["version"]
    objects = {key(row["ref"]): row["value"] for row in data["objects"]}
    source = lambda ref: objects[key(ref)]
    space, funds = source(data["input"]["candidate_space_ref"]), source(data["input"]["funding_ref"])
    capacity = source(space["capacity_ref"])
    briefs = payload.model_dump(mode="json")["briefs"]
    selected = []
    for brief in briefs:
        matches = [source(ref) for ref in space["candidate_refs"] if source(ref)["brief"] == brief]
        if len(matches) != 1: raise ValueError("Output does not match one unique source draft")
        selected.append(matches[0])
        scale = source(brief["scale"]["basis_ref"])
        purpose = source(brief["purpose_ref"])
        if scale["purpose_ref"] != purpose["ref"] or scale["asset_kind"] != purpose["asset_kind"]:
            raise ValueError("Scale is unrelated to purpose/asset")
        for field in ("lower", "upper"):
            endpoint = brief["scale"][field]
            if endpoint["state"] == "known":
                if not (Fraction(scale["minimum"]["value"]["value"]) <= Fraction(endpoint["value"]["value"]) <= Fraction(scale["maximum"]["value"]["value"])):
                    raise ValueError("Draft scale exceeds independent source bounds")
                if endpoint["value"]["unit"] != scale["minimum"]["value"]["unit"]: raise ValueError("Scale unit changed")
            elif endpoint["state"] == "unknown":
                if not any(source(ref)["check_code"] == "scale_" + field for ref in brief["unresolved_refs"]):
                    raise ValueError("Unknown scale lacks unresolved issue")
            elif endpoint["state"] == "not_applicable":
                if endpoint["rule_ref"] != scale["applicability_rule_ref"]: raise ValueError("Non-applicability lost its rule")
            else: raise ValueError("Unsupported endpoint was emitted")
        if purpose["template"] == "own_use" and not matches[0]["internal_need_refs"]:
            raise ValueError("Public signal substituted for own-use internal need")
    now = data["business_time"]["offset"]
    available_cash = Fraction(funds["actual_cash"]["value"]["value"]) - sum(Fraction(funds[field]["value"]["value"]) for field in ("committed_cash", "restricted_cash"))
    available_effort = max(Fraction(), Fraction(capacity["total"]["value"]["value"]) - sum(
        Fraction(row["quantity"]["value"]) for row in capacity["commitments"] if row["window"]["start"]["offset"] <= now < row["window"]["end"]["offset"]))
    cost = sum(Fraction(row["review_cost"]["value"]["value"]) for row in selected)
    effort = sum(Fraction(row["review_effort"]["value"]["value"]) for row in selected)
    if cost > available_cash or effort > available_effort or len(briefs) > space["maximum_briefs"]["value"]:
        raise ValueError("Joint draft budgets/count exceed independent source limits")
    if len(audit["method_calls"]) != len(space["candidate_refs"]) + 1 or any(call["result"]["kind"] != "ok" for call in audit["method_calls"]):
        raise ValueError("Draft bypassed registered scale and priority calculations")
    if payload.choice == "revise":
        if payload.model_dump(mode="json")["prior_brief_refs"] != [row["prior_brief_ref"] for row in selected]:
            raise ValueError("Revision changed the exact prior association")
    return {"selected_keys": [row["local_key"] for row in selected], "review_cost": str(cost), "available_cash": str(available_cash),
        "review_effort": str(effort), "available_effort": str(available_effort)}


def verify(output, workers=1):
    from tests.test_owner_proposal import build_run
    if not 1 <= workers <= 4: raise ValueError("Use one to four regression processes")
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists(): raise ValueError("Choose a new repository evidence directory")
    baseline = ROOT / "output/integration/plan_20261002_implementation/baseline.json"
    protected = json.loads(baseline.read_text(encoding="utf-8"))["protected_hashes"]
    if any(sha(ROOT / name) != value for name, value in protected.items()): raise ValueError("Protected baseline changed")
    paths = [ROOT / f"tests/test_{name}.py" for name in TEST_MODULES]
    paths.extend(ROOT / name for name in ("integration/verify_owner_proposal.py", "integration/verify_supplier_order.py", "integration/action_catalog.py",
        "integration/coverage.py", "integration/macro_views.py", "config/action_registry.json", "tests/fixtures/roles/owner_proposal.v1.json"))
    for directory in ("src/actions", "src/methods", "src/skills", "src/organization", "skills", "config/roles"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file() and path.suffix in {".py", ".md", ".json"})
    code_hashes = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
    output.mkdir(parents=True)
    commands = [[sys.executable, "-u", "-m", "pytest", *[f"tests/test_{name}.py" for name in TEST_MODULES[index::workers]],
        "-q", "--disable-warnings", "-o", "faulthandler_timeout=60", f"--junitxml={output / f'tests-worker-{index}.xml'}"] for index in range(workers)]
    print("Running frozen owner proposal and shared regression", flush=True)
    def run_worker(index):
        with (output / f"tests-worker-{index}.log").open("x", encoding="utf-8") as log:
            result = subprocess.run(commands[index], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
        print(f"Worker {index} finished: {result.returncode}", flush=True)
        return result.returncode
    with ThreadPoolExecutor(max_workers=workers) as executor: returncodes = list(executor.map(run_worker, range(workers)))
    combined = ElementTree.Element("testsuites")
    for index in range(workers): combined.extend(ElementTree.parse(output / f"tests-worker-{index}.xml").getroot().findall("testsuite"))
    ElementTree.ElementTree(combined).write(output / "tests.xml", encoding="utf-8", xml_declaration=True)
    (output / "tests.log").write_text("\n".join((output / f"tests-worker-{index}.log").read_text(encoding="utf-8") for index in range(workers)), encoding="utf-8")
    totals = {field: sum(int(suite.get(field, "0")) for suite in combined) for field in ("tests", "failures", "errors", "skipped")}
    tests = {(row.get("classname"), row.get("name")) for row in combined.findall(".//testcase")}
    role_count = sum(module == "tests.test_owner_proposal" for module, _ in tests)
    method_count = sum(module == "tests.test_owner_proposal_methods" for module, _ in tests)
    if any(returncodes) or any(totals[key] for key in ("failures", "errors", "skipped")): raise ValueError(f"Regression failed: {totals}; see tests.log")
    if role_count < 65 or method_count < 25 or len(tests) != totals["tests"]: raise ValueError("Incomplete or duplicate evidence")
    catalog, methods = ContractCatalog(), local_method_registry()
    registry = register_representative_processors(ActionRegistry(catalog=catalog))
    skill = registry.get("OWN-A16").skill.manifest
    inputs, calls, oracles = [], [], []
    print("Replaying proposal branches and independent source checks", flush=True)
    for label, data, kind, choice in cases():
        run = build_run(data, catalog=catalog, run_id=f"{output.name}:{label}")
        before = deepcopy(run.objects)
        result = run.execute()
        if result.kind != kind or choice and result.payload.choice != choice: raise ValueError(f"Unexpected {label}: {result}")
        audit = run.runner.audit_records[-1].as_dict()
        if run.objects != before or audit["method_registry_digest"] != methods.content_digest: raise ValueError("Source/method state changed")
        if choice in {"propose", "revise"}: oracles.append({"case": label, "draft": check_draft(data, audit, result.payload)})
        if choice == "no_proposal" and set(result.payload.model_dump()) != {"choice", "note"}: raise ValueError("No-proposal emitted phantom draft")
        inputs.append({"case": label, "origin": "synthetic", "context": run.context.model_dump(mode="json"), "input": run.input, "projections": run.objects})
        calls.append({"case": label, "result": result.model_dump(mode="json"), "audit": audit, "formal_submission": None, "macro_receipt": None, "model_calls": 0})
    actual = {row["result"]["payload"]["choice"] for row in calls if row["result"]["kind"] == "completed"}
    if actual != set(catalog.get("OWN-A16").choices): raise ValueError("Missing source branch")
    indexed = subprocess.run([sys.executable, "-m", "integration.action_catalog", "--check"], cwd=ROOT, capture_output=True, text=True)
    if indexed.returncode: raise ValueError(indexed.stdout + indexed.stderr)
    for name in code_hashes:
        checked = subprocess.run(["git", "-c", "core.whitespace=cr-at-eol", "diff", "--no-index", "--check", "/dev/null", name], cwd=ROOT, capture_output=True, text=True)
        if checked.stdout or checked.stderr or checked.returncode not in (0, 1): raise ValueError(f"Whitespace: {name}: {checked.stdout}{checked.stderr}")
    if any(sha(ROOT / name) != value for name, value in {**protected, **code_hashes}.items()): raise ValueError("Frozen sources changed; use a fresh run")
    coverage = json.loads((ROOT / "宏微观衔接方案/新版方案/action_coverage.json").read_text(encoding="utf-8"))
    record = next(row for row in coverage["actions"] if row["action_id"] == "OWN-A16")
    record.update(decision="partial_local_verified", method="partial_local_verified", validation="partial_local_verified", binding="unverified", feedback="pending",
        branches={choice: "partial_local_verified" for choice in sorted(actual)},
        local_processor={"processor_id": skill.processor_id, "code": "src/actions/roles/owner_proposal.py", "scope": "Authorized synthetic private proposal/revision only"},
        local_methods={"code": "src/methods/owner_proposal.py", "support": "Registered inclusive scale and ordinal joint review-budget checks", "registry_status": "registered_host_method", "calibration": "mathematical_only", "registry_digest": methods.content_digest},
        gaps=[{"kind": "formal_binding", "detail": "Actual authorized case/need/candidate producers and private record submit/query unbound"},
              {"kind": "feedback_recovery", "detail": "Private draft registration, A02/A03 continuation, receipts and recovery unbound"},
              {"kind": "real_method_calibration", "detail": "Need, engineering scale, ordinal preferences and point-in-time budgets are synthetic"},
              {"kind": "exclusive_rights_and_commitments", "detail": "No actual rights granting, formal resource reservation, financing or investment validation"}])
    record["evidence"] = list(dict.fromkeys([*record["evidence"], (output / "manifest.json").relative_to(ROOT).as_posix()]))
    inventory = json.loads((ROOT / "config/action_registry.json").read_text(encoding="utf-8"))
    artifacts = {"inputs.json": inputs, "runtime.json": calls, "draft_oracle.json": oracles, "coverage_record.json": record,
        "methods.json": {"registry_digest": methods.content_digest, "catalog": methods.catalog()}, "coverage.json": coverage_report(inventory, coverage),
        "skill_audit.json": registry.skill_audit(), "binding.json": {"action_id": "OWN-A16", "status": "not_bound", "macro_receipt": None, "limitations": LIMITATIONS},
        "checks.json": {"tests": totals, "unique_tests": len(tests), "role_tests": role_count, "method_tests": method_count, "test_commands": commands,
            "catalog": json.loads(indexed.stdout), "protected_files": len(protected), "protected_hashes": "matched", "branches": sorted(actual),
            "runtime_cases": len(calls), "source_checks": CHECKS, "model_calls": 0, "formal_receipts": 0}}
    for name, value in artifacts.items(): write_new(output / name, value)
    write_new(output / "manifest.json", {"schema_version": "plan-owner-proposal-evidence.v1", "action_id": "OWN-A16", "evidence_id": output.name,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "partial_local_verified", "source_sha256": catalog.get("OWN-A16").source_sha256,
        "processor_id": skill.processor_id, "skill_version": skill.skill_version, "method_registry_digest": methods.content_digest,
        "tests": totals, "unique_tests": len(tests), "role_tests": role_count, "method_tests": method_count, "runtime_cases": len(calls), "branches": sorted(actual), "checks": CHECKS,
        "protected": {"unchanged": True, "files": len(protected), "baseline": baseline.relative_to(ROOT).as_posix()}, "code_hashes": code_hashes,
        "artifact_hashes": {name: sha(output / name) for name in [*artifacts, "tests.xml", "tests.log", *[f"tests-worker-{index}.{suffix}" for index in range(workers) for suffix in ("xml", "log")]]},
        "environment": {"python": sys.version, "packages": {name: version(name) for name in ("pytest", "pydantic", "lark")}}, "limitations": LIMITATIONS})
    print(json.dumps({"output": str(output), "tests": totals, "role_tests": role_count, "method_tests": method_count, "runtime_cases": len(calls), "protected": len(protected)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    verify(args.output, args.workers)


if __name__ == "__main__": main()
