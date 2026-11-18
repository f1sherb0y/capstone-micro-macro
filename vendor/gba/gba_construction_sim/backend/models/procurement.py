"""Creation-time procurement selection; a micro executor is not implemented yet."""
from typing import Literal, Optional

from pydantic import BaseModel, root_validator


class ProcurementExecution(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["gba_native", "codedemo_micro"] = "gba_native"
    scope: Literal["full_procurement"] = "full_procurement"
    adapter_profile_id: Optional[Literal["codedemo-local"]] = None
    failure_policy: Literal["pause"] = "pause"

    class Config:
        frozen = True
        extra = "forbid"

    @root_validator(skip_on_failure=True)
    def check_adapter(cls, values):
        mode = values["mode"]
        profile = values.get("adapter_profile_id")
        if mode == "codedemo_micro" and profile != "codedemo-local":
            raise ValueError("codedemo_micro requires adapter_profile_id=codedemo-local")
        if mode == "gba_native" and profile is not None:
            raise ValueError("gba_native must not specify a micro adapter profile")
        return values


class ProcurementUnavailableError(RuntimeError):
    """A valid requested executor is not implemented or ready."""


def require_available(execution: ProcurementExecution, executor=None) -> None:
    # Only enable micro when the complete lifecycle and commit path are wired.
    if execution.mode != "gba_native":
        if executor is not None and executor.supports(execution):
            return
        raise ProcurementUnavailableError(
            "Full codedemo micro procurement is not integrated yet. "
            "This request did not create a simulation. GBA native remains available."
        )


def procurement_capabilities() -> list[dict]:
    return [
        {
            "mode": "gba_native", "label": "GBA native", "available": True,
            "scope": "full_procurement", "adapter_profile_id": None,
            "reason": "Uses the existing GBA procurement lifecycle.",
        },
        {
            "mode": "codedemo_micro", "label": "codedemo micro", "available": False,
            "scope": "full_procurement", "adapter_profile_id": "codedemo-local",
            "reason": (
                "Full micro procurement is not integrated yet: packages, participation, "
                "consortia, bids and awards must connect to GBA contract commit and construction."
            ),
        },
    ]
