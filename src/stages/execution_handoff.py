from __future__ import annotations

from src.models import SimulationState
from src.state_ops import log_event


def write_execution_handoff(state: SimulationState) -> None:
    state.project_execution_log = {
        "status": "not_implemented_in_mvp",
        "purpose": "Structured handoff from simulated tender award into a future project execution simulation.",
        "not_in_scope": [
            "construction progress simulation",
            "site events",
            "payment certification",
            "change orders",
            "delay analysis",
        ],
        "next_stage_inputs": [
            "simulated_award_result.json",
            "bid_documents.json",
            "evaluation_report.json",
            "opening_record.json",
            "agent_discussion_history.json",
        ],
        "package_handoffs": [_package_handoff(state, award) for award in state.simulated_award_result.get("package_awards", [])],
    }
    log_event(
        state,
        "project_execution_handoff_written",
        {"package_count": len(state.project_execution_log["package_handoffs"])},
    )


def _package_handoff(state: SimulationState, award: dict) -> dict:
    bid = next((item for item in state.bid_documents
                if item.bidder_id == award["selected_bidder_id"] and item.package_id == award["package_id"]), None)
    report = next((item for item in state.evaluation_report if item.package_id == award["package_id"]), None)
    return {
        "package_id": award["package_id"],
        "selected_bidder_id": award["selected_bidder_id"],
        "selected_bidder_name": award["selected_bidder_name"],
        "bidder_type": award["bidder_type"],
        "award_reason": award["decision_reason"],
        "quotation": bid.quotation if bid else None,
        "schedule_commitment": bid.schedule_commitment if bid else "",
        "risk_response": bid.risk_response if bid else "",
        "unresolved_condition_ids": list(award.get("unresolved_condition_ids", bid.unresolved_condition_ids if bid else [])),
        "pending_clarifications": list(award.get("pending_clarifications", [])),
        "bid_assumptions": list(bid.bid_assumptions) if bid else [],
        "evaluation_summary": report.comparison_summary if report else "",
        "owner_review_notes": report.owner_review_notes if report else "",
        "discussion_references": _discussion_references(state, award["package_id"]),
    }


def _discussion_references(state: SimulationState, package_id: str) -> list[str]:
    return [
        message.message_id
        for message in state.agent_discussion_history
        if message.package_id == package_id
        and message.stage in {"bid_opening", "evaluation", "owner_award_decision"}
    ][-8:]
