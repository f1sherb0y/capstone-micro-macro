"""Map Batch001 enterprise records into simulation-ready agent profiles."""

from __future__ import annotations

import re
from typing import Any, Iterable

from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile


ROLE_DISPLAY = {
    "developer_owner": "Owner",
    "design_survey_architecture": "Architect",
    "consulting_supervision_cost": "QS",
    "material_equipment_supplier": "Supplier",
    "digital_bim_green_provider": "Consultant",
    "general_contractor": "Contractor",
    "specialized_contractor": "Contractor",
    "decoration_contractor": "Contractor",
    "installation_contractor": "Contractor",
    "civil_infrastructure_contractor": "Contractor",
    "landscape_demolition_equipment": "Contractor",
}

CITY_DISPLAY = {
    "广州": "Guangzhou",
    "廣州": "Guangzhou",
    "深圳": "Shenzhen",
    "香港": "Hong Kong",
    "澳门": "Macau",
    "澳門": "Macau",
    "珠海": "Zhuhai",
    "佛山": "Foshan",
    "东莞": "Dongguan",
    "東莞": "Dongguan",
    "惠州": "Huizhou",
    "中山": "Zhongshan",
    "江门": "Jiangmen",
    "江門": "Jiangmen",
    "肇庆": "Zhaoqing",
    "肇慶": "Zhaoqing",
}

SCALE_CAPACITY = {
    "micro": 0.65,
    "small": 0.85,
    "medium": 1.05,
    "mid": 1.05,
    "large": 1.30,
    "enterprise": 1.30,
}


class AgentProfileMapper:
    """Translate generated database rows into the engine's canonical profile."""

    def to_profile(self, row: dict[str, Any]) -> EnterpriseAgentProfile:
        role = self.display_role(row.get("role_type", ""))
        city = self.normalize_city(self.clean(row.get("city")) or self.clean(row.get("region")) or self.clean(row.get("headquarter_city")))
        scale = self.clean(row.get("enterprise_scale")).lower()
        operation_regions = self.split_regions(row.get("operation_cities")) or [city]
        cash_reserve_factor = self._ratio(row, "cash_reserve_months", 6.0, 12.0)
        payment_cycle_factor = max(0.0, min(1.0, 1.0 - self.to_float(row, "payment_cycle_days", 90.0) / 240.0))
        default_risk_factor = 1.0 - self.score(row, "default_risk_score", 0.35)

        technical_capability = self.average(
            row,
            [
                "technology_advantage_score",
                "bim_capability_score",
                "smart_site_capability_score",
                "digital_maturity_score",
                "quality_control_score",
            ],
        )
        management_capability = self.average(
            row,
            [
                "subcontract_management_score",
                "delivery_reliability_score",
                "cooperation_score",
                "safety_management_score",
            ],
        )
        financial_capacity = self.average(
            row,
            [
                "financing_capacity_score",
                "credit_rating_score",
                "shock_resilience_score",
            ],
        )

        return EnterpriseAgentProfile(
            agent_id=self.clean(row.get("agent_id")),
            name=self.clean(row.get("company_name")) or self.clean(row.get("name")) or self.clean(row.get("企业名称")),
            role=role,
            region=city,
            enterprise_type=self.clean(row.get("main_business_type")) or self.clean(row.get("role_type")) or role.lower(),
            qualification_level=self.score(row, "qualification_level", 0.55),
            financial_capacity=financial_capacity,
            technical_capability=technical_capability,
            management_capability=management_capability,
            risk_preference=self.score(row, "risk_appetite", self.score(row, "bid_aggressiveness", 0.5)),
            collaboration_preference=self.score(row, "cooperation_preference", self.score(row, "joint_venture_preference", 0.5)),
            cross_region_experience=self.average(
                row,
                ["cross_city_operation_score", "cross_border_operation_score", "gba_integration_score"],
                0.45,
            ),
            policy_adaptability=self.average(
                row,
                ["compliance_score", "green_construction_score", "carbon_management_score", "innovation_orientation_score"],
                0.55,
            ),
            design_capability=self.average(
                row,
                ["technology_advantage_score", "innovation_orientation_score", "bim_capability_score", "quality_orientation_score"],
                0.5,
            ),
            cost_estimation_capability=self.average(
                row,
                ["cost_advantage_score", "quality_control_score", "compliance_score", "delivery_reliability_score"],
                0.5,
            ),
            construction_capability=self.average(
                row,
                ["equipment_capacity_score", "delivery_reliability_score", "technology_advantage_score", "resource_advantage_score"],
                0.5,
            ),
            safety_management_capability=self.score(row, "safety_management_score", 0.5),
            quality_management_capability=self.average(row, ["quality_control_score", "quality_orientation_score"], 0.5),
            supervision_capability=self.average(
                row,
                ["quality_control_score", "safety_management_score", "compliance_score", "technology_advantage_score"],
                0.5,
            ),
            supply_reliability=self.average(
                row,
                ["delivery_reliability_score", "shock_resilience_score", "resource_advantage_score"],
                0.5,
            ),
            material_quality=self.average(row, ["quality_control_score", "brand_advantage_score", "green_construction_score"], 0.5),
            payment_reliability=(0.40 * default_risk_factor + 0.30 * cash_reserve_factor + 0.30 * payment_cycle_factor),
            decision_speed=self.average(row, ["delivery_reliability_score", "cooperation_score", "digital_maturity_score"], 0.5),
            total_resource_capacity=SCALE_CAPACITY.get(scale, 1.0),
            occupied_resource=0.0,
            active_regions=operation_regions,
            preferred_partners=[],
            semantic_memory={
                "batch_id": self.clean(row.get("batch_id")),
                "agent_type": self.clean(row.get("agent_type")),
                "is_synthetic": self.to_bool(row, "is_synthetic"),
                "role_type": self.clean(row.get("role_type")),
                "enterprise_scale": self.clean(row.get("enterprise_scale")),
                "source_ids": self.clean(row.get("source_ids")),
                "source_confidence_score": self.to_float(row, "source_confidence_score", 0.0),
                "notes": self.clean(row.get("notes")),
            },
            episodic_memory=[],
        )

    @classmethod
    def display_role(cls, role_type: Any) -> str:
        cleaned = cls.clean(role_type)
        return ROLE_DISPLAY.get(cleaned, cleaned or "Contractor")

    @classmethod
    def normalize_city(cls, city: Any) -> str:
        cleaned = cls.clean(city)
        return CITY_DISPLAY.get(cleaned, cleaned)

    @classmethod
    def split_regions(cls, value: Any) -> list[str]:
        text = cls.clean(value)
        if not text:
            return []
        regions = re.split(r"[|,，;；/、]+", text)
        normalized = [cls.normalize_city(region) for region in regions if cls.clean(region)]
        return list(dict.fromkeys(region for region in normalized if region))

    @staticmethod
    def clean(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        return "" if text.lower() in {"nan", "none", "nat", "<na>"} else text

    @classmethod
    def to_bool(cls, row: dict[str, Any], field: str) -> bool:
        return cls.clean(row.get(field)).lower() in {"true", "1", "yes", "y"}

    @classmethod
    def to_float(cls, row: dict[str, Any], field: str, default: float = 0.0) -> float:
        try:
            text = cls.clean(row.get(field))
            return float(text) if text else default
        except (TypeError, ValueError):
            return default

    @classmethod
    def score(cls, row: dict[str, Any], field: str, default: float = 0.5) -> float:
        return max(0.0, min(1.0, cls.to_float(row, field, default)))

    @classmethod
    def average(cls, row: dict[str, Any], fields: Iterable[str], default: float = 0.5) -> float:
        values = [cls.score(row, field, default) for field in fields if cls.clean(row.get(field))]
        return sum(values) / len(values) if values else default

    @classmethod
    def _ratio(cls, row: dict[str, Any], field: str, default: float, denominator: float) -> float:
        return max(0.0, min(1.0, cls.to_float(row, field, default) / denominator))
