from copy import deepcopy
from typing import Dict, Optional

from gba_construction_sim.backend.models.frontend_dto import AgentClusterDTO, AgentClusterListItemDTO
from gba_construction_sim.backend.services.mock_catalog import CITY_COORDS, CLUSTERS


class ClusterService:
    def list_clusters(
        self,
        city: Optional[str] = None,
        cluster_type: Optional[str] = None,
        structure: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> list[Dict]:
        items = CLUSTERS
        if city and city.lower() not in {"all", "all cities"}:
            items = [item for item in items if item["region"].lower() == city.lower()]
        if cluster_type and cluster_type.lower() not in {"all", "all types"}:
            items = [item for item in items if item["cluster_type"].lower() == cluster_type.lower()]
        if structure and structure.lower() not in {"all", "all structures"}:
            items = [item for item in items if structure.lower() in item["structure_tag"].lower()]
        if keyword:
            needle = keyword.lower()
            items = [item for item in items if needle in item["name"].lower() or needle in item["region"].lower()]
        return [AgentClusterListItemDTO(**item).dict() for item in items]

    def get_cluster(self, cluster_id: str) -> Dict:
        base = deepcopy(next((item for item in CLUSTERS if item["cluster_id"] == cluster_id), CLUSTERS[0]))
        coverage = base.get(
            "coverage",
            ["Hong Kong", "Shenzhen", "Guangzhou", "Macau", "Zhuhai", "Foshan", "Dongguan"],
        )
        detail = {
            "cluster_id": base["cluster_id"],
            "name": base["name"],
            "description": base.get(
                "description",
                "A simulation-ready enterprise cluster covering major construction firms, developers, consultants, and suppliers across the Greater Bay Area.",
            ),
            "city_region": base["region"],
            "cluster_size": base["agent_count"],
            "dominant_type": "Mixed",
            "market_structure": base["structure_tag"],
            "primary_scope": "Building & Infrastructure",
            "coverage": coverage,
            "composition": base.get("composition", {
                "contractors": 46,
                "consultants": 16,
                "suppliers": 12,
                "developers": 14,
                "others": 12,
            }),
            "capacity_radar": {
                "capacity": 4.5,
                "diversity": 4.4 if base["agent_count"] >= 1000 else 4.0,
                "coordination": 4.2,
                "market_reach": 4.1,
                "growth_potential": 4.6,
            },
            "quick_presets": [
                "Focus on Shenzhen",
                "Add Hong Kong Firms",
                "Developer-Led",
                "Contractor-Led",
                "Cross-Border Focus",
            ],
            "recent_usage": [
                {"usage_id": "U001", "date": "2025-05-08", "title": "Used in GBA integration scenario"},
                {"usage_id": "U002", "date": "2025-04-20", "title": "Applied in policy comparison simulation"},
            ],
            "notes": [
                "Designed for rapid scenario setup across the Greater Bay Area.",
                "Supports city coverage, enterprise types, and market structure customization.",
                "Recommended for regional policy and cross-border collaboration simulations.",
            ],
            "map_preview": {
                "nodes": self._map_nodes(coverage),
                "links": self._map_links(),
            },
            "default_output": {
                "enterprise_agent_count": base["agent_count"],
                "support_regulator_count": base.get("source_mix", {}).get("support_regulator", 0),
                "total_agent_count": base["agent_count"] + base.get("source_mix", {}).get("support_regulator", 0),
                "regional_multi_city_structure": True,
                "simulation_ready": base["status"] == "ready",
                "supports_custom_adjustment": True,
                "city_mix": base.get("city_mix", {}),
                "role_mix_by_city": base.get("role_mix_by_city", {}),
                "role_mix_basis": base.get("role_mix_basis", ""),
                "source_mix": base.get("source_mix", {}),
                "recommended_run": base.get("recommended_run", {}),
            },
        }
        return AgentClusterDTO(**detail).dict()

    def duplicate_cluster(self, cluster_id: str) -> Dict:
        base = deepcopy(self.get_cluster(cluster_id))
        base["cluster_id"] = f"{cluster_id}-COPY"
        base["name"] = f"{base['name']} Copy"
        return base

    def use_in_simulation(self, cluster_id: str) -> Dict:
        cluster = self.get_cluster(cluster_id)
        return {
            "cluster_id": cluster_id,
            "agent_ids": ["O001", "A001", "Q001", "C001", "C002", "C003", "S001", "G001"],
            "agent_count": cluster["cluster_size"],
            "enterprise_agent_count": cluster["cluster_size"],
            "support_regulator_count": cluster["default_output"].get("support_regulator_count", 0),
            "total_agent_count": cluster["default_output"].get("total_agent_count", cluster["cluster_size"]),
            "agent_source": "database",
            "agent_source_types": [],
            "recommended_run": cluster["default_output"].get("recommended_run", {}),
            "region_scope": cluster["coverage"],
            "ready_for_simulation": cluster["default_output"]["simulation_ready"],
        }

    def _map_nodes(self, cities: Optional[list[str]] = None) -> list[Dict]:
        cities = cities or ["Guangzhou", "Foshan", "Dongguan", "Shenzhen", "Hong Kong", "Macau", "Zhuhai"]
        return [
            {
                "node_id": city,
                "name": city,
                "city": city,
                "latitude": CITY_COORDS[city]["latitude"],
                "longitude": CITY_COORDS[city]["longitude"],
                "value": 0.75 if city in {"Shenzhen", "Guangzhou", "Hong Kong"} else 0.55,
            }
            for city in cities
        ]

    def _map_links(self) -> list[Dict]:
        pairs = [
            ("Guangzhou", "Shenzhen"),
            ("Foshan", "Guangzhou"),
            ("Dongguan", "Shenzhen"),
            ("Shenzhen", "Hong Kong"),
            ("Macau", "Zhuhai"),
            ("Zhuhai", "Shenzhen"),
        ]
        return [
            {
                "link_id": f"CLINK{index:03d}",
                "source_id": source,
                "target_id": target,
                "strength": 0.62 + index * 0.04,
                "cross_city": source != target,
            }
            for index, (source, target) in enumerate(pairs, start=1)
        ]


cluster_service = ClusterService()
