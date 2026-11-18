"""Original professional A01 decides bounded monthly outreach; native scheduler executes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Literal
from pydantic import Field

from integration.professional_opportunity_native import COMPONENTS
from integration.contractor_tender_authority_runtime import TenderAuthorityRuntimeSettings,build_authority_runtime
from integration.bank_financing_private import checked_result,evidence_binding
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension,module_client_implementation,module_factory_descriptor
from src.actions.contracts.common import ActionContext,StrictRecord,TextId,ref_type
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest,canonical

OPERATIONS={'Architect':'seek_design_commission','Engineer':'review_technical_market','QS':'seek_consulting_work'}


class ProfessionalMonthlyPlan(StrictRecord):
    organization_id: TextId
    role: Literal['Architect','Engineer','QS']
    tick: int = Field(ge=1)
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    observation_ref: ref_type('OutreachObservation')


class ProfessionalMonthlySettings(StrictRecord):
    authority: TenderAuthorityRuntimeSettings
    file_path: TextId
    file_sha256: TextId


class ProfessionalMonthlyApplication:
    VERSION='professional-monthly-outreach.v1'
    PREFIX='professional_monthly_request:'
    COMPONENTS=COMPONENTS
    OPERATIONS=OPERATIONS
    PLAN_TYPE=ProfessionalMonthlyPlan
    INPUT_SCHEMA='professional-monthly-input.v1'
    PARTICIPATION_CHOICE='express_interest'
    COMPLETED_CHOICES={'express_interest','ignore','decline'}
    SCOPE_KEY='native_professional_monthly_scope'
    ACTION_NUMBER='A01'
    LABEL='Original professional outreach decision'

    def participates(self,saved):
        return saved['result']['payload']['choice']==self.PARTICIPATION_CHOICE

    def result_note(self,saved):
        return saved['result']['payload']['note']

    def operation(self,saved,role):
        return self.OPERATIONS[role]

    def action_id(self,role):
        return role.upper()+'-'+self.ACTION_NUMBER

    def __init__(self,*,assembly,settings,authority=None,install=True):
        self.assembly=assembly;self.settings=ProfessionalMonthlySettings.model_validate(settings).model_copy(deep=True)
        self._check_file();document=json.loads(Path(self.settings.file_path).read_bytes())
        if set(document)!={'schema_version','run_id','plans'} or document['schema_version']!=self.INPUT_SCHEMA or document['run_id']!=assembly.client.run_id:
            raise TaskConflict('Monthly professional input requires its pinned original run')
        self.plans=[self.PLAN_TYPE.model_validate(p) for p in document['plans']]
        if not self.plans or len({(p.organization_id,p.tick) for p in self.plans})!=len(self.plans):
            raise TaskConflict('Monthly professional plans must be unique by own organization/time')
        self.authority=authority or build_authority_runtime(assembly=assembly,settings=self.settings.authority)
        if self.authority.assembly is not assembly or self.authority.settings!=self.settings.authority:
            raise TaskConflict('Monthly application requires the exact shared assembly and declared authority')
        self.read_guard=self.authority.read_guard;self.registry=self.authority.registry;self.organizations=self.authority.organizations
        self.snapshots=InvocationSnapshotStore(assembly.client.tasks);self._bound={};self.assemblers={};self.workers={}
        self._plans_sha=task_digest([p.model_dump(mode='json') for p in self.plans]);self._settings_sha=task_digest(self.settings.model_dump(mode='json'))
        self._native_sha=task_digest(assembly.client.native_routes.settings.model_dump(mode='json'))
        self._client_implementation=None
        for role,(assembler,worker) in self.COMPONENTS.items():
            for operation,pool in [('decide_monthly_operation',assembly.client.native_routes._proposals),('monthly_enterprise_operation',assembly.client.native_routes._decisions)]:
                if (role,operation) in pool:raise TaskConflict('Monthly micro and native routes must be exclusive')
            self.assemblers[role]=assembler(registry=self.registry,organizations=self.organizations,provider=self,
                macro_version='gba-public-2026-08-21',source_mode='formal',policy_version=self.VERSION,model_version=assembly.client.versions['model'])
            self.workers[role]=self.build_worker(role,worker)
        for p in self.plans:
            if (p.context.run_id!=document['run_id'] or p.context.actor_id!=self.organizations.get(p.organization_id).actor_id
                    or assembly.client.organization_roles.get(p.organization_id)!=p.role
                    or p.context.contract_ref.id!=self.action_id(p.role) or p.context.scope.kind!='organization'
                    or p.context.scope.ref.id!=p.organization_id or p.context.business_time.offset!=p.tick
                    or p.context.execution_mode=='offline_fixture'):
                raise TaskConflict('Monthly professional plan changes original role/action/current own scope')
        self._other_decision=assembly.client.decision_handler
        if install:self.install()

    def proposal_bindings(self):
        return {(role,'decide_monthly_operation'):self.propose for role in self.COMPONENTS}

    def install(self):
        client=self.assembly.client
        with client._lock:
            if client._calls or client._request_hashes or client.binding_installation_blocked():raise TaskConflict('Install monthly routes before execution')
            for role in self.COMPONENTS:client.bind_proposal_handler(role=role,operation='decide_monthly_operation',handler=self.propose,client_version=self.VERSION+':'+role)
            client.decision_handler=self.decide
            self.seal_client_binding()

    def seal_client_binding(self):
        client=self.assembly.client
        with client._lock:
            if (self._client_implementation is not None or client._calls or client._request_hashes
                    or client.binding_installation_blocked()
                    or any(client.proposal_handlers.get(k)!=v for k,v in self.proposal_bindings().items())):
                raise TaskConflict('Seal original monthly bindings once before any execution')
            self._client_implementation=module_client_implementation(client)

    def build_worker(self,role,worker):
        return worker(store=self.assembly.client.tasks,snapshots=self.snapshots,registry=self.registry,
            client_version=self.VERSION,model_version=self.assembly.client.versions['model'],
            validate_invocation=self.validate_invocation,validate_wait=self.validate_wait)

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest()!=self.settings.file_sha256:
            raise TaskConflict('Monthly professional source bytes changed')

    def check(self):
        self.assembly._validate_components();self._check_file()
        if (self.authority.assembly is not self.assembly or self.authority.settings!=self.settings.authority
                or self._settings_sha!=task_digest(self.settings.model_dump(mode='json'))
                or self._plans_sha!=task_digest([p.model_dump(mode='json') for p in self.plans])
                or self._native_sha!=task_digest(self.assembly.client.native_routes.settings.model_dump(mode='json'))
                or self._client_implementation!=module_client_implementation(self.assembly.client)):
            raise TaskConflict('Monthly professional settings, source plans or original bindings changed')
        for role in self.COMPONENTS:
            views=self.assemblers[role]._views
            view_providers=list(views.values()) if isinstance(views,dict) else [views]
            if (self.workers[role].store is not self.assembly.client.tasks or self.workers[role].snapshots is not self.snapshots
                    or self.workers[role].registry is not self.registry or not view_providers
                    or any(view.provider is not self for view in view_providers)):
                raise TaskConflict('Monthly professional worker lost its shared original runtime')

    def scope(self,request,*,purpose):
        self.check();engine=self.assembly.engine;org=request.agent.agent_id;role=request.agent.role
        if role not in self.COMPONENTS or self.assembly.client.organization_roles.get(org)!=role:
            raise TaskConflict('Monthly professional request substitutes own role or organization')
        scope={'organization_id':org,'role':role,'tick':engine.current_tick}
        environment=engine.macro_environment.model_dump(mode='json')
        if purpose=='propose':
            if request.operation!='decide_monthly_operation' or request.inputs!={'macro_environment':environment}:
                raise TaskConflict('Monthly professional proposal changes actual current macro input')
        elif (request.decision_type!='monthly_enterprise_operation' or request.tick!=scope['tick']
                or request.project_id is not None or request.environment!=environment
                or request.decision_support.get('decision_factors',{}).get(self.SCOPE_KEY)!=scope):
            raise TaskConflict('Monthly professional final changes original proposal scope')
        return scope

    def records(self):
        with self.assembly.client.tasks._lock:
            rows=[json.loads(v) for v, in self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key LIKE ?',(self.PREFIX+'%',))]
        if any(r['record_sha256']!=task_digest({k:v for k,v in r.items() if k!='record_sha256'}) for r in rows):
            raise TaskConflict('Monthly professional original journal changed')
        return rows

    def _save(self,record):
        record={k:v for k,v in record.items() if k!='record_sha256'};record['record_sha256']=task_digest(record)
        with self.assembly.client.tasks._transaction():self.assembly.client.tasks._db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(record['key'],canonical(record)))
        return record

    def history(self,org,tick):
        rows=self.records();tasks=self.assembly.client.tasks.for_organization(run_id=self.assembly.client.run_id,organization_id=org);history=[]
        for event in self.assembly.engine.events.events:
            if event.event_type!='agent_operation' or event.agent_id!=org or event.tick>=tick:continue
            parents=[r for r in rows if r['scope']['organization_id']==org and r['scope']['tick']==event.tick]
            if not parents:continue
            if len(parents)!=1:raise TaskConflict('Monthly event has nonunique micro origin')
            r=parents[0];i=TaskIdentity(**r['identity']);saved=checked_result(self.workers[i.role],i)
            proposals=[t['output'] for t in tasks if t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
                and t['state']=='output_formed' and t['output'].get('factors',{}).get('micro_task_key')==i.key]
            finals=[t['output'] for t in tasks if t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
                and t['state']=='output_formed' and t['output'].get('data',{}).get('micro_task_key')==i.key]
            if len(proposals)!=1 or len(finals)!=1:raise TaskConflict('Original monthly history lost proposal or final')
            proposal,final=proposals[0],finals[0];participate=self.participates(saved)
            operation=self.operation(saved,i.role)
            expected=operation if participate else 'maintain_operations'
            if (event.data['operation']!=expected or event.description!=proposal['data']['description']
                    or proposal['accepted'] is not True or final['decision']!=participate
                    or not (final['action_type']==proposal['action_type']==operation)
                    or not (final['data']['micro_result_sha256']==r['result_sha256']==saved['result_sha256'])
                    or r['proposal_response_sha256']!=task_digest(proposal) or final['data']['proposal_response_sha256']!=task_digest(proposal)):
                raise TaskConflict('Original monthly history differs from actual micro result and native execution')
            raw=event.model_dump(mode='json');history.append({'event_id':event.event_id,'tick':event.tick,
                'operation':expected,'source_event_sha256':task_digest(raw),'micro_identity':i.as_dict(),
                'micro_result_sha256':saved['result_sha256'],'participated':participate})
        return history

    def sources(self,plan,request):
        scope=self.scope(request,purpose='propose');history=self.history(plan.organization_id,plan.tick)
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'macro_environment':deepcopy(request.inputs['macro_environment']),'prior_own_monthly_outcomes':history}
        objects=deepcopy(plan.objects);evidence_binding(objects,plan.native_evidence_ref.model_dump(mode='json'),observed)
        observation,=[r['value'] for r in objects if r['ref']==plan.observation_ref.model_dump(mode='json')]
        if observation['market_demand'] is not None or observation['prior_outreach_count'] is not None:
            raise TaskConflict('Monthly observation must be originally unbound, not a prefilled decision')
        observation['market_demand']={'value':str(request.inputs['macro_environment']['market_demand_index']),'unit':'index','basis_ref':plan.native_evidence_ref.model_dump(mode='json')}
        observation['prior_outreach_count']=sum(h['participated'] for h in history)
        return objects,observed

    def project(self,*,context,organization_id,grants):
        plan,request=self._bound[task_digest(context.model_dump(mode='json'))]
        if context!=plan.context or organization_id!=plan.organization_id:raise TaskConflict('Monthly source reading substitutes original own plan')
        objects,_=self.sources(plan,request)
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21','state_version':'professional-monthly:'+task_digest(objects),
            'read_token':context.read_token,'business_time':context.business_time.model_dump(mode='json'),'organization_id':organization_id,'objects':objects}

    def validate_invocation(self,row,prepared):
        plan,request=self._bound[prepared.context_sha256];self.scope(request,purpose='propose')
        if prepared.context!=plan.context or row['identity']['organization_id']!=plan.organization_id:raise TaskConflict('Monthly worker changes original request')
        prepared.reading.recheck();return True

    def validate_wait(self,*args,**kwargs):raise TaskConflict('Monthly original professional result unresolved; preserve journal, never use fallback')

    def propose(self,request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        with self.read_guard():
            scope=self.scope(request,purpose='propose');matches=[p for p in self.plans if (p.organization_id,p.tick)==(scope['organization_id'],scope['tick'])]
            if len(matches)!=1:raise TaskConflict('Monthly professional request lacks exact original source plan')
            plan=matches[0];key=self.PREFIX+task_digest([self.assembly.client.run_id,scope,request.request_id])
            if any(r['key']==key for r in self.records()):raise TaskConflict('Monthly professional request already claimed; no replay')
            objects,observed=self.sources(plan,request)
            record=self._save({'key':key,'scope':scope,'state':'preparing','native_request':request.model_dump(mode='json'),
                'context':plan.context.model_dump(mode='json'),'action_input':plan.action_input,'observed':observed,'source_sha256':task_digest(objects)})
            self._bound[task_digest(record['context'])]=(plan,request.model_copy(deep=True))
            prepared=self.assemblers[plan.role].build(plan.context,**deepcopy(plan.action_input));worker=self.workers[plan.role]
            identity=worker.register(prepared,request_id=key+':'+self.action_id(plan.role));record['identity']=identity.as_dict();self._save(record)
            worker.execute(identity,prepared);saved=checked_result(worker,identity);choice=saved['result']['payload']['choice']
            if choice not in self.COMPLETED_CHOICES:raise TaskConflict('Monthly outreach has an unresolved original professional choice')
            participate=self.participates(saved);note=self.result_note(saved)
            # Frozen monthly proposal contracts accept only positive candidate
            # pairs. The original final-decision interface carries A01 refusal;
            # no rule fallback or invalid negative proposal is submitted.
            response=AgentProposalResponseV1(request_id=request.request_id,action_type=self.operation(saved,plan.role),accepted=True,
                utility=0.7 if participate else 0.0,probability=1.0,reason=note,data={'label':self.LABEL,'description':note},
                factors={'micro_task_key':identity.key,'micro_result_sha256':saved['result_sha256'],'micro_action_id':identity.action_id,
                    'micro_participation':participate,self.SCOPE_KEY:scope})
            record.update(state='formed',result_sha256=saved['result_sha256'],proposal_response_sha256=task_digest(response.model_dump(mode='json')));self._save(record)
            return response

    def decide(self,request):
        if request.agent.role not in self.COMPONENTS or request.decision_type!='monthly_enterprise_operation':return self._other_decision(request)
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1,AgentDecisionResponseV1
        from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
        with self.read_guard():
            scope=self.scope(request,purpose='decide');record,=[r for r in self.records() if r['scope']==scope and r['state']=='formed']
            plan,=[p for p in self.plans if (p.organization_id,p.tick)==(scope['organization_id'],scope['tick'])]
            objects,observed=self.sources(plan,AgentProposalRequestV1.model_validate(record['native_request']))
            identity=TaskIdentity(**record['identity']);saved=checked_result(self.workers[identity.role],identity)
            tasks=self.assembly.client.tasks.for_organization(run_id=self.assembly.client.run_id,organization_id=scope['organization_id'])
            proposal,=[t['output'] for t in tasks if t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
                and t['state']=='output_formed' and t['output'].get('factors',{}).get('micro_task_key')==identity.key]
            participate=self.participates(saved)
            if (record['source_sha256']!=task_digest(objects) or record['observed']!=observed or record['result_sha256']!=saved['result_sha256']
                    or record['proposal_response_sha256']!=task_digest(proposal) or proposal['accepted'] is not True
                    or proposal['factors'].get('micro_participation')!=participate
                    or proposal['action_type']!=self.operation(saved,identity.role) or request.decision_support.get('decision_factors')!=proposal['factors']
                    or request.decision_support.get('accepted') is not True or request.decision_support.get('action_type')!=proposal['action_type']):
                raise TaskConflict('Monthly professional final changes saved original sources or micro judgment')
            response=AgentDecisionResponseV1(request_id=request.request_id,agent_id=scope['organization_id'],action_type=proposal['action_type'],decision=participate,
                reason=proposal['reason'],data={**proposal['factors'],'proposal_response_sha256':task_digest(proposal)})
            ExternalAgentDecisionProvider._validated_action(request,response);return response

    def evidence(self):
        with self.read_guard():
            self.check()
            return {'version':self.VERSION,'requests':self.records(),'original_global_events':[e.model_dump(mode='json') for e in self.assembly.engine.events.events],
                'authority':self.authority.evidence(),'source_implementation':module_factory_descriptor(type(self).sources,self.VERSION),
                'boundary':'Monthly background outreach only. Independent synthetic dossiers are not actual invitations, sent messages, appointments, private capacity, training, fee receipts, qualifications or cost-database updates. Native capability updates remain original normalized mechanics.'}


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Professional monthly development requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=ProfessionalMonthlyApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
