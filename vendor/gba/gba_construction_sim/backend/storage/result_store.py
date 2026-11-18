from typing import Dict, List, Optional

from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.metrics import SimulationMetrics
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.network.collaboration_network import CollaborationNetwork


class ResultStore:
    def __init__(self, store_full_agent_snapshots: bool = True) -> None:
        self.performance_history: Dict[str, List[Dict]] = {}
        self.tick_snapshots: List[Dict] = []
        self.store_full_agent_snapshots = store_full_agent_snapshots

    def save_tick_result(
        self,
        tick: int,
        projects: Dict[str, ConstructionProject],
        agents: Dict[str, EnterpriseAgentProfile],
        network: CollaborationNetwork,
        metrics: SimulationMetrics,
        workflow_runtime: Optional[Dict] = None,
    ) -> None:
        for project in projects.values():
            history = self.performance_history.setdefault(project.project_id, [])
            history[:] = [row for row in history if int(row.get("tick", 0) or 0) != tick]
            history.append(
                {
                    "tick": tick,
                    "stage": project.current_stage.value,
                    **project.performance.dict(),
                }
            )
        snapshot = {
            "tick": tick,
            "projects": {project_id: project.dict() for project_id, project in projects.items()},
            "network": network.to_dict(),
            "metrics": metrics.dict(),
            "workflow_runtime": workflow_runtime or {},
        }
        if self.store_full_agent_snapshots:
            snapshot["agents"] = {agent_id: agent.dict() for agent_id, agent in agents.items()}
        else:
            active_agent_ids = {
                engagement.agent_id
                for project in projects.values()
                for engagement in project.engagements
            }
            snapshot["agents"] = {
                agent_id: agent.dict()
                for agent_id, agent in agents.items()
                if agent_id in active_agent_ids
            }
            snapshot["agent_summary"] = {
                "agent_count": len(agents),
                "active_or_engaged_agent_count": len(active_agent_ids),
            }
        for index, existing in enumerate(self.tick_snapshots):
            if int(existing.get("tick", 0) or 0) == tick:
                self.tick_snapshots[index] = snapshot
                break
        else:
            self.tick_snapshots.append(snapshot)
        self.tick_snapshots.sort(key=lambda row: int(row.get("tick", 0) or 0))

    def get_project_performance(self, project_id: str) -> List[Dict]:
        return self.performance_history.get(project_id, [])
