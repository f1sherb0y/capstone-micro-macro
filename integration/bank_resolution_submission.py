"""Explicit BANK-A10 resolution proposal transport and original receipt query."""
from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks

BankResolutionSubmissionCallbacks = BankSubmissionCallbacks


class BankResolutionSubmission(BankResultSubmission):
    """Submit only original host-supported remedy, restructure or resolution choices.

    Existing debt, maturity, business keys and actual resolution/cash execution
    identities remain in the original saved evidence. The application checks
    current contractual authority, independent party consent, effectiveness
    conditions, atomic original-debt carry, actual enforcement rights or the
    separate accounting policy appropriate to the original choice. Uncertain
    existing execution stays deferred and cannot be submitted as a new remedy.
    Accounting writeoff does not forgive debt or require collateral execution;
    native registration alone never proves restructure or recovery effects.
    """
    VERSION = 'bank-resolution-submission.v1'
    ACTION_ID = 'BANK-A10'
    METADATA_PREFIX = 'bank_resolution_submission:'
    RECEIPT_SCHEMA = 'bank-resolution-saved-receipt.v1'
    RECEIPT_LIMITATION = 'Resolution registration does not prove consent, effective debt modification, legal enforcement, cash recovery or debt forgiveness.'
