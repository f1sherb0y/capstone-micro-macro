from fastapi import APIRouter

router = APIRouter(prefix="/results", tags=["results"])


@router.get("/health")
def result_api_health():
    return {"status": "ok"}
