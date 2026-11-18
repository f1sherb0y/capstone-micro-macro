"""Relate actual borrower acceptance to original OWN-A05 before Bank A05 evaluation."""
from copy import deepcopy

from integration.bank_arrangement_actions import PreparedBankArrangement
from integration.owner_financing_results import SavedOwnerFinancing
from src.actions.contracts.bank_arrangement_objects import (
    ArrangementAcceptanceView, ArrangementBorrowerDecisionView, ArrangementOfferView,
    OwnerFinancingAcceptanceReceiptView, accepted_offer_digest,
)
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_financing_objects import FinancingOfferView
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def _recheck(prepared):
    prepared.reading.recheck()
    if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
            or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Owner acceptance reception changed original Bank arrangement input or sources')


def read_received_owner_financing_acceptance(prepared, *, source_task_sha256, receipt_ref,
        read_owner_financing, validate_reception, receipt_sha256=None):
    """Use the application's authorized original Owner journal, without replay."""
    if not callable(read_owner_financing) or not callable(validate_reception):
        raise TaskConflict('Bank acceptance requires original Owner reader and actual reception validator')
    try:
        saved = read_owner_financing(context=prepared.context.model_copy(deep=True),
            source_task_sha256=source_task_sha256)
        if not isinstance(saved, SavedOwnerFinancing) or saved.identity.key != source_task_sha256:
            raise TaskConflict('Acceptance reader substituted the explicitly selected original Owner task')
        actual_sha256 = validate_received_owner_financing_acceptance(saved, prepared=prepared,
            receipt_ref=receipt_ref, validate_reception=validate_reception)
        if receipt_sha256 is not None and receipt_sha256 != actual_sha256:
            raise TaskConflict('Owner acceptance receipt replaces the explicitly retained original reception')
        provenance = {'source_task_sha256': saved.identity.key, 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': task_digest(saved.result.model_dump(mode='json')),
            'source_reading_sha256': saved.source_reading_sha256,
            'receipt_ref': Reference.model_validate(receipt_ref).model_dump(mode='json'),
            'execution_source_reading_sha256': prepared.reading_sha256}
        if receipt_sha256 is not None:
            provenance['receipt_sha256'] = actual_sha256
        return provenance
    finally:
        _recheck(prepared)


def validate_received_owner_financing_acceptance(saved, *, prepared, receipt_ref, validate_reception):
    """Validate actual PartyAcceptance/RecordedDecision, never derive them from choice.

    The receiving application confirms native acceptance, original Owner journal
    authority and disclosure, exact reservation policy and any later withdrawal.
    Bank confirmation, formation conditions and cash effects remain independent.
    """
    context, reading = prepared.context, prepared.reading
    if (not isinstance(saved, SavedOwnerFinancing) or not isinstance(prepared, PreparedBankArrangement)
            or context.contract_ref.id != 'BANK-A05'
            or saved.identity.action_id != 'OWN-A05' or saved.identity.role != 'Owner'
            or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
            or saved.context.contract_ref.id != 'OWN-A05' or saved.context.execution_mode != context.execution_mode
            or saved.result.kind != 'completed' or saved.result.payload.choice != 'accept_offer'
            or not callable(validate_reception)
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise TaskConflict('Acceptance reception requires original Owner accept_offer and actual Bank source validation')
    reading.check_method_context(context, 'BANK-A05')
    if task_digest(reading.evidence()) != prepared.reading_sha256:
        raise TaskConflict('Acceptance reception changed original Bank source snapshot')
    try:
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        if any(saved.audit.get(key) != value for key, value in {
                'run_id': context.run_id, 'action_id': 'OWN-A05', 'operation_id': saved.context.operation_id,
                'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
                'result_kind': 'completed'}.items()):
            raise TaskConflict('Actual acceptance lacks original successful Owner funding audit')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Acceptance relation repeats an original Owner source')
            originals[key] = row['projection']
        receipt = reading.resolve(Reference.model_validate(receipt_ref))
        if (not isinstance(receipt, OwnerFinancingAcceptanceReceiptView)
                or receipt.run_id != context.run_id or receipt.recipient_organization_id != reading.organization_id
                or receipt.author_organization_id != saved.identity.organization_id
                or receipt.source_task_sha256 != saved.identity.key or receipt.source_record_sha256 != saved.record_sha256
                or receipt.source_result_sha256 != result_sha or receipt.source_reading_sha256 != saved.source_reading_sha256
                or receipt.offer_ref != saved.result.payload.offer_ref
                or receipt.offer_ref != prepared.action_input.offer_ref
                or receipt.acceptance_ref != prepared.action_input.borrower_acceptance_ref
                or not scope_covers(context.scope, receipt.scope) or not receipt.effective_window.contains(context.business_time)):
            raise TaskConflict('Acceptance receipt substitutes original Owner choice, Bank, offer or received decision')
        offer = reading.resolve(receipt.offer_ref)
        original_offer = FinancingOfferView.model_validate(originals[receipt.offer_ref.key()])
        if (not isinstance(offer, ArrangementOfferView) or receipt.scope != offer.scope_ref
                or offer.lender_id != reading.organization_id
                or offer.terms.borrower_id != saved.action_input.borrower_id
                or offer.terms.borrower_id != saved.identity.organization_id
                or not scope_covers(saved.context.scope, offer.scope_ref)
                or original_offer.model_dump(mode='json') != offer.model_dump(mode='json', exclude={'reservation_policy_ref'})):
            raise TaskConflict('Actual acceptance changes the original complete Owner offer projection, terms or borrower')
        acceptance = reading.resolve(receipt.acceptance_ref)
        recorded = reading.resolve(receipt.recorded_decision_ref)
        if (not isinstance(acceptance, ArrangementAcceptanceView) or not isinstance(recorded, ArrangementBorrowerDecisionView)
                or receipt.acceptance_sha256 != task_digest(acceptance.model_dump(mode='json'))
                or receipt.recorded_decision_sha256 != task_digest(recorded.model_dump(mode='json'))
                or acceptance.recorded_decision_ref != recorded.ref or acceptance.offer_ref != offer.ref
                or acceptance.scope_ref != offer.scope_ref or acceptance.organization_id != saved.identity.organization_id
                or acceptance.actor_id != saved.context.actor_id or acceptance.function_ref != saved.context.function_ref
                or acceptance.authority_ref not in saved.context.authorization_refs
                or acceptance.action_id != 'OWN-A05' or acceptance.decision != 'accept'
                or acceptance.accepted_terms != offer.terms or acceptance.agreement_sha256 != accepted_offer_digest(offer)):
            raise TaskConflict('Native independent acceptance changes original Owner author, exact terms or agreement')
        for field in ('offer_ref', 'scope_ref', 'organization_id', 'actor_id', 'function_ref',
                'authority_ref', 'action_id', 'decision', 'accepted_terms', 'agreement_sha256'):
            if getattr(recorded, field) != getattr(acceptance, field):
                raise TaskConflict('Actual acceptance differs from its original independent recorded decision')
        if recorded.decided_at != acceptance.accepted_at:
            raise TaskConflict('Acceptance changes independent recorded decision time')
        original_grant = Authorization.model_validate(originals[acceptance.authority_ref.key()])
        actual_grant = reading.resolve(acceptance.authority_ref)
        assignment = reading.resolve(acceptance.function_ref)
        original_assignment = RoleAssignment.model_validate(originals[acceptance.function_ref.key()])
        if (not isinstance(actual_grant, Authorization) or actual_grant != original_grant
                or not isinstance(assignment, RoleAssignment) or assignment != original_assignment
                or assignment.role != 'Owner' or assignment.function_ref != saved.context.function_ref
                or original_grant.actor_id != saved.context.actor_id
                or original_grant.function_ref != saved.context.function_ref
                or original_grant.organization_id != saved.identity.organization_id
                or 'OWN-A05' not in original_grant.action_ids
                or not original_grant.validity.contains(saved.context.business_time)
                or not original_grant.validity.contains(acceptance.accepted_at)
                or not any(scope_covers(scope, offer.scope_ref) for scope in original_grant.scopes)
                or offer.ref not in original_grant.readable_refs):
            raise TaskConflict('Independent acceptance lacks original and actual borrower authority')
        points = [saved.context.business_time, recorded.decided_at, acceptance.available_at,
            receipt.received_at, receipt.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))):
            raise TaskConflict('Acceptance reception changes original decision, authorship or receipt chronology')
        for ref in [*actual_grant.basis_refs, *assignment.basis_refs]:
            source = reading.resolve(ref)
            if originals.get(ref.key()) != source.model_dump(mode='json'):
                raise TaskConflict('Acceptance author basis changes its original saved source content')
            if ref.kind == 'Evidence':
                if (not isinstance(source, EvidenceRecord) or source.effective_window is not None
                        and any(not source.effective_window.contains(point)
                            for point in (saved.context.business_time, acceptance.accepted_at))):
                    raise TaskConflict('Acceptance author evidence was not valid at original decision and acceptance')
        for ref in receipt.evidence_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(receipt.received_at)):
                raise TaskConflict('Acceptance receipt evidence was not applicable at actual reception')
        native = reading.resolve(receipt.native_evidence_ref)
        if (not isinstance(native, EvidenceRecord) or native.basis_kind != 'observed'
                or native.content_hash != receipt.native_record_sha256
                or (native.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')
                or native.effective_window is not None and not native.effective_window.contains(receipt.received_at)):
            raise TaskConflict('Acceptance reception lacks observed actual native borrower acceptance')
        if validate_reception(saved=deepcopy(saved), receipt=receipt.model_copy(deep=True),
                offer=offer.model_copy(deep=True), acceptance=acceptance.model_copy(deep=True),
                recorded_decision=recorded.model_copy(deep=True), context=context.model_copy(deep=True)) is not True:
            raise TaskConflict('Bank did not confirm actual independent acceptance, exact reservation/history and lawful disclosure')
        return task_digest(receipt.model_dump(mode='json'))
    finally:
        _recheck(prepared)
