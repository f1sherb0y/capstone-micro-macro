"""Explicit BANK-A12 private lesson/future strategy application and receipt query."""
from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks

BankLearningSubmissionCallbacks = BankSubmissionCallbacks


class BankLearningSubmission(BankResultSubmission):
    """Submit host-supported original retain, lesson or future-strategy proposals.

    Actual received mature outcomes, original judgments/information, recipient
    scope, method evidence and applied outcome/business keys remain in the
    saved source cache. The application checks current private-write authority,
    duplicate applications and original allowed future strategy before using
    its actual private-state application endpoint. Pending application stays
    deferred; no financial macro endpoint is inferred. Retain never rewrites
    a judgment, and accepted registration does not prove an applied lesson or
    changed future policy, much less alter existing debt, cash or loan terms.
    """
    VERSION = 'bank-learning-submission.v1'
    ACTION_ID = 'BANK-A12'
    METADATA_PREFIX = 'bank_learning_submission:'
    RECEIPT_SCHEMA = 'bank-learning-saved-receipt.v1'
    RECEIPT_LIMITATION = 'Learning registration does not prove private-state application, risk calibration, future policy effectiveness or changed financial facts.'
