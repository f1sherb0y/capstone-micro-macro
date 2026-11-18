"""Relate original Owner A09 publication/invitation to actual Contractor A02 intake."""
from copy import deepcopy
from dataclasses import dataclass

from integration.owner_tender_results import SavedOwnerTender
from integration.owner_submission_host import OwnerSubmissionHost
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.contractor_bid_objects import ContractorBidPackageView
from src.actions.contracts.owner_tender_objects import OwnerTenderPackageView, OwnerTenderRoundView
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class OwnerTenderPublicationSource:
    """Borrow the original Owner record and its configured submission host.

    Application owns both resources and the source guard. Reading its confirmed
    receipt performs no submit, query transport, task creation or decision.
    """
    saved: SavedOwnerTender
    submission_host: OwnerSubmissionHost


def read_received_owner_tender(prepared, *, source_task_sha256, native_evidence_ref,
        read_owner_tender, validate_reception):
    """Caller holds the source guard; publication and delivery must already exist.

    The independent application validator confirms actual publication/notice,
    current recipient permission, privacy and complete native package mapping.
    No package/round ID, invitation, price, quantity or programme is generated.
    """
    if not callable(read_owner_tender) or not callable(validate_reception):
        raise TaskConflict('Tender reception requires original Owner reader and independent intake validator')
    try:
        context, reading = prepared.context, prepared.reading
        source = read_owner_tender(context=context.model_copy(deep=True), source_task_sha256=source_task_sha256)
        saved = source.saved if isinstance(source, OwnerTenderPublicationSource) else source
        if (not isinstance(saved, SavedOwnerTender) or saved.identity.key != source_task_sha256
                or saved.identity.action_id != 'OWN-A09' or saved.identity.role != 'Owner'
                or saved.identity.purpose != 'action' or saved.identity.organization_id == reading.organization_id
                or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
                or saved.context.contract_ref.id != 'OWN-A09' or context.contract_ref.id != 'CONTRACTOR-A02'
                or saved.context.execution_mode != context.execution_mode
                or saved.result.kind != 'completed' or saved.result.payload.choice not in {'publish_package', 'invite'}
                or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
                or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
                or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
            raise TaskConflict('Tender reception requires original completed publication/invitation and current Contractor A02')
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        reading.check_method_context(context, 'CONTRACTOR-A02')
        if any(saved.audit.get(k) != v for k, v in {'run_id': context.run_id, 'action_id': 'OWN-A09',
                'operation_id': saved.context.operation_id, 'input_sha256': saved.identity.input_sha256,
                'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
            raise TaskConflict('Tender reception lacks original Owner publication/invitation audit')
        publication = None
        if context.execution_mode != 'offline_fixture':
            if (not isinstance(source, OwnerTenderPublicationSource)
                    or not isinstance(source.submission_host, OwnerSubmissionHost)):
                raise TaskConflict('Formal tender intake requires the original configured Owner submission host')
            publication = source.submission_host.read_receipt(saved.identity)
            receipt = publication.get('receipt', {})
            if (publication.get('schema_version') != 'owner-tender-saved-receipt.v1'
                    or publication.get('identity') != saved.identity.as_dict()
                    or publication.get('record_sha256') != saved.record_sha256
                    or publication.get('receipt_sha256') != task_digest(receipt)
                    or receipt.get('disposition') != 'accepted'
                    or any(receipt.get(k) != v for k, v in {'run_id': context.run_id,
                        'organization_id': saved.identity.organization_id, 'request_id': saved.identity.request_id,
                        'task_sha256': task_digest(saved.identity.as_dict()), 'output_sha256': result_sha}.items())):
                raise TaskConflict('Formal tender intake lacks the actual correlated accepted original publication/invitation receipt')
        package = reading.resolve(prepared.action_input.package_ref)
        evidence = reading.resolve(Reference.model_validate(native_evidence_ref))
        if (not isinstance(package, ContractorBidPackageView) or not isinstance(evidence, EvidenceRecord)
                or package.ref != prepared.action_input.package_ref
                or reading.organization_id not in package.recipient_organization_ids
                or evidence.ref not in package.evidence_refs or evidence.basis_kind != 'observed'
                or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')):
            raise TaskConflict('Tender intake lacks actual authorized recipient package and observed publication evidence')
        bidders = saved.result.payload.bidder_ids
        if len(set(bidders)) != len(bidders) or bidders and reading.organization_id not in bidders:
            raise TaskConflict('Tender intake substitutes the original invited legal organization')
        if saved.result.payload.choice == 'invite':
            if not bidders or saved.action_input.package_context.kind != 'published':
                raise TaskConflict('Original invitation requires its published package and selected recipients')
            originals = {}
            for row in saved.source_reading:
                key = Reference.model_validate(row['ref']).key()
                if key in originals:
                    raise TaskConflict('Tender reception repeats an original source')
                originals[key] = row['projection']
            original_package = OwnerTenderPackageView.model_validate(
                originals[saved.action_input.package_context.package_ref.key()])
            original_round = OwnerTenderRoundView.model_validate(originals[package.round_ref.key()])
            if (package.ref != original_package.ref or original_package.owner_organization_id != saved.identity.organization_id
                    or package.round_ref not in saved.action_input.round_refs
                    or package.round_ref not in original_package.round_refs
                    or original_round.package_ref != original_package.ref
                    or original_round.owner_organization_id != saved.identity.organization_id
                    or original_round.status != 'open' or original_round.accepts_new_bids is not True):
                raise TaskConflict('Tender invitation changes original package or open authorized round')
        else:
            draft = saved.result.payload.package
            if (saved.action_input.package_context.kind != 'preparation' or draft is None
                    or package.submission_window_ref != draft.submission_window_ref):
                raise TaskConflict('Tender intake changes original first-publication preparation or submission window')
        now = context.business_time
        if (saved.context.business_time.clock_ref != now.clock_ref or package.available_at.clock_ref != now.clock_ref
                or saved.context.business_time.offset > now.offset or package.available_at.offset > now.offset
                or saved.result.payload.choice == 'publish_package' and package.available_at.offset < saved.context.business_time.offset
                or not package.effective_window.contains(now)
                or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
            raise TaskConflict('Tender intake changes original publication/intake chronology or current validity')
        relation = {'schema_version': 'owner-tender-contractor-reception.v1',
            'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
            'package_ref': package.ref.model_dump(mode='json'), 'round_ref': package.round_ref.model_dump(mode='json'),
            'package_sha256': task_digest(package.model_dump(mode='json')),
            'recipient_organization_id': reading.organization_id}
        if publication is not None:
            relation['publication'] = deepcopy(publication)
        if evidence.content_hash != task_digest(relation) or validate_reception(
                deepcopy(saved), package.model_copy(deep=True), evidence.model_copy(deep=True),
                context.model_copy(deep=True)) is not True:
            raise TaskConflict('Application did not confirm actual tender publication/intake and complete authorized native package mapping')
        return {**relation, 'native_evidence_ref': evidence.ref.model_dump(mode='json'),
            'native_evidence_sha256': task_digest(evidence.model_dump(mode='json')),
            'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Tender reader changed original Contractor sources or invocation')
