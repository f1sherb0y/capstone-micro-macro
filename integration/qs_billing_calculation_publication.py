"""Retain original QS-A10 fee calculations for explicit fresh-token reading."""
from copy import deepcopy
import json

from integration.module_host import module_factory_descriptor
from integration.qs_billing_actions import validate_qs_billing_sources
from integration.qs_cost_calculation_publication import (
    QSCostCalculationPublicationStore, QSCostCalculationPublishedViewProvider, _plain,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.qs_billing_objects import QSBillingCalculationView, qs_billing_schemas, qs_billing_types
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.registry import ActionRegistry
from src.actions.roles.service_billing import prepare_service_fee_calculation
from src.coordination.tasks import TaskConflict, TaskStore, canonical, task_digest
from src.organization.models import Authorization
from src.organization.registry import OrganizationRegistry


class QSBillingCalculationPublicationStore(QSCostCalculationPublicationStore):
    """Reuse immutable publication transactions for the declared billing formula.

    No method-registry execution is claimed. Validation checks the retained
    formula and its exact inputs using the existing billing arithmetic. The
    independent validate_source gate must check actual originals under the
    caller's source/authorization writer guard. No fee claim or cash is posted.
    """
    SCHEMA = 'qs-billing-calculation-record.v1'
    PUBLICATION_SCHEMA = 'qs-billing-calculation-publication.v1'
    ACTION_ID = 'QS-A10'
    METHOD_REF = None
    RECORDS_TABLE = 'qs_billing_calculation_records'
    PUBLICATIONS_TABLE = 'qs_billing_calculation_publications'
    SOURCE_SCHEMAS = staticmethod(qs_billing_schemas)

    def __init__(self, *, store, registry, organizations, validate_source):
        if (not isinstance(store, TaskStore) or store.path is None or not isinstance(registry, ActionRegistry)
                or not isinstance(organizations, OrganizationRegistry)
                or organizations.run_id != store.run_id or not callable(validate_source)):
            raise ValueError('Fee persistence requires its original persistent journal, registry, authority and source gate')
        self.store, self.registry, self.organizations = store, registry, organizations
        self.validate_source = validate_source
        self.schemas = self.SOURCE_SCHEMAS()
        with store._transaction():
            store._db.execute(f'CREATE TABLE IF NOT EXISTS {self.RECORDS_TABLE} '
                '(record_sha256 TEXT PRIMARY KEY, ref_key TEXT UNIQUE NOT NULL, record TEXT NOT NULL)')
            store._db.execute(f'CREATE TABLE IF NOT EXISTS {self.PUBLICATIONS_TABLE} '
                '(boundary_key TEXT PRIMARY KEY, record TEXT NOT NULL)')

    def _binding(self):
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != 'QS' or registration.skill is None:
            raise TaskConflict('Fee persistence requires its original implemented QS-A10 contract and Skill')
        return {'processor_id':registration.processor_id,
            'skill_sha256':registration.skill.manifest.skill_sha256,
            'contract_source_sha256':registration.contract.source_sha256,
            'formula':module_factory_descriptor(prepare_service_fee_calculation, 'service_fee.declared_formula')}

    def _validate(self, record):
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'organization_id',
                'context', 'action_input', 'prepared', 'binding', 'record_sha256'}
                or record['schema_version'] != self.SCHEMA or record['binding'] != self._binding()
                or record['record_sha256'] != task_digest({k:v for k,v in record.items() if k != 'record_sha256'})):
            raise TaskConflict('Saved fee calculation changes its original schema, binding or digest')
        context = ActionContext.model_validate(record['context'])
        grants = self._grants(context)
        if record['organization_id'] != grants[0].organization_id:
            raise TaskConflict('Saved fee calculation belongs to another original recipient')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(record['action_input'])
        prepared = record['prepared']
        fields = {'kind', 'projection', 'projection_sha256', 'context_sha256', 'input_sha256',
            'source_mode', 'source_reading', 'reading_sha256', 'author_authority_ref', 'formula', 'limitations'}
        if (not isinstance(prepared, dict) or set(prepared) != fields or prepared['kind'] != 'prepared'
                or action_input.calculation_ref is not None or action_input.scope != context.scope
                or prepared['context_sha256'] != task_digest(record['context'])
                or prepared['input_sha256'] != task_digest(record['action_input'])
                or prepared['reading_sha256'] != task_digest(prepared['source_reading'])
                or prepared['formula'] != record['binding']['formula']
                or prepared['source_mode'] != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')
                or not isinstance(prepared['source_reading'], list)):
            raise TaskConflict('Saved fee calculation substitutes its original input, formula or source reading')
        projection = QSBillingCalculationView.model_validate(prepared['projection'])
        resolver = ReferenceResolver(context.run_id, source_mode=prepared['source_mode'], schemas=self.schemas)
        sources, refs = {}, []
        for row in prepared['source_reading']:
            if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                raise TaskConflict('Saved fee sources require exact original ref/projection records')
            ref = Reference.model_validate(row['ref'])
            if ref.key() in sources:
                raise TaskConflict('Saved fee calculation repeats an original source reference')
            value = self.schemas.validate_projection(ref, row['projection'])
            if prepared['source_mode'] == 'formal' and isinstance(value, EvidenceRecord) and value.source_kind == 'synthetic':
                raise TaskConflict('Formal fee calculation cannot retain synthetic source evidence')
            sources[ref.key()] = value
            resolver.register_projection(ref, value)
            refs.append(ref)
        validate_qs_billing_sources(action_input, context=context,
            organization_id=record['organization_id'], sources=sources)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'QS')
        for ref in refs:
            reading.resolve(ref)
        author_ref = Reference.model_validate(prepared['author_authority_ref'])
        grant = reading.resolve(author_ref)
        if (not isinstance(grant, Authorization) or author_ref not in context.authorization_refs
                or grant not in grants or projection.ref not in context.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Saved fee calculation lost its original author or target read authority')
        for ref in grant.basis_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
                raise TaskConflict('Saved fee calculation author lacks current original evidence')
        expected = prepare_service_fee_calculation(context, action_input, reading,
            role='QS', action_id=self.ACTION_ID, billing_types=qs_billing_types(), calculation_ref=projection.ref)
        if (expected['kind'] != 'prepared' or expected['projection'] != projection
                or projection.model_dump(mode='json') != prepared['projection']
                or task_digest(prepared['projection']) != prepared['projection_sha256']
                or reading.evidence() != prepared['source_reading'] or reading.method_evidence()):
            raise TaskConflict('Saved fee calculation substitutes original work, credits, limits or formula output')
        reading.recheck()
        return context, projection

    def _publication_refs(self, record, projection):
        return [*super()._publication_refs(record, projection),
            *(Reference.model_validate(row['ref']) for row in record['prepared']['source_reading'])]

    def save(self, prepared, *, context, action_input, reading):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        grants = self._grants(context)
        if (not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations
                or reading.organization_id != grants[0].organization_id or reading.method_evidence()):
            raise TaskConflict('Fee save requires its actual original authorized formula reading')
        reading.check_method_context(context, self.ACTION_ID)
        reading.recheck()
        prepared = _plain(deepcopy(prepared))
        if prepared['source_reading'] != reading.evidence():
            raise TaskConflict('Fee save substitutes its actual original source cache')
        record = {'schema_version':self.SCHEMA, 'organization_id':reading.organization_id,
            'context':context.model_dump(mode='json'), 'action_input':action_input.model_dump(mode='json'),
            'prepared':prepared, 'binding':self._binding()}
        record['record_sha256'] = task_digest(record)
        _, projection = self._validate(record)
        if self.validate_source(deepcopy(record), context.model_copy(deep=True)) is not True:
            raise TaskConflict('Fee save requires independent actual current source validation')
        reading.recheck()
        ref_key = task_digest([self.store.run_id, self.ACTION_ID, self._execution_ref(projection)])
        with self.store._transaction():
            if self._grants(context) != grants:
                raise TaskConflict('Fee save authority changed during validation')
            self._validate(record)
            prior = self.store._db.execute(f'SELECT record FROM {self.RECORDS_TABLE} WHERE ref_key=?', (ref_key,)).fetchone()
            if prior is not None and json.loads(prior[0]) != record:
                raise TaskConflict('An original fee calculation reference cannot replace its saved execution')
            if prior is None:
                self.store._db.execute(f'INSERT INTO {self.RECORDS_TABLE} VALUES (?,?,?)',
                    (record['record_sha256'], ref_key, canonical(record)))
        return deepcopy(record)


class QSBillingCalculationPublishedViewProvider(QSCostCalculationPublishedViewProvider):
    def __init__(self, *, provider, publications):
        if not isinstance(publications, QSBillingCalculationPublicationStore):
            raise ValueError('Fee publication provider requires its original QS-A10 calculation store')
        super().__init__(provider=provider, publications=publications)
