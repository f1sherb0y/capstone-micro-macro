"""Recheck original BANK-A10 debt resolution/cash executions before new work."""
from dataclasses import dataclass

from src.actions.contracts.bank_resolution_objects import BankResolutionExecutionView, BankResolutionProfileView
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.references import ActionReadView
from src.coordination.bank_closeout_conditions import _bank_original_finance_execution_profile


@dataclass(frozen=True)
class BankResolutionExecutionConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_ref: Reference
    profile_ref: Reference | None = None


def bank_original_resolution_execution_profile(read_current, validate_relation):
    """Register A10's original resolution/cash dependency wait.

    The host supplies original/current authorized execution versions and an
    independent native query validator under its source/authority boundary.
    Ready only allows preparation of a fresh decision. It grants no enforcement
    right, accepted restructure, accounting writeoff, debt release or cash.
    Unknown/partial payment and unresolved resolution remain waiting; known
    failure can prompt another judgment while retaining existing obligations.
    """
    return _bank_original_finance_execution_profile(read_current, validate_relation,
        action_id='BANK-A10', code='query_original_resolution_or_cash_execution',
        execution_kind='DebtResolutionExecution', execution_schema=BankResolutionExecutionView,
        profile_schema=BankResolutionProfileView,
        reading_type=BankResolutionExecutionConditionReading)
