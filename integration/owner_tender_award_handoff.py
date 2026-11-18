"""Relate original Owner A09 evaluation to an independently selected A10 offer."""
from copy import deepcopy

from integration.owner_tender_results import SavedOwnerTender
from integration.owner_contractor_tender_handoff import OwnerTenderPublicationSource
from integration.owner_submission_host import OwnerSubmissionHost
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_award_objects import OwnerAwardOfferView, OwnerAwardTermsView, OwnerAwardRoundView
from src.actions.contracts.owner_tender_objects import OwnerTenderBidView
from src.coordination.tasks import TaskConflict, task_digest


def read_selected_tender_evaluation(prepared, *, source_task_sha256, selected_bid_ref, native_evidence_ref,
        read_evaluation, validate_selection):
    """Caller holds the source guard; selection must be supplied by the application.

    Evaluation ranks are not an award instruction. Membership in the original
    eligible set, including equal scores, creates no strict preference, consent
    or contract. Actual selection and any negotiated Offer/terms mapping need
    independent confirmation; all original A10 business gates still apply.
    """
    if not callable(read_evaluation) or not callable(validate_selection):
        raise TaskConflict('Evaluation handoff requires original reader and independent native selection validator')
    try:
        context, reading = prepared.context, prepared.reading
        source = read_evaluation(context=context.model_copy(deep=True), source_task_sha256=source_task_sha256)
        saved = source.saved if isinstance(source, OwnerTenderPublicationSource) else source
        if (not isinstance(saved, SavedOwnerTender) or saved.identity.key != source_task_sha256
                or saved.identity.action_id != 'OWN-A09' or saved.identity.role != 'Owner' or saved.identity.purpose != 'action'
                or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
                or saved.identity.organization_id != reading.organization_id
                or saved.context.contract_ref.id != 'OWN-A09' or context.contract_ref.id != 'OWN-A10'
                or saved.context.execution_mode != context.execution_mode
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'evaluate'
                or saved.action_input.package_context.kind != 'published'
                or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
                or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
                or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
            raise TaskConflict('Selection requires original completed same-owner tender evaluation')
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        reading.check_method_context(context, 'OWN-A10')
        if any(saved.audit.get(k) != v for k, v in {'run_id': context.run_id, 'action_id': 'OWN-A09',
                'operation_id': saved.context.operation_id, 'input_sha256': saved.identity.input_sha256,
                'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
            raise TaskConflict('Selection lacks original successful tender evaluation audit')
        publication = None
        if context.execution_mode != 'offline_fixture':
            if not isinstance(source, OwnerTenderPublicationSource) or not isinstance(source.submission_host, OwnerSubmissionHost):
                raise TaskConflict('Formal selection requires original confirmed evaluation submission')
            publication = source.submission_host.read_receipt(saved.identity)
            receipt = publication.get('receipt', {})
            if (publication.get('schema_version') != 'owner-tender-saved-receipt.v1'
                    or publication.get('identity') != saved.identity.as_dict()
                    or publication.get('record_sha256') != saved.record_sha256
                    or publication.get('receipt_sha256') != task_digest(receipt) or receipt.get('disposition') != 'accepted'
                    or any(receipt.get(k) != v for k, v in {'run_id': context.run_id,
                        'organization_id': saved.identity.organization_id, 'request_id': saved.identity.request_id,
                        'task_sha256': task_digest(saved.identity.as_dict()), 'output_sha256': result_sha}.items())):
                raise TaskConflict('Selection changes original accepted evaluation submission provenance')
        selected = Reference.model_validate(selected_bid_ref)
        if (selected.kind != 'Bid' or selected not in saved.action_input.bid_refs
                or selected not in saved.result.payload.ranked_bid_refs or selected in saved.result.payload.rejected_bid_refs):
            raise TaskConflict('Native selection substitutes an unevaluated or rejected bid')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Evaluation repeats an original source')
            originals[key] = row['projection']
        bid = OwnerTenderBidView.model_validate(originals[selected.key()])
        offer = reading.resolve(prepared.action_input.selected_offer_ref)
        terms = reading.resolve(prepared.action_input.final_terms_ref)
        round_view = reading.resolve(prepared.action_input.round_ref)
        evidence = reading.resolve(Reference.model_validate(native_evidence_ref))
        if (not isinstance(offer, OwnerAwardOfferView) or not isinstance(terms, OwnerAwardTermsView)
                or not isinstance(round_view, OwnerAwardRoundView) or not isinstance(evidence, EvidenceRecord)
                or offer.ref not in round_view.offer_refs or offer.round_ref != round_view.ref or terms.round_ref != round_view.ref
                or offer.final_terms_ref != terms.ref or terms.offer_ref != offer.ref
                or round_view.ref not in saved.action_input.round_refs or bid.round_ref != round_view.ref
                or bid.package_ref != saved.action_input.package_context.package_ref
                or offer.package_ref != bid.package_ref or round_view.package_ref != bid.package_ref
                or offer.owner_organization_id != reading.organization_id or terms.owner_organization_id != reading.organization_id
                or round_view.owner_organization_id != reading.organization_id
                or offer.counterparty_organization_id != bid.bidder_organization_id
                or terms.counterparty_organization_id != bid.bidder_organization_id
                or evidence.ref not in offer.evidence_refs or evidence.basis_kind != 'observed'
                or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')):
            raise TaskConflict('Selection changes original owner, bidder, package/round or actual selected offer/terms')
        now = context.business_time
        if (saved.context.business_time.clock_ref != now.clock_ref or saved.context.business_time.offset > now.offset
                or offer.available_at.clock_ref != now.clock_ref or offer.available_at.offset > now.offset
                or terms.available_at.clock_ref != now.clock_ref or terms.available_at.offset > now.offset
                or not offer.effective_window.contains(now) or not terms.effective_window.contains(now)
                or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
            raise TaskConflict('Selected offer or evaluation is not available or current at award time')
        relation = {'schema_version': 'owner-tender-evaluation-award-selection.v1',
            'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
            'selected_bid_ref': selected.model_dump(mode='json'), 'selected_bid_sha256': task_digest(bid.model_dump(mode='json')),
            'offer_sha256': task_digest(offer.model_dump(mode='json')), 'terms_sha256': task_digest(terms.model_dump(mode='json')),
            'round_sha256': task_digest(round_view.model_dump(mode='json'))}
        if publication is not None:
            relation['publication'] = deepcopy(publication)
        if evidence.content_hash != task_digest(relation) or validate_selection(
                deepcopy(saved), bid.model_copy(deep=True), offer.model_copy(deep=True), terms.model_copy(deep=True),
                round_view.model_copy(deep=True), evidence.model_copy(deep=True), context.model_copy(deep=True)) is not True:
            raise TaskConflict('Application did not confirm actual independent selection, equal-score treatment and complete offer/negotiated terms mapping')
        return {**relation, 'native_evidence_ref': evidence.ref.model_dump(mode='json'),
            'native_evidence_sha256': task_digest(evidence.model_dump(mode='json')),
            'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Evaluation reader changed original Owner award sources or invocation')
