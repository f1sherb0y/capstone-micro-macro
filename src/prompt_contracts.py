from __future__ import annotations

from decimal import Decimal


BID_DOCUMENT_FIELDS = [
    "technical_proposal",
    "implementation_plan",
    "quotation_breakdown",
    "quotation",
    "schedule_commitment",
    "owner_control_response",
    "risk_response",
    "submission_summary",
]


PROJECT_IDEA_FIELDS = [
    "project_name",
    "project_type",
    "location",
    "owner_intent",
    "scale_hint",
    "budget_hint",
    "schedule_hint",
    "constraints",
]


OWNER_REQUIREMENT_FIELDS = [
    "project_scope",
    "functional_needs",
    "technical_needs",
    "budget_approach",
    "schedule_approach",
    "owner_control_needs",
    "risk_priorities",
    "package_plan",
]


PACKAGE_REQUIREMENT_FIELDS = [
    "package_id",
    "package_type",
    "package_name",
    "scope",
    "required_company_role",
    "package_capability_needs",
    "bid_content_requests",
    "pricing_approach",
    "owner_comparison_focus",
    "owner_decision_policy",
]


CONSORTIUM_FIELDS = [
    "status",
    "consortium_name",
    "member_company_ids",
    "formation_reason",
    "role_split",
    "agreement_summary",
]


AWARD_FIELDS = [
    "thoughts",
    "selected_bidder_id",
    "decision_reason",
    "content",
]

ROSTER_MEMBER_FIELDS = [
    "agent_name",
    "department",
    "position",
    "personal_profile",
    "responsibilities",
    "decision_authority",
    "communication_style",
]


COMPANY_FIELDS = [
    "company_id",
    "company_name",
    "company_role",
    "profile",
    "strengths",
    "weaknesses",
    "capability_areas",
    "sim_experience_notes",
    "capacity",
    "risk_signals",
    "eligible_packages",
]


def require_fields(data: dict, fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in data]
    if missing:
        raise KeyError(f"{label} missing fields: {missing}")


def require_project_idea_shape(data: dict) -> None:
    require_fields(data, PROJECT_IDEA_FIELDS, "PROJECT_IDEA")
    if not isinstance(data["constraints"], list):
        raise TypeError("PROJECT_IDEA constraints must be a list")


def require_exact_fields(data: dict, fields: list[str], label: str) -> None:
    require_fields(data, fields, label)
    extra = sorted(set(data) - set(fields))
    if extra:
        raise KeyError(f"{label} has extra fields: {extra}")


def require_bid_document_shape(data: dict, enforce_quotation_match: bool = True) -> None:
    require_fields(data, BID_DOCUMENT_FIELDS, "BID_DOCUMENT")
    breakdown = data["quotation_breakdown"]
    if not isinstance(breakdown, list) or not breakdown:
        raise TypeError("BID_DOCUMENT quotation_breakdown must be a non-empty list")
    total = Decimal(0)
    for item in breakdown:
        if not isinstance(item, dict):
            raise TypeError("BID_DOCUMENT quotation_breakdown items must be objects")
        require_fields(item, ["item", "amount", "basis"], "BID_DOCUMENT quotation_breakdown item")
        total += _bid_amount(item["amount"], "quotation_breakdown amount")
    quotation = _bid_amount(data["quotation"], "quotation")
    if quotation < 0:
        raise ValueError("BID_DOCUMENT quotation must not be negative")
    if enforce_quotation_match and abs(total - quotation) > 1:
        raise ValueError(
            f"BID_DOCUMENT quotation_breakdown total {total} does not match quotation {quotation}; "
            f"quotation minus breakdown = {quotation - total}. Recalculate your proposed figures and "
            "return a consistent JSON; no amounts were automatically changed."
        )


def _bid_amount(value, label: str) -> Decimal:
    # JSON booleans, numeric strings and non-finite values are not money.
    if type(value) not in (int, float):
        raise TypeError(f"BID_DOCUMENT {label} must be a finite JSON number")
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise ValueError(f"BID_DOCUMENT {label} must be a finite JSON number")
    return amount


def require_management_decision(data: dict) -> None:
    require_fields(data, ["thoughts", "decision", "reason", "content"], "MANAGEMENT_DECISION")
    if data["decision"] not in {"bid", "no_bid", "bid_with_consortium"}:
        raise ValueError(f"Unsupported management decision: {data['decision']}")


def require_consortium_shape(data: dict) -> None:
    status = data["status"]
    if status not in {"formed", "not_formed"}:
        raise ValueError(f"CONSORTIUM unsupported status: {status}")
    if not isinstance(data["member_company_ids"], list):
        raise TypeError("CONSORTIUM member_company_ids must be a list")
    if not all(isinstance(item, str) for item in data["member_company_ids"]):
        raise TypeError("CONSORTIUM member_company_ids must contain company_id strings")
    if not isinstance(data["role_split"], dict):
        raise TypeError("CONSORTIUM role_split must be an object")
    if not all(isinstance(key, str) for key in data["role_split"]):
        raise TypeError("CONSORTIUM role_split keys must be company_id strings")
    if not all(isinstance(value, str) and value.strip() for value in data["role_split"].values()):
        raise TypeError("CONSORTIUM role_split values must be non-empty role strings")
    unknown_role_keys = set(data["role_split"]) - set(data["member_company_ids"])
    if unknown_role_keys:
        raise ValueError(f"CONSORTIUM role_split keys are not member ids: {sorted(unknown_role_keys)}")
    if status == "formed":
        member_ids = data["member_company_ids"]
        if len(set(member_ids)) < 2:
            raise ValueError("CONSORTIUM formed status needs at least two different member ids")
        missing_roles = set(member_ids) - set(data["role_split"])
        if missing_roles:
            raise ValueError(f"CONSORTIUM role_split is missing member ids: {sorted(missing_roles)}")
    elif data["member_company_ids"] or data["role_split"] or data["consortium_name"]:
        raise ValueError("CONSORTIUM not_formed status needs empty consortium_name, member_company_ids, and role_split")


def require_roster_shape(data: dict) -> None:
    if not isinstance(data, dict):
        raise TypeError("ROSTER top-level output must be an object with a members key")
    members = data["members"]
    if not isinstance(members, list) or not members:
        raise TypeError("ROSTER members must be a non-empty list")
    for member in members:
        require_fields(member, ROSTER_MEMBER_FIELDS, "ROSTER member")
        if not isinstance(member["responsibilities"], list):
            raise TypeError("ROSTER member responsibilities must be a list")
    if not any(member["decision_authority"] == "final" for member in members):
        raise ValueError("ROSTER must include one final decision member")


def require_company_pool_shape(data: dict) -> None:
    if not isinstance(data, dict):
        raise TypeError("COMPANIES top-level output must be an object")
    companies = data["companies"]
    if not isinstance(companies, list) or not companies:
        raise TypeError("COMPANIES companies must be a non-empty list")
    ids: set[str] = set()
    allowed_roles = {"owner", "designer", "supplier", "contractor", "supervisor"}
    allowed_packages = {"design_package", "supplier_package", "contractor_package", "supervision_package"}
    for company in companies:
        require_fields(company, COMPANY_FIELDS, "COMPANIES company")
        if company["company_role"] not in allowed_roles:
            raise ValueError(f"Unsupported company_role: {company['company_role']}")
        if company["company_id"] in ids:
            raise ValueError(f"Duplicate company_id: {company['company_id']}")
        ids.add(company["company_id"])
        for key in ["strengths", "weaknesses", "capability_areas", "sim_experience_notes", "risk_signals", "eligible_packages"]:
            if not isinstance(company[key], list):
                raise TypeError(f"{company['company_id']}.{key} must be a list")
        unknown_packages = set(company["eligible_packages"]) - allowed_packages
        if unknown_packages:
            raise ValueError(f"{company['company_id']} has unknown eligible packages: {sorted(unknown_packages)}")
    owner_count = len([item for item in companies if item["company_role"] == "owner"])
    if owner_count != 1:
        raise ValueError(f"COMPANIES must include exactly one owner, got {owner_count}")
    owner = next(item for item in companies if item["company_role"] == "owner")
    if set(owner["eligible_packages"]) != allowed_packages:
        raise ValueError("Owner eligible_packages must include all package ids")
    for role in ["designer", "supplier", "contractor", "supervisor"]:
        count = len([item for item in companies if item["company_role"] == role])
        if count < 3:
            raise ValueError(f"COMPANIES must include at least three {role} companies, got {count}")
