"""Check actual QS-A05 compile history and document sources without replay."""
from integration.module_host import module_factory_descriptor
from integration.qs_cost_calculation_validation import QSCostCalculationSourceValidator
from integration.qs_procurement_documents import prepare_saved_procurement_document
from integration.qs_procurement_results import QSProcurementResultWorker, SavedQSProcurement
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.actions.contracts.qs_procurement_objects import (
    QSProcurementDocumentView, QSProcurementScopeView, qs_procurement_schemas,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.models import Authorization, RoleAssignment


class QSProcurementDocumentSourceValidator(QSCostCalculationSourceValidator):
    """Use the original provider beneath the saved-document publication wrapper.

    Caller holds the actual source/authorization writer guard. Historical source
    evidence keeps its original dates; current draft and author evidence must be
    valid now. This gate never recompiles a procurement action, executes a method,
    calls a model, or grants independent buyer publication authority.
    """
    VERSION = 'qs-procurement-document-source-validator.v1'
    ACTION_ID = 'QS-A05'
    SOURCE_SCHEMAS = staticmethod(qs_procurement_schemas)

    def __init__(self, *, worker, organizations, provider, macro_version, source_mode):
        if (not isinstance(worker, QSProcurementResultWorker)
                or worker.store.run_id != organizations.run_id):
            raise ValueError('Procurement source validation requires the original same-run compile worker')
        super().__init__(registry=worker.registry, organizations=organizations, provider=provider,
            macro_version=macro_version, source_mode=source_mode)
        self.worker = worker
        self._worker_components = (worker, worker.store, worker.snapshots, worker.registry)
        self._worker_declared = self._worker_binding()

    def _worker_binding(self):
        return {'client_version': self.worker.client_version, 'model_version': self.worker.model_version,
            'history': module_factory_descriptor(self.worker.read_completed, self.VERSION + '.history'),
            'history_gate': module_factory_descriptor(type(self).validate_history, self.VERSION + '.history_gate'),
            'prepare': module_factory_descriptor(prepare_saved_procurement_document, self.VERSION + '.prepare')}

    def _check(self):
        super()._check()
        if (any(current is not original for current, original in zip(
                (self.worker, self.worker.store, self.worker.snapshots, self.worker.registry), self._worker_components))
                or self.worker.registry is not self.registry or self.worker.snapshots.store is not self.worker.store
                or self.worker.store.run_id != self.organizations.run_id
                or self._worker_binding() != self._worker_declared):
            raise TaskConflict('Procurement source validation changes its original compile worker or code binding')

    def _reading(self, context):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID
                or self._views.source_mode != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Procurement source validation changes its original run, action or source mode')
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != 'QS' or registration.skill is None:
            raise TaskConflict('Procurement source validation requires its original implemented contract and Skill')
        resolver = self._views.build_resolver(context, self.ACTION_ID, 'QS')
        return context, ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'QS')

    def _current_evidence(self, context, reading, saved):
        draft = saved.result.payload.draft
        procurement = reading.resolve(saved.action_input.procurement_scope_ref)
        if not isinstance(procurement, QSProcurementScopeView):
            raise TaskConflict('Procurement history lacks its original concrete compilation scope')
        dependencies = [procurement.ref, procurement.task_ref, procurement.round_ref, *walk_references(draft)]
        current = {ref.key() for ref in dependencies if ref.kind == 'Evidence'}
        for ref in dependencies:
            source = reading.resolve(ref)
            current.update(ref.key() for ref in getattr(source, 'evidence_refs', []))
        for grant in self.organizations.grants(context, self.ACTION_ID, 'QS'):
            supplied = reading.resolve(grant.ref)
            if not isinstance(supplied, Authorization) or supplied != grant:
                raise TaskConflict('Procurement history changes its actual current author grant')
            current.update(ref.key() for ref in grant.basis_refs)
        assignment = reading.resolve(context.function_ref)
        if (not isinstance(assignment, RoleAssignment) or assignment.role != 'QS'
                or assignment.function_ref != context.function_ref):
            raise TaskConflict('Procurement history changes its current original QS function')
        current.update(ref.key() for ref in assignment.basis_refs)
        for key in current:
            evidence = reading.resolve(Reference(kind=key[0], id=key[1], version=key[2]))
            if (not isinstance(evidence, EvidenceRecord)
                    or self._views.source_mode == 'formal' and evidence.source_kind == 'synthetic'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
                raise TaskConflict('Procurement history lacks current original draft or author evidence')
        return current

    def validate_history(self, saved):
        """Gate for worker.read_completed: compare retained originals to actual sources."""
        if not isinstance(saved, SavedQSProcurement):
            raise TaskConflict('Procurement history requires its original typed saved compile result')
        identity = TaskIdentity(**saved.identity.as_dict())
        current, reading = self._reading(saved.current_context)
        source = self.worker.get_record(identity)
        task = self.worker.store.get(identity)
        snapshot = self.worker.snapshots.get(identity)
        original = ActionContext.model_validate(snapshot['context'])
        if (source is None or identity.action_id != self.ACTION_ID or identity.role != 'QS'
                or identity.organization_id != reading.organization_id
                or source['record_sha256'] != saved.record_sha256
                or source['result'] != saved.result.model_dump(mode='json')
                or source['audit'] != saved.audit or snapshot['action_input'] != saved.action_input.model_dump(mode='json')
                or original != saved.context or source['source_reading'] != list(saved.source_reading)
                or source['source_reading_sha256'] != saved.source_reading_sha256
                or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'prepare'
                or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                or task['output'] != source['result'] or task['output_sha256'] != source['result_sha256']
                or task['revision'] < source['attempt_revision']
                or any(getattr(original, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope'))
                or original.business_time.clock_ref != current.business_time.clock_ref
                or original.business_time.offset > current.business_time.offset
                or (original.execution_mode == 'offline_fixture') != (current.execution_mode == 'offline_fixture')):
            raise TaskConflict('Procurement history differs from its original finalized persisted compile result')
        required = self._current_evidence(current, reading, saved)
        self._compare(current, reading, saved.source_reading, current_evidence_refs=required)
        reading.recheck()
        self._check()
        return True

    def validate_source(self, record, context):
        """Save/publication/read gate: derive only from the original saved draft."""
        original = ActionContext.model_validate(record['context'])
        current, reading = self._reading(context)
        saved = record['prepared']
        projection = QSProcurementDocumentView.model_validate(saved['projection'])
        identity = TaskIdentity(**saved['source_identity'])
        if (record['organization_id'] != reading.organization_id or saved['context'] != record['context']
                or any(getattr(original, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                or saved['reading_sha256'] != task_digest(saved['reading'])):
            raise TaskConflict('Procurement document publication substitutes its original author, time or reading')
        self._compare(current, reading, saved['reading'])
        prepared = prepare_saved_procurement_document(worker=self.worker, identity=identity,
            current_context=current, reading=reading, execution_versions=identity.versions,
            validate_history=self.validate_history, document_ref=projection.ref,
            author_authority_ref=projection.author_authority_ref)
        expected = {**prepared, 'projection': prepared['projection'].model_dump(mode='json')}
        for name in ('kind', 'projection', 'projection_sha256', 'draft_sha256', 'source_identity',
                'source_record_sha256', 'source_reading_sha256', 'source_context', 'reading', 'reading_sha256'):
            if expected[name] != saved[name]:
                raise TaskConflict('Current procurement sources differ from their original saved document provenance')
        snapshot = self.worker.snapshots.get(identity)
        if snapshot['action_input'] != record['action_input'] or reading.method_evidence():
            raise TaskConflict('Procurement source validation changes original input or executed an unexpected method')
        reading.recheck()
        self._check()
        return True
