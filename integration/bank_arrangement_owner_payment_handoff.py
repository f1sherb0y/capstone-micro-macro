"""Original Bank A05 confirmation to an actual Owner A06 arrangement projection."""
from copy import deepcopy

from integration.bank_arrangement_results import BankArrangementResultWorker, SavedBankArrangement
from src.actions.contracts.bank_arrangement_objects import ArrangementAcceptanceView, ArrangementOfferView
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_financing_objects import FinancingAcceptanceView
from src.actions.contracts.owner_payment_objects import OwnerPaymentArrangementReceiptView, OwnerPaymentArrangementView
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def _recheck(prepared):
    prepared.reading.recheck()
    if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
            or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Bank arrangement reception changed original Owner payment input or sources')


def read_received_payment_arrangement(prepared, *, source_task_sha256, receipt_ref,
        read_bank_arrangement, validate_reception, receipt_sha256=None):
    if not callable(read_bank_arrangement) or not callable(validate_reception):
        raise TaskConflict('Payment arrangement requires original Bank reader and actual reception validator')
    try:
        saved = read_bank_arrangement(context=prepared.context.model_copy(deep=True),
            source_task_sha256=source_task_sha256)
        if not isinstance(saved, SavedBankArrangement) or saved.identity.key != source_task_sha256:
            raise TaskConflict('Arrangement reader substituted the explicitly selected original Bank task')
        actual_sha256 = validate_received_payment_arrangement(saved, prepared=prepared,
            receipt_ref=receipt_ref, validate_reception=validate_reception)
        if receipt_sha256 is not None and receipt_sha256 != actual_sha256:
            raise TaskConflict('Bank arrangement receipt replaces the explicitly retained original reception')
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


def validate_received_payment_arrangement(saved, *, prepared, receipt_ref, validate_reception):
    """Preserve independent parties and terms; no signature or cash is inferred.

    The receiving application verifies actual signature/registration, exact
    projection and native facility terms, every confirmed condition at its
    formation/per-draw stage, current undrawn capacity, unknown executions and
    draw permissions. The original Owner processor still evaluates drawing.
    """
    context, reading = prepared.context, prepared.reading
    if (not isinstance(saved, SavedBankArrangement) or prepared.ACTION_ID != 'OWN-A06'
            or saved.identity.action_id != 'BANK-A05' or saved.identity.role != 'Bank'
            or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
            or saved.context.contract_ref.id != 'BANK-A05' or saved.context.execution_mode != context.execution_mode
            or saved.result.kind != 'completed' or saved.result.payload.choice != 'confirm'
            or not callable(validate_reception)
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise TaskConflict('Arrangement reception requires original Bank confirmation and actual Owner validation')
    reading.check_method_context(context, 'OWN-A06')
    if task_digest(reading.evidence()) != prepared.reading_sha256:
        raise TaskConflict('Arrangement reception changed original Owner payment source snapshot')
    try:
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        if any(saved.audit.get(key) != value for key, value in {
                'run_id': context.run_id, 'action_id': 'BANK-A05', 'operation_id': saved.context.operation_id,
                'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
                'result_kind': 'completed'}.items()):
            raise TaskConflict('Received arrangement lacks original successful Bank confirmation audit')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Arrangement relation repeats an original Bank source')
            originals[key] = row['projection']
        receipt = reading.resolve(Reference.model_validate(receipt_ref))
        if (not isinstance(receipt, OwnerPaymentArrangementReceiptView)
                or receipt.run_id != context.run_id or receipt.recipient_organization_id != reading.organization_id
                or receipt.author_organization_id != saved.identity.organization_id
                or receipt.source_task_sha256 != saved.identity.key or receipt.source_record_sha256 != saved.record_sha256
                or receipt.source_result_sha256 != result_sha or receipt.source_reading_sha256 != saved.source_reading_sha256
                or receipt.arrangement_ref not in prepared.action_input.arrangement_refs
                or not scope_covers(context.scope, receipt.scope) or not receipt.effective_window.contains(context.business_time)):
            raise TaskConflict('Arrangement receipt substitutes original Bank, recipient, confirmation or arrangement')
        offer = ArrangementOfferView.model_validate(originals[saved.action_input.offer_ref.key()])
        original_acceptance = ArrangementAcceptanceView.model_validate(originals[saved.action_input.borrower_acceptance_ref.key()])
        arrangement = reading.resolve(receipt.arrangement_ref)
        if (not isinstance(arrangement, OwnerPaymentArrangementView)
                or receipt.arrangement_sha256 != task_digest(arrangement.model_dump(mode='json'))
                or arrangement.lender_id != saved.identity.organization_id or arrangement.borrower_id != reading.organization_id
                or arrangement.offer_ref != offer.ref or offer.ref != saved.result.payload.offer_ref
                or offer.terms.borrower_id != arrangement.borrower_id or offer.lender_id != arrangement.lender_id
                or arrangement.borrower_acceptance_ref != original_acceptance.ref
                or original_acceptance.ref != saved.result.payload.acceptance_ref
                or original_acceptance.decision != 'accept' or original_acceptance.accepted_terms != offer.terms
                or original_acceptance.offer_ref != offer.ref or original_acceptance.scope_ref != offer.scope_ref
                or original_acceptance.organization_id != arrangement.borrower_id
                or receipt.accepted_terms != offer.terms
                or receipt.confirmed_conditions_sha256 != task_digest([row.model_dump(mode='json') for row in saved.result.payload.conditions])
                or arrangement.scope_ref != receipt.scope or receipt.scope != offer.scope_ref
                or not scope_covers(saved.context.scope, receipt.scope) or arrangement.as_of != context.business_time
                or not arrangement.effective_window.contains(context.business_time)):
            raise TaskConflict('Received arrangement changes original terms, independent borrower, confirmed conditions or exact projection')
        borrower = reading.resolve(arrangement.borrower_acceptance_ref)
        lender = reading.resolve(arrangement.lender_confirmation_ref)
        if not isinstance(borrower, FinancingAcceptanceView) or not isinstance(lender, FinancingAcceptanceView):
            raise TaskConflict('Actual arrangement requires both independently received party acceptances')
        for field in ('ref', 'offer_ref', 'scope_ref', 'organization_id', 'actor_id', 'function_ref',
                'authority_ref', 'action_id', 'decision', 'accepted_at'):
            if getattr(borrower, field) != getattr(original_acceptance, field):
                raise TaskConflict('Owner arrangement changes original independent borrower acceptance')
        if (lender.offer_ref != offer.ref or lender.scope_ref != offer.scope_ref
                or lender.organization_id != arrangement.lender_id or lender.action_id != 'BANK-A05'
                or lender.decision != 'accept' or lender.actor_id != saved.context.actor_id
                or lender.function_ref != saved.context.function_ref
                or lender.authority_ref != saved.action_input.bank_authority_ref):
            raise TaskConflict('Owner arrangement substitutes original independent Bank confirmation author')
        original_schemas = BankArrangementResultWorker.SOURCE_SCHEMAS()
        for acceptance in (borrower, lender):
            grant = reading.resolve(acceptance.authority_ref)
            original_grant = Authorization.model_validate(originals[acceptance.authority_ref.key()])
            assignment = RoleAssignment.model_validate(originals[acceptance.function_ref.key()])
            if (not isinstance(grant, Authorization) or grant != original_grant
                    or assignment.function_ref != acceptance.function_ref
                    or assignment.role != ('Owner' if acceptance is borrower else 'Bank')
                    or grant.actor_id != acceptance.actor_id or grant.organization_id != acceptance.organization_id
                    or grant.function_ref != acceptance.function_ref or acceptance.action_id not in grant.action_ids
                    or not grant.validity.contains(acceptance.accepted_at)
                    or not any(scope_covers(scope, receipt.scope) for scope in grant.scopes)):
                raise TaskConflict('Actual party acceptance changes original independent financing authority')
            if acceptance is lender and (grant.ref not in saved.context.authorization_refs
                    or not grant.validity.contains(saved.context.business_time)):
                raise TaskConflict('Lender confirmation lacks its original Bank decision authority')
            basis_points = (acceptance.accepted_at,) if acceptance is borrower else (
                saved.context.business_time, acceptance.accepted_at)
            for ref in [*grant.basis_refs, *assignment.basis_refs]:
                if ref.key() not in originals:
                    raise TaskConflict('Arrangement reception omits an original party authority basis')
                source = original_schemas.validate_projection(ref, originals[ref.key()])
                if ref.kind == 'Evidence':
                    if (not isinstance(source, EvidenceRecord) or source.effective_window is not None
                            and any(not source.effective_window.contains(point) for point in basis_points)):
                        raise TaskConflict('Arrangement party authority evidence was not valid at original decision/acceptance')
        points = [borrower.accepted_at, saved.context.business_time, lender.accepted_at, receipt.signed_at,
            arrangement.available_at, receipt.received_at, receipt.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))):
            raise TaskConflict('Arrangement reception changes confirmation, independent signing or reception chronology')
        for ref in receipt.evidence_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(receipt.received_at)):
                raise TaskConflict('Arrangement receipt evidence was not applicable at actual reception')
        native = reading.resolve(receipt.native_evidence_ref)
        if (not isinstance(native, EvidenceRecord) or native.basis_kind != 'observed'
                or native.content_hash != receipt.native_record_sha256
                or (native.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')
                or native.effective_window is not None and not native.effective_window.contains(receipt.received_at)):
            raise TaskConflict('Received arrangement lacks observed actual signed native registration')
        if validate_reception(saved=deepcopy(saved), receipt=receipt.model_copy(deep=True),
                arrangement=arrangement.model_copy(deep=True), offer=offer.model_copy(deep=True),
                borrower_acceptance=borrower.model_copy(deep=True), lender_confirmation=lender.model_copy(deep=True),
                context=context.model_copy(deep=True)) is not True:
            raise TaskConflict('Owner did not confirm actual signature, native conditions/terms, current capacity and lawful disclosure')
        return task_digest(receipt.model_dump(mode='json'))
    finally:
        _recheck(prepared)
