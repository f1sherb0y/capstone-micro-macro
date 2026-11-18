from typing import Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from gba_construction_sim.backend.decision.camel_provider import CamelDecisionError
from gba_construction_sim.backend.models.api_response import ok
from gba_construction_sim.backend.services.simulation_service import simulation_runtime_service

router = APIRouter(tags=["simulation-runtime"])


@router.get("/api/simulations/{simulation_id}/runtime-state")
def runtime_state(simulation_id: str, tick: Optional[int] = Query(default=None)):
    try:
        return ok(simulation_runtime_service.runtime_state(simulation_id, tick))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CamelDecisionError as exc:
        raise _camel_blocked(exc, simulation_id, tick) from exc
    except RuntimeError as exc:
        if "CAMEL" in str(exc):
            raise _camel_blocked(exc, simulation_id, tick) from exc
        raise


@router.get("/api/simulations/{simulation_id}/map")
def simulation_map(simulation_id: str, tick: Optional[int] = Query(default=None)):
    return ok(_call(lambda: simulation_runtime_service.map_data(simulation_id, tick)))


@router.get("/api/simulations/{simulation_id}/projects")
def simulation_projects(simulation_id: str, tick: Optional[int] = Query(default=None)):
    return ok(_call(lambda: simulation_runtime_service.projects(simulation_id, tick)))


@router.get("/api/simulations/{simulation_id}/timeline")
def simulation_timeline(simulation_id: str):
    return ok(_call(lambda: simulation_runtime_service.timeline(simulation_id)))


@router.get("/api/simulations/{simulation_id}/agents/{agent_id}/history")
def simulation_agent_history(simulation_id: str, agent_id: str, tick: Optional[int] = Query(default=None)):
    return ok(_call(lambda: simulation_runtime_service.agent_history(simulation_id, agent_id, tick)))


@router.get("/api/simulations/{simulation_id}/insights")
def simulation_insights(simulation_id: str, tick: Optional[int] = Query(default=None)):
    return ok(_call(lambda: simulation_runtime_service.insights(simulation_id, tick)))


@router.post("/api/simulations/{simulation_id}/play")
def play_simulation(simulation_id: str):
    return ok(_call(lambda: simulation_runtime_service.play(simulation_id)))


@router.post("/api/simulations/{simulation_id}/pause")
def pause_simulation(simulation_id: str):
    return ok(_call(lambda: simulation_runtime_service.pause(simulation_id)))


@router.post("/api/simulations/{simulation_id}/step")
def step_simulation_runtime(simulation_id: str):
    return ok(_call(lambda: simulation_runtime_service.step(simulation_id)))


@router.post("/api/simulations/{simulation_id}/seek")
def seek_simulation(simulation_id: str, payload: Dict = Body(default_factory=dict)):
    return ok(_call(lambda: simulation_runtime_service.seek(simulation_id, int(payload.get("target_tick", 0)))))


def _call(factory):
    try:
        return factory()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CamelDecisionError as exc:
        raise _camel_blocked(exc) from exc
    except RuntimeError as exc:
        if "CAMEL" in str(exc):
            raise _camel_blocked(exc) from exc
        raise


def _camel_blocked(
    exc: Exception,
    simulation_id: Optional[str] = None,
    requested_tick: Optional[int] = None,
) -> HTTPException:
    generation_state = None
    if simulation_id:
        try:
            generation_state = simulation_runtime_service.generation_status(
                simulation_id,
                requested_tick=requested_tick,
                error=str(exc),
            )
        except Exception:
            generation_state = None
    return HTTPException(
        status_code=503,
        detail={
            "status": "blocked",
            "code": "camel_decision_blocked",
            "message": str(exc),
            "generation_state": generation_state,
        },
    )
