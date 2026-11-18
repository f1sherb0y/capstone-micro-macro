"""QS fee recovery binds shared arithmetic to original QS sources and authority."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.qs_billing_objects import qs_billing_types
from src.actions.roles.qs_billing import handle_qs_fees
from src.coordination.continuations import ConditionProfile
from src.coordination.engineer_billing_conditions import (
    CONDITIONS_CODE, CLAIM_CODE, REMINDER_CODE, LEDGER_CODE,
    EngineerBillingConditionReading, ServiceBillingRecoveryPolicy,
    _check_engineer_billing_history, check_engineer_billing_internal_cost,
)
from src.coordination.tasks import TaskConflict


INTERNAL_CODE = 'internal_qs_costs_require_actual_work_accounting_without_self_fee_claim'
CONDITION_KINDS = {CONDITIONS_CODE: 'BillingClause', CLAIM_CODE: 'FeeClaim',
    REMINDER_CODE: 'FeeClaim', LEDGER_CODE: 'FeeClaim', INTERNAL_CODE: 'Engagement'}


@dataclass(frozen=True)
class QSBillingConditionReading(EngineerBillingConditionReading):
    """Actual QS invocation snapshots; no engineering action identity is substituted."""


QS_POLICY = ServiceBillingRecoveryPolicy('QS-A10', 'QS', QSBillingConditionReading,
    handle_qs_fees, qs_billing_types(), INTERNAL_CODE)


def check_qs_billing_history(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code == INTERNAL_CODE:
        return check_engineer_billing_internal_cost(check, selected, validate_relation,
            terminal=terminal, policy=QS_POLICY)
    return _check_engineer_billing_history(check, selected, validate_relation,
        terminal=terminal, policy=QS_POLICY)


def check_qs_billing_claim(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code != CLAIM_CODE:
        raise TaskConflict('QS claim archival substitutes the original duplicate-query wait')
    return check_qs_billing_history(check, selected, validate_relation, terminal=terminal)


def check_qs_billing_receipts(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code not in {REMINDER_CODE, LEDGER_CODE}:
        raise TaskConflict('QS receipt archival substitutes the original reminder or recognition wait')
    return check_qs_billing_history(check, selected, validate_relation, terminal=terminal)


def check_qs_billing_internal_cost(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code != INTERNAL_CODE:
        raise TaskConflict('QS cost archival substitutes the original internal accounting wait')
    return check_qs_billing_history(check, selected, validate_relation, terminal=terminal)


def qs_original_billing_profile(read_current, validate_relation, condition_code=CONDITIONS_CODE):
    if condition_code not in CONDITION_KINDS or not callable(read_current) or not callable(validate_relation):
        raise ValueError('QS fee recovery requires actual guarded sources and independent native validation')

    def evaluate(check):
        if check.condition.condition_code != condition_code:
            raise TaskConflict('QS billing profile substitutes its original wait')
        selected = read_current(deepcopy(check))
        try:
            return check_qs_billing_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('QS-A10', condition_code, '1', frozenset({'dependency_change'}), evaluate)
