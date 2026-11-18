"""Persist Supplier quote source projections at fresh read points, without business writes."""
from copy import deepcopy
from functools import partial
import json

from integration.supplier_quote_costs import prepare_supplier_quote_cost
from integration.supplier_quote_logistics_source import prepare_supplier_quote_logistics
from integration.supplier_quote_inventory_source import prepare_supplier_quote_inventory
from integration.supplier_quote_capacity_source import prepare_supplier_quote_capacity
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_quote_objects import (
    QuoteCapacityView, QuoteCostView, QuoteInventoryView, QuoteLogisticsView, QuoteResourcePoolView,
)
from src.coordination.tasks import TaskConflict, TaskStore, canonical, task_digest
from src.organization.registry import OrganizationRegistry


class SupplierQuoteCostPublicationStore:
    """Technical quote cache in the original TaskStore; never a business ledger.

    validate_source(record, context) must return True after checking every
    original source/adoption against the actual current host snapshot. It runs
    before saving and on every read, including retained prior publications.
    """
    SCHEMA = 'supplier-quote-cost-publication.v1'
    LOGISTICS_SCHEMA = 'supplier-quote-publication.v2'
    INVENTORY_SCHEMA = 'supplier-quote-publication.v3'
    CAPACITY_SCHEMA = 'supplier-quote-publication.v4'
    ACTION = 'SUPPLIER-A03'

    def __init__(self, *, store, organizations, validate_source):
        if (not isinstance(store, TaskStore) or not isinstance(organizations, OrganizationRegistry)
                or organizations.run_id != store.run_id or not callable(validate_source)):
            raise ValueError('Original same-run store, registry and actual source validator required')
        self.store, self.organizations, self.validate_source = store, organizations, validate_source
        with store._transaction():
            store._db.execute('CREATE TABLE IF NOT EXISTS supplier_quote_cost_publications '
                '(publication_key TEXT PRIMARY KEY, record TEXT NOT NULL)')
            store._db.execute('CREATE TABLE IF NOT EXISTS supplier_quote_cost_objects '
                '(ref_key TEXT PRIMARY KEY, record TEXT NOT NULL)')
            store._db.execute('CREATE TABLE IF NOT EXISTS supplier_quote_cost_read_points '
                '(boundary_key TEXT PRIMARY KEY, record TEXT NOT NULL)')

    def _key(self, context, organization_id):
        return task_digest([context.run_id, organization_id, context.read_token])

    def _object_key(self, ref):
        return task_digest([self.store.run_id, self.ACTION, ref])

    def _grants(self, context, organization_id=None, grants=None):
        if (context.run_id != self.store.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION):
            raise TaskConflict('Cost publication requires original run and Supplier A03')
        current = self.organizations.grants(context, self.ACTION, 'Supplier')
        recipient = current[0].organization_id
        if (recipient not in self.store.organization_ids
                or organization_id is not None and organization_id != recipient
                or grants is not None and current != grants):
            raise TaskConflict('Cost publication changes current original Supplier authority')
        return current

    def _check_objects(self, objects, context, grants, organization_id):
        permitted = {ref.key() for grant in grants for ref in grant.readable_refs}
        permitted &= {ref.key() for ref in context.visible_refs}
        refs, capacities, pools = [], [], {}
        for item in objects:
            if not isinstance(item, dict) or set(item) != {'ref', 'value'}:
                raise TaskConflict('Cost publication requires closed object projections')
            ref = Reference.model_validate(item['ref'])
            schema = {'CostBasis': QuoteCostView, 'LogisticsAssessment': QuoteLogisticsView,
                'InventorySnapshot': QuoteInventoryView, 'SupplierCapacity': QuoteCapacityView,
                'ResourcePool': QuoteResourcePoolView}.get(ref.kind)
            if schema is None:
                raise TaskConflict('Quote publication only accepts explicitly supported source projections')
            row = schema.model_validate(item['value'])
            snapshot = isinstance(row, (QuoteInventoryView, QuoteCapacityView))
            pool = isinstance(row, QuoteResourcePoolView)
            recipient = row.organization_id if snapshot or pool else row.supplier_organization_id
            if pool:
                current = True  # The matching capacity below supplies the original current window.
            elif snapshot:
                current = row.as_of == context.business_time
            else:
                current = row.available_at == context.business_time and row.effective_window.contains(context.business_time)
            if (row.ref != ref or ref.key() not in permitted
                    or recipient != organization_id
                    or isinstance(row, QuoteCostView) and row.destination_scope_ref != context.scope
                    or not current):
                raise TaskConflict('Published quote source changes original version, Supplier, scope, time or permission')
            refs.append(ref)
            if pool:
                pools[ref.key()] = row
            elif isinstance(row, QuoteCapacityView):
                capacities.append(row)
        unique_refs(refs)
        required = {resource.resource_ref.key() for capacity in capacities for resource in capacity.resources}
        if required != set(pools):
            raise TaskConflict('Published capacity and original pool objects must form one complete bundle')
        for capacity in capacities:
            for resource in capacity.resources:
                if (pools[resource.resource_ref.key()].region_id != resource.region_id
                        or not resource.effective_window.contains(context.business_time)):
                    raise TaskConflict('Published pool changes original region or current capacity window')

    def publish(self, prepared, *, source_context, reading, next_context,
            adoption_ref, validate_current):
        """Reproduce an original cost, preserving the legacy cost-only record format."""
        return self._publish(prepared, source_context=source_context, reading=reading,
            next_context=next_context, adoption_ref=adoption_ref, validate_current=validate_current,
            producer=prepare_supplier_quote_cost, projection_name='cost_projection', ref_name='cost_ref')

    def publish_logistics(self, prepared, *, source_context, reading, next_context,
            adoption_ref, validate_current):
        """Publish the exact original plan while retaining costs and their provenance."""
        return self._publish(prepared, source_context=source_context, reading=reading,
            next_context=next_context, adoption_ref=adoption_ref, validate_current=validate_current,
            producer=prepare_supplier_quote_logistics, projection_name='logistics_projection', ref_name='logistics_ref')

    def publish_inventory(self, prepared, *, source_context, reading, next_context,
            adoption_ref, validate_current):
        """Publish exact actual stock while retaining all original quote sources."""
        return self._publish(prepared, source_context=source_context, reading=reading,
            next_context=next_context, adoption_ref=adoption_ref, validate_current=validate_current,
            producer=prepare_supplier_quote_inventory, projection_name='inventory_projection', ref_name='inventory_ref')

    def publish_capacity(self, prepared, *, source, source_context, reading, next_context,
            adoption_ref, validate_current):
        """Publish capacity and its original pool projections in one transaction."""
        return self._publish(prepared, source_context=source_context, reading=reading,
            next_context=next_context, adoption_ref=adoption_ref, validate_current=validate_current,
            producer=partial(prepare_supplier_quote_capacity, deepcopy(source)),
            projection_name='capacity_projection', ref_name='capacity_ref')

    def _publish(self, prepared, *, source_context, reading, next_context,
            adoption_ref, validate_current, producer, projection_name, ref_name):
        """Reproduce from actual sources, then save at an explicitly new token."""
        source = ActionContext.model_validate(source_context).model_copy(deep=True)
        context = ActionContext.model_validate(next_context).model_copy(deep=True)
        if (not isinstance(reading, ActionReadView) or source.read_token == context.read_token
                or any(getattr(source, name) != getattr(context, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('Cost publication requires same original identity/time and a fresh token')
        source_grants = self._grants(source)
        grants = self._grants(context, source_grants[0].organization_id)
        organization_id = grants[0].organization_id
        if reading.organization_id != organization_id:
            raise TaskConflict('Cost reading belongs to another Supplier')
        reading.check_method_context(source, self.ACTION)
        original = producer(context=source, reading=reading,
            adoption_ref=adoption_ref, validate_current=validate_current)
        if prepared != original:
            raise TaskConflict('Prepared quote source differs from its actual original record/adoption')
        parent = self.read(source, organization_id=organization_id, grants=source_grants)
        objects = {} if parent is None else {
            Reference.model_validate(item['ref']).key(): deepcopy(item) for item in parent['objects']}
        for item in objects.values():
            if reading.resolve(Reference.model_validate(item['ref'])).model_dump(mode='json') != item['value']:
                raise TaskConflict('Retained quote source differs from the authorized original source reading')
        projection = original[projection_name]
        additions = [projection, *original.get('resource_projections', [])]
        for row in additions:
            item = {'ref': row.ref.model_dump(mode='json'), 'value': row.model_dump(mode='json')}
            if row.ref.key() in objects and objects[row.ref.key()] != item:
                raise TaskConflict('Quote publication cannot replace an immutable source version')
            objects[row.ref.key()] = item
        self._check_objects(list(objects.values()), context, grants, organization_id)
        provenance = {key: deepcopy(value) for key, value in original.items()
            if key not in {projection_name, 'resource_projections'}}
        provenance.update(adoption_ref=Reference.model_validate(adoption_ref).model_dump(mode='json'),
            source_context=source.model_dump(mode='json'))
        provenance[ref_name] = projection.ref.model_dump(mode='json')
        if 'resource_projections' in original:
            provenance['resource_refs'] = [row.ref.model_dump(mode='json') for row in original['resource_projections']]
        sources = [] if parent is None else deepcopy(parent['sources'])
        if provenance not in sources:
            sources.append(provenance)
        schema_version = self.SCHEMA
        if ref_name == 'logistics_ref' or parent is not None and parent['schema_version'] == self.LOGISTICS_SCHEMA:
            schema_version = self.LOGISTICS_SCHEMA
        if ref_name == 'inventory_ref' or parent is not None and parent['schema_version'] == self.INVENTORY_SCHEMA:
            schema_version = self.INVENTORY_SCHEMA
        if ref_name == 'capacity_ref' or parent is not None and parent['schema_version'] == self.CAPACITY_SCHEMA:
            schema_version = self.CAPACITY_SCHEMA
        record = {'schema_version': schema_version, 'run_id': context.run_id,
            'organization_id': organization_id, 'context': context.model_dump(mode='json'),
            'objects': list(objects.values()), 'sources': sources,
            'parent_publication_sha256': None if parent is None else parent['record_sha256']}
        record['record_sha256'] = task_digest(record)
        if self.validate_source(deepcopy(record), context.model_copy(deep=True)) is not True:
            raise TaskConflict('All retained and new quote sources/adoptions require current host validation')
        reading.recheck()
        key = self._key(context, organization_id)
        with self.store._transaction():
            self._grants(source, organization_id, source_grants)
            self._grants(context, organization_id, grants)
            prior = self.store._db.execute('SELECT record FROM supplier_quote_cost_publications '
                'WHERE publication_key=?', (key,)).fetchone()
            if prior is not None:
                if json.loads(prior[0]) != record:
                    raise TaskConflict('Published cost token content cannot change')
                return deepcopy(record)
            if self.store._db.execute('SELECT 1 FROM supplier_quote_cost_read_points '
                    'WHERE boundary_key=?', (key,)).fetchone() is not None:
                raise TaskConflict('Previously read token cannot receive a new cost publication')
            for obj in record['objects']:
                ref_key = self._object_key(obj['ref'])
                saved = self.store._db.execute('SELECT record FROM supplier_quote_cost_objects '
                    'WHERE ref_key=?', (ref_key,)).fetchone()
                if saved is not None and json.loads(saved[0]) != obj:
                    raise TaskConflict('Original cost object version cannot change')
                if saved is None:
                    self.store._db.execute('INSERT INTO supplier_quote_cost_objects VALUES (?,?)',
                        (ref_key, canonical(obj)))
            self.store._db.execute('INSERT INTO supplier_quote_cost_publications VALUES (?,?)',
                (key, canonical(record)))
        return deepcopy(record)

    def read(self, context, *, organization_id, grants):
        context = ActionContext.model_validate(context)
        self._grants(context, organization_id, grants)
        with self.store._lock:
            saved = self.store._db.execute('SELECT record FROM supplier_quote_cost_publications '
                'WHERE publication_key=?', (self._key(context, organization_id),)).fetchone()
            if saved is None:
                return None
            record = json.loads(saved[0])
            if (record.get('schema_version') not in {
                    self.SCHEMA, self.LOGISTICS_SCHEMA, self.INVENTORY_SCHEMA, self.CAPACITY_SCHEMA}
                    or record.get('run_id') != self.store.run_id
                    or record.get('organization_id') != organization_id
                    or record.get('context') != context.model_dump(mode='json')
                    or task_digest({k: v for k, v in record.items() if k != 'record_sha256'}) != record.get('record_sha256')):
                raise TaskConflict('Saved cost publication changes original identity or digest')
            self._check_objects(record['objects'], context, grants, organization_id)
            allowed = {self.SCHEMA: {'CostBasis'},
                self.LOGISTICS_SCHEMA: {'CostBasis', 'LogisticsAssessment'},
                self.INVENTORY_SCHEMA: {'CostBasis', 'LogisticsAssessment', 'InventorySnapshot'},
                self.CAPACITY_SCHEMA: {'CostBasis', 'LogisticsAssessment', 'InventorySnapshot', 'SupplierCapacity', 'ResourcePool'}}
            if any(item['ref']['kind'] not in allowed[record['schema_version']] for item in record['objects']):
                raise TaskConflict('Original publication schema contains a substituted object kind')
            for item in record['objects']:
                original = self.store._db.execute('SELECT record FROM supplier_quote_cost_objects '
                    'WHERE ref_key=?', (self._object_key(item['ref']),)).fetchone()
                if original is None or json.loads(original[0]) != item:
                    raise TaskConflict('Saved cost object differs from the original version')
        if self.validate_source(deepcopy(record), context.model_copy(deep=True)) is not True:
            raise TaskConflict('All published quote sources/adoptions require fresh actual host validation')
        self._grants(context, organization_id, grants)
        return deepcopy(record)


class SupplierQuoteCostPublishedViewProvider:
    """Merge into an actual fresh host envelope; freeze each observed read point."""
    def __init__(self, *, provider, publications):
        if (not callable(getattr(provider, 'project', None))
                or not isinstance(publications, SupplierQuoteCostPublicationStore)):
            raise ValueError('Actual host provider and original Supplier cost publication store required')
        self.provider, self.publications = provider, publications

    def project(self, *, context, organization_id, grants):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        raw = deepcopy(self.provider.project(context=context.model_copy(deep=True),
            organization_id=organization_id, grants=deepcopy(grants)))
        if context.contract_ref.id != self.publications.ACTION:
            return raw
        required = {'run_id', 'macro_version', 'state_version', 'read_token',
            'business_time', 'organization_id', 'objects'}
        if (not isinstance(raw, dict) or set(raw) != required or raw['run_id'] != context.run_id
                or raw['read_token'] != context.read_token or raw['organization_id'] != organization_id
                or raw['business_time'] != context.business_time.model_dump(mode='json')
                or not all(isinstance(raw[key], str) and raw[key].strip() for key in ('macro_version', 'state_version'))
                or not isinstance(raw['objects'], list)):
            raise TaskConflict('Actual host provider changes published cost read point')
        publication = self.publications.read(context, organization_id=organization_id, grants=grants)
        permitted = {ref.key() for grant in grants for ref in grant.readable_refs}
        permitted &= {ref.key() for ref in context.visible_refs}
        objects = {}
        for item in raw['objects']:
            if not isinstance(item, dict) or set(item) != {'ref', 'value'}:
                raise TaskConflict('Host provider returned an invalid projection')
            key = Reference.model_validate(item['ref']).key()
            if key not in permitted or key in objects:
                raise TaskConflict('Host provider repeats or exceeds authorized original objects')
            objects[key] = item
        if publication is not None:
            for item in publication['objects']:
                key = Reference.model_validate(item['ref']).key()
                if key in objects and objects[key] != item:
                    raise TaskConflict('Host object conflicts with the immutable cost projection')
                objects[key] = item
            raw['state_version'] = task_digest({'host_state_version': raw['state_version'],
                'cost_publication_sha256': publication['record_sha256']})
        unique_refs([Reference.model_validate(item['ref']) for item in objects.values()])
        raw['objects'] = list(objects.values())
        token_key = self.publications._key(context, organization_id)
        boundary_key = task_digest(['boundary', context.model_dump(mode='json'), organization_id])
        frozen = {'state_version': raw['state_version'], 'macro_version': raw['macro_version'],
            'business_time': raw['business_time']}
        with self.publications.store._transaction():
            self.publications._grants(context, organization_id, grants)
            # Detect publication racing the underlying provider read.
            saved = self.publications.store._db.execute('SELECT record FROM supplier_quote_cost_publications '
                'WHERE publication_key=?', (token_key,)).fetchone()
            if (None if saved is None else json.loads(saved[0])) != publication:
                raise TaskConflict('Cost publication changed while reading; use a fresh token')
            for key, value in ((token_key, frozen), (boundary_key, {'sha256': task_digest(raw)})):
                prior = self.publications.store._db.execute('SELECT record FROM supplier_quote_cost_read_points '
                    'WHERE boundary_key=?', (key,)).fetchone()
                if prior is not None and json.loads(prior[0]) != value:
                    raise TaskConflict('Observed original cost read point cannot change')
                if prior is None:
                    self.publications.store._db.execute('INSERT INTO supplier_quote_cost_read_points VALUES (?,?)',
                        (key, canonical(value)))
        return raw
