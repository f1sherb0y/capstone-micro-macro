"""Relate original Owner supplements to actual Government A06 response intake."""
from copy import deepcopy
from dataclasses import dataclass

from integration.owner_regulatory_results import SavedOwnerRegulatory
from integration.owner_submission_host import OwnerSubmissionHost
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.government_supplement_objects import GovSupplementResponseView, GovSupplementSubmissionView
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class OwnerSupplementPublicationSource:
    saved: SavedOwnerRegulatory
    submission_host: OwnerSubmissionHost


def read_received_owner_supplement(prepared, *, source_task_sha256, response_refs, native_evidence_ref,
        read_supplement, validate_reception):
    """Read already received originals under the caller's actual source guard.

    Independent validation binds all response items/evidence and the original
    notice to the received response facts and current submission content. This
    creates no response, verified fact, assessment reuse or issue resolution.
    """
    if not callable(read_supplement) or not callable(validate_reception) or not response_refs:
        raise TaskConflict('Supplement intake requires explicit responses and independent original sources')
    try:
        context, reading = prepared.context, prepared.reading
        source = read_supplement(context=context.model_copy(deep=True), source_task_sha256=source_task_sha256)
        saved = source.saved if isinstance(source, OwnerSupplementPublicationSource) else source
        if (not isinstance(saved, SavedOwnerRegulatory) or saved.identity.key != source_task_sha256
                or saved.identity.action_id != 'OWN-A08' or saved.identity.role != 'Owner' or saved.identity.purpose != 'action'
                or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
                or saved.identity.organization_id == reading.organization_id
                or saved.context.contract_ref.id != 'OWN-A08' or context.contract_ref.id != 'GOV-A06'
                or saved.context.execution_mode != context.execution_mode
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'supplement'
                or saved.result.payload.case_ref != prepared.action_input.case_ref
                or not saved.result.payload.response_items
                or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
                or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
                or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
            raise TaskConflict('Supplement intake requires original completed Owner response for the current agency case')
        reading.check_method_context(context, 'GOV-A06')
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        if any(saved.audit.get(k) != v for k, v in {'run_id': context.run_id, 'action_id': 'OWN-A08',
                'operation_id': saved.context.operation_id, 'input_sha256': saved.identity.input_sha256,
                'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
            raise TaskConflict('Supplement intake lacks original successful Owner audit')
        publication = None
        if context.execution_mode != 'offline_fixture':
            if not isinstance(source, OwnerSupplementPublicationSource) or not isinstance(source.submission_host, OwnerSubmissionHost):
                raise TaskConflict('Formal supplement intake requires original confirmed Owner submission')
            publication = source.submission_host.read_receipt(saved.identity)
            receipt = publication.get('receipt', {})
            if (publication.get('schema_version') != 'owner-regulatory-saved-receipt.v1'
                    or publication.get('identity') != saved.identity.as_dict()
                    or publication.get('record_sha256') != saved.record_sha256
                    or publication.get('receipt_sha256') != task_digest(receipt) or receipt.get('disposition') != 'accepted'
                    or any(receipt.get(k) != v for k, v in {'run_id': context.run_id,
                        'organization_id': saved.identity.organization_id, 'request_id': saved.identity.request_id,
                        'task_sha256': task_digest(saved.identity.as_dict()), 'output_sha256': result_sha}.items())):
                raise TaskConflict('Supplement intake changes original accepted Owner submission provenance')
        selected = [Reference.model_validate(ref) for ref in response_refs]
        if (any(ref.kind != 'Response' for ref in selected) or len(set(selected)) != len(selected)
                or not set(selected) <= set(prepared.action_input.response_refs)):
            raise TaskConflict('Supplement intake repeats or substitutes a selected original response')
        current = reading.resolve(prepared.action_input.current_submission_ref)
        evidence = reading.resolve(Reference.model_validate(native_evidence_ref))
        if (not isinstance(current, GovSupplementSubmissionView) or not isinstance(evidence, EvidenceRecord)
                or evidence.basis_kind != 'observed'
                or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')):
            raise TaskConflict('Supplement intake lacks original current content and observed reception evidence')
        responses = []
        now = context.business_time
        for ref in selected:
            response = reading.resolve(ref)
            if (not isinstance(response, GovSupplementResponseView) or response.status != 'received'
                    or response.case_ref != prepared.action_input.case_ref
                    or response.issue_ref not in prepared.action_input.issue_refs
                    or response.original_submission_ref != prepared.action_input.original_submission_ref
                    or response.current_submission_ref != current.ref or response.current_content_sha256 != current.content_sha256
                    or response.author_organization_id != saved.identity.organization_id
                    or response.author_actor_id != saved.context.actor_id or response.author_function_ref != saved.context.function_ref
                    or response.author_authority_ref not in saved.context.authorization_refs or response.author_action_id != 'OWN-A08'
                    or evidence.ref not in response.evidence_refs
                    or response.authored_at.clock_ref != now.clock_ref or response.received_at.clock_ref != now.clock_ref
                    or response.available_at.clock_ref != now.clock_ref
                    or saved.context.business_time.clock_ref != now.clock_ref
                    or not saved.context.business_time.offset <= response.authored_at.offset <= response.received_at.offset <= response.available_at.offset <= now.offset
                    or not response.effective_window.contains(now)):
                raise TaskConflict('Supplement response changes original author, issue, submission version, content or receipt chronology')
            responses.append(response)
        if evidence.effective_window is not None and not evidence.effective_window.contains(now):
            raise TaskConflict('Supplement reception evidence is no longer current')
        relation = {'schema_version': 'owner-supplement-government-reception.v1',
            'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
            'responses': [{'ref': row.ref.model_dump(mode='json'), 'sha256': task_digest(row.model_dump(mode='json'))} for row in responses],
            'current_submission_sha256': task_digest(current.model_dump(mode='json')),
            'recipient_organization_id': reading.organization_id}
        if publication is not None:
            relation['publication'] = deepcopy(publication)
        if evidence.content_hash != task_digest(relation) or validate_reception(
                deepcopy(saved), [row.model_copy(deep=True) for row in responses], current.model_copy(deep=True),
                evidence.model_copy(deep=True), context.model_copy(deep=True)) is not True:
            raise TaskConflict('Application did not confirm actual supplement receipt and complete response/fact/current-material mapping')
        return {**relation, 'native_evidence_ref': evidence.ref.model_dump(mode='json'),
            'native_evidence_sha256': task_digest(evidence.model_dump(mode='json')),
            'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Supplement reader changed original agency sources or invocation')
