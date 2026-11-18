from typing import Any, Dict, Optional, Set

from pydantic import BaseModel, Field


FORBIDDEN_ACTION_MUTATION_KEYS = frozenset(
    {
        "current_stage",
        "next_stage",
        "stage_transition",
        "force_transition",
        "performance",
        "project_state",
        "planned_progress",
        "actual_progress",
        "progress_deviation",
        "overall_quality",
        "actual_cost",
        "delay_days",
        "engagements",
        "engagement_status",
        "resource_allocation",
        "selected_architect_id",
        "selected_engineer_id",
        "selected_qs_id",
        "selected_contractor_id",
        "selected_supplier_ids",
        "bids",
        "contracts",
        "event_log",
    }
)


class AgentAction(BaseModel):
    action_type: str = Field(
        description="Single action selected by the enterprise agent from the current stage's allowed actions."
    )
    project_id: Optional[str] = Field(
        default=None,
        description="Current project identifier that the decision applies to.",
    )
    agent_id: str = Field(description="Enterprise agent identifier making this decision.")
    decision: bool = Field(
        default=True,
        description="Whether the agent chooses to execute the selected action.",
    )
    data: Dict = Field(
        default_factory=dict,
        description="Decision-specific read-only payload such as bid price, risk level, or rationale details.",
    )
    reason: str = Field(
        default="",
        description="Concise enterprise reasoning behind the selected action.",
    )


def find_forbidden_action_mutation_keys(payload: Any) -> Set[str]:
    found: Set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_ACTION_MUTATION_KEYS:
                found.add(key)
            found.update(find_forbidden_action_mutation_keys(value))
    elif isinstance(payload, list):
        for item in payload:
            found.update(find_forbidden_action_mutation_keys(item))
    return found
