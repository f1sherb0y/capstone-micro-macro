from __future__ import annotations

from src.agent_runtime import AgentRuntime
from src.discussion_context import public_discussion_line
from src.models import OwnerRequirements, SimulationState, TenderPackage
from src.prompt_contracts import OWNER_REQUIREMENT_FIELDS, PACKAGE_REQUIREMENT_FIELDS, require_fields
from src.prompt_loader import load_prompt
from src.state_ops import company_by_role


async def owner_refine_requirements(state: SimulationState, runtime: AgentRuntime, profile: str = "full") -> OwnerRequirements:
    owner = company_by_role(state, "owner")[0]
    authorized = state.validation_context.get("authorized_packages")
    agents = state.company_agent_rosters[owner.company_id]
    try:
        await runtime.discuss_async(
            state,
            "owner_requirement_refinement",
            owner,
            "",
            agents,
            [(1, "department_requirements"), (2, "cross_department_revision"), (3, "final_tender_requirements")],
            _owner_discussion_context(state),
        )
    except Exception as exc:
        runtime.record_recovery(
            "owner_discussion_skipped",
            error=f"{type(exc).__name__}: {exc}",
        )
    try:
        data = await runtime.for_entity(owner.company_id).ask_json_async(
            load_prompt("owner", "requirements.md"),
            "OWNER_PACKAGE_BRIEF",
            _requirements_prompt(state),
            validator=lambda data: _require_owner_response(data, authorized),
        )
    except Exception as exc:
        runtime.record_recovery(
            "owner_requirements_standard_fallback",
            error=f"{type(exc).__name__}: {exc}",
        )
        return _fallback_owner_requirements(state)
    package_plan = data["package_plan"]
    if not isinstance(package_plan, list):
        raise TypeError("package_plan must be a list")
    packages = [_package(item, authorized) for item in package_plan]
    return OwnerRequirements(
        state.project_idea.project_id,
        data["project_scope"],
        data["functional_needs"],
        data["technical_needs"],
        data["budget_approach"],
        data["schedule_approach"],
        data["owner_control_needs"],
        data["risk_priorities"],
        packages,
    )


def _require_owner_response(data: dict, authorized: dict | None = None) -> None:
    require_fields(data, OWNER_REQUIREMENT_FIELDS, "OWNER_PACKAGE_BRIEF")
    package_plan = data["package_plan"]
    if not isinstance(package_plan, list):
        raise TypeError("package_plan must be a list")
    if not package_plan:
        raise ValueError("package_plan must not be empty")
    for item in package_plan:
        if not isinstance(item, dict):
            raise TypeError("package_plan items must be objects")
        _package(item, authorized)
    if authorized and {item["package_id"] for item in package_plan} != set(authorized):
        raise ValueError("Package plan must cover exactly the authorized package IDs")
    if len({item["package_id"] for item in package_plan}) != len(package_plan):
        raise ValueError("Duplicate package IDs")


def _requirements_prompt(state: SimulationState) -> str:
    discussions = [
        public_discussion_line(msg)
        for msg in state.agent_discussion_history
        if msg.stage == "owner_requirement_refinement"
    ]
    idea = state.project_idea
    return (
        f"Project id: {idea.project_id}\nProject name: {idea.project_name}\n"
        f"Project type: {idea.project_type}\nLocation: {idea.location}\n"
        f"Owner intent: {idea.owner_intent}\nScale hint: {idea.scale_hint}\n"
        f"Budget hint: {idea.budget_hint}\nSchedule hint: {idea.schedule_hint}\n"
        f"Constraints: {idea.constraints}\nOwner discussion:\n"
        + "\n".join(f"- {item}" for item in discussions[-10:])
        + _authorized_scope(state)
    )


def _owner_discussion_context(state: SimulationState) -> str:
    idea = state.project_idea
    return (
        "The owner organization is turning a rough project idea into a tender strategy. "
        "Treat this as the owner's early intent, not as a complete tender brief.\n"
        f"Project id: {idea.project_id}\nProject name: {idea.project_name}\n"
        f"Project type: {idea.project_type}\nLocation: {idea.location}\n"
        f"Owner intent: {idea.owner_intent}\nScale hint: {idea.scale_hint}\n"
        f"Budget hint: {idea.budget_hint}\nSchedule hint: {idea.schedule_hint}\n"
        f"Constraints: {idea.constraints}\n"
        "Discuss what the owner needs to clarify, how packages should be separated, "
        "which owner review controls matter, and which risks should shape the tender."
        + _authorized_scope(state)
    )


def _authorized_scope(state: SimulationState) -> str:
    authorized = state.validation_context.get("authorized_packages")
    if not authorized:
        return ""
    import json
    return ("\nINTEGRATED PROCUREMENT: the organization is the actual buyer for this task. "
            "Refine only these authorized packages. Preserve their exact IDs, roles, types and scope boundaries; "
            "do not generate the four legacy default packages. Cost-consulting means QS advice, not government approval.\n"
            + json.dumps(authorized, ensure_ascii=False))


def _package(data: dict, authorized: dict | None = None) -> TenderPackage:
    require_fields(data, PACKAGE_REQUIREMENT_FIELDS, "OWNER_PACKAGE_BRIEF package")
    package_id = data["package_id"] if authorized else _package_id(data["package_id"], data["package_type"], data["required_company_role"])
    package_type = data["package_type"]
    role = data["required_company_role"]
    if package_id not in (set(authorized) if authorized else {"design_package", "supplier_package", "contractor_package", "supervision_package"}):
        raise ValueError(f"Unsupported package_id from LLM: {package_id}")
    if authorized and (package_type != authorized[package_id]["package_type"] or role != authorized[package_id]["required_company_role"]):
        raise ValueError("Package type/role differs from macro authorization")
    if package_type not in {"design", "supplier", "contractor", "supervision"}:
        raise ValueError(f"Unsupported package_type from LLM: {package_type}")
    if role not in {"designer", "supplier", "contractor", "supervisor"}:
        raise ValueError(f"Unsupported required_company_role from LLM: {role}")
    for key in ["package_capability_needs", "bid_content_requests", "owner_comparison_focus"]:
        if not isinstance(data[key], list):
            raise TypeError(f"{package_id}.{key} must be a list")
    return TenderPackage(
        package_id,
        package_type,
        data["package_name"],
        data["scope"],
        role,
        data["package_capability_needs"],
        data["bid_content_requests"],
        data["pricing_approach"],
        data["owner_comparison_focus"],
        data["owner_decision_policy"],
    )


def _package_id(raw_id: str, package_type: str, role: str) -> str:
    mapping = {
        "design": "design_package",
        "designer": "design_package",
        "supplier": "supplier_package",
        "supply": "supplier_package",
        "contractor": "contractor_package",
        "construction": "contractor_package",
        "supervisor": "supervision_package",
        "supervision": "supervision_package",
    }
    text = str(raw_id)
    if text in {"design_package", "supplier_package", "contractor_package", "supervision_package"}:
        return text
    for key in [package_type, role, text.split("_", 1)[0]]:
        if key in mapping:
            return mapping[key]
    return text


def _fallback_owner_requirements(state: SimulationState) -> OwnerRequirements:
    packages = [
        TenderPackage(
            f"{package_type if package_type != 'supervision' else 'supervision'}_package",
            package_type,
            name,
            f"Standard degraded-simulation scope for {name}.",
            role,
            ["Role-appropriate capability", "Available delivery capacity"],
            ["Technical response", "Price", "Schedule", "Risk response"],
            "Submit an auditable MOP quotation.",
            ["Technical fit", "delivery confidence", "price reasonableness"],
            "No automatic award; owner evaluation remains required.",
        )
        for package_type, name, role in [
            ("design", "Design services", "designer"),
            ("supplier", "Equipment and material supply", "supplier"),
            ("contractor", "Main construction", "contractor"),
            ("supervision", "Independent supervision", "supervisor"),
        ]
    ]
    idea = state.project_idea
    return OwnerRequirements(
        idea.project_id,
        idea.owner_intent,
        ["Deliver the stated owner intent"],
        ["Use role-appropriate technical standards"],
        idea.budget_hint,
        idea.schedule_hint,
        ["Auditable owner review", "Safety and quality control"],
        list(idea.constraints),
        packages,
    )
