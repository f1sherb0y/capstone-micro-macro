"""Explicit BANK-A13 advisory delivery/registration and original receipt query."""
from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks

BankAdviceSubmissionCallbacks = BankSubmissionCallbacks


class BankAdviceSubmission(BankResultSubmission):
    """Submit original indicative_opinion or decline_advice to actual recipients.

    Authorized advisory scope, borrower disclosure state, assumptions, source
    basis and unsupported/unknown funding information remain in the saved
    input/result/cache. The application validates current consultation/delivery
    authority, intended recipient and original opinion identity before using
    its actual delivery or advisory registration endpoint. No missing financing
    plan is filled and no conditional opinion becomes a quotation or commitment.
    Registration acceptance does not independently establish receipt by the
    recipient, adoption of advice or availability of financing.
    """
    VERSION = 'bank-advice-submission.v1'
    ACTION_ID = 'BANK-A13'
    METADATA_PREFIX = 'bank_advice_submission:'
    RECEIPT_SCHEMA = 'bank-advice-saved-receipt.v1'
    RECEIPT_LIMITATION = 'Advisory registration does not prove recipient delivery/adoption, financing commitment, quote, capacity reservation or funds.'
