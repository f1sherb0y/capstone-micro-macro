"""Corroborate exact saved tender indicators against independent observed input."""
import hashlib
import json
from pathlib import Path
from typing import Literal

from integration.bindings.gba_v1_tender_proposal import GbaTenderProposalMappingView
from integration.contractor_bid_results import ContractorTenderReadSelection
from src.actions.contracts.common import (
    ActionContext, EvidenceRecord, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ref_type,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class TenderExposureObservationSource(StrictRecord):
    evidence_ref: ref_type('Evidence')
    evidence_locator: TextId
    file_path: TextId
    file_sha256: Digest


class TenderExposureValidationSettings(StrictRecord):
    observations: dict[Digest, TenderExposureObservationSource]


class ObservedTenderExposure(StrictRecord):
    """Actual supplied indicator observation; contains no invented transport response."""
    schema_version: Literal['contractor-tender-exposure-observation.v1']
    run_id: TextId
    simulation_id: TextId
    organization_id: TextId
    scope: ScopeRef
    available_at: TimePoint
    effective_window: TimeWindow
    request_sha256: Digest
    original_context_sha256: Digest
    current_context_sha256: Digest
    input_sha256: Digest
    result_sha256: Digest
    audit_sha256: Digest
    mapping: GbaTenderProposalMappingView


def _read_observation(config):
    raw = Path(config.file_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != config.file_sha256:
        raise TaskConflict('Tender observation differs from its explicitly configured original file SHA')

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Tender observation repeats a JSON field')
            value[key] = item
        return value

    def reject_constant(value):
        raise ValueError('Tender observation requires finite JSON values')

    value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object, parse_constant=reject_constant)
    return ObservedTenderExposure.model_validate_json(json.dumps(value, allow_nan=False))


def validate_exposure(*, request, original_context, current_context, action_input, result,
        reading, application, settings):
    """Configured professional.exposure callback for both submit and decline.

    The original adapter retains indicator units, ranges, authorship, audit and
    transport checks. This callback checks a real supplied documentary mapping
    against the exact persisted bid and fresh authorized originals. It does not
    compute probability/profit/risk, rerun A02, emit a proposal, or certify award.
    Native snapshot validation remains the source factory's separate gate.
    """
    application._check()
    if application.selector is None:
        raise TaskConflict('Tender exposure requires the original persistent task selector')
    selection = application.selector.select_current(request)
    _validate_observation(request=request, original_context=original_context,
        current_context=current_context, action_input=action_input, result=result,
        reading=reading, application=application, settings=settings, selection=selection)
    if application.selector.select_current(request) != selection:
        raise TaskConflict('Tender source selection changed during exposure')


def validate_mapping(*, identity, mapping_ref, request, original_context, current_context,
        action_input, result, reading, application, settings):
    """Check the exact saved bid before its mapping/selection is published.

    No selector lookup is valid at this phase. The original host supplies the
    exact identity, and the worker authenticates its completed output and audit.
    This checks documentary indicators; it does not register a selection or
    weaken the later exposure and native-current validation gates.
    """
    selection = ContractorTenderReadSelection(identity=TaskIdentity(**identity.as_dict()),
        current_context=ActionContext.model_validate(current_context).model_copy(deep=True),
        mapping_ref=Reference.model_validate(mapping_ref).model_copy(deep=True))
    _validate_observation(request=request, original_context=original_context,
        current_context=current_context, action_input=action_input, result=result,
        reading=reading, application=application, settings=settings, selection=selection)


def _validate_observation(*, request, original_context, current_context, action_input,
        result, reading, application, settings, selection):
    configuration = TenderExposureValidationSettings.model_validate(settings).model_copy(deep=True)
    original_context = ActionContext.model_validate(original_context).model_copy(deep=True)
    current_context = ActionContext.model_validate(current_context).model_copy(deep=True)
    application._check()
    if application.host is None or application.selector is None or not isinstance(reading, ActionReadView):
        raise TaskConflict('Tender exposure requires the installed original host, selector and reading')
    application.host._check(bound=True)
    request = application.selector._request(request)
    request_sha256 = task_digest(request.model_dump(mode='json'))
    config = configuration.observations.get(request_sha256)
    if (config is None or original_context.execution_mode == 'offline_fixture'
            or current_context.execution_mode == 'offline_fixture'
            or reading._organizations is not application.organizations or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Tender exposure requires an explicitly selected real observation and formal original authority')
    pipeline = application.host.pipeline
    identity = selection.identity
    if (identity.run_id != application.store.run_id or identity.organization_id != request.agent.agent_id
            or identity.role != 'Contractor' or identity.action_id != 'CONTRACTOR-A02'
            or identity.purpose != 'action'
            or identity.versions['client'] != pipeline.worker.client_version
            or identity.versions['model'] != pipeline.worker.model_version
            or selection.current_context != current_context):
        raise TaskConflict('Tender observation changes the exact saved task, recipient, versions or current context')
    current = pipeline.assembler.build_result_reading(selection.current_context)
    saved = pipeline.worker.read_completed(selection.identity, current_context=selection.current_context,
        reading=current, mapping_ref=selection.mapping_ref)
    pipeline.assembler.check_execution_versions(identity, context=saved.context)
    original_record = pipeline.worker.get_record(selection.identity)
    if (original_context != saved.context or current_context != saved.current_context
            or action_input != saved.action_input or result != saved.result
            or reading.organization_id != selection.identity.organization_id
            or result.kind != 'completed' or result.payload.choice not in {'submit_bid', 'decline_bid'}):
        raise TaskConflict('Tender exposure changes its originally selected saved bid, choice or contexts')
    reading.check_method_context(current_context, 'CONTRACTOR-A02')
    for item in reading.evidence():
        ref = item['ref']
        if current.resolve(Reference.model_validate(ref)).model_dump(mode='json') != item['projection']:
            raise TaskConflict('Tender exposure substitutes a current original authorized source projection')
    mapping = current.resolve(selection.mapping_ref)
    if (not isinstance(mapping, GbaTenderProposalMappingView) or config.evidence_ref not in mapping.evidence_refs
            or config.evidence_ref == mapping.result_evidence_ref
            or mapping.run_id != application.store.run_id or mapping.simulation_id != application.assembly.client.simulation_id
            or mapping.organization_id != selection.identity.organization_id or mapping.scope != current_context.scope
            or mapping.request_sha256 != request_sha256 or mapping.context_sha256 != selection.identity.context_sha256
            or mapping.input_sha256 != selection.identity.input_sha256
            or mapping.result_sha256 != task_digest(result.model_dump(mode='json'))
            or mapping.package_ref != action_input.package_ref
            or mapping.project_id != request.inputs['project'].get('project_id')):
        raise TaskConflict('Tender exposure changes independently supplied mapping identity or documentary evidence')
    evidence = current.resolve(config.evidence_ref)
    if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind not in {'real_user', 'real_public'}
            or evidence.basis_kind != 'observed' or evidence.locator != config.evidence_locator
            or evidence.content_hash != config.file_sha256
            or evidence.effective_window is not None and not evidence.effective_window.contains(current_context.business_time)):
        raise TaskConflict('Tender indicators lack their current independently observed documentary input')
    observed = _read_observation(config)
    expected = {'run_id': application.store.run_id, 'simulation_id': application.assembly.client.simulation_id,
        'organization_id': selection.identity.organization_id, 'scope': current_context.scope,
        'request_sha256': request_sha256, 'original_context_sha256': selection.identity.context_sha256,
        'current_context_sha256': task_digest(current_context.model_dump(mode='json')),
        'input_sha256': selection.identity.input_sha256, 'result_sha256': mapping.result_sha256,
        'audit_sha256': task_digest(saved.audit), 'mapping': mapping}
    now = current_context.business_time
    if (any(getattr(observed, name) != value for name, value in expected.items())
            or observed.available_at.clock_ref != now.clock_ref
            or observed.available_at.clock_ref != mapping.authored_at.clock_ref
            or observed.available_at.offset < mapping.authored_at.offset or observed.available_at.offset > now.offset
            or not observed.effective_window.contains(now) or not observed.effective_window.contains(observed.available_at)):
        raise TaskConflict('Tender observation changes original indicators, author, bid provenance or availability')
    reading.recheck()
    current.recheck()
    if (pipeline.worker.get_record(selection.identity) != original_record
            or hashlib.sha256(Path(config.file_path).read_bytes()).hexdigest() != config.file_sha256):
        raise TaskConflict('Tender source selection, original bid record or observation changed during exposure')
    application.host._check(bound=True)
    application._check()
