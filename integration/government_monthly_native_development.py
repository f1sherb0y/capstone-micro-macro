"""Declare original organization-only private feedback mandates before execution."""
from copy import deepcopy

from integration.contractor_tender_development import ref
from integration.government_approval_native_learning_development import feedback_plan
from integration.government_monthly_native import GovernmentMonthlyPlan


def monthly_plans(intake_plans,grants,*,ticks):
    originals={}
    for plan in intake_plans:originals.setdefault(plan['organization_id'],plan)
    result=[]
    for org,intake in originals.items():
        original=deepcopy(intake);context=original['context'];function=context['function_ref']
        function_source,=[r['value'] for r in original['objects'] if r['ref']==function]
        scope={'kind':'organization','ref':ref('Organization',org),'coverage_refs':[]}
        original['action_input']['scope']=scope;context['scope']=scope
        original['objects'].append({'ref':scope['ref'],'value':{'ref':scope['ref'],
            'evidence_refs':deepcopy(function_source['basis_refs'])}})
        for tick in ticks:
            feedback=feedback_plan(original,tick=tick,tag=f'{org}-monthly-{tick}',grants=grants)
            result.append(GovernmentMonthlyPlan.model_validate({'organization_id':org,'tick':tick,
                'feedback':feedback}).model_dump(mode='json'))
    return result
