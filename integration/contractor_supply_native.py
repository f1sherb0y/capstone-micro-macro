"""Original Contractor A05 accepts an independently authorized current Supplier quote."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from pydantic import Field

from integration.bank_financing_private import checked_result, evidence_binding
from integration.contractor_planning_actions import ContractorPlanningActionAssembler
from integration.contractor_planning_results import ContractorPlanningResultWorker
from integration.contractor_supply_native_sources import supplier_quote_for_contractor
from integration.contractor_supply_native_substitution import quoted_substitutions
from integration.module_host import module_factory_descriptor
from integration.supplier_order_native_scope import supply_scope
from integration.native_contract_supply import signed_contract_for_supply
from src.actions.contracts.common import ActionContext, EvidenceRecord, Measured, StrictRecord, TextId, ref_type
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class ContractorSupplyRequirementLink(StrictRecord):
    supply_requirement_ref: ref_type('SupplyRequirement')
    quote_requirement_refs: list[ref_type('Requirement')]


class ContractorSupplyDisclosure(StrictRecord):
    supplier_id: TextId
    offer_ref: ref_type('SupplyOffer')
    authority_ref: ref_type('ProcurementAuthority')
    evidence_ref: ref_type('Evidence')
    requirement_links: list[ContractorSupplyRequirementLink]
    payment_rules: list[dict]
    shared_evidence_refs: list[ref_type('Evidence')]
    included_service_refs: list[ref_type('DeliveryService')]
    substitutions: list['ContractorSupplySubstitution']=Field(default_factory=list)


class ContractorSupplySubstitution(StrictRecord):
    supply_requirement_ref: ref_type('SupplyRequirement')
    authority_ref: ref_type('SubstitutionAuthority')
    deviation_refs: list[ref_type('SpecificationDeviation')]=Field(min_length=1)


ContractorSupplyDisclosure.model_rebuild()


class ContractorSupplyPlan(StrictRecord):
    organization_id: TextId
    project_id: TextId
    tick: int=Field(ge=1)
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    # This order is the Contractor's supplied preference, never Supplier utility.
    disclosures: list[ContractorSupplyDisclosure]
    repeat_supplier_priority_penalty: int=Field(default=0,ge=0,strict=True)
    require_native_award: bool=False
    negative_selection_observation_ref: ref_type('NativeSupplySelectionObservation') | None=None
    utility: Measured
    probability: Measured


class ContractorSupplySettings(StrictRecord):
    version: TextId
    file_path: TextId
    file_sha256: Digest


class ContractorSupplyNativeApplication:
    PREFIX='contractor_supply_native_request:'

    def __init__(self,*,supplier,settings):
        self.supplier=supplier;self.settings=ContractorSupplySettings.model_validate(settings).model_copy(deep=True)
        self._check_file();doc=json.loads(Path(self.settings.file_path).read_bytes())
        if (set(doc)!={'schema_version','run_id','plans'} or doc['schema_version']!='contractor-supply-input.v1'
                or doc['run_id']!=supplier.assembly.client.run_id):raise TaskConflict('Contractor procurement changes its schema or run')
        self.plans=[ContractorSupplyPlan.model_validate(p) for p in doc['plans']]
        keys=[(p.organization_id,p.project_id,p.tick) for p in self.plans]
        if not keys or len(set(keys))!=len(keys):raise TaskConflict('Contractor procurement needs unique current selectors')
        for p in self.plans:
            c=p.context
            if (c.run_id!=doc['run_id'] or c.contract_ref.id!='CONTRACTOR-A05'
                    or c.scope.kind!='project' or c.scope.ref.id!=p.project_id or c.business_time.offset!=p.tick
                    or c.execution_mode=='offline_fixture' or len({task_digest(r['ref']) for r in p.objects})!=len(p.objects)
                    or not p.disclosures or len({d.supplier_id for d in p.disclosures})!=len(p.disclosures)
                    or len({task_digest(d.offer_ref.model_dump(mode='json')) for d in p.disclosures})!=len(p.disclosures)):
                raise TaskConflict('Contractor procurement changes its original actor, project, time or disclosures')
        self._plans_sha=task_digest([p.model_dump(mode='json') for p in self.plans]);self._settings_sha=task_digest(self.settings.model_dump(mode='json'))
        self._bound={}
        self._source_pins=self.source_descriptors()
        self.assembler=ContractorPlanningActionAssembler(registry=supplier.registry,organizations=supplier.organizations,
            provider=self,macro_version='gba-public-2026-08-21',source_mode='formal',policy_version=supplier.settings.policy_version,
            model_version=supplier.assembly.client.versions['model'])
        self.worker=ContractorPlanningResultWorker(store=supplier.assembly.client.tasks,snapshots=supplier.snapshots,
            registry=supplier.registry,client_version=supplier.VERSION,model_version=supplier.assembly.client.versions['model'],
            validate_invocation=self.validate_invocation,validate_wait=self.validate_wait)

    def validate_wait(self,task,result,conditions):
        from integration.contractor_negative_selection import validate_selection_wait
        return validate_selection_wait(self,task,result,conditions)

    def saved_result(self,identity):
        from integration.contractor_negative_selection import saved_selection
        return saved_selection(self,identity)

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest()!=self.settings.file_sha256:
            raise TaskConflict('Contractor independent procurement inputs changed their pinned bytes')

    @staticmethod
    def source_descriptors():
        return {name:module_factory_descriptor(function,'contractor-supply-sources.v1') for name,function in
            [('quote',supplier_quote_for_contractor),('substitutions',quoted_substitutions)]}

    def check_components(self):
        self._check_file()
        if (task_digest(self.settings.model_dump(mode='json'))!=self._settings_sha
                or self.source_descriptors()!=self._source_pins
                or task_digest([p.model_dump(mode='json') for p in self.plans])!=self._plans_sha
                or self.worker.store is not self.supplier.worker.store or self.worker.registry is not self.supplier.registry
                or self.assembler.organizations is not self.supplier.organizations):
            raise TaskConflict('Contractor procurement changes original plans or shared authority/runtime')

    def _current(self,request):
        self.supplier._check();scope=supply_scope(self.supplier.assembly,request,purpose='propose')
        if (request.agent.role,request.operation)!=('Contractor','select_supplier'):
            raise TaskConflict('Contractor procurement needs its actual original selection request')
        plan,=[p for p in self.plans if (p.organization_id,p.project_id,p.tick)==(request.agent.agent_id,scope['project_id'],scope['tick'])]
        if self.supplier.organizations.grants(plan.context,'CONTRACTOR-A05','Contractor')[0].organization_id!=plan.organization_id:
            raise TaskConflict('Contractor procurement lost current own original authority')
        return plan,scope

    def _sources(self,plan,request):
        from integration.contractor_supply_native_feedback import prior_contractor_supply_selections
        objects=deepcopy(plan.objects);scope=supply_scope(self.supplier.assembly,request,purpose='propose')
        history=prior_contractor_supply_selections(self.supplier.assembly,organization_id=plan.organization_id,
            tick=plan.tick,read_guard=self.supplier.read_guard,query_original=self.query_native_outcome)
        accepted={p['agent_id'] for p,d in request.inputs['offers'] if d['accepted']}
        unknown=accepted-{d.supplier_id for d in plan.disclosures}
        if unknown:raise TaskConflict('Current accepted supplier lacks an explicit Contractor disclosure')
        choices=[]
        for index,d in enumerate(plan.disclosures):
            if d.supplier_id in accepted:
                count=sum(h['supplier_id']==d.supplier_id for h in history)
                choices.append((index+plan.repeat_supplier_priority_penalty*count,index,d))
        if not choices:
            if plan.negative_selection_observation_ref is not None:
                from integration.contractor_negative_selection import negative_sources
                return negative_sources(self,plan,request,scope)
            raise TaskConflict('No accepted authorized Supplier quote; procurement remains unresolved')
        _,_,selected=min(choices,key=lambda row:(row[0],row[1]))
        origin=supplier_quote_for_contractor(self.supplier,plan=plan,request=request,disclosure=selected,objects=objects)
        mandate_ref=plan.action_input['work_basis']['contract_ref']
        mandate,=[r['value'] for r in objects if r['ref']==mandate_ref]
        project=self.supplier.assembly.engine.projects[plan.project_id]
        if (mandate['organization_id']!=plan.organization_id or mandate['scope']!=plan.context.scope.model_dump(mode='json')
                or not any(r.get('contractor_id')==plan.organization_id for r in project.contracts)):
            raise TaskConflict('Contractor work basis changes its actual signed-project appointment')
        profile,=[r['value'] for r in objects if r['ref']==mandate['planning_profile_ref']]
        if (profile['choice']!='accept_supply_offer' or profile['selected_offer_ref'] is not None
                or profile['procurement_authority_ref'] is not None
                or plan.native_evidence_ref.model_dump(mode='json') not in profile['evidence_refs']):
            raise TaskConflict('Contractor supplied profile lacks its explicit current-candidate binding points')
        profile['selected_offer_ref']=selected.offer_ref.model_dump(mode='json')
        profile['procurement_authority_ref']=selected.authority_ref.model_dump(mode='json')
        profile['requirement_refs']=[r.supply_requirement_ref.model_dump(mode='json') for r in selected.requirement_links]
        profile['evidence_refs'].append(selected.evidence_ref.model_dump(mode='json'))
        candidate,=[r['value'] for r in objects if r['ref']==plan.context.candidate_set_ref.model_dump(mode='json')]
        candidate['candidates']=[{'ref':selected.offer_ref.model_dump(mode='json'),'permitted_choices':['accept_supply_offer']}]
        for d in plan.disclosures:
            if d!=selected:
                evidence_binding(objects,d.evidence_ref.model_dump(mode='json'),{
                    'source':'not_selected_for_current_private_review','supplier_id':d.supplier_id,
                    'currently_accepted':d.supplier_id in accepted,'scope':scope})
        inputs=deepcopy(plan.action_input);inputs['supplier_offer_refs']=[selected.offer_ref.model_dump(mode='json')]
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),'origin':origin,
            'prior_selections':history,'repeat_supplier_priority_penalty':plan.repeat_supplier_priority_penalty,
            'eligible_preferences':[{'supplier_id':d.supplier_id,'priority':score,'base_priority':index} for score,index,d in choices],
            'selected_supplier_id':selected.supplier_id}
        if plan.require_native_award:
            observed['native_signed_contract']=signed_contract_for_supply(self.supplier.assembly,
                scope=scope,organization_id=plan.organization_id)
        evidence_binding(objects,plan.native_evidence_ref.model_dump(mode='json'),observed)
        if plan.negative_selection_observation_ref is not None:
            from integration.contractor_negative_selection import bind_selection_observation
            bind_selection_observation(self,plan,request,objects,history=[])
        return objects,inputs,observed

    def project(self,*,context,organization_id,grants):
        bound=self._bound.get(task_digest(context.model_dump(mode='json')))
        if bound is None or organization_id!=bound[0].organization_id:raise TaskConflict('Contractor view changes its own current bound request')
        plan,request=bound;self._current(request);objects,_,_=self._sources(plan,request)
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21','state_version':'native-procurement:'+task_digest(objects),
            'read_token':context.read_token,'business_time':context.business_time.model_dump(mode='json'),
            'organization_id':organization_id,'objects':objects}

    def validate_invocation(self,row,prepared):
        plan,request=self._bound[prepared.context_sha256];self._current(request)
        if prepared.context!=plan.context or prepared.runner.registry is not self.supplier.registry:
            raise TaskConflict('Contractor procurement worker changes its original invocation')
        prepared.reading.recheck();return True

    def _records(self):return self.supplier._records(prefix=self.PREFIX)

    def _summary(self,saved,plan,request):
        if saved['result']['kind']=='deferred':
            from src.actions.roles.contractor_negative_selection import WAIT_CODES
            if (plan.negative_selection_observation_ref is None or saved['result'].get('reason_code') not in WAIT_CODES
                    or any(d['accepted'] for p,d in request.inputs['offers'])):
                raise TaskConflict('Unresolved procurement cannot be promoted to a bounded negative selection')
            return None
        result=saved['result']['payload']
        if result['choice']!='accept_supply_offer':raise TaskConflict('Contractor non-purchase result remains unresolved for native selection')
        selected,=[d for d in plan.disclosures if d.offer_ref.model_dump(mode='json')==result.get('offer_ref')]
        if (result['choice']!='accept_supply_offer' or selected.supplier_id not in
                {p['agent_id'] for p,d in request.inputs['offers'] if d['accepted']}):
            raise TaskConflict('Contractor unresolved or non-purchase result cannot become native supplier selection')
        return selected.supplier_id

    def propose(self,request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        with self.supplier.read_guard():
            plan,scope=self._current(request);key=self.PREFIX+task_digest([self.supplier.assembly.client.simulation_id,scope,request.request_id])
            if any(r['key']==key for r in self._records()):raise TaskConflict('Contractor supply request already claimed; diagnose its original transport')
            record=self.supplier._save(key,{'key':key,'state':'preparing','scope':scope,'native_request':request.model_dump(mode='json')})
            self._bound[task_digest(plan.context.model_dump(mode='json'))]=(plan,request.model_copy(deep=True))
            objects,inputs,observed=self._sources(plan,request);prepared=self.assembler.build(plan.context,**inputs)
            identity=self.worker.register(prepared,request_id=key+':CONTRACTOR-A05')
            record.update(identity=identity.as_dict(),source_sha256=task_digest(objects),observed=observed)
            record=self.supplier._save(key,record);self.worker.execute(identity,prepared);saved=self.saved_result(identity)
            selected=self._summary(saved,plan,request)
            for metric,unit in ((plan.utility,'score'),(plan.probability,'probability')):
                if (metric.unit!=unit or not 0<=Decimal(metric.value)<=1
                        or not isinstance(prepared.reading.resolve(metric.basis_ref),EvidenceRecord)):
                    raise TaskConflict('Contractor supply indicators need independently sourced bounded units')
            response=AgentProposalResponseV1(request_id=request.request_id,action_type='select_supplier',accepted=selected is not None,
                utility=float(plan.utility.value) if selected else 0,probability=float(plan.probability.value) if selected else 0,
                reason=saved['result']['payload']['note'] if selected else saved['result']['reason_code'],
                data={'selected_supplier_id':selected,'accepted_supplier_ids':[p['agent_id'] for p,d in request.inputs['offers'] if d['accepted']]},
                factors={'micro_action_id':'CONTRACTOR-A05','micro_task_key':identity.key,
                    'micro_result_sha256':saved['result_sha256'],'native_supply_scope':scope,
                    **({'decision_source':'micro_contractor_no_accepted'} if selected is None else {})})
            record.update(state='formed',result_sha256=saved['result_sha256'],proposal_response_sha256=task_digest(response.model_dump(mode='json')))
            self.supplier._save(key,record);return response

    def decide(self,request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1,AgentDecisionResponseV1
        from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
        with self.supplier.read_guard():
            self.supplier._check();scope=supply_scope(self.supplier.assembly,request,purpose='decide')
            technical,=[r for r in self._records() if r['state']=='formed' and r['scope']==scope]
            original=AgentProposalRequestV1.model_validate(technical['native_request']);plan,_=self._current(original)
            saved=self.saved_result(TaskIdentity(**technical['identity']));objects,_,observed=self._sources(plan,original)
            selected=self._summary(saved,plan,original);tasks=self.supplier.assembly.client.tasks
            proposal,=[t['output'] for t in tasks.for_organization(run_id=plan.context.run_id,organization_id=plan.organization_id)
                if t['state']=='output_formed' and t['identity']['purpose']=='propose' and t['identity']['action_id']=='select_supplier'
                and t['output'].get('factors',{}).get('native_supply_scope')==scope]
            support=request.decision_support
            if (technical['source_sha256']!=task_digest(objects) or observed!=technical['observed']
                    or saved['result_sha256']!=technical['result_sha256'] or task_digest(proposal)!=technical['proposal_response_sha256']
                    or support.get('decision_factors')!=proposal['factors'] or support.get('action_type')!='select_supplier'
                    or support.get('accepted') is not (selected is not None) or support.get('selected_supplier_id')!=selected
                    or proposal['data']!={'selected_supplier_id':selected,'accepted_supplier_ids':[
                        p['agent_id'] for p,d in original.inputs['offers'] if d['accepted']]}
                    or support.get('accepted_supplier_ids')!=proposal['data']['accepted_supplier_ids']
                    or request.choice_contract.output_field!='selected_supplier_id'
                    or request.choice_contract.multiple or selected is not None and selected not in {o['id'] for o in request.candidate_options}
                    or selected is None and request.candidate_options
                    or 'select_supplier' not in request.constraints.allowed_actions):
                raise TaskConflict('Contractor confirmation changes its actual original A05, quote, selection or bounded candidates')
            response=AgentDecisionResponseV1(request_id=request.request_id,agent_id=plan.organization_id,action_type='select_supplier',decision=selected is not None,
                reason=proposal['reason'],data={**proposal['data'],**proposal['factors'],'proposal_response_sha256':technical['proposal_response_sha256']})
            ExternalAgentDecisionProvider._validated_action(request,response);return response

    def query_native_outcome(self,identity,*,organization_id,tick):
        from integration.supply_native_outcome_query import query_contractor_supply_outcome
        return query_contractor_supply_outcome(self,identity,organization_id=organization_id,tick=tick)

    def evidence(self):
        self.check_components();return {'source_file_sha256':self.settings.file_sha256,'requests':self._records(),
            'limits':'Original A05 validates independently received signed commercial views against actual Supplier A03/A04; native selection creates no detailed order or payment.'}
