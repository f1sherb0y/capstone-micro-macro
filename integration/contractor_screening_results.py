"""Persist A01 outcomes and retain original source evidence for later A02 handoff."""
from copy import deepcopy
from dataclasses import dataclass
import json

from integration.contractor_bid_results import ContractorBidResultWorker
from integration.contractor_screening_actions import PreparedContractorScreening
from integration.bindings.gba_v1_contractor_screening import gba_contractor_screening_source_schemas
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.contractor_objects import ProcurementPackageView
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class SavedContractorScreening:
    """Historical evidence only; there is no executable runner or revived read authorization."""
    identity: TaskIdentity
    registry: object
    context: ActionContext
    action_input: object
    result: object
    audit: dict
    organization_id: str
    source_reading: tuple[dict, ...]
    input_sha256: str
    context_sha256: str
    reading_sha256: str
    record_sha256: str


class ContractorScreeningResultWorker(ContractorBidResultWorker):
    """Reuse claim-once execution and recovery; save A01 original projections as well."""
    SCHEMA = 'contractor-screening-result.v1'
    ACTION_ID = 'CONTRACTOR-A01'
    PREPARED_TYPE = PreparedContractorScreening
    RESULT_TABLE = 'contractor_screening_results'
    WAIT_KIND = 'manual_screening_result_review'
    EXTRA_FIELDS = frozenset({'source_reading', 'source_reading_sha256'})

    def _result_extras(self, prepared):
        prepared.reading.recheck()
        original = prepared.reading.evidence()
        if task_digest(original) != prepared.reading_sha256:
            raise TaskConflict('Original screening assembly cache changed; no historical snapshot substitution')
        return {'source_reading': original, 'source_reading_sha256': prepared.reading_sha256}

    @classmethod
    def validate_saved_record(cls, identity, record, *, registry, snapshots):
        snapshot = super().validate_saved_record(identity, record, registry=registry, snapshots=snapshots)
        rows = record['source_reading']
        if not isinstance(rows, list) or task_digest(rows) != record['source_reading_sha256']:
            raise TaskConflict('Saved screening source evidence changed')
        schemas = gba_contractor_screening_source_schemas()
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                raise TaskConflict('Saved screening source reading has missing or extra fields')
            ref = Reference.model_validate(row['ref'])
            if ref.key() in seen:
                raise TaskConflict('Saved screening source reading repeats an original version')
            seen.add(ref.key())
            schemas.validate_projection(ref, row['projection'])
        package_ref = Reference.model_validate(snapshot['action_input']['package_ref'])
        packages = [row for row in rows if Reference.model_validate(row['ref']) == package_ref]
        if len(packages) != 1:
            raise TaskConflict('Saved screening source evidence lacks its exact original package')
        ProcurementPackageView.model_validate(packages[0]['projection'])
        return snapshot

    def read_completed(self, identity, *, current_context, reading, execution_versions, validate_current):
        """Read completed originals under fresh A02 authority; no historical permission checks or replay."""
        identity = TaskIdentity(**identity.as_dict())
        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        if (not isinstance(reading, ActionReadView) or not callable(validate_current)
                or current.run_id != identity.run_id or current.contract_ref.id != 'CONTRACTOR-A02'
                or reading.organization_id != identity.organization_id
                or execution_versions != identity.versions):
            raise TaskConflict('Screening recovery requires current A02 authority and all original execution versions')
        reading.check_method_context(current, 'CONTRACTOR-A02')
        record = self.get_record(identity)
        row = self.store.get(identity)
        if (record is None or record['result']['kind'] != 'completed'
                or row['state'] != 'output_formed' or row['output'] != record['result']
                or row['revision'] <= record['attempt_revision']):
            raise TaskConflict('Screening handoff requires its saved completed and finalized original result')
        snapshot = self.snapshots.get(identity)
        context = ActionContext.model_validate(snapshot['context'])
        registration = self.registry.get(self.ACTION_ID)
        action_input = registration.contract.validate_input(snapshot['action_input'])
        result = registration.contract.result_adapter.validate_python(record['result'])
        if (context.scope != current.scope or context.business_time.clock_ref != current.business_time.clock_ref
                or context.business_time.offset > current.business_time.offset
                or (context.execution_mode == 'offline_fixture') != (current.execution_mode == 'offline_fixture')):
            raise TaskConflict('Screening recovery changes original scope, clock, order or source mode')
        # Current A02 may use a different concrete representation of the same
        # package. Authorize its exact reference; the handoff separately proves
        # the two original projection digests and common procurement source.
        reading.resolve(action_input.package_ref)
        saved = SavedContractorScreening(identity=identity, registry=self.registry, context=context,
            action_input=action_input, result=result, audit=deepcopy(record['audit']),
            organization_id=identity.organization_id, source_reading=tuple(deepcopy(record['source_reading'])),
            input_sha256=identity.input_sha256, context_sha256=identity.context_sha256,
            reading_sha256=record['source_reading_sha256'], record_sha256=record['record_sha256'])
        if validate_current(saved, current.model_copy(deep=True)) is not True:
            raise TaskConflict('Original screening versions/evidence and current source require explicit host validation')
        if (saved.identity.as_dict() != record['identity'] or saved.audit != record['audit']
                or saved.context.model_dump(mode='json') != snapshot['context']
                or saved.action_input.model_dump(mode='json') != snapshot['action_input']
                or saved.result.model_dump(mode='json') != record['result']
                or task_digest(list(saved.source_reading)) != record['source_reading_sha256']):
            raise TaskConflict('Host validation changed the retained original screening evidence')
        reading.recheck()
        if (self.store.get(identity) != row or self.get_record(identity) != record
                or self.snapshots.get(identity) != snapshot):
            raise TaskConflict('Original screening task, record or snapshot changed during host validation')
        return saved


def read_screening_history(*, store, registry, snapshots, identity, record_sha256,
        current_context, reading):
    """Read an explicitly selected A01 record under current A02 read authority.

    No worker is constructed and no historical permission is revived. This
    supplies original evidence only; the pipeline must still run its independent
    handoff/source gate before treating participation as a valid A02 relation.
    Missing snapshots and unfinished tasks require their actual original data.
    """
    from src.actions.registry import ActionRegistry
    from src.coordination.tasks import TaskStore

    identity = TaskIdentity(**identity.as_dict())
    current = ActionContext.model_validate(current_context).model_copy(deep=True)
    if (not isinstance(store, TaskStore) or not isinstance(registry, ActionRegistry)
            or snapshots.store is not store or not isinstance(reading, ActionReadView)
            or reading._organizations.run_id != store.run_id or identity.run_id != store.run_id
            or identity.role != 'Contractor' or identity.action_id != 'CONTRACTOR-A01'
            or identity.purpose != 'action' or current.run_id != store.run_id
            or current.contract_ref.kind != 'ActionContract' or current.contract_ref.id != 'CONTRACTOR-A02'
            or reading.organization_id != identity.organization_id):
        raise TaskConflict('Screening history requires original same-run dependencies and current A02 authority')
    reading.check_method_context(current, 'CONTRACTOR-A02')
    with store._lock:
        row = store.get(identity)
        tables = {item[0] for item in store._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('contractor_screening_results','invocation_snapshots')")}
        if tables != {'contractor_screening_results', 'invocation_snapshots'}:
            raise TaskConflict('Screening history lacks its original result or snapshot table')
        original_snapshot = store._db.execute('SELECT record FROM invocation_snapshots WHERE task_key=?',
            (identity.key,)).fetchone()
        raw = store._db.execute('SELECT record FROM contractor_screening_results WHERE task_key=?',
            (identity.key,)).fetchone()
        if raw is None or original_snapshot is None:
            raise TaskConflict('Screening history requires existing original result and invocation snapshot')
        record = json.loads(raw[0])
        snapshot = ContractorScreeningResultWorker.validate_saved_record(identity, record,
            registry=registry, snapshots=snapshots)
        if (record['record_sha256'] != record_sha256 or record['result']['kind'] != 'completed'
                or row['state'] != 'output_formed' or row['output'] != record['result']
                or row['revision'] <= record['attempt_revision']):
            raise TaskConflict('Screening history changes the selected original finalized record')
    context = ActionContext.model_validate(snapshot['context'])
    if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != identity.action_id
            or context.run_id != current.run_id or context.scope != current.scope
            or context.business_time.clock_ref != current.business_time.clock_ref
            or context.business_time.offset > current.business_time.offset
            or (context.execution_mode == 'offline_fixture') != (current.execution_mode == 'offline_fixture')):
        raise TaskConflict('Screening history changes original contract, scope, clock or source mode')
    contract = registry.get('CONTRACTOR-A01').contract
    action_input = contract.validate_input(snapshot['action_input'])
    reading.resolve(action_input.package_ref)
    saved = SavedContractorScreening(identity=identity, registry=registry, context=context,
        action_input=action_input, result=contract.result_adapter.validate_python(record['result']),
        audit=deepcopy(record['audit']), organization_id=identity.organization_id,
        source_reading=tuple(deepcopy(record['source_reading'])), input_sha256=identity.input_sha256,
        context_sha256=identity.context_sha256, reading_sha256=record['source_reading_sha256'],
        record_sha256=record['record_sha256'])
    reading.recheck()
    with store._lock:
        if (store.get(identity) != row
                or store._db.execute('SELECT record FROM contractor_screening_results WHERE task_key=?',
                    (identity.key,)).fetchone() != raw
                or store._db.execute('SELECT record FROM invocation_snapshots WHERE task_key=?',
                    (identity.key,)).fetchone() != original_snapshot):
            raise TaskConflict('Original screening record or invocation changed during its historical read')
    return saved
