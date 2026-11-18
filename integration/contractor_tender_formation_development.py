"""Initial actual-tender/terms composition; all commercial assumptions precede runtime."""
from copy import deepcopy
import argparse
import json
from pathlib import Path

from integration.contractor_tender_development import _write,_write_launch_files,ref
from integration.qs_bid_native_development import build_bundle as build_tender
from integration.contractor_formation_native import ContractorFormationPlan,ContractorFormationNativeApplication
from integration.contractor_formation_native import ContractorFormationNativeSettings
from integration.contractor_tender_authority_runtime import build_authority_runtime
from integration.module_host import GbaModuleHostExtension,GbaModuleHostConfiguration
from src.actions.contracts.common import Reference
from src.actions.contracts.contractor_formation_objects import ContractorFormationTermsView,contractor_agreement_digest
from src.coordination.tasks import task_digest


def build_bundle(directory,*,run_id,declared_price='110',declared_cost='100',
        with_owner_award=False,max_prior_owner_accepts=1,
        contractor_ids=('dev-contractor-a','dev-contractor-b')):
    """Two possible contractors, no preselected bid or prewritten submission."""
    from integration.financing_professional_development import _merge_snapshot
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    child=directory/'tender'
    build_tender(child,run_id=run_id,with_native_owner_selection=True,
        owner_options={'contractor_ids':contractor_ids})
    read=lambda name:json.loads((child/name).read_bytes())
    config=read('tender-configuration-input.json');tender=read('tender-host.json')
    snapshot=deepcopy(config['authority']['organization_snapshot'])
    source=json.loads(Path(config['snapshots']['snapshot_path']).read_bytes())['snapshots']
    root=Path(__file__).resolve().parent/'examples'
    template=json.loads((root/'role_contract_contractor_formation_accept_host.json').read_bytes())['settings']['source_settings']
    invocation=json.loads((root/'role_contract_contractor_formation_accept_invocation.json').read_bytes())
    plans=[]
    for work in config['request_work_settings']['requests']:
        org=work['organization_id'];project=work['project_id'];tag=org+'-actual-terms'
        bid_context=work['bid_plan']['bid_context'];clock=bid_context['business_time']['clock_ref']
        original,=[s for s in source if s['context']==bid_context]
        original_rows=original['projection']['objects']
        get=lambda kind:next(r['value'] for r in original_rows if r['ref']['kind']==kind)
        package=get('ProcurementPackage');pricing=get('ContractorPricingProfile')
        owner=next(o['organization_id'] for o in snapshot['organizations'] if any(a['role']=='Owner' for a in o['assignments']))
        actual={'ProcurementPackage':package['ref'],'TenderRound':package['round_ref'],
            'ProgrammeProposal':pricing['programme_ref'],'CostBasis':ref('CostBasis',org+'-cost'),
            'QuantityBasis':package['quantity_refs'][0],'WorkMethod':package['allowed_method_refs'][0],
            'ClockProfile':clock,'ResourcePool':ref('ResourcePool',org+'-capacity'),
            'Qualification':ref('Qualification',org+'-qualification')}
        def transform(value):
            if isinstance(value,str):return {'v2-fixture-contractor':org,'v2-fixture-contractor-actor':org,
                'v2-fixture-owner':owner,'v2-fixture-owner-actor':owner,'synthetic-HK':'Hong Kong'}.get(value,value)
            if isinstance(value,list):return [transform(v) for v in value]
            if not isinstance(value,dict):return value
            if set(value)=={'kind','id','version'}:
                kind,name=value['kind'],value['id']
                if kind=='ActionContract':return deepcopy(value)
                if kind in actual:return deepcopy(actual[kind])
                if kind=='TimeWindow' and name.endswith('work-slot'):
                    return deepcopy(get('ProgrammeProposal')['tasks'][0]['window_ref'])
                if kind=='TimeWindow' and name.endswith('bid-validity'):
                    return deepcopy(pricing['validity_ref'])
                if kind=='Project':return deepcopy(bid_context['scope']['ref'])
                if kind=='WorkScope':return deepcopy(bid_context['scope']['coverage_refs'][0])
                return ref(kind,tag+'-'+name.removeprefix('v2-formation-accept-'))
            if set(value)=={'clock_ref','offset'}:
                return {'clock_ref':clock,'offset':{8:0,10:6,20:10,22:11,30:15,40:20}.get(value['offset'],value['offset'])}
            return {k:transform(v) for k,v in value.items()}
        rows=transform(template['source_projection']['objects'])
        skip={'Bid','SubmissionExecution','PartyAcceptance','ProgrammeProposal','CostBasis','QuantityBasis',
            'ProcurementPackage','TenderRound','ResourcePool','ResourceCommitment','Qualification','WorkMethod',
            'ClockProfile','Project','WorkScope','ReleasedDeliverable','Deliverable'}
        objects=[r for r in rows if r['ref']['kind'] not in skip and 'other-project' not in r['ref']['id']]
        # The actual historical work/validity references enter from A02 later.
        objects=[r for r in objects if r['ref']['kind']!='TimeWindow'
            or r['ref'] not in [get('ProgrammeProposal')['tasks'][0]['window_ref'],pricing['validity_ref']]]
        kind=lambda k:next(r['value'] for r in objects if r['ref']['kind']==k)
        context=transform(invocation['context']);inputs=transform(invocation['action_input'])
        inputs['counterpart_acceptance_refs']=[]
        terms=kind('ContractTerms');terms['price']['value']=str(declared_price)
        terms['work_window']={'start':{'clock_ref':clock,'offset':10},'end':{'clock_ref':clock,'offset':20},'bounds':'closed_open'}
        terms['scope_keys']=deepcopy(package['coverage_keys']);terms['deliverable_refs']=deepcopy(package['deliverable_refs'])
        capacity=kind('ContractorCapacity');capacity.update(resources=[],commitments=[],qualification_refs=[],as_of={'clock_ref':clock,'offset':6})
        kind('FundingPosition')['existing_payment_refs']=[]
        kind('FundingSource')['actual_cash']['value']['value']='1000'
        for item in objects:
            name=item['ref']['id'];value=item['value']
            if item['ref']['kind'] in {'FundingCommitment','SettlementComponent','ContractPayment'} and 'amount' in value:
                value['amount']['value']['value']=str(declared_cost if 'new-contract-cost' in name else declared_price)
        native=ref('Evidence',tag+'-actual-negotiation');submission=ref('Evidence',tag+'-actual-native-submission')
        resources=ref('Evidence',tag+'-actual-current-resources');occupancy=ref('ResourceCommitment',tag+'-current-only')
        for evidence,locator in [(native,'actual-native-contract-terms-request'),(submission,'actual-own-native-bid-submitted-query'),
            (resources,'actual-current-own-normalized-capacity-one-tick-only')]:
            objects.append({'ref':evidence,'value':{'ref':evidence,'source_kind':'synthetic','basis_kind':'observed',
                'locator':locator,'content_hash':None,'effective_window':None}})
        profile=kind('ContractFormationProfile');profile['reviewed_agreement_sha256']=contractor_agreement_digest(
            ContractorFormationTermsView.model_validate(terms));profile['evidence_refs'].append(native)
        common=kind('Evidence');common['content_hash']=task_digest({'run_id':run_id,'tag':tag,'declared_price':declared_price,
            'declared_cost':declared_cost,'cash':'1000','restriction':'10','future_commitments':[],
            'work_window':[10,20],'submission_projection':'actual_original_native_bid_event_only'})
        common['locator']='explicit-initial-independent-agreement-cash-cost-and-empty-future-calendar-declaration'
        context.update(run_id=run_id,actor_id=org,scope=deepcopy(bid_context['scope']),operation_id=tag,
            task_ref=ref('DecisionTask',tag),business_time={'clock_ref':clock,'offset':6},read_token=tag,execution_mode='rule')
        candidates=kind('CandidateSet');candidates.update(operation_id=tag,as_of=context['business_time'])
        visible={task_digest(r):r for r in [*bid_context['visible_refs'],*[r['ref'] for r in objects],
            terms['bid_ref'],transform(ref('SubmissionExecution','v2-formation-accept-bid-submission')),occupancy]}
        context['visible_refs']=list(visible.values())
        from src.actions.contracts.domain import CandidateSet
        from src.actions.contracts.common import ActionContext
        CandidateSet.model_validate(candidates).check_context(ActionContext.model_validate(context),('accept','revise','reject'))
        for item in objects:
            if item['ref']['kind']=='Authorization':item['value']['readable_refs']=deepcopy(context['visible_refs'])
        initial=transform(template['organization_snapshot']);initial['run_id']=run_id
        initial['authorizations']=[deepcopy(r['value']) for r in objects if r['ref']['kind']=='Authorization']
        for organization in initial['organizations']:
            previous=next(o for o in snapshot['organizations'] if o['organization_id']==organization['organization_id'])
            organization['public_location']=deepcopy(previous['public_location'])
            organization['source_ids']=['synthetic:actual-terms:'+organization['organization_id']]
        snapshot=_merge_snapshot(snapshot,initial)
        plan=ContractorFormationPlan.model_validate({'organization_id':org,'project_id':project,'tick':6,
            'context':context,'action_input':inputs,'objects':objects,'native_evidence_ref':native,
            'native_contract_currency':'HKD','max_prior_accept_terms':None,
            'original_tender_request_id':f'proposal-tick2-{project}-{org}-consider_tender',
            'original_tender_projection':{'bid_ref':terms['bid_ref'],
                'submission_ref':transform(ref('SubmissionExecution','v2-formation-accept-bid-submission')),
                'source_evidence_ref':submission,'resource_evidence_ref':resources,'current_occupancy_ref':occupancy},
            'utility':{'value':'0.7','unit':'score','basis_ref':common['ref']},
            'probability':{'value':'1','unit':'probability','basis_ref':common['ref']}})
        plans.append(plan.model_dump(mode='json'))
    owner_settings=None
    if with_owner_award:
        from integration.owner_award_native_development import build_owner_sources
        owner_settings,snapshot=build_owner_sources(directory,run_id=run_id,formation_plans=plans,
            snapshot=snapshot,max_prior_accepts=max_prior_owner_accepts)
    authority={**config['authority'],'organization_snapshot':snapshot}
    tender['settings']['source_settings']['application_settings']['owner_contractor']['contractor']['authority']=authority
    tender_file=_write(directory,'tender-host.json',tender)
    formation_file=_write(directory,'contractor-formation-input.json',{'schema_version':'contractor-formation-input.v1','run_id':run_id,'plans':plans})
    formation=ContractorFormationNativeSettings.model_validate({'version':'1','policy_version':'actual-tender-independent-terms-v1',
        'authority':authority,**formation_file,'owner':owner_settings})
    request=read('macro-request.json');request['ticks']=8
    request['initial_projects'][0]['performance']['planned_duration']=10
    for agent in request['agents']:
        agent.update(financial_capacity=1,management_capability=1,payment_reliability=1,decision_speed=1)
    _write(directory,'macro-request.json',request)
    native=read('native-host.json');native['settings']['micro_contractor_formation_scope']=True
    if with_owner_award:
        native['settings']['micro_owner_award_scope']=True
    else:
        native['settings']['native_proposals'].append({'role':'Owner','operation':'decide_contract_award'})
        native['settings']['native_decisions'].append({'role':'Owner','decision_type':'owner_contract_award'})
    _write(directory,'native-host.json',native)
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1',
        'settings':{'tender':tender,'formation':formation.model_dump(mode='json')}})
    _write_launch_files(directory,assembly_hook='integration.contractor_tender_formation_development:configure_assembly',
        readme_override=('Actual native tender, QS evaluation and Owner preferred-bid selection feed original Contractor A04; '
            + ('the actual accepted winner then feeds original Owner A10 and native signing. '
                if with_owner_award else 'native Owner signing remains independent. ')
            + 'Initial commercial sources are synthetic declarations.'))
    return {'status':'actual-tender-formation-input-unverified','run_id':run_id,'plans':len(plans),**tender_file}


class TenderFormationComposition:
    VERSION='gba-v1-actual-tender-formation.v3'
    def __init__(self,*,assembly,request,output_directory,offline,configuration):
        from integration.contractor_tender_module_host import configure_assembly as configure_tender
        self.assembly=assembly;self.tender=None;self.supplier=None;self.lifecycle=None;self.opportunity=None;self.government=None
        config=GbaModuleHostConfiguration.model_validate(configuration)
        self.formation_settings=ContractorFormationNativeSettings.model_validate(config.settings['formation'])
        assembly.client.native_routes.attach(assembly)
        self.authority=build_authority_runtime(assembly=assembly,settings=self.formation_settings.authority)
        try:
            self.formation=ContractorFormationNativeApplication(assembly=assembly,settings=self.formation_settings,
                authority=self.authority,install=False)
            for (role,operation),handler in self.formation.proposal_bindings().items():
                assembly.client.bind_proposal_handler(role=role,operation=operation,handler=handler,
                    client_version=self.VERSION+':'+role+':'+operation)
            assembly.client.decision_handler=self.formation.decide
            if config.settings.get('supplier') is not None:
                from integration.supplier_order_native import SupplierOrderNativeApplication
                self.supplier=SupplierOrderNativeApplication(assembly=assembly,settings=config.settings['supplier'],
                    authority=self.authority,install=False)
                for (role,operation),handler in self.supplier.proposal_bindings().items():
                    assembly.client.bind_proposal_handler(role=role,operation=operation,handler=handler,
                        client_version=self.VERSION+':'+role+':'+operation)
                assembly.client.decision_handler=self.decide
            if config.settings.get('opportunity') is not None:
                from integration.owner_opportunity_native import OwnerOpportunityApplication
                self.opportunity=OwnerOpportunityApplication(assembly=assembly,settings=config.settings['opportunity'],
                    authority=self.authority,install=False)
                for (role,operation),handler in self.opportunity.proposal_bindings().items():
                    assembly.client.bind_proposal_handler(role=role,operation=operation,handler=handler,
                        client_version=self.VERSION+':'+role+':'+operation)
                assembly.client.decision_handler=self.decide
            if config.settings.get('government') is not None:
                from integration.government_intake_native import GovernmentIntakeApplication
                self.government=GovernmentIntakeApplication(assembly=assembly,settings=config.settings['government'],
                    authority=self.authority,install=False)
                for (role,operation),handler in self.government.proposal_bindings().items():
                    assembly.client.bind_proposal_handler(role=role,operation=operation,handler=handler,
                        client_version=self.VERSION+':'+role+':'+operation)
                assembly.client.decision_handler=self.decide
            if config.settings.get('lifecycle') is not None:
                from integration.native_lifecycle_actions import NativeLifecycleApplication
                self.lifecycle=NativeLifecycleApplication(assembly=assembly,authority=self.authority,settings=config.settings['lifecycle'])
            self.tender=configure_tender(assembly=assembly,request=request,output_directory=output_directory,
                offline=offline,configuration=config.settings['tender'],authority=self.authority)
            self.formation.seal_client_binding()
            if self.supplier is not None:self.supplier.seal_client_binding()
            if self.opportunity is not None:self.opportunity.seal_client_binding()
            if self.government is not None:self.government.seal_client_binding()
        except Exception:
            self.close();raise
    def decide(self,request):
        if self.government is not None and request.agent.role=='Government' and request.decision_type in {
                'government_review_assignment','government_design_approval','government_completion_approval'}:
            return self.government.decide(request)
        if self.opportunity is not None and (request.agent.role,request.decision_type)==('Owner','owner_project_opportunity'):
            return self.opportunity.decide(request)
        if (request.agent.role,request.decision_type) in {('Supplier','supplier_order_acceptance'),('Contractor','contractor_supplier_selection')}:
            return self.supplier.decide(request)
        return self.formation.decide(request)
    def evidence(self):
        return {'version':self.VERSION,'formation':self.formation.evidence(),'tender':self.tender.evidence(),
            **({'supplier':self.supplier.evidence()} if self.supplier is not None else {}),
            **({'lifecycle':self.lifecycle.evidence()} if self.lifecycle is not None else {}),
            **({'government':self.government.evidence()} if self.government is not None else {}),
            **({'opportunity':self.opportunity.evidence()} if self.opportunity is not None else {})}
    def close(self):
        if self.tender is not None:self.tender.close()
        if self.lifecycle is not None:self.lifecycle.close()
        self.authority.close()


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Actual tender development uses explicitly declared offline assumptions')
    app=TenderFormationComposition(assembly=assembly,request=request,output_directory=output_directory,
        offline=offline,configuration=configuration)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.close,writer_guard=app.authority.read_guard)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--with-owner-award',action='store_true')
    parser.add_argument('--max-prior-owner-accepts',type=int,default=1)
    args=parser.parse_args(argv)
    print(json.dumps(build_bundle(args.output,run_id=args.run_id,with_owner_award=args.with_owner_award,
        max_prior_owner_accepts=args.max_prior_owner_accepts)))


if __name__=='__main__':main()
