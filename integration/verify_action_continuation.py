"""Freeze computable wakeup and exact new-invocation recovery evidence."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

from integration.action_catalog import ROOT, write_new
from integration.verify_consortium_recovery import TEST_MODULES as SHARED_TESTS
from integration.verify_supplier import sha


TEST_MODULES = (*SHARED_TESTS, "action_continuation", "owner_observation")


def replay(output):
    from integration.observations import ObservationInbox
    from integration.task_continuation import ObservationContinuationDispatcher
    from src.actions.contracts.common import ActionContext
    from src.coordination.continuations import ContinuationJournal
    from src.coordination.tasks import TaskIdentity, TaskStore
    from tests.test_action_continuation import build, signal, preparation, owner_case
    records = []
    # Simulate a host interruption after observation persistence; replay the
    # actual inbox after opening both stores again, without re-sending events.
    store, journal, source, original = build(output / "synthetic-tasks.sqlite")
    event = signal()
    inbox = ObservationInbox("fixture-run", ["Supplier", "Owner"], output / "synthetic-inbox.json")
    inbox.deliver(run_id=event.run_id, organization_id=event.organization_id, event_id=event.event_id, payload=event.payload)
    def interrupted(*args):
        raise ConnectionError("Explicit synthetic host interruption")
    dispatcher = ObservationContinuationDispatcher(inbox=inbox, journal=journal,
        project_signal=lambda row: event.model_dump(mode="json"), prepare=interrupted, revalidate=lambda *args: True)
    try:
        dispatcher(run_id=event.run_id, organization_id=event.organization_id)
    except ConnectionError:
        pass
    else:
        raise ValueError("Synthetic interruption did not occur")
    if store.get(source) != original or store.continuation(source) is not None:
        raise ValueError("Interrupted wakeup consumed the original wait")
    store.close()
    store = TaskStore(run_id="fixture-run", organization_ids=["Supplier", "Owner"], path=output / "synthetic-tasks.sqlite")
    journal = ContinuationJournal(store, journal.registry)
    inbox = ObservationInbox("fixture-run", ["Supplier", "Owner"], output / "synthetic-inbox.json")
    dispatcher = ObservationContinuationDispatcher(inbox=inbox, journal=journal,
        project_signal=lambda row: event.model_dump(mode="json"), prepare=preparation, revalidate=lambda *args: True)
    links = dispatcher(run_id=event.run_id, organization_id=event.organization_id)
    if len(links) != 1 or dispatcher(run_id=event.run_id, organization_id=event.organization_id):
        raise ValueError("Saved event failed to wake once or created a duplicate successor")
    ready = journal.ready(run_id=event.run_id, organization_id=event.organization_id)
    if len(ready) != 1 or journal.ready(run_id="fixture-run", organization_id="Owner"):
        raise ValueError("Ready tasks are missing or leak to a competitor")
    records.append({"case": "feedback-persisted-before-interruption", "origin": "synthetic", "initial": original,
        "link": links[0], "ready_after_restart": ready, "original_after_restart": store.get(source),
        "history": store.history(source), "formal_receipt": None})
    store.close()

    # Run the actual registered Owner Skill/processor with authorized synthetic
    # facts. Load the queued input/context from disk before invoking it.
    store, journal, source, original, current, event, prepare = owner_case(output / "local-owner")
    before = deepcopy(current.objects)
    links = journal.wake(event, prepare=prepare,
        revalidate=lambda *args: bool(current.runner.organizations.grants(current.context, "OWN-A01", "Owner")))
    if len(links) != 1:
        raise ValueError("Real local Owner condition did not produce a successor")
    path, registry = store.path, journal.registry
    store.close()
    store = TaskStore(run_id="synthetic-owner", organization_ids=[source.organization_id], path=path)
    journal = ContinuationJournal(store, registry)
    ready = journal.ready(run_id=source.run_id, organization_id=source.organization_id)
    if len(ready) != 1:
        raise ValueError("Owner continuation snapshots were not recovered")
    invocation = ready[0]
    successor = TaskIdentity(**invocation["task"]["identity"])
    started = store.start(successor, invocation["task"]["revision"])
    result = current.runner.run_action(ActionContext.model_validate(invocation["continuation"]["next_context"]),
                                       invocation["continuation"]["next_input"])
    completed = store.finish(successor, started["revision"], output=result.model_dump(mode="json"))
    if (result.kind != "completed" or result.payload.choice != "create_case" or current.objects != before
            or store.get(source)["output"] is not None or completed["receipt"] is not None
            or journal.wake(event, prepare=prepare, revalidate=lambda *args: True)):
        raise ValueError("Owner wakeup altered formal facts, replayed old output or failed current action validation")
    records.append({"case": "owner-capacity-deferred-to-current-screening", "origin": "synthetic", "initial": original,
        "signal": event.model_dump(mode="json"), "link": invocation["continuation"], "completed_task": completed,
        "source_history": store.history(source), "successor_history": store.history(successor),
        "before_objects": before, "after_objects": deepcopy(current.objects),
        "action_audit": [row.as_dict() for row in current.runner.audit_records], "formal_receipt": None})
    store.close()
    write_new(output / "continuation-replay.json", records)
    return {"synthetic_cases": 2, "saved_feedback_recoveries": 1, "actual_local_owner_actions": 1,
            "duplicate_successors": 0, "formal_state_changes": 0, "formal_receipts": 0}


def verify(output):
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        raise ValueError("Use a fresh evidence directory within the repository")
    baseline = ROOT / "output/integration/plan_20261002_implementation/baseline.json"
    protected = json.loads(baseline.read_text(encoding="utf-8"))["protected_hashes"]
    if any(sha(ROOT / name) != digest for name, digest in protected.items()):
        raise ValueError("Protected sources differ from baseline")
    paths = []
    for directory in ("src", "integration", "tests", "skills", "config/roles", "prompts"):
        paths.extend(path for path in (ROOT / directory).rglob("*")
                     if path.is_file() and path.suffix in {".py", ".md", ".json"})
    paths.append(ROOT / "config/action_registry.json")
    frozen = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
    output.mkdir(parents=True)
    command = [sys.executable, "-u", "-m", "pytest", *[f"tests/test_{name}.py" for name in TEST_MODULES],
               "-q", "--disable-warnings", "-o", "faulthandler_timeout=60", f"--junitxml={output / 'tests.xml'}"]
    os.environ["CODEDEMO_PROGRESS"] = "0"
    print("Running continuation, Owner and shared recovery regression", flush=True)
    with (output / "tests.log").open("x", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
    suites = ElementTree.parse(output / "tests.xml").getroot().findall("testsuite")
    totals = {field: sum(int(suite.get(field, "0")) for suite in suites) for field in ("tests", "failures", "errors", "skipped")}
    if result.returncode or not totals["tests"] or any(totals[field] for field in ("failures", "errors", "skipped")):
        raise ValueError(f"Regression failed: {totals}; inspect tests.log")
    print("Replaying persisted feedback and exact Owner continuation snapshots", flush=True)
    result = replay(output)
    catalog = subprocess.run([sys.executable, "-m", "integration.action_catalog", "--check"], cwd=ROOT, capture_output=True, text=True)
    if catalog.returncode:
        raise ValueError(catalog.stdout + catalog.stderr)
    if (any(sha(ROOT / name) != digest for name, digest in frozen.items())
            or any(sha(ROOT / name) != digest for name, digest in protected.items())):
        raise ValueError("Frozen source changed during verification")
    artifacts = {path.relative_to(output).as_posix(): sha(path) for path in output.rglob("*") if path.is_file()}
    write_new(output / "manifest.json", {"schema_version": "plan-action-continuation-evidence.v1", "run_id": output.name,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "tests": totals, "command": command, "continuation_replay": result,
        "code_hashes": frozen, "artifact_hashes": artifacts,
        "protected": {"files": len(protected), "unchanged": True, "baseline": baseline.relative_to(ROOT).as_posix(), "sha256": sha(baseline)},
        "environment": {"python": sys.version, "pytest": version("pytest"), "pydantic": version("pydantic")},
        "api_model_calls": 0, "formal_106_action_receipts": 0,
        "limitations": ["Signals, data and current authority are explicit synthetic fixtures",
            "Only local OWN-A01 management capacity has a supplied business condition profile",
            "Other profiles, real condition event projections and formal 106-action adapters remain incomplete",
            "Scheduler creates technical successor tasks; it does not execute a model, submit a business command or form a receipt",
            "Host must replay saved feedback on startup and recheck facts/authorization at actual action execution",
            "No macro clock advancement, resource reservation, acceptance carryover or full engine restart claim",
            "9 local processors, 97 pending and all 106 formal bindings/feedback remain incomplete"]})
    print(json.dumps({"tests": totals, "continuation": result, "protected": len(protected)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    verify(parser.parse_args().output)
