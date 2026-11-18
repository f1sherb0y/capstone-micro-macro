"""Relate an actually received Owner financing offer to the original Bank A04 record."""
from copy import deepcopy

from integration.bank_quote_results import BankQuoteResultWorker, SavedBankQuote
from src.actions.contracts.bank_objects import FinanceApplicationView
from src.actions.contracts.common import EvidenceRecord, Reference, walk_references
from src.actions.contracts.owner_financing_objects import FinancingOfferView, OwnerFinancingOfferReceiptView
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def _recheck(prepared):
    prepared.reading.recheck()
    if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
            or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Bank quote reception changed original Owner financing input or sources')


def read_received_financing_offer(prepared, *, source_task_sha256, receipt_ref,
        read_bank_quote, validate_reception, receipt_sha256=None):
    """Read the explicitly selected bank record through the authorized application."""
    if not callable(read_bank_quote) or not callable(validate_reception):
        raise TaskConflict('Financing offer requires original Bank journal reader and receiver validator')
    try:
        saved = read_bank_quote(context=prepared.context.model_copy(deep=True),
            source_task_sha256=source_task_sha256)
        if not isinstance(saved, SavedBankQuote) or saved.identity.key != source_task_sha256:
            raise TaskConflict('Offer reader substituted the explicitly selected original Bank task')
        actual_sha256 = validate_received_financing_offer(saved, prepared=prepared, receipt_ref=receipt_ref,
            validate_reception=validate_reception)
        if receipt_sha256 is not None and receipt_sha256 != actual_sha256:
            raise TaskConflict('Financing offer receipt replaces the explicitly retained original reception')
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


def validate_received_financing_offer(saved, *, prepared, receipt_ref, validate_reception):
    """Preserve exact registered terms; reception proves no acceptance or funding.

    The application validates authorized disclosure of the bank record, actual
    registration/receipt, current offer status and native reservation policy.
    The Owner processor still decides all funding choices and conditions.
    """
    context, reading = prepared.context, prepared.reading
    if (not isinstance(saved, SavedBankQuote) or prepared.ACTION_ID != 'OWN-A05'
            or saved.identity.action_id != 'BANK-A04' or saved.identity.role != 'Bank'
            or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
            or saved.context.contract_ref.id != 'BANK-A04' or saved.context.execution_mode != context.execution_mode
            or saved.result.kind != 'completed' or saved.result.payload.choice not in {'offer', 'conditional_offer'}
            or not callable(validate_reception)
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise TaskConflict('Offer reception requires original successful Bank quotation and actual receiver validation')
    reading.check_method_context(context, 'OWN-A05')
    if task_digest(reading.evidence()) != prepared.reading_sha256:
        raise TaskConflict('Offer reception changes original financing source snapshot')
    try:
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        if any(saved.audit.get(key) != value for key, value in {
                'run_id': context.run_id, 'action_id': 'BANK-A04', 'operation_id': saved.context.operation_id,
                'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
                'result_kind': 'completed'}.items()):
            raise TaskConflict('Received offer lacks the original successful Bank quotation audit')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Offer relation repeats an original Bank source')
            originals[key] = row['projection']
        receipt = reading.resolve(Reference.model_validate(receipt_ref))
        if (not isinstance(receipt, OwnerFinancingOfferReceiptView)
                or receipt.run_id != context.run_id or receipt.recipient_organization_id != reading.organization_id
                or receipt.author_organization_id != saved.identity.organization_id
                or receipt.source_task_sha256 != saved.identity.key or receipt.source_record_sha256 != saved.record_sha256
                or receipt.source_result_sha256 != result_sha or receipt.source_reading_sha256 != saved.source_reading_sha256
                or receipt.offer_ref not in prepared.action_input.offers
                or not scope_covers(context.scope, receipt.scope) or not receipt.effective_window.contains(context.business_time)):
            raise TaskConflict('Offer receipt substitutes original Bank, recipient, decision or offer')
        offer = reading.resolve(receipt.offer_ref)
        if (not isinstance(offer, FinancingOfferView) or receipt.offer_sha256 != task_digest(offer.model_dump(mode='json'))
                or offer.status != 'offered' or offer.lender_id != saved.identity.organization_id
                or offer.application_ref != saved.action_input.application_ref
                or offer.terms.borrower_id != prepared.action_input.borrower_id
                or offer.terms.model_dump(mode='json') != saved.result.payload.terms.model_dump(mode='json')
                or receipt.reservation_policy_ref != saved.result.payload.reservation_policy_ref
                or offer.author_actor_id != saved.context.actor_id or offer.author_function_ref != saved.context.function_ref
                or offer.authority_ref != saved.action_input.authority_ref or offer.originating_action_id != 'BANK-A04'
                or offer.scope_ref != receipt.scope or not scope_covers(saved.context.scope, offer.scope_ref)
                or not offer.effective_window.contains(context.business_time)):
            raise TaskConflict('Received offer changes original terms, borrower, author, scope or reservation policy')
        application = reading.resolve(offer.application_ref)
        if (not isinstance(application, FinanceApplicationView)
                or originals.get(application.ref.key()) != application.model_dump(mode='json')
                or application.borrower_id != prepared.action_input.borrower_id
                or application.lender_id != offer.lender_id or application.scope_ref != offer.scope_ref):
            raise TaskConflict('Received offer substitutes the original borrower application or exact version')
        grant = Authorization.model_validate(originals[offer.authority_ref.key()])
        assignment = RoleAssignment.model_validate(originals[offer.author_function_ref.key()])
        required_reads = {ref.key() for value in (saved.action_input, saved.result.payload) for ref in walk_references(value)}
        if (grant.actor_id != offer.author_actor_id or grant.function_ref != offer.author_function_ref
                or grant.ref != offer.authority_ref or offer.authority_ref not in saved.context.authorization_refs
                or assignment.role != 'Bank' or assignment.function_ref != offer.author_function_ref
                or grant.organization_id != offer.lender_id or 'BANK-A04' not in grant.action_ids
                or not grant.validity.contains(saved.context.business_time)
                or not any(scope_covers(scope, offer.scope_ref) for scope in grant.scopes)
                or not required_reads <= {ref.key() for ref in grant.readable_refs}):
            raise TaskConflict('Received offer lacks original independently authorized Bank quotation authorship')
        points = [saved.context.business_time, offer.issued_at, offer.available_at, receipt.received_at,
            receipt.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))):
            raise TaskConflict('Offer reception changes original decision, registration or reception chronology')
        original_schemas = BankQuoteResultWorker.SOURCE_SCHEMAS()
        for ref in [*grant.basis_refs, *assignment.basis_refs]:
            if ref.key() not in originals:
                raise TaskConflict('Received offer omits an original Bank author basis source')
            source = original_schemas.validate_projection(ref, originals[ref.key()])
            if ref.kind == 'Evidence':
                if (not isinstance(source, EvidenceRecord) or source.effective_window is not None
                        and not source.effective_window.contains(saved.context.business_time)):
                    raise TaskConflict('Bank offer author evidence was not valid at the original quotation')
        for ref in receipt.evidence_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(receipt.received_at)):
                raise TaskConflict('Offer receipt evidence was not applicable at actual reception')
        native = reading.resolve(receipt.native_evidence_ref)
        if (not isinstance(native, EvidenceRecord) or native.basis_kind != 'observed'
                or native.content_hash != receipt.native_record_sha256
                or (native.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')
                or native.effective_window is not None and not native.effective_window.contains(receipt.received_at)):
            raise TaskConflict('Received offer lacks observed actual native quotation registration')
        if validate_reception(saved=deepcopy(saved), receipt=receipt.model_copy(deep=True),
                offer=offer.model_copy(deep=True), application=application.model_copy(deep=True),
                context=context.model_copy(deep=True)) is not True:
            raise TaskConflict('Receiver did not confirm actual registration, current offer/reservation history and lawful disclosure')
        return task_digest(receipt.model_dump(mode='json'))
    finally:
        _recheck(prepared)
