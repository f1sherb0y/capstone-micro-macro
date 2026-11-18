"""Paired single-agent vs multi-agent runs of the micro tender stages (real LLM).

Run:  python -m scripts.micro_org_experiment --output runs/<experiment-id> --cases CASE-0014,...

Arms (AgentRuntime.organization_mode):
  single  the decision maker answers alone in one call, no department discussion
  solo    the decision maker alone runs the same discussion rounds (same-role control)
  multi   department members discuss, then the decision maker decides (system default)

Stage-isolated design: every arm receives IDENTICAL inputs at each stage, so a
difference in an output can only come from the organization mechanism.
  stage owner    input = project idea                      -> owner tender brief
  stage bidders  input = reference tender packages          -> participation decisions, bid documents
  stage award    input = reference packages + reference bids -> evaluation report, award
The reference upstream artifact is the multi arm's (the system default); only
artifacts cross a stage boundary, never another arm's discussion history.
Member rosters are generated once per case and shared by all arms.

Responses are cached per arm, so an interrupted run resumes without repaying.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import time

from src.agent_runtime import AgentRuntime
from src.async_policy import install_asyncio_policy
from src.case_sources import DEFAULT_CONFIG, load_case_config, load_case_inputs
from src.llm_client import OpenAICompatibleClient
from src.models import SimulationState, dump, load_simulation_state
from src.progress import set_log_path
from src.run_audit import LLMCallAuditLogger
from src.stages.award import make_award_decisions
from src.stages.bid_documents import generate_bid_documents
from src.stages.consortiums import form_consortiums
from src.stages.evaluation import evaluate_bids
from src.stages.opening import open_bids
from src.stages.owner_requirements import owner_refine_requirements
from src.stages.participation import run_bid_participation
from src.stages.reconsideration import reconsider_after_failed_consortiums
from src.stages.rosters import generate_member_agents

ARMS = ("single", "solo", "multi")
REFERENCE_ARM = "multi"
STAGES = ("owner", "bidders", "award")
ROLES = ("designer", "supplier", "contractor", "supervisor")


class RetryingClient:
    """Retry transient transport failures; a business answer is never rewritten."""

    def __init__(self, client, attempts=4):
        self.client, self.config, self.attempts = client, client.config, attempts

    def chat_with_metadata(self, messages, temperature=0.2):
        for attempt in range(1, self.attempts + 1):
            try:
                return self.client.chat_with_metadata(messages, temperature)
            except Exception:
                if attempt == self.attempts:
                    raise
                time.sleep(3 * attempt)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def select_companies(companies, per_role):
    """Owner plus the first N candidates of each role, in the case pool's own order."""
    owner = [c for c in companies if c.company_role == "owner"]
    chosen = [c for role in ROLES for c in [x for x in companies if x.company_role == role][:per_role]]
    return [*owner, *chosen]


def artifacts_only(state: SimulationState, *, keep_bids: bool) -> SimulationState:
    """Carry task artifacts across a stage boundary; drop discussion, logs and reviews."""
    fresh = SimulationState(project_idea=deepcopy(state.project_idea), companies=deepcopy(state.companies))
    fresh.company_agent_rosters = deepcopy(state.company_agent_rosters)
    fresh.owner_requirements = deepcopy(state.owner_requirements)
    fresh.tender_packages = deepcopy(state.tender_packages)
    if keep_bids:
        fresh.participation_decisions = deepcopy(state.participation_decisions)
        fresh.consortiums = deepcopy(state.consortiums)
        fresh.bid_documents = deepcopy(state.bid_documents)
    return fresh


class Arm:
    def __init__(self, directory: Path, case_id: str, arm: str, profile: str, transport):
        from integration.model_client import CachedModelClient

        self.directory, self.case_id, self.arm, self.profile = directory, case_id, arm, profile
        self.client = CachedModelClient(transport, directory / "model_cache")

    def runtime(self, stage: str) -> AgentRuntime:
        audit_dir = self.directory / f"audit_{stage}"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit = LLMCallAuditLogger(audit_dir, f"{self.case_id}/{self.arm}/{stage}", self.client)
        runtime = AgentRuntime(self.client, profile=self.profile, audit_logger=audit)
        runtime.organization_mode = self.arm
        runtime.internal_condition_review = True
        return runtime

    async def run_stage(self, stage: str, start: SimulationState) -> SimulationState:
        path = self.directory / f"stage_{stage}.json"
        if path.exists():
            return load_simulation_state(read_json(path)["state"])
        before = self.client.usage()
        started = time.time()
        runtime = self.runtime(stage)
        state = start
        if stage == "owner":
            state.owner_requirements = await owner_refine_requirements(state, runtime, self.profile)
            state.tender_packages = state.owner_requirements.tender_package_plan
        elif stage == "bidders":
            await run_bid_participation(state, runtime)
            await form_consortiums(state, runtime)
            await reconsider_after_failed_consortiums(state, runtime)
            await generate_bid_documents(state, runtime)
        else:
            await open_bids(state, runtime)
            await evaluate_bids(state, runtime)
            await make_award_decisions(state, runtime)
        after = self.client.usage()
        write_json(path, {
            "case_id": self.case_id, "arm": self.arm, "stage": stage, "profile": self.profile,
            "seconds": round(time.time() - started, 1),
            "usage": {key: after[key] - before[key] for key in ("requests", "cache_hits", "input_tokens", "output_tokens")},
            "model": after["model"], "recovery_events": list(runtime.recovery_events), "state": dump(state)})
        return state


async def run_case(case_id: str, output: Path, arms, profile: str, per_role: int, config: dict, transport) -> None:
    case_dir = output / case_id
    project, companies, _context = load_case_inputs(config, case_id)
    companies = select_companies(companies, per_role)
    arm_runs = {arm: Arm(case_dir / arm, case_id, arm, profile, transport) for arm in arms}

    roster_path = case_dir / "shared_rosters.json"
    base = SimulationState(project_idea=project, companies=companies)
    if roster_path.exists():
        base.company_agent_rosters = load_simulation_state({"company_agent_rosters": read_json(roster_path)}).company_agent_rosters
    else:
        from integration.model_client import CachedModelClient
        setup = AgentRuntime(CachedModelClient(transport, case_dir / "shared_model_cache"), profile=profile)
        base.company_agent_rosters = await generate_member_agents(companies, setup)
        if setup.recovery_events:
            raise RuntimeError(f"Roster generation degraded for {case_id}: {setup.recovery_events}")
        write_json(roster_path, {key: dump(value) for key, value in base.company_agent_rosters.items()})
    write_json(case_dir / "inputs.json", {"case_id": case_id, "project_idea": dump(project),
                                          "companies": dump(companies), "per_role": per_role, "profile": profile})

    owner = dict(zip(arms, await asyncio.gather(*[arm_runs[a].run_stage("owner", deepcopy(base)) for a in arms])))
    reference = artifacts_only(owner[REFERENCE_ARM], keep_bids=False)
    bidders = dict(zip(arms, await asyncio.gather(*[arm_runs[a].run_stage("bidders", deepcopy(reference)) for a in arms])))
    reference_bids = artifacts_only(bidders[REFERENCE_ARM], keep_bids=True)
    await asyncio.gather(*[arm_runs[a].run_stage("award", deepcopy(reference_bids)) for a in arms])


async def main_async(args) -> None:
    arms = [arm.strip() for arm in args.arms.split(",") if arm.strip()]
    if REFERENCE_ARM not in arms or any(arm not in ARMS for arm in arms):
        raise SystemExit(f"--arms must include {REFERENCE_ARM} and use only {ARMS}")
    cases = [case.strip() for case in args.cases.split(",") if case.strip()]
    config = load_case_config(args.config)
    transport = RetryingClient(OpenAICompatibleClient.from_env())
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = args.output / "experiment.json"
    settings = {"cases": cases, "arms": arms, "profile": args.profile, "per_role": args.per_role,
                "reference_arm": REFERENCE_ARM, "model": transport.config.model, "provider": transport.config.provider,
                "llm_concurrency": os.getenv("CODEDEMO_LLM_CONCURRENCY", "3"),
                "design": "stage-isolated paired arms; shared rosters; internal condition review enabled"}
    if manifest.exists() and {k: v for k, v in read_json(manifest).items() if k != "llm_concurrency"} != \
            {k: v for k, v in settings.items() if k != "llm_concurrency"}:
        raise SystemExit("Output directory holds a different experiment design; use a new directory")
    write_json(manifest, settings)
    set_log_path(args.output / "progress.log")
    gate = asyncio.Semaphore(args.parallel_cases)

    async def one(case_id):
        async with gate:
            started = time.time()
            try:
                await run_case(case_id, args.output, arms, args.profile, args.per_role, config, transport)
                result = {"case": case_id, "status": "done", "seconds": round(time.time() - started, 1)}
            except Exception as exc:  # one failed case must not discard the others
                result = {"case": case_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:600]}
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return result
    results = await asyncio.gather(*[one(case_id) for case_id in cases])
    set_log_path(None)
    write_json(args.output / "case_status.json", results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", required=True, help="Comma-separated case ids")
    parser.add_argument("--arms", default="single,solo,multi")
    parser.add_argument("--profile", choices=["full", "smoke"], default="full")
    parser.add_argument("--per-role", type=int, default=2, help="Candidate companies per bidder role")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--parallel-cases", type=int, default=1)
    args = parser.parse_args()
    install_asyncio_policy()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
