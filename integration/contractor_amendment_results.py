"""Persist original Contractor A03 decisions without procurement mutations."""
from copy import deepcopy
from dataclasses import dataclass

from integration.contractor_amendment_actions import (
    PreparedContractorAmendment, validate_contractor_amendment_sources,
)
from integration.contractor_bid_results import ContractorBidResultWorker
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.contractor_amendment_objects import contractor_amendment_schemas
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, task_digest


@dataclass(frozen=True)
class SavedContractorAmendment:
    """Own historical intention; it proves no accepted revision or resource release."""
    identity: TaskIdentity
    context: ActionContext
    current_context: ActionContext
    action_input: object
    result: object
    audit: dict
    source_reading: tuple[dict, ...]
    source_reading_sha256: str
    record_sha256: str


class ContractorAmendmentResultWorker(ContractorBidResultWorker):
    """Reuse claim-once execution, saved-result recovery and explicit pending rules."""
    SCHEMA = 'contractor-amendment-result.v1'
    ACTION_ID = 'CONTRACTOR-A03'
    ROLE = 'Contractor'
    PREPARED_TYPE = PreparedContractorAmendment
    RESULT_TABLE = 'contractor_amendment_results'
    WAIT_KIND = 'manual_contractor_amendment_result_review'
    EXECUTION_ERROR_CODE = 'contractor_amendment_execution_exception'
    EXTRA_FIELDS = frozenset({'source_reading', 'source_reading_sha256'})
    SOURCE_SCHEMAS = staticmethod(contractor_amendment_schemas)
    SAVED_TYPE = SavedContractorAmendment

    def __init__(self, *, store, snapshots, registry, client_version, model_version,
            validate_invocation, validate_wait, validate_recovery=None):
        if not isinstance(store, TaskStore) or store.path is None:
            raise ValueError('Amendment results require the original persistent task journal')
        super().__init__(store=store, snapshots=snapshots, registry=registry,
            client_version=client_version, model_version=model_version,
            validate_invocation=validate_invocation, validate_wait=validate_wait,
            validate_recovery=validate_recovery)

    def _result_extras(self, prepared):
        prepared.reading.recheck()
        sources = prepared.reading.evidence()
        if task_digest(sources) != prepared.reading_sha256:
            raise TaskConflict('Original amendment assembly source evidence changed')
        return {'source_reading': sources, 'source_reading_sha256': prepared.reading_sha256}

    def _validate_record(self, identity, record):
        snapshot = super()._validate_record(identity, record)
        rows = record['source_reading']
        if not isinstance(rows, list) or task_digest(rows) != record['source_reading_sha256']:
            raise TaskConflict('Saved amendment source digest changed')
        context = ActionContext.model_validate(snapshot['context'])
        permitted = {ref.key() for ref in context.visible_refs}
        originals, schemas = {}, self.SOURCE_SCHEMAS()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                raise TaskConflict('Saved amendment sources change the closed reference/projection schema')
            ref = Reference.model_validate(row['ref'])
            if ref.key() in originals or ref.key() not in permitted:
                raise TaskConflict('Saved amendment source is duplicated or outside original visibility')
            originals[ref.key()] = schemas.validate_projection(ref, row['projection'])
        self._validate_primary_sources(snapshot, identity, originals)
        return snapshot

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        unique_refs(action_input.clarification_refs)
        unique_refs(action_input.reservation_refs)
        if any(ref.key() not in originals for ref in walk_references(action_input)):
            raise TaskConflict('Saved amendment lacks complete original input source snapshots')
        validate_contractor_amendment_sources(action_input, context=context,
            organization_id=identity.organization_id, sources=originals)

    def read_completed(self, identity, *, current_context, reading, execution_versions, validate_current):
        """Read own finalized originals under current action authority without replay."""
        identity = TaskIdentity(**identity.as_dict())
        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        if (not isinstance(reading, ActionReadView) or not callable(validate_current)
                or current.run_id != identity.run_id or current.contract_ref.kind != 'ActionContract'
                or current.contract_ref.id != self.ACTION_ID or reading._role != self.ROLE
                or reading.organization_id != identity.organization_id or execution_versions != identity.versions
                or (reading._resolver.source_mode == 'fixture') != (current.execution_mode == 'offline_fixture')):
            raise TaskConflict('Amendment history requires current own authority and all original execution versions')
        reading.check_method_context(current, self.ACTION_ID)
        reading.recheck()
        record = self.get_record(identity)
        task = self.store.get(identity)
        if (record is None or record['result']['kind'] != 'completed'
                or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                or task['output'] != record['result'] or task['output_sha256'] != record['result_sha256']
                or task['revision'] < record['attempt_revision']):
            raise TaskConflict('Amendment history requires its finalized completed original result')
        snapshot = self.snapshots.get(identity)
        original = ActionContext.model_validate(snapshot['context'])
        if (any(getattr(original, name) != getattr(current, name)
                for name in ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope'))
                or original.business_time.clock_ref != current.business_time.clock_ref
                or original.business_time.offset > current.business_time.offset
                or (original.execution_mode == 'offline_fixture') != (current.execution_mode == 'offline_fixture')):
            raise TaskConflict('Amendment history changes original actor, function, scope, clock or source mode')
        contract = self.registry.get(self.ACTION_ID).contract
        saved = self.SAVED_TYPE(identity, original, current,
            contract.validate_input(snapshot['action_input']),
            contract.result_adapter.validate_python(record['result']), deepcopy(record['audit']),
            tuple(deepcopy(record['source_reading'])), record['source_reading_sha256'], record['record_sha256'])
        if validate_current(deepcopy(saved)) is not True:
            raise TaskConflict('Amendment history requires current host validation of original sources and visibility')
        reading.recheck()
        return saved
