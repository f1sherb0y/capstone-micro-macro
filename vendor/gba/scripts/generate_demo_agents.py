"""Generate deterministic synthetic profiles for public integration tests."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "gba_construction_agents_batch001.csv"

CITIES = [
    "Guangzhou",
    "Shenzhen",
    "Zhuhai",
    "Foshan",
    "Huizhou",
    "Dongguan",
    "Zhongshan",
    "Jiangmen",
    "Zhaoqing",
    "Hong Kong",
    "Macau",
]

ROLES = [
    ("developer_owner", "Owner", "developer"),
    ("design_survey_architecture", "Architect", "design_consultancy"),
    ("consulting_supervision_cost", "QS", "cost_consultancy"),
    ("general_contractor", "Contractor", "construction"),
    ("material_equipment_supplier", "Supplier", "supply"),
]


def score(role_index: int, city_index: int, sample_index: int, offset: int) -> str:
    value = 0.56 + ((role_index * 7 + city_index * 3 + sample_index + offset) % 31) / 100
    return f"{min(value, 0.90):.2f}"


def generate() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "batch_id",
        "agent_id",
        "company_name",
        "role_type",
        "role",
        "city",
        "region",
        "enterprise_scale",
        "enterprise_type",
        "agent_type",
        "data_source_type",
        "is_synthetic",
        "main_business_type",
        "operation_cities",
        "qualification_level",
        "financing_capacity_score",
        "credit_rating_score",
        "technology_advantage_score",
        "management_capability_score",
        "collaboration_preference_score",
        "risk_preference_score",
        "policy_adaptability_score",
        "total_resource_capacity",
    ]
    rows = []
    for role_index, (role_type, role, enterprise_type) in enumerate(ROLES, start=1):
        for city_index, city in enumerate(CITIES, start=1):
            for sample_index in range(1, 25):
                rows.append(
                    {
                        "batch_id": "PUBLIC-DEMO-001",
                        "agent_id": f"SYN-{city_index:02d}-{sample_index:03d}-{role_index:02d}-{role.upper()}",
                        "company_name": f"Synthetic {city} {role} {sample_index:03d}",
                        "role_type": role_type,
                        "role": role,
                        "city": city,
                        "region": city,
                        "enterprise_scale": ["small", "medium", "large"][(city_index + role_index + sample_index) % 3],
                        "enterprise_type": enterprise_type,
                        "agent_type": "synthetic",
                        "data_source_type": "generated_public_demo",
                        "is_synthetic": "true",
                        "main_business_type": enterprise_type,
                        "operation_cities": f"{city};Shenzhen;Guangzhou",
                        "qualification_level": ["B", "A", "A+"][(city_index + role_index + sample_index) % 3],
                        "financing_capacity_score": score(role_index, city_index, sample_index, 1),
                        "credit_rating_score": score(role_index, city_index, sample_index, 5),
                        "technology_advantage_score": score(role_index, city_index, sample_index, 9),
                        "management_capability_score": score(role_index, city_index, sample_index, 13),
                        "collaboration_preference_score": score(role_index, city_index, sample_index, 17),
                        "risk_preference_score": score(role_index, city_index, sample_index, 21),
                        "policy_adaptability_score": score(role_index, city_index, sample_index, 25),
                        "total_resource_capacity": str(2 + ((city_index + role_index + sample_index) % 4)),
                    }
                )
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    count = generate()
    print(f"Generated {count} synthetic profiles at {OUTPUT}")
