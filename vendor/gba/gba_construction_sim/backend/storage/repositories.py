from typing import Dict

from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine


class SimulationRepository:
    def __init__(self) -> None:
        self._items: Dict[str, SimulationEngine] = {}

    def add(self, engine: SimulationEngine) -> None:
        self._items[engine.simulation_id] = engine

    def get(self, simulation_id: str) -> SimulationEngine:
        if simulation_id not in self._items:
            raise KeyError(f"Simulation {simulation_id} not found")
        return self._items[simulation_id]

    def all(self) -> list[SimulationEngine]:
        return list(self._items.values())


simulation_repository = SimulationRepository()
