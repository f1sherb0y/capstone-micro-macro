"""Freeze task recovery tests and separate real old wiring from fake transport."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

from integration.action_catalog import ROOT, write_new
from integration.bindings.gba_v1 import build_module_engine, macro_binding_source_hashes
from integration.verify_supplier import sha


TEST_MODULES = ("action_recovery", "gba_v1_binding", "macro_binding", "integration",
                "integration_context", "macro_views", "integration_workbench",
                "action_runner", "action_reading", "action_runtime_boundaries")


def replay_client(output):
    from tests.test_gba_v1_binding import Handlers, ROLES, inputs, make_client
    handlers = Handlers()
    request = inputs()
    directory = output / "old-macro-run"
    task_path = directory / "tasks.sqlite"
    client = make_client(directory, handlers, output.name, task_path=task_path)
    assembly = build_module_engine(request, client)
    assembly.engine.step(False)
    evidence = assembly.evidence()
    events = [event.model_dump(mode="json") for event in assembly.engine.events.events
              if event.event_type == "agent_operation"]
    counts = Counter((row["purpose"], row["status"]) for row in evidence["client"]["calls"])
    if (counts[("propose", "returned")] != 8 or counts[("decide", "returned")] != 8
            or counts[("observe", "recorded")] != 8 or counts[("observe", "duplicate")] != 8
            or len(events) != 8):
        raise ValueError("Actual module/final provider/observation paths did not all execute")
    for role in ROLES:
        rows = evidence["client"]["tasks"][role]
        if (len(rows) != 2 or any(row["state"] != "output_formed" or row["receipt"] is not None
                                 or row["submission"] is not None for row in rows)):
            raise ValueError("Old proposal/decision output became a formal receipt")
    for event in events:
        if event["data"]["operation"] != "maintain_operations" or event["data"].get("agent_observer_errors"):
            raise ValueError("Wrong final macro operation or failed feedback")
        own = client.inbox.for_organization(run_id=client.run_id, organization_id=event["agent_id"])
        if len(own) != 1 or own[0]["event_id"] != event["event_id"]:
            raise ValueError("Feedback is not recipient-isolated and deduplicated")
    simulation_id = client.simulation_id
    client.close()
    restored_handlers = Handlers()
    restored = make_client(directory, restored_handlers, output.name, task_path=task_path)
    restored.claim(restored.organization_roles)
    # Attach the existing identity only for client replay. No fresh engine or
    # macro restart is performed or claimed by this evidence.
    restored.attach(simulation_id)
    recovered = []
    for purpose, requests in (("propose", handlers.proposals), ("decide", handlers.decisions)):
        for original in requests:
            response = getattr(restored, purpose)(original)
            if response.request_id != original.request_id:
                raise ValueError("Recovery changed the original request ID")
            recovered.append({"purpose": purpose, "request": original.model_dump(mode="json"),
                              "response": response.model_dump(mode="json")})
    if restored_handlers.proposals or restored_handlers.decisions:
        raise ValueError("Output recovery invoked the handler again")
    recovered_evidence = restored.evidence()
    if len(recovered_evidence["calls"]) != 16 or any(row["status"] != "cache_hit" or not row["recovered"]
            for row in recovered_evidence["calls"]):
        raise ValueError("Incomplete durable output recovery")
    restored.close()
    write_new(output / "old-macro-inputs.json", {"origin": "synthetic", "request": request.model_dump(mode="json")})
    write_new(output / "assembly.json", evidence)
    write_new(output / "old-macro-events.json", events)
    write_new(output / "client-recovery.json", {"scope": "Client recovery only; no macro engine restart",
                                               "replays": recovered, "evidence": recovered_evidence})
    return {"actual_old_operations": len(events), "persisted_outputs": 16, "recovered_outputs": len(recovered),
            "recovery_handler_calls": 0, "new_action_macro_receipts": 0}


def replay_submission(output):
    from tests.test_action_recovery import SyntheticTransport, formed, identity, store
    cases = []
    for case in ("lost_response", "unavailable_query", "unconfirmed_query"):
        path = output / f"synthetic-{case}.sqlite"
        task, transport = identity(request_id=f"original:{case}"), SyntheticTransport()
        db = store(path)
        formed(db, task)
        transport.response_lost = True
        before = transport.binding(db).execute(task)
        if before["state"] != "receipt_unknown":
            raise ValueError("Lost response was treated as a known outcome")
        db.close()
        restored = store(path)
        options = {"query": None} if case == "unavailable_query" else {
            "query": lambda request: None} if case == "unconfirmed_query" else {}
        binding = transport.binding(restored, **options)
        after = binding.execute(task)
        expected = "reconciled" if case == "lost_response" else "receipt_unknown"
        if after["state"] != expected or len(transport.submissions) != 1:
            raise ValueError("Uncertain task was resubmitted or incorrectly reconciled")
        if case == "lost_response" and transport.submissions != transport.queries:
            raise ValueError("Receipt query changed the original invocation")
        if case != "lost_response" and after["receipt"] is not None:
            raise ValueError("Missing receipt query created execution evidence")
        cases.append({"case": case, "origin": "synthetic", "production_binding": None,
            "before_restart": before, "after_restart": after, "history": restored.history(task),
            "submit_count": len(transport.submissions), "query_count": len(transport.queries)})
        restored.close()
    write_new(output / "synthetic-submission-recovery.json", cases)
    return {"synthetic_replays": len(cases), "duplicate_submissions": 0,
            "synthetic_reconciled": 1, "synthetic_unknown": 2, "production_action_bindings": 0}


def verify(output):
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        raise ValueError("Use a new evidence directory within the repository")
    baseline_path = ROOT / "output/integration/plan_20261002_implementation/baseline.json"
    protected = json.loads(baseline_path.read_text(encoding="utf-8"))["protected_hashes"]
    if any(sha(ROOT / name) != digest for name, digest in protected.items()):
        raise ValueError("Protected sources differ from baseline")
    paths = []
    for directory in ("src", "integration", "tests", "skills", "config/roles"):
        paths.extend(path for path in (ROOT / directory).rglob("*")
                     if path.is_file() and path.suffix in {".py", ".md", ".json"})
    paths.append(ROOT / "config/action_registry.json")
    frozen = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
    output.mkdir(parents=True)
    command = [sys.executable, "-u", "-m", "pytest", *[f"tests/test_{name}.py" for name in TEST_MODULES],
               "-q", "--disable-warnings", "-o", "faulthandler_timeout=60", f"--junitxml={output / 'tests.xml'}"]
    print("Running task recovery and shared boundary regression", flush=True)
    with (output / "tests.log").open("x", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
    suites = ElementTree.parse(output / "tests.xml").getroot().findall("testsuite")
    totals = {field: sum(int(suite.get(field, "0")) for suite in suites)
              for field in ("tests", "failures", "errors", "skipped")}
    if result.returncode or not totals["tests"] or any(totals[field] for field in ("failures", "errors", "skipped")):
        raise ValueError(f"Regression failed: {totals}; inspect tests.log")
    print("Replaying persisted old client outputs and synthetic uncertain submissions", flush=True)
    client = replay_client(output)
    submission = replay_submission(output)
    catalog = subprocess.run([sys.executable, "-m", "integration.action_catalog", "--check"],
                             cwd=ROOT, capture_output=True, text=True)
    if catalog.returncode:
        raise ValueError(catalog.stdout + catalog.stderr)
    if (any(sha(ROOT / name) != digest for name, digest in protected.items())
            or any(sha(ROOT / name) != digest for name, digest in frozen.items())):
        raise ValueError("Frozen sources changed during verification")
    artifacts = {p.relative_to(output).as_posix(): sha(p) for p in output.rglob("*") if p.is_file()}
    write_new(output / "manifest.json", {
        "schema_version": "plan-task-recovery-evidence.v1", "run_id": output.name,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "tests": totals, "command": command,
        "client_replay": client, "submission_replay": submission,
        "protected": {"unchanged": True, "files": len(protected),
                      "baseline": baseline_path.relative_to(ROOT).as_posix(), "sha256": sha(baseline_path)},
        "code_hashes": frozen, "artifact_hashes": artifacts, "macro_source_hashes": macro_binding_source_hashes(),
        "environment": {"python": sys.version, "pytest": version("pytest"), "pydantic": version("pydantic")},
        "model_calls": 0, "formal_106_action_receipts": 0,
        "limitations": ["All handlers/inputs and generic submission transports are explicit synthetic fixtures",
            "Actual bundled macro verifies old monthly operation wiring only; no 106-action mapping",
            "Client journal recovery does not restart or restore a macro engine",
            "No production submit/query binding, receipt-event correlation or automatic pending-action wakeup",
            "No negotiation version/independent acceptance coordination or model quality evidence",
            "9 local action processors remain implemented; the other 97 and all 106 formal bindings remain incomplete"],
    })
    print(json.dumps({"tests": totals, "client": client, "submission": submission, "protected": len(protected)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    verify(parser.parse_args().output)
