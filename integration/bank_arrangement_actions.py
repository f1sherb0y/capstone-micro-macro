"""Prepare BANK-A05 from received offer and independent borrower decision sources."""
from copy import deepcopy
from dataclasses import dataclass, replace

from integration.bank_intake_actions import BankIntakeActionAssembler, PreparedBankIntake
from integration.bank_quote_handoff import bank_quote_handoff_schemas, prepare_bank_quote_handoff
from src.actions.contracts.bank_arrangement_objects import (
    ArrangementAcceptanceView, ArrangementFormationView, ArrangementOfferView,
)
from src.actions.contracts.bank_credit_objects import CreditLendingCapacityView, unique_identities
from src.actions.contracts.bank_objects import FinanceApplicationView
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest
from src.organization.models import Authorization


def validate_arrangement_selection(action_input, *, organization_id, resolve):
    """Check original bank source identities, preserving borrower rejection branches."""
    selected = (
        (action_input.offer_ref, ArrangementOfferView),
        (action_input.borrower_acceptance_ref, ArrangementAcceptanceView),
        (action_input.formation_profile_ref, ArrangementFormationView),
        (action_input.capacity_snapshot_ref, CreditLendingCapacityView),
        (action_input.bank_authority_ref, Authorization),
    )
    values = []
    for ref, schema in selected:
        row = resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Arrangement selection changes its original source schema or version')
        values.append(row)
    offer, acceptance, profile, capacity, authority = values
    application = resolve(offer.application_ref)
    if (not isinstance(application, FinanceApplicationView) or application.ref.key() != offer.application_ref.key()
            or any(row.lender_id != organization_id for row in (offer, application, profile, capacity))
            or authority.organization_id != organization_id
            or offer.terms.borrower_id != application.borrower_id or offer.scope_ref != application.scope_ref
            or profile.offer_ref != offer.ref or profile.borrower_id != offer.terms.borrower_id
            or profile.scope_ref != offer.scope_ref):
        raise ValueError('Arrangement selection changes original bank, offer, application, borrower or scope')
    # A mismatched/rejected/revised borrower decision is an original processor
    # branch. Do not replace it, accept it here, or require it to be affirmative.


@dataclass(frozen=True)
class PreparedBankArrangement(PreparedBankIntake):
    """Local arrangement invocation; confirm does not create a formal commitment."""


class BankArrangementActionAssembler(BankIntakeActionAssembler):
    ACTION_ID = 'BANK-A05'
    SOURCE_SCHEMAS = staticmethod(bank_quote_handoff_schemas)

    def build(self, context, *, offer_ref, borrower_acceptance_ref, bank_authority_ref,
            condition_evidence_refs, capacity_snapshot_ref, formation_profile_ref):
        evidence = [Reference.model_validate(ref) for ref in condition_evidence_refs]
        unique_identities(evidence)
        return self._prepare_supplied_snapshot(context, input_values={
            'offer_ref': Reference.model_validate(offer_ref),
            'borrower_acceptance_ref': Reference.model_validate(borrower_acceptance_ref),
            'bank_authority_ref': Reference.model_validate(bank_authority_ref),
            'condition_evidence_refs': evidence,
            'capacity_snapshot_ref': Reference.model_validate(capacity_snapshot_ref),
            'formation_profile_ref': Reference.model_validate(formation_profile_ref)},
            prepared_type=PreparedBankArrangement, validate_sources=validate_arrangement_selection)

    def build_from_quote(self, context, *, quote_worker, quote_identity, quote_execution_versions,
            basis_ref, validate_history, validate_current, **arrangement_refs):
        """Connect original saved terms to actual registered offer without replay."""
        from integration.bank_quote_results import BankQuoteResultWorker

        if (not isinstance(quote_worker, BankQuoteResultWorker) or quote_worker.ACTION_ID != 'BANK-A04'
                or quote_worker.registry is not self.registry
                or quote_worker.store.run_id != self.organizations.run_id
                or not callable(validate_history) or not callable(validate_current)):
            raise ValueError('Arrangement handoff requires original A04 worker and explicit current host checks')
        invocation = self.build(context, **arrangement_refs)
        saved = quote_worker.read_completed(quote_identity, current_context=invocation.context,
            reading=invocation.reading, execution_versions=quote_execution_versions, validate_current=validate_history)
        handoff = prepare_bank_quote_handoff(saved, context=invocation.context, reading=invocation.reading,
            basis_ref=basis_ref, offer_ref=invocation.action_input.offer_ref, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        invocation.reading.recheck()
        return {**handoff, 'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}

    def build_from_owner_acceptance(self, context, *, owner_decision, receipt_ref,
            validate_reception, **arrangement_refs):
        """Bind actual independent Owner acceptance to its original saved funding choice."""
        from integration.owner_financing_bank_acceptance_handoff import validate_received_owner_financing_acceptance

        prepared = self.build(context, **arrangement_refs)
        validate_received_owner_financing_acceptance(owner_decision, prepared=prepared,
            receipt_ref=receipt_ref, validate_reception=validate_reception)
        return prepared

    def build_from_submitted_quote(self, context, *, quote_submission, quote_identity,
            quote_execution_versions, basis_ref, validate_history, validate_current,
            validate_receipt_relation, **arrangement_refs):
        """Link original confirmed quote registration to an independently supplied offer.

        The original quote handoff still checks terms, reservation and native
        evidence. The host proves which actual offer/event the raw receipt
        identifies. Borrower acceptance and formation stay independent.
        """
        from integration.bank_quote_submission import BankQuoteSubmission

        if (not isinstance(quote_submission, BankQuoteSubmission)
                or quote_submission.worker.registry is not self.registry
                or quote_submission.worker.store.run_id != self.organizations.run_id
                or not all(callable(callback) for callback in
                    (validate_history, validate_current, validate_receipt_relation))):
            raise ValueError('Submitted quote handoff requires original A04 binding and actual host relation validators')
        receipt = quote_submission.read_receipt(quote_identity)
        if receipt['receipt']['disposition'] != 'accepted':
            raise ValueError('Rejected native quote registration cannot prove a received offer')

        def validate_link(**sources):
            if (sources['reading']._resolver.source_mode != 'formal'
                    or sources['saved'].identity.as_dict() != receipt['identity']
                    or sources['saved'].record_sha256 != receipt['record_sha256']):
                raise ValueError('Quote receipt changes original formal decision or current source mode')
            if validate_current(**sources) is not True:
                return False
            return validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True

        handoff = self.build_from_quote(context, quote_worker=quote_submission.worker,
            quote_identity=quote_identity, quote_execution_versions=quote_execution_versions,
            basis_ref=basis_ref, validate_history=validate_history, validate_current=validate_link, **arrangement_refs)
        if handoff['kind'] != 'prepared':
            return handoff
        if quote_submission.read_receipt(quote_identity) != receipt:
            raise ValueError('Original quote registration receipt changed during actual offer linkage')
        invocation = handoff['invocation']
        invocation.reading.recheck()
        return {**handoff, 'provenance': {**handoff['provenance'], 'submission': deepcopy(receipt)},
            'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}
