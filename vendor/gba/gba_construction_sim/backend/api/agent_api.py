from typing import Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from gba_construction_sim.backend.models.api_response import ok, page as page_response
from gba_construction_sim.backend.models.frontend_dto import AgentChatRequest
from gba_construction_sim.backend.services.agent_cognitive_service import agent_cognitive_service
from gba_construction_sim.backend.services.agent_service import agent_service

router = APIRouter(tags=["agents"])


@router.get("/agents/health")
def agent_api_health():
    return {"status": "ok"}


@router.get("/api/agents")
def list_agents(
    type: Optional[str] = Query(default=None),
    region: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1),
):
    items = agent_service.list_agents(type, region, status, keyword)
    return page_response(items, page, page_size)


@router.get("/api/agents/{agent_id}")
def get_agent(agent_id: str):
    try:
        return ok(agent_service.get_agent(agent_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/agents")
def create_agent(payload: Dict = Body(default_factory=dict)):
    return ok(agent_service.create_agent(payload), "created")


@router.put("/api/agents/{agent_id}")
def update_agent(agent_id: str, payload: Dict = Body(default_factory=dict)):
    return ok(agent_service.update_agent(agent_id, payload), "updated")


@router.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str):
    return ok(agent_service.delete_agent(agent_id), "deleted")


@router.get("/api/agents/{agent_id}/export")
def export_agent(agent_id: str):
    return ok(agent_service.get_agent(agent_id), "export-ready")


@router.get("/api/agents/{agent_id}/memory")
def get_agent_memory(
    agent_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    memory_type: Optional[str] = Query(default=None),
):
    try:
        return ok(agent_cognitive_service.get_agent_memory(agent_id, limit=limit, memory_type=memory_type))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/agents/{agent_id}/beliefs")
def get_agent_beliefs(agent_id: str):
    try:
        return ok(agent_cognitive_service.get_agent_beliefs(agent_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/agents/{agent_id}/strategy")
def get_agent_strategy(agent_id: str):
    strategy = agent_cognitive_service.get_agent_strategy(agent_id)
    if not strategy:
        raise HTTPException(status_code=404, detail=f"Agent strategy not found: {agent_id}")
    return ok(strategy)


@router.get("/api/agents/{agent_id}/decision-trace")
def get_agent_decision_trace(agent_id: str, limit: int = Query(default=50, ge=1, le=200)):
    try:
        return ok(agent_cognitive_service.get_agent_decision_trace(agent_id, limit=limit))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/agents/{agent_id}/cognitive-state")
def get_agent_cognitive_state(agent_id: str):
    try:
        return ok(agent_cognitive_service.get_agent_cognitive_state(agent_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/agents/{agent_id}/chat")
def chat_with_agent(agent_id: str, request: AgentChatRequest):
    return ok(agent_service.chat(agent_id, request.message, request.context))
