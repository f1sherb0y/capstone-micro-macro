"""Local integration workbench and optional GBA web/API composition."""
from __future__ import annotations

from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
import uuid
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from integration.bootstrap import enable_gba_imports
from integration.catalog import SharedCatalog, DEFAULT_DATABASE, ROOT
from integration.case_runner import CaseRunner


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    case_id: str = "CASE-0005"
    mode: Literal["llm", "offline"] = "llm"
    procurement_mode: Literal["codedemo_micro", "gba_native"] = "codedemo_micro"
    profile: Literal["smoke", "full"] = "smoke"
    budget: float = Field(default=150_000_000, gt=0, le=1e13)
    duration: int = Field(default=24, ge=1, le=240)
    ticks: int = Field(default=120, ge=1, le=600)
    seed: int = 42
    plan: bool = True
    material_price_index: float = Field(default=1, ge=.5, le=3)
    labor_price_index: float = Field(default=1, ge=.5, le=3)
    allow_model_data_transfer: bool = False


def create_app(database=DEFAULT_DATABASE, runs_directory=ROOT / "output/integration/runs", client_factory=None):
    macro = enable_gba_imports()
    from src.llm_client import load_project_env
    load_project_env()
    catalog = SharedCatalog(database)
    if not catalog.metadata():
        catalog.import_inputs()
    directory = Path(runs_directory)
    directory.mkdir(parents=True, exist_ok=True)
    active = {}
    from gba_construction_sim.backend.main import app as gba_app
    from gba_construction_sim.backend.services.workflow_service import workflow_service

    def legacy_workflow_run(workflow_id, payload, workflow, ticks):
        cfg = workflow.get("configuration") or {}
        case_id = payload.get("integration_case_id", cfg.get("integration_case_id", "CASE-0005"))
        mode = payload.get("integration_model_mode", cfg.get("integration_model_mode", "llm"))
        if mode not in {"llm", "offline"}:
            raise HTTPException(422, "Unsupported integration model mode")
        # The integration-aware selector supplies explicit consent; API callers
        # must do the same. No implicit export through an old native UI payload.
        consent = payload.get("allow_model_data_transfer", cfg.get("allow_model_data_transfer", False))
        if mode == "llm" and consent is not True:
            raise HTTPException(422, "Open /integration and authorize the model data transfer before a live micro run")
        key = "web-" + uuid.uuid4().hex[:12]
        runner = CaseRunner(directory / key, case_id=case_id, mode=mode, ticks=ticks,
            seed=int(payload.get("random_seed", 42)), database=database, plan=False,
            client=client_factory() if client_factory else None, workflow=workflow,
            environment=payload.get("macro_environment") or cfg.get("macro_environment"), policy=payload.get("policy") or cfg.get("policy"))
        runner._prepare()  # No model calls: the legacy editor uses the approved input plan.
        active[key] = runner
        engine = runner.engine
        return {"simulation_id": engine.simulation_id, "workflow_id": workflow_id, "status": "created", "run_id": key,
            "procurement": engine.procurement_state(), "agent_count": len(engine.agents) - 1, "enterprise_agent_count": len(engine.agents) - 1,
            "support_regulator_count": 1, "total_agent_count": len(engine.agents), "project_count": len(engine.projects), "prior_edge_count": 0,
            "current_tick": 0, "total_ticks": ticks, "live_mode": True, "configuration_summary": {"agent_source": "shared_catalog", "case_id": case_id},
            "workflow_runtime": engine.workflow_runtime.state(), "message": "Shared-input micro procurement executor attached."}

    @asynccontextmanager
    async def lifespan(app):
        previous = workflow_service.procurement_run_handler
        workflow_service.procurement_run_handler = legacy_workflow_run
        yield
        workflow_service.procurement_run_handler = previous

    app = FastAPI(title="宏微观联动工作台", lifespan=lifespan)
    app.state.runners, app.state.catalog = active, catalog

    def safe_dir(run_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,90}", run_id):
            raise HTTPException(404, "Unknown run")
        path = directory / run_id
        if not path.is_dir():
            raise HTTPException(404, "Unknown run")
        return path

    @app.get("/")
    @app.get("/integration")
    def index():
        return FileResponse(ROOT / "integration/static/index.html")

    @app.get("/integration/api/catalog")
    def get_catalog():
        provider = os.getenv("LLM_PROVIDER", "deepseek")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat") if provider == "deepseek" else os.getenv("OPENAI_MODEL", "")
        configured = bool(os.getenv("DEEPSEEK_API_KEY" if provider == "deepseek" else "OPENAI_API_KEY"))
        return {"projects": catalog.list_projects(), "metadata": catalog.metadata(), "model": {"provider": provider, "model": model, "configured": configured}}

    @app.get("/api/procurement-engines")
    def capabilities():
        from gba_construction_sim.backend.models.procurement import procurement_capabilities
        items = procurement_capabilities()
        for item in items:
            if item["mode"] == "codedemo_micro":
                item.update(available=True, reason="Shared catalog micro executor is attached. Select a case and model mode in the integration workbench.")
        return {"success": True, "data": items, "message": "ok", "error": None}

    @app.post("/integration/api/runs", status_code=202)
    def start_run(request: RunRequest):
        if request.mode == "llm" and request.procurement_mode == "codedemo_micro" and not request.allow_model_data_transfer:
            raise HTTPException(422, "Live model runs require explicit consent to send the selected project/enterprise inputs")
        # Validate the shared input synchronously before creating a background job.
        try:
            catalog.scenario(request.case_id, request.budget, request.duration, request.seed)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        key = "web-" + uuid.uuid4().hex[:12]
        options = request.model_dump(exclude={"allow_model_data_transfer", "material_price_index", "labor_price_index"})
        runner = CaseRunner(directory / key, **options, database=database,
            client=client_factory() if client_factory else None,
            environment={"material_price_index": request.material_price_index, "labor_price_index": request.labor_price_index})
        active[key] = runner
        runner.start()
        return runner.status()

    @app.get("/integration/api/runs")
    def list_runs():
        rows = []
        for path in directory.glob("*/status.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if value["run_id"] not in active and value["status"] in {"created", "planning", "running", "retrying"}:
                    value["status"] = "external_or_interrupted"
                rows.append(value)
            except (OSError, ValueError, KeyError):
                continue
        return sorted(rows, key=lambda r: r.get("created_at", ""), reverse=True)

    @app.get("/integration/api/runs/{run_id}")
    def status(run_id: str):
        if run_id in active:
            return {**active[run_id].status(), "live_in_server": True}
        path = safe_dir(run_id) / "status.json"
        if not path.exists():
            raise HTTPException(404, "No saved status")
        return {**json.loads(path.read_text(encoding="utf-8")), "live_in_server": False}

    @app.post("/integration/api/runs/{run_id}/resume")
    def resume(run_id: str):
        if run_id not in active:
            raise HTTPException(409, "This process does not own the engine. Saved results remain readable; create a new run to restart.")
        try:
            active[run_id].start()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return active[run_id].status()

    @app.post("/integration/api/runs/{run_id}/pause")
    def pause(run_id: str):
        if run_id not in active:
            raise HTTPException(409, "Run is not active in this server")
        active[run_id].pause()
        return active[run_id].status()

    @app.get("/integration/api/runs/{run_id}/result")
    def result(run_id: str):
        if run_id in active and active[run_id].engine and not (active[run_id].worker and active[run_id].worker.is_alive()):
            from gba_construction_sim.backend.services.simulation_service import simulation_runtime_service
            runner = active[run_id]
            with simulation_runtime_service._lock_for(runner.engine.simulation_id):
                return runner.result_data()
        path = safe_dir(run_id) / "result.json"
        if not path.exists():
            return {"simulation": {"project_results": []}}
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/integration/api/runs/{run_id}/input")
    def shared_input(run_id: str):
        path = safe_dir(run_id) / "shared_input.json"
        if not path.exists():
            raise HTTPException(409, "Plan is still being prepared")
        return FileResponse(path, media_type="application/json", filename=f"{run_id}-input.json")

    @app.get("/integration/api/runs/{run_id}/decisions")
    def decisions(run_id: str):
        path = safe_dir(run_id)
        rows = []
        for checkpoint in (path / "sessions").glob("*.json"):
            data = json.loads(checkpoint.read_text(encoding="utf-8"))
            state = data["state"]
            rows.append({"session_id": data["session_id"], "status": data["status"], "spec": data["spec"],
                         "messages": state.get("agent_discussion_history", []), "participation": state.get("participation_decisions", []),
                         "consortiums": state.get("consortiums", []), "bids": state.get("bid_documents", []),
                         "award": state.get("simulated_award_result"), "proposal": data["proposal"]})
        return rows

    dist = macro / "frontend/dist"
    if dist.is_dir():
        app.mount("/macro", StaticFiles(directory=dist, html=True), name="macro-ui")
    app.mount("/", gba_app)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("INTEGRATION_PORT", "8765")))
