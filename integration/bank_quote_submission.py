"""Explicit BANK-A04 quotation registration and original receipt query."""
from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks

BankQuoteSubmissionCallbacks = BankSubmissionCallbacks


class BankQuoteSubmission(BankResultSubmission):
    """Submit only host-supported original quote branches from saved formal sources.

    Original terms, conditions, validity and reservation request remain in the
    saved result. The application validates current actual capacity and native
    quotation authority before transport. A registration receipt does not by
    itself prove a reservation, independently accepted offer or arrangement;
    those actual sources retain their separate A04 to A05 handoff validation.
    """
    VERSION = 'bank-quote-submission.v1'
    ACTION_ID = 'BANK-A04'
    METADATA_PREFIX = 'bank_quote_submission:'
    RECEIPT_SCHEMA = 'bank-quote-saved-receipt.v1'
    RECEIPT_LIMITATION = 'A quote registration receipt does not prove capacity reservation, borrower acceptance, arrangement or funding.'
