from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from gba_construction_sim.backend.models.api_response import ok
from gba_construction_sim.backend.services.analytics_service import analytics_service

router = APIRouter(tags=["analytics"])


@router.get("/api/analytics/dashboard")
def analytics_dashboard(
    simulation_id: Optional[str] = Query(default=None),
    scenario: str = Query(default="green_growth_2030"),
):
    return ok(_call(lambda: analytics_service.dashboard(simulation_id, scenario)))


@router.get("/api/analytics/spatial-distribution")
def spatial_distribution(
    simulation_id: Optional[str] = Query(default=None),
    project_type: str = Query(default="all"),
    policy_scenario: str = Query(default="green_growth_2030"),
):
    return ok(_call(lambda: analytics_service.spatial_distribution(simulation_id, project_type, policy_scenario)))


@router.get("/api/analytics/collaboration-network")
def collaboration_network(
    simulation_id: Optional[str] = Query(default=None),
    region: str = Query(default="all"),
):
    return ok(_call(lambda: analytics_service.collaboration_network(simulation_id, region)))


@router.get("/api/analytics/trends")
def trends(
    simulation_id: Optional[str] = Query(default=None),
    metric: str = Query(default="total_project_investment"),
    time_range: str = Query(default="24_months"),
):
    return ok(_call(lambda: analytics_service.trends(simulation_id, metric, time_range)))


@router.get("/api/analytics/policy-evaluation")
def policy_evaluation(
    simulation_id: Optional[str] = Query(default=None),
    policy_id: str = Query(default="POL001"),
):
    return ok(_call(lambda: analytics_service.policy_evaluation(simulation_id, policy_id)))


@router.get("/api/analytics/export-report")
def export_report(simulation_id: Optional[str] = Query(default=None)):
    return ok({"simulation_id": simulation_id, "export_ready": True, "format": "json"}, "export-ready")


def _call(factory):
    try:
        return factory()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
