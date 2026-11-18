"""Authenticate a bounded original preparation intention without executing it."""
from copy import deepcopy

from integration.bank_financing_private import checked_result
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.owner_investment_objects import InvestmentComparisonView, InvestmentOptionView, InvestmentPlanView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def preparation_origin(saved, snapshot, *, organizations, worker):
    if organizations is None:
        raise TaskConflict('Preparation history requires its current original organization authority')
    identity = TaskIdentity(**saved['identity'])
    context = ActionContext.model_validate(snapshot['context'])
    result = saved['result']; payload = result.get('payload', {})
    grants = organizations.grants(context, 'OWN-A03', 'Owner')
    readable = {r.key() for grant in grants for r in grant.readable_refs} & {r.key() for r in context.visible_refs}
    if (not grants or any(g.organization_id != identity.organization_id for g in grants)
            or identity.action_id != 'OWN-A03' or identity.role != 'Owner' or identity.purpose != 'action'
            or snapshot['identity'] != identity.as_dict() or context.contract_ref.id != 'OWN-A03'
            or identity.context_sha256 != task_digest(snapshot['context'])
            or identity.input_sha256 != task_digest(snapshot['action_input'])
            or saved['result_sha256'] != task_digest(result)
            or saved['source_reading_sha256'] != task_digest(saved['source_reading'])
            or result.get('kind') != 'completed' or payload.get('choice') != 'authorize_preparation'
            or any(Reference.model_validate(r['ref']).key() not in readable for r in saved['source_reading'])):
        raise TaskConflict('Preparation history changes its original action, result or current authorized reading')
    if checked_result(worker, identity) != saved or worker.snapshots.get(identity) != snapshot:
        raise TaskConflict('Preparation history substitutes its original stored result or snapshot')
    sources = {task_digest(r['ref']): r['projection'] for r in saved['source_reading']}
    option_raw = sources.get(task_digest(payload['option_ref']))
    if option_raw is None:
        raise TaskConflict('Preparation history lost its selected original option')
    option = InvestmentOptionView.model_validate(option_raw)
    if option.preparation_plan_ref is None:
        raise TaskConflict('Preparation history lost its selected original preparation reference')
    comparison_raw = sources.get(task_digest(snapshot['action_input']['comparison_ref']))
    if comparison_raw is None:
        raise TaskConflict('Preparation history lost its original complete comparison')
    comparison = InvestmentComparisonView.model_validate(comparison_raw)
    plan_raw = sources.get(task_digest(option.preparation_plan_ref.model_dump(mode='json')))
    if plan_raw is None:
        raise TaskConflict('Preparation history lost its exact original preparation plan')
    plan = InvestmentPlanView.model_validate(plan_raw)
    if (option.organization_id != identity.organization_id or plan.organization_id != identity.organization_id
            or option.case_ref.model_dump(mode='json') != snapshot['action_input']['case_ref']
            or plan.case_ref != option.case_ref or plan.option_ref != option.ref
            or plan.choice != 'authorize_preparation' or plan.scope.model_dump(mode='json') != payload['scope']
            or comparison.organization_id != identity.organization_id or comparison.case_ref != option.case_ref
            or option.comparison_ref != comparison.ref or option.ref not in comparison.option_refs):
        raise TaskConflict('Preparation history changes its original case, selected plan or bounded scope')
    return {'identity':identity.as_dict(), 'record_sha256':saved['record_sha256'],
        'result_sha256':saved['result_sha256'], 'source_reading_sha256':saved['source_reading_sha256'],
        'option_ref':option.ref.model_dump(mode='json'), 'option_sha256':task_digest(option_raw),
        'plan_ref':plan.ref.model_dump(mode='json'), 'plan_sha256':task_digest(plan_raw),
        'scope':deepcopy(payload['scope']), 'conditions':deepcopy(payload['conditions']),
        'expenditure_cap':plan.expenditure_cap.model_dump(mode='json'),
        'proposed_cash_uses':[r.model_dump(mode='json') for r in plan.cash_uses],
        'proposed_allocations':[r.model_dump(mode='json') for r in plan.allocations],
        'private_intention_only':True,
        'boundary':'Original bounded preparation authorization; no project registration, cash execution, '
            'resource reservation, permit or completed preparation work is inferred.'}
