import random

from gba_construction_sim.backend.core.random_utils import clamp
from gba_construction_sim.backend.models.environment import MacroEnvironment


class MacroEnvironmentUpdater:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def update(self, environment: MacroEnvironment, current_tick: int) -> None:
        environment.current_tick = current_tick
        environment.market_demand_index = clamp(
            environment.market_demand_index + self.rng.uniform(-0.03, 0.03),
            0.6,
            1.4,
        )
        environment.material_price_index = clamp(
            environment.material_price_index + self.rng.uniform(-0.02, 0.04),
            0.7,
            1.6,
        )
        environment.labor_price_index = clamp(
            environment.labor_price_index + self.rng.uniform(-0.01, 0.03),
            0.8,
            1.5,
        )
        environment.financing_condition_index = clamp(
            environment.financing_condition_index + self.rng.uniform(-0.03, 0.02),
            0.5,
            1.3,
        )
