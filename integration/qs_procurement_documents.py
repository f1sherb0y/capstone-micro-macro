"""Prepare a procurement document from an original finalized QS-A05 decision."""
from copy import deepcopy

from integration.qs_procurement_results import QSProcurementResultWorker
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, ref_type, walk_references
from src.actions.contracts.qs_procurement_objects import (
    QSProcurementDocumentView, QSProcurementScopeView, QSProcurementTaskView,
    procurement_document_digest,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization
from src.organization.registry import scope_covers


def prepare_saved_procurement_document(*, worker, identity, current_context, reading,
        execution_versions, validate_history, document_ref, author_authority_ref):
    """Read the saved compile decision once; never execute its processor or model.

    Caller holds the actual source and authorization writer guard. The existing
    worker history gate validates original result/source visibility. This returns
    a saved-status document projection and its provenance for later immutable
    persistence/publication. It does not register a native document, publish a
    tender or substitute an independent buyer publication grant.
    """
    if not isinstance(worker, QSProcurementResultWorker) or not isinstance(reading, ActionReadView):
        raise TaskConflict('Procurement document preparation requires its original result worker and authorized reading')
    context = ActionContext.model_validate(current_context).model_copy(deep=True)
    document_ref = ref_type('ProcurementDocument').model_validate(document_ref).model_copy(deep=True)
    author_authority_ref = ref_type('Authorization').model_validate(author_authority_ref).model_copy(deep=True)
    if (identity.action_id != 'QS-A05' or identity.role != 'QS'
            or reading._organizations.run_id != worker.store.run_id
            or context.scope != reading._context.scope or type(document_ref.version) is not str):
        raise TaskConflict('Procurement document changes its original action, role, run or target version')
    saved = worker.read_completed(identity, current_context=context, reading=reading,
        execution_versions=deepcopy(execution_versions), validate_current=validate_history)
    if saved.result.payload.choice != 'prepare':
        raise TaskConflict('Only the original finalized procurement compile decision can produce its document')
    original_input = saved.action_input
    procurement = reading.resolve(original_input.procurement_scope_ref)
    if not isinstance(procurement, QSProcurementScopeView):
        raise TaskConflict('Procurement document lacks its original concrete scope')
    task = reading.resolve(procurement.task_ref)
    if (not isinstance(task, QSProcurementTaskView) or task.operation != 'compile'
            or task.organization_id != reading.organization_id or task.function_ref != context.function_ref
            or procurement.prior_document_ref == document_ref
            or procurement.saved_document_ref not in (None, document_ref)):
        raise TaskConflict('Procurement document replaces a predecessor or changes its original compilation task')
    schemas = worker.SOURCE_SCHEMAS()
    cache = {Reference.model_validate(item['ref']).key(): item for item in saved.source_reading}
    if len(cache) != len(saved.source_reading):
        raise TaskConflict('Original procurement compilation repeats a source version')
    draft = saved.result.payload.draft.model_copy(deep=True)
    required = [procurement.ref, task.ref, procurement.round_ref, *walk_references(draft)]
    draft_evidence = {ref.key(): ref for ref in walk_references(draft) if ref.kind == 'Evidence'}
    for ref in {ref.key(): ref for ref in required}.values():
        if ref.key() not in cache:
            raise TaskConflict('Saved procurement compilation omits an original draft dependency')
        original = schemas.validate_projection(ref, cache[ref.key()]['projection'])
        if reading.resolve(ref) != original:
            raise TaskConflict('Current procurement document inputs differ from the original saved draft sources')
        for evidence_ref in getattr(original, 'evidence_refs', []):
            draft_evidence[evidence_ref.key()] = evidence_ref
    grant = reading.resolve(author_authority_ref)
    now = context.business_time
    if (not isinstance(grant, Authorization) or author_authority_ref not in context.authorization_refs
            or grant.actor_id != context.actor_id or grant.function_ref != context.function_ref
            or grant.organization_id != reading.organization_id or 'QS-A05' not in grant.action_ids
            or not grant.validity.contains(now) or not any(scope_covers(scope, context.scope) for scope in grant.scopes)
            or document_ref not in context.visible_refs or document_ref not in grant.readable_refs
            or not {ref.key() for ref in required} <= {ref.key() for ref in grant.readable_refs}):
        raise TaskConflict('Procurement document target and draft dependencies lack current author/read authority')
    evidence_refs = {ref.key(): ref for ref in grant.basis_refs}
    evidence_refs.update(draft_evidence)
    for ref in evidence_refs.values():
        evidence = reading.resolve(ref)
        if (not isinstance(evidence, EvidenceRecord)
                or reading._resolver.source_mode == 'formal' and evidence.source_kind == 'synthetic'
                or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
            raise TaskConflict('Procurement document author/draft lacks current original source evidence')
        if ref.key() in cache and evidence != schemas.validate_projection(ref, cache[ref.key()]['projection']):
            raise TaskConflict('Procurement document changes original saved evidence under the same reference')
    projection = QSProcurementDocumentView(ref=document_ref, round_ref=procurement.round_ref,
        draft=draft, status='saved', author_actor_id=context.actor_id, author_function_ref=context.function_ref,
        author_authority_ref=author_authority_ref, author_action_id='QS-A05', scope=context.scope,
        available_at=now, effective_window={'start':now,'end':now,'bounds':'closed_closed'},
        evidence_refs=list(evidence_refs.values()))
    reading.recheck()
    current_record = worker.get_record(identity)
    if current_record is None or current_record['record_sha256'] != saved.record_sha256:
        raise TaskConflict('Original procurement compile record changed during document preparation')
    current_sources = reading.evidence()
    return {'kind':'prepared','projection':projection,
        'projection_sha256':task_digest(projection.model_dump(mode='json')),
        'draft_sha256':procurement_document_digest(draft),'source_identity':saved.identity.as_dict(),
        'source_record_sha256':saved.record_sha256,'source_reading_sha256':saved.source_reading_sha256,
        'source_context':saved.context.model_dump(mode='json'),'context':context.model_dump(mode='json'),
        'reading':current_sources,'reading_sha256':task_digest(current_sources),
        'limitations':['Derived from original saved compile output; no action or model replay.',
            'Persist and publish the immutable document before use; native registration and buyer publication authority remain separate.']}
