from typing import Dict

from gba_construction_sim.backend.core.enums import ProjectStage
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.metrics import SimulationMetrics
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.network.collaboration_network import CollaborationNetwork


class MetricsCalculator:
    def calculate(
        self,
        projects: Dict[str, ConstructionProject],
        agents: Dict[str, EnterpriseAgentProfile],
        network: CollaborationNetwork,
        policy: PolicyRegime,
    ) -> SimulationMetrics:
        project_list = list(projects.values())
        completed = [project for project in project_list if project.current_stage == ProjectStage.CLOSED]
        project_metrics = {
            "project_completion_rate": len(completed) / max(len(project_list), 1),
            "average_delay_days": self._avg([project.performance.delay_days for project in project_list]),
            "average_cost_overrun": self._avg([project.performance.cost_overrun_ratio for project in project_list]),
            "average_quality_score": self._avg([project.performance.overall_quality for project in project_list]),
            "approval_pass_rate": self._event_rate(project_list, "approval_approved"),
            "tender_failure_rate": self._event_rate(project_list, "bid_failed"),
            "construction_failure_rate": self._stage_rate(project_list, ProjectStage.FAILED),
            "claim_frequency": self._risk_frequency(project_list, "claim_risk", 0.5),
            "variation_frequency": self._event_rate(project_list, "variation_requested"),
            "inspection_failure_rate": self._event_rate(project_list, "inspection_failed"),
            "project_failure_risk_average": self._avg([project.performance.project_failure_risk for project in project_list]),
        }
        agent_metrics = self._calculate_agent_metrics(agents, project_list)
        policy_metrics = {
            "policy_cost_burden": policy.compliance_cost,
            "approval_efficiency": 1.0 - project_metrics["average_delay_days"] / max(365, 1),
            "cross_region_collaboration_share": network.metrics()["cross_region_edge_share"],
            "systemic_risk_index": project_metrics["project_failure_risk_average"],
        }
        return SimulationMetrics(
            project_metrics=project_metrics,
            agent_metrics=agent_metrics,
            network_metrics=network.metrics(),
            policy_metrics=policy_metrics,
        )

    def _avg(self, values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def _event_rate(self, projects: list[ConstructionProject], event_type: str) -> float:
        return sum(1 for project in projects if any(event.get("event_type") == event_type for event in project.event_log)) / max(len(projects), 1)

    def _stage_rate(self, projects: list[ConstructionProject], stage: ProjectStage) -> float:
        return sum(1 for project in projects if project.current_stage == stage) / max(len(projects), 1)

    def _risk_frequency(self, projects: list[ConstructionProject], field_name: str, threshold: float) -> float:
        return sum(1 for project in projects if getattr(project.performance, field_name) >= threshold) / max(len(projects), 1)

    def _calculate_agent_metrics(
        self,
        agents: Dict[str, EnterpriseAgentProfile],
        projects: list[ConstructionProject],
    ) -> Dict:
        joined_projects_by_agent: Dict[str, list[ConstructionProject]] = {}
        for project in projects:
            for engagement in project.engagements:
                joined_projects_by_agent.setdefault(engagement.agent_id, []).append(project)
        joined_counts = {
            agent_id: len(joined_projects_by_agent.get(agent_id, []))
            for agent_id in agents
        }
        if len(agents) <= 1000:
            return {
                agent_id: {
                    "resource_utilization": agent.occupied_resource / max(agent.total_resource_capacity, 1e-9),
                    "number_of_projects_joined": joined_counts[agent_id],
                    "cross_region_project_share": self._cross_region_share_from_joined(
                        agent,
                        joined_projects_by_agent.get(agent_id, []),
                    ),
                }
                for agent_id, agent in agents.items()
            }

        utilization_values = [
            agent.occupied_resource / max(agent.total_resource_capacity, 1e-9)
            for agent in agents.values()
        ]
        joined_agent_ids = [agent_id for agent_id, count in joined_counts.items() if count > 0]
        role_counts: Dict[str, int] = {}
        source_counts: Dict[str, int] = {}
        for agent in agents.values():
            role_counts[agent.role] = role_counts.get(agent.role, 0) + 1
            source_type = str(
                agent.semantic_memory.get("agent_type")
                or agent.semantic_memory.get("source_type")
                or "default"
            )
            source_counts[source_type] = source_counts.get(source_type, 0) + 1

        top_engaged = sorted(
            (
                {
                    "agent_id": agent_id,
                    "name": agents[agent_id].name,
                    "role": agents[agent_id].role,
                    "region": agents[agent_id].region,
                    "number_of_projects_joined": count,
                    "cross_region_project_share": self._cross_region_share_from_joined(
                        agents[agent_id],
                        joined_projects_by_agent.get(agent_id, []),
                    ),
                }
                for agent_id, count in joined_counts.items()
                if count > 0
            ),
            key=lambda item: (-item["number_of_projects_joined"], item["agent_id"]),
        )[:50]

        return {
            "summary": {
                "total_agents": len(agents),
                "joined_agents": len(joined_agent_ids),
                "free_agents": len(agents) - len(joined_agent_ids),
                "average_resource_utilization": self._avg(utilization_values),
                "role_counts": role_counts,
                "source_counts": source_counts,
            },
            "top_engaged_agents": top_engaged,
            "detail_truncated": True,
        }

    def _cross_region_share(self, agent: EnterpriseAgentProfile, projects: list[ConstructionProject]) -> float:
        joined = [
            project
            for project in projects
            if any(engagement.agent_id == agent.agent_id for engagement in project.engagements)
        ]
        return self._cross_region_share_from_joined(agent, joined)

    @staticmethod
    def _cross_region_share_from_joined(
        agent: EnterpriseAgentProfile,
        joined: list[ConstructionProject],
    ) -> float:
        if not joined:
            return 0.0
        cross_region = [project for project in joined if project.region != agent.region]
        return len(cross_region) / len(joined)
