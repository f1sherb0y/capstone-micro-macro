"""Prepare original BANK-A06 against supplied facility and draw-batch sources."""
from copy import deepcopy
from dataclasses import dataclass, replace

from integration.bank_arrangement_handoff import bank_arrangement_handoff_schemas, prepare_bank_arrangement_handoff
from integration.bank_intake_actions import BankIntakeActionAssembler, PreparedBankIntake
from src.actions.contracts.bank_draw_objects import (
    BankDrawArrangementView, BankDrawCapacityView, BankDrawDecisionView,
    BankDrawRequestView, BankDrawTermsView,
)
from src.actions.contracts.bank_objects import FundingPurposeView
from src.actions.contracts.common import Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import task_digest


def validate_draw_selection(action_input, *, organization_id, resolve):
    """Check original source identities without approving, releasing or reconciling."""
    selected = (
        (action_input.draw_request_ref, BankDrawRequestView),
        (action_input.arrangement_ref, BankDrawArrangementView),
        (action_input.capacity_snapshot_ref, BankDrawCapacityView),
        (action_input.purpose_ref, FundingPurposeView),
    )
    values = []
    for ref, schema in selected:
        row = resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Draw selection changes an original typed source reference')
        values.append(row)
    request, arrangement, capacity, purpose = values
    if (any(row.lender_id != organization_id for row in (request, arrangement, capacity))
            or request.borrower_id != arrangement.borrower_id
            or request.arrangement_ref.key() != arrangement.ref.key()
            or capacity.arrangement_ref.key() != arrangement.ref.key()):
        raise ValueError('Draw selection changes the original lender, borrower or facility')
    terms = resolve(arrangement.terms_ref)
    profile = resolve(request.decision_profile_ref)
    if (not isinstance(terms, BankDrawTermsView) or terms.ref.key() != arrangement.terms_ref.key()
            or request.terms_ref.key() != terms.ref.key() or terms.arrangement_ref.key() != arrangement.ref.key()
            or terms.borrower_id != arrangement.borrower_id or terms.lender_id != organization_id
            or not isinstance(profile, BankDrawDecisionView) or profile.ref.key() != request.decision_profile_ref.key()
            or profile.organization_id != organization_id or profile.draw_request_ref.key() != request.ref.key()):
        raise ValueError('Draw selection changes original facility terms or supplied lender decision profile')
    # Leave incomplete usage, unknown executions, missing verification and
    # decline/partial-approval branches to the original processor.


@dataclass(frozen=True)
class PreparedBankDraw(PreparedBankIntake):
    """A local batch approval invocation, without transfers or actual principal."""


class BankDrawActionAssembler(BankIntakeActionAssembler):
    ACTION_ID = 'BANK-A06'
    SOURCE_SCHEMAS = staticmethod(bank_arrangement_handoff_schemas)

    def build(self, context, *, draw_request_ref, arrangement_ref, condition_evidence_refs,
            capacity_snapshot_ref, pending_execution_refs, purpose_ref):
        evidence = [Reference.model_validate(ref) for ref in condition_evidence_refs]
        executions = [Reference.model_validate(ref) for ref in pending_execution_refs]
        unique_refs(evidence)
        unique_refs(executions)
        return self._prepare_supplied_snapshot(context, input_values={
            'draw_request_ref': Reference.model_validate(draw_request_ref),
            'arrangement_ref': Reference.model_validate(arrangement_ref),
            'condition_evidence_refs': evidence,
            'capacity_snapshot_ref': Reference.model_validate(capacity_snapshot_ref),
            'pending_execution_refs': executions,
            'purpose_ref': Reference.model_validate(purpose_ref)},
            prepared_type=PreparedBankDraw, validate_sources=validate_draw_selection)

    def build_from_arrangement(self, context, *, arrangement_worker, arrangement_identity,
            arrangement_execution_versions, basis_ref, validate_history, validate_current, **draw_refs):
        """Connect explicitly selected confirmation to actual registered facility."""
        from integration.bank_arrangement_results import BankArrangementResultWorker

        if (not isinstance(arrangement_worker, BankArrangementResultWorker) or arrangement_worker.ACTION_ID != 'BANK-A05'
                or arrangement_worker.registry is not self.registry
                or arrangement_worker.store.run_id != self.organizations.run_id
                or not callable(validate_history) or not callable(validate_current)):
            raise ValueError('Draw handoff requires original A05 worker and explicit current host checks')
        invocation = self.build(context, **draw_refs)
        saved = arrangement_worker.read_completed(arrangement_identity, current_context=invocation.context,
            reading=invocation.reading, execution_versions=arrangement_execution_versions, validate_current=validate_history)
        handoff = prepare_bank_arrangement_handoff(saved, context=invocation.context, reading=invocation.reading,
            basis_ref=basis_ref, arrangement_ref=invocation.action_input.arrangement_ref, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        invocation.reading.recheck()
        return {**handoff, 'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}

    def build_from_owner_draw_request(self, context, *, owner_decision, receipt_ref,
            validate_reception, **draw_refs):
        """Bind an actual received draw request to the original Owner instruction."""
        from integration.owner_payment_bank_draw_handoff import validate_received_owner_draw_request

        prepared = self.build(context, **draw_refs)
        validate_received_owner_draw_request(owner_decision, prepared=prepared,
            receipt_ref=receipt_ref, validate_reception=validate_reception)
        return prepared

    def build_from_submitted_arrangement(self, context, *, arrangement_submission, arrangement_identity,
            arrangement_execution_versions, basis_ref, validate_history, validate_current,
            validate_receipt_relation, **draw_refs):
        """Link a confirmed original registration receipt to actual facility sources.

        The existing handoff still checks actual signed offer, independent
        acceptance, complete terms and condition-stage relations. The host
        additionally proves the raw receipt's actual native record/event.
        Registration does not verify later conditions or approve this draw.
        """
        from integration.bank_arrangement_submission import BankArrangementSubmission

        if (not isinstance(arrangement_submission, BankArrangementSubmission)
                or arrangement_submission.worker.registry is not self.registry
                or arrangement_submission.worker.store.run_id != self.organizations.run_id
                or not all(callable(callback) for callback in
                    (validate_history, validate_current, validate_receipt_relation))):
            raise ValueError('Submitted arrangement handoff requires original A05 binding and explicit relation validators')
        receipt = arrangement_submission.read_receipt(arrangement_identity)
        if receipt['receipt']['disposition'] != 'accepted':
            raise ValueError('Rejected native arrangement registration cannot prove a received facility')

        def validate_link(**sources):
            if (sources['reading']._resolver.source_mode != 'formal'
                    or sources['saved'].identity.as_dict() != receipt['identity']
                    or sources['saved'].record_sha256 != receipt['record_sha256']):
                raise ValueError('Arrangement receipt changes original formal decision or current source mode')
            if validate_current(**sources) is not True:
                return False
            return validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True

        handoff = self.build_from_arrangement(context, arrangement_worker=arrangement_submission.worker,
            arrangement_identity=arrangement_identity, arrangement_execution_versions=arrangement_execution_versions,
            basis_ref=basis_ref, validate_history=validate_history, validate_current=validate_link, **draw_refs)
        if handoff['kind'] != 'prepared':
            return handoff
        if arrangement_submission.read_receipt(arrangement_identity) != receipt:
            raise ValueError('Original arrangement registration receipt changed during actual facility linkage')
        invocation = handoff['invocation']
        invocation.reading.recheck()
        return {**handoff, 'provenance': {**handoff['provenance'], 'submission': deepcopy(receipt)},
            'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}
