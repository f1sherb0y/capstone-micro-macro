"""Relate original GOV-A06 questions to an actually received Owner A08 notice."""
from copy import deepcopy
from dataclasses import dataclass

from integration.government_supplement_results import SavedGovernmentSupplement
from integration.government_submission_host import GovernmentSubmissionHost
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.government_supplement_objects import GovSupplementCaseView
from src.actions.contracts.owner_regulatory_objects import (
    OwnerRegulatoryNoticeView, OwnerRegulatoryCaseView, OwnerRegulatoryAuthorityView,
)
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class GovernmentSupplementPublicationSource:
    """Borrow original agency sources; application owns resources and read guard."""
    saved: SavedGovernmentSupplement
    submission_host: GovernmentSubmissionHost


def read_received_supplement_notice(prepared, *, source_task_sha256, notice_ref, native_evidence_ref,
        read_supplement, validate_reception):
    """Caller holds its source guard; make no notice, response, approval or permit.

    Independent reception confirms actual notice delivery, lawful recipient
    disclosure and complete original question/target/response-requirement
    mapping. Owner's existing processor keeps response windows, authorizations,
    complete response items, submitted versions and actual supplement effects.
    """
    if not callable(read_supplement) or not callable(validate_reception):
        raise TaskConflict('Supplement intake requires original agency reader and independent reception validator')
    try:
        context, reading = prepared.context, prepared.reading
        source = read_supplement(context=context.model_copy(deep=True), source_task_sha256=source_task_sha256)
        saved = source.saved if isinstance(source, GovernmentSupplementPublicationSource) else source
        if (not isinstance(saved, SavedGovernmentSupplement) or saved.identity.key != source_task_sha256
                or saved.identity.action_id != 'GOV-A06' or saved.identity.role != 'Government'
                or saved.identity.purpose != 'action' or saved.identity.organization_id == reading.organization_id
                or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
                or saved.context.contract_ref.id != 'GOV-A06' or context.contract_ref.id != 'OWN-A08'
                or saved.context.execution_mode != context.execution_mode
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'request_supplement'
                or not saved.result.payload.questions
                or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
                or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
                or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
            raise TaskConflict('Supplement notice requires original completed agency questions and current independent Owner input')
        reading.check_method_context(context, 'OWN-A08')
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        if any(saved.audit.get(k) != v for k, v in {'run_id': context.run_id, 'action_id': 'GOV-A06',
                'operation_id': saved.context.operation_id, 'input_sha256': saved.identity.input_sha256,
                'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
            raise TaskConflict('Supplement notice lacks original successful agency audit')
        publication = None
        if context.execution_mode != 'offline_fixture':
            if (not isinstance(source, GovernmentSupplementPublicationSource)
                    or not isinstance(source.submission_host, GovernmentSubmissionHost)):
                raise TaskConflict('Formal supplement intake requires original confirmed agency submission')
            publication = source.submission_host.read_receipt(saved.identity)
            receipt = publication.get('receipt', {})
            if (publication.get('schema_version') != 'government-supplement-saved-receipt.v1'
                    or publication.get('identity') != saved.identity.as_dict()
                    or publication.get('record_sha256') != saved.record_sha256
                    or publication.get('receipt_sha256') != task_digest(receipt) or receipt.get('disposition') != 'accepted'
                    or any(receipt.get(k) != v for k, v in {'run_id': context.run_id,
                        'organization_id': saved.identity.organization_id, 'request_id': saved.identity.request_id,
                        'task_sha256': task_digest(saved.identity.as_dict()), 'output_sha256': result_sha}.items())):
                raise TaskConflict('Supplement intake changes original accepted agency request provenance')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Supplement intake repeats an original agency source')
            originals[key] = row['projection']
        original_case = GovSupplementCaseView.model_validate(originals[saved.action_input.case_ref.key()])
        notice = reading.resolve(Reference.model_validate(notice_ref))
        evidence = reading.resolve(Reference.model_validate(native_evidence_ref))
        if (not isinstance(notice, OwnerRegulatoryNoticeView) or not isinstance(evidence, EvidenceRecord)
                or notice.ref not in prepared.action_input.notice_refs or notice.case_ref not in prepared.action_input.case_refs
                or notice.case_ref != original_case.ref or notice.purpose != 'supplement'
                or notice.applicant_id != prepared.action_input.applicant_id or original_case.applicant_id != notice.applicant_id
                or original_case.organization_id != saved.identity.organization_id
                or not notice.issue_refs or not set(notice.issue_refs) <= set(saved.action_input.issue_refs)
                or notice.issuer_actor_id != saved.context.actor_id or notice.issuer_function_ref != saved.context.function_ref
                or notice.issuer_authority_ref not in saved.context.authorization_refs or notice.issuer_action_id != 'GOV-A06'
                or evidence.ref not in notice.evidence_refs or evidence.basis_kind != 'observed'
                or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')):
            raise TaskConflict('Supplement notice substitutes original case, applicant, questions, issuer or observed delivery evidence')
        case = reading.resolve(notice.case_ref)
        authority = reading.resolve(notice.authority_ref)
        if (not isinstance(case, OwnerRegulatoryCaseView) or not isinstance(authority, OwnerRegulatoryAuthorityView)
                or case.applicant_id != notice.applicant_id or case.authority_ref != authority.ref
                or notice.ref not in case.open_notice_refs
                or authority.organization_id != saved.identity.organization_id or authority.procedure_ref != original_case.procedure_ref):
            raise TaskConflict('Supplement notice changes original case registration or competent agency/procedure')
        now = context.business_time
        if (saved.context.business_time.clock_ref != now.clock_ref or notice.available_at.clock_ref != now.clock_ref
                or not saved.context.business_time.offset <= notice.available_at.offset <= now.offset
                or not notice.effective_window.contains(now)
                or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
            raise TaskConflict('Supplement intake changes original agency decision/notice chronology or current validity')
        relation = {'schema_version': 'government-supplement-owner-notice-reception.v1',
            'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
            'notice_ref': notice.ref.model_dump(mode='json'), 'notice_sha256': task_digest(notice.model_dump(mode='json')),
            'case_sha256': task_digest(case.model_dump(mode='json')), 'authority_sha256': task_digest(authority.model_dump(mode='json'))}
        if publication is not None:
            relation['publication'] = deepcopy(publication)
        if evidence.content_hash != task_digest(relation) or validate_reception(
                deepcopy(saved), notice.model_copy(deep=True), case.model_copy(deep=True), authority.model_copy(deep=True),
                evidence.model_copy(deep=True), context.model_copy(deep=True)) is not True:
            raise TaskConflict('Application did not confirm actual notice delivery and complete lawful question/subject/response mapping')
        return {**relation, 'native_evidence_ref': evidence.ref.model_dump(mode='json'),
            'native_evidence_sha256': task_digest(evidence.model_dump(mode='json')),
            'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Supplement reader changed original Owner regulatory sources or invocation')
