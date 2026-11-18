"""Durable original A05 area reports, published only at a fresh authorized token."""
from copy import deepcopy
import json

from integration.architect_design_actions import validate_architect_area_preparation_sources
from integration.qs_cost_calculation_publication import (
    QSCostCalculationPublicationStore, QSCostCalculationPublishedViewProvider,
)
from src.actions.contracts.architect_design_objects import (
    ArchitectDesignAreaPreparation, ArchitectDesignAreaResultView, architect_design_schemas,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.architect_design import prepare_architect_area_input
from src.coordination.tasks import TaskConflict, canonical, task_digest
from src.methods.architect_area import AREA_METHOD, ArchitectAreaInput, ArchitectAreaReport, calculate_area_schedule
from src.methods.models import MethodOk
from src.organization.models import Authorization


class ArchitectAreaCalculationPublicationStore(QSCostCalculationPublicationStore):
    """Reuse immutable journal transactions and proof verification without replay.

    The caller holds its actual source guard. Independent validate_source checks
    the original actual sources on every save, publication and provider read.
    """
    SCHEMA = 'architect-area-calculation-record.v1'
    PUBLICATION_SCHEMA = 'architect-area-calculation-publication.v1'
    BATCH_PUBLICATION_SCHEMA = 'architect-area-calculation-batch-publication.v1'
    ACTION_ID = 'ARCHITECT-A05'
    ROLE = 'Architect'
    METHOD_REF = AREA_METHOD
    RECORDS_TABLE = 'architect_area_calculation_records'
    PUBLICATIONS_TABLE = 'architect_area_calculation_publications'
    SOURCE_SCHEMAS = staticmethod(architect_design_schemas)

    def __init__(self, **components):
        if getattr(components.get('store'), 'path', None) is None:
            raise ValueError('Area persistence requires its original durable journal')
        super().__init__(**components)

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id', 'context',
                'action_input', 'prepared', 'binding', 'record_sha256'}
                or record['schema_version'] != self.SCHEMA or record['binding'] != self._binding()
                or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})):
            raise TaskConflict('Saved area calculation changes its original schema, binding or digest')
        context = ActionContext.model_validate(record['context'])
        grants = self._grants(context)
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        saved = record['prepared']
        fields = {'kind', 'projection', 'projection_sha256', 'context_sha256', 'input_sha256',
            'preparation', 'preparation_sha256', 'area_input_sha256', 'source_mode', 'source_reading',
            'reading_sha256', 'author_authority_ref', 'method_execution', 'method_registry_sha256', 'limitations'}
        if (not isinstance(saved, dict) or set(saved) != fields or saved['kind'] != 'prepared'
                or record['organization_id'] != grants[0].organization_id or action_input.scope != context.scope
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['preparation_sha256'] != task_digest(saved['preparation'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['method_registry_sha256'] != self.methods.content_digest
                or saved['source_mode'] != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Saved area calculation substitutes its original input, reading or registry')
        preparation = ArchitectDesignAreaPreparation.model_validate(saved['preparation'])
        projection = ArchitectDesignAreaResultView.model_validate(saved['projection'])
        execution = saved['method_execution']
        if not isinstance(execution, dict) or set(execution) != {'method_ref', 'registry_digest', 'input', 'result'}:
            raise TaskConflict('Saved area calculation lacks its original complete method execution')
        data = ArchitectAreaInput.model_validate(execution['input'])
        result = MethodOk[ArchitectAreaReport].model_validate(execution['result'])
        resolver = ReferenceResolver(context.run_id, source_mode=saved['source_mode'], schemas=self.schemas)
        sources, originals, refs = {}, {}, []
        if not isinstance(saved['source_reading'], list):
            raise TaskConflict('Area calculation requires its exact original source cache records')
        for row in saved['source_reading']:
            if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                raise TaskConflict('Area calculation source cache changes its closed record schema')
            ref = Reference.model_validate(row['ref'])
            if ref.key() in sources:
                raise TaskConflict('Area calculation repeats an original immutable source version')
            sources[ref.key()] = self.schemas.validate_projection(ref, row['projection'])
            originals[ref.key()] = sources[ref.key()].model_dump(mode='json')
            resolver.register_projection(ref, sources[ref.key()])
            refs.append(ref)
        validate_architect_area_preparation_sources(action_input, preparation=preparation,
            context=context, organization_id=record['organization_id'], sources=sources)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, self.ROLE)
        for ref in refs:
            reading.resolve(ref)
        original = prepare_architect_area_input(context, action_input, reading, preparation)
        if (original['kind'] != 'prepared' or original['preparation'] != preparation
                or reading.method_evidence() or reading.evidence() != saved['source_reading']
                or preparation.input != data or saved['area_input_sha256'] != task_digest(data.model_dump(mode='json'))):
            raise TaskConflict('Saved area calculation replaces its original authorized draft or mapped input')
        self._validate_method_execution(context=context, arithmetic=data, execution=execution, originals=originals, result=result)
        grant = sources.get(projection.author_authority_ref.key())
        if (projection.model_dump(mode='json') != saved['projection'] or projection.ref != preparation.calculation_ref
                or type(projection.ref.version) is not str or projection.task_ref != original['task'].ref
                or projection.design_profile_ref != original['profile'].ref or projection.draft_index != preparation.draft_index
                or projection.area_variable_refs != preparation.area_variable_refs
                or projection.floor_count_variable_refs != preparation.floor_count_variable_refs
                or projection.input != data or projection.report != result.value or result.value != calculate_area_schedule(data)
                or projection.method_ref != AREA_METHOD or projection.status != 'ok' or projection.scope != context.scope
                or projection.executed_at != context.business_time or projection.available_at != context.business_time
                or projection.effective_window.model_dump(mode='json') != {'start': context.business_time.model_dump(mode='json'),
                    'end': context.business_time.model_dump(mode='json'), 'bounds': 'closed_closed'}
                or projection.author_actor_id != context.actor_id or projection.author_function_ref != context.function_ref
                or projection.author_authority_ref.model_dump(mode='json') != saved['author_authority_ref']
                or projection.author_authority_ref not in context.authorization_refs
                or projection.evidence_refs != [ref for ref in refs if ref.kind == 'Evidence']
                or task_digest(saved['projection']) != saved['projection_sha256']
                or not isinstance(grant, Authorization) or grant not in grants
                or projection.ref not in context.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Saved area report changes its original result, draft, author or target authority')
        for ref in grant.basis_refs:
            evidence = sources.get(ref.key())
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
                raise TaskConflict('Saved area author lacks current original evidence')
        if saved['source_mode'] == 'formal' and any(isinstance(row, EvidenceRecord)
                and row.source_kind == 'synthetic' for row in sources.values()):
            raise TaskConflict('Formal area calculation cannot retain synthetic source evidence')
        reading.recheck()
        return context, projection

    def _publication_refs(self, record, projection):
        return list({ref.key(): ref for ref in [projection.ref, *walk_references(projection),
            *(Reference.model_validate(row['ref']) for row in record['prepared']['source_reading'])]}.values())

    def publish_many(self, record_sha256s, *, source_context, next_context):
        """Publish separately saved drafts together at one immutable read point."""
        if not isinstance(record_sha256s, (list, tuple)) or not record_sha256s or len(set(record_sha256s)) != len(record_sha256s):
            raise TaskConflict('Area publication requires a nonempty unique list of saved executions')
        if len(record_sha256s) == 1:
            return self.publish(record_sha256s[0], source_context=source_context, next_context=next_context)
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        context = ActionContext.model_validate(next_context).model_copy(deep=True)
        source_grants, grants = self._grants(source), self._grants(context)
        if (source.read_token == context.read_token or source_grants[0].organization_id != grants[0].organization_id
                or any(getattr(source, name) != getattr(context, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('Area publication requires original same-time identity and a fresh authorized token')
        permitted = {ref.key() for grant in grants for ref in grant.readable_refs} & {ref.key() for ref in context.visible_refs}
        records, objects, targets, original_input = [], [], set(), None
        for record_sha in sorted(record_sha256s):
            with self.store._lock:
                raw = self.store._db.execute(f'SELECT record FROM {self.RECORDS_TABLE} WHERE record_sha256=?', (record_sha,)).fetchone()
            if raw is None:
                raise TaskConflict('Area publication requires already persisted original executions')
            record = json.loads(raw[0])
            original, projection = self._validate(record)
            if original_input is None:
                original_input = record['action_input']
            if (original != source or record['action_input'] != original_input or projection.ref.key() in targets
                    or any(ref.key() not in permitted for ref in self._publication_refs(record, projection) if ref != self.METHOD_REF)
                    or self.validate_source(deepcopy(record), context.model_copy(deep=True)) is not True):
                raise TaskConflict('Area publication substitutes original execution, unique target or current source authority')
            self._validate(record)
            records.append((record_sha, raw))
            targets.add(projection.ref.key())
            objects.append(self._publication_content(projection)['object'])
        publication = {'schema_version': self.BATCH_PUBLICATION_SCHEMA, 'context': context.model_dump(mode='json'),
            'organization_id': grants[0].organization_id, 'execution_sha256s': [row[0] for row in records], 'objects': objects}
        publication['record_sha256'] = task_digest(publication)
        key = task_digest([context.run_id, grants[0].organization_id, context.read_token])
        with self.store._transaction():
            if self._grants(source) != source_grants or self._grants(context) != grants:
                raise TaskConflict('Area publication authority changed during validation')
            for record_sha, raw in records:
                if self.store._db.execute(f'SELECT record FROM {self.RECORDS_TABLE} WHERE record_sha256=?', (record_sha,)).fetchone() != raw:
                    raise TaskConflict('Original area execution changed before publication')
            prior = self.store._db.execute(f'SELECT record FROM {self.PUBLICATIONS_TABLE} WHERE boundary_key=?', (key,)).fetchone()
            if prior is not None and json.loads(prior[0]) != publication:
                raise TaskConflict('Area publication cannot replace an original read point')
            if prior is None:
                self.store._db.execute(f'INSERT INTO {self.PUBLICATIONS_TABLE} VALUES (?,?)', (key, canonical(publication)))
        return deepcopy(publication)

    def read(self, context, *, organization_id, grants):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        current = self._grants(context)
        if current != grants or organization_id != current[0].organization_id:
            raise TaskConflict('Area publication read changes its current authority')
        key = task_digest([context.run_id, organization_id, context.read_token])
        with self.store._lock:
            raw = self.store._db.execute(f'SELECT record FROM {self.PUBLICATIONS_TABLE} WHERE boundary_key=?', (key,)).fetchone()
        if raw is None:
            return None
        publication = json.loads(raw[0])
        if publication.get('schema_version') != self.BATCH_PUBLICATION_SCHEMA:
            return super().read(context, organization_id=organization_id, grants=grants)
        if (set(publication) != {'schema_version', 'context', 'organization_id', 'execution_sha256s', 'objects', 'record_sha256'}
                or publication['context'] != context.model_dump(mode='json') or publication['organization_id'] != organization_id
                or publication['record_sha256'] != task_digest({k: v for k, v in publication.items() if k != 'record_sha256'})
                or not isinstance(publication['execution_sha256s'], list) or len(publication['execution_sha256s']) < 2
                or publication['execution_sha256s'] != sorted(set(publication['execution_sha256s']))):
            raise TaskConflict('Area publication lost its original closed schema, identity or digest')
        permitted = {ref.key() for grant in current for ref in grant.readable_refs} & {ref.key() for ref in context.visible_refs}
        objects, targets, source_context, original_input = [], set(), None, None
        for record_sha in publication['execution_sha256s']:
            with self.store._lock:
                saved = self.store._db.execute(f'SELECT record FROM {self.RECORDS_TABLE} WHERE record_sha256=?', (record_sha,)).fetchone()
            if saved is None:
                raise TaskConflict('Area publication lacks its retained original execution')
            record = json.loads(saved[0])
            original, projection = self._validate(record)
            if source_context is None:
                source_context = original
                original_input = record['action_input']
            if (original != source_context or record['action_input'] != original_input
                    or record['organization_id'] != organization_id or projection.ref.key() in targets
                    or original.read_token == context.read_token
                    or any(getattr(original, name) != getattr(context, name) for name in
                        ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                    or any(ref.key() not in permitted for ref in self._publication_refs(record, projection) if ref != self.METHOD_REF)
                    or self.validate_source(deepcopy(record), context.model_copy(deep=True)) is not True):
                raise TaskConflict('Published area report differs from its original source or current permission')
            self._validate(record)
            targets.add(projection.ref.key())
            objects.append(self._publication_content(projection)['object'])
        if publication['objects'] != objects or self._grants(context) != current:
            raise TaskConflict('Published area report set or current authority changed')
        return deepcopy(publication)

    def _published_objects(self, publication):
        if publication['schema_version'] == self.BATCH_PUBLICATION_SCHEMA:
            return publication['objects']
        return super()._published_objects(publication)


class ArchitectAreaCalculationPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, ArchitectAreaCalculationPublicationStore):
            raise ValueError('Area publication requires its original Architect area store')
        super().__init__(provider=provider, publications=publications)
