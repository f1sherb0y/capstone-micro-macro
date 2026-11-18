"""Stage own actual normalized supply feedback while detailed issuers are missing.

This is an observation/source gate, not an order, execution or receipt ledger.
No detailed Supplier A05-A09 invocation is fabricated from aggregate state.
"""
from copy import deepcopy
import json

from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension
from integration.supplier_order_native import configure_assembly as configure_supply
from src.coordination.tasks import TaskConflict, canonical, task_digest


GATES = {
    'SUPPLIER-A05': {'handler':'integration.supplier_planning_actions:SupplierPlanningActionAssembler',
        'missing':['effective_order_and_original_lines','verified_order_formation_relation','current_work_authority','physical_demand_recipe_stock_capacity']},
    'SUPPLIER-A06': {'handler':'integration.supplier_execution_actions:SupplierExecutionActionAssembler',
        'missing':['formed_original_plan_and_tasks','authentic_production_release_and_gates','exclusive_inputs_and_allocations','actual_execution_and_stock_query']},
    'SUPPLIER-A07': {'handler':'integration.supplier_quality_actions:SupplierQualityActionAssembler',
        'missing':['actual_physical_batch_and_lineage','inspection_requirements_and_method','independent_inspection_or_disposition_issuer_and_query']},
    'SUPPLIER-A08': {'handler':'integration.supplier_logistics_actions:SupplierLogisticsActionAssembler',
        'missing':['effective_order_lines_and_dispatchable_stock','independent_dispatch_release','route_window_transport_allocations','actual_shipment_issuer_and_query']},
    'SUPPLIER-A09': {'handler':'integration.supplier_receiving_actions:SupplierReceivingActionAssembler',
        'missing':['actual_original_shipment_and_arrival','independent_customer_receipt_and_problems','authored_supplement_or_customer_disposition','receipt_and_stock_use_release_queries']},
}
EVENTS = {'supplier_selected','construction_progress_updated','supply_delay'}


class SupplyFulfillmentObservation:
    VERSION='native-supply-fulfillment-observation.v1'
    PREFIX='native_supply_fulfillment_observation:'

    def __init__(self,*,assembly,base,settings):
        self.assembly,self.base,self.settings=assembly,base,deepcopy(settings)
        if settings!={'version':'1','verified_detailed_issuers':{}}:
            raise ValueError('Unverified detailed issuers cannot become a formal supply endpoint')
        self._gates=task_digest(GATES)
        assembly.engine.events.add_observer(self.observe)

    def check(self):
        self.assembly._validate_components()
        if (self._gates!=task_digest(GATES)
                or self.assembly.engine.events._observers.count(self.observe)!=1
                or self.settings!={'version':'1','verified_detailed_issuers':{}}):
            raise TaskConflict('Original supply feedback gate or observer changed')

    def observe(self,event,source_project):
        if event.event_type not in EVENTS:return
        with self.base.writer_guard():
            self.check()
            engine,client=self.assembly.engine,self.assembly.client
            project=engine.projects.get(event.project_id)
            if project is None or source_project is not project:
                raise TaskConflict('Supply observation lost its actual project')
            original=event.model_dump(mode='json')
            def business(value):
                v=deepcopy(value);v['data'].pop('agent_observer_errors',None);return v
            global_events=[e.model_dump(mode='json') for e in engine.events.events if e.event_id==event.event_id]
            project_events=[e for e in project.event_log if e['event_id']==event.event_id]
            if (len(global_events)!=1 or len(project_events)!=1
                    or business(global_events[0])!=business(original) or business(project_events[0])!=business(original)
                    or event.tick!=engine.current_tick):
                raise TaskConflict('Supply feedback is not the current actual original global/project event')
            if event.event_type=='supplier_selected' and event.data.get('supplier_id') not in project.selected_supplier_ids:
                raise TaskConflict('Supply selection projection changed its actual native recipient')
            if event.event_type=='construction_progress_updated' and event.agent_id!=project.selected_contractor_id:
                raise TaskConflict('Supply snapshot trigger lost its actual current Contractor')
            if event.event_type=='supply_delay' and event.data.get('supplier_ids')!=project.selected_supplier_ids:
                raise TaskConflict('Supply delay changed its actual selected Suppliers')
            suppliers=[engine.agents[org] for org in project.selected_supplier_ids]
            if not suppliers:return
            mean=lambda name:sum(getattr(p,name) for p in suppliers)/len(suppliers)
            state={field:getattr(project.performance,field) for field in
                ('material_availability','material_quality','supply_delay_risk')}
            profiles={'supplier_count':len(suppliers),'average_reliability':mean('supply_reliability'),
                'average_material_quality':mean('material_quality')}
            for org in project.selected_supplier_ids:
                if client.organization_roles.get(org)!='Supplier':raise TaskConflict('Supply feedback recipient is not a Supplier')
                engagements=[g for g in project.engagements if g.role=='Supplier' and g.agent_id==org and g.status.value=='active']
                if len(engagements)!=1:raise TaskConflict('Supply feedback lacks its own actual ACTIVE native engagement')
                record={'schema_version':self.VERSION,'simulation_id':client.simulation_id,'run_id':client.run_id,
                    'organization_id':org,'project_id':project.project_id,'tick':event.tick,'event_id':event.event_id,
                    'event_type':event.event_type,'source_event_sha256':task_digest(business(original)),
                    'native_state':state,'native_supplier_profile_averages':profiles,
                    'engagement_sha256':task_digest(engagements[0].model_dump(mode='json')),
                    'projection_fields':sorted(state),'scope':'own_current_selected_supplier',
                    'gates':{action:{**deepcopy(v),'status':'blocked_missing_verified_native_sources','micro_identity':None}
                        for action,v in GATES.items()},
                    'micro_actions_invoked':0,'formal_effects_created':False,
                    'boundary':'Authenticated aggregate native observation only. Missing detailed sources stay unknown; no order, release, batch, shipment, inspection, receipt or stock/cash effect is inferred.'}
                key=self.PREFIX+task_digest([client.simulation_id,org,event.event_id])
                record['key']=key;record['record_sha256']=task_digest(record)
                with client.tasks._transaction():
                    prior=client.tasks._db.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()
                    if prior is not None and json.loads(prior[0])!=record:
                        raise TaskConflict('Original supply observation identity was reused with changed state')
                    if prior is None:client.tasks._db.execute('INSERT INTO metadata VALUES (?,?)',(key,canonical(record)))

    def records(self):
        with self.assembly.client.tasks._lock:
            return [json.loads(v) for v, in self.assembly.client.tasks._db.execute(
                'SELECT value FROM metadata WHERE key LIKE ? ORDER BY key',(self.PREFIX+'%',))]

    def evidence(self):
        with self.base.writer_guard():
            self.check()
            return {'version':self.VERSION,'supply':self.base.evidence(),'supply_feedback':self.records(),
                'detailed_stage_status':'blocked_missing_verified_native_sources','micro_fulfillment_actions_invoked':0,
                'boundary':'Source staging and explicit waits, not completed micro fulfilment or formal receipts.'}


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    config=GbaModuleHostConfiguration.model_validate(configuration)
    if set(config.settings)!={'supplier','supply_feedback'}:
        raise ValueError('Supply feedback needs its explicit original supplier host and source gate')
    base=configure_supply(assembly=assembly,request=request,output_directory=output_directory,offline=offline,
        configuration={**config.model_dump(mode='json'),'settings':config.settings['supplier']})
    try:
        app=SupplyFulfillmentObservation(assembly=assembly,base=base,settings=config.settings['supply_feedback'])
    except BaseException:
        base.close();raise
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=base.close,writer_guard=base.writer_guard)
