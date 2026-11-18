"""Explicit capability and call evidence for the bundled macro boundary."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from copy import deepcopy
import threading
from typing import Any


@dataclass(frozen=True)
class MacroCapability:
    name: str
    status: str
    component: str | None
    reason: str | None = None


class MacroBindingError(RuntimeError):
    """Raised when a caller requests a macro capability that is not bound."""


class MacroBinding:
    """Record only capabilities that are proven by the supplied macro object.

    The adapter never invents a ``propose`` method.  The public GBA package
    exposes ``decide`` on its provider and event observers for feedback; a
    proposal is produced by the micro procurement executor and remains a
    separate boundary.
    """

    def __init__(self, provider: Any):
        self.provider = provider
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._engine_id = None
        self.capabilities = self._inspect(provider)

    @staticmethod
    def _inspect(provider: Any) -> dict[str, MacroCapability]:
        component = f"{type(provider).__module__}.{type(provider).__qualname__}" if provider is not None else None
        decide = callable(getattr(provider, "decide", None))
        return {
            "propose": MacroCapability("propose", "unsupported", None,
                                        "This provider-only legacy path does not bind the macro module propose entry point"),
            "decide": MacroCapability("decide", "bound" if decide else "unsupported", component,
                                      None if decide else "Provider does not implement decide"),
            "observe": MacroCapability("observe", "unsupported", None,
                                        "No procurement event observer has been attached"),
        }

    def require(self, name: str) -> MacroCapability:
        try:
            capability = self.capabilities[name]
        except KeyError as exc:
            raise MacroBindingError(f"Unknown macro capability: {name}") from exc
        if capability.status != "bound":
            raise MacroBindingError(f"Macro capability {name!r} is not bound: {capability.reason}")
        return capability

    def decide(self, agent, context):
        capability = self.require("decide")
        record = {"capability": "decide", "component": capability.component,
                  "agent_id": getattr(agent, "agent_id", None),
                  "request_id": context.get("request_id"), "status": "started"}
        with self._lock:
            self.calls.append(record)
        try:
            result = self.provider.decide(agent, context)
        except Exception as exc:
            with self._lock:
                record.update(status="failed", error_type=type(exc).__name__)
            raise
        with self._lock:
            record.update(status="returned", action_type=getattr(result, "action_type", None))
        return result

    def bind_observer(self, engine_id: str, component: str) -> None:
        with self._lock:
            if self._engine_id is not None and self._engine_id != engine_id:
                raise MacroBindingError("A legacy binding cannot be shared between simulations")
            self._engine_id = engine_id
            self.capabilities["observe"] = MacroCapability("observe", "bound", component)

    @property
    def macro_binding(self):
        return self

    def observe(self, event_id: str, recipients: list[str], payload: dict[str, Any]) -> None:
        capability = self.require("observe")
        with self._lock:
            self.calls.append({"capability": "observe", "component": capability.component,
                               "event_id": event_id, "recipients": list(recipients),
                               "event_type": payload.get("event_type"), "status": "recorded"})

    def evidence(self) -> dict[str, Any]:
        with self._lock:
            return {"schema_version": "macro-binding.v1", "mode": "legacy_procurement",
                    "simulation_id": self._engine_id,
                    "capabilities": {key: asdict(value) for key, value in self.capabilities.items()},
                    "calls": deepcopy(self.calls)}
