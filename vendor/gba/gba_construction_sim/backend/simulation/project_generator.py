import random
from typing import List

from gba_construction_sim.backend.models.environment import MacroEnvironment


GBA_REGIONS = [
    "Shenzhen",
    "Guangzhou",
    "Hong Kong",
    "Macau",
    "Zhuhai",
    "Foshan",
    "Dongguan",
    "Huizhou",
    "Zhongshan",
    "Jiangmen",
    "Zhaoqing",
]

PROJECT_TYPE_PROFILES = {
    "building": {
        "budget": (80_000_000, 260_000_000),
        "duration": (10, 18),
        "complexity": (0.38, 0.62),
        "names": ["Mixed-use Tower", "Public Housing Phase", "Commercial Complex", "Urban Renewal Block"],
    },
    "infrastructure": {
        "budget": (180_000_000, 680_000_000),
        "duration": (16, 30),
        "complexity": (0.55, 0.86),
        "names": ["Metro Extension", "Port Upgrade", "Smart Road Corridor", "Transit Interchange"],
    },
    "industrial": {
        "budget": (120_000_000, 420_000_000),
        "duration": (12, 24),
        "complexity": (0.45, 0.76),
        "names": ["Advanced Manufacturing Park", "Logistics Hub", "Energy Storage Factory", "Industrial Campus"],
    },
    "public_facility": {
        "budget": (60_000_000, 220_000_000),
        "duration": (10, 20),
        "complexity": (0.35, 0.66),
        "names": ["Community Health Centre", "School Redevelopment", "Civic Service Hub", "Waterfront Facility"],
    },
    "digital_smart": {
        "budget": (90_000_000, 300_000_000),
        "duration": (10, 20),
        "complexity": (0.52, 0.82),
        "names": ["BIM Delivery Centre", "AI Innovation Park", "Smart Logistics Node", "Data Campus"],
    },
}


class ProjectGenerator:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    def generate(self, macro_environment: MacroEnvironment) -> List[dict]:
        if self.rng.random() > 0.05 * macro_environment.market_demand_index:
            return []
        return [self.generate_opportunity(macro_environment)]

    def generate_candidate_set(
        self,
        macro_environment: MacroEnvironment,
        count: int = 6,
    ) -> List[dict]:
        """Publish a varied opportunity set for owners to evaluate independently."""
        return [self.generate_opportunity(macro_environment) for _ in range(max(1, count))]

    def generate_opportunity(self, macro_environment: MacroEnvironment) -> dict:
        project_type = self._weighted_choice(
            {
                "building": 0.30,
                "infrastructure": 0.22,
                "industrial": 0.18,
                "public_facility": 0.16,
                "digital_smart": 0.14,
            }
        )
        region = self._weighted_choice(
            {
                "Shenzhen": 0.16,
                "Guangzhou": 0.15,
                "Hong Kong": 0.10,
                "Macau": 0.07,
                "Zhuhai": 0.08,
                "Foshan": 0.10,
                "Dongguan": 0.10,
                "Huizhou": 0.08,
                "Zhongshan": 0.07,
                "Jiangmen": 0.05,
                "Zhaoqing": 0.04,
            }
        )
        profile = PROJECT_TYPE_PROFILES[project_type]
        budget_min, budget_max = profile["budget"]
        duration_min, duration_max = profile["duration"]
        complexity_min, complexity_max = profile["complexity"]
        demand = max(0.65, min(1.45, macro_environment.market_demand_index))
        price_pressure = max(0.75, min(1.45, macro_environment.material_price_index))
        budget = self.rng.uniform(budget_min, budget_max) * demand * price_pressure
        normalized_budget = (budget - budget_min) / max(budget_max - budget_min, 1.0)
        scale = "small" if normalized_budget < 0.33 else "medium" if normalized_budget < 0.70 else "large"
        return {
            "project_type": project_type,
            "region": region,
            "scale": scale,
            "budget": budget,
            "planned_duration": self.rng.randint(duration_min, duration_max),
            "technical_complexity": self.rng.uniform(complexity_min, complexity_max),
            "name": f"{region} {self.rng.choice(profile['names'])}",
        }

    def _weighted_choice(self, weights: dict[str, float]) -> str:
        total = sum(weights.values())
        pick = self.rng.random() * total
        cumulative = 0.0
        for key, weight in weights.items():
            cumulative += weight
            if pick <= cumulative:
                return key
        return next(reversed(weights))
