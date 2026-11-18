from abc import ABC, abstractmethod
import asyncio
from typing import Dict

from gba_construction_sim.backend.models.action import AgentAction
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile


class DecisionProvider(ABC):
    @abstractmethod
    def decide(self, agent: EnterpriseAgentProfile, context: Dict) -> AgentAction:
        raise NotImplementedError

    async def decide_async(self, agent: EnterpriseAgentProfile, context: Dict) -> AgentAction:
        return await asyncio.to_thread(self.decide, agent, context)
