"""Validate an exact persisted participation and the current native procurement relation."""
from contextlib import nullcontext
import json

from integration.bindings.gba_v1_contractor_screening import gba_contractor_screening_source_schemas
from integration.contractor_bid_actions import PreparedContractorBid
from integration.contractor_procurement_handoff import ContractorProcurementHandoffBasis
from integration.contractor_screening_actions import PreparedContractorScreening
from integration.contractor_screening_results import SavedContractorScreening
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, StrictRecord, TextId
from src.actions.contracts.contractor_objects import ProcurementPackageView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class TenderHandoffSource(StrictRecord):
    project_id: TextId
    screening_identity: dict
    screening_record_sha256: Digest


class TenderHandoffRequestSource(StrictRecord):
    """Select the A01 actually completed by this current request, not a future SHA."""
    project_id: TextId
    request_id: TextId


class TenderHandoffValidationSettings(StrictRecord):
    handoffs: dict[TextId, TenderHandoffSource | TenderHandoffRequestSource]


def _request_source(application, config, context, basis):
    from integration.contractor_tender_request_trigger import read_request_record
    from integration.contractor_tender_snapshot_sources import ContractorTenderSnapshotReader

    pipeline = application.host.pipeline
    reader = pipeline.assembler.provider.provider
    if (not isinstance(reader, ContractorTenderSnapshotReader) or reader.assembly is not application.assembly
            or reader.organizations is not application.organizations or reader.read_guard is not application.read_guard):
        raise TaskConflict('Request-bound handoff requires its original source reader')
    trigger = read_request_record(application=application, organization_id=basis.organization_id,
        request_id=config.request_id)
    from integration.contractor_tender_clarification_continuation import effective_screening
    screening_identity, screening_result_sha256 = effective_screening(application, trigger)
    source = reader.handoff_source(context)
    if (trigger['state'] not in {'screened', 'bid_formed', 'selected'}
            or context.scope.kind != 'project' or context.scope.ref.id != config.project_id
            or source is None or source['request_id'] != config.request_id
            or source['request_sha256'] != trigger['request_sha256']
            or source['screening_identity'] != screening_identity
            or source['objects'][0]['value'] != basis.model_dump(mode='json')):
        raise TaskConflict('Request-bound handoff substitutes its original request, completed screening or published basis')
    identity = TaskIdentity(**source['screening_identity'])
    row, record = _original_record(application, identity, source['screening_record_sha256'])
    if screening_result_sha256 != record['result_sha256']:
        raise TaskConflict('Request-bound handoff changes its completed screening result')
    return TenderHandoffSource(project_id=config.project_id, screening_identity=identity.as_dict(),
        screening_record_sha256=record['record_sha256']), source


def _original_record(application, identity, expected_sha256):
    """Read existing evidence only; never construct a worker or create a table."""
    with application.store._lock:
        row = application.store.get(identity)
        saved = application.store._db.execute(
            'SELECT record FROM contractor_screening_results WHERE task_key=?', (identity.key,)).fetchone()
        if saved is None:
            raise TaskConflict('Handoff requires its original persistent A01 result')
        record = json.loads(saved[0])
    fields = {'schema_version', 'identity', 'attempt_revision', 'result', 'result_sha256', 'audit',
        'record_sha256', 'source_reading', 'source_reading_sha256'}
    if (set(record) != fields or record['schema_version'] != 'contractor-screening-result.v1'
            or record['identity'] != identity.as_dict() or row['state'] != 'output_formed'
            or row['output'] != record['result'] or record['record_sha256'] != expected_sha256
            or type(record['attempt_revision']) is not int or record['attempt_revision'] < 1
            or row['revision'] <= record['attempt_revision']
            or task_digest(record['result']) != record['result_sha256']
            or task_digest({key: value for key, value in record.items() if key != 'record_sha256'}) != expected_sha256
            or task_digest(record['source_reading']) != record['source_reading_sha256']):
        raise TaskConflict('Handoff changes original finalized screening identity, result or source evidence')
    schemas = gba_contractor_screening_source_schemas()
    seen = set()
    for item in record['source_reading']:
        if not isinstance(item, dict) or set(item) != {'ref', 'projection'}:
            raise TaskConflict('Original screening evidence requires exact ref/projection records')
        ref = Reference.model_validate(item['ref'])
        if ref.key() in seen:
            raise TaskConflict('Original screening evidence repeats a source version')
        seen.add(ref.key())
        schemas.validate_projection(ref, item['projection'])
    return row, record


def validate_handoff(*, screening, screening_result, bid, basis, application, settings):
    """Configured professional.handoff callback; caller holds the shared writer guard.

    Preserves historical A01 permissions and execution versions. Requires an
    explicitly selected original record, or the completed A01 of a configured
    current request with exact published private provenance.
    Current native invitation membership corroborates the common procurement
    source only. Local participation confers no award, bid, booking or receipt.
    """
    configuration = TenderHandoffValidationSettings.model_validate(settings).model_copy(deep=True)
    application._check()
    if (application.host is None or not isinstance(bid, PreparedContractorBid)
            or not isinstance(screening, (PreparedContractorScreening, SavedContractorScreening))
            or not isinstance(basis, ContractorProcurementHandoffBasis)
            or bid.runner.registry is not application.registry
            or bid.reading._organizations is not application.organizations):
        raise TaskConflict('Handoff requires original same-run screening, bid, registry and authority')
    application.host._check(bound=True)
    context = ActionContext.model_validate(bid.context).model_copy(deep=True)
    config = configuration.handoffs.get(context.operation_id)
    if config is None:
        raise TaskConflict('Handoff requires an explicit original screening selection for this operation')
    generated = None
    if isinstance(config, TenderHandoffRequestSource):
        config, generated = _request_source(application, config, context, basis)
    identity = TaskIdentity(**config.screening_identity)
    if (identity.run_id != application.store.run_id or identity.role != 'Contractor'
            or identity.action_id != 'CONTRACTOR-A01' or identity.purpose != 'action'
            or context.run_id != identity.run_id or context.contract_ref.id != 'CONTRACTOR-A02'
            or context.execution_mode == 'offline_fixture' or bid.reading.organization_id != identity.organization_id
            or identity.context_sha256 != screening.context_sha256 or identity.input_sha256 != screening.input_sha256
            or task_digest(bid.action_input.model_dump(mode='json')) != bid.input_sha256
            or task_digest(context.model_dump(mode='json')) != bid.context_sha256):
        raise TaskConflict('Handoff changes its original formal A01/A02 context or input identity')
    if isinstance(screening, SavedContractorScreening):
        if (screening.identity != identity or screening.registry is not application.registry
                or screening.record_sha256 != config.screening_record_sha256):
            raise TaskConflict('Handoff substitutes the explicitly selected historical screening record')
    elif (screening.runner.registry is not application.registry
            or screening.reading._organizations is not application.organizations):
        raise TaskConflict('Prepared screening belongs to a different original application')
    row, record = _original_record(application, identity, config.screening_record_sha256)
    snapshot = application.host.pipeline.worker.snapshots.get(identity)
    if (snapshot['context'] != screening.context.model_dump(mode='json')
            or snapshot['action_input'] != screening.action_input.model_dump(mode='json')
            or record['result'] != screening_result.model_dump(mode='json')
            or screening_result.kind != 'completed' or screening_result.payload.choice != 'participate'
            or record['source_reading_sha256'] != screening.reading_sha256):
        raise TaskConflict('Handoff changes the original participation snapshot, result or reading')
    if isinstance(screening, SavedContractorScreening):
        if record['audit'] != screening.audit or record['source_reading'] != list(screening.source_reading):
            raise TaskConflict('Historical screening audit or retained sources changed')
    else:
        if record['source_reading'] != screening.reading.evidence():
            raise TaskConflict('Prepared screening differs from its original persisted source cache')
    contract = application.registry.get('CONTRACTOR-A01').contract
    contract_sha256 = task_digest({'ref': screening.context.contract_ref.model_dump(mode='json'),
        'source_sha256': contract.source_sha256, 'input_schema': contract.input_model.model_json_schema(),
        'payload_schema': contract.payload_adapter.json_schema()})
    if contract_sha256 != identity.versions['contract']:
        raise TaskConflict('Handoff requires its original screening contract without migration')
    contract.validate_decision(contract.validate_input(snapshot['action_input']), screening_result.payload)
    expected = {'screening_context_sha256': identity.context_sha256, 'screening_input_sha256': identity.input_sha256,
        'screening_result_sha256': record['result_sha256'], 'screening_audit_sha256': task_digest(record['audit'])}
    if any(getattr(basis, key) != value for key, value in expected.items()):
        raise TaskConflict('Handoff basis differs from its exact persisted participation evidence')
    packages = [item['projection'] for item in record['source_reading']
        if Reference.model_validate(item['ref']) == screening.action_input.package_ref]
    if len(packages) != 1:
        raise TaskConflict('Handoff lacks the original screening package projection')
    package = ProcurementPackageView.model_validate(packages[0])
    reading = application.host.pipeline.assembler.build_capacity_reading(context)
    reading.check_method_context(context, 'CONTRACTOR-A02')
    if reading.organization_id != identity.organization_id or reading._resolver.source_mode != 'formal':
        raise TaskConflict('Handoff changes current original Contractor read authority')
    if (reading.resolve(basis.ref) != basis or basis.run_id != context.run_id
            or basis.organization_id != identity.organization_id or basis.scope != context.scope
            or basis.package_ref != bid.action_input.package_ref or package.ref != basis.package_ref
            or basis.screening_projection_sha256 != task_digest(package.model_dump(mode='json'))):
        raise TaskConflict('Handoff substitutes original procurement package, basis or source projection')
    current_package = reading.resolve(basis.package_ref)
    if (current_package != bid.reading.resolve(basis.package_ref)
            or basis.bid_projection_sha256 != task_digest(current_package.model_dump(mode='json'))):
        raise TaskConflict('Handoff substitutes the current original bid procurement representation')
    for ref, digest in ((basis.procurement_source_evidence_ref, basis.procurement_source_sha256),
            (basis.screening_result_evidence_ref, record['result_sha256'])):
        evidence = reading.resolve(ref)
        generated_evidence = next((item['value'] for item in generated['objects'][1:]
            if Reference.model_validate(item['ref']) == ref), None) if generated is not None else None
        valid_origin = isinstance(evidence, EvidenceRecord) and (
            evidence.source_kind in {'real_user', 'real_public'} if generated is None
            else evidence.source_kind == 'synthetic' and evidence.model_dump(mode='json') == generated_evidence)
        if (not valid_origin
                or evidence.basis_kind != 'observed' or evidence.content_hash != digest
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
            raise TaskConflict('Handoff lacks its current original observed source/result evidence')
    if context.scope.kind == 'project' and context.scope.ref.id != config.project_id:
        raise TaskConflict('Handoff changes its explicitly selected original project')
    native = application.assembly.read_invited_tender_project(organization_id=identity.organization_id,
        project_id=config.project_id, read_guard=nullcontext)
    if native.get('record_sha256') != basis.procurement_source_sha256:
        raise TaskConflict('Handoff no longer matches the current own native procurement invitation source')
    reading.recheck()
    bid.reading.recheck()
    current_row, current_record = _original_record(application, identity, config.screening_record_sha256)
    if current_row != row or current_record != record or application.host.pipeline.worker.snapshots.get(identity) != snapshot:
        raise TaskConflict('Original participation evidence changed during current handoff validation')
    application.host._check(bound=True)
    application._check()
