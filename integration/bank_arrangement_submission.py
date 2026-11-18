"""Explicit BANK-A05 arrangement registration and original receipt query."""
from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks

BankArrangementSubmissionCallbacks = BankSubmissionCallbacks


class BankArrangementSubmission(BankResultSubmission):
    """Submit host-supported original confirm, requote or decline decisions.

    Original signed-offer version, independently received borrower acceptance,
    accepted terms and condition stages remain in the saved input/result/source
    evidence. The application revalidates actual formation authority, consent,
    validity and current capacity before transport. Registration acceptance
    does not establish arrangement effectiveness or verified draw conditions;
    actual arrangement/terms retain their separate A05 to A06 source handoff.
    """
    VERSION = 'bank-arrangement-submission.v1'
    ACTION_ID = 'BANK-A05'
    METADATA_PREFIX = 'bank_arrangement_submission:'
    RECEIPT_SCHEMA = 'bank-arrangement-saved-receipt.v1'
    RECEIPT_LIMITATION = 'An arrangement registration receipt does not prove effectiveness, condition verification, draw approval or disbursement.'
