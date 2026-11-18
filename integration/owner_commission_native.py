"""Original OWN-A04 selects actual independently accepting professionals."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from integration.bank_financing_private import checked_result
from integration.owner_commission_actions import OwnerCommissionActionAssembler
from integration.owner_commission_results import OwnerCommissionResultWorker
from integration.owner_commission_native_sources import commission_sources
from integration.professional_intake_scope import professional_scope
from src.actions.contracts.common import ActionContext,DecimalString,StrictRecord,TextId,ref_type
from src.coordination.tasks import TaskConflict,TaskIdentity,canonical,task_digest
from src.methods.models import Digest


class OwnerCommissionDisclosure(StrictRecord):
    provider_id: TextId
    provider_ref: ref_type('EligibleProvider')
    offer_ref: ref_type('ServiceOffer')
    terms_ref: ref_type('ContractTerms')
    # Distinct action-specific views of the same initially declared requirement.
    deliverable_links: list[dict]
    shared_evidence_refs: list[ref_type('Evidence')]


class OwnerCommissionPlan(StrictRecord):
    organization_id: TextId
    project_id: TextId
    tick: int=Field(ge=0)
    role: Literal['Architect','Engineer','QS']
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    handoff_evidence_ref: ref_type('Evidence')
    disclosures: list[OwnerCommissionDisclosure]=Field(min_length=1)
    repeat_provider_priority_penalty: int=Field(default=0,ge=0)
    utility: DecimalString
    probability: DecimalString


class OwnerCommissionSettings(StrictRecord):
    version: TextId
    file_path: TextId
    file_sha256: Digest


class OwnerCommissionApplication:
    VERSION='gba-v1-owner-commission.v2'
    PREFIX='owner_commission_native_request:'

    def __init__(self,*,professional,settings):
        self.professional=professional;self.settings=OwnerCommissionSettings.model_validate(settings).model_copy(deep=True)
        self._check_file();doc=json.loads(Path(self.settings.file_path).read_bytes())
        if (set(doc)!={'schema_version','run_id','plans'} or doc['schema_version']!='owner-commission-input.v1'
                or doc['run_id']!=professional.assembly.client.run_id):
            raise TaskConflict('Owner commission changes its independent initial source composition')
        self.plans=[OwnerCommissionPlan.model_validate(p) for p in doc['plans']]
        keys=[(p.organization_id,p.project_id,p.tick,p.role) for p in self.plans]
        if not keys or len(set(keys))!=len(keys):raise TaskConflict('Owner commission repeats its original plans')
        for p in self.plans:
            c=p.context
            if (c.run_id!=doc['run_id'] or c.actor_id!=professional.organizations.get(p.organization_id).actor_id or c.contract_ref.id!='OWN-A04'
                    or c.scope.kind!='project' or c.scope.ref.id!=p.project_id or c.business_time.offset!=p.tick
                    or c.execution_mode=='offline_fixture' or len({task_digest(r['ref']) for r in p.objects})!=len(p.objects)
                    or len({d.provider_id for d in p.disclosures})!=len(p.disclosures)
                    or not 0<=Decimal(p.utility)<=1 or not 0<=Decimal(p.probability)<=1):
                raise TaskConflict('Owner commission changes its actual actor, scope, source identities or indicators')
        self._settings_sha=task_digest(self.settings.model_dump(mode='json'))
        self._plans_sha=task_digest([p.model_dump(mode='json') for p in self.plans]);self._bound={}
        self.assembler=OwnerCommissionActionAssembler(registry=professional.registry,organizations=professional.organizations,
            provider=self,macro_version='gba-public-2026-08-21',source_mode='formal',
            policy_version=professional.settings.policy_version,model_version=professional.assembly.client.versions['model'])
        self.worker=OwnerCommissionResultWorker(store=professional.assembly.client.tasks,snapshots=professional.snapshots,
            registry=professional.registry,client_version=self.VERSION,model_version=professional.assembly.client.versions['model'],
            validate_invocation=self.validate_invocation,validate_wait=professional.validate_wait)

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest()!=self.settings.file_sha256:
            raise TaskConflict('Owner commission independent inputs changed their pinned bytes')

    def check_components(self):
        self._check_file();p=self.professional
        if (task_digest(self.settings.model_dump(mode='json'))!=self._settings_sha
                or task_digest([v.model_dump(mode='json') for v in self.plans])!=self._plans_sha
                or self.worker.store is not p.assembly.client.tasks or self.worker.registry is not p.registry
                or self.assembler.organizations is not p.organizations):
            raise TaskConflict('Owner commission changes its original plans or shared professional runtime')

    def _current(self,request):
        self.professional._check();scope=professional_scope(self.professional.assembly,request,purpose='propose')
        if (request.agent.role,request.operation)!=('Owner','select_appointment'):
            raise TaskConflict('Owner commission requires its actual original appointment selection request')
        plans=[p for p in self.plans if (p.organization_id,p.project_id,p.tick,p.role)==
            (request.agent.agent_id,scope['project_id'],scope['tick'],scope['role'])]
        if len(plans)!=1:raise TaskConflict('Owner commission has no exact independent current plan')
        plan=plans[0]
        service,=[r['value'] for r in plan.objects if r['ref']==plan.action_input['service_scope_ref']]
        project=self.professional.assembly.engine.projects[plan.project_id]
        if service['region_id']!=project.region or service['permitted_roles']!=[plan.role]:
            raise TaskConflict('Owner commission independent service leaves the actual project region or professional role')
        if self.professional.organizations.grants(plan.context,'OWN-A04','Owner')[0].organization_id!=plan.organization_id:
            raise TaskConflict('Owner commission lost its own current procurement authority')
        return plan,scope

    def _sources(self,plan,request):
        from integration.owner_commission_native_feedback import prior_owner_commissions
        history=prior_owner_commissions(self.professional.assembly,organization_id=plan.organization_id,
            role=plan.role,tick=plan.tick,read_guard=self.professional.read_guard)
        return commission_sources(self,plan=plan,request=request,history=history)

    def project(self,*,context,organization_id,grants):
        plan,request=self._bound[task_digest(context.model_dump(mode='json'))]
        self._current(request);objects,observed=self._sources(plan,request)
        if context!=plan.context or organization_id!=plan.organization_id:
            raise TaskConflict('Owner commission substitutes the actual own source invocation')
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21',
            'state_version':'native-owner-commission:'+task_digest(objects),'read_token':context.read_token,
            'business_time':context.business_time.model_dump(mode='json'),'organization_id':organization_id,'objects':objects}

    def validate_invocation(self,row,prepared):
        plan,request=self._bound[prepared.context_sha256];self._current(request)
        if (prepared.context!=plan.context or row['identity']['organization_id']!=plan.organization_id
                or prepared.runner.registry is not self.professional.registry):
            raise TaskConflict('Owner commission worker changes its original invocation')
        prepared.reading.recheck();return True

    def records(self):
        with self.professional.assembly.client.tasks._lock:
            records=[json.loads(v) for v, in self.professional.assembly.client.tasks._db.execute(
                'SELECT value FROM metadata WHERE key LIKE ?',(self.PREFIX+'%',))]
        if any(r['record_sha256']!=task_digest({k:v for k,v in r.items() if k!='record_sha256'}) for r in records):
            raise TaskConflict('Owner commission technical evidence changed')
        return records

    def _save(self,key,record):
        r=deepcopy(record);r['record_sha256']=task_digest({k:v for k,v in r.items() if k!='record_sha256'})
        with self.professional.assembly.client.tasks._transaction():
            self.professional.assembly.client.tasks._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',(key,canonical(r)))
        return r

    @staticmethod
    def summary(plan,saved,objects,request):
        payload=saved['result']['payload'];choice=payload['choice']
        if choice=='reject_all':return False,None
        if choice!='accept':raise TaskConflict('Unresolved commission is not native selection or business rejection')
        offer,=[r['value'] for r in objects if r['ref']==payload['offer_ref']]
        provider,=[r['value'] for r in objects if r['ref']==offer['provider_ref']]
        accepted={p['agent_id'] for p,d in request.inputs['candidates'] if d['accepted']}
        if (offer['status']!='offered' or offer['terms_ref']!=payload['terms_ref']
                or provider['organization_id'] not in accepted):
            raise TaskConflict('Owner commission selects outside the independently accepting current providers')
        return True,provider['organization_id']

    def propose(self,request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        with self.professional.read_guard():
            plan,scope=self._current(request);objects,observed=self._sources(plan,request)
            key=self.PREFIX+task_digest([self.professional.assembly.client.simulation_id,scope,request.agent.agent_id,request.request_id])
            if any(r['key']==key for r in self.records()):raise TaskConflict('Owner commission already claimed; recover original transport')
            record=self._save(key,{'key':key,'state':'preparing','scope':scope,'native_request':request.model_dump(mode='json'),
                'source_sha256':task_digest(objects),'observed':observed})
            self._bound[task_digest(plan.context.model_dump(mode='json'))]=(plan,request.model_copy(deep=True))
            prepared=self.assembler.build(plan.context,**deepcopy(plan.action_input))
            identity=self.worker.register(prepared,request_id=key+':OWN-A04')
            record.update(identity=identity.as_dict());record=self._save(key,record)
            self.worker.execute(identity,prepared);saved=checked_result(self.worker,identity)
            accepted,selected=self.summary(plan,saved,objects,request)
            accepted_ids=[p['agent_id'] for p,d in request.inputs['candidates'] if d['accepted']]
            response=AgentProposalResponseV1(request_id=request.request_id,action_type='select_'+request.inputs['purpose'],
                accepted=accepted,utility=float(plan.utility),probability=float(plan.probability),reason=saved['result']['payload']['note'],
                data={'selected_agent_id':selected,'accepted_agent_ids':accepted_ids} if accepted else {},
                factors={'micro_action_id':'OWN-A04','micro_task_key':identity.key,'micro_result_sha256':saved['result_sha256'],
                    'native_professional_scope':scope})
            record.update(state='formed',result_sha256=saved['result_sha256'],proposal_response_sha256=task_digest(response.model_dump(mode='json')))
            self._save(key,record);return response

    def decide(self,request):
        from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1,AgentProposalRequestV1
        from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
        from gba_construction_sim.backend.simulation.decision_request_collector import DecisionRequestCollector
        with self.professional.read_guard():
            self.professional._check();scope=professional_scope(self.professional.assembly,request,purpose='decide')
            record,=[r for r in self.records() if r['state']=='formed' and r['scope']==scope
                and r['native_request']['agent']['agent_id']==request.agent.agent_id]
            original=AgentProposalRequestV1.model_validate(record['native_request']);plan,_=self._current(original)
            objects,observed=self._sources(plan,original);saved=checked_result(self.worker,TaskIdentity(**record['identity']))
            proposal,=[t['output'] for t in self.professional.assembly.client.tasks.for_organization(
                run_id=self.professional.assembly.client.run_id,organization_id=plan.organization_id)
                if t['state']=='output_formed' and t['identity']['purpose']=='propose'
                and t['identity']['action_id']=='select_appointment'
                and t['output']['factors'].get('native_professional_scope')==scope]
            accepted,selected=self.summary(plan,saved,objects,original);support=request.decision_support
            project=self.professional.assembly.engine.projects[plan.project_id]
            if (request.project!=DecisionRequestCollector._project_snapshot(project)
                    or record['observed']!=observed or record['source_sha256']!=task_digest(objects)
                    or record['result_sha256']!=saved['result_sha256'] or record['proposal_response_sha256']!=task_digest(proposal)
                    or support.get('decision_factors')!=proposal['factors'] or support.get('accepted')!=accepted
                    or proposal['accepted']!=accepted or support.get('action_type')!=proposal['action_type']
                    or support.get('selected_agent_id')!=selected or proposal['data'].get('selected_agent_id')!=selected
                    or request.choice_contract.output_field!='selected_agent_id' or request.choice_contract.multiple
                    or accepted and selected not in {o['id'] for o in request.candidate_options}
                    or proposal['action_type'] not in request.constraints.allowed_actions):
                raise TaskConflict('Owner commission final changes original sources, proposal or bounded choice')
            response=AgentDecisionResponseV1(request_id=request.request_id,agent_id=plan.organization_id,
                action_type=proposal['action_type'],decision=accepted,reason=proposal['reason'],
                data={**deepcopy(proposal['data']),**deepcopy(proposal['factors']),'proposal_response_sha256':task_digest(proposal)})
            ExternalAgentDecisionProvider._validated_action(request,response);return response

    def evidence(self):
        self.check_components()
        return {'version':self.VERSION,'source_file_sha256':self.settings.file_sha256,'requests':self.records(),
            'limits':'Independent synthetic service, management capacity and mandates. Actual original A02 acceptance drives private received-offer views; no private provider pricing policy or calendar is disclosed. Only native core appoints. No service fee, detailed signed contract, management reservation or A03 confirmation is inferred.'}
