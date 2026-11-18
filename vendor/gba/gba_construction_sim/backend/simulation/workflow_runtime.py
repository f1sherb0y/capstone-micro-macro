from copy import deepcopy
from typing import Any, Dict, Iterable, Optional

from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.services.policy_service import policy_service
from gba_construction_sim.backend.simulation.event_system import EventSystem


def _model_fields(model_type: type) -> set[str]:
    fields = getattr(model_type, "model_fields", None)
    if fields is None:
        fields = getattr(model_type, "__fields__", {})
    return set(fields)


POLICY_FIELDS = _model_fields(PolicyRegime)
ENVIRONMENT_FIELDS = _model_fields(MacroEnvironment)


def _as_dict(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _first_value(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def normalize_workflow_configuration(workflow: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return one canonical schedule while retaining the original workflow payload."""

    normalized = deepcopy(workflow or {})
    configuration = normalized.get("configuration") or {}

    raw_periods = configuration.get("periods")
    if raw_periods is None:
        raw_periods = normalized.get("phases") or normalized.get("periods") or []
    phases = []
    for index, row in enumerate(raw_periods or []):
        row = deepcopy(row or {})
        start_tick = max(0, _integer(_first_value(row, "start_tick", "startTick", "start"), 0))
        end_tick = max(
            start_tick + 1,
            _integer(_first_value(row, "end_tick", "endTick", "end"), start_tick + 1),
        )
        phases.append(
            {
                **row,
                "phase_id": _first_value(row, "phase_id", "period_id", "id", default=f"PH{index + 1:03d}"),
                "name": _first_value(row, "name", "title", default=f"Period {index + 1}"),
                "start_tick": start_tick,
                "end_tick": end_tick,
                "phase_type": _first_value(row, "phase_type", "stage", "type", default="simulation"),
            }
        )

    raw_policies = configuration.get("policies")
    if raw_policies is None:
        raw_policies = normalized.get("interventions") or normalized.get("policies") or []
    interventions = []
    for index, row in enumerate(raw_policies or []):
        row = deepcopy(row or {})
        apply_tick = max(
            0,
            _integer(_first_value(row, "apply_tick", "start_tick", "startTick", "tick", "start"), 0),
        )
        end_value = _first_value(row, "end_tick", "endTick", "end")
        end_tick = max(apply_tick + 1, _integer(end_value, apply_tick + 1)) if end_value is not None else None
        intervention = {
            **row,
            "intervention_id": _first_value(
                row,
                "intervention_id",
                "id",
                default=f"INT{index + 1:03d}",
            ),
            "name": _first_value(row, "name", "title", default=f"Policy {index + 1}"),
            "apply_tick": apply_tick,
        }
        if end_tick is not None:
            intervention["end_tick"] = end_tick
        interventions.append(intervention)

    raw_events = configuration.get("events")
    if raw_events is None:
        raw_events = normalized.get("events") or normalized.get("external_events") or []
    events = []
    for index, row in enumerate(raw_events or []):
        row = deepcopy(row or {})
        tick = max(0, _integer(_first_value(row, "tick", "start_tick", "startTick", "start"), 0))
        events.append(
            {
                **row,
                "event_id": _first_value(row, "event_id", "id", default=f"WFE{index + 1:03d}"),
                "name": _first_value(row, "name", "title", default=f"External Event {index + 1}"),
                "tick": tick,
                "event_type": _first_value(row, "event_type", "type", default="external_event"),
            }
        )

    normalized["phases"] = sorted(phases, key=lambda row: (row["start_tick"], row["end_tick"]))
    normalized["interventions"] = sorted(
        interventions,
        key=lambda row: (row["apply_tick"], row.get("end_tick") or 10**9),
    )
    normalized["events"] = sorted(events, key=lambda row: row["tick"])
    normalized["configuration"] = {
        **configuration,
        "periods": deepcopy(normalized["phases"]),
        "policies": deepcopy(normalized["interventions"]),
        "events": deepcopy(normalized["events"]),
    }
    return normalized


class WorkflowRuntimeController:
    """Apply scheduled periods, policy regimes, and explicit environment events per tick."""

    def __init__(
        self,
        workflow: Optional[Dict[str, Any]],
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        events: EventSystem,
    ) -> None:
        self.workflow = normalize_workflow_configuration(workflow)
        self.policy = policy
        self.macro_environment = macro_environment
        self.events = events
        self.baseline_policy = _as_dict(policy)
        self.baseline_environment = _as_dict(macro_environment)
        self.current_period: Optional[Dict[str, Any]] = None
        self.active_interventions: list[Dict[str, Any]] = []
        self.triggered_event_ids: set[str] = set()
        self.last_applied_events: list[Dict[str, Any]] = []
        self._previous_period_id: Optional[str] = None
        self._previous_intervention_ids: set[str] = set()

    def apply_tick(self, tick: int) -> Dict[str, Any]:
        self.current_period = self._period_at(tick)
        self.active_interventions = self._interventions_at(tick)
        self._apply_policy(self.active_interventions)
        self.last_applied_events = self._apply_events(tick)
        self._record_schedule_transitions(tick)
        return self.state()

    def state(self) -> Dict[str, Any]:
        return {
            "current_period": deepcopy(self.current_period),
            "active_interventions": [self._intervention_summary(row) for row in self.active_interventions],
            "triggered_event_ids": sorted(self.triggered_event_ids),
            "events_applied_this_tick": deepcopy(self.last_applied_events),
            "effective_policy": _as_dict(self.policy),
            "macro_environment": _as_dict(self.macro_environment),
            "configured_counts": {
                "periods": len(self.workflow.get("phases") or []),
                "policies": len(self.workflow.get("interventions") or []),
                "events": len(self.workflow.get("events") or []),
            },
        }

    def _period_at(self, tick: int) -> Optional[Dict[str, Any]]:
        periods = self.workflow.get("phases") or []
        for period in periods:
            if period["start_tick"] <= tick < period["end_tick"]:
                return period
        if periods and tick == periods[-1]["end_tick"]:
            return periods[-1]
        return None

    def _interventions_at(self, tick: int) -> list[Dict[str, Any]]:
        active = []
        for intervention in self.workflow.get("interventions") or []:
            end_tick = intervention.get("end_tick")
            if tick >= intervention["apply_tick"] and (end_tick is None or tick < end_tick):
                active.append(intervention)
        return active

    def _apply_policy(self, interventions: Iterable[Dict[str, Any]]) -> None:
        effective = deepcopy(self.baseline_policy)
        for intervention in interventions:
            policy_id = intervention.get("policy_id")
            if policy_id:
                try:
                    policy_detail = policy_service.get_policy(str(policy_id))
                    if policy_detail.get("policy_id") == str(policy_id):
                        effective.update(policy_detail.get("parameters") or {})
                        effective["policy_id"] = str(policy_id)
                except (KeyError, IndexError, ValueError):
                    pass
            effective.update(self._inline_policy_parameters(intervention))
            if intervention.get("name"):
                effective["name"] = str(intervention["name"])
        for field in POLICY_FIELDS:
            if field in effective:
                setattr(self.policy, field, effective[field])

    @staticmethod
    def _inline_policy_parameters(intervention: Dict[str, Any]) -> Dict[str, Any]:
        parameters: Dict[str, Any] = {}
        for key in ("parameters", "policy_parameters", "parameter_changes"):
            value = intervention.get(key)
            if isinstance(value, dict):
                parameters.update(value)
        for field in POLICY_FIELDS:
            if field in intervention:
                parameters[field] = intervention[field]
        return {key: value for key, value in parameters.items() if key in POLICY_FIELDS}

    def _apply_events(self, tick: int) -> list[Dict[str, Any]]:
        applied = []
        for event in self.workflow.get("events") or []:
            event_id = str(event["event_id"])
            if event["tick"] != tick or event_id in self.triggered_event_ids:
                continue
            declared_changes = self._event_changes(event)
            applied_changes: Dict[str, Any] = {}
            for field, specification in declared_changes.items():
                if field not in ENVIRONMENT_FIELDS or field == "current_tick":
                    continue
                before = getattr(self.macro_environment, field)
                after = self._apply_change(before, specification)
                setattr(self.macro_environment, field, after)
                applied_changes[field] = {"before": before, "after": after}
            self.triggered_event_ids.add(event_id)
            event_result = {
                "event_id": event_id,
                "name": event.get("name"),
                "declared_changes": declared_changes,
                "applied_changes": applied_changes,
                "quantitative_effect_applied": bool(applied_changes),
            }
            applied.append(event_result)
            self.events.record(
                tick,
                "workflow_external_event",
                str(event.get("description") or event.get("note") or event.get("name") or event_id),
                data={**event_result, "source_event": deepcopy(event)},
            )
        return applied

    @staticmethod
    def _event_changes(event: Dict[str, Any]) -> Dict[str, Any]:
        changes: Dict[str, Any] = {}
        for key in ("environment_changes", "macro_environment", "parameter_changes"):
            value = event.get(key)
            if isinstance(value, dict):
                changes.update(value)
        return changes

    @staticmethod
    def _apply_change(before: Any, specification: Any) -> Any:
        if not isinstance(specification, dict):
            return specification
        operation = str(specification.get("operation") or specification.get("op") or "set").lower()
        value = specification.get("value")
        if operation in {"add", "increase", "delta"}:
            return before + value
        if operation in {"multiply", "scale"}:
            return before * value
        return value

    def _record_schedule_transitions(self, tick: int) -> None:
        period_id = str(self.current_period.get("phase_id")) if self.current_period else None
        if period_id != self._previous_period_id and self.current_period:
            self.events.record(
                tick,
                "workflow_period_started",
                f"Workflow entered {self.current_period['name']}",
                data={"period": deepcopy(self.current_period)},
            )
        self._previous_period_id = period_id

        current_ids = {str(row["intervention_id"]) for row in self.active_interventions}
        for intervention in self.active_interventions:
            intervention_id = str(intervention["intervention_id"])
            if intervention_id not in self._previous_intervention_ids:
                self.events.record(
                    tick,
                    "policy_intervention_started",
                    f"Policy intervention {intervention.get('name') or intervention_id} became active",
                    data={"intervention": self._intervention_summary(intervention)},
                )
        for intervention_id in sorted(self._previous_intervention_ids - current_ids):
            self.events.record(
                tick,
                "policy_intervention_ended",
                f"Policy intervention {intervention_id} ended",
                data={"intervention_id": intervention_id},
            )
        self._previous_intervention_ids = current_ids

    @staticmethod
    def _intervention_summary(intervention: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: deepcopy(intervention.get(key))
            for key in (
                "intervention_id",
                "policy_id",
                "name",
                "apply_tick",
                "end_tick",
                "target_scope",
                "target_roles",
                "target_regions",
            )
            if key in intervention
        }
