"""Explicit offline Owner intake backed by original Contractor A02 journals."""
from copy import deepcopy
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator

from integration.action_versions import prepared_action_execution_versions
from integration.contractor_bid_actions import ContractorBidActionAssembler
from integration.contractor_bid_fixture_sources import ContractorBidFixtureSettings, build_sources as build_bid_sources
from integration.contractor_bid_results import ContractorBidResultWorker
from integration.contractor_owner_tender_handoff import ContractorBidJournalSource
from integration.owner_role_contract_fixture_sources import OwnerFixtureSourceSettings, build_sources as build_owner_sources
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, ScopeRef, StrictRecord, TextId, TimeWindow, ref_type
from src.actions.contracts.owner_tender_objects import OwnerTenderBidView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class DeclaredBidSourceRecord(StrictRecord):
    ref: Reference
    projection: dict


class ContractorBidHistorySettings(StrictRecord):
    request: RoleContractInvocation
    source_settings: ContractorBidFixtureSettings
    identity: TaskIdentity
    macro_version: TextId
    client_version: TextId
    policy_version: TextId
    model_version: TextId
    # A02 journals retain only the digest. Fresh host executions export this
    # witness, checked against that digest and current Contractor source values.
    original_source_reading: Annotated[list[DeclaredBidSourceRecord], Field(min_length=1)]

    @field_validator('identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class DeclaredContractorBidRegistration(StrictRecord):
    schema_version: Literal['contractor-bid-registration.v1']
    registration_id: TextId
    run_id: TextId
    source_identity: TaskIdentity
    source_record_sha256: Digest
    source_result_sha256: Digest
    source_snapshot_sha256: Digest
    source_audit_reading_sha256: Digest
    bid: OwnerTenderBidView
    draft: dict
    planned_tasks: list[dict]
    native_evidence_ref: ref_type('Evidence')
    recipient_organization_id: TextId
    recipient_actor_id: TextId
    recipient_function_ref: ref_type('FunctionAssignment')
    recipient_authorization_refs: Annotated[list[ref_type('Authorization')], Field(min_length=1)]
    scope: ScopeRef
    effective_window: TimeWindow
    sharing_authorized: bool
    current_state: Literal['received', 'withdrawn', 'superseded']

    @field_validator('source_identity', mode='before')
    @classmethod
    def original_identity(cls, value):
        return TaskIdentity(**value) if isinstance(value, dict) else value


class ReceivedContractorBidSettings(StrictRecord):
    history: ContractorBidHistorySettings
    registration: DeclaredContractorBidRegistration


class OwnerContractorBidFixtureSettings(OwnerFixtureSourceSettings):
    received_bids: Annotated[list[ReceivedContractorBidSettings], Field(min_length=1)]


class _BidHistory:
    def __init__(self, settings, sources):
        self.settings = settings
        self.sources = sources
        history = settings.history
        self.worker = ContractorBidResultWorker(store=sources.store,
            snapshots=InvocationSnapshotStore(sources.store), registry=sources.registry,
            client_version=history.client_version, model_version=history.model_version,
            validate_invocation=sources.validators.invocation, validate_wait=sources.validators.wait,
            validate_recovery=sources.validators.recovery)
        self.assembler = ContractorBidActionAssembler(registry=sources.registry,
            organizations=sources.organizations, provider=sources.provider,
            macro_version=history.macro_version, source_mode='fixture', methods=sources.methods,
            policy_version=history.policy_version, model_version=history.model_version)

    def read(self):
        history, registration = self.settings.history, self.settings.registration
        context = history.request.context
        with self.sources.read_guard(context):
            supplied = history.request.action_input
            prepared = self.assembler.build(context, **{key: supplied[key] for key in
                ('pricing_profile_ref', 'capacity_ref', 'cost_refs', 'allowed_method_refs')})
            reading = prepared.reading
            try:
                if (prepared.action_input.model_dump(mode='json') != supplied
                        or reading.organization_id != history.identity.organization_id
                        or prepared_action_execution_versions(prepared, client_version=history.client_version,
                            model_version=history.model_version) != history.identity.versions):
                    raise TaskConflict('Received bid history changes original input, Contractor or execution versions')
                with self.worker.store._lock:
                    record = self.worker.get_record(history.identity)
                    task = self.worker.store.get(history.identity)
                    snapshot = self.worker.snapshots.get(history.identity)
                if record is None:
                    raise TaskConflict('Received bid requires its existing original Contractor result')
                original = RoleContractInvocation.model_validate({'schema_version': 'role-contract-invocation.v1',
                    'context': snapshot['context'], 'action_input': snapshot['action_input']}).context
                if (record['result']['kind'] != 'completed' or record['result']['payload']['choice'] != 'submit_bid'
                        or snapshot['action_input'] != supplied
                        or any(getattr(original, key) != getattr(context, key)
                            for key in ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'execution_mode'))
                        or original.business_time.clock_ref != context.business_time.clock_ref
                        or original.business_time.offset > context.business_time.offset
                        or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                        or task['output'] != record['result'] or task['output_sha256'] != record['result_sha256']
                        or record['record_sha256'] != registration.source_record_sha256
                        or record['result_sha256'] != registration.source_result_sha256
                        or task_digest(snapshot) != registration.source_snapshot_sha256
                        or task_digest(record['audit']['reading']) != registration.source_audit_reading_sha256):
                    raise TaskConflict('Received bid substitutes finalized original task, record, snapshot or audit')
                witness = [row.model_dump(mode='json') for row in history.original_source_reading]
                if (len({row.ref.key() for row in history.original_source_reading}) != len(witness)
                        or task_digest(witness) != record['audit']['reading'].get('sha256')):
                    raise TaskConflict('Received bid source witness does not match the original A02 audit digest')
                for row in history.original_source_reading:
                    current = reading.resolve(row.ref)
                    if current.model_dump(mode='json') != row.projection:
                        raise TaskConflict('Original bid source witness differs from current authorized Contractor sources')
                if reading.evidence() != witness:
                    raise TaskConflict('Received bid witness omits or reorders original source reads')
                return ContractorBidJournalSource(worker=self.worker, identity=history.identity)
            finally:
                reading.recheck()


class _BidReception:
    VERSION = 'configured-owner-contractor-bid-fixture-sources.v1'

    def __init__(self, request, settings, owner, histories):
        self.request = request.model_copy(deep=True)
        self.settings = settings.model_copy(deep=True)
        self.owner, self.histories = owner, histories
        self._digest = task_digest(self.settings.model_dump(mode='json'))
        self._closed = False

    def _check(self, context):
        if (self._closed or context != self.request.context
                or task_digest(self.settings.model_dump(mode='json')) != self._digest):
            raise TaskConflict('Owner bid intake changes configured recipient or registration')
        self.owner.evidence()
        for history in self.histories.values():
            history.sources.evidence()

    def read_contractor_bid(self, *, context, source_task_sha256):
        self._check(context)
        if source_task_sha256 not in self.histories:
            raise TaskConflict('Owner bid intake requires an explicitly selected original Contractor task')
        with self.owner.read_guard(context):
            source = self.histories[source_task_sha256].read()
            self._check(context)
            return source

    def validate_reception(self, identity, record, snapshot, bid, evidence, context):
        self._check(context)
        key = TaskIdentity(**identity).key
        selected = self.histories.get(key)
        if selected is None:
            raise TaskConflict('Owner bid registration changes selected Contractor task')
        registration = selected.settings.registration
        source = self.read_contractor_bid(context=context, source_task_sha256=key)
        with source.worker.store._lock:
            original_record = source.worker.get_record(source.identity)
            original_snapshot = source.worker.snapshots.get(source.identity)
        payload = record['result']['payload']
        if (record != original_record or snapshot != original_snapshot or bid != registration.bid
                or registration.source_identity.as_dict() != identity
                or registration.run_id != context.run_id or registration.current_state != 'received'
                or registration.sharing_authorized is not True or bid.status != 'submitted'
                or registration.draft != payload['bid'] or registration.planned_tasks != payload['planned_tasks']
                or registration.recipient_organization_id != self.settings.source_projection['organization_id']
                or registration.recipient_actor_id != context.actor_id
                or registration.recipient_function_ref != context.function_ref
                or registration.recipient_authorization_refs != context.authorization_refs
                or registration.scope != context.scope
                or registration.scope.model_dump(mode='json') != payload['bid']['scope_ref']
                or registration.native_evidence_ref != evidence.ref or evidence.ref not in bid.evidence_refs
                or evidence.basis_kind != 'observed' or evidence.source_kind != 'synthetic'
                or not registration.effective_window.contains(context.business_time)):
            raise TaskConflict('Independent Owner registration changes whole bid draft, tasks, native view or permission')
        self._check(context)
        return True

    def evidence(self):
        self._check(self.request.context)
        return {**deepcopy(self.owner.evidence()), 'schema_version': self.VERSION,
            'received_bids': [{'source_task_sha256': row.history.identity.key,
                'registration_sha256': task_digest(row.registration.model_dump(mode='json')),
                'source_witness_sha256': task_digest([r.model_dump(mode='json') for r in row.history.original_source_reading])}
                for row in self.settings.received_bids], 'configuration_sha256': self._digest}

    def close(self):
        if not self._closed:
            self._closed = True
            with ExitStack() as cleanup:
                cleanup.callback(self.owner.close)
                for history in self.histories.values():
                    cleanup.callback(history.sources.close)


def build_sources(*, request, output_directory, offline, settings):
    """Bind existing bid journals and independently supplied Owner intake declarations."""
    request = RoleContractInvocation.model_validate(request).model_copy(deep=True)
    settings = OwnerContractorBidFixtureSettings.model_validate(settings).model_copy(deep=True)
    if (offline is not True or request.context.execution_mode != 'offline_fixture'
            or request.execution_path not in {None, 'deterministic'}
            or request.context.contract_ref.id != 'OWN-A09' or settings.action_id != 'OWN-A09'):
        raise ValueError('Bid intake fixture requires an explicit offline Owner A09')
    selected = settings.received_bids
    if (len({row.history.identity.key for row in selected}) != len(selected)
            or len({row.registration.bid.ref.key() for row in selected}) != len(selected)):
        raise ValueError('Bid intake fixture repeats selected tasks or native bids')
    for row in selected:
        history, registration = row.history, row.registration
        journal = Path(history.source_settings.journal_path).resolve()
        if (history.identity.action_id != 'CONTRACTOR-A02' or history.identity.role != 'Contractor'
                or history.identity.purpose != 'action' or history.source_settings.action_id != 'CONTRACTOR-A02'
                or history.request.context.contract_ref.id != 'CONTRACTOR-A02'
                or history.request.context.execution_mode != 'offline_fixture'
                or history.request.execution_path not in {None, 'deterministic'}
                or history.identity.run_id != request.context.run_id or history.request.context.run_id != request.context.run_id
                or history.request.context.business_time != request.context.business_time
                or history.identity.as_dict() != registration.source_identity.as_dict()
                or registration.run_id != request.context.run_id or registration.current_state != 'received'
                or registration.sharing_authorized is not True
                or registration.recipient_organization_id != settings.source_projection['organization_id']
                or journal == Path(settings.journal_path).resolve() or not journal.is_file()):
            raise ValueError('Bid intake requires existing separate Contractor journals and same-run independent registrations')
    owner, resources, histories = None, [], {}
    try:
        owner = build_owner_sources(request=request, output_directory=output_directory, offline=offline,
            settings=settings.model_dump(mode='json', exclude={'received_bids'}))
        for row in selected:
            sources = build_bid_sources(request=row.history.request, output_directory=output_directory,
                offline=offline, settings=row.history.source_settings)
            resources.append(sources)
            histories[row.history.identity.key] = _BidHistory(row, sources)
        binding = _BidReception(request, settings, owner, histories)
        return replace(owner, version=binding.VERSION, read_contractor_bid=binding.read_contractor_bid,
            validate_contractor_bid_reception=binding.validate_reception, evidence=binding.evidence, close=binding.close)
    except Exception:
        with ExitStack() as cleanup:
            if owner is not None:
                cleanup.callback(owner.close)
            for sources in resources:
                cleanup.callback(sources.close)
        raise
