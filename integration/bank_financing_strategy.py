"""Private Bank A01 feedback sources and a bounded A01-to-A04 policy view."""
from copy import deepcopy
from decimal import Decimal

from integration.bank_financing_private import evidence_binding
from integration.project_financing_feedback import own_financing_history
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def selection_feedback(application, plan, request, objects):
    """Count only earlier actual selections disclosed to this Bank/borrower."""
    binding = plan.strategy_feedback
    history = own_financing_history(application.assembly, organization_id=plan.organization_id,
        tick=plan.tick, read_guard=application.read_guard)
    history = [r for r in history if r['owner_id'] == plan.borrower_id]
    if any(r['selected_bank_id'] != plan.organization_id or r['recipient_organization_id'] != plan.organization_id
           or any(k.startswith('micro_') for k in r) for r in history):
        raise TaskConflict('Bank strategy substitutes its own disclosed selection feedback')
    observed = {'scope':{'project_id':plan.project_id,'owner_id':plan.borrower_id,'tick':plan.tick},
        'native_request_sha256':task_digest(request.model_dump(mode='json')),
        'recipient_organization_id':plan.organization_id,'borrower_id':plan.borrower_id,
        'history':history,'selected_count':len(history)}
    count = len(history)
    if binding.basis == 'unconfirmed_arrangement_review':
        reviews = [row for row in application.arrangement.prior_reviews(organization_id=plan.organization_id, tick=plan.tick)
            if row['borrower_id'] == plan.borrower_id]
        if {row['event_id'] for row in reviews} != {row['event_id'] for row in history}:
            raise TaskConflict('Bank strategy review feedback differs from its own actual selections')
        count = sum(row['choice'] != 'confirm' for row in reviews)
        observed.update(basis=binding.basis, arrangement_reviews=reviews, unconfirmed_review_count=count)
    observation, = [r['value'] for r in objects if r['ref'] == binding.observation_ref.model_dump(mode='json')]
    if (observation['recipient_lender_id'] != plan.organization_id
            or observation['scope_ref'] != plan.steps['BANK-A01'].context.scope.model_dump(mode='json')
            or observation['interval'] != {'state':'known','value':None}
            or observation['evidence_refs'] != [binding.evidence_ref.model_dump(mode='json')]):
        raise TaskConflict('Bank feedback count requires its exact unbound private observation')
    measure={'value':str(count),'unit':'count','basis_ref':binding.evidence_ref.model_dump(mode='json')}
    observation['interval']['value']={'lower':deepcopy(measure),'upper':deepcopy(measure)}
    evidence_binding(objects,binding.evidence_ref.model_dump(mode='json'),observed)
    return observed


def strategy_for_quote(record, *, invocation, plan, objects):
    """Apply only a tighter private new-business ceiling within original authority.

    A01 is an internal choice. This view authorizes no extra commitment, and
    neither edits the original independent policy nor registers a policy/loan.
    The original policy and selected strategy hashes remain in the evidence.
    """
    context=plan.steps['BANK-A01'].context
    if (record['identity']['action_id']!='BANK-A01' or record['identity']['organization_id']!=plan.organization_id
            or record['identity']['run_id']!=context.run_id or invocation['context']!=context.model_dump(mode='json')
            or invocation['action_input']!=plan.steps['BANK-A01'].action_input):
        raise TaskConflict('Quote strategy handoff changes its original A01 invocation')
    sources={task_digest(r['ref']):r['projection'] for r in record['source_reading']}
    space=sources[task_digest(plan.steps['BANK-A01'].action_input['strategy_space_ref'])]
    payload=record['result']['payload']
    if payload['choice']=='revise_strategy':
        selected=payload['strategy_ref']
    elif payload['choice']=='retain_strategy' and space['current_strategy_ref']['state']=='known':
        selected=space['current_strategy_ref']['value']
    else:
        raise TaskConflict('Unresolved Bank strategy cannot silently become an unrestricted quotation')
    profile=sources[task_digest(selected)]
    if (profile['lender_id']!=plan.organization_id or profile['scope_ref']!=context.scope.model_dump(mode='json')
            or profile['originating_action_id']!='BANK-A01' or profile['modifies_existing_terms'] is not False
            or profile['maximum_new_commitment']['state']!='known'):
        raise TaskConflict('Quote changes its original private new-business strategy')
    cap=profile['maximum_new_commitment']['value']
    policy,=[r['value'] for r in objects if r['ref']==plan.strategy_feedback.quote_policy_ref.model_dump(mode='json')]
    original=deepcopy(policy)
    if (policy['lender_id']!=plan.organization_id or policy['scope_ref']!=context.scope.model_dump(mode='json')
            or policy['maximum_principal']['state']!='known'):
        raise TaskConflict('Strategy quotation requires its original independent amount authority')
    ceiling=policy['maximum_principal']['value']
    if cap['currency']!=ceiling['currency'] or min(Decimal(cap['value']),Decimal(ceiling['value']))<0:
        raise TaskConflict('Strategy quotation changes original nonnegative currency units')
    observed={'source':'private_original_bank_strategy','identity':record['identity'],
        'task_key':TaskIdentity(**record['identity']).key,'record_sha256':record['record_sha256'],
        'result_sha256':record['result_sha256'],'source_reading_sha256':record['source_reading_sha256'],
        'selected_strategy_ref':selected,'selected_strategy_sha256':task_digest(profile),
        'independent_quote_policy_sha256':task_digest(original),'independent_maximum_principal':deepcopy(ceiling),
        'strategy_maximum_new_commitment':deepcopy(cap)}
    evidence_ref=plan.strategy_feedback.quote_evidence_ref.model_dump(mode='json')
    evidence_binding(objects,evidence_ref,observed)
    policy['maximum_principal']['value']={**ceiling,'value':format(min(Decimal(cap['value']),Decimal(ceiling['value'])),'f'),
        'basis_ref':evidence_ref}
    if evidence_ref not in policy['evidence_refs']:
        policy['evidence_refs'].append(evidence_ref)
    return observed
