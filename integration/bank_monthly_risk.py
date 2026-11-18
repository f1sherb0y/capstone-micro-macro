"""Bind actual own received financing inputs and native outcomes without new ledgers."""
from copy import deepcopy

from integration.bank_financing_private import checked_result
from integration.project_financing_feedback import own_financing_history
from src.actions.contracts.bank_monthly_risk_objects import MonthlyBorrowerRiskJudgment
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def result_judgment(saved):
    spaces=[r['projection'] for r in saved['source_reading'] if r['ref']['kind']=='LendingStrategySpace']
    if len(spaces)!=1:raise TaskConflict('Monthly Bank result lost its original strategy space')
    if spaces[0].get('monthly_risk_policy_ref') is None:return None
    judgment=MonthlyBorrowerRiskJudgment.model_validate_json(saved['result']['payload']['note'])
    if judgment.original_strategy_choice!=saved['result']['payload']['choice']:
        raise TaskConflict('Monthly Bank monitoring changes its original strategy selection')
    return judgment


def result_operation(saved):
    judgment=result_judgment(saved)
    return judgment.operation if judgment else ('adjust_credit_terms' if saved['result']['payload']['choice']=='revise_strategy' else 'review_credit_pipeline')


def received_financing_cases(app, *, organization_id, tick):
    """Only the current Bank's actual earlier application inputs, not another lender's data."""
    parent=app.parent
    selections=own_financing_history(app.assembly,organization_id=organization_id,tick=tick,read_guard=parent.read_guard)
    selections=[s for s in selections if s['selected_bank_id']==organization_id and s['native_accepted'] is True]
    tasks=app.assembly.client.tasks.for_organization(run_id=app.assembly.client.run_id,organization_id=organization_id)
    cases=[]
    for record in parent._records():
        scope=record['scope']
        if record['native_request']['agent']['agent_id']!=organization_id or scope['tick']>=tick:continue
        if record['state']!='formed':raise TaskConflict('Monthly Bank risk query encountered an unresolved original financing request')
        request=record['native_request'];inputs=request['inputs']
        if request['agent']['agent_id']!=organization_id or request['operation']!='consider_financing':
            raise TaskConflict('Monthly monitoring substitutes another Bank or original financing operation')
        proposal=[t['output'] for t in tasks if t['identity']['purpose']=='propose' and t['identity']['action_id']=='consider_financing'
            and t['state']=='output_formed' and t['output'].get('factors',{}).get('native_financing_scope')==scope]
        finals=[t['output'] for t in tasks if t['identity']['purpose']=='decide' and t['identity']['action_id']=='bank_project_financing'
            and t['state']=='output_formed' and t['output'].get('data',{}).get('native_financing_scope')==scope]
        if len(proposal)!=1 or len(finals)!=1 or task_digest(proposal[0])!=record['proposal_response_sha256']:
            raise TaskConflict('Monthly monitoring lost its own original financing proposal or final')
        originals={}
        for action,origin in record['steps'].items():
            saved=checked_result(parent.workers[action],TaskIdentity(**origin['identity']))
            if saved['identity']['organization_id']!=organization_id or origin['result_sha256']!=saved['result_sha256']:
                raise TaskConflict('Monthly monitoring substitutes original financing-case micro evidence')
            originals[action]={'identity':saved['identity'],'result_sha256':saved['result_sha256']}
        selected=[s for s in selections if s['project_id']==scope['project_id'] and s['owner_id']==scope['owner_id'] and s['tick']==scope['tick']]
        if len(selected)>1:raise TaskConflict('Monthly monitoring repeats one actual own financing selection')
        cases.append({'organization_id':organization_id,'project_id':scope['project_id'],'borrower_id':scope['owner_id'],
            'observed_tick':scope['tick'],'original_request_sha256':task_digest(request),'original_inputs':deepcopy(inputs),
            'original_micro_results':originals,'proposal_response_sha256':task_digest(proposal[0]),'final_response_sha256':task_digest(finals[0]),
            'actual_own_selection':deepcopy(selected[0]) if selected else None,
            'boundary':'Received historical financing-request estimates for an applicant; selection is not drawdown, debt, cash, payment or default evidence.'})
    return sorted(cases,key=lambda c:(c['observed_tick'],c['project_id'],c['borrower_id']))


def bind_monthly_risk(objects, *, observed, plan):
    spaces=[r['value'] for r in objects if r['ref']['kind']=='LendingStrategySpace']
    if len(spaces)!=1:raise TaskConflict('Monthly risk binding lacks its original strategy space')
    space=spaces[0]
    if space.get('monthly_risk_policy_ref') is None:return
    observation,=[r['value'] for r in objects if r['ref']==space['monthly_risk_observation_ref']]
    if any(observation[k] is not None for k in ('financing_condition','received_cases','prior_own_operations')):
        raise TaskConflict('Monthly Bank risk inputs must remain unbound until actual original observation')
    observation.update(financing_condition={'value':str(observed['macro_environment']['financing_condition_index']),
        'unit':'index','basis_ref':plan.native_evidence_ref.model_dump(mode='json')},
        received_cases=deepcopy(observed['received_own_financing_cases']),prior_own_operations=deepcopy(observed['prior_own_monthly_strategy']))
