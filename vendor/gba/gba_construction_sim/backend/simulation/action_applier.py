from __future__ import annotations

from contextlib import ExitStack
from typing import Callable, Iterable

from gba_construction_sim.backend.simulation.decision_request import DecisionResult
from gba_construction_sim.backend.simulation.locks import simulation_lock_registry


class ActionApplier:
    """Serial application boundary for state-changing decision results.

    LLM decisions may finish concurrently, but callers should use this boundary
    to serialize project and agent mutations. The supplied apply callback keeps
    lifecycle-specific behavior in ProjectLifecycleEngine / ProjectStateUpdateEngine.
    """

    def apply_results(
        self,
        results: Iterable[DecisionResult],
        apply_one: Callable[[DecisionResult], None],
        *,
        include_non_ok: bool = False,
    ) -> None:
        ordered = sorted(
            results,
            key=lambda result: (
                int(result.request.priority),
                result.request.tick,
                result.request.project_id or "",
                result.request.agent_id,
            ),
        )
        for result in ordered:
            if not include_non_ok and not result.ok:
                continue
            project_id = result.request.project_id
            agent_id = result.request.agent_id
            if project_id:
                with simulation_lock_registry.project_lock(project_id):
                    with simulation_lock_registry.agent_lock(agent_id):
                        apply_one(result)
            else:
                with simulation_lock_registry.agent_lock(agent_id):
                    apply_one(result)

    def apply_project_update(self, project, agents: dict, apply_one: Callable[[], None]) -> None:
        project_id = getattr(project, "project_id", None)
        agent_ids = self._project_agent_ids(project, agents)
        self.apply_project_mutation(project_id, agent_ids, apply_one)

    def apply_project_mutation(
        self,
        project_id: str | None,
        agent_ids: Iterable[str],
        apply_one: Callable[[], None],
    ) -> None:
        if project_id:
            with simulation_lock_registry.project_lock(project_id):
                self._with_agent_locks(agent_ids, apply_one)
        else:
            self._with_agent_locks(agent_ids, apply_one)

    @staticmethod
    def _with_agent_locks(agent_ids: Iterable[str], apply_one: Callable[[], None]) -> None:
        unique_agent_ids = sorted({agent_id for agent_id in agent_ids if agent_id})
        with ExitStack() as stack:
            for agent_id in unique_agent_ids:
                stack.enter_context(simulation_lock_registry.agent_lock(agent_id))
            apply_one()

    @staticmethod
    def _project_agent_ids(project, agents: dict) -> list[str]:
        agent_ids = [
            getattr(project, "owner_id", None),
            getattr(project, "selected_architect_id", None),
            getattr(project, "selected_engineer_id", None),
            getattr(project, "selected_qs_id", None),
            getattr(project, "selected_contractor_id", None),
            getattr(project, "selected_bank_id", None),
        ]
        agent_ids.extend(getattr(project, "selected_supplier_ids", []) or [])
        for engagement in getattr(project, "engagements", []) or []:
            agent_ids.append(getattr(engagement, "agent_id", None))
        return [agent_id for agent_id in agent_ids if agent_id in agents]
