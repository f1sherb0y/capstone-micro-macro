"""Explicit BANK-A03 review registration and receipt query, not financing."""
from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks

BankCreditSubmissionCallbacks = BankSubmissionCallbacks


class BankCreditSubmission(BankResultSubmission):
    """Host submits the original review result, including only declared branches.

    Recommend, conditional and decline remain the original review choices.
    An accepted native registration receipt cannot turn an indicative range,
    condition or decline into an offer, facility, approval or cash reservation.
    Actual recorded assessment/review projections remain independently supplied
    and verified by the existing A03 to A04 handoff.
    """
    VERSION = 'bank-credit-submission.v1'
    ACTION_ID = 'BANK-A03'
    METADATA_PREFIX = 'bank_credit_submission:'
    RECEIPT_SCHEMA = 'bank-credit-saved-receipt.v1'
    RECEIPT_LIMITATION = 'A review registration receipt does not prove a quote, approved facility, loan, reservation or funding.'
