"""Explicit Owner portfolio and lawful quote disclosures for the Bank bundle."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from integration.contractor_tender_development import _write, ref, known
from integration.owner_financing_native import OwnerFinancingPlan
from integration.owner_financing_quote_views import disclosure_refs
from integration.owner_financing_actions import OwnerFinancingActionAssembler
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest
from integration.development_owner_funding import initial_owner_fundings


def extend_bundle(directory, *, run_id, bank_plans, settings, native_host, repeat_lender_priority_penalty=0,
        prior_refusal_priority_penalty=0,
        with_arrangement=False,owner_funding=None,arrangement_principal_limits=None,arrangement_capacity_limits=None):
    owner_funding=initial_owner_fundings(owner_funding)
    template_path=Path(__file__).resolve().parents[1]/'tests/fixtures/roles/owner_financing.v1.json'
    template=json.loads(template_path.read_bytes());template_sha=hashlib.sha256(template_path.read_bytes()).hexdigest()
    settings=deepcopy(settings);snapshot=settings['authority']['organization_snapshot']
    organizations={o['organization_id']:o for o in snapshot['organizations']}
    initial_lender='disclosed-other-lender'
    organizations[initial_lender]={'organization_id':initial_lender,'actor_id':initial_lender,
        'source_ids':['synthetic:initial-debt-lender'],'public_description':'Explicit author of assumed pre-existing debt; no native actor is added.',
        'public_location':known('Hong Kong'),'members':[],'assignments':[],'evidence_refs':[]}
    plans=[];grants=[]
    for owner in ['finance-owner-a','finance-owner-b']:
        projects = [(p['project_id'],p['tick']) for p in bank_plans
            if p['organization_id']=='finance-bank-a' and p['borrower_id']==owner]
        for project, tick in projects:
            tag=owner+'-'+project+'-own-finance';rr=lambda kind,name:ref(kind,tag+'-'+name)
            bank_plan=next(p for p in bank_plans if p['organization_id']=='finance-bank-a' and p['borrower_id']==owner and p['project_id']==project)
            clock=bank_plan['steps']['BANK-A04']['context']['business_time']['clock_ref'];point=lambda n:{'clock_ref':clock,'offset':n}
            window={'start':point(0),'end':point(99),'bounds':'closed_open'}
            scope={'kind':'project','ref':ref('Project',project),'coverage_refs':[]}
            basis,native=rr('Evidence','initial-assumptions'),rr('Evidence','native-selection')
            def remap(value):
                if isinstance(value,list):return [remap(v) for v in value]
                if not isinstance(value,dict):
                    return {'owner':owner,'owner-actor':organizations[owner]['actor_id'],
                        'bank':initial_lender,'bank-actor':initial_lender}.get(value,value) if isinstance(value,str) else value
                if set(value)=={'kind','id','version'}:
                    kind,name=value['kind'],value['id']
                    if kind=='Method':return deepcopy(value)
                    if kind=='Evidence':return basis
                    if kind=='OwnerCase':return scope['ref']
                    if kind=='Organization':return ref('Organization',owner)
                    shared = {'Account':'borrower-cash','Debt':'old-debt','Obligation':'due-mirror','Project':'old-project'}
                    if kind in shared:
                        identity=ref(kind,owner+'-'+shared[kind]);identity['version']=str(tick)
                        return identity
                    return rr(kind,name)
                if 'clock_ref' in value and 'offset' in value:return point(0 if value['offset']<=10 else 2 if value['offset']==14 else 6 if value['offset']==20 else 99)
                if value.get('kind')=='assessment_case':return deepcopy(scope)
                result={k:remap(v) for k,v in value.items()}
                if 'coverage_refs' in result:result['coverage_refs']=[]
                if {'value','currency','basis_ref'}<=set(value):result['value']=format(Decimal(value['value'])*1000000,'f')
                return result
            keep={('FunctionAssignment','owner-function'),('FunctionAssignment','bank-function'),('Authorization','owner-authority'),
                ('Authorization','bank-authority'),('Project','prior-project'),('FundingProfile','funding'),('Account','actual-cash'),
                ('FundingSource','cash'),('FundingApproval','nonbank'),('Debt','existing-loan'),('Obligation','existing-payment'),
                ('FinanceOffer','original'),('PartyAcceptance','borrower-acceptance'),('PartyAcceptance','bank-confirmation'),
                ('FinanceArrangement','existing-arrangement'),('TimeWindow','period')}
            objects=[remap(r) for r in template['objects'] if (r['ref']['kind'],r['ref']['id']) in keep]
            named=lambda kind:next(r['value'] for r in objects if r['ref']['kind']==kind)
            money=lambda v:{'value':v,'currency':'HKD','basis_ref':basis}
            source=named('FundingSource');account=named('Account');profile=named('FundingProfile')
            shared=owner_funding.get(owner)
            source.update(actual_cash=known(money('30000000' if shared is None else shared.actual_cash)),
                restricted_cash=known(money('10000000' if shared is None else shared.restricted_cash)),as_of=point(tick))
            account.update(actual_cash=source['actual_cash'],restricted_cash=source['restricted_cash'],as_of=point(tick),
                permitted_project_region_ids=known(list(bank_plan['native_region_ids'].values())))
            # The same initial debt values as disclosed to Bank A03: 15m unpaid
            # principal at native time 2. These are supplied initial assumptions.
            debt=named('Debt');debt['as_of']=point(tick);debt['origin_scope']['coverage_refs']=[]
            obligation=named('Obligation');obligation.update(actual_due=known(money('15000000')),actual_paid=known(money('0')),
                due_at=point(2),as_of=point(tick),component_refs=[ref('SettlementComponent',owner+'-old-principal')])
            purpose_ref=ref('FundingPurpose',owner+'-'+project+'-purpose')
            profile.update(scope_ref=scope,purpose_ref=purpose_ref,policy=known('evaluate'),on_unavailable=known('no_finance'),
                selected_offer_ref=None,application=None,revision_ref=None,question_refs=[],required_condition_refs=[],as_of=point(tick))
            # Bind the actual native request amount at invocation. Timing remains
            # an explicit independent plan, never inferred from macro aggregates.
            profile['funding_lines'][0].update(available=known(money('20000000')),
                planned_use={'state':'unknown','reason_code':'await_current_native_financing_amount','missing_refs':[native]})
            named('TimeWindow').update(start=point(3),end=point(4),bounds='closed_open')
            approval=named('FundingApproval');approval.update(purpose_ref=purpose_ref,scope_ref=scope,release_time=point(6),available_at=point(tick))
            source['releases'][0].update(time=point(6),available_at=point(tick))
            # This 100m independently assumed future approval is not copied from
            # the Bank's 120..130m forecast, and is never credited as actual cash.
            own_grant=next(r['value'] for r in objects if r['ref']==rr('Authorization','owner-authority'))
            old_grant=next(r['value'] for r in objects if r['ref']==rr('Authorization','bank-authority'))
            old_grant['organization_id']=old_grant['actor_id']=initial_lender
            own_fn=next(r['value'] for r in objects if r['ref']==rr('FunctionAssignment','owner-function'))
            old_fn=next(r['value'] for r in objects if r['ref']==rr('FunctionAssignment','bank-function'))
            organizations[owner]['assignments'].append(deepcopy(own_fn));organizations[initial_lender]['assignments'].append(deepcopy(old_fn))
            organizations[initial_lender]['evidence_refs'].append(basis)
            common=bank_plan['steps']['BANK-A04']['objects']
            shared_refs=[ref('Organization',owner),purpose_ref,ref('Evidence',owner+'-assumed-financing-disclosure'),bank_plan['native_project_evidence_ref']]
            objects.extend(deepcopy(r) for r in common if r['ref'] in shared_refs)
            objects.append({'ref':scope['ref'],'value':{'ref':scope['ref'],'owner_organization_id':owner,
                'available_at':point(tick),'status':'active','evidence_refs':[native]}})
            objects.extend([{'ref':basis,'value':{'ref':basis,'source_kind':'synthetic','basis_kind':'assumed',
                'locator':'explicit-owner-initial-portfolio:'+template_sha,'content_hash':task_digest({'template':template_sha,
                    'cash':30000000 if shared is None else shared.actual_cash,
                    'restricted':10000000 if shared is None else shared.restricted_cash,
                    'as_of_tick':tick,'existing_principal_due':15000000,'due_tick':2,
                    'planned_use':'actual-native-requested-financing-amount','planned_tick':3,
                    'independent_future_approved_funding':100000000,'release_tick':6}),
                'effective_window':window}},
                {'ref':native,'value':{'ref':native,'source_kind':'synthetic','basis_kind':'observed',
                    'locator':'actual-owner-financing-selection','content_hash':None,'effective_window':window}}])
            # All quote dependencies are explicitly disclosed; risk observations,
            # Bank capacity, private credit assessments and other accounts are absent.
            disclosures=[];visible=[r['ref'] for r in objects]
            for bank_id in ['finance-bank-a','finance-bank-b']:
                bank_step=next(p for p in bank_plans if (p['organization_id'],p['borrower_id'],p['project_id'])==(bank_id,owner,project))['steps']['BANK-A04']
                refs=disclosure_refs(bank_step['objects'],bank_step['action_input'])
                offer,received=rr('FinanceOffer',bank_id),rr('Evidence',bank_id+'-received-proposal')
                disclosures.append({'bank_id':bank_id,'offer_ref':offer,'evidence_ref':received,'priority':1 if bank_id.endswith('-a') else 2,'readable_refs':refs})
                visible.extend([*refs,offer,received])
            candidate=rr('CandidateSet','received-offers');visible.append(candidate)
            objects.append({'ref':candidate,'value':{'operation_id':tag,'scope':scope,'as_of':point(tick),'candidates':[],
                'search_profile_ref':rr('Profile','declared-finance-candidates')}})
            visible=list({task_digest(r):r for r in visible}.values())
            own_grant['readable_refs']=old_grant['readable_refs']=visible
            grants.extend([deepcopy(own_grant),deepcopy(old_grant)])
            context={'run_id':run_id,'actor_id':organizations[owner]['actor_id'],'function_ref':own_fn['function_ref'],'authorization_refs':[own_grant['ref']],
                'operation_id':tag,'contract_ref':ref('ActionContract','OWN-A05'),'task_ref':rr('DecisionTask','selection'),
                'scope':scope,'business_time':point(tick),'read_token':tag+'-read','visible_refs':visible,
                'candidate_set_ref':candidate,'execution_mode':'rule'}
            inputs={'scope_ref':scope,'borrower_id':owner,'funding_lines':profile['funding_lines'],'debt_refs':profile['debt_refs'],
                'offers':[],'funding_profile_ref':profile['ref']}
            checked=OwnerFinancingPlan.model_validate({'organization_id':owner,'project_id':project,'tick':tick,
                'context':context,'action_input':inputs,'objects':objects,'native_evidence_ref':native,
                'project_evidence_ref':bank_plan['native_project_evidence_ref'],'disclosures':disclosures,
                'repeat_lender_priority_penalty':repeat_lender_priority_penalty,
                'prior_refusal_priority_penalty':prior_refusal_priority_penalty,
                'utility':{'value':'0.7','unit':'score','basis_ref':basis},'probability':{'value':'1','unit':'probability','basis_ref':basis}})
            for row in checked.objects:
                value=deepcopy(row['value'])
                if row['ref']['kind']=='Evidence' and value['content_hash'] is None:value['content_hash']='0'*64
                if row['ref']['kind']=='FundingPurpose' and value['project_region_id']['value'] is None:value['project_region_id']=known('DG')
                OwnerFinancingActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
            plans.append(checked.model_dump(mode='json'))
    snapshot['organizations']=list(organizations.values());snapshot['authorizations'].extend(grants)
    if with_arrangement:
        from integration.bank_arrangement_native_development import extend_sources
        settings['arrangement'] = extend_sources(directory, run_id=run_id, bank_plans=bank_plans,
            owner_plans=plans, snapshot=snapshot, principal_limits=arrangement_principal_limits,
            capacity_limits=arrangement_capacity_limits)
    source=_write(directory,'owner-financing-input.json',{'schema_version':'owner-financing-input.v1','run_id':run_id,'plans':plans})
    settings['owner_financing']={'version':'1',**source}
    native_host['settings']['native_financing_proposal_transport_roles']=[]
    native_host['settings']['native_proposals']=[r for r in native_host['settings']['native_proposals'] if (r['role'],r['operation'])!=('Owner','select_financing_offer')]
    native_host['settings']['native_decisions']=[r for r in native_host['settings']['native_decisions'] if (r['role'],r['decision_type'])!=('Owner','owner_financing_selection')]
    return settings,native_host
