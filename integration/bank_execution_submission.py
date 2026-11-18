"""Explicit BANK-A07 command transport and original-execution receipt query."""
from copy import deepcopy

from integration.bank_submission import BankResultSubmission, BankSubmissionCallbacks
from src.coordination.tasks import TaskConflict

BankExecutionSubmissionCallbacks = BankSubmissionCallbacks


class BankExecutionSubmission(BankResultSubmission):
    """Preserve original execute/reconcile/cancel_unexecuted command boundaries.

    Host validation receives the saved input/context/source cache containing
    actual approval, prior executions, command IDs and business keys. execute
    may dispatch only the original initiation; cancel targets only original
    verified undispatched remainder. reconcile uses the read-only query callback
    and never calls submit. Query recovery uses the same original task/output.
    Native receipt validation must correlate those actual command identities;
    transport acceptance alone never establishes funds or principal effects.
    """
    VERSION = 'bank-execution-submission.v1'
    ACTION_ID = 'BANK-A07'
    METADATA_PREFIX = 'bank_execution_submission:'
    RECEIPT_SCHEMA = 'bank-execution-saved-receipt.v1'
    RECEIPT_LIMITATION = 'Command acceptance does not prove executed principal, cash arrival, cancellation or released funds.'

    def __init__(self, *, worker, binding_id, binding_version, macro_version, supported_choices, callbacks):
        choices = frozenset(supported_choices)
        if 'reconcile' in choices and (not isinstance(callbacks, BankExecutionSubmissionCallbacks) or callbacks.query is None):
            raise ValueError('Payment reconciliation requires an explicitly bound read-only original-command query')
        super().__init__(worker=worker, binding_id=binding_id, binding_version=binding_version,
            macro_version=macro_version, supported_choices=choices, callbacks=callbacks)

    def _original(self, identity):
        request, record, snapshot, row = super()._original(identity)
        action_input = self.worker.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        operation = action_input.operation_context
        payload = record['result']['payload']
        if payload['choice'] == 'execute':
            if operation.kind != 'initiate' or operation.prior_execution_refs or action_input.receipt_refs:
                raise TaskConflict('New payment transport requires its original initiation without prior executions or receipts')
        else:
            if operation.kind != 'existing' or payload['choice'] not in {'reconcile', 'cancel_unexecuted'}:
                raise TaskConflict('Existing payment processing must retain its original execution context')
            refs = [ref.model_dump(mode='json') for ref in operation.execution_refs]
            if not refs or payload['execution_refs'] != refs:
                raise TaskConflict('Existing payment transport changes its original execution identities')
        return request, record, snapshot, row

    def _revalidate(self, request):
        if request.output['payload']['choice'] == 'reconcile':
            self._check_request(request)
            if self.callbacks.validate_query(deepcopy(request)) is not True:
                raise TaskConflict('Existing payment reconciliation requires current original-command read authority')
            return
        return super()._revalidate(request)

    def _submit(self, request):
        self._check_request(request)
        if request.output['payload']['choice'] == 'reconcile':
            # Original TaskSubmission records uncertainty around the read,
            # while the application queries the existing native command only.
            return self._query(request)
        return self.callbacks.submit(deepcopy(request))

    def capabilities(self):
        evidence = super().capabilities()
        evidence['branch_transport'] = {choice: 'read_only_query' if choice == 'reconcile' else 'submit_original_command'
            for choice in sorted(self.supported_choices)}
        return evidence
