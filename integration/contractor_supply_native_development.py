"""Independent A05 procurement views, limits and explicit preference; no formal orders."""
from copy import deepcopy

from integration.contractor_planning_actions import ContractorPlanningActionAssembler
from integration.contractor_supply_native import ContractorSupplyPlan
from integration.contractor_tender_development import known, ref
from src.actions.contracts.common import Reference
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import task_digest


def contractor_plans(supplier_plans,*,organizations,grants,procurement_limits=None,substitution_permitted=True):
    plans=[];selectors=sorted({(p['project_id'],p['tick']) for p in supplier_plans})
    for project,tick in selectors:
        supplied=sorted([p for p in supplier_plans if (p['project_id'],p['tick'])==(project,tick)],key=lambda p:p['organization_id'])
        buyers={next(r['value']['buyer_id'] for r in p['objects'] if r['ref']==p['action_input']['offer_ref']) for p in supplied}
        if len(buyers)!=1:
            raise ValueError('Contractor procurement sources must share one original explicit buyer')
        org=buyers.pop();tag=f'{org}-{project}-t{tick}-procurement';rr=lambda kind,name:ref(kind,tag+'-'+name)
        limit=(procurement_limits or {}).get((project,tick),'1000')
        first=supplied[0];scope=first['context']['scope'];now=first['context']['business_time']
        by=lambda p,reference:next(r['value'] for r in p['objects'] if r['ref']==reference)
        window=by(first,first['action_input']['formation_profile_ref'])['effective_window'];start=window['start']
        common=organizations[0]['evidence_refs'][0];common_value=by(first,common)
        basis=rr('Evidence','explicit-procurement-input');native=rr('Evidence','actual-native-selection')
        objects=[{'ref':common,'value':deepcopy(common_value)}, {'ref':basis,'value':{'ref':basis,'source_kind':'synthetic',
            'basis_kind':'assumed','locator':'independent-contractor-procurement-mandate-and-received-commercial-views',
            'content_hash':task_digest({'organization_id':org,'project_id':project,'tick':tick,'procurement_limit_HKD':limit,
                'procurement_used_HKD':0,'inspection_permission':'explicit_assumption','initial_signed_supplier_views':True,
                'repeat_supplier_priority_penalty':2,'substitution_permitted':substitution_permitted}),'effective_window':window}},
            {'ref':native,'value':{'ref':native,'source_kind':'synthetic','basis_kind':'observed',
                'locator':'actual-native-contractor-selection-and-own-earlier-A05-results','content_hash':None,'effective_window':window}}]
        objects.append({'ref':scope['ref'],'value':{'ref':scope['ref'],'evidence_refs':[common]}})
        assignment=next(o['assignments'][0] for o in organizations if o['organization_id']==org)
        function=deepcopy(assignment['function_ref'])
        objects.append({'ref':function,'value':deepcopy(assignment)})
        authority=rr('Authorization','procurement');mandate=rr('Contract','private-view-of-current-main-contract')
        profile=rr('WorkPlanningProfile','own-procurement');capacity=rr('ContractorCapacity','source-snapshot')
        receiving=rr('TimeWindow','site-receiving');receiving_window=deepcopy(window)
        first_offer=by(first,first['action_input']['offer_ref'])
        delivery_window=by(first,first_offer['lines'][0]['delivery']['delivery_window_ref'])
        receiving_window['start']=deepcopy(delivery_window['start'])
        receiving_window['end']={**deepcopy(delivery_window['end']),'offset':delivery_window['end']['offset']+1}
        objects.append({'ref':receiving,'value':receiving_window})
        def add(reference,**value):objects.append({'ref':reference,'value':{'ref':reference,'scope':scope,'available_at':start,
            'effective_window':window,'evidence_refs':[basis],**value}})
        money=lambda n:{'value':str(n),'currency':'HKD','basis_ref':basis}
        add(mandate,organization_id=org,mandate_kind='contract',effective=known(True),planning_profile_ref=profile,
            allowed_task_purposes=['construction'],allow_quote=known(True),allow_supply_acceptance=known(True),
            procurement_limit=known(money(limit)),procurement_used=known(money(0)),procurement_history_refs=[],
            procurement_history_complete=True,region_id='Hong Kong',object_type='building',work_type='factory_supply',
            special_condition_codes=[],required_qualification_codes=[],dependency_refs=[],design_refs=[],method_refs=[],evidence_refs=[basis,native])
        add(profile,mandate_ref=mandate,organization_id=org,authority_ref=authority,choice='accept_supply_offer',plan_ref=None,
            prior_plan_ref=None,requirement_refs=[],supplier_refs=[],selected_offer_ref=None,receiving_window_ref=receiving,
            procurement_authority_ref=None,note='Apply explicit current-accepted supplier preference, then verify exact independent terms and procurement authority.',
            evidence_refs=[basis,native])
        add(capacity,organization_id=org,as_of=now,coverage='complete',resources=[],commitments=[],qualification_refs=[],qualification_coverage='complete')
        disclosures=[]
        for source in supplied:
            supplier=source['organization_id'];offer=deepcopy(by(source,source['action_input']['offer_ref']))
            terms=deepcopy(by(source,offer['terms_ref']));delivery=offer['lines'][0]['delivery'];product=delivery['product']
            requirement=rr('SupplyRequirement',supplier+'-required-batch');inspection=rr('InspectionRule',supplier+'-receiving-rule')
            payment=rr('PaymentRule',supplier+'-delivery-payment');binding=rr('SupplyBinding',supplier+'-exact-terms')
            permission=rr('ProcurementAuthority',supplier+'-independent-responsible-authority')
            evidence=rr('Evidence',supplier+'-actual-quote-check')
            deviations=product['deviation_refs']
            substitution=rr('SubstitutionAuthority',supplier+'-independent-exact-deviations') if deviations else None
            original_basis=product['quantity']['basis_ref']
            if not any(r['ref']==original_basis for r in objects):objects.append({'ref':original_basis,'value':deepcopy(by(source,original_basis))})
            original_window=delivery['delivery_window_ref']
            objects.append({'ref':original_window,'value':deepcopy(by(source,original_window))})
            add(requirement,mandate_ref=mandate,product_ref=product['product_ref'],quantity=product['quantity'],delivery_window_ref=original_window,
                receiving_window_ref=receiving,destination_ref=delivery['destination_ref'],inspection_rule_ref=inspection,payment_rule_ref=payment,
                allowed_supplier_ids=[supplier],substitution_authority_ref=substitution)
            if substitution is not None:
                add(substitution,requirement_refs=[requirement],offer_ref=None,terms_ref=None,
                    permitted=known(substitution_permitted))
            for reference in (product['product_ref'],delivery['destination_ref'],inspection,payment,binding):
                add(reference,requirement_refs=[requirement],offer_ref=offer['ref'] if reference==binding else None,
                    terms_ref=terms['ref'] if reference==binding else None,permitted=known(True))
            source_assignment=next(o['assignments'][0] for o in organizations if o['organization_id']==supplier)
            source_function=deepcopy(source_assignment['function_ref'])
            objects.append({'ref':source_function,'value':deepcopy(source_assignment)})
            initial_authority=rr('Authorization',supplier+'-independent-initial-offer-author')
            # This is explicitly an initial independently authored commercial
            # source, not a rewritten grant or a signature attributed to the
            # future same-request A03. Actual A03/A04 support is checked later.
            initial_grant={'ref':initial_authority,'organization_id':supplier,'actor_id':supplier,'function_ref':source_function,
                'action_ids':['SUPPLIER-A03'],'scopes':[scope],'readable_refs':[terms['ref'],requirement,original_basis,common],
                'tool_ids':[],'basis_refs':[common],'validity':window}
            objects.append({'ref':initial_authority,'value':initial_grant});grants.append(deepcopy(initial_grant))
            lines=[{'local_key':'batch-1','requirement_ref':requirement,'product_ref':product['product_ref'],
                'quantity':product['quantity'],'batch_price':delivery['price']}]
            add(offer['ref'],supplier_id=supplier,buyer_id=org,payer_id=org,terms_ref=terms['ref'],requirement_refs=[requirement],
                lines=lines,status='active',author_actor_id=supplier,author_organization_id=supplier,author_function_ref=source_function,
                author_authority_ref=initial_authority,author_action_id='SUPPLIER-A03',authored_at=start,evidence_refs=[original_basis])
            add(terms['ref'],offer_ref=offer['ref'],supplier_id=supplier,buyer_id=org,payer_id=org,requirement_refs=[requirement],lines=lines,
                receiving_window_ref=receiving,delivery_window_ref=original_window,destination_ref=delivery['destination_ref'],
                inspection_rule_ref=inspection,payment_rule_ref=payment,gross_price=delivery['price'],binding_ref=binding,evidence_refs=[original_basis])
            typed_terms=ContractorPlanningActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(terms['ref']),objects[-1]['value'])
            add(permission,mandate_ref=mandate,actor_id=org,function_ref=function,organization_id=org,permitted=known(True),
                offer_ref=offer['ref'],terms_ref=terms['ref'],terms_sha256=content_digest(typed_terms))
            objects.append({'ref':evidence,'value':{'ref':evidence,'source_kind':'synthetic','basis_kind':'observed',
                'locator':'actual-supplier-quote-and-acceptance-support-independent-received-commercial-views','content_hash':None,'effective_window':window}})
            disclosures.append({'supplier_id':supplier,'offer_ref':offer['ref'],'authority_ref':permission,'evidence_ref':evidence,
                'requirement_links':[{'supply_requirement_ref':requirement,'quote_requirement_refs':product['requirement_refs']}],
                'payment_rules':terms['payment_rules'],'shared_evidence_refs':[original_basis,common],
                'included_service_refs':delivery['included_service_refs'],
                'substitutions':[{'supply_requirement_ref':requirement,'authority_ref':substitution,
                    'deviation_refs':deepcopy(deviations)}] if substitution is not None else []})
        grant={'ref':authority,'organization_id':org,'actor_id':org,'function_ref':function,'action_ids':['CONTRACTOR-A05'],
            'scopes':[scope],'readable_refs':[],'tool_ids':[],'basis_refs':[common],'validity':window}
        objects.append({'ref':authority,'value':grant});candidate=rr('CandidateSet','current-quote')
        objects.append({'ref':candidate,'value':{'operation_id':tag,'scope':scope,'as_of':now,'candidates':[],
            'search_profile_ref':rr('Profile','explicit-contractor-preference')}})
        visible=[r['ref'] for r in objects];grant['readable_refs']=visible;grants.append(deepcopy(grant))
        context={'run_id':first['context']['run_id'],'actor_id':org,'function_ref':function,'authorization_refs':[authority],
            'operation_id':tag,'contract_ref':ref('ActionContract','CONTRACTOR-A05'),'task_ref':rr('DecisionTask','procurement'),
            'scope':scope,'business_time':now,'read_token':tag+'-read','visible_refs':visible,'candidate_set_ref':candidate,'execution_mode':'rule'}
        inputs={'work_basis':{'kind':'contract','contract_ref':mandate},'authorized_scope_ref':scope,'dependency_refs':[],
            'design_refs':[],'capacity_ref':capacity,'supplier_offer_refs':[],'work_method_refs':[]}
        for row in objects:
            value=deepcopy(row['value'])
            if row['ref']['kind']=='Evidence' and value['content_hash'] is None:value['content_hash']='0'*64
            ContractorPlanningActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
        if len({p.get('require_native_award',False) for p in supplied})!=1:
            raise ValueError('Supplier sources disagree on their actual native award requirement')
        plans.append(ContractorSupplyPlan.model_validate({'organization_id':org,'project_id':project,'tick':tick,'context':context,
            'action_input':inputs,'objects':objects,'native_evidence_ref':native,'disclosures':disclosures,'repeat_supplier_priority_penalty':2,
            'require_native_award':first.get('require_native_award',False),
            'utility':{'value':'0.8','unit':'score','basis_ref':basis},'probability':{'value':'1','unit':'probability','basis_ref':basis}}).model_dump(mode='json'))
    return plans
