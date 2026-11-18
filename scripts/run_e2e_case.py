"""Run one case end to end with a real model: micro procurement inside the macro lifecycle.

Run:  python -m scripts.run_e2e_case --case CASE-0014 --output runs/<run-id>

Micro side (real LLM): owner packaging plan, tender requirements, participation,
bid documents, evaluation, award and contract signatures for every package.
Macro side (GBA rules): design, construction, payment, closeout state per tick.
Outputs go to a NEW directory under runs/. Nothing from an earlier run is replayed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--case", default="CASE-0014")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--ticks", type=int, default=120)
    parser.add_argument("--budget", type=float, default=150_000_000)
    parser.add_argument("--duration", type=int, default=24)
    parser.add_argument("--no-plan", action="store_true", help="Skip the owner's LLM packaging plan")
    parser.add_argument("--organization-mode", choices=["multi", "single", "solo"], default="multi")
    parser.add_argument("--repair-retries", type=int, default=3,
                        help="Extra targeted corrections of a rejected model answer (see AgentRuntime)")
    parser.add_argument("--database", type=Path, default=ROOT / "runs/catalog/shared_catalog.sqlite3")
    args = parser.parse_args()

    # Opt-in live switches read by AgentRuntime (see src/agent_runtime.py).
    os.environ["CAPSTONE_CONDITION_REVIEW"] = "1"
    os.environ["CAPSTONE_REPAIR_RETRIES"] = str(args.repair_retries)
    os.environ["CAPSTONE_ORGANIZATION_MODE"] = args.organization_mode

    from integration.case_runner import CaseRunner
    from integration.catalog import DEFAULT_SOURCE, SharedCatalog
    from integration.model_client import CachedModelClient
    from scripts.micro_org_experiment import RetryingClient
    from src.llm_client import OpenAICompatibleClient
    from src.progress import set_log_path

    catalog = SharedCatalog(args.database)
    if not catalog.metadata().get("project_count"):
        catalog.import_inputs(DEFAULT_SOURCE)
    args.output.mkdir(parents=True, exist_ok=True)
    set_log_path(args.output / "progress.log")
    client = CachedModelClient(RetryingClient(OpenAICompatibleClient.from_env()), args.output / "model_cache")
    runner = CaseRunner(args.output, args.case, "llm", args.profile, ticks=args.ticks, budget=args.budget,
                        duration=args.duration, database=args.database, plan=not args.no_plan, client=client)
    client.on_call = runner.on_call
    runner.publish(live_switches={"internal_condition_review": True, "organization_mode": args.organization_mode,
                                  "targeted_repair_retries": args.repair_retries})
    runner.execute()
    status = runner.status()
    print(json.dumps({key: status.get(key) for key in ("run_id", "status", "phase", "current_tick", "projects", "usage", "error")},
                     ensure_ascii=False, indent=2))
    raise SystemExit(0 if status["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
