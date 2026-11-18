"""Cross-field rules explicitly stated in the source local-type tables."""
from __future__ import annotations

from decimal import Decimal

from src.actions.contracts.common import Known, Money, Measured


def _keys(items):
    return {item.key() for item in items}


def disjoint(first, second, message):
    if _keys(first) & _keys(second):
        raise ValueError(message)


def validate_local(value):
    name = type(value).__name__
    fields = type(value).model_fields
    for field in fields:
        items = getattr(value, field)
        if isinstance(items, list) and items:
            for key in ("local_key", "line_key"):
                if all(hasattr(item, key) for item in items):
                    keys = [getattr(item, key) for item in items]
                    if len(keys) != len(set(keys)):
                        raise ValueError(f"Duplicate {key} within {field}")
    if "lower" in fields and "upper" in fields:
        if isinstance(value.lower, Known) and isinstance(value.upper, Known):
            lower, upper = value.lower.value, value.upper.value
            if isinstance(lower, (Money, Measured)) and isinstance(upper, type(lower)):
                unit = "currency" if isinstance(lower, Money) else "unit"
                if getattr(lower, unit) != getattr(upper, unit):
                    raise ValueError("Range endpoints must use the same explicit unit or currency")
                if Decimal(lower.value) > Decimal(upper.value):
                    raise ValueError("Range lower exceeds upper")
    if name.endswith("Handover"):
        disjoint(value.release_allocation_refs, value.retain_allocation_refs, "Cannot release and retain the same allocation")
    if name == "ArchitectComparison":
        if not _keys(value.recommended_option_refs) <= _keys(value.option_refs):
            raise ValueError("Recommended option must belong to the compared set")
        if value.recommended_option_refs and value.comparison_method_ref is None:
            raise ValueError("Recommendation requires an applicable comparison method")
    if name == "ArchitectOptionDraft":
        if value.relation == "revision" and value.parent_option_ref is None:
            raise ValueError("Revision requires its parent option version")
    if name == "QSComparison":
        if not _keys(value.ranked_option_refs) <= _keys(value.option_refs):
            raise ValueError("Ranking must be a subset of compared options")
        if value.ranked_option_refs and not value.comparable:
            raise ValueError("Cannot rank incomparable options")
    if name == "QSCostPlan":
        if value.complete_total is not None and (value.missing_items or value.calculation_ref is None):
            raise ValueError("Complete cost total requires calculation and no missing items")
        if not value.lines and isinstance(value.known_subtotal, Known):
            raise ValueError("No calculable lines cannot yield a known subtotal")
    if name == "EngineerCheckItem":
        if value.method_result_ref is None and value.result is not None:
            raise ValueError("Unexecuted check must not report a method result")
    if name == "GovIssueResolution":
        if value.verification_result_ref is None and value.resolution != "unresolved":
            raise ValueError("Closing an issue requires verification evidence")
        disjoint(value.affected_assessment_refs, value.reusable_assessment_refs, "Assessment cannot be invalidated and reused for the same version")
    if name == "GovConditionResult" and value.verification_result_ref is None and value.result != "undetermined":
        raise ValueError("Condition result requires a verification record")
    if name == "GovAssessment":
        if any(check.finding == "conforms" and check.method_result_ref is None for check in value.checks):
            raise ValueError("Conformity requires an executed method record")
    if name == "OwnerCondition" and value.verification == "met" and not value.evidence_refs:
        raise ValueError("Met condition requires authorized evidence")
    if name == "BankCondition" and value.outcome == "satisfied" and not value.evidence_refs:
        raise ValueError("Satisfied bank condition requires evidence")
    nonempty = {
        "OwnerBriefDraft": ("region_ids",), "OwnerRegulatoryApplicationDraft": ("requested_matter_refs",),
        "ContractorMeasurementDraft": ("lines",), "SupplierPaymentClaimDraft": ("lines",),
        "SupplierOfferDraft": ("lines",), "GovCondition": ("responsible_party_ids", "affected_action_refs"),
    }
    for field in nonempty.get(name, ()):
        if not getattr(value, field):
            raise ValueError(f"{name}.{field} must be nonempty")
    if name.startswith("SupplierRescheduleTarget"):
        for field in ("line_refs", "shipment_refs"):
            if field in fields and not getattr(value, field):
                raise ValueError("Reschedule target must be nonempty")
    for field in ("local_key", "line_key"):
        if field in fields and not getattr(value, field).strip():
            raise ValueError(f"{field} must identify a local draft item")
    return value
