"""Freeze bounded OWN-A02 studies, retained fee history and shared regression."""
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
from integration.verify_owner_proposal import TEST_MODULES as PROPOSAL_TEST_MODULES
from src.actions.contracts.catalog import ContractCatalog
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.methods.capacity import local_method_registry

TEST_MODULES = (*PROPOSAL_TEST_MODULES, "owner_study", "owner_study_method")
CHECKS = {
    "CHECK-OWN-003": "partial: actual incurred and earned-but-unpaid fees are retained when study stops/fails or investment is absent; formal fees/spending and investment persistence unbound",
    "CHECK-OWN-036": "partial: authorized limited study works without a formal project, final construction permit or received financing; later formal commitments remain separate and unbound",
    "CHECK-OWN-037": "partial: no-fact repeated questions reuse history, active work cannot be duplicated, new facts/scheduled review/remedy require explicit verified reassessment; formal task and fee deduplication unbound",
    "CHECK-OWN-040": "partial: linked-project history retains original case/study/debtor and actual unpaid fees without new obligations; actual project formation and debt inheritance binding unverified",
}
LIMITATIONS = [
    "Explicit synthetic cases, questions, professional qualification, authority, review costs, staff pools and reassessment triggers; no reality calibration",
    "At most 64 declared study candidates and one selected plan; exact currency/unit comparisons and fixed staff pools on one clock with half-open windows",
    "Current complete study history and actual fees required; disjoint funding deductions declared, no forecasts or automatic debt settlement",
    "Local bounded choice only, not a created task, signed commission, expenditure, resource reservation, project, permit, financing or receipt",
    "Actual authorized producers, formal task/commission submit/query, independent provider acceptance and action feedback/recovery remain unbound",
    "Repeated-question and retained-debt tests do not prove real formal task/fee deduplication or debt inheritance across project formation",
    "No real model quality evidence; remaining 106-action scope and formal bindings remain unfinished",
]


def cases():
    from tests.test_owner_study import facts, add_offer, narrow, add_history, add_brief, reassess, add_requirement, view, known, unknown, money, measured, add, ref
    rows = []
    for label, kind, choice in (
        ("internal", "completed", "internal_study"), ("commission", "completed", "commission"),
        ("narrow", "completed", "narrow"), ("stop", "completed", "stop"), ("partial_brief", "completed", "internal_study"),
        ("completed_history", "completed", "stop"), ("active_history", "completed", "stop"),
        ("failed_history", "completed", "stop"), ("stopped_history", "completed", "stop"),
        ("changed_information", "completed", "internal_study"), ("scheduled_review", "completed", "internal_study"),
        ("failed_remedy", "completed", "internal_study"), ("history_overrun_stop", "completed", "stop"),
        ("narrow_cap_shortage", "completed", "stop"), ("cash_shortage", "completed", "stop"),
        ("capacity_shortage", "completed", "stop"), ("capacity_released", "completed", "internal_study"),
        ("unqualified_provider", "completed", "stop"), ("offer_withdrawn", "completed", "stop"),
        ("no_offer_defer", "deferred", None), ("no_capacity_defer", "deferred", None),
        ("missing_questions", "needs_information", None), ("unknown_cost", "needs_information", None),
        ("unknown_cash", "needs_information", None), ("unknown_deductions", "needs_information", None),
        ("unknown_incurred", "needs_information", None), ("partial_history", "needs_information", None),
        ("stale_history", "needs_information", None), ("stale_debt", "needs_information", None),
        ("future_candidate", "needs_information", None), ("future_offer", "needs_information", None),
        ("unverified_reassessment", "needs_information", None), ("old_evidence", "technical_error", None),
        ("foreign_debtor", "technical_error", None), ("foreign_staff", "technical_error", None),
        ("foreign_author", "technical_error", None), ("fee_mismatch", "technical_error", None),
        ("old_case", "technical_error", None), ("history_omitted", "technical_error", None),
        ("narrow_scope_unchanged", "technical_error", None), ("currency", "unsupported", None),
        ("unit", "unsupported", None), ("clock", "unsupported", None), ("method", "unsupported", None),
        ("unrelated_extra_work", "technical_error", None), ("mixed_scope_questions", "technical_error", None),
        ("same_content_new_identity", "technical_error", None), ("same_content_new_version", "technical_error", None),
        ("mixed_old_and_new_evidence", "technical_error", None), ("changed_content_new_version", "completed", "internal_study"),
    ):
        data = facts()
        candidate, profile = view(data, "StudyCandidate"), view(data, "StudyProfile")
        if label == "commission": add_offer(data)
        elif label == "narrow": narrow(data)
        elif label == "stop": profile["policy"] = known("stop")
        elif label == "partial_brief": add_brief(data)
        elif label.endswith("_history") and label in {"completed_history", "active_history", "failed_history", "stopped_history"}:
            add_history(data, status=label.removesuffix("_history"))
        elif label in {"changed_information", "scheduled_review", "failed_remedy"}:
            reassess(data, trigger="failed_study_remedy" if label == "failed_remedy" else label,
                status="failed" if label == "failed_remedy" else "completed")
        elif label == "history_overrun_stop": add_history(data, spent="45", outstanding="45"); profile["policy"] = known("stop")
        elif label == "narrow_cap_shortage": narrow(data); candidate["expenditure_cap"] = known(money("24.99999999999999999999999999"))
        elif label == "cash_shortage":
            candidate["future_cost"] = known(money("51")); candidate["expenditure_cap"] = known(money("60")); data["input"]["spending_limit"] = money("60")
        elif label in {"capacity_shortage", "no_capacity_defer"}: candidate["allocations"][0]["quantity"] = measured("1.0000000000000000000000001")
        elif label == "capacity_released": view(data, "ResourcePool")["commitments"][0]["window"]["end"]["offset"] = 12
        elif label == "unqualified_provider": add_offer(data)["qualified"] = known(False)
        elif label == "offer_withdrawn": add_offer(data)["status"] = "withdrawn"
        elif label == "no_offer_defer": add_offer(data)["status"] = "withdrawn"
        elif label == "missing_questions": data["input"]["issue_refs"] = []
        elif label == "unknown_cost": candidate["future_cost"] = unknown()
        elif label == "unknown_cash": view(data, "FundingPosition")["actual_cash"] = unknown()
        elif label == "unknown_deductions": view(data, "FundingPosition")["deduction_policy"] = unknown()
        elif label == "unknown_incurred": add_history(data)["incurred_cost"] = unknown()
        elif label == "partial_history": profile["history_coverage"] = "partial"
        elif label == "stale_history": profile["as_of"]["offset"] = 9
        elif label == "stale_debt": add_history(data); view(data, "Obligation")["as_of"]["offset"] = 9
        elif label == "future_candidate": candidate["available_at"]["offset"] = 11
        elif label == "future_offer": add_offer(data)["available_at"]["offset"] = 11
        elif label == "unverified_reassessment": reassess(data); view(data, "Requirement")["verified"] = known(False)
        elif label == "old_evidence": reassess(data)["changed_evidence_refs"] = [candidate["evidence_refs"][0]]
        elif label == "foreign_debtor": add_history(data); view(data, "Obligation")["debtor_organization_id"] = "other"
        elif label == "foreign_staff": view(data, "ResourcePool")["organization_id"] = "other"
        elif label == "foreign_author": add_offer(data)["author_actor_id"] = "impersonator"
        elif label == "fee_mismatch": add_offer(data)["fee"] = known(money("19"))
        elif label == "old_case": candidate["case_ref"]["version"] = "2"
        elif label == "history_omitted": add_history(data); profile["history_refs"] = []
        elif label == "narrow_scope_unchanged": prior = narrow(data); candidate["task_scope"]["scope_ref"]["coverage_refs"] = deepcopy(prior["remaining_work_refs"])
        elif label == "currency": candidate["future_cost"]["value"]["currency"] = "USD"
        elif label == "unit": candidate["allocations"][0]["quantity"]["unit"] = "hours"
        elif label == "clock": candidate["available_at"]["clock_ref"]["version"] = "2"
        elif label == "method": profile["algorithm_code"] = "not-provided"
        elif label in {"unrelated_extra_work", "mixed_scope_questions"}:
            questions = ["unrelated"] if label == "unrelated_extra_work" else ["ground-condition", "unrelated"]
            work = add(data, "WorkScope", "extra-work", case_ref=data["input"]["case_ref"], research_permitted=known(True),
                question_codes=questions, effective_window=profile["effective_window"])
            candidate["task_scope"]["scope_ref"]["coverage_refs"].append(work["ref"])
            profile["permitted_scope"]["coverage_refs"].append(work["ref"])
            view(data, "Authorization")["scopes"] = [deepcopy(profile["permitted_scope"])]
            for allocation in candidate["allocations"]:
                allocation["task_target"]["scope_ref"] = deepcopy(candidate["task_scope"]["scope_ref"])
        elif label in {"same_content_new_identity", "same_content_new_version", "mixed_old_and_new_evidence", "changed_content_new_version"}:
            change = reassess(data)
            new_evidence = view(data, "Evidence")
            past = deepcopy(new_evidence)
            past["ref"] = ref("Evidence", new_evidence["ref"]["id"] if label.endswith("new_version") else "past-information")
            past["content_hash"] = "b" * 64
            data["objects"].append({"ref": past["ref"], "value": past})
            view(data, "StudyPlan")["information_basis_refs"] = [past["ref"]]
            if label.endswith("new_version"):
                new_evidence["ref"]["version"] = "2"
                change["changed_evidence_refs"] = [deepcopy(new_evidence["ref"])]
            if label.startswith("same_content"): new_evidence["content_hash"] = past["content_hash"]
            if label == "mixed_old_and_new_evidence":
                alias = deepcopy(past)
                alias["ref"] = ref("Evidence", "past-information-alias")
                data["objects"].append({"ref": alias["ref"], "value": alias})
                change["changed_evidence_refs"].append(alias["ref"])
        if label in {"no_offer_defer", "no_capacity_defer"}: profile["on_unavailable"] = known("defer")
        rows.append((label, data, kind, choice))
    return rows


def check_study(data, audit, payload, projections):
    """Recompute source budgets/history and every pool segment without methods."""
    def key(ref): return ref["kind"], ref["id"], ref["version"]
    objects = {key(row["ref"]): row["value"] for row in projections}
    if any(objects.get(key(row["ref"])) != row["value"] for row in data["objects"]):
        raise ValueError("Received study projection differs from frozen source fixture")
    source = lambda ref: objects[key(ref)]
    profile = source(data["input"]["study_profile_ref"])
    raw = payload.model_dump(mode="json")
    matches = [source(ref) for ref in profile["candidate_refs"] if source(ref)["choice"] == raw["choice"]
               and source(ref)["task_scope"] == raw["task_scope"] and source(ref)["window_ref"] == raw["window_ref"]
               and source(ref)["expenditure_cap"]["value"] == raw["expenditure_cap"]]
    if len(matches) != 1: raise ValueError("Decision does not match one unique source candidate")
    selected = matches[0]
    selected_questions = {source(ref)["question_code"] for ref in selected["issue_refs"]}
    covered_questions = set()
    for work_ref in raw["task_scope"]["scope_ref"]["coverage_refs"]:
        work_questions = set(source(work_ref)["question_codes"])
        if work_questions - selected_questions: raise ValueError("Study adds work outside selected registered questions")
        covered_questions.update(work_questions)
    if covered_questions != selected_questions: raise ValueError("Study does not cover every selected question")
    for change_ref in selected["reassessment_refs"]:
        change = source(change_ref)
        if change["trigger_code"] != "changed_information": continue
        past = source(change["prior_study_ref"])
        past_keys = set(map(key, past["information_basis_refs"]))
        past_hashes = {source(ref)["content_hash"] for ref in past["information_basis_refs"]}
        if not change["changed_evidence_refs"] or any(key(ref) in past_keys or source(ref)["content_hash"] in past_hashes
                for ref in change["changed_evidence_refs"]):
            raise ValueError("Reassessment reuses old information content or identity")
    amount = lambda row: Fraction(row["value"])
    funds = source(profile["funding_ref"])
    cash = amount(funds["actual_cash"]["value"]) - amount(funds["committed_cash"]["value"]) - amount(funds["restricted_cash"]["value"])
    future, cap = amount(selected["future_cost"]["value"]), amount(raw["expenditure_cap"])
    spent = Fraction()
    if raw["choice"] == "narrow":
        if raw["prior_study_ref"] != selected["prior_study_ref"]: raise ValueError("Narrowing changed prior version")
        prior = source(raw["prior_study_ref"])
        spent = amount(prior["incurred_cost"]["value"])
        if cap > amount(prior["expenditure_cap"]) or not set(map(key, raw["task_scope"]["scope_ref"]["coverage_refs"])) < set(map(key, prior["remaining_work_refs"])):
            raise ValueError("Narrowing expands a cap or fails to reduce original remaining work")
    if cap > amount(data["input"]["spending_limit"]) or future > cash or spent + future > cap:
        raise ValueError("Study exceeds independently calculated cash or expenditure cap")
    retained = []
    for ref in profile["history_refs"]:
        history = source(ref)
        for debt_ref in history["obligation_refs"]:
            debt = source(debt_ref)
            if debt["debtor_organization_id"] != data["organization_id"] or debt["origin_study_ref"] != ref:
                raise ValueError("Research changed original fee debtor or lineage")
            retained.append({"obligation_ref": debt_ref, "actual_due": debt["actual_due"], "actual_paid": debt["actual_paid"]})
    segments = []
    if raw["choice"] == "internal_study":
        if raw["allocations"] != selected["allocations"]: raise ValueError("Allocations differ from sourced plan")
        needed = {}
        for allocation in raw["allocations"]:
            identity = key(allocation["resource_ref"])
            needed[identity] = needed.get(identity, Fraction()) + amount(allocation["quantity"])
        window = source(raw["window_ref"])
        for identity, quantity in needed.items():
            pool = objects[identity]
            endpoints = {window["start"]["offset"], window["end"]["offset"], pool["effective_window"]["start"]["offset"], pool["effective_window"]["end"]["offset"]}
            for load in pool["commitments"]: endpoints.update([load["window"]["start"]["offset"], load["window"]["end"]["offset"]])
            points = sorted(endpoints)
            for begin, end in zip(points, points[1:]):
                if not window["start"]["offset"] <= begin < window["end"]["offset"]: continue
                total = amount(pool["total"]["value"]) if pool["effective_window"]["start"]["offset"] <= begin < pool["effective_window"]["end"]["offset"] else Fraction()
                used = sum(amount(row["quantity"]) for row in pool["commitments"] if row["window"]["start"]["offset"] <= begin < row["window"]["end"]["offset"])
                free = max(Fraction(), total - used)
                if quantity > free: raise ValueError("Study oversubscribes an actual shared staff pool")
                segments.append({"pool": identity, "start": begin, "end": end, "needed": str(quantity), "available": str(free)})
    elif raw["choice"] == "commission":
        if raw["offer_ref"] != selected["offer_ref"] or raw["offer_ref"] not in data["input"]["service_candidates"]:
            raise ValueError("Commission did not select a received exact offer")
        offer = source(raw["offer_ref"])
        if amount(offer["fee"]["value"]) != future or offer["client_organization_id"] != data["organization_id"] or offer["payer_organization_id"] != data["organization_id"]:
            raise ValueError("Commission changes offered fee, client or payer")
    call = audit["method_calls"][-1]
    if call["method_ref"]["id"] != "micro.owner.declared_study_budget" or call["result"]["kind"] != "ok":
        raise ValueError("Successful study bypasses the registered budget method")
    priorities = []
    for row in call["input"]["candidates"]:
        candidate = next(source(ref) for ref in profile["candidate_refs"] if source(ref)["local_key"] == row["local_key"])
        if row["future_cost"] != candidate["future_cost"]["value"] or row["expenditure_cap"] != candidate["expenditure_cap"]["value"] or row["priority"] != candidate["priority"]["value"]:
            raise ValueError("Method budget input differs from source candidate")
        historical = source(candidate["prior_study_ref"]) if candidate["choice"] == "narrow" else None
        source_spent = amount(historical["incurred_cost"]["value"]) if historical else Fraction()
        if amount(row["incurred_cost"]) != source_spent: raise ValueError("Budget omitted actual historical study cost")
        candidate_cap, candidate_cost = amount(row["expenditure_cap"]), amount(row["future_cost"])
        if candidate_cap <= amount(data["input"]["spending_limit"]) and candidate_cost <= cash and candidate_cost + source_spent <= candidate_cap and (historical is None or candidate_cap <= amount(historical["expenditure_cap"])):
            priorities.append((row["priority"], row["local_key"]))
    best = min(priority for priority, _ in priorities)
    preferred = [identity for priority, identity in priorities if priority == best]
    if preferred != [selected["local_key"]]: raise ValueError("Study selection bypasses explicit ordinal preference")
    return {"selected_key": selected["local_key"], "incurred_cost": str(spent), "future_cost": str(future), "cap": str(cap),
        "available_cash": str(cash), "retained_obligations": retained, "segments": segments}


def verify(output, workers=1):
    from tests.test_owner_study import build_run
    if not 1 <= workers <= 4: raise ValueError("Use one to four regression processes")
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists(): raise ValueError("Choose a new repository evidence directory")
    baseline = ROOT / "output/integration/plan_20261002_implementation/baseline.json"
    protected = json.loads(baseline.read_text(encoding="utf-8"))["protected_hashes"]
    if any(sha(ROOT / name) != value for name, value in protected.items()): raise ValueError("Protected baseline changed")
    paths = [ROOT / f"tests/test_{name}.py" for name in TEST_MODULES]
    paths.extend(ROOT / name for name in ("integration/verify_owner_study.py", "integration/verify_owner_proposal.py", "integration/verify_supplier_order.py", "integration/action_catalog.py",
        "integration/coverage.py", "integration/macro_views.py", "config/action_registry.json", "tests/fixtures/roles/owner_study.v1.json"))
    for directory in ("src/actions", "src/methods", "src/skills", "src/organization", "skills", "config/roles"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file() and path.suffix in {".py", ".md", ".json"})
    code_hashes = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
    output.mkdir(parents=True)
    commands = [[sys.executable, "-u", "-m", "pytest", *[f"tests/test_{name}.py" for name in TEST_MODULES[index::workers]],
        "-q", "--disable-warnings", "-o", "faulthandler_timeout=60", f"--junitxml={output / f'tests-worker-{index}.xml'}"] for index in range(workers)]
    print("Running frozen owner study and shared regression", flush=True)
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
    role_count = sum(module == "tests.test_owner_study" for module, _ in tests)
    method_count = sum(module == "tests.test_owner_study_method" for module, _ in tests)
    if any(returncodes) or any(totals[key] for key in ("failures", "errors", "skipped")): raise ValueError(f"Regression failed: {totals}; see tests.log")
    if role_count < 120 or method_count < 26 or len(tests) != totals["tests"]: raise ValueError("Incomplete or duplicate evidence")
    catalog, methods = ContractCatalog(), local_method_registry()
    registry = register_representative_processors(ActionRegistry(catalog=catalog))
    skill = registry.get("OWN-A02").skill.manifest
    inputs, calls, oracles = [], [], []
    print("Replaying study branches and independent source checks", flush=True)
    for label, data, kind, choice in cases():
        run = build_run(data, catalog=catalog, run_id=f"{output.name}:{label}")
        before = deepcopy(run.objects)
        result = run.execute()
        if result.kind != kind or choice and result.payload.choice != choice: raise ValueError(f"Unexpected {label}: {result}")
        audit = run.runner.audit_records[-1].as_dict()
        if run.objects != before or audit["method_registry_digest"] != methods.content_digest: raise ValueError("Source/method state changed")
        if choice in {"internal_study", "commission", "narrow"}: oracles.append({"case": label, "draft": check_study(data, audit, result.payload, before)})
        if choice == "stop" and set(result.payload.model_dump()) != {"choice", "note"}: raise ValueError("Stop emitted phantom study")
        inputs.append({"case": label, "origin": "synthetic", "context": run.context.model_dump(mode="json"), "input": run.input, "projections": run.objects})
        calls.append({"case": label, "result": result.model_dump(mode="json"), "audit": audit, "formal_submission": None, "macro_receipt": None, "model_calls": 0})
    actual = {row["result"]["payload"]["choice"] for row in calls if row["result"]["kind"] == "completed"}
    if actual != set(catalog.get("OWN-A02").choices): raise ValueError("Missing source branch")
    indexed = subprocess.run([sys.executable, "-m", "integration.action_catalog", "--check"], cwd=ROOT, capture_output=True, text=True)
    if indexed.returncode: raise ValueError(indexed.stdout + indexed.stderr)
    for name in code_hashes:
        checked = subprocess.run(["git", "-c", "core.whitespace=cr-at-eol", "diff", "--no-index", "--check", "/dev/null", name], cwd=ROOT, capture_output=True, text=True)
        if checked.stdout or checked.stderr or checked.returncode not in (0, 1): raise ValueError(f"Whitespace: {name}: {checked.stdout}{checked.stderr}")
    if any(sha(ROOT / name) != value for name, value in {**protected, **code_hashes}.items()): raise ValueError("Frozen sources changed; use a fresh run")
    coverage = json.loads((ROOT / "宏微观衔接方案/新版方案/action_coverage.json").read_text(encoding="utf-8"))
    record = next(row for row in coverage["actions"] if row["action_id"] == "OWN-A02")
    record.update(decision="partial_local_verified", method="partial_local_verified", validation="partial_local_verified", binding="unverified", feedback="pending",
        branches={choice: "partial_local_verified" for choice in sorted(actual)},
        local_processor={"processor_id": skill.processor_id, "code": "src/actions/roles/owner_study.py", "scope": "Authorized synthetic bounded research/internal/commission/narrow/stop only"},
        local_methods={"code": "src/methods/owner_study.py", "support": "Registered exact limited-study budget/priority and shared physical staff capacity", "registry_status": "registered_host_method", "calibration": "mathematical_only", "registry_digest": methods.content_digest},
        gaps=[{"kind": "formal_binding", "detail": "Actual authorized case/question/history/fee producers and limited task/commission submit/query unbound"},
              {"kind": "feedback_recovery", "detail": "Formal study registration, independent provider acceptance, investment continuation, receipts and recovery unbound"},
              {"kind": "real_method_calibration", "detail": "Professional qualification, staff capacity, review costs, reassessment triggers and funding are synthetic"},
              {"kind": "actual_fees_and_debt_lineage", "detail": "No actual fee creation/payment, task reservation or debt inheritance across formal project formation verified"}])
    record["evidence"] = list(dict.fromkeys([*record["evidence"], (output / "manifest.json").relative_to(ROOT).as_posix()]))
    inventory = json.loads((ROOT / "config/action_registry.json").read_text(encoding="utf-8"))
    artifacts = {"inputs.json": inputs, "runtime.json": calls, "study_oracle.json": oracles, "coverage_record.json": record,
        "methods.json": {"registry_digest": methods.content_digest, "catalog": methods.catalog()}, "coverage.json": coverage_report(inventory, coverage),
        "skill_audit.json": registry.skill_audit(), "binding.json": {"action_id": "OWN-A02", "status": "not_bound", "macro_receipt": None, "limitations": LIMITATIONS},
        "checks.json": {"tests": totals, "unique_tests": len(tests), "role_tests": role_count, "method_tests": method_count, "test_commands": commands,
            "catalog": json.loads(indexed.stdout), "protected_files": len(protected), "protected_hashes": "matched", "branches": sorted(actual),
            "runtime_cases": len(calls), "source_checks": CHECKS, "model_calls": 0, "formal_receipts": 0}}
    for name, value in artifacts.items(): write_new(output / name, value)
    write_new(output / "manifest.json", {"schema_version": "plan-owner-study-evidence.v1", "action_id": "OWN-A02", "evidence_id": output.name,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "partial_local_verified", "source_sha256": catalog.get("OWN-A02").source_sha256,
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
