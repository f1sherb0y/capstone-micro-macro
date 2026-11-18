"""Declare independent monthly portfolios and policy; bind actual history at use."""
from copy import deepcopy

from integration.bank_financing_strategy_development import extend_plans
from integration.bank_monthly_native import BankMonthlyPlan
from integration.bank_strategy_actions import BankStrategyActionAssembler
from integration.contractor_tender_development import _write, ref
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def extend_monthly(directory, *, run_id, plans, organizations, grants, ticks, max_prior_reviews=1):
    if type(max_prior_reviews) is not int or max_prior_reviews < 1:
        raise ValueError('Monthly Bank review threshold must be a positive explicit count')
    seeds = {}
    for p in plans:
        seeds.setdefault(p['organization_id'], deepcopy(p))
    originals = extend_plans(list(seeds.values()), deepcopy(organizations), deepcopy(grants))
    monthly = []
    for plan in originals:
        bank = plan['organization_id']
        original = plan['steps']['BANK-A01']
        old_scope = original['context']['scope']
        old_tick = plan['tick']
        for tick in range(1, ticks + 1):
            tag = bank + '-monthly-strategy-' + str(tick)
            scope = {'kind': 'organization', 'ref': ref('Organization', bank), 'coverage_refs': []}

            def bind(value):
                if isinstance(value, list):
                    return [bind(v) for v in value]
                if not isinstance(value, dict):
                    return value
                if value == old_scope:
                    return deepcopy(scope)
                if set(value) == {'kind', 'id', 'version'}:
                    if value == original['context']['business_time']['clock_ref'] or value['kind'] == 'ActionContract':
                        return deepcopy(value)
                    return ref(value['kind'], tag + '-' + value['kind'] + '-' + task_digest(value)[:12])
                result = {k: bind(v) for k, v in value.items()}
                if set(value) == {'clock_ref', 'offset'} and value['offset'] == old_tick:
                    result['offset'] = tick
                return result

            step = bind(original)
            context = step['context']
            context.update(operation_id=tag, read_token=tag+'-read',
                task_ref=ref('DecisionTask',tag), candidate_set_ref=ref('CandidateSet',tag))
            native = bind(plan['strategy_feedback']['evidence_ref'])
            observation = bind(plan['strategy_feedback']['observation_ref'])
            original_native = bind(plan['native_evidence_ref'])
            for row in step['objects']:
                value = row['value']
                if row['ref']['kind'] == 'Evidence' and row['ref'] == native:
                    value.update(locator='actual-own-earlier-native-Bank-monthly-strategies',content_hash=None)
                elif row['ref']['kind'] == 'Evidence' and row['ref'] == original_native:
                    value.update(locator='explicit-independent-monthly-bank-portfolio-disclosure',
                        content_hash=task_digest({'origin':'synthetic','bank':bank,'tick':tick,
                            'boundary':'Initial detailed portfolio disclosure, not native score-derived cash or a new loan.'}))
                elif row['ref']['kind'] == 'LendingStrategyProfile':
                    threshold = value['signal_tests'][0]
                    threshold['threshold']['value'] = str(max_prior_reviews-1 if threshold['predicate']=='at_most' else max_prior_reviews)
                    if threshold['predicate']=='at_least' and bank!='finance-bank-a':
                        value['maximum_new_commitment']['value']['value']='100000000'
                elif row['ref']['kind'] == 'CandidateSet':
                    row['ref']=deepcopy(context['candidate_set_ref'])
                    value['operation_id']=tag
            # Visibility and grants are declared together before any action;
            # no sealed source or future result is renamed after execution.
            visible=[r['ref'] for r in step['objects']]
            context['visible_refs']=deepcopy(visible)
            if context['business_time']['clock_ref']!=original['context']['business_time']['clock_ref']:
                raise ValueError('Monthly Bank sources must retain the original shared business clock')
            grant,=[r['value'] for r in step['objects'] if r['ref'] in context['authorization_refs']]
            grant['readable_refs']=deepcopy(visible)
            assignment,=[r['value'] for r in step['objects'] if r['ref']==context['function_ref']]
            organizations[bank]['assignments'].append(deepcopy(assignment))
            grants.append(deepcopy(grant))
            for row in step['objects']:
                value=deepcopy(row['value'])
                if row['ref']['kind']=='Evidence' and value['content_hash'] is None:
                    value['content_hash']='0'*64
                if row['ref']==observation:
                    endpoint={'value':'0','unit':'count','basis_ref':native}
                    value['interval']={'state':'known','value':{'lower':endpoint,'upper':endpoint}}
                BankStrategyActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
            monthly.append(BankMonthlyPlan.model_validate({'organization_id':bank,'tick':tick,**step,
                'native_evidence_ref':native,'observation_ref':observation,
                'utility':bind(plan['utility']),'probability':bind(plan['probability'])}).model_dump(mode='json'))
    for plan in plans:
        quote=plan['steps']['BANK-A04']
        evidence=ref('Evidence',quote['context']['operation_id']+'-actual-monthly-strategy')
        quote['objects'].append({'ref':evidence,'value':{'ref':evidence,'source_kind':'synthetic','basis_kind':'observed',
            'locator':'actual-own-earlier-monthly-strategy-and-independent-quote-authority',
            'content_hash':None,'effective_window':None}})
        policy,=[r['value'] for r in quote['objects'] if r['ref']['kind']=='QuoteAuthorityPolicy']
        policy['evidence_refs'].append(evidence)
        quote['context']['visible_refs'].append(evidence)
        for grant in grants:
            if grant['ref'] in quote['context']['authorization_refs']:
                grant['readable_refs'].append(evidence)
        for row in quote['objects']:
            if row['ref'] in quote['context']['authorization_refs']:
                row['value']['readable_refs'].append(evidence)
        plan['monthly_strategy_evidence_ref']=evidence
    return _write(directory,'bank-monthly-strategy-input.json',{
        'schema_version':'bank-monthly-strategy-input.v1','run_id':run_id,'plans':monthly})
