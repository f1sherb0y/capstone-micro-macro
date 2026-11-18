from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from typing import Any


class IntegrationError(RuntimeError):
    """A technical failure; never an economic no-bid decision."""


class CommitRejected(IntegrationError):
    """A proposal is well formed but cannot be committed to current state."""


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def positive(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True)
class PackageSpec:
    package_id: str
    project_id: str
    kind: str
    buyer_id: str
    name: str
    scope: str
    budget: float
    currency: str
    resource_required: float
    depends_on: tuple[str, ...] = ()
    cost_inclusion: str = "owner_additional"
    parent_package_id: str | None = None
    # Explicit eligibility is scenario input, never inferred from historical awards.
    candidate_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if self.kind not in {"design", "cost_consulting", "construction", "supply"}:
            raise ValueError(f"Unsupported package kind: {self.kind}")
        for key in ("package_id", "project_id", "buyer_id", "name", "scope", "currency"):
            if not isinstance(getattr(self, key), str) or not getattr(self, key).strip():
                raise ValueError(f"Missing {key}")
        positive(self.budget, "package budget")
        positive(self.resource_required, "resource requirement")
        if self.currency not in {"MOP", "HKD", "CNY"}:
            raise ValueError("Specify a supported task currency; implicit currency conversion is forbidden")
        if self.cost_inclusion not in {"owner_additional", "included_in_parent"}:
            raise ValueError("Invalid cost inclusion")
        if self.cost_inclusion == "included_in_parent" and not self.parent_package_id:
            raise ValueError("Included cost requires parent package")
        if self.buyer_id == "$construction_lead" and self.kind != "supply":
            raise ValueError("Only supply procurement can use the construction lead as buyer")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("Duplicate dependencies")

    @property
    def micro_role(self):
        return {"design": "designer", "cost_consulting": "supervisor", "construction": "contractor", "supply": "supplier"}[self.kind]

    @property
    def macro_role(self):
        return {"design": "Architect", "cost_consulting": "QS", "construction": "Contractor", "supply": "Supplier"}[self.kind]


@dataclass(frozen=True)
class DecisionSnapshot:
    simulation_id: str
    project_id: str
    package_id: str
    round_id: int
    tick: int
    public: dict
    private: dict[str, dict]
    data_version: str

    @property
    def version(self):
        return digest(asdict(self))

    def for_entity(self, entity_id: str | None):
        if entity_id not in self.private:
            raise IntegrationError(f"No authorized decision view for {entity_id}")
        return {"simulation_id": self.simulation_id, "project_id": self.project_id,
                "package_id": self.package_id, "round_id": self.round_id, "tick": self.tick,
                "snapshot_version": self.version, "data_version": self.data_version,
                "public": self.public, "own_state": self.private[entity_id]}


@dataclass
class ContractProposal:
    proposal_id: str
    simulation_id: str
    project_id: str
    package_id: str
    session_id: str
    snapshot_version: str
    buyer_id: str
    bid_id: str
    bidder_id: str
    lead_id: str
    members: list[str]
    price: float
    currency: str
    resource_commitments: dict[str, float]
    work_shares: dict[str, float]
    signatures: dict[str, bool]
    signed_terms_hash: str
    terms: dict = field(default_factory=dict)

    def terms_hash(self):
        payload = asdict(self)
        payload.pop("signatures")
        payload.pop("signed_terms_hash")
        return digest(payload)

    def validate(self):
        positive(self.price, "contract price")
        members = set(self.members)
        if not members or len(members) != len(self.members) or self.lead_id not in members or self.buyer_id in members:
            raise CommitRejected("Invalid or conflicting contract parties")
        if set(self.resource_commitments) != members or set(self.work_shares) != members:
            raise CommitRejected("Each member requires a resource commitment and work share")
        for value in self.resource_commitments.values():
            positive(value, "member commitment")
        for value in self.work_shares.values():
            positive(value, "member work share")
        if abs(sum(self.work_shares.values()) - 1) > 1e-8:
            raise CommitRejected("Work shares must sum to one")
        if self.signed_terms_hash != self.terms_hash():
            raise CommitRejected("Contract terms changed after signing")
        if set(self.signatures) != members | {self.buyer_id} or not all(x is True for x in self.signatures.values()):
            raise CommitRejected("All parties must independently accept the same terms")
