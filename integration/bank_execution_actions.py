"""Prepare BANK-A07 with the original initiate or existing-execution context."""
from copy import deepcopy
from dataclasses import dataclass, replace

from integration.bank_draw_handoff import bank_draw_handoff_schemas, prepare_bank_draw_handoff
from integration.bank_intake_actions import BankIntakeActionAssembler, PreparedBankIntake
from src.actions.contracts.bank_execution_objects import (
    BankExecutionAccountView, BankExecutionApprovalView, BankExecutionArrangementView,
    BankExecutionPathView, BankExecutionProfileView, BankExecutionSavedView,
)
from src.actions.contracts.common import Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import task_digest


def validate_execution_selection(action_input, *, organization_id, resolve):
    """Check identities while retaining historical queries and unknown outcomes."""
    def read(ref, schema):
        row = resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Execution selection changes an original typed source reference')
        return row

    arrangement = read(action_input.arrangement_ref, BankExecutionArrangementView)
    profile = read(arrangement.execution_profile_ref, BankExecutionProfileView)
    if (arrangement.lender_id != organization_id or profile.organization_id != organization_id
            or profile.arrangement_ref.key() != arrangement.ref.key()):
        raise ValueError('Execution selection changes the original lender, facility or execution policy')
    operation = action_input.operation_context
    if operation.kind == 'initiate':
        approval = read(operation.draw_approval_ref, BankExecutionApprovalView)
        if (approval.lender_id != organization_id or approval.borrower_id != arrangement.borrower_id
                or approval.arrangement_ref.key() != arrangement.ref.key()
                or approval.terms_ref.key() != arrangement.terms_ref.key()):
            raise ValueError('New execution selection changes the original approval or current facility terms')
        executions = operation.prior_execution_refs
        if not executions:
            path = read(operation.path_ref, BankExecutionPathView)
            account = read(operation.funding_account_ref, BankExecutionAccountView)
            if (path.lender_id != organization_id or path.arrangement_ref.key() != arrangement.ref.key()
                    or path.source_account_ref.key() != account.ref.key() or account.organization_id != organization_id):
                raise ValueError('New execution selection changes original funding path or physical source account')
    else:
        executions = operation.execution_refs
    unique_refs(executions)
    for ref in executions:
        saved = read(ref, BankExecutionSavedView)
        if (saved.lender_id != organization_id or saved.borrower_id != arrangement.borrower_id
                or saved.arrangement_ref.key() != arrangement.ref.key()
                or operation.kind == 'initiate' and saved.approval_ref.key() != approval.ref.key()):
            raise ValueError('Execution selection changes original command owner, borrower, facility or approval')
    # Existing contexts keep their original approval/path versions; current
    # terms, cash availability and expiry never substitute for receipt queries.


@dataclass(frozen=True)
class PreparedBankExecution(PreparedBankIntake):
    """A local execution/query/cancellation proposal, without dispatching payment."""


class BankExecutionActionAssembler(BankIntakeActionAssembler):
    ACTION_ID = 'BANK-A07'
    SOURCE_SCHEMAS = staticmethod(bank_draw_handoff_schemas)

    def build(self, context, *, arrangement_ref, operation_context, receipt_refs):
        receipts = [Reference.model_validate(ref) for ref in receipt_refs]
        unique_refs(receipts)
        operation = (operation_context.model_dump(mode='python') if hasattr(operation_context, 'model_dump')
            else deepcopy(operation_context))
        return self._prepare_supplied_snapshot(context, input_values={
            'arrangement_ref': Reference.model_validate(arrangement_ref),
            'operation_context': operation, 'receipt_refs': receipts},
            prepared_type=PreparedBankExecution, validate_sources=validate_execution_selection)

    def build_from_draw(self, context, *, draw_worker, draw_identity, draw_execution_versions,
            basis_ref, validate_history, validate_current, **execution_refs):
        """Connect explicit original batch approval to actual registered approval."""
        from integration.bank_draw_results import BankDrawResultWorker

        if (not isinstance(draw_worker, BankDrawResultWorker) or draw_worker.ACTION_ID != 'BANK-A06'
                or draw_worker.registry is not self.registry
                or draw_worker.store.run_id != self.organizations.run_id
                or not callable(validate_history) or not callable(validate_current)):
            raise ValueError('Execution handoff requires original A06 worker and explicit current host checks')
        invocation = self.build(context, **execution_refs)
        operation = invocation.action_input.operation_context
        if operation.kind != 'initiate':
            raise ValueError('Approval handoff requires explicit initiation; historical queries use their original existing context')
        saved = draw_worker.read_completed(draw_identity, current_context=invocation.context,
            reading=invocation.reading, execution_versions=draw_execution_versions, validate_current=validate_history)
        handoff = prepare_bank_draw_handoff(saved, context=invocation.context, reading=invocation.reading,
            basis_ref=basis_ref, approval_ref=operation.draw_approval_ref,
            arrangement_ref=invocation.action_input.arrangement_ref, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        invocation.reading.recheck()
        return {**handoff, 'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}

    def build_from_submitted_draw(self, context, *, draw_submission, draw_identity,
            draw_execution_versions, basis_ref, validate_history, validate_current,
            validate_receipt_relation, **execution_refs):
        """Link confirmed draw registration to actual approval for explicit initiation.

        Original approval identity, amount, transfer rows and approver evidence
        remain checked by the existing handoff. The host proves which native
        approval/event the raw receipt identifies. Existing execution queries
        keep their direct build path and never acquire a new initiation identity.
        """
        from integration.bank_draw_submission import BankDrawSubmission

        if (not isinstance(draw_submission, BankDrawSubmission)
                or draw_submission.worker.registry is not self.registry
                or draw_submission.worker.store.run_id != self.organizations.run_id
                or not all(callable(callback) for callback in
                    (validate_history, validate_current, validate_receipt_relation))):
            raise ValueError('Submitted draw handoff requires original A06 binding and explicit native relation validators')
        receipt = draw_submission.read_receipt(draw_identity)
        if receipt['receipt']['disposition'] != 'accepted':
            raise ValueError('Rejected native draw registration cannot prove a payment approval')

        def validate_link(**sources):
            if (sources['reading']._resolver.source_mode != 'formal'
                    or sources['saved'].identity.as_dict() != receipt['identity']
                    or sources['saved'].record_sha256 != receipt['record_sha256']):
                raise ValueError('Draw receipt changes original formal decision or current source mode')
            if validate_current(**sources) is not True:
                return False
            return validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True

        handoff = self.build_from_draw(context, draw_worker=draw_submission.worker,
            draw_identity=draw_identity, draw_execution_versions=draw_execution_versions,
            basis_ref=basis_ref, validate_history=validate_history, validate_current=validate_link, **execution_refs)
        if handoff['kind'] != 'prepared':
            return handoff
        if draw_submission.read_receipt(draw_identity) != receipt:
            raise ValueError('Original draw registration receipt changed during actual approval linkage')
        invocation = handoff['invocation']
        invocation.reading.recheck()
        return {**handoff, 'provenance': {**handoff['provenance'], 'submission': deepcopy(receipt)},
            'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}
