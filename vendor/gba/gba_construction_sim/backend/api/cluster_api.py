from typing import Dict, Optional

from fastapi import APIRouter, Body, Query

from gba_construction_sim.backend.models.api_response import ok, page as page_response
from gba_construction_sim.backend.services.cluster_service import cluster_service

router = APIRouter(tags=["clusters"])


@router.get("/api/clusters")
def list_clusters(
    city: Optional[str] = Query(default=None),
    type: Optional[str] = Query(default=None),
    structure: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1),
):
    items = cluster_service.list_clusters(city, type, structure, keyword)
    return page_response(items, page, page_size)


@router.get("/api/clusters/{cluster_id}")
def get_cluster(cluster_id: str):
    return ok(cluster_service.get_cluster(cluster_id))


@router.post("/api/clusters")
def create_cluster(payload: Dict = Body(default_factory=dict)):
    return ok({**payload, "cluster_id": payload.get("cluster_id", "CL_CUSTOM")}, "created")


@router.put("/api/clusters/{cluster_id}")
def update_cluster(cluster_id: str, payload: Dict = Body(default_factory=dict)):
    return ok({**cluster_service.get_cluster(cluster_id), **payload}, "updated")


@router.post("/api/clusters/{cluster_id}/duplicate")
def duplicate_cluster(cluster_id: str):
    return ok(cluster_service.duplicate_cluster(cluster_id), "duplicated")


@router.post("/api/clusters/{cluster_id}/use-in-simulation")
def use_cluster_in_simulation(cluster_id: str):
    return ok(cluster_service.use_in_simulation(cluster_id), "ready")
