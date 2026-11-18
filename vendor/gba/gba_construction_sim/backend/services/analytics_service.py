from collections import Counter
from statistics import mean
from typing import Dict, Optional

from gba_construction_sim.backend.models.frontend_dto import AnalyticsDashboardDTO
from gba_construction_sim.backend.services.mock_catalog import CITY_COORDS
from gba_construction_sim.backend.services.simulation_service import simulation_runtime_service


class AnalyticsService:
    def dashboard(self, simulation_id: Optional[str] = None, scenario: str = "green_growth_2030") -> Dict:
        engine = simulation_runtime_service.get_engine(simulation_id) if simulation_id else simulation_runtime_service.ensure_demo_simulation()
        runtime_state = simulation_runtime_service.runtime_state(engine.simulation_id, engine.current_tick)
        runtime_map = runtime_state.get("map", {})
        runtime_kpis = runtime_state.get("kpis", {})
        project_metrics = engine.metrics.dict().get("project_metrics", {})
        network_metrics = engine.metrics.dict().get("network_metrics", {})
        project_rows = runtime_map.get("projects", [])
        enterprise_rows = runtime_map.get("enterprises", [])
        collaboration_links = runtime_map.get("collaboration_links", [])
        resource_flows = runtime_map.get("resource_flows", [])
        cross_city_links = len([link for link in collaboration_links if link.get("cross_city")])
        cross_region_share = round(
            (cross_city_links / max(1, len(collaboration_links))) * 100,
            1,
        ) if collaboration_links else round((network_metrics.get("cross_region_edge_share", 0.0) or 0.0) * 100, 1)
        policy_impact = round(82.7 - (project_metrics.get("project_failure_risk_average", 0.0) or 0) * 10, 1)
        workflow = getattr(engine, "workflow_config", {}) or {}
        total_ticks = int((workflow.get("execution_logic") or {}).get("total_ticks") or engine.ticks)
        visible_enterprise_count = len(enterprise_rows)
        enterprise_pool_count = len(
            [
                agent
                for agent in engine.agents.values()
                if str(getattr(agent, "role", "") or "").lower() != "government"
            ]
        )
        engaged_firm_count = len(
            {
                participant.get("agent_id")
                for project in project_rows
                for participant in project.get("participants", [])
                if participant.get("agent_id")
            }
        ) or len([agent for agent in enterprise_rows if str(agent.get("status")) != "free"])
        city_counts = Counter(project.get("city", "") for project in project_rows if project.get("city"))
        top_cities = self._top_affected_cities(city_counts, project_rows)
        dashboard = {
            "simulation_id": engine.simulation_id,
            "scenario_name": scenario.replace("_", " ").title(),
            "time_range": f"Month 0 - Month {total_ticks}",
            "workflow": workflow,
            "kpis": {
                "active_projects": runtime_kpis.get("active_projects", len(project_rows)),
                "project_count": runtime_kpis.get("project_count", len(project_rows)),
                "total_projects": runtime_kpis.get("total_projects", len(engine.projects)),
                "firms_engaged": runtime_kpis.get("firms_engaged", engaged_firm_count),
                "enterprise_pool": enterprise_pool_count,
                "visible_enterprises": visible_enterprise_count,
                "runtime_links": runtime_kpis.get("runtime_links", len(collaboration_links) + len(resource_flows)),
                "collaboration_links": runtime_kpis.get("collaboration_links", len(collaboration_links)),
                "resource_flows": runtime_kpis.get("resource_flows", len(resource_flows)),
                "cross_city_links": runtime_kpis.get("cross_city_links", cross_city_links),
                "active_projects_change_pct": runtime_kpis.get("active_projects_change_pct", 12.6),
                "cross_regional_collaboration_rate": cross_region_share,
                "cross_regional_collaboration_change_pp": 6.3,
                "policy_impact_score": policy_impact,
                "policy_impact_score_change_pct": 5.4,
                "resource_flow_index": runtime_kpis.get(
                    "resource_flow_index",
                    round(8.0 + min(0.9, max(engaged_firm_count, len(resource_flows)) * 0.01), 1),
                ),
                "resource_flow_components": runtime_kpis.get("resource_flow_components", {}),
                "resource_flow_volume": runtime_kpis.get("resource_flow_volume", 0),
                "market_concentration_hhi": round(float(network_metrics.get("market_concentration_hhi", 0.26) or 0.26), 3),
                "market_concentration_change": -0.04,
            },
            "spatial_distribution": self.spatial_distribution(engine.simulation_id),
            "collaboration_network": self.collaboration_network(engine.simulation_id),
            "trend_analysis": self.trends(engine.simulation_id),
            "top_affected_cities": top_cities,
            "policy_evaluation_summary": {
                "overall_impact_score": policy_impact,
                "impact_level": "high",
                "scenario_name": "Green Growth 2030",
                "compared_to": "Baseline Scenario",
                "evaluation_period": f"Month 0 - Month {total_ticks}",
                "score_breakdown": {
                    "economic_growth": 85.1,
                    "environmental_impact": 84.6,
                    "social_wellbeing": 79.2,
                    "innovation_capacity": 81.2,
                    "regulatory_governance_effectiveness": 72.3,
                },
                "key_insights": [
                    "Green Growth 2030 significantly improves environmental outcomes across the GBA.",
                    "Cross-regional collaboration is stronger and drives higher innovation capacity.",
                    "Market concentration decreased, indicating a more competitive construction market.",
                ],
                "recommended_actions": [
                    {"action_id": "REC001", "title": "Increase green finance incentives", "category": "finance"},
                    {"action_id": "REC002", "title": "Strengthen SME participation support", "category": "market"},
                    {"action_id": "REC003", "title": "Expand cross-border digital standards", "category": "digital"},
                ],
            },
        }
        dashboard["collaboration_network"]["runtime_links"] = runtime_map["collaboration_links"]
        return AnalyticsDashboardDTO(**dashboard).dict()

    def spatial_distribution(
        self,
        simulation_id: Optional[str] = None,
        project_type: str = "all",
        policy_scenario: str = "green_growth_2030",
    ) -> Dict:
        if simulation_id:
            try:
                runtime_map = simulation_runtime_service.map_data(simulation_id)
                project_rows = runtime_map.get("projects", [])
                if project_rows:
                    points = []
                    for index, project in enumerate(project_rows):
                        progress = float(project.get("progress", 0.0) or 0.0)
                        if progress >= 72:
                            density_level = "high"
                        elif progress >= 38:
                            density_level = "medium"
                        else:
                            density_level = "low"
                        points.append(
                            {
                                "project_id": project.get("project_id", f"MAP{index + 1:03d}"),
                                "city": project.get("city", "Shenzhen"),
                                "latitude": project.get("latitude", CITY_COORDS["Shenzhen"]["latitude"]),
                                "longitude": project.get("longitude", CITY_COORDS["Shenzhen"]["longitude"]),
                                "project_type": project.get("project_type", "Building"),
                                "density_level": density_level,
                                "policy_scenario": policy_scenario,
                                "size": max(8, min(36, round(progress / 4) + len(project.get("participants", [])))),
                                "impact_score": round(float(project.get("quality_score", 0.0) or 0.0) * 0.55 + progress * 0.45, 1),
                            }
                        )
                    return {
                        "project_type_filter_options": [
                            "All",
                            "Public Infrastructure",
                            "Buildings & Real Estate",
                            "Industrial & Logistics",
                            "Green & Digital Upgrade",
                        ],
                        "policy_scenario_options": ["Workflow Simulation", "Baseline Scenario", "Cross-Regional Collaboration"],
                        "points": points,
                    }
            except KeyError:
                pass
        cities = ["Guangzhou", "Foshan", "Dongguan", "Shenzhen", "Hong Kong", "Macau", "Zhuhai", "Huizhou"]
        points = []
        for index, city in enumerate(cities):
            coords = CITY_COORDS[city]
            points.append(
                {
                    "project_id": f"MAP{index + 1:03d}",
                    "city": city,
                    "latitude": coords["latitude"],
                    "longitude": coords["longitude"],
                    "project_type": ["Public Infrastructure", "Buildings & Real Estate", "Industrial & Logistics", "Green & Digital Upgrade"][index % 4],
                    "density_level": ["low", "medium", "high"][index % 3],
                    "policy_scenario": policy_scenario,
                    "size": 8 + index * 2,
                    "impact_score": 65 + index * 3,
                }
            )
        return {
            "project_type_filter_options": ["All", "Public Infrastructure", "Buildings & Real Estate", "Industrial & Logistics", "Green & Digital Upgrade"],
            "policy_scenario_options": ["Green Growth 2030", "Baseline Scenario", "Cross-Regional Collaboration"],
            "points": points,
        }

    def collaboration_network(self, simulation_id: Optional[str] = None, region: str = "all") -> Dict:
        if simulation_id:
            try:
                engine = simulation_runtime_service.get_engine(simulation_id)
                runtime_edges = engine.network.edges[:80]
                node_ids = {edge.source_agent_id for edge in runtime_edges} | {edge.target_agent_id for edge in runtime_edges}
                for project in engine.projects.values():
                    node_ids.add(project.project_id)
                nodes = []
                for node_id in node_ids:
                    project = engine.projects.get(node_id)
                    agent = engine.agents.get(node_id)
                    if project:
                        nodes.append(
                            {
                                "node_id": node_id,
                                "name": project.name,
                                "node_type": "project",
                                "city": project.region,
                                "value": round(project.performance.overall_quality * 100, 1),
                            }
                        )
                    elif agent:
                        nodes.append(
                            {
                                "node_id": node_id,
                                "name": agent.name,
                                "node_type": "government" if agent.role == "Government" else "enterprise",
                                "city": agent.region,
                                "value": round(
                                    (
                                        agent.management_capability
                                        + agent.technical_capability
                                        + agent.financial_capacity
                                    )
                                    / 3
                                    * 100,
                                    1,
                                ),
                            }
                        )
                edges = [
                    {
                        "edge_id": f"RT{index + 1:03d}",
                        "source_id": edge.source_agent_id,
                        "target_id": edge.target_agent_id,
                        "edge_type": "strong_collaboration" if edge.strength >= 0.72 else "medium_collaboration",
                        "weight": round(edge.strength, 3),
                    }
                    for index, edge in enumerate(runtime_edges)
                ]
                if nodes and edges:
                    return {
                        "nodes": nodes[:80],
                        "edges": edges,
                        "legend": {
                            "node_types": ["Enterprise", "Government / Agency", "Project"],
                            "edge_types": ["Strong Collaboration", "Medium Collaboration", "Project Link"],
                        },
                    }
            except KeyError:
                pass
        nodes = [
            {"node_id": "GOV_GZ", "name": "Guangzhou Municipal Gov.", "node_type": "government", "city": "Guangzhou", "value": 80},
            {"node_id": "GOV_SZ", "name": "Shenzhen Municipal Gov.", "node_type": "government", "city": "Shenzhen", "value": 86},
            {"node_id": "GOV_HK", "name": "Hong Kong Development Bureau", "node_type": "government", "city": "Hong Kong", "value": 82},
            {"node_id": "P001", "name": "Green Waterfront Complex", "node_type": "project", "city": "Shenzhen", "value": 95},
            {"node_id": "C003", "name": "Shenzhen Contractor C", "node_type": "enterprise", "city": "Shenzhen", "value": 90},
            {"node_id": "C002", "name": "Hong Kong Contractor B", "node_type": "enterprise", "city": "Hong Kong", "value": 82},
            {"node_id": "A001", "name": "GBA Design Studio", "node_type": "enterprise", "city": "Guangzhou", "value": 76},
        ]
        edges = [
            {"edge_id": "E001", "source_id": "GOV_GZ", "target_id": "P001", "edge_type": "medium_collaboration", "weight": 0.6},
            {"edge_id": "E002", "source_id": "GOV_SZ", "target_id": "P001", "edge_type": "strong_collaboration", "weight": 0.9},
            {"edge_id": "E003", "source_id": "GOV_HK", "target_id": "P001", "edge_type": "medium_collaboration", "weight": 0.7},
            {"edge_id": "E004", "source_id": "C003", "target_id": "P001", "edge_type": "project_link", "weight": 0.9},
            {"edge_id": "E005", "source_id": "C002", "target_id": "P001", "edge_type": "medium_collaboration", "weight": 0.5},
            {"edge_id": "E006", "source_id": "A001", "target_id": "P001", "edge_type": "project_link", "weight": 0.8},
        ]
        return {"nodes": nodes, "edges": edges, "legend": {"node_types": ["Enterprise", "Government / Agency", "Project"], "edge_types": ["Strong Collaboration", "Medium Collaboration", "Project Link"]}}

    def trends(
        self,
        simulation_id: Optional[str] = None,
        metric: str = "total_project_investment",
        time_range: str = "24_months",
    ) -> Dict:
        engine = simulation_runtime_service.get_engine(simulation_id) if simulation_id else simulation_runtime_service.ensure_demo_simulation()
        snapshots = sorted(
            list(getattr(engine.result_store, "tick_snapshots", []) or []),
            key=lambda row: int(row.get("tick", 0) or 0),
        )
        history = []
        for snapshot in snapshots:
            projects = list((snapshot.get("projects") or {}).values())
            if not projects:
                continue
            tick = int(snapshot.get("tick", len(history) + 1) or len(history) + 1)
            progress_values = [
                float((project.get("performance") or {}).get("actual_progress", 0.0) or 0.0)
                for project in projects
            ]
            quality_values = [
                float((project.get("performance") or {}).get("overall_quality", 0.0) or 0.0)
                for project in projects
            ]
            edge_count = len((snapshot.get("network") or {}).get("edges", []) or [])
            active_projects = len(
                [
                    project
                    for project in projects
                    if str(project.get("current_stage", "")).lower() not in {"closed", "failed", "suspended"}
                ]
            )
            avg_progress = mean(progress_values) if progress_values else 0.0
            avg_quality = mean(quality_values) if quality_values else 0.0
            baseline_value = min(96, 12 + tick * 0.62 + active_projects * 0.18 + avg_progress * 22)
            scenario_value = min(100, 14 + tick * 0.82 + active_projects * 0.24 + avg_progress * 34 + avg_quality * 8 + edge_count * 0.025)
            history.append(
                {
                    "tick": tick,
                    "baseline_value": round(baseline_value, 1),
                    "scenario_value": round(max(scenario_value, baseline_value + 1.5), 1),
                }
            )
        if not history:
            total = max(24, int(getattr(engine, "ticks", 24) or 24))
            history = [
                {
                    "tick": index,
                    "baseline_value": round(10 + index / total * 42, 1),
                    "scenario_value": round(12 + index / total * 72, 1),
                }
                for index in range(1, total + 1)
            ]
        baseline = []
        scenario = []
        for row in history:
            tick = int(row.get("tick", len(baseline) + 1))
            baseline.append({"date": f"T{tick}", "value": row["baseline_value"]})
            scenario.append({"date": f"T{tick}", "value": row["scenario_value"]})
        return {
            "metric_options": ["Collaboration Index", "Project Count", "Resource Flow Index", "Average Quality"],
            "time_range_options": ["Last 12 Months", "Last 24 Months", "Full Horizon"],
            "series": [
                {"name": "Baseline Scenario", "data": baseline},
                {"name": "Workflow Simulation", "data": scenario},
            ],
        }

    @staticmethod
    def _top_affected_cities(city_counts: Counter, project_rows: list[Dict]) -> list[Dict]:
        quality_by_city: dict[str, list[float]] = {}
        for project in project_rows:
            city = project.get("city")
            if not city:
                continue
            quality_by_city.setdefault(city, []).append(float(project.get("quality_score", 0.0) or 0.0))
        if not city_counts:
            city_counts = Counter({"Shenzhen": 3, "Guangzhou": 2, "Hong Kong": 1, "Foshan": 1, "Zhuhai": 1})
        max_count = max(city_counts.values() or [1])
        rows = []
        for rank, (city, count) in enumerate(city_counts.most_common(5), start=1):
            avg_quality = mean(quality_by_city.get(city, [70.0]))
            impact_score = round(min(96.0, 54 + (count / max_count) * 26 + avg_quality * 0.18), 1)
            rows.append(
                {
                    "rank": rank,
                    "city": city,
                    "impact_score": impact_score,
                    "delta_vs_baseline": round(max(2.0, impact_score - 70), 1),
                }
            )
        return rows

    def policy_evaluation(self, simulation_id: Optional[str] = None, policy_id: str = "POL001") -> Dict:
        return self.dashboard(simulation_id).get("policy_evaluation_summary", {})


analytics_service = AnalyticsService()
