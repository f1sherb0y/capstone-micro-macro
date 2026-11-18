"""Candidate pool selection for database-backed simulations."""

from __future__ import annotations

import random
from typing import Iterable, Optional

from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.network.collaboration_prior import CollaborationPrior
from gba_construction_sim.backend.simulation.engagement_manager import EngagementManager


class AgentPoolService:
    def __init__(
        self,
        rng: Optional[random.Random] = None,
        max_tender_invites: int = 40,
        collaboration_prior: Optional[CollaborationPrior] = None,
    ) -> None:
        self.rng = rng or random.Random()
        self.max_tender_invites = max(1, max_tender_invites)
        self.collaboration_prior = collaboration_prior or CollaborationPrior()

    def available(
        self,
        candidates: Iterable[EnterpriseAgentProfile],
        role: str,
        required_resource: float,
        engagement_manager: EngagementManager,
    ) -> list[EnterpriseAgentProfile]:
        return [
            agent
            for agent in candidates
            if agent.role == role and engagement_manager.check_agent_availability(agent, required_resource)
        ]

    def visible_candidates(
        self,
        candidates: Iterable[EnterpriseAgentProfile],
        role: str,
        required_resource: float,
        engagement_manager: EngagementManager,
        project: ConstructionProject | None = None,
        participant_ids: Iterable[str] = (),
        limit: int = 48,
    ) -> list[EnterpriseAgentProfile]:
        """Apply hard eligibility and market-visibility limits without making the final choice."""
        eligible = self.available(candidates, role, required_resource, engagement_manager)
        return self._bounded_candidate_pool(
            eligible,
            project,
            participant_ids,
            limit=max(1, limit),
        )

    def _bounded_candidate_pool(
        self,
        eligible: list[EnterpriseAgentProfile],
        project: ConstructionProject | None,
        participant_ids: Iterable[str],
        limit: int,
    ) -> list[EnterpriseAgentProfile]:
        """Bound market visibility without deciding who receives the work."""
        if len(eligible) <= limit:
            return eligible
        participant_ids = [agent_id for agent_id in participant_ids if agent_id]
        project_region = project.region if project else ""

        def shortlist_score(agent: EnterpriseAgentProfile) -> float:
            local_bonus = 0.20 if project_region and agent.region == project_region else 0.0
            active_region_bonus = 0.12 if project_region and project_region in agent.active_regions else 0.0
            prior_fit = self.collaboration_prior.participant_fit(agent.agent_id, participant_ids, 0.5)
            return (
                0.38 * agent.available_resource()
                + 0.30 * prior_fit
                + local_bonus
                + active_region_bonus
                + self.rng.random() * 0.015
            )

        return sorted(eligible, key=shortlist_score, reverse=True)[:limit]
