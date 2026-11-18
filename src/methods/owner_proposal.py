"""Exact checks and ordinal selection of declared private proposal candidates."""
from decimal import Decimal
from fractions import Fraction
import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import Known, Measured, Money, Reference, StrictRecord, TextId, ValueState, ref_type


SCALE_METHOD = ref_type("Method")(kind="Method", id="micro.owner.declared_scale_bounds", version="1")
PROPOSAL_METHOD = ref_type("Method")(kind="Method", id="micro.owner.declared_proposal_priority", version="1")


class ProposalScaleInput(StrictRecord):
    lower: ValueState[Measured]
    upper: ValueState[Measured]
    applicability: Literal["range", "not_applicable"]
    minimum: Measured | None
    maximum: Measured | None
    applicability_rule_ref: ref_type("Rule") | None
    source_refs: Annotated[list[Reference], Field(min_length=1)]
    basis_refs: Annotated[list[ref_type("Evidence")], Field(min_length=1)]

    @model_validator(mode="after")
    def declared_domain(self):
        if self.applicability == "not_applicable":
            if (self.minimum is not None or self.maximum is not None or self.applicability_rule_ref is None
                    or any(state.state != "not_applicable" or state.rule_ref != self.applicability_rule_ref for state in (self.lower, self.upper))):
                raise ValueError("Non-applicable scale requires the same explicit rule and no invented bounds")
        else:
            if self.minimum is None or self.maximum is None or self.applicability_rule_ref is not None:
                raise ValueError("Scale range needs explicit declared bounds")
            if self.minimum.unit != self.maximum.unit or Decimal(self.minimum.value) < 0 or Decimal(self.minimum.value) > Decimal(self.maximum.value):
                raise ValueError("Scale method bounds must be nonnegative, ordered and use one unit")
            for state in (self.lower, self.upper):
                if state.state not in {"known", "unknown"}:
                    raise ValueError("Scale range supports known or unknown endpoints")
                if isinstance(state, Known) and (state.value.unit != self.minimum.unit or Decimal(state.value.value) < 0):
                    raise ValueError("Scale endpoint requires the method's exact unit and nonnegative value")
            if isinstance(self.lower, Known) and isinstance(self.upper, Known) and Decimal(self.lower.value.value) > Decimal(self.upper.value.value):
                raise ValueError("Scale lower exceeds upper")
        return self


class ProposalScaleReport(StrictRecord):
    applicable: bool
    fits_known_bounds: bool
    unknown_endpoints: list[Literal["lower", "upper"]]


def check_scale(data: ProposalScaleInput) -> ProposalScaleReport:
    if data.applicability == "not_applicable":
        return ProposalScaleReport(applicable=False, fits_known_bounds=True, unknown_endpoints=[])
    low, high = Fraction(Decimal(data.minimum.value)), Fraction(Decimal(data.maximum.value))
    unknown, fits = [], True
    for name in ("lower", "upper"):
        state = getattr(data, name)
        if isinstance(state, Known):
            fits = fits and low <= Fraction(Decimal(state.value.value)) <= high
        else:
            unknown.append(name)
    return ProposalScaleReport(applicable=True, fits_known_bounds=fits, unknown_endpoints=unknown)


class ProposalRankCandidate(StrictRecord):
    local_key: TextId
    priority: int
    review_cost: Money
    review_effort: Measured


class ProposalPriorityInput(StrictRecord):
    maximum_briefs: Annotated[int, Field(ge=0, le=64)]
    available_cash: Money
    available_effort: Measured
    candidates: Annotated[list[ProposalRankCandidate], Field(max_length=64)]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode="after")
    def known_compatible_limits(self):
        if len({row.local_key for row in self.candidates}) != len(self.candidates):
            raise ValueError("Proposal candidate identity repeated")
        if Decimal(self.available_cash.value) < 0 or Decimal(self.available_effort.value) < 0:
            raise ValueError("Available review budgets cannot be negative")
        for row in self.candidates:
            if (row.review_cost.currency != self.available_cash.currency or row.review_effort.unit != self.available_effort.unit
                    or Decimal(row.review_cost.value) < 0 or Decimal(row.review_effort.value) < 0):
                raise ValueError("Proposal review needs identical units/currency and nonnegative sourced demand")
        return self


class ProposalPriorityReport(StrictRecord):
    selected_keys: list[TextId]
    ambiguous_keys: list[TextId]
    excluded_keys: list[TextId]


def select_proposals(data: ProposalPriorityInput) -> ProposalPriorityReport:
    cash, effort = Fraction(Decimal(data.available_cash.value)), Fraction(Decimal(data.available_effort.value))
    selected, excluded = [], []
    # Lower ordinal priority is preferred. Equal-priority candidates are a group;
    # never break an infeasible tie using enumeration order or invented utility.
    for priority in sorted({row.priority for row in data.candidates}):
        group = [row for row in data.candidates if row.priority == priority]
        fitting = []
        for row in group:
            if (Fraction(Decimal(row.review_cost.value)) > cash or Fraction(Decimal(row.review_effort.value)) > effort
                    or len(selected) == data.maximum_briefs):
                excluded.append(row.local_key)
            else:
                fitting.append(row)
        cost = sum((Fraction(Decimal(row.review_cost.value)) for row in fitting), Fraction())
        load = sum((Fraction(Decimal(row.review_effort.value)) for row in fitting), Fraction())
        if len(selected) + len(fitting) > data.maximum_briefs or cost > cash or load > effort:
            return ProposalPriorityReport(selected_keys=selected, ambiguous_keys=sorted(row.local_key for row in fitting), excluded_keys=sorted(excluded))
        selected.extend(row.local_key for row in sorted(fitting, key=lambda row: row.local_key))
        cash -= cost
        effort -= load
    return ProposalPriorityReport(selected_keys=selected, ambiguous_keys=[], excluded_keys=sorted(excluded))


def register_owner_proposal_methods(registry):
    basis = Path(__file__).with_name("OWNER_PROPOSAL.md")
    for ref, inputs, outputs, executor, code, domain in (
        (SCALE_METHOD, ProposalScaleInput, ProposalScaleReport, check_scale, "scale",
            ["Declared inclusive scale bounds with identical units", "Unknown endpoints remain unknown", "Explicit sourced rule for non-applicability"]),
        (PROPOSAL_METHOD, ProposalPriorityInput, ProposalPriorityReport, select_proposals, "priority",
            ["At most 64 supplied private candidates and briefs", "Explicit ordinal priorities", "Known point-in-time review cash and effort budgets", "Equal-priority ambiguity remains explicit"]),
    ):
        registry.register({"method_ref": ref, "namespace": "micro_local", "effect_kind": "pure_calculation", "invocation": "trusted_processor",
            "input_schema_id": f"micro-owner-proposal.v1:{code}:input", "output_schema_id": f"micro-owner-proposal.v1:{code}:report",
            "action_ids": ["OWN-A16"], "support_domain": domain, "unit_rule": "exact_declared_units_no_conversion",
            "basis_locator": "src/methods/OWNER_PROPOSAL.md", "basis_sha256": hashlib.sha256(basis.read_bytes()).hexdigest(),
            "calibration": "mathematical_only", "limitations": ["No demand forecasting, valuation, engineering scale estimation or inferred preferences",
                "Review budgets and ordinal priorities are sourced scenario assumptions, not actual spending or resource reservations",
                "No land rights, investment approval, financing, technology selection or formal project"]}, inputs, outputs, executor)
