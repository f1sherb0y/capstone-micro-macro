"""QS-specific projections used by the local service-intake decision."""
from typing import Literal

from pydantic import model_validator

from src.actions.contracts.common import ScopeRef, TextId, TimePoint, TimeWindow, ref_type
from src.actions.contracts.service_objects import SourcedServiceProjection, service_intake_schemas


class QSConflictCheckView(SourcedServiceProjection):
    ref: ref_type("ConflictCheck")
    organization_id: TextId
    request_ref: ref_type("ServiceRequest")
    scope: ScopeRef
    status: Literal["clear", "conflict", "unknown", "failed"]
    conflict_codes: list[TextId]
    checked_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode="after")
    def consistent_status(self):
        if self.checked_at.clock_ref != self.effective_window.start.clock_ref:
            raise ValueError("Conflict check time differs from its validity clock")
        if len(set(self.conflict_codes)) != len(self.conflict_codes):
            raise ValueError("Conflict category repeated")
        if self.status == "clear" and self.conflict_codes:
            raise ValueError("Clear conflict check cannot retain conflict findings")
        if self.status == "conflict" and not self.conflict_codes:
            raise ValueError("Known conflict requires an explicit finding category")
        return self


def qs_intake_schemas():
    return service_intake_schemas({"ConflictCheck": QSConflictCheckView})
