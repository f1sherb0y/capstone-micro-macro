"""Bind original supplement resolutions to actual current Government decision inputs."""
from copy import deepcopy

from integration.government_supplement_results import SavedGovernmentSupplement
from integration.government_owner_supplement_handoff import GovernmentSupplementPublicationSource
from integration.government_submission_host import GovernmentSubmissionHost
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.government_decision_objects import GovDecisionCaseView, GovDecisionIssueView
from src.actions.contracts.government_supplement_objects import GovSupplementSubmissionView
from src.coordination.tasks import TaskConflict, task_digest


def read_applied_supplement_resolutions(prepared, *, source_task_sha256, native_evidence_ref,
        read_verification, validate_application):
    """Caller holds the source guard; current issue states must already exist.

    Agency submission acceptance is not native issue resolution. Independent
    application validation binds every original resolution, retained requirement
    and affected/reusable assessment to current decision inputs. It also verifies
    any subsequent reassessment; this helper performs no status update or reuse.
    """
    if not callable(read_verification) or not callable(validate_application):
        raise TaskConflict('Supplement resolutions require original reader and independent current-state application validator')
    try:
        context, reading = prepared.context, prepared.reading
        source = read_verification(context=context.model_copy(deep=True), source_task_sha256=source_task_sha256)
        saved = source.saved if isinstance(source, GovernmentSupplementPublicationSource) else source
        if (not isinstance(saved, SavedGovernmentSupplement) or saved.identity.key != source_task_sha256
                or saved.identity.action_id != 'GOV-A06' or saved.identity.role != 'Government'
                or saved.identity.purpose != 'action' or saved.identity.organization_id != reading.organization_id
                or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
                or saved.context.contract_ref.id != 'GOV-A06' or context.contract_ref.id != 'GOV-A07'
                or saved.context.execution_mode != context.execution_mode
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'verify_response'
                or saved.action_input.case_ref != prepared.action_input.case_ref
                or saved.action_input.current_submission_ref != prepared.action_input.current_submission_ref
                or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
                or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
                or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
            raise TaskConflict('Decision input requires original same-agency supplement verification and exact current material version')
        reading.check_method_context(context, 'GOV-A07')
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        if any(saved.audit.get(k) != v for k, v in {'run_id': context.run_id, 'action_id': 'GOV-A06',
                'operation_id': saved.context.operation_id, 'input_sha256': saved.identity.input_sha256,
                'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
            raise TaskConflict('Supplement resolutions lack original successful verification audit')
        publication = None
        if context.execution_mode != 'offline_fixture':
            if (not isinstance(source, GovernmentSupplementPublicationSource)
                    or not isinstance(source.submission_host, GovernmentSubmissionHost)):
                raise TaskConflict('Formal decision input requires original confirmed verification submission')
            publication = source.submission_host.read_receipt(saved.identity)
            receipt = publication.get('receipt', {})
            if (publication.get('schema_version') != 'government-supplement-saved-receipt.v1'
                    or publication.get('identity') != saved.identity.as_dict()
                    or publication.get('record_sha256') != saved.record_sha256
                    or publication.get('receipt_sha256') != task_digest(receipt) or receipt.get('disposition') != 'accepted'
                    or any(receipt.get(k) != v for k, v in {'run_id': context.run_id,
                        'organization_id': saved.identity.organization_id, 'request_id': saved.identity.request_id,
                        'task_sha256': task_digest(saved.identity.as_dict()), 'output_sha256': result_sha}.items())):
                raise TaskConflict('Supplement verification changes original accepted submission provenance')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Supplement verification repeats an original source')
            originals[key] = row['projection']
        original_submission = GovSupplementSubmissionView.model_validate(originals[saved.action_input.current_submission_ref.key()])
        current = reading.resolve(prepared.action_input.current_submission_ref)
        case = reading.resolve(prepared.action_input.case_ref)
        evidence = reading.resolve(Reference.model_validate(native_evidence_ref))
        if (not isinstance(case, GovDecisionCaseView) or case.organization_id != reading.organization_id
                or case.current_submission_ref != current.ref or current.ref != original_submission.ref
                or current.content_sha256 != original_submission.content_sha256
                or not isinstance(evidence, EvidenceRecord) or evidence.ref not in case.evidence_refs
                or evidence.basis_kind != 'observed'
                or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')):
            raise TaskConflict('Applied supplement resolutions change current case/material content or observed native evidence')
        resolutions = saved.result.payload.resolutions
        keys = [row.issue_ref.key() for row in resolutions]
        if len(set(keys)) != len(keys) or set(keys) != {ref.key() for ref in saved.action_input.issue_refs}:
            raise TaskConflict('Supplement verification omits or repeats original issues')
        issue_states = []
        for resolution in resolutions:
            issue = reading.resolve(resolution.issue_ref)
            if (not isinstance(issue, GovDecisionIssueView) or issue.case_ref != case.ref or issue.submission_ref != current.ref
                    or (issue.status == 'resolved') != (resolution.resolution == 'resolved')
                    or resolution.resolution != 'resolved' and (
                        issue.ref not in case.unresolved_issue_refs or issue.ref not in prepared.action_input.unresolved_issue_refs)
                    or resolution.resolution == 'resolved' and (
                        issue.ref in case.unresolved_issue_refs or issue.ref in prepared.action_input.unresolved_issue_refs)):
                raise TaskConflict('Decision input drops unresolved requirements or invents a resolved supplement issue')
            issue_states.append(issue.model_dump(mode='json'))
        now = context.business_time
        if (saved.context.business_time.clock_ref != now.clock_ref or saved.context.business_time.offset > now.offset
                or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
            raise TaskConflict('Supplement verification is unavailable or its native application evidence expired')
        relation = {'schema_version': 'government-supplement-decision-application.v1',
            'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
            'resolutions': [row.model_dump(mode='json') for row in resolutions],
            'issue_states': issue_states, 'case_sha256': task_digest(case.model_dump(mode='json')),
            'current_submission_sha256': task_digest(current.model_dump(mode='json'))}
        if publication is not None:
            relation['publication'] = deepcopy(publication)
        if evidence.content_hash != task_digest(relation) or validate_application(
                deepcopy(saved), case.model_copy(deep=True), current.model_copy(deep=True),
                prepared.action_input.model_copy(deep=True), evidence.model_copy(deep=True), context.model_copy(deep=True)) is not True:
            raise TaskConflict('Application did not confirm actual issue disposition, retained requirements and affected/reusable assessment mapping')
        return {**relation, 'native_evidence_ref': evidence.ref.model_dump(mode='json'),
            'native_evidence_sha256': task_digest(evidence.model_dump(mode='json')),
            'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Supplement verification reader changed original agency decision sources or invocation')
