"""Bind original agency permit-condition verification to Contractor readiness."""
from copy import deepcopy
from dataclasses import dataclass

from integration.government_permit_results import SavedGovernmentPermit
from integration.government_submission_host import GovernmentSubmissionHost
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.contractor_readiness_objects import (
    ContractorReadyTaskView, ContractorReadyRequirementView, ContractorReadyVerificationView,
)
from src.actions.contracts.government_permit_objects import GovPermitView
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class GovernmentPermitPublicationSource:
    saved: SavedGovernmentPermit
    submission_host: GovernmentSubmissionHost


def read_received_permit_verification(prepared, *, source_task_sha256, requirement_ref,
        verification_ref, native_evidence_ref, read_permit, validate_reception):
    """Caller holds the actual cross-source guard; make no release or fulfillment.

    Independent reception validates all original condition findings, any saved
    result references, current action/scope, recipient permission and native
    readiness input digest. A08 acceptance alone grants no construction right.
    """
    if not callable(read_permit) or not callable(validate_reception):
        raise TaskConflict('Permit readiness requires original agency reader and independent reception validator')
    try:
        context, reading = prepared.context, prepared.reading
        source = read_permit(context=context.model_copy(deep=True), source_task_sha256=source_task_sha256)
        saved = source.saved if isinstance(source, GovernmentPermitPublicationSource) else source
        if (not isinstance(saved, SavedGovernmentPermit) or saved.identity.key != source_task_sha256
                or saved.identity.action_id != 'GOV-A08' or saved.identity.role != 'Government' or saved.identity.purpose != 'action'
                or saved.identity.organization_id == reading.organization_id
                or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
                or saved.context.contract_ref.id != 'GOV-A08' or context.contract_ref.id != 'CONTRACTOR-A06'
                or saved.context.execution_mode != context.execution_mode
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'verify' or not saved.result.payload.results
                or saved.action_input.permit_ref not in prepared.action_input.permit_refs
                or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
                or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
                or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
            raise TaskConflict('Readiness requires original agency permit verification and current independent Contractor input')
        reading.check_method_context(context, 'CONTRACTOR-A06')
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        if any(saved.audit.get(k) != v for k, v in {'run_id': context.run_id, 'action_id': 'GOV-A08',
                'operation_id': saved.context.operation_id, 'input_sha256': saved.identity.input_sha256,
                'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
            raise TaskConflict('Permit readiness lacks original successful verification audit')
        publication = None
        if context.execution_mode != 'offline_fixture':
            if not isinstance(source, GovernmentPermitPublicationSource) or not isinstance(source.submission_host, GovernmentSubmissionHost):
                raise TaskConflict('Formal readiness requires original confirmed agency verification submission')
            publication = source.submission_host.read_receipt(saved.identity)
            receipt = publication.get('receipt', {})
            if (publication.get('schema_version') != 'government-permit-saved-receipt.v1'
                    or publication.get('identity') != saved.identity.as_dict()
                    or publication.get('record_sha256') != saved.record_sha256
                    or publication.get('receipt_sha256') != task_digest(receipt) or receipt.get('disposition') != 'accepted'
                    or any(receipt.get(k) != v for k, v in {'run_id': context.run_id,
                        'organization_id': saved.identity.organization_id, 'request_id': saved.identity.request_id,
                        'task_sha256': task_digest(saved.identity.as_dict()), 'output_sha256': result_sha}.items())):
                raise TaskConflict('Permit readiness changes original accepted agency verification provenance')
        task = reading.resolve(prepared.action_input.task_ref)
        requirement = reading.resolve(Reference.model_validate(requirement_ref))
        verification = reading.resolve(Reference.model_validate(verification_ref))
        permit = reading.resolve(saved.action_input.permit_ref)
        evidence = reading.resolve(Reference.model_validate(native_evidence_ref))
        if (not isinstance(task, ContractorReadyTaskView) or not isinstance(requirement, ContractorReadyRequirementView)
                or not isinstance(verification, ContractorReadyVerificationView) or not isinstance(permit, GovPermitView)
                or not isinstance(evidence, EvidenceRecord) or task.organization_id != reading.organization_id
                or requirement.ref not in prepared.action_input.readiness_requirement_refs
                or requirement.task_ref != task.ref or requirement.category != 'permit'
                or permit.ref not in requirement.source_refs or permit.organization_id != saved.identity.organization_id
                or requirement.verification_ref != verification.ref or verification.task_ref != task.ref
                or verification.requirement_ref != requirement.ref or permit.ref not in verification.source_refs
                or requirement.verifier_organization_id != saved.identity.organization_id or requirement.verifier_action_id != 'GOV-A08'
                or verification.author_organization_id != saved.identity.organization_id
                or verification.author_actor_id != saved.context.actor_id or verification.author_function_ref != saved.context.function_ref
                or verification.author_authority_ref not in saved.context.authorization_refs or verification.author_action_id != 'GOV-A08'
                or task.action_ref != saved.action_input.intended_action_ref
                or evidence.ref not in verification.evidence_refs or evidence.basis_kind != 'observed'
                or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')):
            raise TaskConflict('Permit readiness mapping substitutes original permit, action, task, requirement or authorized agency verification')
        results = saved.result.payload.results
        if (any(row.action_ref != task.action_ref for row in results)
                or any(row.result in {'not_satisfied', 'undetermined'} for row in results)
                    and verification.satisfied.state == 'known' and verification.satisfied.value is True):
            raise TaskConflict('Readiness mapping promotes negative or undetermined permit findings to satisfied')
        now = context.business_time
        if (saved.context.business_time.clock_ref != now.clock_ref or verification.authored_at.clock_ref != now.clock_ref
                or verification.available_at.clock_ref != now.clock_ref
                or not saved.context.business_time.offset <= verification.authored_at.offset <= verification.available_at.offset <= now.offset
                or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
            raise TaskConflict('Permit readiness reception changes original verification chronology')
        relation = {'schema_version': 'government-permit-contractor-readiness-reception.v1',
            'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
            'findings': [row.model_dump(mode='json') for row in results],
            'task_sha256': task_digest(task.model_dump(mode='json')), 'permit_sha256': task_digest(permit.model_dump(mode='json')),
            'requirement_sha256': task_digest(requirement.model_dump(mode='json')),
            'verification_sha256': task_digest(verification.model_dump(mode='json')),
            'recipient_organization_id': reading.organization_id}
        if publication is not None:
            relation['publication'] = deepcopy(publication)
        if evidence.content_hash != task_digest(relation) or validate_reception(
                deepcopy(saved), task.model_copy(deep=True), requirement.model_copy(deep=True), verification.model_copy(deep=True),
                permit.model_copy(deep=True), evidence.model_copy(deep=True), context.model_copy(deep=True)) is not True:
            raise TaskConflict('Application did not confirm actual permit verification reception and complete scope/condition/readiness input mapping')
        return {**relation, 'native_evidence_ref': evidence.ref.model_dump(mode='json'),
            'native_evidence_sha256': task_digest(evidence.model_dump(mode='json')),
            'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Permit reader changed original Contractor readiness sources or invocation')
