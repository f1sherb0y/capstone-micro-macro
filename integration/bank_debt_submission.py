"""Explicit BANK-A09 accounting proposal transport and read-only reconciliation."""
from copy import deepcopy

from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks
from src.coordination.tasks import TaskConflict

BankDebtSubmissionCallbacks = BankSubmissionCallbacks


class BankDebtSubmission(BankResultSubmission):
    """Preserve original due, accrual correction and verified receipt allocations.

    The application verifies current original terms, posted periods, append-only
    corrections, actual verified cash/command/event identities and allocation
    deduplication from the saved input/source/method evidence before submitting.
    Reconciliation only queries actual records. Local calculations and native
    proposal registration do not themselves post a ledger or create cash.
    """
    VERSION = 'bank-debt-submission.v1'
    ACTION_ID = 'BANK-A09'
    METADATA_PREFIX = 'bank_debt_submission:'
    RECEIPT_SCHEMA = 'bank-debt-saved-receipt.v1'
    RECEIPT_LIMITATION = 'Accounting proposal acceptance does not prove cash receipt, ledger posting, debt discharge or released funds.'

    def __init__(self, *, worker, binding_id, binding_version, macro_version, supported_choices, callbacks):
        choices = frozenset(supported_choices)
        if 'reconcile' in choices and (not isinstance(callbacks, BankDebtSubmissionCallbacks) or callbacks.query is None):
            raise ValueError('Debt reconciliation requires an explicitly bound read-only original-ledger query')
        super().__init__(worker=worker, binding_id=binding_id, binding_version=binding_version,
            macro_version=macro_version, supported_choices=choices, callbacks=callbacks)

    def _revalidate(self, request):
        if request.output['payload']['choice'] == 'reconcile':
            self._check_request(request)
            if self.callbacks.validate_query(deepcopy(request)) is not True:
                raise TaskConflict('Debt reconciliation requires current own original-ledger read authority')
            return
        return super()._revalidate(request)

    def _submit(self, request):
        self._check_request(request)
        if request.output['payload']['choice'] == 'reconcile':
            return self._query(request)
        return self.callbacks.submit(deepcopy(request))

    def capabilities(self):
        evidence = super().capabilities()
        evidence['branch_transport'] = {choice: 'read_only_query' if choice == 'reconcile' else 'submit_original_proposal'
            for choice in sorted(self.supported_choices)}
        return evidence
