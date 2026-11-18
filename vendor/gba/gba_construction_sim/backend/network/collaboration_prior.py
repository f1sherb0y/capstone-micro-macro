"""Historical collaboration priors generated with Batch001 agents."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_NETWORK_EDGE_CSV = PROJECT_ROOT / "outputs" / "gba_construction_agent_network_edges_batch001.csv"


@dataclass(frozen=True)
class CollaborationPriorEdge:
    edge_id: str
    source_agent_id: str
    target_agent_id: str
    edge_type: str
    relationship_strength: float
    trust_score: float
    historical_project_count: int
    collaboration_probability: float
    relationship_stability: float
    conflict_probability: float
    cross_city: bool
    cross_border: bool

    @property
    def fit_score(self) -> float:
        score = (
            0.30 * self.relationship_strength
            + 0.25 * self.trust_score
            + 0.25 * self.collaboration_probability
            + 0.15 * self.relationship_stability
            + 0.05 * min(1.0, self.historical_project_count / 8)
            - 0.20 * self.conflict_probability
        )
        return max(0.0, min(1.0, score))


class CollaborationPrior:
    def __init__(self, edges: Iterable[CollaborationPriorEdge] = ()) -> None:
        self.edges = list(edges)
        self._by_pair: dict[tuple[str, str], CollaborationPriorEdge] = {}
        for edge in self.edges:
            key = self._key(edge.source_agent_id, edge.target_agent_id)
            existing = self._by_pair.get(key)
            if not existing or edge.fit_score > existing.fit_score:
                self._by_pair[key] = edge
        self.edge_count = len(self.edges)
        self.average_fit = (
            sum(edge.fit_score for edge in self.edges) / self.edge_count if self.edge_count else 0.0
        )

    @classmethod
    def from_csv(cls, csv_path: Path = DEFAULT_NETWORK_EDGE_CSV) -> "CollaborationPrior":
        if not csv_path.exists():
            return cls()
        edges: list[CollaborationPriorEdge] = []
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                source = _clean(row.get("source_agent_id"))
                target = _clean(row.get("target_agent_id"))
                if not source or not target or source == target:
                    continue
                edges.append(
                    CollaborationPriorEdge(
                        edge_id=_clean(row.get("edge_id")),
                        source_agent_id=source,
                        target_agent_id=target,
                        edge_type=_clean(row.get("edge_type")),
                        relationship_strength=_float(row, "relationship_strength", 0.5),
                        trust_score=_float(row, "trust_score", 0.5),
                        historical_project_count=_int(row, "historical_project_count", 0),
                        collaboration_probability=_float(row, "collaboration_probability", 0.5),
                        relationship_stability=_float(row, "relationship_stability", 0.5),
                        conflict_probability=_float(row, "conflict_probability", 0.2),
                        cross_city=_bool(row, "cross_city_flag"),
                        cross_border=_bool(row, "cross_border_flag"),
                    )
                )
        return cls(edges)

    def score(self, source_agent_id: str, target_agent_id: str, default: float = 0.5) -> float:
        edge = self._by_pair.get(self._key(source_agent_id, target_agent_id))
        return edge.fit_score if edge else default

    def participant_fit(self, agent_id: str, participant_ids: Iterable[str], default: float = 0.5) -> float:
        scores = [self.score(agent_id, participant_id, default) for participant_id in participant_ids if participant_id != agent_id]
        return sum(scores) / len(scores) if scores else default

    def edge_for(self, source_agent_id: str, target_agent_id: str) -> CollaborationPriorEdge | None:
        return self._by_pair.get(self._key(source_agent_id, target_agent_id))

    def stats(self) -> dict[str, Any]:
        return {
            "prior_edge_count": self.edge_count,
            "prior_pair_count": len(self._by_pair),
            "prior_average_fit": round(self.average_fit, 4),
        }

    @staticmethod
    def _key(source_agent_id: str, target_agent_id: str) -> tuple[str, str]:
        return tuple(sorted((source_agent_id, target_agent_id)))


@lru_cache(maxsize=1)
def load_default_collaboration_prior() -> CollaborationPrior:
    return CollaborationPrior.from_csv(DEFAULT_NETWORK_EDGE_CSV)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _float(row: dict[str, Any], field: str, default: float = 0.0) -> float:
    try:
        text = _clean(row.get(field))
        return float(text) if text else default
    except (TypeError, ValueError):
        return default


def _int(row: dict[str, Any], field: str, default: int = 0) -> int:
    try:
        text = _clean(row.get(field))
        return int(float(text)) if text else default
    except (TypeError, ValueError):
        return default


def _bool(row: dict[str, Any], field: str) -> bool:
    return _clean(row.get(field)).lower() in {"true", "1", "yes", "y"}
