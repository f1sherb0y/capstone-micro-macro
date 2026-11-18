"""Explicit BANK-A06 draw-decision registration and original receipt query."""
from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks

BankDrawSubmissionCallbacks = BankSubmissionCallbacks


class BankDrawSubmission(BankResultSubmission):
    """Submit host-supported original approve_draw or decline_draw decisions.

    Approved amount, complete transfer rows, batch identity and condition
    evidence stay in the original saved result and source cache. The host
    revalidates actual facility terms, condition verification, current usage
    including unknown executions and approval authority before transport.
    Registration acceptance does not dispatch payment or establish principal
    drawdown; actual DrawApproval remains independently supplied and checked
    by the existing A06 to A07 source handoff.
    """
    VERSION = 'bank-draw-submission.v1'
    ACTION_ID = 'BANK-A06'
    METADATA_PREFIX = 'bank_draw_submission:'
    RECEIPT_SCHEMA = 'bank-draw-saved-receipt.v1'
    RECEIPT_LIMITATION = 'A draw-decision registration receipt does not prove payment dispatch, executed principal, cash arrival or released usage.'
