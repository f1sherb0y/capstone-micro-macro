"""Explicit BANK-A02 native binding; no fabricated endpoint or loan effects."""
from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks

# Preserve the existing public callback name and protocol.
BankIntakeSubmissionCallbacks = BankSubmissionCallbacks


class BankIntakeSubmission(BankResultSubmission):
    """Submit a saved formal intake decision; no inferred approval or loan."""
    VERSION = 'bank-intake-submission.v1'
    ACTION_ID = 'BANK-A02'
    METADATA_PREFIX = 'bank_intake_submission:'
    RECEIPT_SCHEMA = 'bank-intake-saved-receipt.v1'
    RECEIPT_LIMITATION = 'An intake receipt does not prove risk approval, loan formation, funding or payment.'
