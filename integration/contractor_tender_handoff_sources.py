"""Derive private A01 -> A02 provenance after the original screening completes.

Only technical identities, digests and observed simulator provenance are
generated here. A02 package terms, pricing, methods and author authority must
already be independently supplied; a local intention creates no native bid.
"""
from contextlib import nullcontext

from integration.contractor_procurement_handoff import ContractorProcurementHandoffBasis
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, StrictRecord, ref_type
from src.actions.contracts.contractor_bid_objects import ContractorBidPackageView
from src.actions.contracts.contractor_objects import ProcurementPackageView
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.coordination.tasks import TaskConflict, task_digest


class TenderHandoffProduction(StrictRecord):
    source_context: ActionContext
    author: GovReviewAuthored
    procurement_source_evidence_ref: ref_type('Evidence')
    screening_result_evidence_ref: ref_type('Evidence')


def derive_handoff_objects(*, context, identity, record, source_package, bid_package,
        native, basis_ref, settings):
    """Pure derivation; the caller must read the actual worker/native records."""
    config = TenderHandoffProduction.model_validate(settings).model_copy(deep=True)
    context = ActionContext.model_validate(context)
    source_package = ProcurementPackageView.model_validate(source_package)
    bid_package = ContractorBidPackageView.model_validate(bid_package)
    author = config.author
    if (identity.action_id != 'CONTRACTOR-A01' or identity.role != 'Contractor'
            or identity.run_id != context.run_id or record['identity'] != identity.as_dict()
            or record['result']['kind'] != 'completed' or record['result']['payload']['choice'] != 'participate'
            or record['result_sha256'] != task_digest(record['result'])
            or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
            or record['source_reading_sha256'] != task_digest(record['source_reading'])
            or record['audit'].get('stages') != {
                'input_validation': 'accepted', 'authorization': 'accepted', 'processor': 'bound'}
            or record['audit'].get('reading', {}).get('status') != 'accepted'
            or record['audit'].get('reading', {}).get('source_mode') != 'formal'
            or source_package.ref != bid_package.ref or context.scope != source_package.scope
            or context.scope != bid_package.scope or context.contract_ref.id != 'CONTRACTOR-A02'
            or context.execution_mode == 'offline_fixture' or context.scope.kind != 'project'
            or native.get('schema_version') != 'gba-v1-invited-tender-project.v1'
            or native.get('record_sha256') != task_digest({k: v for k, v in native.items() if k != 'record_sha256'})
            or native.get('facts_sha256') != task_digest(native.get('facts'))
            or native.get('run_id') != identity.run_id or native.get('organization_id') != identity.organization_id
            or native['facts']['project_id'] != context.scope.ref.id
            or native['facts']['owner_id'] != source_package.employer_ref.id
            or native['facts']['own_invited'] is not True or native['facts']['stage'] != 'tendering'
            or author.scope != context.scope or author.author_organization_id != identity.organization_id
            or author.author_action_id != 'CONTRACTOR-A02'
            or author.author_actor_id != context.actor_id or author.author_function_ref != context.function_ref
            or author.authored_at != context.business_time or author.available_at != context.business_time
            or not author.effective_window.contains(context.business_time)
            or config.procurement_source_evidence_ref == config.screening_result_evidence_ref):
        raise TaskConflict('Runtime handoff requires exact completed participation, supplied bid terms and current own invitation')
    original = [row['projection'] for row in record['source_reading']
        if Reference.model_validate(row['ref']) == source_package.ref]
    if original != [source_package.model_dump(mode='json')]:
        raise TaskConflict('Runtime handoff source package is not the original persisted A01 projection')
    basis_ref = ref_type('ContractorProcurementHandoffBasis').model_validate(basis_ref.model_dump(mode='python'))
    authored = author.model_dump(mode='python')
    authored['evidence_refs'] = [*author.evidence_refs, *[ref for ref in
        (config.procurement_source_evidence_ref, config.screening_result_evidence_ref)
        if ref not in author.evidence_refs]]
    basis = ContractorProcurementHandoffBasis(**authored, ref=basis_ref,
        run_id=identity.run_id, organization_id=identity.organization_id, package_ref=bid_package.ref,
        screening_context_sha256=identity.context_sha256, screening_input_sha256=identity.input_sha256,
        screening_result_sha256=record['result_sha256'], screening_audit_sha256=task_digest(record['audit']),
        screening_projection_sha256=task_digest(source_package.model_dump(mode='json')),
        bid_projection_sha256=task_digest(bid_package.model_dump(mode='json')),
        procurement_source_sha256=native['record_sha256'],
        procurement_source_evidence_ref=config.procurement_source_evidence_ref,
        screening_result_evidence_ref=config.screening_result_evidence_ref)
    # Synthetic describes the simulation/local computation origin. "observed"
    # describes exact saved bytes, never real-world qualification or performance.
    native_evidence = EvidenceRecord(ref=config.procurement_source_evidence_ref,
        source_kind='synthetic', basis_kind='observed',
        locator='gba-invited-tender:' + native['record_sha256'], content_hash=native['record_sha256'],
        effective_window=author.effective_window)
    result_evidence = EvidenceRecord(ref=config.screening_result_evidence_ref,
        source_kind='synthetic', basis_kind='observed', locator='micro-result:' + identity.key,
        content_hash=record['result_sha256'], effective_window=author.effective_window)
    return basis, native_evidence, result_evidence


def publish_handoff(*, application, request, screening, identity, plan, settings):
    """Called after A01, before the original bid pipeline starts reading A02."""
    from integration.contractor_tender_snapshot_sources import ContractorTenderSnapshotReader

    config = TenderHandoffProduction.model_validate(settings).model_copy(deep=True)
    pipeline = application.host.pipeline
    reader = pipeline.assembler.provider.provider
    if (not isinstance(reader, ContractorTenderSnapshotReader) or reader.assembly is not application.assembly
            or reader.organizations is not application.organizations or reader.read_guard is not application.read_guard):
        raise TaskConflict('Runtime handoff requires the original same-run snapshot provider')
    application._check()
    worker, _ = application._execution_components('CONTRACTOR-A01')
    record = worker.get_record(identity)
    if (record is None or application.store.get(identity)['state'] != 'output_formed'
            or application.store.get(identity)['output'] != record['result']
            or worker.snapshots.get(identity)['context'] != screening.context.model_dump(mode='json')
            or record['source_reading'] != screening.reading.evidence()
            or identity.organization_id != request.agent.agent_id):
        raise TaskConflict('Runtime handoff requires its actual finalized original screening task and source cache')
    reading = pipeline.assembler.build_capacity_reading(config.source_context)
    bid_package = reading.resolve(screening.action_input.package_ref)
    source_package = screening.reading.resolve(screening.action_input.package_ref)
    native = application.assembly.read_invited_tender_project(organization_id=identity.organization_id,
        project_id=request.inputs['project']['project_id'], read_guard=nullcontext)
    basis, native_evidence, result_evidence = derive_handoff_objects(context=plan.bid_context,
        identity=identity, record=record, source_package=source_package, bid_package=bid_package,
        native=native, basis_ref=plan.handoff_basis_ref, settings=config)
    reading.recheck()
    return reader.publish_handoff_source(context=plan.bid_context, request=request, identity=identity,
        worker=worker, basis=basis, native_evidence=native_evidence, result_evidence=result_evidence)
