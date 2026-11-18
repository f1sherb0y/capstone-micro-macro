"""Run-local, recipient-scoped feedback; this store owns no formal state."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading

from integration.sessions import atomic_json
from src.json_input import read_json_object


def observation_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class ObservationInbox:
    def __init__(self, run_id: str, organization_ids, path: Path | None = None):
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("Run identity is required")
        self.run_id = run_id
        self.organization_ids = frozenset(organization_ids)
        if not self.organization_ids or any(not isinstance(item, str) or not item.strip()
                                            for item in self.organization_ids):
            raise ValueError("Explicit recipient identities are required")
        self.path = Path(path) if path is not None else None
        self._records = {}
        self._lock = threading.RLock()
        if self.path is not None and self.path.exists():
            _, saved = read_json_object(self.path)
            if (set(saved) != {"schema_version", "run_id", "organization_ids", "records"}
                    or saved["run_id"] != run_id or saved["schema_version"] != "observation-inbox.v1"
                    or not isinstance(saved["organization_ids"], list)
                    or any(not isinstance(item, str) or not item.strip() for item in saved["organization_ids"])
                    or len(set(saved["organization_ids"])) != len(saved["organization_ids"])
                    or set(saved["organization_ids"]) != self.organization_ids
                    or not isinstance(saved["records"], list)):
                raise ValueError("Observation store belongs to another run or recipient set")
            for row in saved["records"]:
                self._insert(row, persist=False)

    def deliver(self, *, run_id: str, event_id: str, organization_id: str, payload: dict) -> bool:
        row = {"run_id": run_id, "event_id": event_id, "organization_id": organization_id,
               "payload": deepcopy(payload)}
        with self._lock:
            return self._insert(row, persist=True)

    def _insert(self, row: dict, *, persist: bool) -> bool:
        if (not isinstance(row, dict)
                or set(row) != {"run_id", "event_id", "organization_id", "payload"}):
            raise ValueError("Observation requires its exact event, run, recipient and payload fields")
        if (row["run_id"] != self.run_id or not isinstance(row["organization_id"], str)
                or row["organization_id"] not in self.organization_ids):
            raise ValueError("Observation run or recipient mismatch")
        if not isinstance(row["event_id"], str) or not row["event_id"].strip():
            raise ValueError("Stable event identity is required")
        if not isinstance(row["payload"], dict):
            raise ValueError("Observation payload must be a projection")
        digest = observation_digest(row)
        key = (row["event_id"], row["organization_id"])
        prior = self._records.get(key)
        if prior is not None:
            # JSON booleans and numbers are distinct event contents even when
            # Python compares their decoded values as equal (True == 1).
            if observation_digest(prior) != digest:
                raise ValueError("Immutable observation changed for an existing event and recipient")
            return False
        self._records[key] = deepcopy(row)
        if persist and self.path is not None:
            try:
                atomic_json(self.path, {"schema_version": "observation-inbox.v1", "run_id": self.run_id,
                                       "organization_ids": sorted(self.organization_ids),
                                       "records": list(self._records.values())})
            except Exception:
                del self._records[key]
                raise
        return True

    def for_organization(self, *, run_id: str, organization_id: str) -> list[dict]:
        if run_id != self.run_id or organization_id not in self.organization_ids:
            raise ValueError("Observation run or recipient mismatch")
        with self._lock:
            return deepcopy([row for row in self._records.values()
                             if row["organization_id"] == organization_id])


class GbaV1OwnEventProjection:
    """Only named own-enterprise events are supported by this initial policy.

    Whole project snapshots and unclassified event data never enter memory.
    Additional business events require their own verified projection policy.
    """

    FIELDS = {
        "agent_operation": ("operation", "label", "description", "available_resource",
                            "capability_update", "decision_source"),
        "agent_engaged": ("role", "resource_amount"),
        "agent_recalled": ("role",),
        "agent_standby": ("role",),
        "agent_released": ("role",),
        "agent_terminated": ("role",),
        "contractor_tender_decision": ("final_submit_bid", "advisor_adjusted_probability", "decision_advisor"),
        "bid_submitted": ("contractor_id", "bid_price", "expected_profit", "risk_level", "bid_probability", "decision_advisor"),
        "bid_declined": ("contractor_id", "decline_reason", "expected_profit", "risk_level", "bid_probability", "decision_advisor"),
    }

    def __call__(self, observation, organization_ids) -> dict[str, dict]:
        if (observation.event_type=='agent_operation' and organization_ids.get(observation.agent_id)=='Government'
                and observation.data.get('operation') in {'review_policy_feedback','adjust_regulatory_focus','monitor_compliance','publish_guidelines'}):
            from integration.government_monthly_native_sources import project_monthly_feedback_event
            return project_monthly_feedback_event(observation,organization_ids)
        if observation.event_type in {'project_opportunity_initiated','project_opportunity_declined'}:
            from integration.owner_opportunity_native_feedback import project_owner_opportunity_event
            return project_owner_opportunity_event(observation,organization_ids)
        if observation.event_type=='supplier_selection_failed':
            from integration.procurement_failure_followup import project_failure_event
            return project_failure_event(observation,organization_ids)
        if observation.event_type in {'supplier_order_decision','supplier_selected'}:
            from integration.supplier_order_native_feedback import project_supply_event
            return project_supply_event(observation,organization_ids)
        if observation.event_type in {'regulatory_review_decision','approval_approved','approval_rejected'}:
            from integration.government_intake_feedback import project_government_event
            return project_government_event(observation,organization_ids)
        if observation.event_type in {'bank_financing_decision', 'project_financing_selected', 'project_financing_deferred'}:
            from integration.project_financing_feedback import project_financing_event
            return project_financing_event(observation, organization_ids)
        if observation.event_type in {'appointment_decision', 'consultant_team_appointed'}:
            from integration.professional_intake_feedback import project_professional_event
            return project_professional_event(observation, organization_ids)
        if observation.event_type == 'tender_opened':
            from integration.owner_invitation_feedback import project_owner_invitation_event
            return project_owner_invitation_event(observation, organization_ids)
        if observation.event_type in {'contractor_tender_decision', 'bid_submitted', 'bid_declined'}:
            from integration.bindings.gba_v1_tender_feedback import project_tender_event
            return project_tender_event(observation, organization_ids)
        if (not observation.committed or observation.event_type not in self.FIELDS
                or observation.agent_id not in organization_ids):
            return {}
        return {observation.agent_id: {
            "event_type": observation.event_type, "tick": observation.tick,
            "project_id": observation.project_id, "agent_id": observation.agent_id,
            "committed": True,
            "data": {key: deepcopy(observation.data[key])
                     for key in self.FIELDS[observation.event_type] if key in observation.data},
        }}
