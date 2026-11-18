"""Persist original OWN-A01 screening evidence without creating formal cases."""
from copy import deepcopy
from dataclasses import dataclass

from integration.contractor_bid_results import ContractorBidResultWorker
from integration.owner_observation_actions import PreparedOwnerObservation
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.owner_objects import (
    OwnerCaseView, OwnerManagementCapacityView, OwnerObjectiveView, owner_observation_schemas,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, task_digest


@dataclass(frozen=True)
class SavedOwnerObservation:
    identity: TaskIdentity
    context: ActionContext
    current_context: ActionContext
    action_input: object
    result: object
    audit: dict
    source_reading: tuple[dict, ...]
    source_reading_sha256: str
    record_sha256: str


class OwnerObservationResultWorker(ContractorBidResultWorker):
    """Reuse claim-once, result-first persistence and explicit host recovery."""
    SCHEMA = 'owner-observation-result.v1'
    ACTION_ID = 'OWN-A01'
    ROLE = 'Owner'
    PREPARED_TYPE = PreparedOwnerObservation
    RESULT_TABLE = 'owner_observation_results'
    WAIT_KIND = 'manual_owner_observation_result_review'
    EXECUTION_ERROR_CODE = 'owner_observation_execution_exception'
    EXTRA_FIELDS = frozenset({'source_reading', 'source_reading_sha256'})
    SOURCE_SCHEMAS = staticmethod(owner_observation_schemas)
    READ_ACTION_IDS = frozenset({'OWN-A01', 'OWN-A16'})
    SAVED_TYPE = SavedOwnerObservation

    def __init__(self, *, store, snapshots, registry, client_version, model_version,
            validate_invocation, validate_wait, validate_recovery=None):
        if not isinstance(store, TaskStore) or store.path is None:
            raise ValueError('Owner results require the original persistent task journal')
        super().__init__(store=store, snapshots=snapshots, registry=registry,
            client_version=client_version, model_version=model_version,
            validate_invocation=validate_invocation, validate_wait=validate_wait, validate_recovery=validate_recovery)

    def _result_extras(self, prepared):
        prepared.reading.recheck()
        sources = prepared.reading.evidence()
        if task_digest(sources) != prepared.reading_sha256:
            raise TaskConflict('Original owner observation assembly sources changed')
        return {'source_reading': sources, 'source_reading_sha256': prepared.reading_sha256}

    def _validate_record(self, identity, record):
        snapshot = super()._validate_record(identity, record)
        sources = record['source_reading']
        if not isinstance(sources, list) or task_digest(sources) != record['source_reading_sha256']:
            raise TaskConflict('Saved owner observation source digest changed')
        context = ActionContext.model_validate(snapshot['context'])
        permitted = {ref.key() for ref in context.visible_refs}
        schemas, originals = self.SOURCE_SCHEMAS(), {}
        for row in sources:
            if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                raise TaskConflict('Saved owner sources change the closed reference/projection schema')
            ref = Reference.model_validate(row['ref'])
            if ref.key() in originals or ref.key() not in permitted:
                raise TaskConflict('Saved owner source is duplicated or outside original visibility')
            originals[ref.key()] = schemas.validate_projection(ref, row['projection'])
        self._validate_primary_sources(snapshot, identity, originals)
        return snapshot

    def _validate_primary_sources(self, snapshot, identity, originals):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        if (action_input.scope_ref != context.scope
                or any(ref.key() not in originals for ref in walk_references(action_input))
                or context.scope.kind == 'organization' and context.scope.ref.id != identity.organization_id):
            raise TaskConflict('Saved owner observation changes original scope or lacks complete original input sources')
        for ref, schema in ((action_input.objective_ref, OwnerObjectiveView),
                (action_input.capacity_ref, OwnerManagementCapacityView),
                *((ref, OwnerCaseView) for ref in action_input.existing_case_refs)):
            source = originals.get(ref.key())
            if not isinstance(source, schema) or source.organization_id != identity.organization_id:
                raise TaskConflict('Saved owner observation substitutes another owner private source')
        for refs in (action_input.observations, action_input.opportunity_refs, action_input.existing_case_refs):
            if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
                raise TaskConflict('Saved owner observation repeats a physical source or case')

    def read_completed(self, identity, *, current_context, reading, execution_versions, validate_current):
        """Read own finalized local evidence under current authority, never replay.

        A saved create_case/propose intention does not prove an actual private
        case, project, right, downstream brief or management reservation exists.
        """
        identity = TaskIdentity(**identity.as_dict())
        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        if (not isinstance(reading, ActionReadView) or not callable(validate_current)
                or current.run_id != identity.run_id or current.contract_ref.kind != 'ActionContract'
                or current.contract_ref.id not in self.READ_ACTION_IDS or reading._role != self.ROLE
                or reading.organization_id != identity.organization_id or execution_versions != identity.versions
                or (reading._resolver.source_mode == 'fixture') != (current.execution_mode == 'offline_fixture')):
            raise TaskConflict('Owner history requires current own action authority and all original execution versions')
        reading.check_method_context(current, current.contract_ref.id)
        reading.recheck()
        record = self.get_record(identity)
        task = self.store.get(identity)
        if (record is None or record['result']['kind'] != 'completed'
                or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                or task['output'] != record['result'] or task['output_sha256'] != record['result_sha256']
                or task['revision'] < record['attempt_revision']):
            raise TaskConflict('Owner history requires its finalized completed original local result')
        snapshot = self.snapshots.get(identity)
        original = ActionContext.model_validate(snapshot['context'])
        fields = ('run_id', 'actor_id')
        if current.contract_ref.id == self.ACTION_ID:
            fields += ('function_ref', 'contract_ref')
        if (any(getattr(original, name) != getattr(current, name) for name in fields)
                or not self._history_scope_compatible(original, current, identity)
                or original.business_time.clock_ref != current.business_time.clock_ref
                or original.business_time.offset > current.business_time.offset
                or (original.execution_mode == 'offline_fixture') != (current.execution_mode == 'offline_fixture')):
            raise TaskConflict('Owner history changes original actor, scope, clock, function or source mode')
        contract = self.registry.get(self.ACTION_ID).contract
        saved = self.SAVED_TYPE(identity, original, current, contract.validate_input(snapshot['action_input']),
            contract.result_adapter.validate_python(record['result']), deepcopy(record['audit']),
            tuple(deepcopy(record['source_reading'])), record['source_reading_sha256'], record['record_sha256'])
        if validate_current(deepcopy(saved)) is not True:
            raise TaskConflict('Owner history requires current host validation of original sources and visibility')
        reading.recheck()
        return saved

    def _history_scope_compatible(self, original, current, identity):
        if original.scope == current.scope:
            return True
        # Reading own history under a new case's current authority does not
        # establish a business relation. The explicit A01 -> A16 handoff must
        # still validate the independently observed actual case and evidence.
        if (self.ACTION_ID != 'OWN-A01' or current.contract_ref.id != 'OWN-A16'
                or current.scope.kind != 'assessment_case'):
            return False
        if original.scope.kind == 'organization':
            return original.scope.ref.id == identity.organization_id
        return (original.scope.kind == 'assessment_case'
            and (original.scope.ref.kind, original.scope.ref.id) == (current.scope.ref.kind, current.scope.ref.id))
