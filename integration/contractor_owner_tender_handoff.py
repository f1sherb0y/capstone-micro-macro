"""Read original Contractor A02 journals for independently received Owner A09 bids."""
from copy import deepcopy
from dataclasses import dataclass

from integration.contractor_bid_results import ContractorBidResultWorker
from integration.contractor_submission_host import ContractorSubmissionHost
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.owner_tender_objects import OwnerEligibleBidderView, OwnerTenderBidView, OwnerTenderRoundView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class ContractorBidJournalSource:
    """Application owns this original persistent worker; the reader grants access.

    Do not construct a replacement worker, rerun a bid or close this source from
    the receiving Owner host. The application source guard protects both sides.
    """
    worker: ContractorBidResultWorker
    identity: TaskIdentity
    submission_host: ContractorSubmissionHost | None = None


def _read_bid(prepared, selected, read_bid, validate_reception):
    context, reading = prepared.context, prepared.reading
    source = read_bid(context=context.model_copy(deep=True), source_task_sha256=selected['source_task_sha256'])
    if (not isinstance(source, ContractorBidJournalSource) or not isinstance(source.worker, ContractorBidResultWorker)
            or not isinstance(source.identity, TaskIdentity) or source.identity.key != selected['source_task_sha256']
            or source.worker.ACTION_ID != 'CONTRACTOR-A02' or source.worker.store.path is None
            or source.identity.action_id != 'CONTRACTOR-A02' or source.identity.role != 'Contractor'
            or source.identity.purpose != 'action' or source.identity.run_id != context.run_id
            or source.identity.organization_id == reading.organization_id):
        raise TaskConflict('Bid reception requires the selected original independent Contractor A02 persistent journal')
    worker, identity = source.worker, source.identity
    with worker.store._lock:
        record = worker.get_record(identity)
        task = worker.store.get(identity)
        snapshot = worker.snapshots.get(identity)
    if (record is None or record['result']['kind'] != 'completed'
            or record['result']['payload']['choice'] != 'submit_bid'
            or task['identity'] != identity.as_dict() or task['output'] != record['result']
            or task['output_sha256'] != record['result_sha256']
            or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}):
        raise TaskConflict('Bid reception lacks an original durable submitted-bid proposal; decline or pending is not a received bid')
    original_context = ActionContext.model_validate(snapshot['context'])
    if original_context.execution_mode != context.execution_mode:
        raise TaskConflict('Bid reception cannot promote an offline proposal into formal evidence')
    publication = None
    if context.execution_mode != 'offline_fixture':
        if (not isinstance(source.submission_host, ContractorSubmissionHost)
                or source.submission_host.store is not worker.store
                or source.submission_host.workers.get(identity.action_id) is not worker):
            raise TaskConflict('Formal bid reception requires the original same-journal Contractor submission host')
        publication = source.submission_host.read_receipt(identity)
        receipt = publication.get('receipt', {})
        if (publication.get('schema_version') != 'contractor-bid-saved-receipt.v1'
                or publication.get('identity') != identity.as_dict()
                or publication.get('record_sha256') != record['record_sha256']
                or publication.get('receipt_sha256') != task_digest(receipt)
                or receipt.get('disposition') != 'accepted'
                or any(receipt.get(k) != v for k, v in {'run_id': context.run_id,
                    'organization_id': identity.organization_id, 'request_id': identity.request_id,
                    'task_sha256': task_digest(identity.as_dict()), 'output_sha256': record['result_sha256']}.items())):
            raise TaskConflict('Formal bid reception lacks the actual correlated accepted original submission receipt')
    bid = reading.resolve(Reference.model_validate(selected['bid_ref']))
    evidence = reading.resolve(Reference.model_validate(selected['native_evidence_ref']))
    if (not isinstance(bid, OwnerTenderBidView) or not isinstance(evidence, EvidenceRecord)
            or bid.ref not in prepared.action_input.bid_refs
            or prepared.action_input.package_context.kind != 'published'
            or bid.package_ref != prepared.action_input.package_context.package_ref
            or bid.round_ref not in prepared.action_input.round_refs
            or bid.bidder_ref not in prepared.action_input.bidder_refs
            or bid.bidder_organization_id != identity.organization_id
            or bid.author_actor_id != original_context.actor_id
            or bid.author_function_ref != original_context.function_ref
            or bid.author_authority_ref not in original_context.authorization_refs
            or bid.author_action_id != 'CONTRACTOR-A02'
            or evidence.ref not in bid.evidence_refs or evidence.basis_kind != 'observed'
            or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')):
        raise TaskConflict('Received bid substitutes original bidder, author, selected package or actual submission evidence')
    bidder = reading.resolve(bid.bidder_ref)
    round_view = reading.resolve(bid.round_ref)
    if (not isinstance(bidder, OwnerEligibleBidderView) or not isinstance(round_view, OwnerTenderRoundView)
            or bidder.organization_id != identity.organization_id or bidder.actor_id != original_context.actor_id
            or bidder.function_ref != original_context.function_ref
            or round_view.package_ref != bid.package_ref or round_view.owner_organization_id != reading.organization_id
            or bid.ref not in round_view.bid_refs):
        raise TaskConflict('Bid reception changes original legal bidder or same-round submission registration')
    draft = record['result']['payload']['bid']
    price = draft['price']
    if (draft['package_ref'] != bid.package_ref.model_dump(mode='json')
            or snapshot['action_input']['package_ref'] != draft['package_ref']
            or bid.total_price.state != 'known' or bid.total_price.value.value != price['value']
            or bid.total_price.value.currency != price['currency']):
        raise TaskConflict('Bid reception changes original package or offered price/currency')
    now = context.business_time
    if (original_context.business_time.clock_ref != now.clock_ref or bid.submitted_at.clock_ref != now.clock_ref
            or not original_context.business_time.offset <= bid.submitted_at.offset <= now.offset
            or bid.available_at.clock_ref != now.clock_ref or bid.available_at.offset > now.offset
            or bid.submitted_at.offset > bid.available_at.offset
            or not bid.effective_window.contains(now)
            or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
        raise TaskConflict('Bid reception changes original proposal/submission chronology or current evidence validity')
    relation = {'schema_version': 'contractor-bid-owner-reception.v1',
        'source_identity': identity.as_dict(), 'source_record_sha256': record['record_sha256'],
        'source_result_sha256': record['result_sha256'], 'source_snapshot_sha256': task_digest(snapshot),
        'source_audit_reading_sha256': task_digest(record['audit']['reading']),
        'bid_ref': bid.ref.model_dump(mode='json'), 'bid_sha256': task_digest(bid.model_dump(mode='json')),
        'recipient_organization_id': reading.organization_id}
    if publication is not None:
        relation['publication'] = deepcopy(publication)
    if evidence.content_hash != task_digest(relation) or validate_reception(
            identity.as_dict(), deepcopy(record), deepcopy(snapshot), bid.model_copy(deep=True),
            evidence.model_copy(deep=True), context.model_copy(deep=True)) is not True:
        raise TaskConflict('Application did not confirm actual bid submission/intake, complete draft mapping and current recipient permission')
    return {**relation, 'native_evidence_ref': evidence.ref.model_dump(mode='json'),
        'native_evidence_sha256': task_digest(evidence.model_dump(mode='json'))}


def read_received_contractor_bids(prepared, *, bids, read_bid, validate_reception):
    """Keep whole selected draft mappings, including terms, exclusions and tasks.

    Original A02 validates its saved contract/input/result/audit through its
    existing worker. Actual dispatch, intake, compliance, native price basis,
    risk and full programme/terms/exclusion mapping need the independent
    validator. No compliance, ranking, award or native bid is manufactured.
    """
    if not callable(read_bid) or not callable(validate_reception) or not bids:
        raise TaskConflict('Bid reception requires explicit bids, original journal reader and independent intake validator')
    try:
        reading = prepared.reading
        reading.check_method_context(prepared.context, 'OWN-A09')
        selected = [Reference.model_validate(row['bid_ref']).key() for row in bids]
        if (len(set(selected)) != len(selected)
                or len({row['source_task_sha256'] for row in bids}) != len(bids)):
            raise TaskConflict('Bid reception repeats a selected native bid or original task')
        originals = [reading.resolve(ref) for ref in prepared.action_input.bid_refs]
        expected = {bid.ref.key() for bid in originals if isinstance(bid, OwnerTenderBidView)
            and bid.author_action_id == 'CONTRACTOR-A02'}
        if set(selected) != expected:
            raise TaskConflict('Configured bid reception must cover every original Contractor A02 bid in the current Owner input')
        provenance = [_read_bid(prepared, row, read_bid, validate_reception) for row in bids]
        return {'bids': provenance, 'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Bid reader changed original Owner sources or invocation')
