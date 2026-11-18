from __future__ import annotations

from src.prompt_contracts import require_exact_fields


EVALUATION_FIELDS = [
    "bid_evaluations",
    "comparison_summary",
    "owner_review_notes",
    "recommended_bidder_id",
]

EVALUATION_BID_FIELDS = [
    "bid_id",
    "bidder_id",
    "bidder_name",
    "technical_view",
    "cost_view",
    "owner_control_view",
    "strengths",
    "concerns",
]


def require_owner_evaluation_shape(data: dict) -> None:
    require_exact_fields(data, EVALUATION_FIELDS, "EVALUATION")
    if not isinstance(data["bid_evaluations"], list):
        raise TypeError("EVALUATION bid_evaluations must be a list")
    for item in data["bid_evaluations"]:
        if not isinstance(item, dict):
            raise TypeError("EVALUATION bid_evaluations items must be objects")
        require_exact_fields(item, EVALUATION_BID_FIELDS, "EVALUATION bid_evaluations item")
        for field in ["strengths", "concerns"]:
            if not isinstance(item[field], list):
                raise TypeError(f"EVALUATION {field} must be a list")
