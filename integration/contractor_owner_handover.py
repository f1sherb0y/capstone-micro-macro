"""Bind an original Contractor handover decision to independently received Owner sources."""
from copy import deepcopy

from integration.contractor_closeout_results import SavedContractorCloseout
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.contractor_closeout_objects import (
    ContractorAsBuiltView, ContractorCloseoutContractView, ContractorHandoverProfileView, ContractorHandoverRequestView,
)
from src.actions.contracts.owner_closeout_objects import OwnerCloseoutContractView, OwnerHandoverSubmissionView
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


def read_received_owner_handover(prepared, *, source_task_sha256, handover_ref, native_evidence_ref,
        read_contractor_closeout, validate_reception):
    """Relate actual reception without granting acceptance, use rights or debt release.

    Reader holds lawful cross-organization disclosure/current journal authority.
    Receiver independently authenticates native registration and complete mapping
    of configurations, checks, permits, defects and continuing responsibilities.
    Existing Owner A12 processor retains all acceptance and settlement decisions.
    """
    context, reading = prepared.context, prepared.reading
    if (prepared.ACTION_ID != 'OWN-A12' or not callable(read_contractor_closeout)
            or not callable(validate_reception)):
        raise TaskConflict('Handover reception requires Owner closeout and explicit original Contractor reader/validator')
    try:
        reading.check_method_context(context, 'OWN-A12')
        saved = read_contractor_closeout(context=context.model_copy(deep=True), source_task_sha256=source_task_sha256)
        if (not isinstance(saved, SavedContractorCloseout) or saved.identity.key != source_task_sha256
                or saved.identity.action_id != 'CONTRACTOR-A11' or saved.identity.role != 'Contractor'
                or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
                or saved.context.execution_mode != context.execution_mode
                or saved.audit.get('reading', {}).get('source_mode') != (
                    'fixture' if context.execution_mode == 'offline_fixture' else 'formal')
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'submit_handover'
                or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
                or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
                or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
            raise TaskConflict('Handover reception substitutes original Contractor submit decision, sources or model mode')
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        if any(saved.audit.get(key) != value for key, value in {'run_id': context.run_id,
                'action_id': 'CONTRACTOR-A11', 'operation_id': saved.context.operation_id,
                'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
                'result_kind': 'completed'}.items()):
            raise TaskConflict('Received handover lacks its original completed Contractor audit')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Original Contractor handover repeats a source version')
            originals[key] = row['projection']
        original_contract = ContractorCloseoutContractView.model_validate(originals[saved.action_input.contract_ref.key()])
        original_profile = ContractorHandoverProfileView.model_validate(originals[saved.action_input.handover_profile_ref.key()])
        submission = reading.resolve(Reference.model_validate(handover_ref))
        if (not isinstance(submission, OwnerHandoverSubmissionView)
                or submission.ref not in prepared.action_input.handover_refs):
            raise TaskConflict('Received handover is outside explicitly selected Owner input')
        contract = reading.resolve(submission.contract_ref)
        request = reading.resolve(submission.request_ref)
        if (not isinstance(contract, OwnerCloseoutContractView) or not isinstance(request, ContractorHandoverRequestView)
                or contract.ref != original_contract.ref or contract.owner_id != reading.organization_id
                or original_contract.client_id != reading.organization_id
                or contract.contractor_id != saved.identity.organization_id
                or original_contract.contractor_id != saved.identity.organization_id
                or contract.currency != original_contract.currency or submission.ref not in contract.handover_refs
                or request.contract_ref != contract.ref or original_profile.contract_ref != contract.ref
                or request.business_key != original_profile.business_key
                or original_profile.choice != 'submit_handover'
                or submission.status not in {'submitted', 'pending'} or request.status not in {'submitted', 'pending'}
                or submission.scope != saved.result.payload.scope_ref or request.scope != submission.scope
                or not scope_covers(context.scope, submission.scope)
                or set(submission.as_built_refs) != set(saved.action_input.as_built_refs)
                or set(request.as_built_refs) != set(saved.action_input.as_built_refs)
                or len(set(submission.as_built_refs)) != len(submission.as_built_refs)
                or len(set(request.as_built_refs)) != len(request.as_built_refs)
                or set(submission.issue_refs) != set(saved.result.payload.remaining_issue_refs)
                or len(set(submission.issue_refs)) != len(submission.issue_refs)
                or not set(submission.issue_refs) <= set(contract.issue_refs)):
            raise TaskConflict('Actual handover changes original contract, parties, scope, configuration or unresolved issues')
        for row in (submission, request):
            if (row.author_organization_id != saved.identity.organization_id
                    or row.author_actor_id != saved.context.actor_id or row.author_function_ref != saved.context.function_ref
                    or row.author_action_id != 'CONTRACTOR-A11'
                    or row.author_authority_ref not in saved.context.authorization_refs
                    or not row.effective_window.contains(row.authored_at)
                    or row is submission and not row.effective_window.contains(context.business_time)):
                raise TaskConflict('Native handover substitutes original Contractor author/function/authority')
        points = [saved.context.business_time, request.authored_at, request.available_at,
            submission.authored_at, submission.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))):
            raise TaskConflict('Handover changes original decision, registration or reception chronology')
        configurations = []
        for ref in submission.as_built_refs:
            original = ContractorAsBuiltView.model_validate(originals[ref.key()])
            current = reading.resolve(ref)
            if (current != original or original.contract_ref != contract.ref
                    or original.author_organization_id != saved.identity.organization_id):
                raise TaskConflict('Received actual configuration replaces original design/batch/work version or content hash')
            configurations.append(original.model_dump(mode='json'))
        for ref in saved.result.payload.evidence_refs:
            current = reading.resolve(ref)
            if (not isinstance(current, EvidenceRecord) or current.model_dump(mode='json') != originals.get(ref.key())):
                raise TaskConflict('Handover reception replaces original Contractor supporting evidence')
        evidence = reading.resolve(Reference.model_validate(native_evidence_ref))
        native = {'schema_version': 'contractor-owner-handover-reception.v1',
            'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
            'original_result': saved.result.model_dump(mode='json'),
            'original_profile_ref': original_profile.ref.model_dump(mode='json'),
            'handover_request': request.model_dump(mode='json'), 'submission': submission.model_dump(mode='json'),
            'configurations': configurations, 'recipient_organization_id': reading.organization_id}
        if (not isinstance(evidence, EvidenceRecord) or evidence.basis_kind != 'observed'
                or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')
                or evidence.content_hash != task_digest(native)
                or evidence.ref not in submission.evidence_refs or evidence.ref not in request.evidence_refs
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise TaskConflict('Handover reception lacks independent native observation bound to the original submission')
        if validate_reception(saved=deepcopy(saved), request=request.model_copy(deep=True),
                submission=submission.model_copy(deep=True), contract=contract.model_copy(deep=True),
                native_payload=deepcopy(native), context=context.model_copy(deep=True)) is not True:
            raise TaskConflict('Owner did not confirm authentic registration, lawful sharing or complete residual-duty mapping')
        return {'source_task_sha256': saved.identity.key, 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
            'handover_ref': submission.ref.model_dump(mode='json'), 'request_ref': request.ref.model_dump(mode='json'),
            'native_reception_sha256': task_digest(native), 'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        reading.recheck()
        if (task_digest(reading.evidence()) != prepared.reading_sha256
                or task_digest(context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Handover reception changed original Owner input or current authorized source snapshot')


def bind_owner_handover_sources(sources, *, read_contractor_closeout, validate_reception):
    """Add independent handover reception to an existing authorized Owner factory."""
    from dataclasses import replace
    from integration.module_host import module_factory_descriptor
    from integration.owner_role_contract_host import OwnerRoleContractSources

    if (not isinstance(sources, OwnerRoleContractSources) or sources.read_contractor_closeout is not None
            or not callable(read_contractor_closeout) or not callable(validate_reception)):
        raise ValueError('Handover source binding requires original Owner sources and explicit new reader/validator')
    declared = {'schema_version': 'contractor-owner-handover-sources.v1',
        'reader': module_factory_descriptor(read_contractor_closeout, 'read_contractor_closeout'),
        'validator': module_factory_descriptor(validate_reception, 'validate_reception')}

    def evidence():
        if (module_factory_descriptor(read_contractor_closeout, 'read_contractor_closeout') != declared['reader']
                or module_factory_descriptor(validate_reception, 'validate_reception') != declared['validator']):
            raise TaskConflict('Owner handover source code changed')
        return {**deepcopy(sources.evidence()), 'contractor_handover_reception': deepcopy(declared)}

    return replace(sources, version=sources.version + '+contractor-owner-handover-sources.v1', evidence=evidence,
        read_contractor_closeout=read_contractor_closeout, validate_handover_reception=validate_reception)
