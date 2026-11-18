from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models import SimulationState, dump, load_simulation_state
from src.run_audit import SCHEMA_VERSION, append_jsonl, atomic_write_json, utc_now


STAGE_ORDER = [
    "project",
    "companies",
    "rosters",
    "owner_requirements",
    "participation",
    "consortiums",
    "reconsideration",
    "bid_documents",
    "opening",
    "evaluation",
    "award",
    "execution_placeholder",
]
END_STAGE = "__end__"


class WorkflowCheckpointStore:
    def __init__(self, run_dir: Path, case_id: str, profile: str):
        self.run_dir = run_dir
        self.case_id = case_id
        self.profile = profile
        self.path = run_dir / "workflow_checkpoint.json"
        self.events_path = run_dir / "workflow_checkpoint_events.jsonl"
        self.events_path.touch(exist_ok=True)

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> tuple[SimulationState, str]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("case_id", "") != self.case_id:
            raise ValueError(
                f"Checkpoint case mismatch: expected {self.case_id!r}, found {payload.get('case_id')!r}"
            )
        if payload.get("profile") != self.profile:
            raise ValueError(
                f"Checkpoint profile mismatch: expected {self.profile!r}, found {payload.get('profile')!r}"
            )
        next_stage = str(payload.get("next_stage", ""))
        if next_stage not in {*STAGE_ORDER, END_STAGE}:
            raise ValueError(f"Checkpoint has invalid next_stage: {next_stage!r}")
        return load_simulation_state(payload["state"]), next_stage

    def save(self, completed_stage: str, state: SimulationState) -> None:
        if completed_stage not in STAGE_ORDER:
            raise ValueError(f"Unknown workflow stage: {completed_stage}")
        index = STAGE_ORDER.index(completed_stage)
        next_stage = STAGE_ORDER[index + 1] if index + 1 < len(STAGE_ORDER) else END_STAGE
        payload = {
            "schema_version": SCHEMA_VERSION,
            "saved_at": utc_now(),
            "case_id": self.case_id,
            "profile": self.profile,
            "completed_stage": completed_stage,
            "next_stage": next_stage,
            "state": dump(state),
        }
        atomic_write_json(self.path, payload)
        append_jsonl(
            self.events_path,
            {
                "schema_version": SCHEMA_VERSION,
                "timestamp": payload["saved_at"],
                "case_id": self.case_id,
                "profile": self.profile,
                "completed_stage": completed_stage,
                "next_stage": next_stage,
                "state_counts": _state_counts(state),
            },
        )

    def summary(self) -> dict[str, Any]:
        if not self.exists():
            return {"available": False, "path": str(self.path)}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            "available": True,
            "path": str(self.path),
            "completed_stage": payload.get("completed_stage"),
            "next_stage": payload.get("next_stage"),
            "saved_at": payload.get("saved_at"),
        }


def _state_counts(state: SimulationState) -> dict[str, int]:
    return {
        "companies": len(state.companies),
        "rosters": len(state.company_agent_rosters),
        "messages": len(state.agent_discussion_history),
        "packages": len(state.tender_packages),
        "participation_decisions": len(state.participation_decisions),
        "consortiums": len(state.consortiums),
        "bids": len(state.bid_documents),
        "evaluations": len(state.evaluation_report),
        "awards": len(state.simulated_award_result.get("package_awards", [])),
    }
