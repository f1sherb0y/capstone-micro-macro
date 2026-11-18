from fastapi import APIRouter

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/health")
def project_api_health():
    return {"status": "ok"}
