"""Original Supplier A05 inventory planning and actual aggregate supply feedback."""
from copy import deepcopy
from integration.professional_monthly_native import ProfessionalMonthlyApplication, ProfessionalMonthlySettings
from integration.supplier_monthly_reliability import ReliabilityPlan, backup_request
from integration.supplier_planning_actions import SupplierPlanningActionAssembler
from integration.supplier_planning_results import SupplierPlanningResultWorker
from integration.supplier_order_native import SupplierOrderNativeApplication, SupplierOrderNativeSettings
from integration.supply_fulfillment_native import SupplyFulfillmentObservation
from integration.bank_financing_private import checked_result, evidence_binding
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension, module_client_implementation
from src.actions.contracts.common import StrictRecord, ref_type
from src.actions.contracts.supplier_monthly_inventory import SupplierInventoryJudgment
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest

BOUNDARY = ('Original aggregate monthly inventory-planning review only. An independently authorized own-risk '
    'forecast and original A05 request candidate remain private planning. Own actual earlier normalized supply '
    'results may affect the review; they are not physical stock, orders, batches, inspection, shipment or receipt facts. '
    'No inquiry is sent and no stock movement, exclusive reservation, payment or physical improvement is inferred.')


class InventoryPlan(ReliabilityPlan):
    observation_ref: ref_type('SupplierInventoryObservation')


def result_judgment(saved):
    if saved['result']['kind'] != 'completed' or saved['result']['payload']['choice'] != 'request_quote':
        raise TaskConflict('Inventory review needs the original completed A05 planning request')
    return SupplierInventoryJudgment.model_validate_json(saved['result']['payload']['note'])


def bind_sources(plan, observed):
    objects = deepcopy(plan.objects)
    basis = plan.native_evidence_ref.model_dump(mode='json')
    evidence_binding(objects, basis, observed)
    row, = [r['value'] for r in objects if r['ref'] == plan.observation_ref.model_dump(mode='json')]
    if any(row[k] is not None for k in ('material_index', 'native_free_ratio', 'prior_own_outcomes', 'actual_supply_outcomes')):
        raise TaskConflict('Inventory observations must be initially unbound')
    row.update(material_index={'value': str(observed['macro_environment']['material_price_index']), 'unit': 'index', 'basis_ref': basis},
        native_free_ratio={'value': str(observed['native_profile']['free_ratio']), 'unit': 'ratio', 'basis_ref': basis},
        prior_own_outcomes=deepcopy(observed['prior_own_monthly_outcomes']),
        actual_supply_outcomes=deepcopy(observed['actual_supply_outcomes']))
    return objects


class SupplierInventoryApplication(ProfessionalMonthlyApplication):
    VERSION = 'supplier-monthly-inventory-planning.v1'
    PREFIX = 'supplier_monthly_inventory_request:'
    COMPONENTS = {'Supplier': (SupplierPlanningActionAssembler, SupplierPlanningResultWorker)}
    OPERATIONS = {'Supplier': 'adjust_inventory'}
    PLAN_TYPE = InventoryPlan
    INPUT_SCHEMA = 'supplier-monthly-inventory-input.v1'
    ACTION_NUMBER = 'A05'
    COMPLETED_CHOICES = {'request_quote'}
    SCOPE_KEY = 'native_supplier_inventory_scope'
    LABEL = 'Original aggregate inventory-planning review'

    def __init__(self, *, supply_observer=None, **kwargs):
        self.supply_observer = supply_observer
        super().__init__(**kwargs)

    def participates(self, saved): return result_judgment(saved).participate
    def result_note(self, saved): return result_judgment(saved).interpretation

    def history(self, org, tick):
        history = super().history(org, tick)
        for h in history:
            saved = checked_result(self.workers['Supplier'], TaskIdentity(**h['micro_identity']))
            event, = [e for e in self.assembly.engine.events.events if e.event_id == h['event_id']]
            memory = [m for m in self.assembly.engine.agents[org].episodic_memory
                if m.get('tick') == h['tick'] and m.get('operation') == h['operation']]
            if len(memory) != 1 or memory[0]['label'] != event.data['label'] or memory[0]['capability_update'] != event.data.get('capability_update'):
                raise TaskConflict('Inventory history lost its actual own native memory')
            h.update(review=result_judgment(saved).model_dump(mode='json'), backup_request=backup_request(saved),
                original_native_memory=deepcopy(memory[0]))
        expected = {r['scope']['tick'] for r in self.records() if r['scope']['organization_id'] == org and r['scope']['tick'] < tick}
        if expected != {h['tick'] for h in history}:
            raise TaskConflict('Earlier micro inventory review has no actual monthly outcome')
        return sorted(history, key=lambda h: h['tick'])

    def supply_outcomes(self, org, tick):
        if self.supply_observer is None: return []
        self.supply_observer.check()
        engine = self.assembly.engine
        rows = [r for r in self.supply_observer.records() if r['organization_id'] == org and r['tick'] < tick]
        for r in rows:
            event, = [e for e in engine.events.events if e.event_id == r['event_id']]
            raw = event.model_dump(mode='json'); raw['data'].pop('agent_observer_errors', None)
            project = engine.projects[r['project_id']]
            if (r['record_sha256'] != task_digest({k: v for k, v in r.items() if k != 'record_sha256'})
                    or r['run_id'] != self.assembly.client.run_id or r['simulation_id'] != self.assembly.client.simulation_id
                    or r['source_event_sha256'] != task_digest(raw) or r['project_id'] != event.project_id
                    or r['tick'] != event.tick or r['event_type'] != event.event_type
                    or org not in project.selected_supplier_ids
                    or not any(task_digest(g.model_dump(mode='json')) == r['engagement_sha256'] for g in project.engagements
                        if g.agent_id == org and g.role == 'Supplier')):
                raise TaskConflict('Inventory review lost its own exact committed original supply result')
        return sorted(rows, key=lambda r: (r['tick'], r['event_id'], r['project_id']))

    def sources(self, plan, request):
        scope = self.scope(request, purpose='propose'); agent = self.assembly.engine.agents[plan.organization_id]
        observed = {'scope': scope, 'native_request_sha256': task_digest(request.model_dump(mode='json')),
            'macro_environment': deepcopy(request.inputs['macro_environment']),
            'native_profile': {'available_resource': agent.available_resource(), 'total_resource_capacity': agent.total_resource_capacity,
                'free_ratio': agent.available_resource()/agent.total_resource_capacity},
            'prior_own_monthly_outcomes': self.history(plan.organization_id, plan.tick),
            'actual_supply_outcomes': self.supply_outcomes(plan.organization_id, plan.tick)}
        return bind_sources(plan, observed), observed

    def evidence(self):
        result = super().evidence(); result['boundary'] = BOUNDARY
        return result


class InventorySupplySettings(StrictRecord):
    supplier: SupplierOrderNativeSettings
    monthly: ProfessionalMonthlySettings


class InventorySupplyComposition:
    VERSION = 'supplier-inventory-supply-feedback.v1'

    def __init__(self, *, assembly, settings):
        self.assembly = assembly; self.settings = InventorySupplySettings.model_validate(settings).model_copy(deep=True)
        self._settings_sha = task_digest(self.settings.model_dump(mode='json'))
        self.supplier = SupplierOrderNativeApplication(assembly=assembly, settings=self.settings.supplier, install=False)
        self.authority = self.supplier.authority; self.read_guard = self.authority.read_guard
        try:
            base = GbaModuleHostExtension(version=self.supplier.VERSION, evidence=self.supplier.evidence,
                close=self.authority.close, writer_guard=self.read_guard)
            self.observer = SupplyFulfillmentObservation(assembly=assembly, base=base, settings={'version': '1', 'verified_detailed_issuers': {}})
            self.monthly = SupplierInventoryApplication(assembly=assembly, settings=self.settings.monthly,
                authority=self.authority, install=False, supply_observer=self.observer)
            client = assembly.client
            with client._lock:
                for (role, operation), handler in self.bindings().items():
                    client.bind_proposal_handler(role=role, operation=operation, handler=handler, client_version=self.VERSION+':'+role+':'+operation)
                client.decision_handler = self.decide
                self.supplier.seal_client_binding(); self.monthly.seal_client_binding()
                self._implementation = module_client_implementation(client)
            self.check()
        except BaseException:
            self.authority.close(); raise

    def bindings(self): return {**self.supplier.proposal_bindings(), **self.monthly.proposal_bindings()}

    def check(self):
        client = self.assembly.client
        if (task_digest(self.settings.model_dump(mode='json')) != self._settings_sha
                or self.monthly.authority is not self.authority or self.monthly.supply_observer is not self.observer
                or self.monthly._other_decision != self.supplier._other_decision
                or module_client_implementation(client) != self._implementation or client.decision_handler != self.decide
                or any(client.proposal_handlers.get(k) != v for k, v in self.bindings().items())):
            raise TaskConflict('Inventory/supply composition changed its sealed original runtime')
        self.supplier._check(); self.monthly.check(); self.observer.check()

    def decide(self, request):
        self.check()
        if request.agent.role == 'Supplier' and request.decision_type == 'monthly_enterprise_operation':
            return self.monthly.decide(request)
        return self.supplier.decide(request)

    def evidence(self):
        with self.read_guard():
            self.check()
            return {'version': self.VERSION, 'supplier': self.supplier.evidence(), 'monthly': self.monthly.evidence(),
                'supply_observations': self.observer.records(), 'boundary': BOUNDARY}


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    if offline is not True: raise ValueError('Fixed inventory scenario requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    settings = GbaModuleHostConfiguration.model_validate(configuration).settings
    if 'supplier' in settings:
        app = InventorySupplyComposition(assembly=assembly, settings=settings)
    else:
        app = SupplierInventoryApplication(assembly=assembly, settings=settings)
    return GbaModuleHostExtension(version=app.VERSION, evidence=app.evidence, close=app.authority.close, writer_guard=app.read_guard)
