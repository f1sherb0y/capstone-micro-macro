"""Retain saved QS-A05 compile documents at immutable authorized read points."""
from copy import deepcopy
import json

from integration.qs_cost_calculation_publication import (
    QSCostCalculationPublicationStore, QSCostCalculationPublishedViewProvider, _plain,
)
from integration.qs_procurement_results import QSProcurementResultWorker
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.actions.contracts.qs_procurement_objects import (
    QSProcurementDocumentView, QSProcurementScopeView, QSProcurementTaskView,
    procurement_document_digest, qs_procurement_schemas,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.organization.models import Authorization
from src.organization.registry import OrganizationRegistry, scope_covers


class QSProcurementDocumentPublicationStore(QSCostCalculationPublicationStore):
    """Publish a readable saved document, without native tender publication.

    The caller holds the actual source/authorization writer guard. Its independent
    validate_source(record, current_context) gate must verify current sources and
    the original compile history. No arithmetic method or model is invoked here.
    """
    SCHEMA = 'qs-procurement-document-record.v1'
    PUBLICATION_SCHEMA = 'qs-procurement-document-publication.v1'
    ACTION_ID = 'QS-A05'
    METHOD_REF = None
    RECORDS_TABLE = 'qs_procurement_document_records'
    PUBLICATIONS_TABLE = 'qs_procurement_document_publications'
    SOURCE_SCHEMAS = staticmethod(qs_procurement_schemas)

    def __init__(self, *, worker, organizations, validate_source):
        if (not isinstance(worker, QSProcurementResultWorker)
                or not isinstance(organizations, OrganizationRegistry)
                or organizations.run_id != worker.store.run_id or not callable(validate_source)):
            raise ValueError('Procurement documents require their original same-run result worker and source gate')
        self.worker, self.store, self.registry = worker, worker.store, worker.registry
        self.organizations, self.validate_source = organizations, validate_source
        self.schemas = self.SOURCE_SCHEMAS()
        with self.store._transaction():
            self.store._db.execute(f'CREATE TABLE IF NOT EXISTS {self.RECORDS_TABLE} '
                '(record_sha256 TEXT PRIMARY KEY, ref_key TEXT UNIQUE NOT NULL, record TEXT NOT NULL)')
            self.store._db.execute(f'CREATE TABLE IF NOT EXISTS {self.PUBLICATIONS_TABLE} '
                '(boundary_key TEXT PRIMARY KEY, record TEXT NOT NULL)')

    def _binding(self):
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != 'QS' or registration.skill is None:
            raise TaskConflict('Procurement documents require their original implemented QS-A05 binding')
        return {'processor_id': registration.processor_id,
            'skill_sha256': registration.skill.manifest.skill_sha256,
            'contract_source_sha256': registration.contract.source_sha256,
            'client_version': self.worker.client_version, 'model_version': self.worker.model_version}

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id',
                'context', 'action_input', 'prepared', 'binding', 'record_sha256'}
                or record['schema_version'] != self.SCHEMA or record['binding'] != self._binding()
                or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})):
            raise TaskConflict('Saved procurement document changes its original schema, binding or digest')
        context = ActionContext.model_validate(record['context'])
        prepared = record['prepared']
        fields = {'kind', 'projection', 'projection_sha256', 'draft_sha256', 'source_identity',
            'source_record_sha256', 'source_reading_sha256', 'source_context', 'context',
            'reading', 'reading_sha256', 'limitations'}
        if (not isinstance(prepared, dict) or set(prepared) != fields or prepared['kind'] != 'prepared'
                or prepared['context'] != record['context']
                or prepared['reading_sha256'] != task_digest(prepared['reading'])):
            raise TaskConflict('Saved procurement document changes its preparation context or source cache')
        identity = TaskIdentity(**prepared['source_identity'])
        if (identity.run_id != self.store.run_id or identity.organization_id != record['organization_id']
                or identity.action_id != self.ACTION_ID or identity.role != 'QS'
                or context.run_id != identity.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID
                or record['organization_id'] not in self.store.organization_ids):
            raise TaskConflict('Saved procurement document belongs to another compile invocation or recipient')
        source = self.worker.get_record(identity)
        task = self.store.get(identity)
        if (source is None or source['record_sha256'] != prepared['source_record_sha256']
                or source['source_reading_sha256'] != prepared['source_reading_sha256']
                or source['result']['kind'] != 'completed'
                or source['result']['payload']['choice'] != 'prepare'
                or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                or task['output'] != source['result'] or task['output_sha256'] != source['result_sha256']
                or task['revision'] < source['attempt_revision']):
            raise TaskConflict('Procurement document requires its unchanged finalized original compile result')
        snapshot = self.worker.snapshots.get(identity)
        original = ActionContext.model_validate(snapshot['context'])
        if (prepared['source_context'] != snapshot['context'] or record['action_input'] != snapshot['action_input']
                or any(getattr(original, name) != getattr(context, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope'))
                or original.business_time.clock_ref != context.business_time.clock_ref
                or original.business_time.offset > context.business_time.offset
                or (original.execution_mode == 'offline_fixture') != (context.execution_mode == 'offline_fixture')):
            raise TaskConflict('Procurement document substitutes its original input, identity, scope or source mode')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        projection = QSProcurementDocumentView.model_validate(prepared['projection'])
        if (projection.model_dump(mode='json') != prepared['projection'] or projection.status != 'saved'
                or type(projection.ref.version) is not str or projection.draft.model_dump(mode='json') != source['result']['payload']['draft']
                or prepared['draft_sha256'] != procurement_document_digest(projection.draft)
                or prepared['projection_sha256'] != task_digest(prepared['projection'])
                or projection.author_actor_id != context.actor_id or projection.author_function_ref != context.function_ref
                or projection.author_authority_ref not in context.authorization_refs or projection.scope != context.scope
                or projection.available_at != context.business_time
                or projection.effective_window.model_dump(mode='json') != {
                    'start': context.business_time.model_dump(mode='json'),
                    'end': context.business_time.model_dump(mode='json'), 'bounds': 'closed_closed'}):
            raise TaskConflict('Saved procurement document substitutes its draft, target, author or availability')
        sources, originals = {}, {}
        for rows, target in ((prepared['reading'], sources), (source['source_reading'], originals)):
            if not isinstance(rows, list):
                raise TaskConflict('Procurement document source cache must retain its original records')
            for row in rows:
                if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                    raise TaskConflict('Procurement document source cache changes its closed record schema')
                ref = Reference.model_validate(row['ref'])
                if ref.key() in target:
                    raise TaskConflict('Procurement document repeats an immutable source reference')
                target[ref.key()] = self.schemas.validate_projection(ref, row['projection'])
        grants = self._grants(context)
        permitted = {ref.key() for grant in grants for ref in grant.readable_refs} & {ref.key() for ref in context.visible_refs}
        if not set(sources) <= permitted:
            raise TaskConflict('Procurement document retains sources outside its original authorized reading')
        procurement = sources.get(action_input.procurement_scope_ref.key())
        task_view = sources.get(procurement.task_ref.key()) if isinstance(procurement, QSProcurementScopeView) else None
        if (not isinstance(procurement, QSProcurementScopeView) or not isinstance(task_view, QSProcurementTaskView)
                or task_view.operation != 'compile' or task_view.organization_id != record['organization_id']
                or task_view.function_ref != context.function_ref or projection.round_ref != procurement.round_ref
                or procurement.prior_document_ref == projection.ref
                or procurement.saved_document_ref not in (None, projection.ref)):
            raise TaskConflict('Saved procurement document changes its original compilation task or predecessor')
        required = [procurement.ref, task_view.ref, procurement.round_ref, *walk_references(projection.draft)]
        evidence_refs = {ref.key(): ref for ref in walk_references(projection.draft) if ref.kind == 'Evidence'}
        for ref in required:
            if ref.key() not in sources or sources[ref.key()] != originals.get(ref.key()):
                raise TaskConflict('Saved procurement document substitutes an original draft dependency')
            for evidence_ref in getattr(sources[ref.key()], 'evidence_refs', []):
                evidence_refs[evidence_ref.key()] = evidence_ref
        grant = sources.get(projection.author_authority_ref.key())
        if (not isinstance(grant, Authorization) or grant not in grants
                or grant.actor_id != context.actor_id or grant.function_ref != context.function_ref
                or grant.organization_id != record['organization_id'] or self.ACTION_ID not in grant.action_ids
                or not grant.validity.contains(context.business_time)
                or not any(scope_covers(scope, context.scope) for scope in grant.scopes)
                or not {ref.key() for ref in [projection.ref, *required]} <= {ref.key() for ref in grant.readable_refs}
                or projection.ref.key() not in permitted):
            raise TaskConflict('Saved procurement document lacks its original target and author authority')
        evidence_refs.update({ref.key(): ref for ref in grant.basis_refs})
        if {ref.key() for ref in projection.evidence_refs} != set(evidence_refs) or len(projection.evidence_refs) != len(evidence_refs):
            raise TaskConflict('Saved procurement document changes its complete draft/author evidence')
        for ref in evidence_refs.values():
            evidence = sources.get(ref.key())
            if (not isinstance(evidence, EvidenceRecord)
                    or context.execution_mode != 'offline_fixture' and evidence.source_kind == 'synthetic'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)
                    or ref.key() in originals and evidence != originals[ref.key()]):
                raise TaskConflict('Saved procurement document lacks current immutable source evidence')
        return context, projection

    def _publication_refs(self, record, projection):
        return [projection.ref, *walk_references(projection),
            *(Reference.model_validate(row['ref']) for row in record['prepared']['reading'])]

    def _validate_saved_targets(self, record, projection):
        """Recheck retained originals inside the publication/save transaction.

        Snapshot recovery opens its own transaction, so this guard only reads
        already materialized original rows and never tries to recover them.
        """
        prepared = record['prepared']
        identity = TaskIdentity(**prepared['source_identity'])
        with self.store._lock:
            source_raw = self.store._db.execute(f'SELECT record FROM {self.worker.RESULT_TABLE} WHERE task_key=?',
                (identity.key,)).fetchone()
            snapshot_raw = self.store._db.execute('SELECT record FROM invocation_snapshots WHERE task_key=?',
                (identity.key,)).fetchone()
            task = self.store._read(identity)
            if source_raw is None or snapshot_raw is None or task is None:
                raise TaskConflict('Saved procurement document lost its original compile evidence')
            source = json.loads(source_raw[0])
            snapshot = self.worker.snapshots._validate(json.loads(snapshot_raw[0]), identity)
            if (source['record_sha256'] != prepared['source_record_sha256']
                    or source['record_sha256'] != task_digest({k: v for k, v in source.items() if k != 'record_sha256'})
                    or source['identity'] != identity.as_dict()
                    or snapshot['action_input'] != record['action_input']
                    or snapshot['context'] != prepared['source_context']
                    or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                    or task['output'] != source['result'] or task['output_sha256'] != source['result_sha256']
                    or task['revision'] < source['attempt_revision']):
                raise TaskConflict('Original procurement compile evidence changed before document publication')

    def save(self, prepared, *, context, reading):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        grants = self._grants(context)
        if (not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations
                or reading.organization_id != grants[0].organization_id):
            raise TaskConflict('Procurement save requires its original current authorized reading')
        reading.check_method_context(context, self.ACTION_ID)
        reading.recheck()
        prepared = _plain(deepcopy(prepared))
        if prepared['reading'] != reading.evidence():
            raise TaskConflict('Procurement save substitutes its actual document preparation source cache')
        identity = TaskIdentity(**prepared['source_identity'])
        snapshot = self.worker.snapshots.get(identity)
        record = {'schema_version': self.SCHEMA, 'organization_id': reading.organization_id,
            'context': context.model_dump(mode='json'), 'action_input': deepcopy(snapshot['action_input']),
            'prepared': prepared, 'binding': self._binding()}
        record['record_sha256'] = task_digest(record)
        _, projection = self._validate(record)
        if self.validate_source(deepcopy(record), context.model_copy(deep=True)) is not True:
            raise TaskConflict('Procurement document save requires independent actual source/history validation')
        reading.recheck()
        self._validate(record)
        ref_key = task_digest([self.store.run_id, self.ACTION_ID, self._execution_ref(projection)])
        with self.store._transaction():
            if self._grants(context) != grants:
                raise TaskConflict('Procurement document save authority changed during validation')
            self._validate_saved_targets(record, projection)
            prior = self.store._db.execute(f'SELECT record FROM {self.RECORDS_TABLE} WHERE ref_key=?', (ref_key,)).fetchone()
            if prior is not None and json.loads(prior[0]) != record:
                raise TaskConflict('An original procurement document reference cannot replace its saved compile result')
            if prior is None:
                self.store._db.execute(f'INSERT INTO {self.RECORDS_TABLE} VALUES (?,?,?)',
                    (record['record_sha256'], ref_key, canonical(record)))
        return deepcopy(record)


class QSProcurementDocumentPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    """Expose only saved-status QS-A05 documents through the authorized provider."""

    def __init__(self, *, provider, publications):
        if not isinstance(publications, QSProcurementDocumentPublicationStore):
            raise ValueError('Procurement document publication provider requires its original document store')
        super().__init__(provider=provider, publications=publications)
