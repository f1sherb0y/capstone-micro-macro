"""Capabilities and immutable per-simulation procurement receipts."""
from fastapi import APIRouter, HTTPException

from gba_construction_sim.backend.models.api_response import ok
from gba_construction_sim.backend.models.procurement import procurement_capabilities
from gba_construction_sim.backend.storage.repositories import simulation_repository

router = APIRouter(tags=["procurement"])


@router.get("/api/procurement-engines")
def list_procurement_engines():
    return ok(procurement_capabilities())


def _engine(simulation_id: str):
    try:
        return simulation_repository.get(simulation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Simulation not found") from exc


@router.get("/api/simulations/{simulation_id}/procurement")
def get_procurement(simulation_id: str):
    # Never call runtime_state here: requesting a future tick can advance it.
    return ok(_engine(simulation_id).procurement_state())


@router.api_route("/api/simulations/{simulation_id}/procurement", methods=["PUT", "PATCH"])
def reject_procurement_change(simulation_id: str):
    _engine(simulation_id)
    raise HTTPException(
        status_code=409,
        detail={
            "error_code": "PROCUREMENT_MODE_LOCKED",
            "message": "Procurement mode is locked from creation. Create a new simulation to change it.",
            "simulation_id": simulation_id,
            "retryable": False,
        },
    )
