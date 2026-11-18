"""Explicit BANK-A08 monitoring decision registration and original receipt query."""
from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks

BankMonitoringSubmissionCallbacks = BankSubmissionCallbacks


class BankMonitoringSubmission(BankResultSubmission):
    """Submit only host-supported original monitoring decisions from formal sources.

    Continue, evidence requests, notices and scoped restriction/release retain
    their original meanings. Host validation receives the original report,
    covenant, notice, scope and contractual terms evidence; it must verify
    current measure authority, actual verified facts, independent service and
    remedy deadlines. Continue creates no contractual measure. Pending unknown
    notice delivery remains a pending local result and cannot be submitted as
    a new notice. A registration receipt never substitutes for service evidence
    or proves that a restriction or release became effective.
    """
    VERSION = 'bank-monitoring-submission.v1'
    ACTION_ID = 'BANK-A08'
    METADATA_PREFIX = 'bank_monitoring_submission:'
    RECEIPT_SCHEMA = 'bank-monitoring-saved-receipt.v1'
    RECEIPT_LIMITATION = 'Monitoring registration does not prove verified facts, notice service, remedy expiry or restriction/release effectiveness.'
