from typing import Dict

from fastapi import APIRouter, Body
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from gba_construction_sim.backend.models.api_response import ok
from gba_construction_sim.backend.services.workflow_service import workflow_service

router = APIRouter(tags=["workflows"])


@router.get("/api/workflows")
def list_workflows():
    return ok(workflow_service.list_workflows())


@router.get("/api/workflows/{workflow_id}")
def get_workflow(workflow_id: str):
    return ok(workflow_service.get_workflow(workflow_id))


@router.post("/api/workflows")
def create_workflow(payload: Dict = Body(default_factory=dict)):
    return ok(workflow_service.create_workflow(payload), "created")


@router.put("/api/workflows/{workflow_id}")
def update_workflow(workflow_id: str, payload: Dict = Body(default_factory=dict)):
    return ok(workflow_service.update_workflow(workflow_id, payload), "updated")


@router.post("/api/workflows/{workflow_id}/save-template")
def save_template(workflow_id: str):
    return ok(workflow_service.save_template(workflow_id), "saved")


@router.post("/api/workflows/load-template")
def load_template():
    return ok(workflow_service.load_template())


@router.post("/api/workflows/{workflow_id}/validate")
def validate_workflow(workflow_id: str):
    return ok(workflow_service.validate_workflow(workflow_id))


@router.post("/api/workflows/{workflow_id}/run")
def run_workflow(workflow_id: str, payload: Dict = Body(default_factory=dict)):
    try:
        return ok(workflow_service.run_workflow(workflow_id, payload))
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(), body=payload) from exc
