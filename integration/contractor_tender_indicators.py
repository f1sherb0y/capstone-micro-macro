"""Produce request-bound tender mappings from supplied independent indicators.

The input document supplies utility/probability/risk/profit, units and author
authority. Only request/task/result provenance is filled after A02 execution.
No financial or delivery metric is inferred from markup or a native scalar.
"""
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from integration.bindings.gba_v1_tender_proposal import GbaTenderProposalMappingView
from integration.contractor_bid_results import ContractorTenderReadSelection
from integration.contractor_tender_snapshot_sources import ContractorTenderSnapshotReader
from src.actions.contracts.common import (
    ActionContext, EvidenceRecord, Known, Measured, Money, StrictRecord, TextId, Unknown, ref_type,
)
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class TenderIndicatorInput(GovReviewAuthored):
    schema_version: Literal['contractor-tender-indicator-input.v1']
    run_id: TextId
    simulation_id: TextId | None
    organization_id: TextId
    project_id: TextId
    package_ref: ref_type('ProcurementPackage')
    mapping_ref: ref_type('GbaTenderProposalMapping')
    input_evidence_ref: ref_type('Evidence')
    result_evidence_ref: ref_type('Evidence')
    source_kind: Literal['real_user', 'real_public', 'synthetic']
    basis_kind: Literal['observed', 'inferred', 'assumed']
    source_note: TextId
    legacy_currency: TextId
    utility: Measured
    bid_probability: Measured
    risk_level: Measured
    regional_friction: Measured
    expected_profit: Measured
    declined_reference_price: Money | None = None

    @model_validator(mode='after')
    def independent_metric_basis(self):
        if (self.input_evidence_ref == self.result_evidence_ref
                or self.input_evidence_ref not in self.evidence_refs
                or self.result_evidence_ref not in self.evidence_refs):
            raise ValueError('Indicator input must identify distinct input and eventual result evidence')
        metrics = [self.utility, self.bid_probability, self.risk_level, self.regional_friction, self.expected_profit]
        if self.declined_reference_price is not None:
            metrics.append(self.declined_reference_price)
        if any(value.basis_ref != self.input_evidence_ref for value in metrics):
            raise ValueError('Supplied indicators must cite their independent input document')
        if self.source_kind != 'synthetic' and self.basis_kind != 'observed':
            raise ValueError('Documentary tender indicators require explicitly observed input')
        return self


class TenderIndicatorDocumentSettings(StrictRecord):
    file_path: TextId
    file_sha256: Digest
    evidence_locator: TextId
    allow_synthetic: bool = False
    bind_simulation_on_request: bool = False


class TenderIndicatorValidationSettings(StrictRecord):
    documents: dict[Digest, TenderIndicatorDocumentSettings] = Field(default_factory=dict)
    request_documents: dict[TextId, TenderIndicatorDocumentSettings] = Field(default_factory=dict)

    @model_validator(mode='after')
    def explicit_documents(self):
        if not self.documents and not self.request_documents:
            raise ValueError('Tender indicators require explicit digest or original request-id document selections')
        return self

    def for_request(self, request):
        selected = [source for source in (self.documents.get(task_digest(request.model_dump(mode='json'))),
            self.request_documents.get(request.request_id)) if source is not None]
        if len(selected) != 1:
            raise TaskConflict('Tender request needs one unambiguous explicitly selected independent indicator input')
        return selected[0].model_copy(deep=True)


def _load_document(settings):
    settings = TenderIndicatorDocumentSettings.model_validate(settings).model_copy(deep=True)
    raw = Path(settings.file_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != settings.file_sha256:
        raise TaskConflict('Tender indicator input changed its configured file hash')

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Tender indicator input repeats a JSON field')
            value[key] = item
        return value

    def reject(value):
        raise ValueError('Tender indicator input requires finite JSON values')

    document = TenderIndicatorInput.model_validate_json(json.dumps(
        json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique, parse_constant=reject), allow_nan=False))
    if document.source_kind == 'synthetic' and not settings.allow_synthetic:
        raise TaskConflict('Synthetic tender indicators require explicit development configuration')
    if document.simulation_id is None and not settings.bind_simulation_on_request:
        raise TaskConflict('Unbound indicator simulation requires explicit current-request configuration')
    return settings, document


def _produce_objects(*, application, request, identity, settings):
    """Pure derivation from a pinned input document and actual completed bid."""
    settings, source = _load_document(settings)
    simulation_id = (application.assembly.client.simulation_id
        if source.simulation_id is None and settings.bind_simulation_on_request else source.simulation_id)
    worker = application.host.pipeline.worker
    record = worker.get_record(identity)
    if (record is None or record['result']['kind'] != 'completed'
            or record['result']['payload']['choice'] not in {'submit_bid', 'decline_bid'}
            or application.store.get(identity)['state'] != 'output_formed'
            or identity.versions['client'] != worker.client_version or identity.versions['model'] != worker.model_version):
        raise TaskConflict('Indicators require the original finalized same-version A02 output')
    snapshot = worker.snapshots.get(identity)
    context = ActionContext.model_validate(snapshot['context'])
    if context.execution_mode == 'offline_fixture':
        raise TaskConflict('Fixture-only action output cannot be promoted into a native tender mapping')
    application.host.pipeline.assembler.check_execution_versions(identity, context=context)
    action_input = worker.registry.get('CONTRACTOR-A02').contract.validate_input(snapshot['action_input'])
    if (source.run_id != identity.run_id or source.run_id != application.store.run_id
            or simulation_id != application.assembly.client.simulation_id
            or source.organization_id != identity.organization_id or source.organization_id != request.agent.agent_id
            or source.project_id != request.inputs['project']['project_id'] or source.scope != context.scope
            or source.package_ref != action_input.package_ref
            or source.author_organization_id != source.organization_id or source.author_action_id != 'CONTRACTOR-A02'):
        raise TaskConflict('Indicator input changes its actual enterprise, project, package, author or saved bid')
    authored = {name: getattr(source, name) for name in GovReviewAuthored.model_fields}
    mapping = GbaTenderProposalMappingView(**authored, ref=source.mapping_ref,
        run_id=source.run_id, simulation_id=simulation_id, organization_id=source.organization_id,
        project_id=source.project_id, package_ref=source.package_ref,
        request_sha256=task_digest(request.model_dump(mode='json')), context_sha256=identity.context_sha256,
        input_sha256=identity.input_sha256, result_sha256=record['result_sha256'],
        result_evidence_ref=source.result_evidence_ref, legacy_currency=source.legacy_currency,
        **{name: Known[Measured](state='known', value=getattr(source, name)) for name in
            ('utility', 'bid_probability', 'risk_level', 'regional_friction', 'expected_profit')},
        declined_reference_price=(Known[Money](state='known', value=source.declined_reference_price)
            if source.declined_reference_price is not None else Unknown(state='unknown',
                reason_code='no_supplied_decline_reference_price', missing_refs=[source.input_evidence_ref])))
    input_evidence = EvidenceRecord(ref=source.input_evidence_ref, source_kind=source.source_kind,
        basis_kind=source.basis_kind, locator=settings.evidence_locator, content_hash=settings.file_sha256,
        effective_window=source.effective_window)
    result_evidence = EvidenceRecord(ref=source.result_evidence_ref, source_kind='synthetic', basis_kind='observed',
        locator='micro-result:' + identity.key, content_hash=record['result_sha256'],
        effective_window=source.effective_window)
    return settings, mapping, result_evidence, input_evidence


def publish_indicators(*, application, request, identity, contexts, mapping_ref, settings):
    """Called by the real request producer after A02, before mapping publication."""
    application._check()
    request = application.selector._request(request)
    configured, mapping, result_evidence, input_evidence = _produce_objects(
        application=application, request=request, identity=identity, settings=settings)
    if mapping.ref != mapping_ref:
        raise TaskConflict('Indicator input changes the explicitly selected original mapping reference')
    reader = application.host.pipeline.assembler.provider.provider
    if (not isinstance(reader, ContractorTenderSnapshotReader) or reader.assembly is not application.assembly
            or reader.organizations is not application.organizations or reader.read_guard is not application.read_guard):
        raise TaskConflict('Runtime indicators require the original configured same-run snapshot reader')
    reader.publish_bid_indicators(contexts=contexts, request=request, identity=identity,
        worker=application.host.pipeline.worker, mapping=mapping, result_evidence=result_evidence,
        input_evidence=input_evidence, input_sha256=configured.file_sha256)


def _validate(*, selection, request, original_context, current_context, action_input,
        result, reading, application, settings):
    application._check()
    application.host._check(bound=True)
    request = application.selector._request(request)
    configuration = TenderIndicatorValidationSettings.model_validate(settings)
    document_settings = configuration.for_request(request)
    reading.check_method_context(current_context, 'CONTRACTOR-A02')
    if (reading._organizations is not application.organizations or reading._resolver.source_mode != 'formal'
            or selection.current_context != current_context or current_context.execution_mode == 'offline_fixture'):
        raise TaskConflict('Indicator validation requires original formal current authority')
    saved = application.host.pipeline.worker.read_completed(selection.identity, current_context=current_context,
        reading=reading, mapping_ref=selection.mapping_ref)
    if (saved.context != original_context or saved.action_input != action_input or saved.result != result
            or reading.organization_id != selection.identity.organization_id):
        raise TaskConflict('Indicator validation changes the exact original saved input or result')
    _, mapping, result_evidence, input_evidence = _produce_objects(
        application=application, request=request, identity=selection.identity, settings=document_settings)
    if mapping.ref != selection.mapping_ref:
        raise TaskConflict('Indicator validation changes original mapping selection')
    for expected in (mapping, result_evidence, input_evidence):
        if reading.resolve(expected.ref) != expected:
            raise TaskConflict('Tender mapping or its evidence differs from the independent input and actual result')
    now = current_context.business_time
    if (mapping.available_at.clock_ref != now.clock_ref or mapping.available_at.offset > now.offset
            or mapping.authored_at.clock_ref != now.clock_ref
            or mapping.authored_at.offset > mapping.available_at.offset
            or not mapping.effective_window.contains(now) or not mapping.effective_window.contains(mapping.authored_at)):
        raise TaskConflict('Tender indicators are not available at the original current business time')
    reading.recheck()
    application._check()


def validate_mapping(*, identity, mapping_ref, request, original_context, current_context,
        action_input, result, reading, application, settings):
    """Pre-selection callback; never depends on a not-yet-registered selector."""
    selection = ContractorTenderReadSelection(identity=TaskIdentity(**identity.as_dict()),
        current_context=ActionContext.model_validate(current_context), mapping_ref=mapping_ref)
    _validate(selection=selection, request=request, original_context=original_context,
        current_context=current_context, action_input=action_input, result=result,
        reading=reading, application=application, settings=settings)


def validate_exposure(*, request, original_context, current_context, action_input,
        result, reading, application, settings):
    """Exposure callback keeps the registered exact original task relation."""
    selection = application.selector.select_current(request)
    _validate(selection=selection, request=request, original_context=original_context,
        current_context=current_context, action_input=action_input, result=result,
        reading=reading, application=application, settings=settings)
    if application.selector.select_current(request) != selection:
        raise TaskConflict('Tender task selection changed during indicator validation')
