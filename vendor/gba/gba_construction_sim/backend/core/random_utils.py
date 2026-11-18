import random
from typing import Optional


def seeded_random(seed: Optional[int] = None) -> random.Random:
    return random.Random(seed)


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))
