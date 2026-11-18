from typing import Dict, List, Optional

import networkx as nx
from pydantic import BaseModel, Field

from gba_construction_sim.backend.core.enums import EngagementStatus
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.network.collaboration_prior import CollaborationPrior


class CollaborationEdge(BaseModel):
    source_agent_id: str
    target_agent_id: str
    project_id: str
    relation_type: str
    start_tick: int
    end_tick: Optional[int] = None
    strength: float = 0.5
    cross_region: bool = False
    performance_result: Dict = Field(default_factory=dict)


class CollaborationNetwork:
    def __init__(self, collaboration_prior: Optional[CollaborationPrior] = None) -> None:
        self.graph = nx.Graph()
        self.edges: List[CollaborationEdge] = []
        self.collaboration_prior = collaboration_prior or CollaborationPrior()

    def update(
        self,
        projects: Dict[str, ConstructionProject],
        agents: Dict[str, EnterpriseAgentProfile],
        tick: int,
    ) -> None:
        for agent in agents.values():
            self.graph.add_node(agent.agent_id, node_type="agent", role=agent.role, region=agent.region)
        for project in projects.values():
            self.graph.add_node(project.project_id, node_type="project", region=project.region)
            active = [
                engagement
                for engagement in project.engagements
                if engagement.status in {EngagementStatus.ACTIVE, EngagementStatus.STANDBY}
            ]
            for engagement in active:
                agent = agents.get(engagement.agent_id)
                if not agent:
                    continue
                self.graph.add_edge(agent.agent_id, project.project_id, relation_type="agent_project", project_id=project.project_id)
            owner_id = project.owner_id
            for engagement in active:
                if engagement.agent_id == owner_id or owner_id not in agents or engagement.agent_id not in agents:
                    continue
                relation = f"owner_{engagement.role.lower()}"
                self._add_edge(owner_id, engagement.agent_id, relation, project, agents, tick)
            if project.selected_contractor_id:
                for supplier_id in project.selected_supplier_ids:
                    if supplier_id in agents:
                        self._add_edge(
                            project.selected_contractor_id,
                            supplier_id,
                            "contractor_supplier",
                            project,
                            agents,
                            tick,
                        )

    def _add_edge(
        self,
        source: str,
        target: str,
        relation_type: str,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        tick: int,
    ) -> None:
        if any(edge.source_agent_id == source and edge.target_agent_id == target and edge.project_id == project.project_id for edge in self.edges):
            return
        cross_region = agents[source].region != agents[target].region
        edge = CollaborationEdge(
            source_agent_id=source,
            target_agent_id=target,
            project_id=project.project_id,
            relation_type=relation_type,
            start_tick=tick,
            strength=max(0.0, 1.0 - project.performance.project_failure_risk),
            cross_region=cross_region,
        )
        self.edges.append(edge)
        self.graph.add_edge(source, target, relation_type=relation_type, project_id=project.project_id)

    def to_dict(self) -> Dict:
        return {
            "nodes": [{"id": node, **attrs} for node, attrs in self.graph.nodes(data=True)],
            "edges": [edge.dict() for edge in self.edges],
            "prior": self.collaboration_prior.stats(),
        }

    def metrics(self) -> Dict:
        node_count = self.graph.number_of_nodes()
        edge_count = self.graph.number_of_edges()
        agent_edges = self.edges
        cross_region_edges = [edge for edge in agent_edges if edge.cross_region]
        return {
            "network_density": nx.density(self.graph) if node_count > 1 else 0.0,
            "average_degree": (2 * edge_count / node_count) if node_count else 0.0,
            "cross_region_edge_share": len(cross_region_edges) / max(len(agent_edges), 1),
            "collaboration_repetition_rate": 0.0,
            **self.collaboration_prior.stats(),
        }
