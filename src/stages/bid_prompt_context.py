from __future__ import annotations

from src.models import Company, ParticipationDecision, SimulationState, TenderPackage
from src.state_ops import company_by_id


def bidder_context(consortium, companies: list[Company]) -> str:
    if not consortium:
        return company_context(companies[0])
    members = "\n".join(company_context(company) for company in companies)
    return (
        f"consortium name: {consortium.consortium_name}\n"
        f"lead company: {consortium.lead_company_id}\nmember company ids: {consortium.member_company_ids}\n"
        f"formation reason: {consortium.formation_reason}\nrole split: {consortium.role_split}\n"
        f"agreement summary: {consortium.agreement_summary}\nmember profiles:\n{members}"
    )


def bid_document_discussion_context(package: TenderPackage, decision: ParticipationDecision, consortium, bidder_name: str) -> str:
    structure = "consortium" if consortium else "single-company"
    decision_text = decision.decision
    return (
        f"Prepare the bid document for {package.package_name}. "
        f"The current bidder is {bidder_name} as a {structure} bidder. "
        f"The participation decision already recorded for this package is {decision_text}. "
        f"This stage should turn that decided bidding position into a credible technical, commercial, risk, and owner-control submission. "
        f"Do not reopen whether to bid alone or form a consortium unless the context explicitly says the prior decision failed."
    )


def bid_decisions(state: SimulationState, package_id: str, company_ids: set[str], bidder_type: str) -> list[str]:
    source = state.participation_decisions
    if bidder_type == "company":
        source = list(reversed(source))
    decisions: list[str] = []
    seen: set[str] = set()
    for item in source:
        if item.package_id == package_id and item.company_id in company_ids and item.company_id not in seen:
            decisions.append(f"{item.company_id}: {item.decision}; reason: {item.reason}; "
                             f"unresolved conditions: {item.unresolved_condition_ids}; "
                             f"bid assumptions: {item.bid_assumptions}")
            seen.add(item.company_id)
    return list(reversed(decisions)) if bidder_type == "company" else decisions


def competition_context(state: SimulationState, package_id: str, bidder_id: str, own_company_ids: set[str]) -> str:
    if state.validation_context.get("integration"):
        return "Other bidders' participation, private resources, reasons and sealed prices are not disclosed."
    competitors = [
        item
        for item in state.participation_decisions
        if item.package_id == package_id
        and item.company_id not in own_company_ids
        and item.decision in {"bid", "bid_with_consortium"}
        and not _covered_by_own_consortium(state, item.company_id, package_id, bidder_id)
    ]
    lines = []
    for item in competitors:
        company = company_by_id(state, item.company_id)
        bidder_note = _competitor_bidder_note(state, item)
        lines.append(
            f"- {company.company_id}: {company.company_name} ({company.company_role}); "
            f"profile: {company.profile}; strengths: {company.strengths}; weaknesses: {company.weaknesses}; "
            f"capacity: {company.capacity}; risk signals: {company.risk_signals}; "
            f"participation: {item.decision}; reason: {item.reason}; bidder structure: {bidder_note}"
        )
    if not lines:
        return "No other participating bidder profiles are visible for this package."
    return "\n".join(lines)


def company_context(company: Company) -> str:
    return (
        f"- {company.company_id}: {company.company_name} ({company.company_role})\n"
        f"  profile: {company.profile}\n  strengths: {company.strengths}\n"
        f"  weaknesses: {company.weaknesses}\n  capabilities: {company.qualifications}\n"
        f"  past experience: {company.past_project_experience}\n  capacity: {company.capacity}\n"
        f"  risk signals: {company.risk_signals}"
    )


def _covered_by_own_consortium(state: SimulationState, company_id: str, package_id: str, bidder_id: str) -> bool:
    return any(
        item.consortium_id == bidder_id and item.package_id == package_id and company_id in item.member_company_ids
        for item in state.consortiums
    )


def _competitor_bidder_note(state: SimulationState, decision: ParticipationDecision) -> str:
    consortium = next(
        (
            item
            for item in state.consortiums
            if item.package_id == decision.package_id and item.lead_company_id == decision.company_id and item.status == "formed"
        ),
        None,
    )
    if not consortium:
        return "single-company bidder"
    return (
        f"consortium {consortium.consortium_name}, members {consortium.member_company_ids}, "
        f"role split {consortium.role_split}"
    )
