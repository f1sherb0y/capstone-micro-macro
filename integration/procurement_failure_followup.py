"""Actual native procurement failure triggers an authorized private original A05."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.bank_financing_private import checked_result,evidence_binding
from integration.contractor_planning_actions import ContractorPlanningActionAssembler
from integration.contractor_planning_results import ContractorPlanningResultWorker
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
from integration.supplier_order_native import SupplierOrderNativeApplication
from src.actions.contracts.common import ActionContext,Reference
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest

BOUNDARY='Original native no-supplier selection remains a failure and adds its original delay. Actual own committed failure may trigger an independently authorized original A05 private request_quote proposal. No inquiry delivery, new Supplier acceptance, selected supplier, detailed order, reservation or payment is inferred. Partial acceptance and revised/unresolved terms remain blocked. No Contractor A05 selection decision is claimed for the native negative selection.'


def project_failure_event(observation,roles):
    """Disclose only the failed Contractor's own original outcome."""
    if not observation.committed or observation.event_type!='supplier_selection_failed' or not isinstance(roles,dict):return {}
    org=observation.agent_id;data=observation.data;decision=data.get('contractor_decision',{})
    if roles.get(org)!='Contractor' or data.get('contractor_id')!=org:return {}
    scope={'project_id':observation.project_id,'contractor_id':org,'tick':observation.tick}
    if (decision.get('accepted') is not False or decision.get('action_type')!='select_supplier'
            or decision.get('native_supply_scope')!=scope or decision.get('decision_source') not in {'native_macro','micro_contractor_no_accepted'}
            or decision.get('selected_supplier_id') or data.get('delay_days_added')!=15):return {}
    return {org:{'event_type':observation.event_type,'tick':observation.tick,'project_id':observation.project_id,
        'agent_id':org,'committed':True,'data':{'contractor_id':org,'delay_days_added':15,
            'native_supply_scope':scope,'native_decision_sha256':task_digest(decision)}}}


def authenticate_failure(supplier,row):
    """Compare recipient-scoped memory with the actual event and native transport."""
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    assembly=supplier.assembly;client=assembly.client;payload=row['payload'];org=row['organization_id']
    project=assembly.engine.projects.get(payload['project_id'])
    events=[] if project is None else [e for e in project.event_log if e['event_id']==row['event_id']]
    if len(events)!=1:raise TaskConflict('Failure feedback lost its original native event')
    event=events[0];expected=project_failure_event(AgentObservationV1.model_validate(event),client.organization_roles)
    if (project.selected_contractor_id!=org or expected.get(org)!=payload or event['tick']>assembly.engine.current_tick
            or row['run_id']!=client.run_id):raise TaskConflict('Failure feedback changed original recipient, event, time or run')
    scope=payload['data']['native_supply_scope'];tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=org)
    def formed(purpose,action,field):
        values=[t for t in tasks if t['identity']['purpose']==purpose and t['identity']['action_id']==action
            and t['state']=='output_formed' and t['output'].get(field,{}).get('native_supply_scope')==scope]
        if len(values)!=1:raise TaskConflict('Failure feedback lacks its exact original native transport')
        task=values[0]
        if task['output_sha256']!=task_digest(task['output']):raise TaskConflict('Original native failure task changed')
        return task
    proposal=formed('propose','select_supplier','factors');final=formed('decide','contractor_supplier_selection','data')
    p=proposal['output'];f=final['output'];decision=event['data']['contractor_decision']
    if (p['accepted'] is not False or f['decision'] is not False or p['data'].get('selected_supplier_id')
            or f['data'].get('selected_supplier_id') or p['factors'].get('decision_source') not in {'native_macro','micro_contractor_no_accepted'}
            or decision.get('proposal_response_sha256')!=task_digest(p)
            or f['data'].get('proposal_response_sha256')!=task_digest(p)):
        raise TaskConflict('Failed selection was not the same actual original negative native decision')
    proof={'event':deepcopy(event),'event_sha256':task_digest(event),'received':deepcopy(row),
        'original_native_proposal':proposal,'original_native_final':final,'scope':scope}
    if p['factors'].get('decision_source')=='micro_contractor_no_accepted':
        from integration.contractor_negative_selection import authenticate_negative_result
        proof['original_micro_negative']=authenticate_negative_result(supplier,decision,p,f)
    elif decision.get('decision_source')!='native_macro' or f['data'].get('decision_source')!='native_macro':
        raise TaskConflict('Original native negative provenance changed')
    return proof


class ProcurementFailureFollowup:
    PREFIX='procurement_failure_followup:'
    VERSION='procurement-failure-followup.v1'
    def boundary(self):
        if self.supplier.contractor is None:return BOUNDARY
        return ('Actual no-accepted A05 wait drives the original negative supplier selection and original delay. '
            'This follow-up is a private request_quote intention only; no sent inquiry, accepted supplier, order, reservation or payment. '
            'The original pending selection stays pending until dependencies change; other unresolved micro outcomes cannot be translated.')
    def __init__(self,*,supplier,settings):
        self.supplier=supplier;self.settings=deepcopy(settings);self._check_file()
        doc=json.loads(Path(settings['file_path']).read_bytes())
        if doc['schema_version']!=self.VERSION or doc['run_id']!=supplier.assembly.client.run_id:raise TaskConflict('Follow-up input changed run/schema')
        self.plans=deepcopy(doc['plans']);self._plans_sha=task_digest(self.plans);self._bound={}
        selectors=[]
        for p in self.plans:
            c=ActionContext.model_validate(p['context']);selectors.append((p['organization_id'],p['project_id'],p['tick']))
            if (c.run_id!=doc['run_id'] or c.contract_ref.id!='CONTRACTOR-A05' or c.scope.kind!='project'
                    or c.scope.ref.id!=p['project_id'] or c.business_time.offset!=p['tick'] or c.execution_mode=='offline_fixture'
                    or supplier.organizations.grants(c,'CONTRACTOR-A05','Contractor')[0].organization_id!=p['organization_id']
                    or p['trigger']!='own_committed_supplier_selection_failed'):
                raise TaskConflict('Follow-up changes its original own authorized invocation')
        if not selectors or len(set(selectors))!=len(selectors):raise TaskConflict('Follow-up selectors must be unique')
        self.assembler=ContractorPlanningActionAssembler(registry=supplier.registry,organizations=supplier.organizations,provider=self,
            macro_version='gba-public-2026-08-21',source_mode='formal',policy_version=self.VERSION,model_version=supplier.assembly.client.versions['model'])
        self.worker=ContractorPlanningResultWorker(store=supplier.assembly.client.tasks,snapshots=supplier.snapshots,registry=supplier.registry,
            client_version=self.VERSION,model_version=supplier.assembly.client.versions['model'],validate_invocation=self.validate_invocation,
            validate_wait=supplier.validate_wait)
        self._components=(self.assembler,self.worker,supplier.assembly.client.tasks,supplier.registry,supplier.organizations)

    def _check_file(self):
        if set(self.settings)!={'file_path','file_sha256'} or hashlib.sha256(Path(self.settings['file_path']).read_bytes()).hexdigest()!=self.settings['file_sha256']:
            raise TaskConflict('Independent follow-up inputs changed pinned bytes')

    def check(self):
        self._check_file();self.supplier._check()
        if (task_digest(self.plans)!=self._plans_sha or (self.assembler,self.worker,self.worker.store,self.worker.registry,self.assembler.organizations)!=self._components
                or self.supplier.assembly.client.continuation_dispatcher!=self):raise TaskConflict('Follow-up changed original components or binding')

    def sources(self,plan,row):
        proof=authenticate_failure(self.supplier,row);scope=proof['scope']
        if (plan['organization_id'],plan['project_id'],plan['tick'])!=(scope['contractor_id'],scope['project_id'],scope['tick']):
            raise TaskConflict('Follow-up borrowed another failure selector')
        observed={'trigger':'own_committed_supplier_selection_failed','event_id':row['event_id'],'event_sha256':proof['event_sha256'],
            'received':row,'scope':scope,'native_proposal_sha256':task_digest(proof['original_native_proposal']['output']),
            'native_final_sha256':task_digest(proof['original_native_final']['output']),'boundary':self.boundary()}
        objects=deepcopy(plan['objects']);evidence_binding(objects,plan['native_evidence_ref'],observed)
        # Unused commercial views are explicitly not supported by an accepted quote.
        for r in objects:
            if r['ref']['kind']=='Evidence' and r['value'].get('content_hash') is None:
                evidence_binding(objects,r['ref'],{'source':'not_an_accepted_quote','failure_event_id':row['event_id'],'scope':scope})
        return objects,observed,proof

    def project(self,*,context,organization_id,grants):
        self.check();plan,row=self._bound[task_digest(context.model_dump(mode='json'))]
        if organization_id!=plan['organization_id']:raise TaskConflict('Follow-up disclosed another organization')
        objects,_,_=self.sources(plan,row)
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21','state_version':self.VERSION+':'+task_digest(objects),
            'read_token':context.read_token,'business_time':context.business_time.model_dump(mode='json'),'organization_id':organization_id,'objects':objects}

    def validate_invocation(self,task,prepared):
        self.check();plan,row=self._bound[prepared.context_sha256];self.sources(plan,row)
        if prepared.context.model_dump(mode='json')!=plan['context']:raise TaskConflict('Follow-up worker changed exact invocation')
        prepared.reading.recheck();return True

    def __call__(self,*,run_id,organization_id):
        if self.supplier.assembly.client.organization_roles.get(organization_id)!='Contractor':return
        with self.supplier.read_guard():
            self.check();client=self.supplier.assembly.client
            if run_id!=client.run_id:raise TaskConflict('Follow-up dispatcher changed run')
            for row in client.inbox.for_organization(run_id=run_id,organization_id=organization_id):
                if row['payload']['event_type']!='supplier_selection_failed':continue
                key=self.PREFIX+task_digest([run_id,organization_id,row['event_id']]);old=[r for r in self.records() if r['key']==key]
                if old:
                    if old[0]['state']!='formed':raise TaskConflict('Unknown failed follow-up must not be replayed')
                    saved=checked_result(self.worker,TaskIdentity(**old[0]['identity']))
                    if saved['result_sha256']!=old[0]['result_sha256']:raise TaskConflict('Saved follow-up changed')
                    continue
                payload=row['payload'];plan,=[p for p in self.plans if (p['organization_id'],p['project_id'],p['tick'])==
                    (organization_id,payload['project_id'],payload['tick'])]
                objects,observed,proof=self.sources(plan,row);context=ActionContext.model_validate(plan['context'])
                if context.business_time.offset!=self.supplier.assembly.engine.current_tick:raise TaskConflict('Unstarted historical follow-up needs explicit current authorization')
                record=self.supplier._save(key,{'key':key,'state':'preparing','context':plan['context'],'action_input':plan['action_input'],
                    'source_sha256':task_digest(objects),'observed':observed,'proof':proof})
                self._bound[task_digest(plan['context'])]=(plan,deepcopy(row));prepared=self.assembler.build(context,**plan['action_input'])
                for r in objects:prepared.reading.resolve(Reference.model_validate(r['ref']))
                from dataclasses import replace
                prepared=replace(prepared,reading_sha256=task_digest(prepared.reading.evidence()))
                identity=self.worker.register(prepared,request_id=key+':CONTRACTOR-A05');record['identity']=identity.as_dict();self.supplier._save(key,record)
                self.worker.execute(identity,prepared);saved=checked_result(self.worker,identity)
                if saved['result']['payload']['choice']!='request_quote':raise TaskConflict('Failure follow-up must not become supply acceptance')
                record.update(state='formed',result_sha256=saved['result_sha256']);self.supplier._save(key,record)

    def records(self):return self.supplier._records(prefix=self.PREFIX)
    def evidence(self):
        with self.supplier.read_guard():
            self.check();return {'version':self.VERSION,'requests':self.records(),'boundary':self.boundary()}


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Failure follow-up development requires explicit offline mode')
    settings=GbaModuleHostConfiguration.model_validate(configuration).settings
    if set(settings)!={'supply','followup'}:raise ValueError('Explicit supply and follow-up sources required')
    assembly.client.native_routes.attach(assembly)
    supplier=SupplierOrderNativeApplication(assembly=assembly,settings=settings['supply'],install=False)
    followup=ProcurementFailureFollowup(supplier=supplier,settings=settings['followup'])
    if assembly.client.continuation_dispatcher is not None:raise TaskConflict('Existing continuation dispatcher requires explicit composition')
    assembly.client.continuation_dispatcher=followup;supplier.install()
    def evidence():return {'supplier':supplier.evidence(),'failure_followup':followup.evidence()}
    return GbaModuleHostExtension(version=followup.VERSION,evidence=evidence,close=supplier.authority.close,writer_guard=supplier.read_guard)
