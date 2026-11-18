"""Bind original A07 publication and received material to Government A02 input."""
from copy import deepcopy

from integration.architect_deliverable_results import SavedArchitectDeliverable
from src.actions.contracts.architect_submission_objects import ArchitectSubmissionDeliverableView
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.government_objects import GovArchitectDeliverableReceiptView, GovSubmissionView
from src.coordination.tasks import TaskConflict, task_digest


def read_received_architect_deliverable(prepared, *, source_task_sha256,
        publication_receipt_sha256, receipt_ref, read_publication, validate_reception):
    """Read the selected original A07 and confirmed receipt without transport."""
    if not callable(read_publication) or not callable(validate_reception):
        raise TaskConflict('Regulatory reception requires actual original publication reader and validator')
    try:
        selected = read_publication(context=prepared.context.model_copy(deep=True),
            source_task_sha256=source_task_sha256, publication_receipt_sha256=publication_receipt_sha256)
        if (not isinstance(selected, tuple) or len(selected) != 2
                or not isinstance(selected[0], SavedArchitectDeliverable) or not isinstance(selected[1], dict)
                or selected[0].identity.key != source_task_sha256
                or selected[1].get('receipt_sha256') != publication_receipt_sha256):
            raise TaskConflict('Regulatory reader substituted the selected original publication or receipt')
        saved, publication = selected
        validate_received_architect_deliverable(saved, prepared=prepared, publication_receipt=publication,
            receipt_ref=receipt_ref, validate_reception=validate_reception)
        return {'source_task_sha256': saved.identity.key, 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': task_digest(saved.result.model_dump(mode='json')),
            'source_reading_sha256': saved.source_reading_sha256,
            'publication_receipt_sha256': publication_receipt_sha256,
            'publication_envelope_sha256': task_digest(publication),
            'receipt_ref': Reference.model_validate(receipt_ref).model_dump(mode='json'),
            'submission_ref': prepared.action_input.submission_ref.model_dump(mode='json'),
            'intake_source_reading_sha256': prepared.reading_sha256}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256
                or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
            raise TaskConflict('Regulatory publication reader changed original intake input or sources')


def validate_received_architect_deliverable(saved, *, prepared, publication_receipt,
        receipt_ref, validate_reception):
    """Require actual publication and reception; intake retains all original checks.

    The application confirms the original journal, receipt route, authority,
    privacy and exact content. Publication acceptance grants no technical
    approval, use permission, registered regulatory case or construction right.
    """
    context, reading = prepared.context, prepared.reading
    if (not isinstance(saved, SavedArchitectDeliverable) or prepared.ACTION_ID != 'GOV-A02'
            or saved.identity.action_id != 'ARCHITECT-A07' or saved.identity.role != 'Architect'
            or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
            or saved.context.contract_ref.id != 'ARCHITECT-A07'
            or saved.context.execution_mode != context.execution_mode
            or not callable(validate_reception) or not isinstance(publication_receipt, dict)
            or saved.result.kind != 'completed' or saved.result.payload.choice not in {'submit', 'request_review'}
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise TaskConflict('Regulatory reception requires original saved A07 publication and independent actual receipt')
    reading.check_method_context(context, 'GOV-A02')
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if any(saved.audit.get(k) != v for k, v in {'run_id': context.run_id, 'action_id': 'ARCHITECT-A07',
            'operation_id': saved.context.operation_id, 'input_sha256': saved.identity.input_sha256,
            'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
        raise TaskConflict('Regulatory reception substitutes the original successful publication audit')
    original_receipt = deepcopy(publication_receipt)
    before = task_digest(reading.evidence())
    if before != prepared.reading_sha256:
        raise TaskConflict('Regulatory reception changed the original intake source snapshot')
    try:
        native = original_receipt.get('receipt', {})
        if (original_receipt.get('schema_version') != 'architect-deliverable-saved-receipt.v1'
                or original_receipt.get('identity') != saved.identity.as_dict()
                or original_receipt.get('record_sha256') != saved.record_sha256
                or original_receipt.get('receipt_sha256') != task_digest(native)
                or any(native.get(k) != v for k, v in {
                    'run_id': context.run_id, 'organization_id': saved.identity.organization_id,
                    'request_id': saved.identity.request_id, 'task_sha256': task_digest(saved.identity.as_dict()),
                    'output_sha256': result_sha, 'disposition': 'accepted'}.items())
                or not native.get('receipt_id') or 'original_receipt' not in native):
            raise TaskConflict('Regulatory material lacks its original confirmed accepted publication receipt')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Regulatory material repeats an original source identity')
            originals[key] = row['projection']
        deliverable = ArchitectSubmissionDeliverableView.model_validate(originals[saved.action_input.deliverable_ref.key()])
        payload = saved.result.payload
        receipt = reading.resolve(Reference.model_validate(receipt_ref))
        submission = reading.resolve(prepared.action_input.submission_ref)
        if (not isinstance(receipt, GovArchitectDeliverableReceiptView) or not isinstance(submission, GovSubmissionView)
                or receipt.run_id != context.run_id or receipt.scope != prepared.action_input.scope
                or receipt.recipient_organization_id != reading.organization_id
                or receipt.author_organization_id != saved.identity.organization_id
                or receipt.publication_recipient_id not in payload.recipient_ids
                or receipt.source_task_sha256 != saved.identity.key
                or receipt.source_record_sha256 != saved.record_sha256
                or receipt.source_result_sha256 != result_sha
                or receipt.source_reading_sha256 != saved.source_reading_sha256
                or receipt.publication_receipt_sha256 != original_receipt['receipt_sha256']
                or receipt.submission_ref != submission.ref
                or receipt.submission_sha256 != task_digest(submission.model_dump(mode='json'))
                or submission.receipt_status != 'received' or submission.scope != deliverable.scope
                or receipt.deliverable_ref != deliverable.ref or payload.deliverable_ref != deliverable.ref
                or receipt.deliverable_content_sha256 != deliverable.content_sha256
                or receipt.requested_use != payload.requested_use
                or saved.action_input.requested_use != payload.requested_use
                or not any(m.requirement_ref == receipt.requirement_ref
                    and m.evidence_ref == receipt.document_evidence_ref for m in submission.materials)):
            raise TaskConflict('Regulatory reception changes original publication, recipient, content, use or submitted material')
        points = [saved.context.business_time, submission.submitted_at, receipt.received_at,
            receipt.available_at, context.business_time]
        if (any(p.clock_ref != context.business_time.clock_ref for p in points)
                or any(a.offset > b.offset for a, b in zip(points, points[1:]))
                or not receipt.effective_window.contains(context.business_time)):
            raise TaskConflict('Regulatory material reception changes original chronology or availability')
        for ref, digest in ((receipt.document_evidence_ref, deliverable.content_sha256),
                (receipt.native_evidence_ref, task_digest(native['original_receipt']))):
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord) or evidence.basis_kind != 'observed'
                    or evidence.content_hash != digest
                    or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')
                    or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
                raise TaskConflict('Regulatory reception requires original observed document and native receipt evidence')
        if receipt.native_evidence_ref == receipt.document_evidence_ref:
            raise TaskConflict('Publication receipt cannot replace the actual submitted document evidence')
        if validate_reception(saved=deepcopy(saved), publication_receipt=deepcopy(original_receipt),
                receipt=receipt.model_copy(deep=True), submission=submission.model_copy(deep=True),
                deliverable=deliverable.model_copy(deep=True), context=context.model_copy(deep=True)) is not True:
            raise TaskConflict('Actual application did not confirm original journal, native receipt, content and lawful reception')
    finally:
        reading.recheck()
        if (task_digest(reading.evidence()) != before
                or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Regulatory reception validation changed original intake input or sources')
