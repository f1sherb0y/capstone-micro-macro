from __future__ import annotations

from typing import Any


def normalize_agent_message(data: dict[str, Any]) -> list[str]:
    return _fill_text(
        data,
        {
            "thoughts": "",
            "recommendation": "No explicit recommendation was returned.",
            "decision_impact": "No explicit decision impact was returned.",
        },
    )


def normalize_management_decision(data: dict[str, Any]) -> list[str]:
    changes = _fill_text(data, {"thoughts": ""})
    if "content" not in data and isinstance(data.get("decision"), str):
        data["content"] = f"Management decision: {data['decision']}"
        changes.append("content:derived_from_decision")
    return changes


def normalize_consortium(data: dict[str, Any]) -> list[str]:
    changes = _fill_text(data, {"formation_reason": "No formation reason was returned."})
    role_split = data.get("role_split")
    member_ids = data.get("member_company_ids")
    if (
        isinstance(role_split, dict)
        and role_split
        and isinstance(member_ids, list)
        and all(isinstance(item, str) for item in member_ids)
        and all(isinstance(key, str) and isinstance(value, str) for key, value in role_split.items())
        and set(role_split.values()) == set(member_ids)
    ):
        data["role_split"] = {company_id: role_label for role_label, company_id in role_split.items()}
        changes.append("role_split:inverted_label_to_company_mapping")
    if "agreement_summary" not in data:
        reason = data.get("formation_reason")
        data["agreement_summary"] = (
            str(reason) if isinstance(reason, str) and reason.strip() else "Consortium responsibilities require clarification."
        )
        changes.append("agreement_summary:derived_from_formation_reason")
    return changes


def normalize_bid_document(data: dict[str, Any]) -> list[str]:
    if "submission_summary" not in data and isinstance(data.get("technical_proposal"), str):
        data["submission_summary"] = data["technical_proposal"][:500]
        return ["submission_summary:derived_from_technical_proposal"]
    return []


def normalize_evaluation(data: dict[str, Any]) -> list[str]:
    return _fill_text(
        data,
        {
            "comparison_summary": "The structured bid evaluations are the comparison record.",
            "owner_review_notes": "No additional owner review notes were returned.",
        },
    )


def normalize_award(data: dict[str, Any]) -> list[str]:
    changes = _fill_text(data, {"thoughts": ""})
    if "content" not in data and isinstance(data.get("selected_bidder_id"), str):
        data["content"] = f"Selected bidder: {data['selected_bidder_id']}"
        changes.append("content:derived_from_selected_bidder_id")
    return changes


def normalize_roster(data: dict[str, Any]) -> list[str]:
    changes: list[str] = []
    members = data.get("members")
    if not isinstance(members, list):
        return changes
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            continue
        for field, default in {
            "personal_profile": "No personal profile was returned.",
            "communication_style": "Direct and role-focused.",
        }.items():
            if field not in member:
                member[field] = default
                changes.append(f"members[{index}].{field}:defaulted")
    return changes


def _fill_text(data: dict[str, Any], defaults: dict[str, str]) -> list[str]:
    changes: list[str] = []
    for field, default in defaults.items():
        if field not in data:
            data[field] = default
            changes.append(f"{field}:defaulted")
    return changes
