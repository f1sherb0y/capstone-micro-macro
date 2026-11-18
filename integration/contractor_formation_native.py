"""Original Contractor A04 for native pre-signature terms and negotiation."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from pydantic import Field

from integration.bank_financing_private import checked_result
from integration.bindings.gba_v1_progress_payments import read_own_progress_payments
from integration.bindings.gba_v1_construction_suspensions import read_own_construction_suspensions
from integration.contractor_formation_actions import ContractorFormationActionAssembler
from integration.contractor_formation_results import ContractorFormationResultWorker
from integration.contractor_formation_native_sources import formation_scope,formation_sources,prior_negotiations
from integration.owner_award_native import OwnerAwardNativeApplication,OwnerAwardNativeSettings
from integration.contractor_tender_formation_projection import OriginalTenderProjection
from integration.contractor_tender_authority_runtime import TenderAuthorityRuntimeSettings,build_authority_runtime
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension,module_client_implementation,module_factory_descriptor
from src.actions.contracts.common import StrictRecord,TextId,ActionContext,EvidenceRecord,Measured,ref_type
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict,TaskIdentity,canonical,task_digest
from src.methods.models import Digest


class ContractorFormationPlan(StrictRecord):
    organization_id: TextId
    project_id: TextId
    tick: int=Field(ge=1)
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    history_revision_change_refs: list[ref_type('ContractChangeRequest')]=Field(default_factory=list)
    max_prior_accept_terms: int | None=Field(default=None,ge=1)
    max_prior_owner_payment_delays: int | None=Field(default=None,ge=1,strict=True)
    max_prior_construction_suspensions: int | None=Field(default=None,ge=1,strict=True)
    original_tender_request_id: TextId | None=None
    original_tender_projection: OriginalTenderProjection | None=None
    native_contract_currency: TextId
    utility: Measured
    probability: Measured


class ContractorFormationNativeSettings(StrictRecord):
    version: TextId
    policy_version: TextId
    authority: TenderAuthorityRuntimeSettings
    file_path: TextId
    file_sha256: Digest
    owner: OwnerAwardNativeSettings | None=None


class ContractorFormationNativeApplication:
    VERSION='gba-v1-contractor-formation.v6'
    PREFIX='contractor_formation_native_request:'

    def __init__(self,*,assembly,settings,authority=None,install=True):
        self.assembly=assembly;self.settings=ContractorFormationNativeSettings.model_validate(settings).model_copy(deep=True)
        self._check_file();self.document=json.loads(Path(self.settings.file_path).read_bytes())
        if (set(self.document)!={'schema_version','run_id','plans'}
                or self.document['schema_version']!='contractor-formation-input.v1'
                or self.document['run_id']!=assembly.client.run_id):
            raise TaskConflict('Contract formation needs its explicit original initial source composition')
        self.plans=[ContractorFormationPlan.model_validate(p) for p in self.document['plans']]
        keys=[(p.organization_id,p.project_id,p.tick,self.declared_price(p)) for p in self.plans]
        if not keys or len(set(keys))!=len(keys):raise TaskConflict('Contract formation repeats its original plan')
        self._document_sha=task_digest(self.document);self._settings_sha=task_digest(self.settings.model_dump(mode='json'))
        self._plans_sha=task_digest([p.model_dump(mode='json') for p in self.plans]);self._source_pins=self.source_descriptors()
        self._owns_authority=authority is None
        self.authority=authority or build_authority_runtime(assembly=assembly,settings=self.settings.authority)
        self.registry,self.organizations=self.authority.registry,self.authority.organizations
        self.read_guard=self.authority.read_guard;self.snapshots=InvocationSnapshotStore(assembly.client.tasks)
        self._bound={};self._implementation=None;client=assembly.client;routes=client.native_routes
        self._other_decision=client.decision_handler;self._native_settings=task_digest(routes.settings.model_dump(mode='json'))
        try:
            if (self.authority.assembly is not assembly or self.authority.settings!=self.settings.authority
                    or not routes.settings.micro_contractor_formation_scope
                    or ('Contractor','decide_contract_terms') in routes._proposals
                    or ('Contractor','contract_negotiation') in routes._decisions):
                raise TaskConflict('Contract formation needs the same authority and exclusive declared native routes')
            for p in self.plans:
                if (p.context.run_id!=client.run_id or p.context.contract_ref.id!='CONTRACTOR-A04'
                        or p.context.execution_mode=='offline_fixture' or p.context.scope.ref.id!=p.project_id
                        or p.context.scope.kind!='project' or p.context.business_time.offset!=p.tick
                        or client.organization_roles.get(p.organization_id)!='Contractor'
                        or self.organizations.get(p.organization_id).actor_id!=p.context.actor_id
                        or p.native_contract_currency!='HKD'
                        or len({task_digest(r['ref']) for r in p.objects})!=len(p.objects)):
                    raise TaskConflict('Contract formation changes its declared original actor, action, project, clock or currency')
            self.assembler=ContractorFormationActionAssembler(registry=self.registry,organizations=self.organizations,
                provider=self,macro_version='gba-public-2026-08-21',source_mode='formal',
                policy_version=self.settings.policy_version,model_version=client.versions['model'])
            self.worker=ContractorFormationResultWorker(store=client.tasks,snapshots=self.snapshots,registry=self.registry,
                client_version=self.VERSION,model_version=client.versions['model'],validate_invocation=self.validate_invocation,
                validate_wait=self.validate_wait)
            self.owner=(OwnerAwardNativeApplication(parent=self,settings=self.settings.owner)
                if self.settings.owner is not None else None)
            self._owner_component=self.owner
            if install:self.install()
        except Exception:
            if self._owns_authority:self.authority.close()
            raise

    @staticmethod
    def source_descriptors():
        from integration.formation_native_outcome_query import query_formation_outcome, _original_result
        from integration.contractor_selected_tender_sources import validate_formation_original_bid
        from integration.contractor_tender_formation_projection import project_original_tender_formation
        return {name:module_factory_descriptor(function,'contractor-formation-sources.v2') for name,function in
            [('query',query_formation_outcome),('query_original_result',_original_result),
             ('scope',formation_scope),('prepare',formation_sources),('history',prior_negotiations),
             ('progress_payments',read_own_progress_payments),('construction_suspensions',read_own_construction_suspensions),
             ('original_tender',validate_formation_original_bid),('original_tender_projection',project_original_tender_formation)]}

    def proposal_bindings(self):
        return {('Contractor','decide_contract_terms'):self.propose,
            **(self.owner.proposal_bindings() if self.owner is not None else {})}

    def seal_client_binding(self):
        client=self.assembly.client
        with client._lock:
            if (self._implementation is not None or client._calls or client._request_hashes
                    or client.binding_installation_blocked()
                    or any(client.proposal_handlers.get(key)!=handler for key,handler in self.proposal_bindings().items())):
                raise TaskConflict('Contract formation must be sealed once after complete routing and before business')
            self._implementation=module_client_implementation(client)

    def install(self):
        client=self.assembly.client
        with client._lock:
            if self._implementation is not None or client._calls or client._request_hashes:
                raise TaskConflict('Contract formation installation must precede all business and sealing')
            for (role,operation),handler in self.proposal_bindings().items():
                client.bind_proposal_handler(role=role,operation=operation,handler=handler,client_version=self.VERSION+':'+role)
            client.decision_handler=self.decide;self.seal_client_binding()

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest()!=self.settings.file_sha256:
            raise TaskConflict('Contract formation initial independent source bytes changed')

    def _check(self):
        self.assembly._validate_components();self._check_file()
        if (task_digest(self.document)!=self._document_sha or task_digest(self.settings.model_dump(mode='json'))!=self._settings_sha
                or self.owner is not self._owner_component
                or task_digest([p.model_dump(mode='json') for p in self.plans])!=self._plans_sha
                or self._implementation is None or module_client_implementation(self.assembly.client)!=self._implementation
                or task_digest(self.assembly.client.native_routes.settings.model_dump(mode='json'))!=self._native_settings
                or self.source_descriptors()!=self._source_pins or self.worker.store is not self.assembly.client.tasks
                or self.worker.registry is not self.registry or self.assembler.registry is not self.registry
                or self.assembler.organizations is not self.organizations or self.authority.assembly is not self.assembly
                or self.authority.settings!=self.settings.authority or self.authority.registry is not self.registry
                or self.authority.organizations is not self.organizations or self.authority.read_guard!=self.read_guard):
            raise TaskConflict('Contract formation changes its original sources, workers, authority or sealed handlers')
        if self.owner is not None:self.owner._check()

    @staticmethod
    def declared_price(plan):
        terms,=[r['value'] for r in plan.objects if r['ref']==plan.action_input['terms_ref']]
        return Decimal(terms['price']['value'])

    def current(self,request):
        self._check();scope=formation_scope(self.assembly,request,purpose='propose')
        project=self.assembly.engine.projects[scope['project_id']]
        matches=[p for p in self.plans if (p.organization_id,p.project_id,p.tick)==
            (scope['contractor_id'],scope['project_id'],scope['tick'])
            and self.declared_price(p)==Decimal(str(project.contract_sum))]
        if len(matches)!=1:raise TaskConflict('Actual contract terms request lacks an exact independent plan')
        plan=matches[0];self.organizations.grants(plan.context,'CONTRACTOR-A04','Contractor')
        terms,=[r['value'] for r in plan.objects if r['ref']==plan.action_input['terms_ref']]
        project=self.assembly.engine.projects[plan.project_id]
        if (terms['contractor_id']!=plan.organization_id or terms['client_id']!=project.owner_id
                or terms['price']['currency']!=plan.native_contract_currency
                or Decimal(terms['price']['value'])!=Decimal(str(project.contract_sum))
                or terms['work_window']['end']['offset']-terms['work_window']['start']['offset']!=project.performance.planned_duration):
            raise TaskConflict('Contract terms change actual native parties, declared price/currency mapping or programme duration')
        return plan,scope

    def project(self,*,context,organization_id,grants):
        bound=self._bound.get(task_digest(context.model_dump(mode='json')))
        if bound is None:raise TaskConflict('Contract terms have no original current invocation')
        plan,request=bound;self.current(request);objects,_=formation_sources(self,plan,request)
        if context!=plan.context or organization_id!=plan.organization_id:
            raise TaskConflict('Contract terms substitute an original own source reading')
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21','state_version':'native-contract-terms:'+task_digest(objects),
            'read_token':context.read_token,'business_time':context.business_time.model_dump(mode='json'),
            'organization_id':organization_id,'objects':objects}

    def validate_invocation(self,row,prepared):
        plan,request=self._bound[prepared.context_sha256];self.current(request)
        if (prepared.context!=plan.context or row['identity']['organization_id']!=plan.organization_id
                or prepared.runner.registry is not self.registry):raise TaskConflict('Contract terms worker changes its original invocation')
        prepared.reading.recheck();return True

    def validate_wait(self,*args,**kwargs):
        raise TaskConflict('Unresolved contract terms need explicit source diagnosis and continuation')

    def query_native_outcome(self,identity,*,organization_id,tick):
        from integration.formation_native_outcome_query import query_formation_outcome
        return query_formation_outcome(self,identity,organization_id=organization_id,tick=tick)

    def records(self):
        with self.assembly.client.tasks._lock:
            rows=[json.loads(v) for v, in self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key LIKE ?',(self.PREFIX+'%',))]
        if any(r['record_sha256']!=task_digest({k:v for k,v in r.items() if k!='record_sha256'}) for r in rows):
            raise TaskConflict('Contract formation original technical request evidence changed')
        return rows

    def save(self,key,record):
        record=deepcopy(record);record['record_sha256']=task_digest({k:v for k,v in record.items() if k!='record_sha256'})
        with self.assembly.client.tasks._transaction():
            self.assembly.client.tasks._db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(key,canonical(record)))
        return record

    @staticmethod
    def summary(saved):
        choice=saved['result']['payload']['choice']
        if choice=='accept':return True,'accept_terms'
        if choice=='revise':return False,'request_revision'
        raise TaskConflict('Contract rejection or unresolved result has no equivalent native negotiation posture in this bridge')

    def propose(self,request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        with self.read_guard():
            plan,scope=self.current(request);key=self.PREFIX+task_digest([self.assembly.client.simulation_id,scope,request.request_id])
            if any(r['key']==key for r in self.records()):raise TaskConflict('Contract terms already claimed; inspect original transport')
            record=self.save(key,{'key':key,'state':'preparing','scope':scope,'native_request':request.model_dump(mode='json')})
            self._bound[task_digest(plan.context.model_dump(mode='json'))]=(plan,request.model_copy(deep=True))
            objects,observed=formation_sources(self,plan,request);prepared=self.assembler.build(plan.context,**deepcopy(plan.action_input))
            identity=self.worker.register(prepared,request_id=key+':CONTRACTOR-A04')
            record.update(identity=identity.as_dict(),source_sha256=task_digest(objects),observed=observed);record=self.save(key,record)
            self.worker.execute(identity,prepared);saved=checked_result(self.worker,identity);accepted,action=self.summary(saved)
            for metric,unit in ((plan.utility,'score'),(plan.probability,'probability')):
                if (metric.unit!=unit or not 0<=Decimal(metric.value)<=1
                        or not isinstance(prepared.reading.resolve(metric.basis_ref),EvidenceRecord)):
                    raise TaskConflict('Contract terms indicators require sourced bounded values')
            response=AgentProposalResponseV1(request_id=request.request_id,action_type=action,accepted=accepted,
                utility=float(plan.utility.value),probability=float(plan.probability.value),reason=saved['result']['payload']['note'],
                data={'stage_state_mutated':False},factors={'micro_action_id':'CONTRACTOR-A04','micro_task_key':identity.key,
                    'micro_result_sha256':saved['result_sha256'],'native_formation_scope':scope})
            record.update(state='formed',result_sha256=saved['result_sha256'],proposal_response_sha256=task_digest(response.model_dump(mode='json')))
            self.save(key,record);return response

    def decide(self,request):
        if self.owner is not None and (request.agent.role,request.decision_type)==('Owner','owner_contract_award'):
            return self.owner.decide(request)
        if (request.agent.role,request.decision_type)!=('Contractor','contract_negotiation'):return self._other_decision(request)
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1,AgentDecisionResponseV1
        from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
        with self.read_guard():
            self._check();scope=formation_scope(self.assembly,request,purpose='decide')
            records=[r for r in self.records() if r['state']=='formed' and r['scope']==scope]
            if len(records)!=1:raise TaskConflict('Contract negotiation lacks its one original terms result')
            record=records[0];original=AgentProposalRequestV1.model_validate(record['native_request']);plan,_=self.current(original)
            saved=checked_result(self.worker,TaskIdentity(**record['identity']));objects,observed=formation_sources(self,plan,original)
            accepted,action=self.summary(saved);tasks=self.assembly.client.tasks.for_organization(run_id=plan.context.run_id,organization_id=plan.organization_id)
            proposals=[t['output'] for t in tasks if t['state']=='output_formed' and t['identity']['purpose']=='propose'
                and t['identity']['action_id']=='decide_contract_terms' and t['output'].get('factors',{}).get('native_formation_scope')==scope]
            if len(proposals)!=1:raise TaskConflict('Contract negotiation lost the original transported terms proposal')
            proposal=proposals[0]
            if (record['result_sha256']!=saved['result_sha256'] or record['source_sha256']!=task_digest(objects)
                    or record['observed']!=observed or record['proposal_response_sha256']!=task_digest(proposal)
                    or proposal['action_type']!=action or proposal['accepted']!=accepted
                    or action not in request.constraints.allowed_actions or request.choice_contract.output_field is not None
                    or request.candidate_options):raise TaskConflict('Contract negotiation changes its original result, source or bounded action')
            response=AgentDecisionResponseV1(request_id=request.request_id,agent_id=plan.organization_id,action_type=action,
                decision=accepted,reason=proposal['reason'],data={**proposal['factors'],'stage_state_mutated':False,
                    'proposal_response_sha256':record['proposal_response_sha256']})
            ExternalAgentDecisionProvider._validated_action(request,response);return response

    def evidence(self):
        self._check();return {'version':self.VERSION,'source_file_sha256':self.settings.file_sha256,'requests':self.records(),
            'authority':self.authority.evidence(),'native_routes':self.assembly.client.native_routes.evidence(),
            'owner_award':self.owner.evidence() if self.owner is not None else None,
            'limits':'Original A04 acceptance/revision mapped to native bounded negotiation only. No detailed signature, crew reservation, payment or effective contract is inferred.'}


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Explicit synthetic Contractor terms composition requires offline mode')
    assembly.client.native_routes.attach(assembly)
    config=GbaModuleHostConfiguration.model_validate(configuration)
    app=ContractorFormationNativeApplication(assembly=assembly,settings=config.settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
