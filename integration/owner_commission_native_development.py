"""Initial independent Owner procurement sources beside professional A02 plans."""
from copy import deepcopy

from integration.contractor_tender_development import _write,ref,known
from integration.owner_commission_native import OwnerCommissionPlan,OwnerCommissionSettings
from src.actions.contracts.owner_commission_objects import owner_commission_schemas
from src.actions.contracts.common import Reference


def commission_plans(directory,*,run_id,professional_plans,organizations,grants,basis_rows):
    owner='professional-owner';owner_basis=organizations[owner]['evidence_refs'][0]
    owner_actor=organizations[owner]['actor_id']
    clock=professional_plans[0]['context']['business_time']['clock_ref']
    point=lambda n:{'clock_ref':clock,'offset':n}
    window=lambda start=0,end=100:{'start':point(start),'end':point(end),'bounds':'closed_open'}
    owner_function=organizations[owner]['assignments'][0]['function_ref'];result=[]
    keys=sorted({(p['project_id'],p['tick'],p['role']) for p in professional_plans})
    for project,tick,role in keys:
        providers=[p for p in professional_plans if (p['project_id'],p['tick'],p['role'])==(project,tick,role)]
        first=providers[0];scope=first['context']['scope'];tag=project+'-owner-'+role.lower()
        rr=lambda kind,name:ref(kind,tag+'-'+name)
        service_ref=rr('ServiceScope','service');work_ref=scope['coverage_refs'][0]
        deliverable=rr('DeliverableRequirement','report');time_ref=rr('TimeWindow','service')
        profile_ref=rr('ProcurementProfile','selection');capacity_ref=ref('ManagementCapacity',owner+'-management',str(tick))
        pool_ref=ref('ResourcePool',owner+'-management-staff',str(tick))
        native=rr('Evidence','native');handoff=rr('Evidence','providers')
        context_candidates=rr('CandidateSet','selection')
        objects=[deepcopy(basis_rows[owner])];disclosures=[];offer_refs=[];provider_refs=[]
        shared={'evidence_refs':[owner_basis]}
        def put(reference,**fields):objects.append({'ref':reference,'value':{'ref':reference,**fields}})
        put(native,source_kind='synthetic',basis_kind='observed',locator='actual-owner-commission-request-and-own-history',
            content_hash=None,effective_window=window())
        put(handoff,source_kind='synthetic',basis_kind='observed',locator='actual-independent-provider-intake-for-owner',
            content_hash=None,effective_window=window())
        # Native time/ownership is checked again on each actual request.
        # Detailed service content and management load are independent inputs.
        put(scope['ref'],**shared,owner_organization_id=owner,available_at=point(tick),status='active')
        assignment=organizations[owner]['assignments'][0]
        objects.append({'ref':owner_function,'value':deepcopy(assignment)})
        objects.append({'ref':grants[owner]['ref'],'value':deepcopy(grants[owner])})
        first_terms=next(r['value'] for r in first['objects'] if r['ref']==first['action_input']['terms_ref'])
        service=first_terms['service_code']['value'];responsibilities=first_terms['responsibility_codes']['value']
        objects.append({'ref':time_ref,'value':deepcopy(first_terms['desired_window']['value'])})
        put(service_ref,**shared,employer_organization_id=owner,scope_ref=scope,region_id='Hong Kong',permitted_roles=[role],
            service_codes=[service],requested_uses=['research'],responsibility_codes=responsibilities,
            required_qualification_codes=['synthetic-professional-license'],required_method_refs=[],deliverable_refs=[deliverable],
            window_ref=time_ref,available_at=point(tick),effective_window=window())
        put(work_ref,**shared,scope_ref=scope,service_codes=[service],requested_uses=['research'],
            responsibility_codes=responsibilities,deliverable_refs=[deliverable],effective_window=window())
        put(deliverable,**shared,service_scope_ref=service_ref,work_ref=work_ref,requested_use='research',
            description='Independent declared '+role+' research report for '+project)
        for index,p in enumerate(providers):
            org=p['organization_id'];basis=organizations[org]['evidence_refs'][0]
            function=organizations[org]['assignments'][0]['function_ref']
            def source(reference):return next(r['value'] for r in p['objects'] if r['ref']==reference)
            terms=source(p['action_input']['terms_ref']);cap=source(p['action_input']['capability_ref'])
            provider=rr('EligibleProvider',org);offer=rr('ServiceOffer',org);terms_ref=rr('ContractTerms',org)
            offer_refs.append(offer);provider_refs.append(provider)
            objects.extend([deepcopy(basis_rows[org]),{'ref':function,'value':deepcopy(organizations[org]['assignments'][0])},
                {'ref':grants[org]['ref'],'value':deepcopy(grants[org])}])
            public_cap={k:deepcopy(cap[k]) for k in ('ref','evidence_refs','organization_id','effective_window','region_ids',
                'service_codes','allowed_uses','responsibility_codes','method_refs','qualification_refs','qualification_coverage')}
            public_cap['function_ref']=function
            objects.append({'ref':public_cap['ref'],'value':public_cap})
            for qref in cap['qualification_refs']:
                q=source(qref);view={k:deepcopy(q[k]) for k in ('ref','evidence_refs','organization_id','code','region_ids',
                    'service_codes','effective_window','standing')}
                view.update(function_ref=function,verified_at=point(tick));objects.append({'ref':qref,'value':view})
            put(provider,evidence_refs=[basis,handoff],organization_id=org,actor_id=p['context']['actor_id'],function_ref=function,
                capability_ref=cap['ref'],invitation_permitted=known(True),available_at=point(tick),effective_window=window(),status='active')
            put(terms_ref,evidence_refs=[basis,handoff],service_scope_ref=service_ref,scope_ref=scope,
                employer_organization_id=owner,provider_organization_id=org,payer_organization_id=owner,payer_actor_id=owner_actor,
                payer_function_ref=owner_function,payer_authority_ref=grants[owner]['ref'],payer_authority_action_id='OWN-A04',
                fee=deepcopy(terms['fee']),service_codes=known([service]),requested_uses=deepcopy(terms['requested_uses']),
                responsibility_codes=deepcopy(terms['responsibility_codes']),deliverable_refs=[deliverable],window_ref=time_ref,
                condition_refs=[],authority_limits=known(['advice_only']),status='offered',issued_at=point(tick),effective_window=window())
            put(offer,evidence_refs=[basis,handoff,native],provider_ref=provider,service_scope_ref=service_ref,terms_ref=terms_ref,
                author_actor_id=p['context']['actor_id'],author_function_ref=function,authority_ref=grants[org]['ref'],authority_action_id=role.upper()+'-A02',
                priority=known(index+1),received_at=point(tick),effective_window=window(),status='offered')
            requirement,=terms['deliverable_requirement_refs']
            disclosures.append({'provider_id':org,'provider_ref':provider,'offer_ref':offer,'terms_ref':terms_ref,
                'deliverable_links':[{'owner_ref':deliverable,'provider_ref':requirement}],
                'shared_evidence_refs':[basis]})
        put(pool_ref,**shared,organization_id=owner,function_ref=owner_function,authority_ref=grants[owner]['ref'],
            service_authority_ref=None,service_actor_id=None,service_authority_action_id=None,capability_ref=None,
            purpose_codes=['management'],region_id='Hong Kong',total=known({'value':'4','unit':'person','basis_ref':owner_basis}),
            commitments=[{'ref':ref('ResourceCommitment',owner+'-prior-service-load'),
                'quantity':{'value':'1','unit':'person','basis_ref':owner_basis},'window':window(0,16)}],
            as_of=point(tick),coverage='complete',effective_window=window())
        put(capacity_ref,**shared,organization_id=owner,resource_refs=[pool_ref],as_of=point(tick),coverage='complete')
        put(profile_ref,evidence_refs=[owner_basis,native],organization_id=owner,scope_ref=scope,service_scope_ref=service_ref,
            policy=known('evaluate'),on_unavailable=known('reject_all'),permitted_roles=[role],
            fee_cap=known({'value':'150','currency':'HKD','basis_ref':owner_basis}),invitation_provider_refs=provider_refs,
            clarification_issue_refs=[],management_allocations=[{'resource_ref':pool_ref,'window_ref':time_ref,
                'quantity':{'value':'0.5','unit':'person','basis_ref':owner_basis},
                'task_target':{'kind':'proposed','local_key':tag+'-manage','scope_ref':scope}}],
            internal_plan_ref=None,required_condition_refs=[],permitted_authority_codes=known(['advice_only']),
            available_at=point(tick),effective_window=window())
        objects.append({'ref':context_candidates,'value':{'operation_id':tag,'scope':scope,'as_of':point(tick),
            'candidates':[{'ref':r,'permitted_choices':['accept']} for r in offer_refs],
            'search_profile_ref':rr('Profile','received-offers')}})
        refs=[r['ref'] for r in objects];grants[owner]['readable_refs'].extend(refs)
        context={'run_id':run_id,'actor_id':owner_actor,'function_ref':owner_function,'authorization_refs':[grants[owner]['ref']],
            'operation_id':tag,'contract_ref':ref('ActionContract','OWN-A04'),'task_ref':rr('DecisionTask','commission'),
            'scope':scope,'business_time':point(tick),'read_token':tag+'-read','visible_refs':refs,
            'candidate_set_ref':context_candidates,'execution_mode':'rule'}
        action_input={'scope_ref':scope,'procurement_profile_ref':profile_ref,'service_scope_ref':service_ref,
            'candidate_provider_refs':provider_refs,'candidates':offer_refs,'authority_ref':grants[owner]['ref'],'capacity_ref':capacity_ref}
        result.append({'organization_id':owner,'project_id':project,'tick':tick,'role':role,'context':context,
            'action_input':action_input,'objects':objects,'native_evidence_ref':native,'handoff_evidence_ref':handoff,
            'disclosures':disclosures,'repeat_provider_priority_penalty':2,'utility':'0.7','probability':'1'})
    return result


def write_commission_sources(directory,*,run_id,plans,grants):
    schemas=owner_commission_schemas()
    for plan in plans:
        for row in plan['objects']:
            if row['ref']['kind']=='Authorization':row['value']=deepcopy(grants[row['value']['organization_id']])
            value=deepcopy(row['value'])
            if row['ref'] in [plan['native_evidence_ref'],plan['handoff_evidence_ref']]:value['content_hash']='0'*64
            schemas.validate_projection(Reference.model_validate(row['ref']),value)
        OwnerCommissionPlan.model_validate(plan)
    source=_write(directory,'owner-commission-input.json',{'schema_version':'owner-commission-input.v1','run_id':run_id,'plans':plans})
    return OwnerCommissionSettings.model_validate({'version':'1',**source})
