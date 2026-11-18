from copy import deepcopy
from typing import Dict, Optional

from gba_construction_sim.backend.models.frontend_dto import PolicyDTO, PolicyListItemDTO, PolicyPreviewDTO
from gba_construction_sim.backend.services.mock_catalog import POLICIES


class PolicyService:
    def list_policies(
        self,
        policy_type: Optional[str] = None,
        region: Optional[str] = None,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> list[Dict]:
        items = POLICIES
        if policy_type and policy_type.lower() not in {"all", "all types"}:
            items = [item for item in items if item["policy_type"].lower() == policy_type.lower()]
        if region and region.lower() not in {"all", "all regions"}:
            items = [item for item in items if item["region"].lower() == region.lower()]
        if status and status.lower() not in {"all", "all status"}:
            items = [item for item in items if item["status"].lower() == status.lower()]
        if keyword:
            needle = keyword.lower()
            items = [item for item in items if needle in item["name"].lower() or needle in item["policy_type"].lower()]
        return [PolicyListItemDTO(**item).dict() for item in items]

    def get_policy(self, policy_id: str) -> Dict:
        base = deepcopy(next((item for item in POLICIES if item["policy_id"] == policy_id), POLICIES[0]))
        is_green = base["policy_id"] == "POL002"
        detail = {
            "policy_id": base["policy_id"],
            "name": base["name"],
            "policy_type": base["policy_type"],
            "applicable_region": base["region"],
            "start_date": "2025-05-01",
            "duration_years": 3,
            "source": "GBA Development Office",
            "description": "This policy aims to lower institutional barriers and support cross-regional cooperation among construction-related actors within the Greater Bay Area.",
            "parameters": {
                "entry_waiting_time": 20.0 if not is_green else 28.0,
                "approval_success_prob": 0.82 if not is_green else 0.74,
                "procedural_uncertainty": 0.18 if not is_green else 0.24,
                "compliance_cost": 0.14 if not is_green else 0.20,
                "scope_breadth": 0.88,
                "cross_region_qualification_recognition": 0.78 if not is_green else 0.58,
                "tax_or_subsidy_intensity": 0.16 if not is_green else 0.28,
                "regulatory_intensity": 0.58 if not is_green else 0.68,
                "information_transparency": 0.76,
            },
            "parameter_summary": {
                "policy_intensity": 4.3,
                "scope_of_impact": 3.8,
                "incentive_strength": 3.6 if not is_green else 4.4,
                "compliance_requirement": 3.0 if not is_green else 3.7,
                "implementation_certainty": 4.1,
            },
            "impact_radar": {
                "market_access": 4.2,
                "collaboration": 4.4,
                "compliance": 3.8,
                "cost": 3.5,
                "innovation": 4.0 if not is_green else 4.7,
            },
            "parameter_tags": base["tags"],
            "recent_updates": [
                {"update_id": "UP001", "date": "2025-05", "title": "Expanded eligible entities to include professional consultancies"},
                {"update_id": "UP002", "date": "2025-04", "title": "Added multi-level recognition of cross-border qualifications"},
                {"update_id": "UP003", "date": "2025-03", "title": "Clarified fast-track approval procedures for cross-border projects"},
            ],
            "notes": "Policy parameters are quantified for simulation use. Ranges reflect expected policy design under normal implementation conditions and may vary by region and project type.",
        }
        return PolicyDTO(**detail).dict()

    def preview_policy(self, policy_id: str) -> Dict:
        policy = self.get_policy(policy_id)
        preview = {
            "policy_id": policy["policy_id"],
            "name": policy["name"],
            "status": "ready" if policy["policy_id"] != "POL004" else "draft",
            "expected_influence_path": [
                {"step": 1, "name": "Agent Behaviour", "description": "Entry willingness and cross-border collaboration preference increase"},
                {"step": 2, "name": "Project Participation", "description": "More cross-regional bids and faster approvals"},
                {"step": 3, "name": "Collaboration Network", "description": "Denser inter-city links and repeated partnerships"},
                {"step": 4, "name": "Market Structure", "description": "Moderately higher competition and improved resource circulation"},
            ],
            "quantified_parameters": {
                "waiting_time_reduction": -25,
                "approval_success_increase": 18,
                "compliance_burden_change": -15,
                "incentive_strength_change": 22,
            },
            "affected_agent_types": [
                {"role": "contractor", "impact_level": "high"},
                {"role": "developer", "impact_level": "high"},
                {"role": "design_institute", "impact_level": "medium"},
                {"role": "supplier", "impact_level": "medium"},
                {"role": "consultant", "impact_level": "medium"},
            ],
            "regional_impact": [
                {"region": "Hong Kong", "impact_level": "high"},
                {"region": "Shenzhen", "impact_level": "high"},
                {"region": "Guangzhou", "impact_level": "medium"},
                {"region": "Zhuhai", "impact_level": "medium"},
                {"region": "Macau", "impact_level": "medium"},
            ],
            "preview_results": {
                "agent_response": "Contractors and consultants become more willing to participate in cross-regional projects.",
                "project_flow": "Approval and tendering stages show lower delay risk and higher bid participation.",
                "network_change": "Cross-city collaboration edges increase and the Shenzhen-Hong Kong-Guangzhou triangle strengthens.",
                "market_effect": "Market concentration decreases moderately as more qualified firms enter.",
            },
        }
        return PolicyPreviewDTO(**preview).dict()

    def create_policy(self, payload: Dict) -> Dict:
        item = {
            "policy_id": payload.get("policy_id", f"POL{len(POLICIES) + 1:03d}"),
            "name": payload.get("name", "Custom Policy Scenario"),
            "policy_type": payload.get("policy_type", "regulation"),
            "region": payload.get("region", payload.get("applicable_region", "GBA")),
            "status": payload.get("status", "draft"),
            "parameter_count": payload.get("parameter_count", 9),
            "tags": payload.get("tags", []),
        }
        POLICIES.append(item)
        return PolicyListItemDTO(**item).dict()

    def update_policy(self, policy_id: str, payload: Dict) -> Dict:
        for item in POLICIES:
            if item["policy_id"] == policy_id:
                item.update(payload)
                if "applicable_region" in payload:
                    item["region"] = payload["applicable_region"]
                return PolicyListItemDTO(**item).dict()
        payload["policy_id"] = policy_id
        return self.create_policy(payload)

    def map_to_parameters(self, policy_id: str) -> Dict:
        return self.get_policy(policy_id)["parameters"]


policy_service = PolicyService()
