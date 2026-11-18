from __future__ import annotations

from typing import Any

from src.models import Company, ProjectIdea
from src.progress import log as progress_log
from src.prompt_contracts import require_company_pool_shape, require_project_idea_shape
from src.prompt_loader import load_prompt


async def generate_project_idea(llm_runtime: Any, project_prompt: str | None) -> ProjectIdea:
    if project_prompt:
        return ProjectIdea(
            "project_001",
            "用户指定建筑项目",
            "user_defined",
            "澳门",
            project_prompt,
            "由业主方 agent 进一步细化",
            "由业主方 agent 进一步细化",
            "由业主方 agent 进一步细化",
            ["需求由业主方 agent 进一步细化"],
            "user_input",
        )
    data = await llm_runtime.ask_json_async(
        load_prompt("generator", "project_idea.md"),
        "PROJECT_IDEA",
        "生成一个中文的业主初步项目想法。",
        validator=require_project_idea_shape,
    )
    return ProjectIdea(
        "project_001",
        data["project_name"],
        data["project_type"],
        data["location"],
        data["owner_intent"],
        data["scale_hint"],
        data["budget_hint"],
        data["schedule_hint"],
        data["constraints"],
        "generator_agent",
    )


async def generate_companies(llm_runtime: Any, project_idea: ProjectIdea, profile: str = "full") -> list[Company]:
    progress_log("companies: asking LLM to generate market participant pool")
    data = await llm_runtime.ask_json_async(
        load_prompt("company", "pool.md"),
        "COMPANIES",
        _companies_prompt(project_idea),
        validator=require_company_pool_shape,
    )
    companies = [_company(item) for item in data["companies"]]
    if profile == "smoke":
        return _smoke_companies(companies)
    return companies


def _companies_prompt(project_idea: ProjectIdea) -> str:
    return (
        f"Project id: {project_idea.project_id}\nProject name: {project_idea.project_name}\n"
        f"Project type: {project_idea.project_type}\nLocation: {project_idea.location}\n"
        f"Owner intent: {project_idea.owner_intent}\nScale hint: {project_idea.scale_hint}\n"
        f"Budget hint: {project_idea.budget_hint}\nSchedule hint: {project_idea.schedule_hint}\n"
        f"Constraints: {project_idea.constraints}"
    )


def _company(data: dict) -> Company:
    return Company(
        data["company_id"],
        data["company_name"],
        data["company_role"],
        data["profile"],
        data["strengths"],
        data["weaknesses"],
        data["capability_areas"],
        data["sim_experience_notes"],
        data["capacity"],
        data["risk_signals"],
        data["eligible_packages"],
    )


def _smoke_companies(companies: list[Company]) -> list[Company]:
    selected: list[Company] = []
    for role, limit in [("owner", 1), ("designer", 3), ("supplier", 3), ("contractor", 3), ("supervisor", 3)]:
        selected.extend([company for company in companies if company.company_role == role][:limit])
    return selected
