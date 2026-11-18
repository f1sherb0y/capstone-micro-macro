"""One-case runner shared by CLI and web; status reads never advance simulation."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
import uuid

from integration.bootstrap import enable_gba_imports
from integration.catalog import SharedCatalog, DEFAULT_DATABASE
from integration.contracts import IntegrationError
from integration.run import build_engine
from integration.sessions import atomic_json


class CaseRunner:
    def __init__(self, directory, case_id="CASE-0005", mode="llm", profile="smoke", seed=42,
                 ticks=120, budget=150_000_000, duration=24, database=DEFAULT_DATABASE, plan=True,
                 procurement_mode="codedemo_micro", client=None, environment=None, policy=None, workflow=None, restore_initial=False, input_path=None):
        if mode not in {"llm", "offline"} or profile not in {"smoke", "full"} or procurement_mode not in {"codedemo_micro", "gba_native"}:
            raise ValueError("Unsupported model mode, profile or procurement engine")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.restore_initial = restore_initial
        saved_status = self.directory / "status.json"
        if saved_status.exists() and not restore_initial:
            raise ValueError("Run already exists; use a new directory")
        previous = json.loads(saved_status.read_text(encoding="utf-8")) if restore_initial and saved_status.exists() else None
        if restore_initial and (not previous or previous["current_tick"] != 0 or previous["status"] != "error"):
            raise ValueError("Initial-window recovery requires an existing technical failure at tick zero")
        self.run_id = self.directory.name
        self.catalog = SharedCatalog(database)
        self.settings = dict(case_id=case_id, mode=mode, profile=profile, seed=seed, ticks=ticks,
                             budget=budget, duration=duration, plan=plan, procurement_mode=procurement_mode)
        self.client = client
        self.input_path = Path(input_path) if input_path else None
        self.environment, self.policy, self.workflow = environment or {}, policy or {}, workflow or {}
        self.engine = None
        self.macro_binding = None
        self.lock = threading.RLock()
        self.stop_requested = threading.Event()
        self.worker = None
        self.state = {"run_id": self.run_id, "status": "created", "phase": "等待运行", "current_tick": 0,
                      "settings": self.settings, "created_at": datetime.now(timezone.utc).isoformat(), "error": None,
                      "projects": [], "sessions": [], "usage": {}}
        if previous:
            self.settings = previous["settings"]
            self.state = previous
            self.state["recovered_initial_window"] = True
        self.publish()

    def publish(self, **changes):
        with self.lock:
            self.state.update(changes)
            self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
            atomic_json(self.directory / "status.json", self.state)

    def status(self):
        with self.lock:
            value = deepcopy(self.state)
        # The original macro UI may own stepping. Reading its engine is still
        # side-effect free; never run a tick or a model from a status query.
        if self.engine and not (self.worker and self.worker.is_alive()):
            from gba_construction_sim.backend.services.simulation_service import simulation_runtime_service
            with simulation_runtime_service._lock_for(self.engine.simulation_id):
                value.update(current_tick=self.engine.current_tick, projects=self.project_status())
                if all(p["stage"] == "closed" for p in value["projects"]):
                    value.update(status="completed", phase="项目已关闭")
        return value

    def project_status(self):
        return [{"id": p.project_id, "name": p.name, "stage": p.current_stage.value,
                 "progress": p.performance.actual_progress, "contracts": len(p.contracts),
                 "cost": p.performance.actual_cost, "delay_days": p.performance.delay_days}
                for p in self.engine.projects.values()]

    def on_call(self, marker):
        self.publish(last_model_call=marker, usage=self.client.usage() if hasattr(self.client, "usage") else {})

    def start(self):
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError("This run is already executing")
            if self.state["status"] == "completed":
                raise ValueError("This run has already completed")
            self.stop_requested.clear()
            self.worker = threading.Thread(target=self.execute, daemon=True, name=f"case-{self.run_id}")
            self.worker.start()

    def pause(self):
        self.stop_requested.set()
        self.publish(pause_requested=True)

    def _prepare(self):
        s = self.settings
        if self.input_path:
            from integration.shared_data import SharedDataset
            dataset = SharedDataset.load(self.input_path)
            if set(dataset.projects) != {s["case_id"]}:
                raise ValueError("Explicit shared input must contain exactly the selected case")
            project = dataset.projects[s["case_id"]]
            s.update(budget=project["budget"], duration=project["duration_months"], plan=False,
                     approved_input=str(self.input_path), input_provenance=dataset.payload["assumptions"]["source_note"])
        else:
            dataset = self.catalog.scenario(s["case_id"], s["budget"], s["duration"], s["seed"])
        if self.restore_initial:
            from integration.shared_data import SharedDataset
            dataset = SharedDataset.load(self.directory / "shared_input.json")
        if self.environment or self.policy:
            from integration.shared_data import SharedDataset
            payload = deepcopy(dataset.payload)
            payload["environment"].update(self.environment)
            payload["policy"].update(self.policy)
            dataset = SharedDataset(payload)
        if self.client is None:
            if s["mode"] == "offline" or s["procurement_mode"] == "gba_native":
                from integration.fixture_client import IntegrationFixtureClient
                self.client = IntegrationFixtureClient()
            else:
                from src.llm_client import OpenAICompatibleClient
                from integration.model_client import CachedModelClient
                self.client = CachedModelClient(OpenAICompatibleClient.from_env(), self.directory / "model_cache", self.on_call)
                if self.restore_initial:
                    usage = self.state.get("usage") or {}
                    self.client.calls, self.client.cached_calls = usage.get("requests", 0), usage.get("cache_hits", 0)
                    self.client.input_tokens, self.client.output_tokens = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        seed_rosters = None
        if s["plan"] and s["mode"] == "llm" and s["procurement_mode"] == "codedemo_micro" and not self.restore_initial:
            from integration.planning import plan_dataset
            self.publish(phase="业主成员讨论采购拆包方案", status="planning")
            dataset, seed_rosters = asyncio.run(plan_dataset(dataset, self.client, self.directory / "planning", s["profile"]))
        atomic_json(self.directory / "shared_input.json", dataset.payload)
        self.catalog.save_scenario(dataset)
        enable_gba_imports()
        from gba_construction_sim.backend.decision.rule_based_provider import RuleBasedDecisionProvider
        from integration.macro_binding import MacroBinding
        self.macro_binding = MacroBinding(RuleBasedDecisionProvider())
        if s["procurement_mode"] == "gba_native":
            from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine
            request = dataset.macro_request(s["ticks"], s["seed"])
            request.workflow_configuration = self.workflow
            self.engine = SimulationEngine.from_request(request, decision_provider=self.macro_binding)
        else:
            self.engine = build_engine(dataset, self.client, self.directory, s["ticks"], s["seed"], s["profile"],
                                       seed_rosters=seed_rosters, workflow=self.workflow,
                                       restore_initial=self.restore_initial, binding=self.macro_binding)
        from gba_construction_sim.backend.storage.repositories import simulation_repository
        simulation_repository.add(self.engine)
        self.publish(simulation_id=self.engine.simulation_id, data_version=dataset.version,
                     source_counts={"projects": len(dataset.projects), "companies": len(dataset.companies)} if self.input_path else
                         {"projects": self.catalog.metadata().get("project_count"), "companies": self.catalog.metadata().get("company_count")})

    def save_result(self):
        result = self.result_data()
        if result is not None:
            atomic_json(self.directory / "result.json", result)
        return result

    def result_data(self):
        if not self.engine:
            return
        executor = self.engine.procurement_executor
        result = {"offline_fixture": self.settings["mode"] == "offline", "non_procurement_provider": "GBA RuleBasedDecisionProvider",
                  "simulation": self.engine.response().model_dump(), "procurement": executor.status() if executor else {"mode": "gba_native"},
                  "usage": self.client.usage() if hasattr(self.client, "usage") else {}, "settings": self.settings,
                  "macro_binding": self.macro_binding.evidence() if self.macro_binding else {}}
        return result

    def execute(self):
        self.publish(status="running", phase="读取共享数据", error=None, pause_requested=False)
        try:
            if self.engine is None:
                self._prepare()
            retries = 0
            while self.engine.current_tick < self.engine.ticks:
                if self.stop_requested.is_set():
                    self.publish(status="paused", phase="已在宏观时间步边界暂停")
                    break
                self.publish(status="running", phase="微观决策与宏观状态推进")
                try:
                    from gba_construction_sim.backend.services.simulation_service import simulation_runtime_service
                    with simulation_runtime_service._lock_for(self.engine.simulation_id):
                        self.engine.step(False)
                    retries = 0
                except IntegrationError as exc:
                    retries += 1
                    if retries > 2:
                        raise
                    self.publish(status="retrying", phase="技术失败重试，宏观时间未推进", error=str(exc)[:1600])
                    time.sleep(2)
                    continue
                projects = [{"id": p.project_id, "name": p.name, "stage": p.current_stage.value,
                             "progress": p.performance.actual_progress, "contracts": len(p.contracts),
                             "cost": p.performance.actual_cost, "delay_days": p.performance.delay_days}
                            for p in self.engine.projects.values()]
                executor = self.engine.procurement_executor
                self.publish(current_tick=self.engine.current_tick, projects=projects, error=None,
                             sessions=executor.status()["sessions"] if executor else [],
                             usage=self.client.usage() if hasattr(self.client, "usage") else {})
                self.save_result()
                if all(p["stage"] in {"closed", "suspended", "failed"} for p in projects):
                    complete = all(p["stage"] == "closed" for p in projects)
                    if complete:
                        self.engine.status = self.engine.current_phase = self.engine.current_operation = "completed"
                    self.publish(status="completed" if complete else "business_stopped", phase="项目已关闭" if complete else "项目因业务决定或宏观条件停止")
                    break
            else:
                self.publish(status="completed" if all(p.current_stage.value == "closed" for p in self.engine.projects.values()) else "tick_limit", phase="到达设置的时间步上限")
        except Exception as exc:
            self.publish(status="error", phase="运行暂停，错误已记录；可以修复后重试", error=f"{type(exc).__name__}: {exc}"[:2000])
        finally:
            self.save_result()
            self.publish(usage=self.client.usage() if hasattr(self.client, "usage") else {})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="CASE-0005")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["llm", "offline"], default="llm")
    parser.add_argument("--profile", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--no-plan", action="store_true")
    parser.add_argument("--resume-initial", action="store_true", help="Recover a saved technical failure before the first macro tick")
    args = parser.parse_args()
    runner = CaseRunner(args.output, args.case, args.mode, args.profile, database=args.database, plan=not args.no_plan, restore_initial=args.resume_initial)
    runner.execute()
    print(json.dumps(runner.status(), ensure_ascii=False))
    raise SystemExit(0 if runner.state["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
