"""Configured tender projections reconciled with actual own GBA source records."""
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from integration.bindings.gba_v1 import GbaV1Assembly
from integration.bindings.gba_v1_views import MACRO_VERSION
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId, TimePoint, ref_type
from src.coordination.tasks import TaskConflict, canonical, task_digest
from src.methods.models import Digest
from src.organization.registry import OrganizationRegistry


class TenderSnapshotObject(StrictRecord):
    ref: Reference
    value: dict


class TenderSnapshotProjection(StrictRecord):
    run_id: TextId
    macro_version: Literal['gba-public-2026-08-21']
    state_version: TextId
    read_token: TextId
    business_time: TimePoint
    organization_id: TextId
    objects: list[TenderSnapshotObject]


class TenderNativeObjectBinding(StrictRecord):
    """Bind only native provenance, never independent professional values."""
    ref: Reference
    source: Literal['enterprise_resources', 'invited_tender']


class TenderCurrentOccupancyBinding(StrictRecord):
    """An explicitly authorized observation at one current clock point only."""
    mapping_ref: ref_type('GbaCapacityMapping')
    commitment_ref: ref_type('ResourceCommitment')


class TenderSourceSnapshot(StrictRecord):
    context: ActionContext
    project_id: TextId
    native_resource_sha256: Digest | None
    native_tender_sha256: Digest | None
    projection: TenderSnapshotProjection
    native_bindings: list[TenderNativeObjectBinding] = Field(default_factory=list)
    current_occupancy_bindings: list[TenderCurrentOccupancyBinding] = Field(default_factory=list)
    clarification_evidence_ref: ref_type('Evidence') | None = None

    @model_validator(mode='after')
    def explicit_native_binding(self):
        if (self.native_resource_sha256 is None) != (self.native_tender_sha256 is None):
            raise ValueError('Tender source must pin both native snapshots or bind both on the current request')
        if self.native_resource_sha256 is not None and (self.native_bindings or self.current_occupancy_bindings):
            raise ValueError('Pinned tender sources cannot also declare runtime native bindings')
        if len({binding.ref.key() for binding in self.native_bindings}) != len(self.native_bindings):
            raise ValueError('Tender native bindings repeat an original object reference')
        if len({binding.mapping_ref.key() for binding in self.current_occupancy_bindings}) != len(self.current_occupancy_bindings):
            raise ValueError('Tender current occupancy bindings repeat a capacity mapping')
        return self


class TenderSourceSnapshotFile(StrictRecord):
    schema_version: Literal['contractor-tender-source-snapshots.v1']
    version: TextId
    run_id: TextId
    simulation_id: TextId | None
    snapshots: Annotated[list[TenderSourceSnapshot], Field(min_length=1)]


class ContractorTenderSnapshotSettings(StrictRecord):
    version: TextId
    snapshot_path: TextId
    snapshot_sha256: Digest
    bind_native_on_request: bool = False


def bind_snapshot_provenance(snapshot, *, resource_sha256, tender_sha256, simulation_id):
    """Fill the explicitly declared native digest fields in a frozen template."""
    snapshot = deepcopy(snapshot)
    snapshot['native_resource_sha256'] = resource_sha256
    snapshot['native_tender_sha256'] = tender_sha256
    objects = {Reference.model_validate(item['ref']).key(): item for item in snapshot['projection']['objects']}
    for binding in snapshot.get('native_bindings', []):
        ref = Reference.model_validate(binding['ref'])
        item = objects.get(ref.key())
        if item is None:
            raise TaskConflict('Native binding lacks its explicitly supplied original object')
        digest = resource_sha256 if binding['source'] == 'enterprise_resources' else tender_sha256
        if ref.kind == 'GbaCapacityMapping' and binding['source'] == 'enterprise_resources':
            fields = {'source_record_sha256': digest, 'simulation_id': simulation_id}
        elif ref.kind == 'GbaTenderPackageTerms' and binding['source'] == 'invited_tender':
            fields = {'source_record_sha256': digest, 'simulation_id': simulation_id}
        elif (ref.kind == 'Evidence' and item['value'].get('source_kind') == 'synthetic'
                and item['value'].get('basis_kind') == 'observed'):
            fields = {'content_hash': digest}
        else:
            raise TaskConflict('Native binding may fill only current native mapping/terms provenance or simulator evidence')
        for name, expected in fields.items():
            if name not in item['value'] or item['value'][name] not in (None, expected):
                raise TaskConflict('Native binding cannot replace an independently supplied object field or pinned source')
            item['value'][name] = expected
    return snapshot


def bind_snapshot_current_occupancy(snapshot, *, resource):
    """Resolve explicit null amounts from an intact own current native read.

    Only the current integer tick is observable, encoded as [tick, tick+1).
    The next integer point is excluded. Future commitments,
    capacity totals, demands, authorizations and independent calendars remain
    byte-for-byte supplied values; this does not reserve or release resources.
    """
    result = deepcopy(snapshot)
    if not result.get('current_occupancy_bindings'):
        return result
    from decimal import Decimal, InvalidOperation
    now = result['context']['business_time']
    if (resource.get('schema_version') != 'gba-v1-enterprise-resources.v1'
            or resource.get('source_kind') != 'macro_execution'
            or resource.get('resource_unit') != 'normalized_enterprise_capacity'
            or resource.get('run_id') != result['context']['run_id']
            or resource.get('organization_id') != result['projection']['organization_id']
            or resource.get('observed_tick') != now['offset']
            or resource.get('record_sha256') != result['native_resource_sha256']
            or resource.get('facts_sha256') != task_digest(resource.get('facts'))
            or resource.get('record_sha256') != task_digest({k:v for k,v in resource.items() if k!='record_sha256'})):
        raise TaskConflict('Current occupancy requires its intact own native read at the exact current point')
    try:
        occupied = Decimal(str(resource['facts']['occupied_resource']))
    except (KeyError, InvalidOperation):
        raise TaskConflict('Current occupancy requires a finite nonnegative observed amount') from None
    if not occupied.is_finite() or occupied < 0:
        raise TaskConflict('Current occupancy requires a finite nonnegative observed amount')
    objects = {Reference.model_validate(item['ref']).key():item for item in result['projection']['objects']}
    for binding in result['current_occupancy_bindings']:
        row = objects.get(Reference.model_validate(binding['mapping_ref']).key())
        if row is None:
            raise TaskConflict('Current occupancy lacks its original explicitly authorized mapping')
        mapping = row['value']
        matches = [c for c in mapping['data']['commitments'] if c['commitment_ref']==binding['commitment_ref']]
        evidence = objects.get(Reference.model_validate(mapping['source_evidence_ref']).key())
        if (mapping['organization_id'] != resource['organization_id'] or mapping['run_id'] != resource['run_id']
                or mapping['simulation_id'] != resource['simulation_id']
                or mapping['source_record_sha256'] != resource['record_sha256']
                or len(matches)!=1 or evidence is None
                or evidence['value'].get('basis_kind')!='observed'
                or evidence['value'].get('content_hash')!=resource['record_sha256']):
            raise TaskConflict('Current occupancy changes its original enterprise, mapping or observed evidence')
        commitment = matches[0]
        if (commitment['quantity']['value'] is not None
                or commitment['quantity']['unit'] != resource['resource_unit']
                or commitment['quantity']['basis_ref'] != mapping['source_evidence_ref']
                or commitment['window'] != {'start':now,'end':{**now,'offset':now['offset']+1},'bounds':'closed_open'}):
            raise TaskConflict('Current occupancy may fill only an explicit null amount at one current point')
        if occupied == 0:
            # Capacity methods represent zero load by absence of a commitment;
            # the original explicit zero observation remains in the journal.
            mapping['data']['commitments'].remove(commitment)
        else:
            commitment['quantity']['value'] = str(occupied)
    return result


def derive_screening_feedback_profile(base, *, profile_ref, evidence_ref, memory, business_time,
        decline_after_prior_submissions, decline_after_prior_evaluations=None, decline_after_prior_declines=None,
        decline_after_prior_final_accounts=None, decline_after_prior_payment_delays=None):
    """Apply an explicit private policy to verified prior native observations.

    This does not infer open contracts, available resources, award, loss or
    future performance. Submission counts describe only observed past bids.
    """
    from src.actions.contracts.common import EvidenceRecord
    from src.actions.contracts.contractor_objects import OpportunityScreeningProfileView

    # Preserve strict kind validation while accepting refs restored through the
    # generic transport type. Parent-model instances are not typed ref DTOs.
    profile_ref = ref_type('OpportunityScreeningProfile').model_validate(profile_ref.model_dump(mode='python'))
    evidence_ref = ref_type('Evidence').model_validate(evidence_ref.model_dump(mode='python'))
    base = OpportunityScreeningProfileView.model_validate(base)
    business_time = TimePoint.model_validate(business_time)
    limits = (decline_after_prior_submissions, decline_after_prior_evaluations, decline_after_prior_declines,
              decline_after_prior_final_accounts, decline_after_prior_payment_delays)
    if (not any(limit is not None for limit in limits)
            or any(limit is not None and (type(limit) is not int or limit < 1) for limit in limits)
            or profile_ref == base.ref or memory.get('schema_version') != 'gba-v1-own-tender-context.v1'
            or memory.get('organization_id') != base.organization_ref.id
            or memory.get('context_sha256') != task_digest(
                {name: value for name, value in memory.items() if name != 'context_sha256'})
            or not base.effective_window.contains(business_time)
            or type(memory.get('submitted_count')) is not int or memory['submitted_count'] < 0):
        raise TaskConflict('Feedback policy requires an intact own context, explicit limit and new profile version')
    evaluated_pause=False
    if decline_after_prior_evaluations is not None:
        if (type(decline_after_prior_evaluations) is not int or decline_after_prior_evaluations<1
                or memory.get('own_evaluated_bids',{}).get('schema_version')!='gba-v1-own-evaluated-bids.v1'):
            raise TaskConflict('Evaluation feedback preference requires actual own queried results and an explicit positive limit')
        evaluated_pause=len(memory['own_evaluated_bids']['records'])>=decline_after_prior_evaluations
    declined_pause = False
    if decline_after_prior_declines is not None:
        outcomes = memory.get('outcomes')
        if (type(memory.get('declined_count')) is not int or memory['declined_count'] < 0
                or not isinstance(outcomes, list)
                or memory['declined_count'] != sum(row.get('effect') == 'native_bid_declined' for row in outcomes)):
            raise TaskConflict('Decline feedback preference requires the exact actual own declined outcomes')
        declined_pause = memory['declined_count'] >= decline_after_prior_declines
    submitted_pause = decline_after_prior_submissions is not None and memory['submitted_count'] >= decline_after_prior_submissions
    settled_pause = False
    if decline_after_prior_final_accounts is not None:
        history = memory.get('own_final_accounts', {})
        query = history.get('query', {})
        if (history.get('schema_version') != 'gba-v1-own-tender-final-accounts.v1'
                or query.get('schema_version') != 'gba-v1-own-final-accounts.v1'
                or query.get('role') != 'Contractor' or query.get('organization_id') != memory['organization_id']
                or query.get('run_id') != memory['run_id'] or query.get('simulation_id') != memory['simulation_id']
                or query.get('as_of_tick') != memory['as_of_tick']
                or query.get('record_sha256') != task_digest({k: v for k, v in query.items() if k != 'record_sha256'})
                or not isinstance(query.get('settlements'), list)):
            raise TaskConflict('Final-account preference requires the actual intact own native query')
        expected = [row for row in query['settlements']
            if not memory['project_only'] or row['project_id'] == memory['project_id']]
        if history.get('records') != expected or any(row['tick'] >= memory['as_of_tick']
                or row['contractor_id'] != memory['organization_id'] for row in expected):
            raise TaskConflict('Final-account preference changes its exact earlier own settlement scope')
        settled_pause = len(expected) >= decline_after_prior_final_accounts
    delayed_pause = False
    if decline_after_prior_payment_delays is not None:
        history = memory.get('own_progress_payments', {})
        query = history.get('query', {})
        if (history.get('schema_version') != 'gba-v1-own-tender-progress-payments.v1'
                or query.get('schema_version') != 'gba-v1-own-progress-payments.v1'
                or query.get('role') != 'Contractor' or query.get('organization_id') != memory['organization_id']
                or query.get('run_id') != memory['run_id'] or query.get('simulation_id') != memory['simulation_id']
                or query.get('as_of_tick') != memory['as_of_tick']
                or query.get('record_sha256') != task_digest({k: v for k, v in query.items() if k != 'record_sha256'})
                or not isinstance(query.get('delay_events'), list) or not isinstance(query.get('payment_requests'), list)):
            raise TaskConflict('Payment-delay preference requires the actual intact own native query')
        expected = [row for row in query['delay_events']
            if not memory['project_only'] or row['project_id'] == memory['project_id']]
        if (history.get('delays') != expected
                or len({row['event_id'] for row in query['delay_events']}) != len(query['delay_events'])
                or any(row['tick'] >= memory['as_of_tick'] or row['contractor_id'] != memory['organization_id']
                    for row in [*query['payment_requests'], *query['delay_events']])):
            raise TaskConflict('Payment-delay preference changes its exact earlier own request scope')
        for delay in query['delay_events']:
            matches = [row for row in query['payment_requests'] if row['event_id'] == delay['request_event_id']
                and row['payment_status'] == 'delayed' and all(row[k] == delay[k] for k in
                    ('project_id', 'tick', 'owner_id', 'contractor_id', 'payment_amount'))]
            if len(matches) != 1:
                raise TaskConflict('Payment-delay preference lost its one original delayed request')
        delayed_pause = len(expected) >= decline_after_prior_payment_delays
    policy = 'decline_new_work' if submitted_pause or evaluated_pause or declined_pause or settled_pause or delayed_pause else base.policy
    raw = base.model_dump(mode='json')
    raw.update(ref=profile_ref.model_dump(mode='json'), policy=policy,
        effective_window={'start': business_time.model_dump(mode='json'),
            'end': base.effective_window.end.model_dump(mode='json'),
            'bounds': 'closed_closed' if base.effective_window.bounds.endswith('closed') else 'closed_open'},
        evidence_refs=[*raw['evidence_refs'], *([] if evidence_ref in base.evidence_refs
            else [evidence_ref.model_dump(mode='json')])])
    profile = OpportunityScreeningProfileView.model_validate(raw)
    evidence = EvidenceRecord(ref=evidence_ref, source_kind='synthetic', basis_kind='observed',
        locator='micro-tender-feedback:' + memory['context_sha256'],
        content_hash=memory['context_sha256'], effective_window=profile.effective_window)
    return profile, evidence


def _load_snapshot_file(settings):
    raw = Path(settings.snapshot_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != settings.snapshot_sha256:
        raise TaskConflict('Tender source file differs from its explicitly configured SHA')

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Tender source file repeats a JSON field')
            value[key] = item
        return value

    def reject_constant(value):
        raise ValueError('Tender source file requires finite JSON values')

    payload = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object,
        parse_constant=reject_constant)
    # JSON-mode validation retains original strict decimal/date transports;
    # allow_nan=False also rejects finite-looking exponent overflow.
    return TenderSourceSnapshotFile.model_validate_json(json.dumps(payload, allow_nan=False))


class ContractorTenderSnapshotReader:
    """Read explicit independent projections under the actual engine writer guard.

    Native reconciliation proves the original own enterprise/project read point
    only. Projection schemas, professional competence, quantities, costs and
    business relationships remain checks of the original assemblers/processors.
    This reader neither produces those facts nor authenticates arbitrary authored
    claims. It is a concrete provider dependency, not a complete tender host.
    """
    VERSION = 'contractor-tender-snapshot-reader.v1'

    def __init__(self, *, assembly, organizations, read_guard, settings):
        if (not isinstance(assembly, GbaV1Assembly) or not isinstance(organizations, OrganizationRegistry)
                or organizations.run_id != assembly.client.run_id or not callable(read_guard)):
            raise ValueError('Tender snapshot reader requires the actual same-run assembly, authority and writer guard')
        assembly._validate_components()
        self.settings = ContractorTenderSnapshotSettings.model_validate(settings).model_copy(deep=True)
        document = _load_snapshot_file(self.settings)
        if (document.version != self.settings.version or document.run_id != assembly.client.run_id
                or document.simulation_id != assembly.client.simulation_id
                    and not (document.simulation_id is None and self.settings.bind_native_on_request)):
            raise TaskConflict('Tender snapshot file changes its original version, run or simulation')
        self.assembly, self.organizations, self.read_guard = assembly, organizations, read_guard
        self._components = (assembly, assembly.engine, assembly.client, organizations, read_guard)
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._snapshots = {}
        for snapshot in document.snapshots:
            context, projection = snapshot.context, snapshot.projection
            if (snapshot.native_resource_sha256 is None and not self.settings.bind_native_on_request
                    or context.run_id != document.run_id or context.contract_ref.kind != 'ActionContract'
                    or context.contract_ref.id not in {'CONTRACTOR-A01', 'CONTRACTOR-A02'}
                    or projection.run_id != context.run_id or projection.read_token != context.read_token
                    or projection.business_time != context.business_time
                    or assembly.client.organization_roles.get(projection.organization_id) != 'Contractor'
                    or context.scope.kind == 'project' and context.scope.ref.id != snapshot.project_id):
                raise TaskConflict('Tender snapshot changes its original action, scope, read point or Contractor')
            key = task_digest(context.model_dump(mode='json'))
            refs = [item.ref.key() for item in projection.objects]
            if key in self._snapshots or len(refs) != len(set(refs)):
                raise TaskConflict('Tender source file duplicates an invocation or original reference')
            raw_snapshot = snapshot.model_dump(mode='json')
            if not snapshot.native_bindings:
                raw_snapshot.pop('native_bindings')
            if not snapshot.current_occupancy_bindings:
                raw_snapshot.pop('current_occupancy_bindings')
            self._snapshots[key] = raw_snapshot
        self._snapshot_sha256 = task_digest(self._snapshots)
        self._served_contexts = set()

    def _check(self):
        actual = (self.assembly, self.assembly.engine, self.assembly.client, self.organizations, self.read_guard)
        if (any(value is not original for value, original in zip(actual, self._components))
                or self.organizations.run_id != self.assembly.client.run_id
                or task_digest(self.settings.model_dump(mode='json')) != self._settings_sha256
                or task_digest(self._snapshots) != self._snapshot_sha256
                or hashlib.sha256(Path(self.settings.snapshot_path).read_bytes()).hexdigest()
                    != self.settings.snapshot_sha256):
            raise TaskConflict('Tender source components, configuration or immutable snapshots changed')
        self.assembly._validate_components()

    def project(self, *, context, organization_id, grants):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        with self.read_guard():
            self._check()
            snapshot = self._snapshots.get(task_digest(context.model_dump(mode='json')))
            if snapshot is None or snapshot['projection']['organization_id'] != organization_id:
                raise TaskConflict('No explicit tender source snapshot for the original invocation and recipient')
            current = self.organizations.grants(context, context.contract_ref.id, 'Contractor')
            if not current or grants != current or current[0].organization_id != organization_id:
                raise TaskConflict('Tender source read substitutes current original Contractor authority')
            permitted = {ref.key() for grant in current for ref in grant.readable_refs}
            permitted &= {ref.key() for ref in context.visible_refs}
            if any(Reference.model_validate(item['ref']).key() not in permitted
                    for item in snapshot['projection']['objects']):
                raise TaskConflict('Tender source file discloses an object outside current read authority')
            resolved = self._resolved_snapshot(context, snapshot)
            resource = self.assembly.read_enterprise_resources(organization_id=organization_id, read_guard=nullcontext)
            tender = self.assembly.read_invited_tender_project(organization_id=organization_id,
                project_id=snapshot['project_id'], read_guard=nullcontext)
            if (resource['macro_version'] != MACRO_VERSION
                    or resource['record_sha256'] != resolved['native_resource_sha256']
                    or tender.get('record_sha256') != resolved['native_tender_sha256']
                    or resource['observed_tick'] != tender.get('observed_tick')):
                raise TaskConflict('Tender source snapshot no longer matches actual own GBA resources and invitation')
            self._check()
            if self.organizations.grants(context, context.contract_ref.id, 'Contractor') != current:
                raise TaskConflict('Tender source authority changed during the original native read')
            projection = deepcopy(resolved['projection'])
            if snapshot.get('clarification_evidence_ref') is not None:
                from integration.contractor_tender_clarification_continuation import response_consumption
                consumption = response_consumption(self, context, snapshot)
                if Reference.model_validate(consumption['evidence']['ref']).key() not in permitted:
                    raise TaskConflict('Clarification response evidence exceeds current read authority')
                projection['objects'].append({'ref':consumption['evidence']['ref'],'value':consumption['evidence']})
                projection['state_version'] = task_digest([projection['state_version'],consumption['record_sha256']])
            key = self._micro_key(context)
            with self.assembly.client.tasks._lock:
                row = self.assembly.client.tasks._db.execute(
                    'SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if row is not None:
                generated = json.loads(row[0])
                expected = {'run_id': context.run_id, 'organization_id': organization_id,
                    'context_sha256': task_digest(context.model_dump(mode='json')),
                    'base_snapshot_sha256': task_digest(snapshot), 'source_file_sha256': self.settings.snapshot_sha256}
                if (generated.get('schema_version') != 'contractor-tender-micro-indicators.v1'
                        or any(generated.get(name) != value for name, value in expected.items())
                        or generated.get('record_sha256') != task_digest(
                            {name: value for name, value in generated.items() if name != 'record_sha256'})):
                    raise TaskConflict('Generated tender indicator source changed its original recipient, read point or digest')
                objects = {Reference.model_validate(item['ref']).key(): item for item in projection['objects']}
                for item in generated['objects']:
                    ref = Reference.model_validate(item['ref'])
                    if ref.key() not in permitted or ref.key() in objects and objects[ref.key()] != item:
                        raise TaskConflict('Generated indicators replace an immutable source or exceed current authority')
                    objects[ref.key()] = deepcopy(item)
                projection['objects'] = list(objects.values())
                projection['state_version'] = task_digest([projection['state_version'], generated['record_sha256']])
            with self.assembly.client.tasks._lock:
                row = self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key=?',
                    (self._feedback_key(context),)).fetchone()
            if row is not None:
                generated = json.loads(row[0])
                expected = {'schema_version': 'contractor-screening-feedback-source.v1',
                    'run_id': context.run_id, 'organization_id': organization_id,
                    'context_sha256': task_digest(context.model_dump(mode='json')),
                    'base_snapshot_sha256': task_digest(snapshot), 'source_file_sha256': self.settings.snapshot_sha256}
                if (any(generated.get(name) != value for name, value in expected.items())
                        or generated.get('record_sha256') != task_digest(
                            {name: value for name, value in generated.items() if name != 'record_sha256'})):
                    raise TaskConflict('Private screening feedback changed its original source, recipient or context')
                objects = {Reference.model_validate(item['ref']).key(): item for item in projection['objects']}
                for item in generated['objects']:
                    ref = Reference.model_validate(item['ref'])
                    if ref.key() not in permitted or ref.key() in objects and objects[ref.key()] != item:
                        raise TaskConflict('Private screening feedback replaces an original source or exceeds authority')
                    objects[ref.key()] = deepcopy(item)
                projection['objects'] = list(objects.values())
                projection['state_version'] = task_digest([projection['state_version'], generated['record_sha256']])
            handoff = self.handoff_source(context)
            if handoff is not None:
                objects = {Reference.model_validate(item['ref']).key(): item for item in projection['objects']}
                for item in handoff['objects']:
                    ref = Reference.model_validate(item['ref'])
                    if ref.key() not in permitted or ref.key() in objects:
                        raise TaskConflict('Runtime handoff replaces an original source or exceeds current authority')
                    objects[ref.key()] = deepcopy(item)
                projection['objects'] = list(objects.values())
                projection['state_version'] = task_digest([projection['state_version'], handoff['record_sha256']])
            self._served_contexts.add(task_digest(context.model_dump(mode='json')))
            return projection

    def _native_binding_key(self, context):
        return 'contractor_tender_native_binding:' + task_digest([
            self.settings.snapshot_sha256, context.model_dump(mode='json')])

    def _resolved_snapshot(self, context, snapshot):
        if snapshot['native_resource_sha256'] is not None:
            return deepcopy(snapshot)
        with self.assembly.client.tasks._lock:
            row = self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key=?',
                (self._native_binding_key(context),)).fetchone()
        if row is None:
            raise TaskConflict('Tender source template has not been bound to its actual current native request')
        record = json.loads(row[0])
        expected = {'schema_version': 'contractor-tender-native-binding.v1',
            'run_id': context.run_id, 'simulation_id': self.assembly.client.simulation_id,
            'organization_id': snapshot['projection']['organization_id'],
            'context_sha256': task_digest(context.model_dump(mode='json')),
            'template_sha256': task_digest(snapshot), 'source_file_sha256': self.settings.snapshot_sha256}
        if (any(record.get(name) != value for name, value in expected.items())
                or record.get('record_sha256') != task_digest(
                    {name: value for name, value in record.items() if name != 'record_sha256'})):
            raise TaskConflict('Native source binding changed its original request, template, run or recipient')
        resolved = bind_snapshot_provenance(snapshot, resource_sha256=record['native_resource_sha256'],
            tender_sha256=record['native_tender_sha256'], simulation_id=record['simulation_id'])
        if snapshot.get('current_occupancy_bindings'):
            resolved = bind_snapshot_current_occupancy(resolved, resource=record['current_occupancy_source'])
        resolved['projection']['state_version'] = task_digest([
            resolved['projection']['state_version'], record['record_sha256']])
        return resolved

    def bind_request_sources(self, *, request, contexts):
        """Pin declared templates under the actual current native writer guard.

        The original file remains immutable. Bindings enter the same technical
        journal before a token is served; repeated requests cannot update them.
        Explicit current-point occupancy observations are read, never inferred;
        no future calendar, permission, native state or clock is generated.
        """
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1
        from gba_construction_sim.backend.agents.operation_specs import get_operation_contract, validate_operation_inputs

        request = AgentProposalRequestV1.model_validate(request).model_copy(deep=True)
        contexts = [ActionContext.model_validate(context).model_copy(deep=True) for context in contexts]
        with self.read_guard():
            self._check()
            contract = get_operation_contract('consider_tender', 'Contractor')
            if (not self.settings.bind_native_on_request or request.agent.role != 'Contractor'
                    or request.operation != 'consider_tender' or request.operation_contract != contract
                    or type(request.metadata.get('tick')) is not int
                    or request.metadata['tick'] != self.assembly.engine.current_tick
                    or request.metadata.get('simulation_id') not in {None, self.assembly.client.simulation_id}
                    or not contexts or len({task_digest(context.model_dump(mode='json')) for context in contexts}) != len(contexts)):
                raise TaskConflict('Native template binding requires explicitly enabled exact current Contractor request and contexts')
            validate_operation_inputs(contract, request.inputs)
            project_id = request.inputs['project']['project_id']
            resource = self.assembly.read_enterprise_resources(organization_id=request.agent.agent_id, read_guard=nullcontext)
            tender = self.assembly.read_invited_tender_project(organization_id=request.agent.agent_id,
                project_id=project_id, read_guard=nullcontext)
            if (tender.get('kind') == 'needs_information' or tender.get('observed_tick') != resource['observed_tick']):
                raise TaskConflict('Native template binding requires a current own invitation and coherent native source reads')
            records = []
            for context in contexts:
                snapshot = self._snapshots.get(task_digest(context.model_dump(mode='json')))
                grants = self.organizations.grants(context, context.contract_ref.id, 'Contractor')
                if (snapshot is None or snapshot['projection']['organization_id'] != request.agent.agent_id
                        or snapshot['project_id'] != project_id or context.scope.kind != 'project'
                        or context.scope.ref.id != project_id or context.execution_mode == 'offline_fixture'
                        or not grants or grants[0].organization_id != request.agent.agent_id):
                    raise TaskConflict('Native template binding requires original same-project recipient authority and supplied context')
                permitted = {ref.key() for grant in grants for ref in grant.readable_refs}
                permitted &= {ref.key() for ref in context.visible_refs}
                if any(Reference.model_validate(item['ref']).key() not in permitted
                        for item in snapshot['projection']['objects']):
                    raise TaskConflict('Native template binding exceeds the supplied current read authority')
                if snapshot['native_resource_sha256'] is not None:
                    if (snapshot['native_resource_sha256'] != resource['record_sha256']
                            or snapshot['native_tender_sha256'] != tender['record_sha256']):
                        raise TaskConflict('Explicitly pinned sources differ from the current native request')
                    continue
                # Validate every placeholder before committing any context.
                resolved = bind_snapshot_provenance(snapshot, resource_sha256=resource['record_sha256'],
                    tender_sha256=tender['record_sha256'], simulation_id=self.assembly.client.simulation_id)
                bind_snapshot_current_occupancy(resolved, resource=resource)
                body = {'schema_version': 'contractor-tender-native-binding.v1',
                    'run_id': context.run_id, 'simulation_id': self.assembly.client.simulation_id,
                    'organization_id': request.agent.agent_id, 'request_id': request.request_id,
                    'request_sha256': task_digest(request.model_dump(mode='json')),
                    'context_sha256': task_digest(context.model_dump(mode='json')),
                    'template_sha256': task_digest(snapshot), 'source_file_sha256': self.settings.snapshot_sha256,
                    'native_resource_sha256': resource['record_sha256'], 'native_tender_sha256': tender['record_sha256']}
                if snapshot.get('current_occupancy_bindings'):
                    body['current_occupancy_source'] = deepcopy(resource)
                if tender['facts'].get('own_invitation_origin') is not None:
                    body['own_invitation_origin'] = deepcopy(tender['facts']['own_invitation_origin'])
                body['record_sha256'] = task_digest(body)
                records.append((self._native_binding_key(context), body))
            self._check()
            store = self.assembly.client.tasks
            with store._transaction():
                for key, body in records:
                    prior = store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
                    if prior is not None:
                        if json.loads(prior[0]) != body:
                            raise TaskConflict('Original native request binding cannot be replaced')
                    elif body['context_sha256'] in self._served_contexts:
                        raise TaskConflict('Native binding requires an unread source token')
                    else:
                        store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(body)))
            return [deepcopy(body) for _, body in records]

    def _handoff_key(self, context):
        return 'contractor_tender_handoff_source:' + task_digest([
            self.settings.snapshot_sha256, context.model_dump(mode='json')])

    def handoff_source(self, context):
        """Read exact private provenance; this does not serve or mutate a token."""
        self._check()
        snapshot = self._snapshots.get(task_digest(context.model_dump(mode='json')))
        if snapshot is None:
            raise TaskConflict('Runtime handoff requires an explicitly supplied original source context')
        with self.assembly.client.tasks._lock:
            row = self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key=?',
                (self._handoff_key(context),)).fetchone()
        if row is None:
            return None
        record = json.loads(row[0])
        expected = {'schema_version': 'contractor-tender-handoff-source.v1',
            'run_id': context.run_id, 'simulation_id': self.assembly.client.simulation_id,
            'organization_id': snapshot['projection']['organization_id'],
            'context_sha256': task_digest(context.model_dump(mode='json')),
            'base_snapshot_sha256': task_digest(snapshot), 'source_file_sha256': self.settings.snapshot_sha256}
        if (any(record.get(name) != value for name, value in expected.items())
                or record.get('record_sha256') != task_digest(
                    {name: value for name, value in record.items() if name != 'record_sha256'})):
            raise TaskConflict('Runtime handoff changed its original recipient, source, context or digest')
        return deepcopy(record)

    def publish_handoff_source(self, *, context, request, identity, worker, basis, native_evidence, result_evidence):
        """Publish only one private relation and its actual native/A01 evidence."""
        from integration.contractor_screening_results import ContractorScreeningResultWorker
        from integration.contractor_procurement_handoff import ContractorProcurementHandoffBasis
        from src.actions.contracts.common import EvidenceRecord

        context = ActionContext.model_validate(context).model_copy(deep=True)
        with self.read_guard():
            self._check()
            digest = task_digest(context.model_dump(mode='json'))
            snapshot = self._snapshots.get(digest)
            if (snapshot is None or context.contract_ref.id != 'CONTRACTOR-A02'
                    or context.execution_mode == 'offline_fixture' or context.scope.kind != 'project'
                    or not isinstance(worker, ContractorScreeningResultWorker) or worker.store is not self.assembly.client.tasks
                    or not isinstance(basis, ContractorProcurementHandoffBasis)
                    or not isinstance(native_evidence, EvidenceRecord) or not isinstance(result_evidence, EvidenceRecord)):
                raise TaskConflict('Runtime handoff requires original formal A02 context, worker and typed private evidence')
            grants = self.organizations.grants(context, 'CONTRACTOR-A02', 'Contractor')
            permitted = {ref.key() for grant in grants for ref in grant.readable_refs}
            permitted &= {ref.key() for ref in context.visible_refs}
            original = worker.get_record(identity)
            original_snapshot = worker.snapshots.get(identity)
            native = self.assembly.read_invited_tender_project(organization_id=identity.organization_id,
                project_id=context.scope.ref.id, read_guard=nullcontext)
            if (not grants or grants[0].organization_id != identity.organization_id
                    or snapshot['projection']['organization_id'] != identity.organization_id
                    or identity.organization_id != request.agent.agent_id or basis.organization_id != identity.organization_id
                    or basis.run_id != context.run_id or identity.run_id != context.run_id or basis.scope != context.scope
                    or request.inputs['project']['project_id'] != context.scope.ref.id
                    or request.metadata.get('tick') != self.assembly.engine.current_tick
                    or original is None or original['result']['kind'] != 'completed'
                    or original['result']['payload']['choice'] != 'participate'
                    or original_snapshot['context']['execution_mode'] == 'offline_fixture'
                    or original['audit'].get('reading', {}).get('source_mode') != 'formal'
                    or original_snapshot['context']['business_time'] != context.business_time.model_dump(mode='json')
                    or self.assembly.client.tasks.get(identity)['state'] != 'output_formed'
                    or self.assembly.client.tasks.get(identity)['output'] != original['result']
                    or basis.screening_context_sha256 != identity.context_sha256
                    or basis.screening_input_sha256 != identity.input_sha256
                    or basis.screening_result_sha256 != original['result_sha256']
                    or basis.screening_audit_sha256 != task_digest(original['audit'])
                    or basis.procurement_source_sha256 != native.get('record_sha256')
                    or basis.procurement_source_evidence_ref != native_evidence.ref
                    or basis.screening_result_evidence_ref != result_evidence.ref
                    or native_evidence.ref == result_evidence.ref
                    or any(row.source_kind != 'synthetic' or row.basis_kind != 'observed'
                        or row.effective_window != basis.effective_window for row in (native_evidence, result_evidence))
                    or native_evidence.content_hash != basis.procurement_source_sha256
                    or native_evidence.locator != 'gba-invited-tender:' + basis.procurement_source_sha256
                    or result_evidence.content_hash != original['result_sha256']
                    or result_evidence.locator != 'micro-result:' + identity.key):
                raise TaskConflict('Runtime handoff cannot substitute current own invitation or actual completed A01 result')
            rows = [{'ref': value.ref.model_dump(mode='json'), 'value': value.model_dump(mode='json')}
                for value in (basis, native_evidence, result_evidence)]
            base_refs = {Reference.model_validate(item['ref']).key() for item in snapshot['projection']['objects']}
            if any(Reference.model_validate(item['ref']).key() not in permitted
                    or Reference.model_validate(item['ref']).key() in base_refs for item in rows):
                raise TaskConflict('Runtime handoff requires preauthorized new references, without replacing supplied versions')
            body = {'schema_version': 'contractor-tender-handoff-source.v1', 'run_id': context.run_id,
                'simulation_id': self.assembly.client.simulation_id, 'organization_id': identity.organization_id,
                'context_sha256': digest, 'base_snapshot_sha256': task_digest(snapshot),
                'source_file_sha256': self.settings.snapshot_sha256,
                'request_sha256': task_digest(request.model_dump(mode='json')), 'request_id': request.request_id,
                'screening_identity': identity.as_dict(), 'screening_record_sha256': original['record_sha256'],
                'objects': rows}
            body['record_sha256'] = task_digest(body)
            store = self.assembly.client.tasks
            with store._transaction():
                prior = self.handoff_source(context)
                if prior is not None:
                    if prior != body:
                        raise TaskConflict('Original runtime handoff source cannot be replaced')
                elif digest in self._served_contexts:
                    raise TaskConflict('Runtime handoff requires a new unread source token')
                else:
                    store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._handoff_key(context), canonical(body)))
            self._check()
            return deepcopy(body)

    def _feedback_key(self, context):
        return 'contractor_screening_feedback_source:' + task_digest([
            self.settings.snapshot_sha256, context.model_dump(mode='json')])

    def publish_screening_feedback(self, *, context, request, base_profile_ref, profile_ref,
            evidence_ref, decline_after_prior_submissions, project_only, decline_after_prior_evaluations=None,
            decline_after_prior_declines=None, decline_after_prior_final_accounts=None,
            decline_after_prior_payment_delays=None):
        """Derive a new private policy version from actual prior own outcomes.

        The base profile and all native facts stay unchanged. Both new refs
        must already be explicitly readable in the supplied action context.
        A later original A01 processor consumes the resulting policy normally.
        """
        from src.actions.contracts.contractor_objects import OpportunityScreeningProfileView

        context = ActionContext.model_validate(context).model_copy(deep=True)
        with self.read_guard():
            self._check()
            digest = task_digest(context.model_dump(mode='json'))
            snapshot = self._snapshots.get(digest)
            if (context.contract_ref.id != 'CONTRACTOR-A01' or context.execution_mode == 'offline_fixture'
                    or snapshot is None or profile_ref == base_profile_ref):
                raise TaskConflict('Feedback policy requires an explicit original A01 source and a distinct new policy version')
            organization_id = snapshot['projection']['organization_id']
            grants = self.organizations.grants(context, 'CONTRACTOR-A01', 'Contractor')
            permitted = {ref.key() for grant in grants for ref in grant.readable_refs}
            permitted &= {ref.key() for ref in context.visible_refs}
            if (request.agent.agent_id != organization_id or not grants or grants[0].organization_id != organization_id
                    or request.metadata.get('tick') != self.assembly.engine.current_tick
                    or any(ref.key() not in permitted for ref in (base_profile_ref, profile_ref, evidence_ref))):
                raise TaskConflict('Feedback policy requires original recipient authority for base and derived sources')
            originals = [item['value'] for item in snapshot['projection']['objects']
                if Reference.model_validate(item['ref']) == base_profile_ref]
            if len(originals) != 1:
                raise TaskConflict('Feedback policy lacks its exact independently supplied base profile')
            base = OpportunityScreeningProfileView.model_validate(originals[0])
            if base.organization_ref.id != organization_id:
                raise TaskConflict('Feedback policy changes original enterprise or project scope')
            memory = self.assembly.client.tender_feedback_context(request, project_only=project_only)
            if decline_after_prior_evaluations is not None:
                from integration.bindings.gba_v1_bid_evaluation import with_own_evaluation_history
                memory=with_own_evaluation_history(self.assembly,request=request,memory=memory,read_guard=self.read_guard)
            if decline_after_prior_final_accounts is not None:
                from integration.bindings.gba_v1_final_accounts import with_own_final_account_history
                memory = with_own_final_account_history(self.assembly, request=request, memory=memory,
                    read_guard=self.read_guard)
            if decline_after_prior_payment_delays is not None:
                from integration.bindings.gba_v1_progress_payments import with_own_progress_payment_history
                memory = with_own_progress_payment_history(self.assembly, request=request, memory=memory,
                    read_guard=self.read_guard)
            if (memory['project_id'] != context.scope.ref.id or not base.effective_window.contains(context.business_time)):
                raise TaskConflict('Feedback policy changes the original project or validity window')
            profile, evidence = derive_screening_feedback_profile(base, profile_ref=profile_ref,
                evidence_ref=evidence_ref, memory=memory, business_time=context.business_time,
                decline_after_prior_submissions=decline_after_prior_submissions,
                decline_after_prior_evaluations=decline_after_prior_evaluations,
                decline_after_prior_declines=decline_after_prior_declines,
                decline_after_prior_final_accounts=decline_after_prior_final_accounts,
                decline_after_prior_payment_delays=decline_after_prior_payment_delays)
            rows = [{'ref': value.ref.model_dump(mode='json'), 'value': value.model_dump(mode='json')}
                for value in (profile, evidence)]
            base_refs = {Reference.model_validate(item['ref']).key() for item in snapshot['projection']['objects']}
            if any(Reference.model_validate(item['ref']).key() in base_refs for item in rows):
                raise TaskConflict('Feedback policy cannot replace any original source object version')
            body = {'schema_version': 'contractor-screening-feedback-source.v1', 'run_id': context.run_id,
                'organization_id': organization_id, 'context_sha256': digest,
                'base_snapshot_sha256': task_digest(snapshot), 'source_file_sha256': self.settings.snapshot_sha256,
                'request_sha256': task_digest(request.model_dump(mode='json')), 'feedback_context': memory,
                'base_profile_ref': base_profile_ref.model_dump(mode='json'), 'base_profile_sha256': task_digest(originals[0]),
                'decline_after_prior_submissions': decline_after_prior_submissions,
                'profile_ref': profile_ref.model_dump(mode='json'), 'evidence_ref': evidence_ref.model_dump(mode='json'),
                'objects': rows}
            if decline_after_prior_evaluations is not None:
                body['decline_after_prior_evaluations']=decline_after_prior_evaluations
            if decline_after_prior_declines is not None:
                body['decline_after_prior_declines']=decline_after_prior_declines
            if decline_after_prior_final_accounts is not None:
                body['decline_after_prior_final_accounts'] = decline_after_prior_final_accounts
            if decline_after_prior_payment_delays is not None:
                body['decline_after_prior_payment_delays'] = decline_after_prior_payment_delays
            body['record_sha256'] = task_digest(body)
            store = self.assembly.client.tasks
            with store._transaction():
                prior = store._db.execute('SELECT value FROM metadata WHERE key=?', (self._feedback_key(context),)).fetchone()
                if prior is not None:
                    if json.loads(prior[0]) != body:
                        raise TaskConflict('Original screening feedback source cannot be replaced')
                elif digest in self._served_contexts:
                    raise TaskConflict('Feedback policy requires a new unread source token')
                else:
                    store._db.execute('INSERT INTO metadata VALUES (?,?)', (self._feedback_key(context), canonical(body)))
            self._check()
            return deepcopy(body)

    def _micro_key(self, context):
        return 'contractor_tender_micro_indicators:' + task_digest([
            self.settings.snapshot_sha256, context.model_dump(mode='json')])

    def publish_bid_indicators(self, *, contexts, request, identity, worker, mapping,
            result_evidence, input_evidence, input_sha256):
        """Publish three private micro artifacts after the actual A02 result.

        Only the bid mapping and its two evidence objects are accepted. The
        original source file, native facts, author grants and all formal object
        kinds remain immutable. This does not submit or execute a native bid.
        """
        from integration.bindings.gba_v1_tender_proposal import GbaTenderProposalMappingView
        from integration.contractor_bid_results import ContractorBidResultWorker
        from src.actions.contracts.common import EvidenceRecord

        with self.read_guard():
            self._check()
            store = self.assembly.client.tasks
            contexts = list(contexts)
            if not contexts or len({task_digest(context.model_dump(mode='json')) for context in contexts}) != len(contexts):
                raise TaskConflict('Runtime indicators require distinct explicit source contexts')
            if (not isinstance(worker, ContractorBidResultWorker) or worker.ACTION_ID != 'CONTRACTOR-A02'
                    or worker.store is not store or not isinstance(mapping, GbaTenderProposalMappingView)
                    or not isinstance(result_evidence, EvidenceRecord) or not isinstance(input_evidence, EvidenceRecord)
                    or mapping.result_evidence_ref != result_evidence.ref
                    or input_evidence.ref not in mapping.evidence_refs
                    or result_evidence.ref == input_evidence.ref
                    or input_evidence.content_hash != input_sha256):
                raise TaskConflict('Runtime indicators require the original worker, typed mapping and distinct input/result evidence')
            original = worker.get_record(identity)
            if (original is None or original['result']['kind'] != 'completed'
                    or store.get(identity)['state'] != 'output_formed'
                    or store.get(identity)['output'] != original['result']
                    or mapping.run_id != store.run_id or mapping.simulation_id != self.assembly.client.simulation_id
                    or mapping.organization_id != identity.organization_id or identity.organization_id != request.agent.agent_id
                    or mapping.project_id != request.inputs['project']['project_id']
                    or mapping.request_sha256 != task_digest(request.model_dump(mode='json'))
                    or mapping.context_sha256 != identity.context_sha256 or mapping.input_sha256 != identity.input_sha256
                    or mapping.result_sha256 != original['result_sha256']
                    or result_evidence.content_hash != original['result_sha256'] or result_evidence.basis_kind != 'observed'):
                raise TaskConflict('Runtime indicators cannot precede or replace the actual saved completed A02 result')
            rows = [{'ref': value.ref.model_dump(mode='json'), 'value': value.model_dump(mode='json')}
                for value in (mapping, result_evidence, input_evidence)]
            records = []
            for context in contexts:
                context = ActionContext.model_validate(context).model_copy(deep=True)
                digest = task_digest(context.model_dump(mode='json'))
                snapshot = self._snapshots.get(digest)
                if (context.contract_ref.id != 'CONTRACTOR-A02' or context.execution_mode == 'offline_fixture'
                        or snapshot is None or snapshot['projection']['organization_id'] != identity.organization_id
                        or context.scope != mapping.scope or context.business_time.clock_ref != mapping.authored_at.clock_ref
                        or context.business_time.offset < mapping.available_at.offset):
                    raise TaskConflict('Runtime indicators require an explicit original same-project authorized source snapshot')
                grants = self.organizations.grants(context, 'CONTRACTOR-A02', 'Contractor')
                permitted = {ref.key() for grant in grants for ref in grant.readable_refs}
                permitted &= {ref.key() for ref in context.visible_refs}
                base = {Reference.model_validate(item['ref']).key(): item for item in snapshot['projection']['objects']}
                if any(Reference.model_validate(item['ref']).key() not in permitted
                        or Reference.model_validate(item['ref']).key() in base
                        and base[Reference.model_validate(item['ref']).key()] != item for item in rows):
                    raise TaskConflict('Runtime indicator publication replaces a base source or exceeds original authority')
                body = {'schema_version': 'contractor-tender-micro-indicators.v1', 'run_id': context.run_id,
                    'organization_id': identity.organization_id, 'context_sha256': digest,
                    'base_snapshot_sha256': task_digest(snapshot), 'source_file_sha256': self.settings.snapshot_sha256,
                    'identity': identity.as_dict(), 'result_record_sha256': original['record_sha256'],
                    'input_sha256': input_sha256, 'objects': deepcopy(rows)}
                body['record_sha256'] = task_digest(body)
                records.append((self._micro_key(context), body, digest))
            with store._transaction():
                for key, body, digest in records:
                    prior = store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
                    if prior is not None:
                        if json.loads(prior[0]) != body:
                            raise TaskConflict('Runtime indicators cannot replace an original authored mapping')
                    elif digest in self._served_contexts:
                        raise TaskConflict('Runtime indicators require a new unread source token')
                    else:
                        store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(body)))
            self._check()


def build_snapshot_reader(*, assembly, organizations, read_guard, settings):
    """Concrete factory for the original tender source bundle's provider dependency.

    Construction reads the explicitly configured source file, performs no native
    read, starts no model and owns no journal or engine resource. The application's
    existing shared writer guard and original authorization registry are required.
    """
    return ContractorTenderSnapshotReader(assembly=assembly, organizations=organizations,
        read_guard=read_guard, settings=settings)
