"""Exact limited-study budget checks with explicit one-plan ordinal selection."""
from decimal import Decimal
from fractions import Fraction
import hashlib
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from src.actions.contracts.common import Money, Reference, StrictRecord, TextId, ref_type

STUDY_METHOD = ref_type("Method")(kind="Method", id="micro.owner.declared_study_budget", version="1")


class StudyBudgetCandidate(StrictRecord):
    local_key: TextId
    priority: int
    expenditure_cap: Money
    future_cost: Money
    incurred_cost: Money
    prior_cap: Money | None


class StudyBudgetInput(StrictRecord):
    spending_limit: Money
    available_cash: Money
    candidates: Annotated[list[StudyBudgetCandidate], Field(max_length=64)]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode="after")
    def exact_domain(self):
        if len({row.local_key for row in self.candidates}) != len(self.candidates):
            raise ValueError("Study candidate repeated")
        amounts = [self.spending_limit, self.available_cash]
        for row in self.candidates:
            amounts.extend([row.expenditure_cap, row.future_cost, row.incurred_cost])
            if row.prior_cap is not None: amounts.append(row.prior_cap)
            elif Decimal(row.incurred_cost.value) != 0:
                raise ValueError("New study cannot inherit an unassociated incurred amount")
        if any(amount.currency != self.spending_limit.currency or Decimal(amount.value) < 0 for amount in amounts):
            raise ValueError("Study amounts require one currency and nonnegative explicit values")
        if any(Decimal(row.expenditure_cap.value) <= 0 for row in self.candidates):
            raise ValueError("A limited task requires a positive expenditure cap")
        return self


class StudyBudgetReport(StrictRecord):
    selected_key: TextId | None
    ambiguous_keys: list[TextId]
    excluded_keys: list[TextId]


def select_study(data: StudyBudgetInput) -> StudyBudgetReport:
    amount = lambda value: Fraction(Decimal(value.value))
    feasible, excluded = [], []
    for row in data.candidates:
        cap = amount(row.expenditure_cap)
        if (cap > amount(data.spending_limit) or amount(row.incurred_cost) + amount(row.future_cost) > cap
                or amount(row.future_cost) > amount(data.available_cash)
                or row.prior_cap is not None and cap > amount(row.prior_cap)):
            excluded.append(row.local_key)
        else:
            feasible.append(row)
    if not feasible:
        return StudyBudgetReport(selected_key=None, ambiguous_keys=[], excluded_keys=sorted(excluded))
    preferred = min(row.priority for row in feasible)
    tied = sorted(row.local_key for row in feasible if row.priority == preferred)
    return StudyBudgetReport(selected_key=tied[0] if len(tied) == 1 else None,
                             ambiguous_keys=tied if len(tied) > 1 else [], excluded_keys=sorted(excluded))


def register_owner_study_method(registry):
    basis = Path(__file__).with_name("OWNER_STUDY.md")
    registry.register({"method_ref": STUDY_METHOD, "namespace": "micro_local", "effect_kind": "pure_calculation",
        "invocation": "trusted_processor", "input_schema_id": "micro-owner-study.v1:input", "output_schema_id": "micro-owner-study.v1:report",
        "action_ids": ["OWN-A02"], "support_domain": ["Up to 64 explicitly supplied study candidates", "One currency and exact nonnegative amounts",
            "One plan per invocation; explicit ascending ordinal priority", "Prior incurred costs count within a narrowed cap; future cost compared to current free cash"],
        "unit_rule": "exact_declared_units_no_conversion", "basis_locator": "src/methods/OWNER_STUDY.md",
        "basis_sha256": hashlib.sha256(basis.read_bytes()).hexdigest(), "calibration": "mathematical_only",
        "limitations": ["No estimation of consulting fees, cash forecasts or inferred preferences", "No spending, debt settlement, task creation or resource reservation",
            "Actual fees, funding, authority, resource productivity and reassessment triggers require trusted sourced projections"]},
        StudyBudgetInput, StudyBudgetReport, select_study)
