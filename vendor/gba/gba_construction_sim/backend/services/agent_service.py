from datetime import datetime
from typing import Dict, Optional

from gba_construction_sim.backend.models.frontend_dto import AgentChatResponseDTO, AgentListItemDTO, AgentProfileDTO
from gba_construction_sim.backend.storage.agent_database import agent_database, summarize_agent


def _float(record: Dict, field: str, default: float = 0.0) -> float:
    try:
        value = record.get(field)
        return float(value) if value not in {None, ""} else default
    except (TypeError, ValueError):
        return default


def _int(record: Dict, field: str, default: int = 0) -> int:
    try:
        value = record.get(field)
        return int(float(value)) if value not in {None, ""} else default
    except (TypeError, ValueError):
        return default


def _established_year(record: Dict) -> int:
    text = str(record.get("成立时间") or "")
    for token in text.replace("/", "-").split("-"):
        if token[:4].isdigit():
            year = int(token[:4])
            if 1800 <= year <= 2026:
                return year
    return 2026


def _capabilities(record: Dict) -> Dict[str, float]:
    summary = summarize_agent(record)
    return {
        "financial_strength": round(float(summary["financial_capacity"]) * 5, 2),
        "technical_capability": round(float(summary["technical_capability"]) * 5, 2),
        "project_experience": round(float(summary["cross_region_experience"]) * 5, 2),
        "innovation_level": round(float(summary["policy_adaptability"]) * 5, 2),
        "compliance_level": round(float(summary["management_capability"]) * 5, 2),
    }


def _profile_from_record(record: Dict) -> Dict:
    summary = summarize_agent(record)
    capabilities = _capabilities(record)
    name = summary["name"]
    role = summary["role"]
    city = summary["region"]
    operation_cities = str(record.get("operation_cities") or city).replace("|", ", ")
    revenue_billion = round(_float(record, "annual_revenue_million") / 1000, 3)
    qualification = record.get("qualification_level") or "not_applicable"
    return AgentProfileDTO(
        agent_id=summary["agent_id"],
        name=name,
        role=role,
        region=city,
        scale=str(record.get("enterprise_scale") or "unknown"),
        ownership=str(record.get("ownership_type") or "unknown"),
        established_year=_established_year(record),
        employees=_int(record, "employees"),
        annual_revenue=revenue_billion,
        service_scope=operation_cities,
        description=summary["short_description"],
        capabilities=capabilities,
        capability_tags=summary["tags"],
        radar=capabilities,
        recent_activities=[
            {
                "activity_id": "DATA001",
                "date": "2026-05",
                "title": f"Loaded into Batch 001 agent database as {record.get('agent_type')}",
                "type": "database",
                "description": "The profile is sourced from generated Batch 001 simulation data.",
            },
            {
                "activity_id": "SIM001",
                "date": "2026-05",
                "title": f"Configured for {record.get('project_type_preference') or 'GBA'} project simulation",
                "type": "simulation",
            },
            {
                "activity_id": "RISK001",
                "date": "2026-05",
                "title": f"Compliance score {float(_float(record, 'compliance_score')):.2f}, debt risk {float(_float(record, 'debt_risk_score')):.2f}",
                "type": "risk",
            },
        ],
        notes=(
            f"{record.get('notes') or ''} Qualification: {qualification}. "
            f"Source: {record.get('data_source_type')}; source_ids: {record.get('source_ids')}."
        ).strip(),
        updated_at=datetime.utcnow().replace(microsecond=0).isoformat(),
    ).dict()


class AgentService:
    def list_agents(
        self,
        agent_type: Optional[str] = None,
        region: Optional[str] = None,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> list[Dict]:
        items = agent_database.list_agents(agent_type, region, status, keyword)
        return [AgentListItemDTO(**summarize_agent(item)).dict() for item in items]

    def get_agent(self, agent_id: str) -> Dict:
        record = agent_database.get_agent(agent_id)
        if record is None:
            raise KeyError(f"Agent not found: {agent_id}")
        return _profile_from_record(record)

    def create_agent(self, payload: Dict) -> Dict:
        item = dict(payload)
        item.setdefault("agent_id", "CUSTOM_AGENT_PREVIEW")
        item.setdefault("name", item.get("company_name", "Custom Agent"))
        item.setdefault("role", item.get("role", "Contractor"))
        item.setdefault("region", item.get("region", "深圳"))
        item.setdefault("status", "active")
        item.setdefault("ai_generated", False)
        item.setdefault("rating", 4.0)
        item.setdefault("project_count", 0)
        item.setdefault("tags", [])
        item.setdefault("short_description", "Preview-only custom agent. Persisting custom agents is not enabled for the generated database.")
        return AgentListItemDTO(**item).dict()

    def update_agent(self, agent_id: str, payload: Dict) -> Dict:
        created = dict(payload)
        created["agent_id"] = agent_id
        return self.create_agent(created)

    def delete_agent(self, agent_id: str) -> Dict:
        return {"deleted": False, "agent_id": agent_id, "reason": "generated_batch_database_is_read_only"}

    def chat(self, agent_id: str, message: str, context: Dict) -> Dict:
        profile = self.get_agent(agent_id)
        lower_message = message.lower()
        if "policy" in lower_message or "low-carbon" in lower_message:
            reply = f"{profile['name']} will respond through green construction, BIM coordination, compliance checks, and margin discipline based on its Batch 001 capability profile."
            reasoning = "The response uses the generated agent database fields for innovation, green construction, and compliance."
        elif "partner" in lower_message:
            reply = f"{profile['name']} prefers partners with reliable delivery, compatible city coverage, and transparent quality and payment behavior."
            reasoning = "The answer is based on cooperation, cross-region operation, quality, and financial-capacity fields."
        else:
            reply = f"{profile['name']} has strong {profile['role']} capabilities in {profile['region']} and can participate in simulation-ready GBA projects."
            reasoning = "The answer summarizes the SQLite-backed AgentProfileDTO generated from Batch 001."
        return AgentChatResponseDTO(
            agent_id=agent_id,
            reply=reply,
            reasoning_summary=reasoning,
            used_memory=[
                {
                    "memory_type": "semantic",
                    "content": "Agent capabilities and recent activities are loaded from the platform profile catalog.",
                }
            ],
            timestamp=datetime.utcnow().replace(microsecond=0).isoformat(),
        ).dict()


agent_service = AgentService()
