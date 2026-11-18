"""Translate pure capacity results to existing action result branches."""
from src.methods.capacity import CAPACITY_METHOD


class MethodDecisionGap(Exception):
    def __init__(self, result):
        self.result = result


def capacity_feasible(reading, data):
    result = reading.calculate(CAPACITY_METHOD, data)
    if result.kind == "ok":
        return result.value.feasible
    if result.kind == "needs_information":
        raise MethodDecisionGap({"kind": "needs_information", "missing_fields": result.missing_fields, "requested_refs": []})
    if result.kind in {"unsupported", "technical_error"}:
        raise MethodDecisionGap(result.model_dump(mode="python"))
    raise MethodDecisionGap({"kind": "technical_error", "error": {"kind": "unrecorded",
        "correlation_id": "capacity-method-input", "code": "method_input_invalid"}, "retryability": "non_retryable"})
