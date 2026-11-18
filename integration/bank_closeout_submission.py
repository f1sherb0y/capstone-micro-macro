"""Explicit BANK-A11 scoped closeout proposal transport and original receipt query."""
from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks

BankCloseoutSubmissionCallbacks = BankSubmissionCallbacks


class BankCloseoutSubmission(BankResultSubmission):
    """Submit host-supported retain, close_unused or close_cleared_scope proposals.

    Retained obligations, release candidates, original business key and actual
    close/payment execution identities remain in the saved evidence. The host
    checks current scope authority, actual remaining debt/unknown payments,
    unused commitments and independent release/clearance verification before
    transport. Expiry does not clear debt or security; neither project completion
    nor accounting writeoff proves a cleared loan. Unknown close execution stays
    deferred. Registration acceptance does not release capacity or security,
    delete surviving obligations or replace the actual core closeout history.
    """
    VERSION = 'bank-closeout-submission.v1'
    ACTION_ID = 'BANK-A11'
    METADATA_PREFIX = 'bank_closeout_submission:'
    RECEIPT_SCHEMA = 'bank-closeout-saved-receipt.v1'
    RECEIPT_LIMITATION = 'Closeout registration does not prove cleared debt, released capacity/security or extinction of remaining obligations.'
