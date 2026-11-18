"""Relate an original Owner A10 acceptance to actual Contractor A04 sources."""
from copy import deepcopy
from dataclasses import dataclass

from integration.owner_award_results import SavedOwnerAward
from integration.owner_submission_host import OwnerSubmissionHost
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.contractor_formation_objects import (
    ContractorFormationOfferView, ContractorFormationTermsView,
    ContractorFormationAcceptanceView, contractor_agreement_digest,
)
from src.actions.contracts.owner_award_objects import OwnerAwardOfferView, OwnerAwardTermsView
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class OwnerAwardPublicationSource:
    """Borrow the original award and submission host under the application guard.

    The receiving host reads a confirmed receipt without submitting, querying
    transport, rerunning the decision or closing application-owned resources.
    """
    saved: SavedOwnerAward
    submission_host: OwnerSubmissionHost


def read_received_owner_award(prepared, *, source_task_sha256, acceptance_ref, native_evidence_ref,
        read_owner_award, validate_reception):
    """Caller holds the actual source guard; create no acceptance or contract.

    The independent validator confirms actual publication/intake and the
    original Offer to ContractOffer mapping, including any additional native
    programme, deliverables, payments and bid references. Matching common terms
    alone cannot prove that mapping or replace contract-core formation gates.
    """
    if not callable(read_owner_award) or not callable(validate_reception):
        raise TaskConflict('Award handoff requires original Owner reader and independent reception validator')
    try:
        context, reading = prepared.context, prepared.reading
        source = read_owner_award(context=context.model_copy(deep=True), source_task_sha256=source_task_sha256)
        saved = source.saved if isinstance(source, OwnerAwardPublicationSource) else source
        if (not isinstance(saved, SavedOwnerAward) or saved.identity.key != source_task_sha256
                or saved.identity.action_id != 'OWN-A10' or saved.identity.role != 'Owner'
                or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
                or saved.identity.purpose != 'action' or saved.identity.organization_id == reading.organization_id
                or saved.context.contract_ref.id != 'OWN-A10' or prepared.ACTION_ID != 'CONTRACTOR-A04'
                or context.contract_ref.id != 'CONTRACTOR-A04'
                or saved.context.execution_mode != context.execution_mode
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'accept'
                or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
                or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
                or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
            raise TaskConflict('Award handoff requires the original completed Owner acceptance in the current run')
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        reading.check_method_context(context, 'CONTRACTOR-A04')
        if any(saved.audit.get(k) != v for k, v in {'run_id': context.run_id, 'action_id': 'OWN-A10',
                'operation_id': saved.context.operation_id, 'input_sha256': saved.identity.input_sha256,
                'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
            raise TaskConflict('Award handoff lacks its original successful Owner audit')
        publication = None
        if context.execution_mode != 'offline_fixture':
            if (not isinstance(source, OwnerAwardPublicationSource)
                    or not isinstance(source.submission_host, OwnerSubmissionHost)):
                raise TaskConflict('Formal award intake requires the original configured Owner submission host')
            publication = source.submission_host.read_receipt(saved.identity)
            receipt = publication.get('receipt', {})
            if (publication.get('schema_version') != 'owner-award-saved-receipt.v1'
                    or publication.get('identity') != saved.identity.as_dict()
                    or publication.get('record_sha256') != saved.record_sha256
                    or publication.get('receipt_sha256') != task_digest(receipt)
                    or receipt.get('disposition') != 'accepted'
                    or any(receipt.get(k) != v for k, v in {'run_id': context.run_id,
                        'organization_id': saved.identity.organization_id, 'request_id': saved.identity.request_id,
                        'task_sha256': task_digest(saved.identity.as_dict()), 'output_sha256': result_sha}.items())):
                raise TaskConflict('Formal award intake lacks the actual correlated accepted original Owner award receipt')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Award handoff repeats an original source')
            originals[key] = row['projection']
        original_offer = OwnerAwardOfferView.model_validate(originals[saved.result.payload.offer_ref.key()])
        original_terms = OwnerAwardTermsView.model_validate(originals[saved.result.payload.terms_ref.key()])
        offer = reading.resolve(prepared.action_input.offer_ref)
        terms = reading.resolve(prepared.action_input.terms_ref)
        acceptance = reading.resolve(Reference.model_validate(acceptance_ref))
        evidence = reading.resolve(Reference.model_validate(native_evidence_ref))
        if (not isinstance(offer, ContractorFormationOfferView) or not isinstance(terms, ContractorFormationTermsView)
                or not isinstance(acceptance, ContractorFormationAcceptanceView) or not isinstance(evidence, EvidenceRecord)
                or acceptance.ref not in prepared.action_input.counterpart_acceptance_refs
                or original_offer.ref != saved.action_input.selected_offer_ref
                or original_terms.ref != saved.action_input.final_terms_ref
                or original_offer.final_terms_ref != original_terms.ref or original_terms.offer_ref != original_offer.ref
                or original_offer.round_ref != original_terms.round_ref
                or original_offer.owner_organization_id != saved.identity.organization_id
                or original_terms.owner_organization_id != saved.identity.organization_id
                or original_offer.counterparty_organization_id != reading.organization_id
                or original_terms.counterparty_organization_id != reading.organization_id
                or offer.client_id != saved.identity.organization_id or terms.client_id != saved.identity.organization_id
                or offer.contractor_id != reading.organization_id or terms.contractor_id != reading.organization_id
                or acceptance.run_id != context.run_id or acceptance.party_id != saved.identity.organization_id
                or acceptance.author_actor_id != saved.context.actor_id
                or acceptance.author_function_ref != saved.context.function_ref
                or acceptance.author_authority_ref not in saved.context.authorization_refs
                or acceptance.author_action_id != 'OWN-A10' or acceptance.choice != 'accept' or acceptance.status != 'active'
                or acceptance.explicit_acceptance.state != 'known' or acceptance.explicit_acceptance.value is not True
                or acceptance.offer_ref != offer.ref or acceptance.terms_ref != terms.ref
                or acceptance.scope != terms.scope
                or acceptance.bid_ref != terms.bid_ref or acceptance.agreement_sha256 != contractor_agreement_digest(terms)
                or evidence.ref not in acceptance.evidence_refs or evidence.basis_kind != 'observed'
                or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')):
            raise TaskConflict('Award reception substitutes original party, offer, terms or independently recorded acceptance')
        if (offer.terms_ref != terms.ref or terms.offer_ref != offer.ref or offer.bid_ref != terms.bid_ref
                or original_offer.package_ref != terms.package_ref or original_terms.round_ref != terms.round_ref
                or offer.package_ref != terms.package_ref or offer.round_ref != terms.round_ref
                or original_terms.total_price != terms.price or original_terms.scope != terms.scope
                or any(getattr(original_terms, k) != getattr(terms, k) for k in (
                    'required_party_ids', 'contract_template_ref', 'scope_keys', 'work_window', 'clause_refs'))
                or not set(original_terms.condition_refs) <= set(terms.condition_refs)
                or not set(saved.result.payload.condition_refs) <= set(terms.condition_refs)):
            raise TaskConflict('Award reception changes original price, parties, scope, clauses or retained conditions')
        now = context.business_time
        if (saved.context.business_time.clock_ref != now.clock_ref or acceptance.decided_at.clock_ref != now.clock_ref
                or acceptance.available_at.clock_ref != now.clock_ref
                or not saved.context.business_time.offset <= acceptance.decided_at.offset <= acceptance.available_at.offset <= now.offset
                or not acceptance.effective_window.contains(now)
                or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
            raise TaskConflict('Award reception changes original acceptance chronology or current validity')
        relation = {'schema_version': 'owner-award-contractor-reception.v1',
            'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
            'owner_offer_sha256': task_digest(original_offer.model_dump(mode='json')),
            'owner_terms_sha256': task_digest(original_terms.model_dump(mode='json')),
            'contractor_offer_sha256': task_digest(offer.model_dump(mode='json')),
            'contractor_terms_sha256': task_digest(terms.model_dump(mode='json')),
            'acceptance_ref': acceptance.ref.model_dump(mode='json'),
            'agreement_sha256': acceptance.agreement_sha256}
        if publication is not None:
            relation['publication'] = deepcopy(publication)
        if evidence.content_hash != task_digest(relation) or validate_reception(
                deepcopy(saved), offer.model_copy(deep=True), terms.model_copy(deep=True),
                acceptance.model_copy(deep=True), evidence.model_copy(deep=True), context.model_copy(deep=True)) is not True:
            raise TaskConflict('Application did not confirm actual award publication, reception and complete native agreement mapping')
        return {**relation, 'acceptance_sha256': task_digest(acceptance.model_dump(mode='json')),
            'native_evidence_ref': evidence.ref.model_dump(mode='json'),
            'native_evidence_sha256': task_digest(evidence.model_dump(mode='json')),
            'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Award reader changed original Contractor sources or invocation')
