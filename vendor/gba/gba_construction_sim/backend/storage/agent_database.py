"""SQLite-backed access to generated Batch 001 agent data."""

from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime
import hashlib
import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.simulation.agent_profile_mapper import AgentProfileMapper


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AGENT_CSV = PROJECT_ROOT / "outputs" / "gba_construction_agents_batch001.csv"
DEFAULT_AGENT_DB = PROJECT_ROOT / "data" / "processed" / "agent_database.sqlite"
PROFILE_MAPPER = AgentProfileMapper()


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

JSON_COLUMNS = {
    "candidate_actions",
    "available_actions",
    "input_context",
    "belief_snapshot",
    "memory_used",
    "memory_belief_used",
    "strategy_used",
    "retry_info",
    "error",
    "validation_result",
    "result",
    "profile_7s",
    "schein_culture",
}

GBA_TEST_CLUSTER_CITY_TARGETS = {
    "Shenzhen": 205,
    "Guangzhou": 177,
    "Hong Kong": 167,
    "Foshan": 91,
    "Dongguan": 85,
    "Huizhou": 55,
    "Zhuhai": 47,
    "Jiangmen": 46,
    "Zhongshan": 45,
    "Macau": 43,
    "Zhaoqing": 39,
}

DEFAULT_ROLE_CLASS_MIX = {
    "developer": 0.11,
    "contractor": 0.50,
    "consultant": 0.27,
    "supplier": 0.12,
}

# Built from city-level real_user / real_public enterprise observations in
# Batch001, smoothed with construction-domain role floors. Official statistics
# do not publish Owner/Contractor/Supplier/Consultant as a GBA city cross-tab,
# so the real sample is the direct evidence for city-level role tilt.
GBA_TEST_CLUSTER_ROLE_MIX = {
    "Shenzhen": {"developer": 0.231, "contractor": 0.306, "consultant": 0.363, "supplier": 0.100},
    "Guangzhou": {"developer": 0.199, "contractor": 0.381, "consultant": 0.320, "supplier": 0.100},
    "Hong Kong": {"developer": 0.181, "contractor": 0.352, "consultant": 0.385, "supplier": 0.082},
    "Foshan": {"developer": 0.161, "contractor": 0.427, "consultant": 0.291, "supplier": 0.121},
    "Dongguan": {"developer": 0.151, "contractor": 0.437, "consultant": 0.307, "supplier": 0.104},
    "Huizhou": {"developer": 0.104, "contractor": 0.505, "consultant": 0.264, "supplier": 0.126},
    "Zhuhai": {"developer": 0.187, "contractor": 0.437, "consultant": 0.271, "supplier": 0.104},
    "Jiangmen": {"developer": 0.111, "contractor": 0.509, "consultant": 0.248, "supplier": 0.133},
    "Zhongshan": {"developer": 0.107, "contractor": 0.490, "consultant": 0.282, "supplier": 0.121},
    "Macau": {"developer": 0.115, "contractor": 0.574, "consultant": 0.230, "supplier": 0.080},
    "Zhaoqing": {"developer": 0.110, "contractor": 0.498, "consultant": 0.268, "supplier": 0.124},
}

ROLE_CLASS_BY_DISPLAY_ROLE = {
    "Owner": "developer",
    "Architect": "consultant",
    "QS": "consultant",
    "Consultant": "consultant",
    "Contractor": "contractor",
    "Supplier": "supplier",
}

SOURCE_PRIORITY = {
    "real_user": 0,
    "real_public": 1,
    "synthetic": 2,
}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _float(row: dict[str, Any], field: str, default: float = 0.0) -> float:
    try:
        text = _clean(row.get(field))
        return float(text) if text else default
    except (TypeError, ValueError):
        return default


def _int(row: dict[str, Any], field: str, default: int = 0) -> int:
    try:
        text = _clean(row.get(field))
        return int(float(text)) if text else default
    except (TypeError, ValueError):
        return default


def _bool(row: dict[str, Any], field: str) -> bool:
    return _clean(row.get(field)).lower() in {"true", "1", "yes", "y"}


def _score(row: dict[str, Any], field: str, default: float = 0.5) -> float:
    return max(0.0, min(1.0, _float(row, field, default)))


def _avg(row: dict[str, Any], fields: Iterable[str], default: float = 0.5) -> float:
    values = [_score(row, field, default) for field in fields if _clean(row.get(field))]
    if not values:
        return default
    return sum(values) / len(values)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _normalize_city(city: str) -> str:
    cleaned = _clean(city)
    return CITY_DISPLAY.get(cleaned, cleaned)


def _split_regions(value: Any) -> list[str]:
    text = _clean(value)
    if not text:
        return []
    regions = re.split(r"[|,，;；/、]+", text)
    normalized = [_normalize_city(region) for region in regions if _clean(region)]
    return list(dict.fromkeys(region for region in normalized if region))


def display_role(role_type: str) -> str:
    return ROLE_DISPLAY.get(_clean(role_type), _clean(role_type) or "Contractor")


def _norm_name(name: str) -> str:
    return re.sub(r"[\s（）()·,，.。\-—_]+", "", name.lower())


def _rating(row: dict[str, Any]) -> float:
    values = [
        _float(row, "quality_control_score", 0.65),
        _float(row, "delivery_reliability_score", 0.65),
        _float(row, "compliance_score", 0.65),
        _float(row, "reputation_score", 0.65),
    ]
    return round(2.2 + (sum(values) / len(values)) * 2.8, 1)


def _tags(row: dict[str, Any]) -> list[str]:
    tags = [
        _clean(row.get("enterprise_scale")).title(),
        _clean(row.get("city")),
        _clean(row.get("role_type")),
    ]
    if _bool(row, "is_synthetic"):
        tags.append("Synthetic")
    elif _clean(row.get("agent_type")) == "real_public":
        tags.append("Real Public")
    else:
        tags.append("User Data")
    if _float(row, "green_construction_score") >= 0.65:
        tags.append("Green")
    if _float(row, "digital_maturity_score") >= 0.65:
        tags.append("Digital")
    return [tag for tag in tags if tag]


def _data_origin(row: dict[str, Any]) -> str:
    agent_type = _clean(row.get("agent_type"))
    if agent_type in {"real_user", "real_public", "synthetic"}:
        return agent_type
    if _bool(row, "is_synthetic"):
        return "synthetic"
    return _clean(row.get("data_source_type")) or "real_user"


def summarize_agent(row: dict[str, Any]) -> dict[str, Any]:
    role = display_role(row.get("role_type", ""))
    city = _clean(row.get("city"))
    name = _clean(row.get("company_name")) or _clean(row.get("企业名称"))
    project_count = _int(row, "annual_project_capacity") + _int(row, "backlog_project_count")
    return {
        "agent_id": _clean(row.get("agent_id")),
        "name": name,
        "role": role,
        "region": city,
        "status": "active",
        "ai_generated": _bool(row, "is_synthetic"),
        "rating": _rating(row),
        "project_count": project_count,
        "tags": _tags(row),
        "short_description": f"{city}{role} Agent，规模为 {_clean(row.get('enterprise_scale'))}，用于 GBA 建筑业仿真。",
        "agent_type": _clean(row.get("agent_type")),
        "role_type": _clean(row.get("role_type")),
        "enterprise_scale": _clean(row.get("enterprise_scale")),
        "data_source_type": _clean(row.get("data_source_type")),
        "source_type": _data_origin(row),
        "financial_capacity": _float(row, "financing_capacity_score", 0.6),
        "technical_capability": (
            _float(row, "technology_advantage_score", 0.6)
            + _float(row, "quality_control_score", 0.6)
            + _float(row, "digital_maturity_score", 0.6)
        )
        / 3,
        "cross_region_experience": (
            _float(row, "cross_city_operation_score", 0.4)
            + _float(row, "cross_border_operation_score", 0.2)
            + _float(row, "gba_integration_score", 0.4)
        )
        / 3,
        "policy_adaptability": (
            _float(row, "green_construction_score", 0.5)
            + _float(row, "innovation_orientation_score", 0.5)
            + _float(row, "compliance_score", 0.6)
        )
        / 3,
        "management_capability": (
            _float(row, "subcontract_management_score", 0.5)
            + _float(row, "delivery_reliability_score", 0.6)
            + _float(row, "safety_management_score", 0.6)
        )
        / 3,
    }


def _primary_strategy(row: dict[str, Any], summary: dict[str, Any]) -> str:
    cash_pressure = 1.0 - _clamp(_float(row, "cash_reserve_months", 6.0) / 12.0)
    bid_aggression = _score(row, "bid_aggressiveness", _score(row, "risk_appetite", 0.5))
    innovation = _avg(row, ["innovation_orientation_score", "digital_maturity_score", "green_construction_score"], 0.5)
    quality = _avg(row, ["quality_control_score", "quality_orientation_score", "reputation_score"], 0.5)
    policy = _avg(row, ["compliance_score", "green_construction_score", "carbon_management_score"], 0.5)
    relationship = _avg(row, ["cooperation_score", "joint_venture_preference", "gba_integration_score"], 0.5)
    if cash_pressure >= 0.72 or _score(row, "debt_risk_score", 0.35) >= 0.68:
        return "cash_preserving"
    if bid_aggression >= 0.72 and summary["financial_capacity"] >= 0.55:
        return "price_aggressive"
    if innovation >= 0.72:
        return "innovation_oriented"
    if quality >= 0.72:
        return "quality_focused"
    if policy >= 0.72:
        return "policy_adaptive"
    if relationship >= 0.68:
        return "relationship_driven"
    if bid_aggression < 0.42 or summary["financial_capacity"] < 0.42:
        return "conservative"
    return "growth_oriented"


def _profile_7s(row: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    role = summary["role"]
    region = summary["region"]
    return {
        "strategy": {
            "market_positioning": _clean(row.get("market_positioning")) or f"{region} {role} enterprise",
            "project_preference": _clean(row.get("project_type_preference")) or "GBA construction projects",
            "regional_expansion": _score(row, "cross_city_operation_score", 0.45),
            "bidding_strategy": _score(row, "bid_aggressiveness", 0.5),
        },
        "structure": {
            "enterprise_scale": _clean(row.get("enterprise_scale")),
            "operation_regions": _split_regions(row.get("operation_cities")) or [region],
            "cross_border_operation": _score(row, "cross_border_operation_score", 0.25),
            "joint_venture_preference": _score(row, "joint_venture_preference", 0.5),
        },
        "systems": {
            "tender_system": _score(row, "bid_preparation_score", _score(row, "delivery_reliability_score", 0.55)),
            "delivery_system": _score(row, "delivery_reliability_score", 0.6),
            "quality_system": _score(row, "quality_control_score", 0.6),
            "safety_system": _score(row, "safety_management_score", 0.6),
            "cashflow_system": _score(row, "financing_capacity_score", 0.55),
        },
        "skills": {
            "qualification": _score(row, "qualification_level", 0.55),
            "bim": _score(row, "bim_capability_score", 0.5),
            "green_construction": _score(row, "green_construction_score", 0.5),
            "digital": _score(row, "digital_maturity_score", 0.5),
            "technical": summary["technical_capability"],
        },
        "staff": {
            "employees": _int(row, "employees", 0),
            "project_capacity": _int(row, "annual_project_capacity", 0),
            "resource_capacity": SCALE_CAPACITY.get(_clean(row.get("enterprise_scale")).lower(), 1.0),
        },
        "style": {
            "risk_preference": _score(row, "risk_appetite", _score(row, "bid_aggressiveness", 0.5)),
            "cooperation_style": _score(row, "cooperation_score", 0.5),
            "safety_culture": _score(row, "safety_management_score", 0.6),
        },
        "shared_values": {
            "quality_orientation": _score(row, "quality_orientation_score", _score(row, "quality_control_score", 0.6)),
            "compliance_orientation": _score(row, "compliance_score", 0.6),
            "innovation_orientation": _score(row, "innovation_orientation_score", 0.5),
            "regional_openness": _avg(row, ["cross_city_operation_score", "cross_border_operation_score", "gba_integration_score"], 0.45),
        },
    }


def _schein_culture(row: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifacts": {
            "qualification_level": _clean(row.get("qualification_level")),
            "project_cases": _int(row, "annual_project_capacity", 0) + _int(row, "backlog_project_count", 0),
            "source_type": _data_origin(row),
            "source_ids": _clean(row.get("source_ids")),
        },
        "espoused_values": {
            "quality": _score(row, "quality_orientation_score", _score(row, "quality_control_score", 0.6)),
            "safety": _score(row, "safety_management_score", 0.6),
            "innovation": _score(row, "innovation_orientation_score", 0.5),
            "green": _score(row, "green_construction_score", 0.5),
            "cooperation": _score(row, "cooperation_score", 0.5),
        },
        "underlying_assumptions": {
            "risk_preference": _score(row, "risk_appetite", _score(row, "bid_aggressiveness", 0.5)),
            "cooperation_tendency": _score(row, "cooperation_preference", _score(row, "joint_venture_preference", 0.5)),
            "compliance_tendency": _score(row, "compliance_score", 0.6),
            "regional_openness": summary["cross_region_experience"],
            "cashflow_conservatism": _clamp(1.0 - _float(row, "cash_reserve_months", 6.0) / 12.0),
        },
    }


def _strategy_from_payload(row: dict[str, Any]) -> dict[str, Any]:
    summary = summarize_agent(row)
    cash_preservation = _clamp(
        0.45 * (1.0 - _float(row, "cash_reserve_months", 6.0) / 12.0)
        + 0.35 * _score(row, "debt_risk_score", 0.35)
        + 0.20 * _score(row, "default_risk_score", 0.35)
    )
    return {
        "agent_id": summary["agent_id"],
        "primary_strategy": _primary_strategy(row, summary),
        "bidding_aggressiveness": _score(row, "bid_aggressiveness", _score(row, "risk_appetite", 0.5)),
        "margin_protection_level": _clamp(0.45 + 0.35 * cash_preservation + 0.20 * (1.0 - _score(row, "cost_advantage_score", 0.5))),
        "cooperation_preference": _score(row, "cooperation_preference", _score(row, "joint_venture_preference", 0.5)),
        "risk_tolerance": _score(row, "risk_appetite", 0.5),
        "innovation_preference": _avg(row, ["innovation_orientation_score", "digital_maturity_score", "bim_capability_score"], 0.5),
        "regional_expansion_preference": _avg(row, ["cross_city_operation_score", "cross_border_operation_score", "gba_integration_score"], 0.45),
        "public_project_preference": _score(row, "public_project_preference", 0.55 if summary["role"] in {"Owner", "Contractor", "QS"} else 0.45),
        "private_project_preference": _score(row, "private_project_preference", 0.50),
        "subcontracting_preference": _score(row, "subcontracting_preference", _score(row, "subcontract_management_score", 0.5)),
        "cash_preservation_level": cash_preservation,
        "source_type": _data_origin(row),
        "profile_7s": _profile_7s(row, summary),
        "schein_culture": _schein_culture(row, summary),
    }


def _beliefs_from_payload(row: dict[str, Any]) -> list[dict[str, Any]]:
    summary = summarize_agent(row)
    agent_id = summary["agent_id"]
    values = {
        "self_capacity_belief": (
            summary["financial_capacity"] + summary["technical_capability"] + summary["management_capability"]
        )
        / 3,
        "market_opportunity_belief": _avg(row, ["market_demand_fit_score", "gba_integration_score", "reputation_score"], 0.55),
        "partner_trust_belief": _score(row, "cooperation_score", 0.55),
        "cashflow_risk_belief": _clamp(0.50 * _score(row, "debt_risk_score", 0.35) + 0.50 * _score(row, "default_risk_score", 0.35)),
        "policy_risk_belief": _clamp(1.0 - summary["policy_adaptability"]),
        "competition_belief": _score(row, "competitive_pressure_score", 0.55),
        "regional_openness_belief": summary["cross_region_experience"],
    }
    explanations = {
        "self_capacity_belief": "Derived from financing, technical, and management capability fields.",
        "market_opportunity_belief": "Derived from market fit, GBA integration, and reputation signals.",
        "partner_trust_belief": "Derived from cooperation and joint-venture preference fields.",
        "cashflow_risk_belief": "Derived from debt and default risk signals.",
        "policy_risk_belief": "Inverse of policy adaptability, compliance, green, and innovation signals.",
        "competition_belief": "Derived from competitive pressure or default market competition assumptions.",
        "regional_openness_belief": "Derived from cross-city, cross-border, and GBA integration signals.",
    }
    return [
        {
            "belief_id": f"BEL_{agent_id}_{belief_type}",
            "agent_id": agent_id,
            "belief_type": belief_type,
            "target_type": "self" if belief_type == "self_capacity_belief" else "market",
            "target_id": agent_id if belief_type == "self_capacity_belief" else summary["region"],
            "belief_value": round(_clamp(value), 4),
            "confidence": round(_clamp(0.55 + 0.35 * _float(row, "source_confidence_score", 0.5)), 4),
            "evidence_count": max(1, len([field for field, value in row.items() if _clean(value)])),
            "updated_tick": 0,
            "explanation": explanations[belief_type],
        }
        for belief_type, value in values.items()
    ]


def _memories_from_payload(row: dict[str, Any]) -> list[dict[str, Any]]:
    summary = summarize_agent(row)
    agent_id = summary["agent_id"]
    source_type = _data_origin(row)
    base = {
        "agent_id": agent_id,
        "related_agent_id": None,
        "related_project_id": None,
        "city": summary["region"],
        "sentiment": 0.0,
        "decay_rate": 0.04,
        "created_tick": 0,
        "last_access_tick": 0,
        "source_type": source_type,
    }
    records = [
        {
            **base,
            "memory_id": f"MEM_{agent_id}_profile",
            "memory_type": "project_memory",
            "event_type": "profile_loaded",
            "content": f"{summary['name']} is a {summary['region']} {summary['role']} enterprise loaded from {source_type} data.",
            "importance_score": 0.78,
        },
        {
            **base,
            "memory_id": f"MEM_{agent_id}_market",
            "memory_type": "market_memory",
            "event_type": "market_position",
            "content": f"Operates across {', '.join(_split_regions(row.get('operation_cities')) or [summary['region']])} with GBA openness {summary['cross_region_experience']:.2f}.",
            "importance_score": 0.62,
        },
        {
            **base,
            "memory_id": f"MEM_{agent_id}_risk",
            "memory_type": "risk_memory",
            "event_type": "risk_profile",
            "content": f"Cashflow and compliance signals imply financial capacity {summary['financial_capacity']:.2f} and policy adaptability {summary['policy_adaptability']:.2f}.",
            "importance_score": 0.70,
        },
    ]
    if summary["role"] == "Contractor":
        records.append(
            {
                **base,
                "memory_id": f"MEM_{agent_id}_tender",
                "memory_type": "tender_memory",
                "event_type": "tender_strategy",
                "content": "Contractor tender decisions should compare margin, resource availability, project complexity, and regional qualification recognition.",
                "importance_score": 0.74,
            }
        )
    return records


def agent_profile_from_payload(row: dict[str, Any]) -> EnterpriseAgentProfile:
    role = display_role(row.get("role_type", ""))
    city = _normalize_city(_clean(row.get("city")) or _clean(row.get("region")) or _clean(row.get("headquarter_city")))
    scale = _clean(row.get("enterprise_scale")).lower()
    operation_regions = _split_regions(row.get("operation_cities")) or [city]
    cash_reserve_factor = max(0.0, min(1.0, _float(row, "cash_reserve_months", 6.0) / 12.0))
    payment_cycle_factor = max(0.0, min(1.0, 1.0 - _float(row, "payment_cycle_days", 90.0) / 240.0))
    default_risk_factor = 1.0 - _score(row, "default_risk_score", 0.35)
    total_resource_capacity = SCALE_CAPACITY.get(scale, 1.0)

    technical_capability = _avg(
        row,
        [
            "technology_advantage_score",
            "bim_capability_score",
            "smart_site_capability_score",
            "digital_maturity_score",
            "quality_control_score",
        ],
    )
    management_capability = _avg(
        row,
        [
            "subcontract_management_score",
            "delivery_reliability_score",
            "cooperation_score",
            "safety_management_score",
        ],
    )
    financial_capacity = _avg(
        row,
        [
            "financing_capacity_score",
            "credit_rating_score",
            "shock_resilience_score",
        ],
    )

    return EnterpriseAgentProfile(
        agent_id=_clean(row.get("agent_id")),
        name=_clean(row.get("company_name")) or _clean(row.get("name")) or _clean(row.get("企业名称")),
        role=role,
        region=city,
        enterprise_type=_clean(row.get("main_business_type")) or _clean(row.get("role_type")) or role.lower(),
        qualification_level=_score(row, "qualification_level", 0.55),
        financial_capacity=financial_capacity,
        technical_capability=technical_capability,
        management_capability=management_capability,
        risk_preference=_score(row, "risk_appetite", _score(row, "bid_aggressiveness", 0.5)),
        collaboration_preference=_score(row, "cooperation_preference", _score(row, "joint_venture_preference", 0.5)),
        cross_region_experience=_avg(
            row,
            ["cross_city_operation_score", "cross_border_operation_score", "gba_integration_score"],
            0.45,
        ),
        policy_adaptability=_avg(
            row,
            ["compliance_score", "green_construction_score", "carbon_management_score", "innovation_orientation_score"],
            0.55,
        ),
        design_capability=_avg(
            row,
            ["technology_advantage_score", "innovation_orientation_score", "bim_capability_score", "quality_orientation_score"],
            0.5,
        ),
        cost_estimation_capability=_avg(
            row,
            ["cost_advantage_score", "quality_control_score", "compliance_score", "delivery_reliability_score"],
            0.5,
        ),
        construction_capability=_avg(
            row,
            ["equipment_capacity_score", "delivery_reliability_score", "technology_advantage_score", "resource_advantage_score"],
            0.5,
        ),
        safety_management_capability=_score(row, "safety_management_score", 0.5),
        quality_management_capability=_avg(row, ["quality_control_score", "quality_orientation_score"], 0.5),
        supervision_capability=_avg(
            row,
            ["quality_control_score", "safety_management_score", "compliance_score", "technology_advantage_score"],
            0.5,
        ),
        supply_reliability=_avg(
            row,
            ["delivery_reliability_score", "shock_resilience_score", "resource_advantage_score"],
            0.5,
        ),
        material_quality=_avg(row, ["quality_control_score", "brand_advantage_score", "green_construction_score"], 0.5),
        payment_reliability=(0.40 * default_risk_factor + 0.30 * cash_reserve_factor + 0.30 * payment_cycle_factor),
        decision_speed=_avg(row, ["delivery_reliability_score", "cooperation_score", "digital_maturity_score"], 0.5),
        total_resource_capacity=total_resource_capacity,
        occupied_resource=0.0,
        active_regions=operation_regions,
        preferred_partners=[],
        semantic_memory={
            "batch_id": _clean(row.get("batch_id")),
            "agent_type": _clean(row.get("agent_type")),
            "is_synthetic": _bool(row, "is_synthetic"),
            "role_type": _clean(row.get("role_type")),
            "enterprise_scale": _clean(row.get("enterprise_scale")),
            "source_ids": _clean(row.get("source_ids")),
            "source_confidence_score": _float(row, "source_confidence_score", 0.0),
            "notes": _clean(row.get("notes")),
        },
        episodic_memory=[],
    )


def build_agent_database(csv_path: Path = DEFAULT_AGENT_CSV, db_path: Path = DEFAULT_AGENT_DB) -> Path:
    if not csv_path.exists():
        raise FileNotFoundError(f"Agent CSV not found: {csv_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = db_path.with_suffix(".tmp.sqlite")
    if temp_path.exists():
        temp_path.unlink()
    conn = sqlite3.connect(temp_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE agents (
                agent_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                region TEXT NOT NULL,
                status TEXT NOT NULL,
                agent_type TEXT NOT NULL,
                role_type TEXT NOT NULL,
                enterprise_scale TEXT NOT NULL,
                company_name_norm TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX idx_agents_role ON agents(role)")
        conn.execute("CREATE INDEX idx_agents_region ON agents(region)")
        conn.execute("CREATE INDEX idx_agents_status ON agents(status)")
        conn.execute("CREATE INDEX idx_agents_type ON agents(agent_type)")
        conn.execute("CREATE INDEX idx_agents_role_type ON agents(role_type)")
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = []
            for row in reader:
                summary = summarize_agent(row)
                payload = dict(row)
                payload.update(summary)
                rows.append(
                    (
                        summary["agent_id"],
                        summary["name"],
                        summary["role"],
                        summary["region"],
                        summary["status"],
                        summary["agent_type"],
                        summary["role_type"],
                        summary["enterprise_scale"],
                        _norm_name(summary["name"]),
                        json.dumps(payload, ensure_ascii=False),
                    )
                )
        conn.executemany(
            """
            INSERT INTO agents (
                agent_id, name, role, region, status, agent_type, role_type,
                enterprise_scale, company_name_norm, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        ensure_agent_cognitive_schema(conn)
        conn.commit()
    finally:
        conn.close()
    temp_path.replace(db_path)
    return db_path


def ensure_agent_database(csv_path: Path = DEFAULT_AGENT_CSV, db_path: Path = DEFAULT_AGENT_DB) -> Path:
    if not db_path.exists() or (csv_path.exists() and csv_path.stat().st_mtime > db_path.stat().st_mtime):
        return build_agent_database(csv_path, db_path)
    return db_path


def ensure_agent_cognitive_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_memory (
            memory_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            related_agent_id TEXT,
            related_project_id TEXT,
            city TEXT,
            event_type TEXT NOT NULL,
            content TEXT NOT NULL,
            sentiment REAL DEFAULT 0,
            importance_score REAL DEFAULT 0.5,
            decay_rate REAL DEFAULT 0.05,
            created_tick INTEGER DEFAULT 0,
            last_access_tick INTEGER DEFAULT 0,
            source_type TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_belief (
            belief_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            belief_type TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT,
            belief_value REAL NOT NULL,
            confidence REAL NOT NULL,
            evidence_count INTEGER NOT NULL,
            updated_tick INTEGER DEFAULT 0,
            explanation TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_strategy (
            agent_id TEXT PRIMARY KEY,
            primary_strategy TEXT NOT NULL,
            bidding_aggressiveness REAL NOT NULL,
            margin_protection_level REAL NOT NULL,
            cooperation_preference REAL NOT NULL,
            risk_tolerance REAL NOT NULL,
            innovation_preference REAL NOT NULL,
            regional_expansion_preference REAL NOT NULL,
            public_project_preference REAL NOT NULL,
            private_project_preference REAL NOT NULL,
            subcontracting_preference REAL NOT NULL,
            cash_preservation_level REAL NOT NULL,
            source_type TEXT NOT NULL,
            profile_7s TEXT NOT NULL,
            schein_culture TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_decision_trace (
            decision_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            project_id TEXT,
            tick INTEGER,
            stage TEXT,
            role TEXT,
            decision_type TEXT NOT NULL,
            selected_action TEXT,
            candidate_actions TEXT,
            available_actions TEXT,
            utility_score REAL,
            input_context TEXT,
            belief_snapshot TEXT,
            memory_used TEXT,
            memory_belief_used TEXT,
            strategy_used TEXT,
            camel_used INTEGER DEFAULT 0,
            fallback_used INTEGER DEFAULT 0,
            validation_result TEXT,
            decision_reason TEXT,
            model_provider TEXT,
            model_name TEXT,
            retry_info TEXT,
            error TEXT,
            explanation TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    _ensure_columns(
        conn,
        "agent_decision_trace",
        {
            "role": "TEXT",
            "available_actions": "TEXT",
            "input_context": "TEXT",
            "memory_belief_used": "TEXT",
            "decision_reason": "TEXT",
            "model_provider": "TEXT",
            "model_name": "TEXT",
            "retry_info": "TEXT",
            "error": "TEXT",
        },
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS simulation_tasks (
            task_id TEXT PRIMARY KEY,
            parent_task_id TEXT,
            project_id TEXT,
            agent_id TEXT,
            stage TEXT,
            task_type TEXT NOT NULL,
            content TEXT NOT NULL,
            state TEXT NOT NULL,
            result TEXT,
            created_tick INTEGER NOT NULL,
            completed_tick INTEGER,
            source TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_memory_agent ON agent_memory(agent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_belief_agent ON agent_belief(agent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_trace_agent ON agent_decision_trace(agent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_trace_project ON agent_decision_trace(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_simulation_tasks_project ON simulation_tasks(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_simulation_tasks_agent ON simulation_tasks(agent_id)")
    seed_missing_cognitive_state(conn)
    conn.commit()


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def seed_missing_cognitive_state(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT agent_id, payload
        FROM agents
        WHERE agent_id NOT IN (SELECT agent_id FROM agent_strategy)
        ORDER BY agent_id
        """
    ).fetchall()
    now = datetime.utcnow().replace(microsecond=0).isoformat()
    for row in rows:
        payload = json.loads(row["payload"])
        strategy = _strategy_from_payload(payload)
        conn.execute(
            """
            INSERT OR IGNORE INTO agent_strategy (
                agent_id, primary_strategy, bidding_aggressiveness, margin_protection_level,
                cooperation_preference, risk_tolerance, innovation_preference,
                regional_expansion_preference, public_project_preference, private_project_preference,
                subcontracting_preference, cash_preservation_level, source_type,
                profile_7s, schein_culture, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy["agent_id"],
                strategy["primary_strategy"],
                strategy["bidding_aggressiveness"],
                strategy["margin_protection_level"],
                strategy["cooperation_preference"],
                strategy["risk_tolerance"],
                strategy["innovation_preference"],
                strategy["regional_expansion_preference"],
                strategy["public_project_preference"],
                strategy["private_project_preference"],
                strategy["subcontracting_preference"],
                strategy["cash_preservation_level"],
                strategy["source_type"],
                json.dumps(strategy["profile_7s"], ensure_ascii=False),
                json.dumps(strategy["schein_culture"], ensure_ascii=False),
                now,
            ),
        )
        for belief in _beliefs_from_payload(payload):
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_belief (
                    belief_id, agent_id, belief_type, target_type, target_id, belief_value,
                    confidence, evidence_count, updated_tick, explanation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    belief["belief_id"],
                    belief["agent_id"],
                    belief["belief_type"],
                    belief["target_type"],
                    belief["target_id"],
                    belief["belief_value"],
                    belief["confidence"],
                    belief["evidence_count"],
                    belief["updated_tick"],
                    belief["explanation"],
                ),
            )
        for memory in _memories_from_payload(payload):
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_memory (
                    memory_id, agent_id, memory_type, related_agent_id, related_project_id,
                    city, event_type, content, sentiment, importance_score, decay_rate,
                    created_tick, last_access_tick, source_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory["memory_id"],
                    memory["agent_id"],
                    memory["memory_type"],
                    memory["related_agent_id"],
                    memory["related_project_id"],
                    memory["city"],
                    memory["event_type"],
                    memory["content"],
                    memory["sentiment"],
                    memory["importance_score"],
                    memory["decay_rate"],
                    memory["created_tick"],
                    memory["last_access_tick"],
                    memory["source_type"],
                ),
            )


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    for key in list(payload):
        if key in JSON_COLUMNS and isinstance(payload[key], str) and payload[key]:
            try:
                payload[key] = json.loads(payload[key])
            except json.JSONDecodeError:
                pass
    for key in ["camel_used", "fallback_used"]:
        if key in payload:
            payload[key] = bool(payload[key])
    return payload


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}"


def _prepare_memory_payload(memory: dict[str, Any]) -> dict[str, Any]:
    payload = dict(memory)
    payload.setdefault("memory_id", _stable_id("MEM", payload))
    payload.setdefault("related_agent_id", None)
    payload.setdefault("related_project_id", None)
    payload.setdefault("city", "")
    payload.setdefault("sentiment", "neutral")
    payload.setdefault("importance_score", 0.5)
    payload.setdefault("decay_rate", 0.03)
    payload.setdefault("created_tick", 0)
    payload.setdefault("last_access_tick", payload.get("created_tick", 0))
    payload.setdefault("source_type", "simulation_event")
    return payload


def _prepare_belief_payload(belief: dict[str, Any]) -> dict[str, Any]:
    payload = dict(belief)
    payload.setdefault(
        "belief_id",
        _stable_id(
            "BEL",
            {
                "agent_id": payload.get("agent_id"),
                "belief_type": payload.get("belief_type"),
                "target_type": payload.get("target_type"),
                "target_id": payload.get("target_id"),
            },
        ),
    )
    payload.setdefault("target_type", "system")
    payload.setdefault("target_id", "")
    payload.setdefault("belief_value", 0.5)
    payload.setdefault("confidence", 0.5)
    payload.setdefault("evidence_count", 1)
    payload.setdefault("updated_tick", 0)
    payload.setdefault("explanation", "")
    return payload


class AgentDatabase:
    def __init__(self, db_path: Path = DEFAULT_AGENT_DB, csv_path: Path = DEFAULT_AGENT_CSV) -> None:
        self.db_path = db_path
        self.csv_path = csv_path
        self._schema_ready = False
        self._connections: dict[int, sqlite3.Connection] = {}
        self._connect_lock = threading.RLock()
        self._memory_cache: dict[tuple[str, int, str | None], list[dict[str, Any]]] = {}
        self._belief_cache: dict[str, list[dict[str, Any]]] = {}
        self._strategy_cache: dict[str, dict[str, Any] | None] = {}

    def _connect(self) -> sqlite3.Connection:
        thread_id = threading.get_ident()
        conn = self._connections.get(thread_id)
        if conn is None:
            with self._connect_lock:
                conn = self._connections.get(thread_id)
                if conn is not None:
                    return conn
                ensure_agent_database(self.csv_path, self.db_path)
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                if not self._schema_ready:
                    ensure_agent_cognitive_schema(conn)
                    self._schema_ready = True
                self._connections[thread_id] = conn
        return conn

    def _invalidate_agent_cache(self, agent_ids: Iterable[str]) -> None:
        ids = {agent_id for agent_id in agent_ids if agent_id}
        if not ids:
            return
        self._memory_cache = {
            key: value
            for key, value in self._memory_cache.items()
            if key[0] not in ids
        }
        for agent_id in ids:
            self._belief_cache.pop(agent_id, None)
            self._strategy_cache.pop(agent_id, None)

    def list_agents(
        self,
        agent_type: str | None = None,
        region: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if agent_type and agent_type.lower() not in {"all", "all types"}:
            normalized = agent_type.strip().lower()
            role_map = {
                "developer": ["Owner"],
                "owner": ["Owner"],
                "designer": ["Architect"],
                "design": ["Architect"],
                "architect": ["Architect"],
                "contractor": ["Contractor"],
                "supplier": ["Supplier"],
                "consultant": ["Consultant", "QS"],
                "qs": ["QS"],
            }
            roles = role_map.get(normalized, [agent_type])
            placeholders = ",".join("?" for _ in roles)
            clauses.append(f"role IN ({placeholders})")
            params.extend(roles)
        if region and region.lower() not in {"all", "all regions"}:
            clauses.append("region = ?")
            params.append(region)
        if status and status.lower() not in {"all", "all status"}:
            clauses.append("status = ?")
            params.append(status)
        if keyword:
            needle = f"%{keyword.strip().lower()}%"
            clauses.append("(lower(name) LIKE ? OR lower(role) LIKE ? OR lower(region) LIKE ? OR lower(role_type) LIKE ?)")
            params.extend([needle, needle, needle, needle])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT payload FROM agents {where} ORDER BY agent_id", params).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def list_agent_profiles(
        self,
        roles: list[str] | None = None,
        regions: list[str] | None = None,
        source_types: list[str] | None = None,
        limit: int | None = None,
        random_seed: int | None = None,
    ) -> list[EnterpriseAgentProfile]:
        payloads = self.list_agents()
        if roles:
            role_set = {role.lower() for role in roles}
            payloads = [payload for payload in payloads if _clean(payload.get("role")).lower() in role_set]
        if regions:
            region_set = {_normalize_city(region).lower() for region in regions}
            payloads = [
                payload
                for payload in payloads
                if _normalize_city(_clean(payload.get("region"))).lower() in region_set
            ]
        if source_types:
            source_set = {source_type.lower() for source_type in source_types}
            payloads = [
                payload
                for payload in payloads
                if _clean(payload.get("agent_type")).lower() in source_set
                or _clean(payload.get("data_source_type")).lower() in source_set
            ]
        payloads = self._limit_payloads(payloads, limit, random_seed)
        return [PROFILE_MAPPER.to_profile(payload) for payload in payloads]

    def _limit_payloads(
        self,
        payloads: list[dict[str, Any]],
        limit: int | None,
        random_seed: int | None,
    ) -> list[dict[str, Any]]:
        if limit is None or limit <= 0 or limit >= len(payloads):
            return payloads
        return self._balanced_cluster_payloads(payloads, limit)

    def _balanced_cluster_payloads(self, payloads: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for payload in payloads:
            city = _normalize_city(_clean(payload.get("region") or payload.get("city"))) or "GBA"
            role_class = self._role_class(payload)
            buckets.setdefault(city, {}).setdefault(role_class, []).append(payload)

        for role_buckets in buckets.values():
            for role_payloads in role_buckets.values():
                role_payloads.sort(key=self._payload_selection_key)

        city_targets = self._city_targets_for_payloads(list(buckets), limit)
        role_targets = {
            city: self._role_targets_for_city(city, city_limit)
            for city, city_limit in city_targets.items()
        }
        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()
        city_seed_counts: Counter[str] = Counter()
        for city, targets in role_targets.items():
            role_buckets = buckets.get(city, {})
            for role_class, target in targets.items():
                real_bucket = [
                    payload
                    for payload in role_buckets.get(role_class, [])
                    if SOURCE_PRIORITY.get(_clean(payload.get("agent_type")).lower(), 3) < SOURCE_PRIORITY["synthetic"]
                ]
                real_target = target + max(2, round(target * 0.20))
                self._take_from_bucket(real_bucket, real_target, selected, selected_ids, limit)

        city_counts = Counter(
            _normalize_city(_clean(payload.get("region") or payload.get("city"))) or "GBA"
            for payload in selected
        )
        city_seed_counts = city_counts
        city_fill_weights = {
            city: max(0, target - city_counts.get(city, 0))
            for city, target in city_targets.items()
        }
        remaining_limit = limit - len(selected)
        city_targets = self._integer_targets(city_fill_weights, remaining_limit)
        role_targets = {
            city: self._role_fill_targets_for_city(city, city_limit, selected, role_targets)
            for city, city_limit in city_targets.items()
        }

        for city, targets in role_targets.items():
            role_buckets = buckets.get(city, {})
            for role_class, target in targets.items():
                self._take_from_bucket(
                    role_buckets.get(role_class, []),
                    target,
                    selected,
                    selected_ids,
                    limit,
                )

        for city, target in city_targets.items():
            if len(selected) >= limit:
                break
            city_selected = sum(
                1
                for payload in selected
                if _normalize_city(_clean(payload.get("region") or payload.get("city"))) == city
            ) - city_seed_counts.get(city, 0)
            if city_selected >= target:
                continue
            remaining = [
                payload
                for role_payloads in buckets.get(city, {}).values()
                for payload in role_payloads
                if payload.get("agent_id") not in selected_ids
            ]
            remaining.sort(key=self._payload_selection_key)
            self._take_from_bucket(remaining, target - city_selected, selected, selected_ids, limit)

        remainder = [payload for payload in payloads if payload.get("agent_id") not in selected_ids]
        remainder.sort(
            key=lambda payload: (
                SOURCE_PRIORITY.get(_clean(payload.get("agent_type")).lower(), 3),
                -self._payload_quality_score(payload),
                _normalize_city(_clean(payload.get("region") or payload.get("city"))),
                self._role_class(payload),
                _clean(payload.get("agent_id")),
            )
        )
        self._take_from_bucket(remainder, limit - len(selected), selected, selected_ids, limit)
        return selected

    def _role_fill_targets_for_city(
        self,
        city: str,
        city_limit: int,
        selected: list[dict[str, Any]],
        desired_role_targets: dict[str, dict[str, int]],
    ) -> dict[str, int]:
        if city_limit <= 0:
            return {}
        role_counts = Counter(
            self._role_class(payload)
            for payload in selected
            if (_normalize_city(_clean(payload.get("region") or payload.get("city"))) or "GBA") == city
        )
        role_needs = {
            role_class: max(0, target - role_counts.get(role_class, 0))
            for role_class, target in desired_role_targets.get(city, {}).items()
        }
        if not any(role_needs.values()):
            role_needs = GBA_TEST_CLUSTER_ROLE_MIX.get(city, DEFAULT_ROLE_CLASS_MIX)
        return self._integer_targets(role_needs, city_limit)

    @staticmethod
    def _take_from_bucket(
        bucket: list[dict[str, Any]],
        target: int,
        selected: list[dict[str, Any]],
        selected_ids: set[str],
        limit: int,
    ) -> None:
        for payload in bucket:
            if len(selected) >= limit or target <= 0:
                break
            agent_id = payload.get("agent_id")
            if agent_id in selected_ids:
                continue
            selected.append(payload)
            selected_ids.add(agent_id)
            target -= 1

    @staticmethod
    def _role_class(payload: dict[str, Any]) -> str:
        return ROLE_CLASS_BY_DISPLAY_ROLE.get(_clean(payload.get("role")), "consultant")

    @staticmethod
    def _payload_quality_score(payload: dict[str, Any]) -> float:
        fields = [
            "source_confidence_score",
            "reputation_score",
            "delivery_reliability_score",
            "quality_control_score",
            "compliance_score",
            "cross_city_operation_score",
            "gba_integration_score",
        ]
        return _avg(payload, fields, 0.5)

    def _payload_selection_key(self, payload: dict[str, Any]) -> tuple:
        return (
            SOURCE_PRIORITY.get(_clean(payload.get("agent_type")).lower(), 3),
            -self._payload_quality_score(payload),
            _clean(payload.get("agent_id")),
        )

    @staticmethod
    def _city_targets_for_payloads(cities: list[str], limit: int) -> dict[str, int]:
        available_cities = [city for city in GBA_TEST_CLUSTER_CITY_TARGETS if city in cities]
        additional_cities = sorted(city for city in cities if city not in GBA_TEST_CLUSTER_CITY_TARGETS)
        ordered_cities = available_cities + additional_cities
        if not ordered_cities:
            return {}
        base_weights = {
            city: GBA_TEST_CLUSTER_CITY_TARGETS.get(city, 50)
            for city in ordered_cities
        }
        return AgentDatabase._integer_targets(base_weights, limit)

    @staticmethod
    def _role_targets_for_city(city: str, limit: int) -> dict[str, int]:
        mix = GBA_TEST_CLUSTER_ROLE_MIX.get(city, DEFAULT_ROLE_CLASS_MIX)
        return AgentDatabase._integer_targets(mix, limit)

    @staticmethod
    def _integer_targets(weights: dict[str, float], limit: int) -> dict[str, int]:
        total_weight = sum(max(0.0, float(value)) for value in weights.values())
        if total_weight <= 0:
            equal = limit // max(1, len(weights))
            targets = {key: equal for key in weights}
            for key in list(targets)[: limit - sum(targets.values())]:
                targets[key] += 1
            return targets
        raw = {
            key: (max(0.0, float(weight)) / total_weight) * limit
            for key, weight in weights.items()
        }
        targets = {key: int(value) for key, value in raw.items()}
        remainder = limit - sum(targets.values())
        for key in sorted(raw, key=lambda item: (raw[item] - targets[item], raw[item]), reverse=True)[:remainder]:
            targets[key] += 1
        return targets

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM agents").fetchone()
        return int(row["total"])

    def get_agent_memory(self, agent_id: str, limit: int = 20, memory_type: str | None = None) -> list[dict[str, Any]]:
        cache_key = (agent_id, limit, memory_type)
        if cache_key in self._memory_cache:
            return [dict(row) for row in self._memory_cache[cache_key]]
        clauses = ["agent_id = ?"]
        params: list[Any] = [agent_id]
        if memory_type:
            clauses.append("memory_type = ?")
            params.append(memory_type)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM agent_memory
                WHERE {' AND '.join(clauses)}
                ORDER BY importance_score DESC, created_tick DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        decoded = [_decode_row(row) for row in rows]
        self._memory_cache[cache_key] = [dict(row) for row in decoded]
        return decoded

    def get_agent_beliefs(self, agent_id: str) -> list[dict[str, Any]]:
        if agent_id in self._belief_cache:
            return [dict(row) for row in self._belief_cache[agent_id]]
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_belief WHERE agent_id = ? ORDER BY belief_type",
                (agent_id,),
            ).fetchall()
        decoded = [_decode_row(row) for row in rows]
        self._belief_cache[agent_id] = [dict(row) for row in decoded]
        return decoded

    def get_agent_strategy(self, agent_id: str) -> dict[str, Any] | None:
        if agent_id in self._strategy_cache:
            cached = self._strategy_cache[agent_id]
            return dict(cached) if cached else None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM agent_strategy WHERE agent_id = ?", (agent_id,)).fetchone()
        decoded = _decode_row(row) if row else None
        self._strategy_cache[agent_id] = dict(decoded) if decoded else None
        return decoded

    def get_agent_decision_trace(self, agent_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM agent_decision_trace
                WHERE agent_id = ?
                ORDER BY COALESCE(tick, -1) DESC, created_at DESC
                LIMIT ?
                """,
                (agent_id, limit),
            ).fetchall()
        return [_decode_row(row) for row in rows]

    def record_agent_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        payload = _prepare_memory_payload(memory)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_memory (
                    memory_id, agent_id, memory_type, related_agent_id, related_project_id,
                    city, event_type, content, sentiment, importance_score, decay_rate,
                    created_tick, last_access_tick, source_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get("memory_id"),
                    payload.get("agent_id"),
                    payload.get("memory_type"),
                    payload.get("related_agent_id"),
                    payload.get("related_project_id"),
                    payload.get("city"),
                    payload.get("event_type"),
                    payload.get("content"),
                    payload.get("sentiment"),
                    payload.get("importance_score"),
                    payload.get("decay_rate"),
                    payload.get("created_tick"),
                    payload.get("last_access_tick"),
                    payload.get("source_type"),
                ),
            )
            conn.commit()
        self._invalidate_agent_cache([payload.get("agent_id")])
        return {**memory, "memory_id": payload["memory_id"]}

    def upsert_agent_belief(self, belief: dict[str, Any]) -> dict[str, Any]:
        payload = _prepare_belief_payload(belief)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT evidence_count FROM agent_belief WHERE belief_id = ?",
                (payload["belief_id"],),
            ).fetchone()
            evidence_count = int(existing["evidence_count"]) + int(payload.get("evidence_count", 1)) if existing else int(payload.get("evidence_count", 1))
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_belief (
                    belief_id, agent_id, belief_type, target_type, target_id,
                    belief_value, confidence, evidence_count, updated_tick, explanation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get("belief_id"),
                    payload.get("agent_id"),
                    payload.get("belief_type"),
                    payload.get("target_type"),
                    payload.get("target_id"),
                    payload.get("belief_value"),
                    payload.get("confidence"),
                    evidence_count,
                    payload.get("updated_tick"),
                    payload.get("explanation"),
                ),
            )
            conn.commit()
        self._invalidate_agent_cache([payload.get("agent_id")])
        return {**belief, "belief_id": payload["belief_id"], "evidence_count": evidence_count}

    def record_cognitive_event(
        self,
        memories: list[dict[str, Any]],
        beliefs: list[dict[str, Any]],
    ) -> dict[str, int]:
        memory_payloads = [_prepare_memory_payload(memory) for memory in memories]
        belief_payloads = [_prepare_belief_payload(belief) for belief in beliefs]
        if not memory_payloads and not belief_payloads:
            return {"memories": 0, "beliefs": 0}

        with self._connect() as conn:
            if memory_payloads:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO agent_memory (
                        memory_id, agent_id, memory_type, related_agent_id, related_project_id,
                        city, event_type, content, sentiment, importance_score, decay_rate,
                        created_tick, last_access_tick, source_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            payload.get("memory_id"),
                            payload.get("agent_id"),
                            payload.get("memory_type"),
                            payload.get("related_agent_id"),
                            payload.get("related_project_id"),
                            payload.get("city"),
                            payload.get("event_type"),
                            payload.get("content"),
                            payload.get("sentiment"),
                            payload.get("importance_score"),
                            payload.get("decay_rate"),
                            payload.get("created_tick"),
                            payload.get("last_access_tick"),
                            payload.get("source_type"),
                        )
                        for payload in memory_payloads
                    ],
                )

            existing_counts: dict[str, int] = {}
            if belief_payloads:
                belief_ids = [payload["belief_id"] for payload in belief_payloads]
                placeholders = ",".join("?" for _ in belief_ids)
                rows = conn.execute(
                    f"SELECT belief_id, evidence_count FROM agent_belief WHERE belief_id IN ({placeholders})",
                    belief_ids,
                ).fetchall()
                existing_counts = {row["belief_id"]: int(row["evidence_count"]) for row in rows}
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO agent_belief (
                        belief_id, agent_id, belief_type, target_type, target_id,
                        belief_value, confidence, evidence_count, updated_tick, explanation
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            payload.get("belief_id"),
                            payload.get("agent_id"),
                            payload.get("belief_type"),
                            payload.get("target_type"),
                            payload.get("target_id"),
                            payload.get("belief_value"),
                            payload.get("confidence"),
                            existing_counts.get(payload["belief_id"], 0) + int(payload.get("evidence_count", 1)),
                            payload.get("updated_tick"),
                            payload.get("explanation"),
                        )
                        for payload in belief_payloads
                    ],
                )
            conn.commit()
        self._invalidate_agent_cache(
            [
                *(payload.get("agent_id") for payload in memory_payloads),
                *(payload.get("agent_id") for payload in belief_payloads),
            ]
        )
        return {"memories": len(memory_payloads), "beliefs": len(belief_payloads)}

    def record_decision_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        payload = dict(trace)
        payload.setdefault("decision_id", _stable_id("DEC", payload))
        payload.setdefault("created_at", datetime.utcnow().replace(microsecond=0).isoformat())
        for key in JSON_COLUMNS:
            if key in payload and not isinstance(payload[key], str):
                payload[key] = json.dumps(payload[key], ensure_ascii=False, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_decision_trace (
                    decision_id, agent_id, project_id, tick, stage, role, decision_type, selected_action,
                    candidate_actions, available_actions, utility_score, input_context, belief_snapshot,
                    memory_used, memory_belief_used, strategy_used, camel_used, fallback_used,
                    validation_result, decision_reason, model_provider, model_name, retry_info, error,
                    explanation, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get("decision_id"),
                    payload.get("agent_id"),
                    payload.get("project_id"),
                    payload.get("tick"),
                    payload.get("stage"),
                    payload.get("role"),
                    payload.get("decision_type") or "agent_decision",
                    payload.get("selected_action"),
                    payload.get("candidate_actions"),
                    payload.get("available_actions"),
                    payload.get("utility_score"),
                    payload.get("input_context"),
                    payload.get("belief_snapshot"),
                    payload.get("memory_used"),
                    payload.get("memory_belief_used"),
                    payload.get("strategy_used"),
                    1 if payload.get("camel_used") else 0,
                    1 if payload.get("fallback_used") else 0,
                    payload.get("validation_result"),
                    payload.get("decision_reason"),
                    payload.get("model_provider"),
                    payload.get("model_name"),
                    payload.get("retry_info"),
                    payload.get("error"),
                    payload.get("explanation"),
                    payload.get("created_at"),
                ),
            )
            conn.commit()
        return {**trace, "decision_id": payload["decision_id"], "created_at": payload["created_at"]}

    def record_simulation_task(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = dict(task)
        payload.setdefault("task_id", _stable_id("TASK", payload))
        if "result" in payload and not isinstance(payload["result"], str):
            payload["result"] = json.dumps(payload["result"], ensure_ascii=False, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO simulation_tasks (
                    task_id, parent_task_id, project_id, agent_id, stage, task_type,
                    content, state, result, created_tick, completed_tick, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get("task_id"),
                    payload.get("parent_task_id"),
                    payload.get("project_id"),
                    payload.get("agent_id"),
                    payload.get("stage"),
                    payload.get("task_type"),
                    payload.get("content"),
                    payload.get("state", "DONE"),
                    payload.get("result"),
                    payload.get("created_tick", 0),
                    payload.get("completed_tick"),
                    payload.get("source", "simulation_engine"),
                ),
            )
            conn.commit()
        return {**task, "task_id": payload["task_id"]}

    def list_simulation_tasks(
        self,
        project_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM simulation_tasks
                {where}
                ORDER BY created_tick DESC, task_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_decode_row(row) for row in rows]


agent_database = AgentDatabase()
