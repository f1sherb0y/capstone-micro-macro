"""Sourced local negotiation recovery and existing legacy procurement evidence."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

from integration.action_catalog import ROOT, write_new
from integration.verify_action_recovery import TEST_MODULES as RECOVERY_TEST_MODULES, replay_client, replay_submission
from integration.verify_supplier import sha


TEST_MODULES = (*RECOVERY_TEST_MODULES, "negotiation_recovery")


def replay_local(output):
    from tests.test_negotiation_recovery import journal, propose, decide, unanimous, no_check
    records = []
    path = output / "synthetic-negotiations.sqlite"
    with journal(path) as db:
        original = propose(db)
        decide(db, original)
        if unanimous(db, original):
            raise ValueError("One party formed a unanimous draft")
    with journal(path) as db:
        row = db.latest(negotiation_id=original["negotiation_id"], recipient_id="buyer")
        records.append({"case": "partial_after_restart", "draft": row, "unanimous": unanimous(db, row)})
        decide(db, row, "supplier")
        if not unanimous(db, row):
            raise ValueError("Matching independent decisions did not authorize their local draft")
        revised = propose(db, 1, terms=row["terms"] | {"price": "110"})
        if revised["choices"] or unanimous(db, revised):
            raise ValueError("Historical acceptance was transferred to revised terms")
        records.append({"case": "new_revision_waits", "draft": revised, "unanimous": False})
        decide(db, revised)
        decide(db, revised, "supplier")
        db.withdraw_choice(negotiation_id=revised["negotiation_id"], revision=1, party_id="supplier",
            operation_id="synthetic-withdraw", authenticated_party="supplier", revalidate=no_check)
        if unanimous(db, revised):
            raise ValueError("Withdrawn choice still formed local unanimity")
        records.append({"case": "withdrawn_choice", "draft": db.get(negotiation_id=revised["negotiation_id"],
            revision=1, recipient_id="supplier"), "unanimous": False})
        history = db.history(negotiation_id=row["negotiation_id"], recipient_id="buyer")
        events = db.events(negotiation_id=row["negotiation_id"], recipient_id="buyer")
    write_new(output / "synthetic-negotiation-replay.json", {
        "origin": "synthetic", "formal_receipts": 0, "records": records, "versions": history, "events": events})
    return {"synthetic_cases": len(records), "preserved_revisions": len(history), "formal_receipts": 0}


def replay_procurement(output):
    import asyncio
    from integration.contracts import IntegrationError
    from integration.fixture_client import IntegrationFixtureClient
    from integration.sessions import ProcurementSession
    from integration.shared_data import SharedDataset
    from tests.test_integration import FIXTURE, create

    class InterruptedFixture(IntegrationFixtureClient):
        def __init__(self):
            super().__init__()
            self.fail = True
            self.reviews = []

        def chat(self, messages, temperature=.2):
            prompt = messages[-1]["content"]
            if prompt.startswith("CONTRACT_ACCEPTANCE"):
                terms = json.loads(prompt.split("\nTerms: ", 1)[1].splitlines()[0])
                party = prompt.split("Company id: ", 1)[1].splitlines()[0]
                self.reviews.append({"proposal_id": terms["proposal_id"], "party": party,
                                     "terms_hash": terms["signed_terms_hash"]})
                if self.fail and party != terms["buyer_id"]:
                    raise RuntimeError("Synthetic counterparty unavailable after buyer choice")
            return super().chat(messages, temperature)

    dataset, client = SharedDataset.load(FIXTURE), InterruptedFixture()
    engine = create(dataset, output / "legacy-run", client)
    # All handlers and data are synthetic, with the explicit old rule provider
    # supplied by create(); this is existing procurement, not 106-action binding.
    try:
        engine.step(False)
    except IntegrationError:
        pass
    else:
        raise ValueError("Injected counterparty failure did not interrupt procurement")
    session = next(row for row in engine.procurement_executor.sessions.values() if row.status == "failed")
    if session.next_stage != 8 or session.proposal is not None or engine.current_tick != 0:
        raise ValueError("Technical failure advanced the engine or created a contract")
    with session._negotiation_journal() as journal:
        partial = journal.latest(negotiation_id=session.session_id + "/contract", recipient_id=session.buyer_id)
    if set(partial["choices"]) != {session.buyer_id}:
        raise ValueError("Buyer choice was lost or counterparty acceptance fabricated")
    allocation_count = sum(row[-1]["content"].startswith("CONTRACT_ALLOCATION") for row in client.requests)
    before = {key: agent.occupied_resource for key, agent in engine.agents.items()}
    restored = ProcurementSession(dataset, session.spec, session.snapshot, session.buyer_id,
        engine.procurement_executor.registry, client, session.path.parent)
    client.fail = False
    asyncio.run(restored.advance_to("signatures"))
    restored.verify_negotiation(restored.proposal)
    buyer_calls = sum(row["party"] == restored.buyer_id and row["proposal_id"] == restored.proposal.proposal_id
                      for row in client.reviews)
    if buyer_calls != 1 or allocation_count != sum(row[-1]["content"].startswith("CONTRACT_ALLOCATION") for row in client.requests):
        raise ValueError("Restoration repeated accepted buyer review or changed allocation")
    committer = engine.procurement_executor.committer
    receipt = committer.commit(restored, engine.current_tick)
    after = {key: agent.occupied_resource for key, agent in engine.agents.items()}
    if not any(after[key] != value for key, value in before.items()):
        raise ValueError("Existing commit did not consume the reviewed resource promises")
    if committer.commit(restored, engine.current_tick) != receipt or after != {
            key: agent.occupied_resource for key, agent in engine.agents.items()}:
        raise ValueError("Duplicate legacy commit changed resources or receipt")
    with restored._negotiation_journal() as journal:
        history = journal.history(negotiation_id=restored.proposal.proposal_id, recipient_id=restored.buyer_id)
        events = journal.events(negotiation_id=restored.proposal.proposal_id, recipient_id=restored.buyer_id)
    write_new(output / "legacy-procurement-recovery.json", {
        "origin": "synthetic", "mode": "legacy_procurement", "new_action_binding": None,
        "input": dataset.payload, "snapshot": asdict(restored.snapshot), "partial_draft": partial,
        "proposal": asdict(restored.proposal), "raw_legacy_receipt": receipt, "journal_versions": history,
        "journal_events": events, "fixture_reviews": client.reviews, "buyer_review_count": buyer_calls,
        "initial_allocation_count": allocation_count, "before_resources": before, "after_resources": after,
        "duplicate_commit_resources": {key: agent.occupied_resource for key, agent in engine.agents.items()},
        "events": [event.model_dump(mode="json") for event in engine.events.events]})
    return {"existing_legacy_receipts": 1, "new_106_action_receipts": 0, "buyer_reviews": buyer_calls,
            "initial_allocation_calls": allocation_count, "duplicate_resource_changes": 0}


def verify(output):
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        raise ValueError("Choose a new evidence directory within the repository")
    baseline_path = ROOT / "output/integration/plan_20261002_implementation/baseline.json"
    protected = json.loads(baseline_path.read_text(encoding="utf-8"))["protected_hashes"]
    if any(sha(ROOT / name) != digest for name, digest in protected.items()):
        raise ValueError("Protected sources differ from baseline")
    paths = []
    for directory in ("src", "integration", "tests", "skills", "config/roles"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.is_file() and path.suffix in {".py", ".md", ".json"})
    paths.append(ROOT / "config/action_registry.json")
    frozen = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
    output.mkdir(parents=True)
    command = [sys.executable, "-u", "-m", "pytest", *[f"tests/test_{name}.py" for name in TEST_MODULES],
        "-q", "--disable-warnings", "-o", "faulthandler_timeout=60", f"--junitxml={output / 'tests.xml'}"]
    print("Running negotiation and shared procurement/recovery regression", flush=True)
    with (output / "tests.log").open("x", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
    suites = ElementTree.parse(output / "tests.xml").getroot().findall("testsuite")
    totals = {field: sum(int(suite.get(field, "0")) for suite in suites) for field in ("tests", "failures", "errors", "skipped")}
    if result.returncode or not totals["tests"] or any(totals[field] for field in ("failures", "errors", "skipped")):
        raise ValueError(f"Regression failed: {totals}; see tests.log")
    print("Replaying local versions, legacy partial-choice restoration, old client and uncertain submissions", flush=True)
    local, procurement = replay_local(output), replay_procurement(output)
    client, submission = replay_client(output), replay_submission(output)
    if (any(sha(ROOT / name) != digest for name, digest in protected.items())
            or any(sha(ROOT / name) != digest for name, digest in frozen.items())):
        raise ValueError("Source changed during verification; use a fresh run")
    artifacts = {path.relative_to(output).as_posix(): sha(path) for path in output.rglob("*") if path.is_file()}
    write_new(output / "manifest.json", {
        "schema_version": "plan-negotiation-recovery-evidence.v1", "run_id": output.name,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "tests": totals, "command": command,
        "local_replay": local, "legacy_procurement": procurement, "client_recovery": client, "submission_recovery": submission,
        "protected": {"unchanged": True, "files": len(protected), "baseline": baseline_path.relative_to(ROOT).as_posix(),
                      "sha256": sha(baseline_path)}, "code_hashes": frozen, "artifact_hashes": artifacts,
        "model_calls": 0, "formal_106_action_receipts": 0,
        "limitations": ["Synthetic inputs, authorization contexts and model answers; no model quality or real qualification evidence",
            "Actual existing legacy procurement receipt is separate from 106 new action bindings",
            "Micro draft choices are not formal PartyAcceptance records, formation receipts or changes to original obligations",
            "Common journal requires host-authenticated parties and current authorization validation; no new role-specific adapters",
            "Legacy contract partial-choice recovery only; consortium proposal/acceptance recovery and condition wakeup remain incomplete",
            "No macro-engine process resume or negotiation-based automatic resource reservation",
            "9 local processors, 97 pending; all 106 new bindings and feedback paths remain incomplete"]})
    print(json.dumps({"tests": totals, "local": local, "legacy": procurement, "protected": len(protected)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    verify(parser.parse_args().output)
