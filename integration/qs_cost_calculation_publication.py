"""Persist original QS arithmetic executions and expose them at fresh read points."""
from copy import deepcopy
import json

from pydantic import BaseModel

from integration.qs_cost_actions import validate_qs_cost_sources
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.qs_cost_objects import QSCostCalculationView, qs_cost_schemas
from src.actions.contracts.references import ActionReadView
from src.actions.registry import ActionRegistry
from src.coordination.tasks import TaskConflict, TaskStore, canonical, task_digest
from src.methods.models import MethodOk
from src.methods.qs_cost import COST_METHOD, CostArithmeticInput, CostArithmeticReport
from src.methods.registry import MethodRegistry, digest
from src.organization.registry import OrganizationRegistry


def _plain(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


class QSCostCalculationPublicationStore:
    """Technical evidence only; validation never repeats a method execution.

    validate_source(record, current_context) must return True after independently
    checking the actual original source/author versions. The caller holds its
    real source writer guard throughout save/publish/provider reads.
    """
    SCHEMA = 'qs-cost-calculation-record.v1'
    PUBLICATION_SCHEMA = 'qs-cost-calculation-publication.v1'
    ACTION_ID = 'QS-A04'
    ROLE = 'QS'
    METHOD_REF = COST_METHOD
    RECORDS_TABLE = 'qs_cost_calculation_records'
    PUBLICATIONS_TABLE = 'qs_cost_calculation_publications'
    SOURCE_SCHEMAS = staticmethod(qs_cost_schemas)

    def __init__(self, *, store, registry, methods, organizations, validate_source):
        if (not isinstance(store, TaskStore) or not isinstance(registry, ActionRegistry)
                or not isinstance(methods, MethodRegistry) or not isinstance(organizations, OrganizationRegistry)
                or organizations.run_id != store.run_id or not callable(validate_source)):
            raise ValueError('Cost persistence requires original same-run journal/registries and actual source validation')
        self.store, self.registry, self.methods = store, registry, methods
        self.organizations, self.validate_source = organizations, validate_source
        self.schemas = self.SOURCE_SCHEMAS()
        with store._transaction():
            store._db.execute(f'CREATE TABLE IF NOT EXISTS {self.RECORDS_TABLE} '
                '(record_sha256 TEXT PRIMARY KEY, ref_key TEXT UNIQUE NOT NULL, record TEXT NOT NULL)')
            store._db.execute(f'CREATE TABLE IF NOT EXISTS {self.PUBLICATIONS_TABLE} '
                '(boundary_key TEXT PRIMARY KEY, record TEXT NOT NULL)')

    def _grants(self, context):
        if (context.run_id != self.store.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID):
            raise TaskConflict('QS calculation evidence requires its original run and action context')
        grants = self.organizations.grants(context, self.ACTION_ID, self.ROLE)
        if grants[0].organization_id not in self.store.organization_ids:
            raise TaskConflict('Cost evidence recipient is outside its original journal')
        return grants

    def _binding(self):
        registration = self.registry.get(self.ACTION_ID)
        if (not registration.implemented or registration.role != self.ROLE or registration.skill is None
                or self.METHOD_REF not in registration.skill.manifest.method_refs):
            raise TaskConflict('Cost persistence requires its original implemented action and declared method')
        return {'processor_id': registration.processor_id, 'skill_sha256': registration.skill.manifest.skill_sha256,
            'contract_source_sha256': registration.contract.source_sha256, 'method_registry_sha256': self.methods.content_digest}

    def _validate_method_execution(self, *, context, arithmetic, execution, originals, result):
        """Check retained registry proof without invoking the registered executor."""
        sources = [{'ref': ref.model_dump(mode='json'), 'value': originals[ref.key()]} for ref in arithmetic.source_refs]
        binding = self.methods._bindings.get(self.METHOD_REF.key())
        if binding is None or execution['method_ref'] != self.METHOD_REF.model_dump(mode='json'):
            raise TaskConflict('Saved QS calculation lacks its exact original method binding')
        proof = {'run_id': context.run_id, 'actor_id': context.actor_id, 'action_id': self.ACTION_ID,
            'operation_id': context.operation_id, 'read_token': context.read_token,
            'function_ref': context.function_ref.model_dump(mode='json'),
            'authorization_refs': [ref.model_dump(mode='json') for ref in context.authorization_refs],
            'contract_ref': context.contract_ref.model_dump(mode='json'), 'task_ref': context.task_ref.model_dump(mode='json'),
            'scope': context.scope.model_dump(mode='json'), 'business_time': context.business_time.model_dump(mode='json'),
            'registry_digest': self.methods.content_digest, 'method_digest': binding.content_digest,
            'input': arithmetic.model_dump(mode='json'), 'source_projections': sources}
        basis = {ref.key(): ref for ref in walk_references(arithmetic) if ref.kind == 'Evidence'}
        if (result.method_ref != self.METHOD_REF or result.input_digest != digest(proof)
                or execution['registry_digest'] != self.methods.content_digest
                or [item.model_dump(mode='json') for item in result.input_refs] != [
                    {'data_space': {'kind': 'run', 'id': context.run_id}, 'ref': ref.model_dump(mode='json')}
                    for ref in arithmetic.source_refs] or result.basis_refs != list(basis.values())):
            raise TaskConflict('QS calculation lost original input/source/method provenance')

    def _publication_refs(self, record, projection):
        return [projection.ref, *walk_references(projection)]

    def _result_projections(self, projection):
        return [projection]

    def _execution_ref(self, projection):
        return projection.ref.model_dump(mode='json')

    def _publication_content(self, projection):
        return {'object': {'ref': projection.ref.model_dump(mode='json'), 'value': projection.model_dump(mode='json')}}

    def _published_objects(self, publication):
        return [publication['object']]

    def _save_targets(self, record, projection, *, is_new):
        """Multi-result stores reserve every target in the save transaction."""

    def _validate_saved_targets(self, record, projection):
        """Multi-result stores require the complete retained target index."""

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id', 'context',
                'action_input', 'prepared', 'binding', 'record_sha256'} or record['schema_version'] != self.SCHEMA
                or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
                or record['binding'] != self._binding()):
            raise TaskConflict('Saved cost execution changes its schema, binding or original digest')
        context = ActionContext.model_validate(record['context'])
        if (context.run_id != self.store.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != 'QS-A04' or record['organization_id'] not in self.store.organization_ids):
            raise TaskConflict('Saved cost execution belongs to another original invocation')
        action_input = self.registry.get('QS-A04').contract.validate_input(record['action_input'])
        prepared = record['prepared']
        expected = {'kind', 'projection', 'projection_sha256', 'context_sha256', 'input_sha256', 'source_mode',
            'source_reading', 'reading_sha256', 'method_execution', 'method_registry_sha256', 'limitations'}
        if (not isinstance(prepared, dict) or set(prepared) != expected or prepared['kind'] != 'prepared'
                or action_input.method_result_refs or prepared['input_sha256'] != task_digest(record['action_input'])
                or prepared['context_sha256'] != task_digest(record['context'])
                or prepared['reading_sha256'] != task_digest(prepared['source_reading'])
                or prepared['method_registry_sha256'] != self.methods.content_digest
                or prepared['source_mode'] != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Saved cost execution changes original input, reading or method registry')
        projection = QSCostCalculationView.model_validate(prepared['projection'])
        execution = prepared['method_execution']
        arithmetic = CostArithmeticInput.model_validate(execution['input'])
        result = MethodOk[CostArithmeticReport].model_validate(execution['result'])
        originals, typed_sources = {}, {}
        for item in prepared['source_reading']:
            if not isinstance(item, dict) or set(item) != {'ref', 'projection'}:
                raise TaskConflict('Cost execution source cache requires exact ref/projection records')
            ref = Reference.model_validate(item['ref'])
            if ref.key() in originals:
                raise TaskConflict('Cost execution repeats an original source reference')
            typed_sources[ref.key()] = self.schemas.validate_projection(ref, item['projection'])
            originals[ref.key()] = typed_sources[ref.key()].model_dump(mode='json')
        validate_qs_cost_sources(action_input, context=context, organization_id=record['organization_id'], sources=typed_sources)
        self._validate_method_execution(context=context, arithmetic=arithmetic,
            execution=execution, originals=originals, result=result)
        report = result.value
        if (projection.method_ref != COST_METHOD or projection.status != 'ok' or type(projection.ref.version) is not str
                or projection.scope != context.scope or projection.calculated_at != context.business_time
                or projection.available_at != context.business_time or not projection.effective_window.contains(context.business_time)
                or projection.author_actor_id != context.actor_id or projection.author_function_ref != context.function_ref
                or projection.author_authority_ref not in context.authorization_refs
                or task_digest(projection.model_dump(mode='json')) != prepared['projection_sha256']
                or any(getattr(projection, name) != getattr(action_input, name) for name in
                    ('task_ref', 'brief_ref', 'option_ref', 'cost_scope_ref', 'comparison_basis_ref', 'quantity_basis_refs', 'price_refs'))
                or [line.model_dump(mode='json') for line in projection.lines] != [
                    line.model_dump(mode='json', exclude={'issues'}) for line in report.lines]
                or projection.known_subtotal != report.known_subtotal or projection.complete_total != report.complete_total):
            raise TaskConflict('Saved cost projection substitutes its original method output, author or input versions')
        return context, projection

    def save(self, prepared, *, context, action_input, reading):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        grants = self._grants(context)
        if (not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations
                or reading._methods is not self.methods or reading.organization_id != grants[0].organization_id):
            raise TaskConflict('Cost save changes its original reading, method registry or current QS authority')
        reading.check_method_context(context, self.ACTION_ID)
        prepared = _plain(deepcopy(prepared))
        if (prepared['method_execution'] not in reading.method_evidence()
                or prepared['source_reading'] != reading.evidence()):
            raise TaskConflict('Cost save requires its actual original reading and recorded method execution')
        record = {'schema_version': self.SCHEMA, 'organization_id': reading.organization_id,
            'context': context.model_dump(mode='json'), 'action_input': action_input.model_dump(mode='json'),
            'prepared': prepared, 'binding': self._binding()}
        record['record_sha256'] = task_digest(record)
        _, projection = self._validate(record)
        permitted = {ref.key() for grant in grants for ref in grant.readable_refs} & {ref.key() for ref in context.visible_refs}
        if any(row.ref.key() not in permitted for row in self._result_projections(projection)):
            raise TaskConflict('Cost execution target lacks its original save-time read permission')
        if self.validate_source(deepcopy(record), context.model_copy(deep=True)) is not True:
            raise TaskConflict('Actual cost execution/source provenance requires independent validation before save')
        reading.recheck()
        self._validate(record)
        ref_key = task_digest([self.store.run_id, self.ACTION_ID, self._execution_ref(projection)])
        with self.store._transaction():
            if self._grants(context) != grants:
                raise TaskConflict('Cost save authority changed during validation')
            prior = self.store._db.execute(f'SELECT record FROM {self.RECORDS_TABLE} WHERE ref_key=?', (ref_key,)).fetchone()
            if prior is not None and json.loads(prior[0]) != record:
                raise TaskConflict('An original calculation reference cannot replace its saved execution')
            self._save_targets(record, projection, is_new=prior is None)
            if prior is None:
                self.store._db.execute(f'INSERT INTO {self.RECORDS_TABLE} VALUES (?,?,?)',
                    (record['record_sha256'], ref_key, canonical(record)))
        return deepcopy(record)

    def publish(self, record_sha256, *, source_context, next_context):
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        context = ActionContext.model_validate(next_context).model_copy(deep=True)
        source_grants, grants = self._grants(source), self._grants(context)
        if (source.read_token == context.read_token or source_grants[0].organization_id != grants[0].organization_id
                or any(getattr(source, name) != getattr(context, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('Cost publication requires the original same-time identity and a fresh authorized token')
        with self.store._lock:
            raw = self.store._db.execute(f'SELECT record FROM {self.RECORDS_TABLE} WHERE record_sha256=?',
                (record_sha256,)).fetchone()
        if raw is None:
            raise TaskConflict('Cost publication requires its already persisted original execution')
        record = json.loads(raw[0])
        original, projection = self._validate(record)
        self._validate_saved_targets(record, projection)
        permitted = {ref.key() for grant in grants for ref in grant.readable_refs} & {ref.key() for ref in context.visible_refs}
        if (original != source or record['organization_id'] != grants[0].organization_id
                or any(ref.key() not in permitted for ref in self._publication_refs(record, projection) if ref != self.METHOD_REF)):
            raise TaskConflict('Cost publication substitutes its original execution or target read permission')
        if self.validate_source(deepcopy(record), context.model_copy(deep=True)) is not True:
            raise TaskConflict('Published calculation requires independent current original source validation')
        self._validate(record)
        publication = {'schema_version': self.PUBLICATION_SCHEMA, 'context': context.model_dump(mode='json'),
            'organization_id': record['organization_id'], 'execution_sha256': record_sha256,
            **self._publication_content(projection)}
        publication['record_sha256'] = task_digest(publication)
        key = task_digest([context.run_id, record['organization_id'], context.read_token])
        with self.store._transaction():
            if self._grants(source) != source_grants or self._grants(context) != grants:
                raise TaskConflict('Original publication authority changed during validation')
            self._validate_saved_targets(record, projection)
            if self.store._db.execute(f'SELECT record FROM {self.RECORDS_TABLE} WHERE record_sha256=?',
                    (record_sha256,)).fetchone() != raw:
                raise TaskConflict('Original calculation execution changed before publication')
            prior = self.store._db.execute(f'SELECT record FROM {self.PUBLICATIONS_TABLE} WHERE boundary_key=?', (key,)).fetchone()
            if prior is not None and json.loads(prior[0]) != publication:
                raise TaskConflict('Cost publication cannot replace an original read point')
            if prior is None:
                self.store._db.execute(f'INSERT INTO {self.PUBLICATIONS_TABLE} VALUES (?,?)', (key, canonical(publication)))
        return deepcopy(publication)

    def read(self, context, *, organization_id, grants):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        current = self._grants(context)
        if current != grants or organization_id != current[0].organization_id:
            raise TaskConflict('Cost publication read changes its original current authority')
        key = task_digest([context.run_id, organization_id, context.read_token])
        with self.store._lock:
            raw = self.store._db.execute(f'SELECT record FROM {self.PUBLICATIONS_TABLE} WHERE boundary_key=?', (key,)).fetchone()
            if raw is None:
                return None
            publication = json.loads(raw[0])
            saved = self.store._db.execute(f'SELECT record FROM {self.RECORDS_TABLE} WHERE record_sha256=?',
                (publication['execution_sha256'],)).fetchone()
        if (saved is None or publication['schema_version'] != self.PUBLICATION_SCHEMA
                or publication['context'] != context.model_dump(mode='json') or publication['organization_id'] != organization_id
                or publication['record_sha256'] != task_digest({k: v for k, v in publication.items() if k != 'record_sha256'})):
            raise TaskConflict('Cost publication lost its original execution, identity or digest')
        record = json.loads(saved[0])
        _, projection = self._validate(record)
        self._validate_saved_targets(record, projection)
        permitted = {ref.key() for grant in current for ref in grant.readable_refs} & {ref.key() for ref in context.visible_refs}
        if (record['organization_id'] != organization_id
                or any(publication.get(key) != value for key, value in self._publication_content(projection).items())
                or any(ref.key() not in permitted for ref in self._publication_refs(record, projection) if ref != self.METHOD_REF)):
            raise TaskConflict('Published calculation differs from its original execution or current permission')
        if self.validate_source(deepcopy(record), context.model_copy(deep=True)) is not True or self._grants(context) != current:
            raise TaskConflict('Current original cost source validation did not succeed')
        self._validate(record)
        self._validate_saved_targets(record, projection)
        return deepcopy(publication)


class QSCostCalculationPublishedViewProvider:
    def __init__(self, *, provider, publications):
        if not callable(getattr(provider, 'project', None)) or not isinstance(publications, QSCostCalculationPublicationStore):
            raise ValueError('Original source provider and cost publication store required')
        self.provider, self.publications = provider, publications

    def project(self, *, context, organization_id, grants):
        raw = deepcopy(self.provider.project(context=context.model_copy(deep=True),
            organization_id=organization_id, grants=deepcopy(grants)))
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.publications.ACTION_ID:
            return raw
        publication = self.publications.read(context, organization_id=organization_id, grants=grants)
        if publication is None:
            return raw
        required = {'run_id', 'macro_version', 'state_version', 'read_token', 'business_time', 'organization_id', 'objects'}
        if (not isinstance(raw, dict) or set(raw) != required or raw['run_id'] != context.run_id
                or raw['read_token'] != context.read_token or raw['business_time'] != context.business_time.model_dump()
                or raw['organization_id'] != organization_id or not isinstance(raw['objects'], list)):
            raise TaskConflict('Cost source provider changes its original published reading envelope')
        objects = {}
        for published, group in ((False, raw['objects']), (True, self.publications._published_objects(publication))):
            for item in group:
                ref = Reference.model_validate(item['ref'])
                if ref.key() in objects and objects[ref.key()] != item:
                    raise TaskConflict('Cost publication conflicts with an original immutable source version')
                if ref.key() in objects and not published:
                    raise TaskConflict('Cost source provider repeats an original reference')
                objects[ref.key()] = item
        raw['objects'] = list(objects.values())
        raw['state_version'] = task_digest({'source_state_version': raw['state_version'], 'publication_sha256': publication['record_sha256']})
        return raw
