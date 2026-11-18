from __future__ import annotations

from collections import defaultdict
from threading import RLock


class SimulationLockRegistry:
    def __init__(self) -> None:
        self._guard = RLock()
        self._project_locks: defaultdict[str, RLock] = defaultdict(RLock)
        self._agent_locks: defaultdict[str, RLock] = defaultdict(RLock)

    def project_lock(self, project_id: str) -> RLock:
        with self._guard:
            return self._project_locks[project_id]

    def agent_lock(self, agent_id: str) -> RLock:
        with self._guard:
            return self._agent_locks[agent_id]


simulation_lock_registry = SimulationLockRegistry()
