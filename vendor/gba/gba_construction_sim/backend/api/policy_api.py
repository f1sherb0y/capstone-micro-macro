from typing import Dict, Optional

from fastapi import APIRouter, Body, Query

from gba_construction_sim.backend.models.api_response import ok, page as page_response
from gba_construction_sim.backend.services.policy_service import policy_service

router = APIRouter(tags=["policy"])


@router.get("/policy/health")
def policy_api_health():
    return {"status": "ok"}


@router.get("/api/policies")
def list_policies(
    type: Optional[str] = Query(default=None),
    region: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1),
):
    items = policy_service.list_policies(type, region, status, keyword)
    return page_response(items, page, page_size)


@router.get("/api/policies/{policy_id}")
def get_policy(policy_id: str):
    return ok(policy_service.get_policy(policy_id))


@router.post("/api/policies")
def create_policy(payload: Dict = Body(default_factory=dict)):
    return ok(policy_service.create_policy(payload), "created")


@router.put("/api/policies/{policy_id}")
def update_policy(policy_id: str, payload: Dict = Body(default_factory=dict)):
    return ok(policy_service.update_policy(policy_id, payload), "updated")


@router.post("/api/policies/import")
def import_policy(payload: Dict = Body(default_factory=dict)):
    payload.setdefault("name", "Imported Policy Scenario")
    return ok(policy_service.create_policy(payload), "imported")


@router.get("/api/policies/{policy_id}/preview")
def preview_policy(policy_id: str):
    return ok(policy_service.preview_policy(policy_id))


@router.post("/api/policies/{policy_id}/map-to-parameters")
def map_policy_to_parameters(policy_id: str):
    return ok(policy_service.map_to_parameters(policy_id))
