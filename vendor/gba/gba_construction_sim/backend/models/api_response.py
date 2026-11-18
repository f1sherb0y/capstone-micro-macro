from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ApiError(BaseModel):
    code: str
    details: List[str] = Field(default_factory=list)


class ApiResponse(BaseModel):
    success: bool = True
    data: Any = None
    message: str = "ok"
    error: Optional[ApiError] = None


class PageData(BaseModel):
    items: List[Any]
    page: int = 1
    page_size: int = 10
    total: int = 0


def ok(data: Any = None, message: str = "ok") -> Dict:
    return ApiResponse(success=True, data=data, message=message, error=None).dict()


def page(items: List[Any], page_number: int = 1, page_size: int = 10) -> Dict:
    start = (page_number - 1) * page_size
    end = start + page_size
    return ok(PageData(items=items[start:end], page=page_number, page_size=page_size, total=len(items)).dict())


def fail(message: str, code: str = "ERROR", details: Optional[List[str]] = None) -> Dict:
    return ApiResponse(
        success=False,
        data=None,
        message=message,
        error=ApiError(code=code, details=details or []),
    ).dict()
