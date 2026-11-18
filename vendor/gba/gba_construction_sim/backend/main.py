from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from gba_construction_sim.backend.models.procurement import ProcurementUnavailableError

from gba_construction_sim.backend.api import (
    agent_api,
    analytics_api,
    cluster_api,
    policy_api,
    project_api,
    result_api,
    runtime_api,
    simulation_api,
    workflow_api,
    procurement_api,
)
from gba_construction_sim.backend.config import settings


app = FastAPI(title=settings.app_name)


@app.exception_handler(ProcurementUnavailableError)
async def procurement_unavailable(request, exc):
    return JSONResponse(status_code=503, content={"detail": {
        "error_code": "PROCUREMENT_ENGINE_UNAVAILABLE",
        "message": str(exc),
        "retryable": False,
    }})

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5175",
        "http://localhost:5175",
        "http://127.0.0.1:5180",
        "http://localhost:5180",
        "http://127.0.0.1:5181",
        "http://localhost:5181",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(simulation_api.router)
app.include_router(project_api.router)
app.include_router(agent_api.router)
app.include_router(cluster_api.router)
app.include_router(policy_api.router)
app.include_router(workflow_api.router)
app.include_router(procurement_api.router)
app.include_router(runtime_api.router)
app.include_router(analytics_api.router)
app.include_router(result_api.router)


@app.get("/health")
def health():
    return {"status": "ok"}
