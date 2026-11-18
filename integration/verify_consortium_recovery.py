"""Freeze candidate/member recovery and its effect on existing procurement."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

from integration.action_catalog import ROOT, write_new
from integration.verify_negotiation_recovery import TEST_MODULES as NEGOTIATION_TESTS, replay_local, replay_procurement
from integration.verify_action_recovery import replay_client, replay_submission
from integration.verify_supplier import sha


TEST_MODULES = (*NEGOTIATION_TESTS, "consortium_recovery")


def replay_consortium(output):
    import asyncio
    from copy import deepcopy
    from dataclasses import asdict
    from integration.contracts import IntegrationError
    from integration.sessions import ProcurementSession
    from src.models import dump
    from tests.test_consortium_recovery import InterruptedConsortium, build_session
    records = []
    for action in ("accept", "reject", "revise"):
        engine, session, client = build_session(output / ("legacy-consortium-" + action),
                                               InterruptedConsortium(action=action))
        initial_state = dump(session.state)
        before_resources = {key: agent.occupied_resource for key, agent in engine.agents.items()}
        try:
            asyncio.run(session.advance_to("consortiums"))
        except IntegrationError:
            pass
        else:
            raise ValueError("Synthetic member failure did not interrupt consortium acceptance")
        if session.next_stage != 2 or session.state.consortiums or dump(session.state) != initial_state:
            raise ValueError("Failed stage consumed state or admitted a partial consortium")
        with session._negotiation_journal() as journal:
            if journal.store.for_organization(run_id=session.snapshot.simulation_id, organization_id=session.buyer_id):
                raise ValueError("Private host audit checkpoint entered the ordinary recipient task view")
            tasks = journal.store.for_organization(run_id=session.snapshot.simulation_id,
                organization_id=session.buyer_id, include_host_audit=True)
            batch = next(row for row in tasks if row["identity"]["action_id"] == "legacy:consortium-proposal-batch")
            candidates = batch["output"]["consortiums"]
            if batch["state"] != "output_formed" or len(candidates) != 1:
                raise ValueError("Failed member review lost the candidate generation checkpoint")
            candidate = candidates[0]
            negotiation_id = session.session_id + "/consortium/" + candidate["consortium_id"]
            partial = journal.latest(negotiation_id=negotiation_id, recipient_id=candidate["lead_company_id"])
            if set(partial["choices"]) != {candidate["lead_company_id"]}:
                raise ValueError("Partial independent choice was lost or another party's acceptance invented")
        generation_count = sum(row[-1]["content"].startswith("CONSORTIUM\n") for row in client.requests)
        client.fail = False
        restored = ProcurementSession(session.dataset, session.spec, session.snapshot, session.buyer_id,
            session.registry, client, session.path.parent)
        asyncio.run(restored.advance_to("bids"))
        lead_count = sum(row["party"] == candidate["lead_company_id"] for row in client.reviews)
        if lead_count != 1 or generation_count != 1 or sum(row[-1]["content"].startswith("CONSORTIUM\n")
                for row in client.requests) != 1:
            raise ValueError("Recovery repeated generation or an already accepted lead decision")
        if action == "accept":
            restored.verify_consortiums()
            if ([asdict(row) for row in restored.state.consortiums] != candidates
                    or not any(bid.bidder_id == candidate["consortium_id"] for bid in restored.state.bid_documents)):
                raise ValueError("Accepted same-version consortium did not enter bid preparation")
        elif restored.state.consortiums or any(bid.bidder_id == candidate["consortium_id"] for bid in restored.state.bid_documents):
            raise ValueError("Member nonacceptance was converted to an accepted consortium bid")
        if before_resources != {key: agent.occupied_resource for key, agent in engine.agents.items()} or restored.proposal is not None:
            raise ValueError("Consortium draft/review created a resource commitment or contract")
        with restored._negotiation_journal() as journal:
            versions = journal.history(negotiation_id=negotiation_id, recipient_id=candidate["lead_company_id"])
            events = journal.events(negotiation_id=negotiation_id, recipient_id=candidate["lead_company_id"])
            if len(versions) != 1 or len(versions[0]["choices"]) != len(candidate["member_company_ids"]):
                raise ValueError("Independent member decision history is incomplete")
        # Freeze only recipient-filtered contexts; host audit evidence is saved
        # separately below and never becomes an organization's combined input.
        contexts = []
        for messages in client.requests:
            prompt = messages[-1]["content"]
            if "Authorized decision context:\n" in prompt:
                context = json.loads(prompt.split("Authorized decision context:\n", 1)[1])
                if "private" in context or "agent_discussion_history" in context:
                    raise ValueError("Decision context contains combined private data")
                contexts.append(context)
        record = {"case": action, "origin": "synthetic", "mode": "legacy_procurement", "new_action_binding": None,
            "snapshot": asdict(restored.snapshot), "initial_state": initial_state, "host_only_batch": batch,
            "partial_member_review": partial, "restored_consortiums": [asdict(row) for row in restored.state.consortiums],
            "restored_bids": [asdict(row) for row in restored.state.bid_documents], "versions": versions, "events": events,
            "fixture_member_reviews": deepcopy(client.reviews), "recipient_contexts": contexts,
            "lead_review_count": lead_count, "generation_count": generation_count,
            "before_resources": before_resources, "after_resources": {key: agent.occupied_resource for key, agent in engine.agents.items()},
            "formal_receipt": None, "api_model_calls": 0}
        records.append(record)
    write_new(output / "consortium-recovery-replay.json", records)
    return {"synthetic_cases": len(records), "generation_calls_per_case": 1, "lead_reviews_per_case": 1,
            "accepted_consortium_bids": 1, "business_nonacceptance": 2, "resource_changes": 0, "formal_receipts": 0}


def verify(output):
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        raise ValueError("Choose a fresh evidence directory within the repository")
    baseline = ROOT / "output/integration/plan_20261002_implementation/baseline.json"
    protected = json.loads(baseline.read_text(encoding="utf-8"))["protected_hashes"]
    if any(sha(ROOT / name) != digest for name, digest in protected.items()):
        raise ValueError("Protected sources differ from baseline")
    paths = []
    for directory in ("src", "integration", "tests", "skills", "config/roles", "prompts"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file() and path.suffix in {".py", ".md", ".json"})
    paths.append(ROOT / "config/action_registry.json")
    frozen = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
    output.mkdir(parents=True)
    command = [sys.executable, "-u", "-m", "pytest", *[f"tests/test_{name}.py" for name in TEST_MODULES],
               "-q", "--disable-warnings", "-o", "faulthandler_timeout=60", f"--junitxml={output / 'tests.xml'}"]
    os.environ["CODEDEMO_PROGRESS"] = "0"
    print("Running consortium, negotiation and shared recovery/procurement regression", flush=True)
    with (output / "tests.log").open("x", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
    suites = ElementTree.parse(output / "tests.xml").getroot().findall("testsuite")
    totals = {field: sum(int(suite.get(field, "0")) for suite in suites) for field in ("tests", "failures", "errors", "skipped")}
    if result.returncode or not totals["tests"] or any(totals[field] for field in ("failures", "errors", "skipped")):
        raise ValueError(f"Regression failed: {totals}; inspect tests.log")
    print("Replaying partial member recovery and existing contract/client/submission boundaries", flush=True)
    consortium, negotiation = replay_consortium(output), replay_local(output)
    procurement = replay_procurement(output)
    client, submission = replay_client(output), replay_submission(output)
    catalog = subprocess.run([sys.executable, "-m", "integration.action_catalog", "--check"], cwd=ROOT, capture_output=True, text=True)
    if catalog.returncode:
        raise ValueError(catalog.stdout + catalog.stderr)
    if (any(sha(ROOT / name) != digest for name, digest in frozen.items())
            or any(sha(ROOT / name) != digest for name, digest in protected.items())):
        raise ValueError("Frozen source changed during verification")
    artifacts = {path.relative_to(output).as_posix(): sha(path) for path in output.rglob("*") if path.is_file()}
    write_new(output / "manifest.json", {
        "schema_version": "plan-consortium-recovery-evidence.v1", "run_id": output.name,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "tests": totals, "command": command,
        "consortium_recovery": consortium, "local_negotiation": negotiation, "legacy_procurement": procurement,
        "client_recovery": client, "submission_recovery": submission, "code_hashes": frozen, "artifact_hashes": artifacts,
        "protected": {"files": len(protected), "unchanged": True, "baseline": baseline.relative_to(ROOT).as_posix(),
                      "sha256": sha(baseline)}, "api_model_calls": 0, "formal_106_action_receipts": 0,
        "environment": {"python": sys.version, "pytest": version("pytest"), "pydantic": version("pydantic")},
        "limitations": ["Explicit synthetic data, participation/authorization contexts and model outputs",
            "Legacy consortium drafts and local decisions; no formal new-action PartyAcceptance or resource reservation",
            "Actual receipt evidence remains existing legacy procurement; no new-action macro bindings",
            "Recovery requires identical frozen input and execution versions; live processing is never auto-reset",
            "Host audit checkpoint contains private traces, hidden from ordinary recipient task queries and never delivered as combined model context",
            "Generic pending-condition wakeup, professional methods, new role-specific negotiation adapters and model quality remain incomplete",
            "No full macro-engine restart claim; 9 local processors, 97 pending and all 106 formal bindings/feedback incomplete"]})
    print(json.dumps({"tests": totals, "consortium": consortium, "legacy": procurement, "protected": len(protected)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    verify(parser.parse_args().output)
