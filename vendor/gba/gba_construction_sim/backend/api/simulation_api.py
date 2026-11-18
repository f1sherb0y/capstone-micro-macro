from fastapi import APIRouter, HTTPException

from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine
from gba_construction_sim.backend.storage.repositories import simulation_repository


router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post("/create")
def create_simulation(request: SimulationCreateRequest):
    engine = SimulationEngine.from_request(request)
    simulation_repository.add(engine)
    return engine.summary().dict()


@router.get("")
def list_simulations():
    return [engine.summary().dict() for engine in simulation_repository.all()]


@router.post("/{simulation_id}/run")
def run_simulation(simulation_id: str):
    engine = _get_engine(simulation_id)
    return engine.run().dict()


@router.post("/{simulation_id}/step")
def step_simulation(simulation_id: str):
    engine = _get_engine(simulation_id)
    return engine.step()


@router.get("/{simulation_id}/projects/{project_id}/timeline")
def get_project_timeline(simulation_id: str, project_id: str):
    engine = _get_engine(simulation_id)
    _ensure_project(engine, project_id)
    return engine.project_timeline(project_id)


@router.get("/{simulation_id}/projects/{project_id}/performance")
def get_project_performance(simulation_id: str, project_id: str):
    engine = _get_engine(simulation_id)
    _ensure_project(engine, project_id)
    return engine.project_performance(project_id)


@router.get("/{simulation_id}/agents/{agent_id}/engagements")
def get_agent_engagements(simulation_id: str, agent_id: str):
    engine = _get_engine(simulation_id)
    if agent_id not in engine.agents:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return engine.agent_engagements(agent_id)


@router.get("/{simulation_id}/network")
def get_network(simulation_id: str):
    engine = _get_engine(simulation_id)
    return engine.network.to_dict()


@router.get("/{simulation_id}/metrics")
def get_metrics(simulation_id: str):
    engine = _get_engine(simulation_id)
    return engine.metrics.dict()


def _get_engine(simulation_id: str) -> SimulationEngine:
    try:
        return simulation_repository.get(simulation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _ensure_project(engine: SimulationEngine, project_id: str) -> None:
    if project_id not in engine.projects:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
