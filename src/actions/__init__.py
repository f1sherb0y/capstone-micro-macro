"""Versioned role actions, independent of macro state storage.

The public classes are loaded lazily so contract and Skill metadata modules can
share the ``src.actions.contracts`` namespace without an import cycle.
"""

__all__ = ["ActionRegistry", "ActionAuditRecord", "ActionRunner", "JsonlActionAuditSink", "run_action"]


def __getattr__(name):
    if name == "ActionRegistry":
        from src.actions.registry import ActionRegistry
        return ActionRegistry
    if name in {"ActionAuditRecord", "ActionRunner", "JsonlActionAuditSink", "run_action"}:
        from src.actions.runner import ActionAuditRecord, ActionRunner, JsonlActionAuditSink, run_action
        return {"ActionAuditRecord": ActionAuditRecord, "ActionRunner": ActionRunner,
                "JsonlActionAuditSink": JsonlActionAuditSink,
                "run_action": run_action}[name]
    raise AttributeError(name)
