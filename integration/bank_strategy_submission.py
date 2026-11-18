"""Explicit BANK-A01 new-business strategy application and original receipt query."""
from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks

BankStrategySubmissionCallbacks = BankSubmissionCallbacks


class BankStrategySubmission(BankResultSubmission):
    """Submit host-supported original retain, revise or investigate decisions.

    Original portfolio, actual capacity/obligations, private signals and allowed
    strategy choices stay in the saved evidence. The application verifies
    current own strategy-write authority, actual capacity and allowed policy
    before using its explicit new-business strategy or investigation endpoint.
    Retain changes no existing records; investigation creates no loan reservation.
    Revision cannot alter old contract terms, commitments or judgments. Native
    registration alone never establishes policy application or lending effects.
    """
    VERSION = 'bank-strategy-submission.v1'
    ACTION_ID = 'BANK-A01'
    METADATA_PREFIX = 'bank_strategy_submission:'
    RECEIPT_SCHEMA = 'bank-strategy-saved-receipt.v1'
    RECEIPT_LIMITATION = 'Strategy registration does not prove policy application, changed existing terms, credit reservation, loan approval or funds.'
