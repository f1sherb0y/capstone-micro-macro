from __future__ import annotations

import asyncio

from src.agent_runtime import AgentRuntime
from src.models import Company, MemberAgent
from src.progress import log as progress_log
from src.prompt_contracts import require_roster_shape
from src.prompt_loader import load_prompt
from src.response_recovery import normalize_roster


async def generate_member_agents(companies: list[Company], runtime: AgentRuntime) -> dict[str, list[MemberAgent]]:
    progress_log(f"rosters: preparing {len(companies)} company roster tasks")
    raw_results = await asyncio.gather(
        *[_roster_task(company, runtime) for company in companies],
        return_exceptions=True,
    )
    results = []
    for company, result in zip(companies, raw_results):
        if isinstance(result, Exception):
            runtime.record_recovery(
                "roster_fallback",
                company_id=company.company_id,
                error=f"{type(result).__name__}: {result}",
            )
            progress_log(f"roster {company.company_id}: using deterministic fallback after {type(result).__name__}")
            results.append((company.company_id, _fallback_roster(company)))
            continue
        if isinstance(result, BaseException):
            raise result
        results.append(result)
    progress_log("rosters: all company roster tasks completed")
    return {company_id: agents for company_id, agents in results}


async def _roster_task(company: Company, runtime: AgentRuntime) -> tuple[str, list[MemberAgent]]:
    progress_log(f"roster {company.company_id}: start ({company.company_name})")
    data = await runtime.for_entity(company.company_id).ask_json_async(
        load_prompt("company", "roster.md"),
        "ROSTER",
        _roster_prompt(company),
        validator=require_roster_shape,
        normalizer=normalize_roster,
    )
    agents = [_member_agent(company, item, index) for index, item in enumerate(data["members"], start=1)]
    progress_log(f"roster {company.company_id}: done ({len(agents)} agents)")
    return company.company_id, agents


def _member_agent(company: Company, data: dict, index: int) -> MemberAgent:
    slug = str(data["agent_name"]).lower().replace("/", " ").replace(" ", "_")
    return MemberAgent(
        f"{company.company_id}_{index:02d}_{slug}",
        data["agent_name"],
        company.company_id,
        company.company_role,
        data["department"],
        data["position"],
        data["personal_profile"],
        data["responsibilities"],
        data["decision_authority"],
        data["communication_style"],
    )


def _roster_prompt(company: Company) -> str:
    return (
        f"Company id: {company.company_id}\nCompany name: {company.company_name}\nRole: {company.company_role}\n"
        f"Profile: {company.profile}\nStrengths: {company.strengths}\nWeaknesses: {company.weaknesses}\n"
        f"Capability areas: {company.qualifications}\nPast experience: {company.past_project_experience}\n"
        f"Capacity: {company.capacity}\nRisk signals: {company.risk_signals}\nEligible packages: {company.eligible_packages}"
    )


def _fallback_roster(company: Company) -> list[MemberAgent]:
    templates = [
        ("Technical Lead", "Technical", "Technical Lead", ["Review technical fit"], "review"),
        ("Commercial Lead", "Commercial", "Commercial Lead", ["Review cost and contract risk"], "review"),
        ("General Manager", "Management", "General Manager", ["Make the final company decision"], "final"),
    ]
    return [
        _member_agent(
            company,
            {
                "agent_name": name,
                "department": department,
                "position": position,
                "personal_profile": f"Deterministic fallback member for {company.company_name}.",
                "responsibilities": responsibilities,
                "decision_authority": authority,
                "communication_style": "Direct and role-focused.",
            },
            index,
        )
        for index, (name, department, position, responsibilities, authority) in enumerate(templates, start=1)
    ]
