"""Explicit synthetic A01 policies; future feedback remains unbound until use."""
from copy import deepcopy

from integration.bank_strategy_actions import BankStrategyActionAssembler
from integration.contractor_tender_development import known, ref
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def extend_plans(plans, organizations, grants, *, feedback_basis='selected_financing'):
    if feedback_basis not in {'selected_financing', 'unconfirmed_arrangement_review'}:
        raise ValueError('Bank strategy requires an explicitly supported own feedback basis')
    for plan in plans:
        quote=plan['steps']['BANK-A04'];credit=plan['steps']['BANK-A03']
        bank=plan['organization_id'];tag=quote['context']['operation_id']+'-strategy'
        rr=lambda kind,name:ref(kind,tag+'-'+name)
        context=quote['context'];scope=deepcopy(context['scope']);point=context['business_time']
        clock=point['clock_ref'];window={'start':{'clock_ref':clock,'offset':0},'end':{'clock_ref':clock,'offset':99},'bounds':'closed_open'}
        basis=plan['utility']['basis_ref'];native=plan['native_evidence_ref']
        history_name = 'unconfirmed-arrangement-history' if feedback_basis == 'unconfirmed_arrangement_review' else 'selected-history'
        count_name = 'unconfirmed-arrangement-count' if feedback_basis == 'unconfirmed_arrangement_review' else 'selected-count'
        feedback=rr('Evidence',history_name);observation=rr('Observation',count_name)
        function=rr('FunctionAssignment','lending-strategy');authority=rr('Authorization','strategy-authority')
        base,restricted=rr('LendingStrategyProfile','new-business'),rr('LendingStrategyProfile','repeat-borrower')
        objects=[]
        def add(kind,name,**value):
            identity=rr(kind,name)
            objects.append({'ref':identity,'value':{**({'function_ref':identity} if kind=='FunctionAssignment' else {'ref':identity}),**value}})
            return identity
        # Preserve exactly the independently supplied portfolio/capacity and all
        # original occupied commitments. The strategy adds no financed loan.
        include={basis['id'],native['id']}
        for row in credit['objects']:
            if row['ref']['kind'] in {'FinancePortfolio','LendingCapacity','FinanceCommitment'} or row['ref']['id'] in include:
                copied=deepcopy(row)
                if copied['ref']['kind']=='FinancePortfolio':copied['value']['obligation_refs']=[]
                objects.append(copied)
        portfolio=next(r['ref'] for r in objects if r['ref']['kind']=='FinancePortfolio')
        capacity=next(r['ref'] for r in objects if r['ref']['kind']=='LendingCapacity')
        assignment={'role':'Bank','function_ref':function,'configuration_version':'1','basis_refs':[basis]}
        objects.append({'ref':function,'value':assignment})
        organizations[bank]['assignments'].append(deepcopy(assignment))
        grant={'ref':authority,'organization_id':bank,'actor_id':organizations[bank]['actor_id'],'function_ref':function,
            'action_ids':['BANK-A01'],'scopes':[scope],'readable_refs':[],'tool_ids':[],'basis_refs':[basis],'validity':window}
        objects.append({'ref':authority,'value':grant})
        add('Evidence',history_name,source_kind='synthetic',basis_kind='observed',
            locator=('actual-own-bank-earlier-unconfirmed-A05-reviews-for-current-borrower'
                if feedback_basis == 'unconfirmed_arrangement_review' else 'actual-own-bank-earlier-selections-for-current-borrower'),
            content_hash=None,effective_window=window)
        add('Observation',count_name,recipient_lender_id=bank,scope_ref=scope,interval=known(None),
            observed_at=point,available_at=point,effective_window=window,evidence_refs=[feedback])
        add('MarketObservation','new-business-history',recipient_lender_id=bank,observation_ref=observation,
            effective_window=window,evidence_refs=[feedback])
        money=lambda value:{'value':value,'currency':'HKD','basis_ref':basis}
        measure=lambda value:{'value':value,'unit':'count','basis_ref':basis}
        # A transparent declared policy: one earlier actual selection for the
        # same borrower pauses further new quotations. It predicts no default.
        for name,ceiling,priority,predicate,threshold in [('new-business','100000000',1,'at_most','0'),
                ('repeat-borrower','0',2,'at_least','1')]:
            add('LendingStrategyProfile',name,lender_id=bank,scope_ref=scope,author_actor_id=organizations[bank]['actor_id'],
                author_function_ref=function,authority_ref=authority,originating_action_id='BANK-A01',
                maximum_new_commitment=known(money(ceiling)),maximum_due_obligations=known(money('0')),
                obligation_horizon=window,signal_tests=[{'observation_ref':observation,'predicate':predicate,'threshold':measure(threshold)}],
                selection_priority=known(priority),modifies_existing_terms=False,effective_window=window,evidence_refs=[basis])
        space=add('LendingStrategySpace','strategy-space',lender_id=bank,scope_ref=scope,current_strategy_ref=known(base),
            candidate_refs=known([restricted]),market_refs=[rr('MarketObservation','new-business-history')],policy_refs=[],
            investigation_issue_refs=[rr('Issue','strategy-investigation')],selection_rule='retain_if_eligible_else_lowest_priority',
            effective_window=window,evidence_refs=[basis])
        add('Issue','strategy-investigation',lender_id=bank,scope_ref=scope,subject_refs=[space],status='open',
            effective_window=window,evidence_refs=[basis])
        candidate=rr('CandidateSet','strategy-candidates')
        objects.append({'ref':candidate,'value':{'operation_id':tag,'scope':scope,'as_of':point,
            'candidates':[{'ref':restricted,'permitted_choices':['revise_strategy']}],
            'search_profile_ref':rr('Profile','supplied-bank-strategy')}})
        grant['readable_refs']=[r['ref'] for r in objects]
        grants.append(deepcopy(grant))
        strategy_context={**deepcopy(context),'function_ref':function,'authorization_refs':[authority],
            'operation_id':tag,'contract_ref':ref('ActionContract','BANK-A01'),'task_ref':rr('DecisionTask','strategy'),
            'read_token':tag+'-read','visible_refs':grant['readable_refs'],'candidate_set_ref':candidate}
        strategy_input={'portfolio_ref':portfolio,'capacity_ref':capacity,'obligation_refs':[],
            'market_refs':[rr('MarketObservation','new-business-history')],'policy_refs':[],'strategy_space_ref':space}
        plan['steps']['BANK-A01']={'context':strategy_context,'action_input':strategy_input,'objects':objects}
        handoff=rr('Evidence','actual-strategy-quote-limit')
        quote['objects'].append({'ref':handoff,'value':{'ref':handoff,'source_kind':'synthetic','basis_kind':'observed',
            'locator':'actual-original-A01-result-and-independent-A04-ceiling','content_hash':None,'effective_window':window}})
        quote_policy=next(r['value'] for r in quote['objects'] if r['ref']['kind']=='QuoteAuthorityPolicy')
        quote_policy['evidence_refs'].append(handoff)
        quote['context']['visible_refs'].append(handoff)
        quote_grant=next(r['value'] for r in quote['objects'] if r['ref']==quote['action_input']['authority_ref'])
        quote_grant['readable_refs'].append(handoff)
        original_grant=next(g for g in grants if g['ref']==quote_grant['ref'])
        original_grant['readable_refs']=deepcopy(quote_grant['readable_refs'])
        plan['strategy_feedback']={'observation_ref':observation,'evidence_ref':feedback,
            'quote_policy_ref':quote_policy['ref'],'quote_evidence_ref':handoff,'basis':feedback_basis}
        for row in objects:
            value=deepcopy(row['value'])
            if row['ref']['kind']=='Evidence' and value['content_hash'] is None:value['content_hash']='0'*64
            if row['ref']==observation:
                endpoint={'value':'0','unit':'count','basis_ref':feedback}
                value['interval']=known({'lower':endpoint,'upper':endpoint})
            BankStrategyActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
    return plans
