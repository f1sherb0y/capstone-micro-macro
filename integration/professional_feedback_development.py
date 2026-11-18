"""Declare private A12 recording sources before native appointment decisions.

Only the actual recipient's native event and original A02 transports bind the
feedback at runtime. Initial permissions/capabilities remain synthetic inputs.
"""
from copy import deepcopy

from integration.contractor_tender_development import known, ref
from integration.native_lifecycle_actions import NativeLifecyclePlan


def feedback_plan(intake, *, grant, event_type='appointment_decision'):
    if event_type not in {'appointment_decision', 'consultant_team_appointed', 'final_account_settled'}:
        raise ValueError('Professional feedback requires a native intake decision or actual team selection')
    role, org = intake['role'], intake['organization_id']
    if event_type == 'final_account_settled' and role != 'QS':
        raise ValueError('Aggregate settlement feedback supports only its original QS recipient')
    context = deepcopy(intake['context'])
    scope, point = context['scope'], context['business_time']
    tag = context['operation_id'] + ('-native-feedback' if event_type == 'appointment_decision'
        else '-native-settlement-feedback' if event_type == 'final_account_settled' else '-native-appointment-feedback')
    rr = lambda kind, name: ref(kind, tag + '-' + name)
    strategy, state = rr('Strategy', 'private'), rr(role + 'LearningState', 'initial-record')
    decision, capability = rr(role + 'LearningDecision', 'record'), rr('Capability', 'unchanged')
    native, feedback, candidates = rr('Evidence', 'actual-reception'), rr('Feedback', 'own-decision'), rr('CandidateSet', 'record')
    objects = [deepcopy(r) for r in intake['objects'] if r['ref'] in
        [scope['ref'], context['function_ref'], point['clock_ref']]
        or r['ref']['kind'] == 'WorkScope'
        or r['ref']['kind'] == 'Evidence' and r['value']['content_hash'] is not None]
    basis, window = grant['basis_refs'][0], deepcopy(grant['validity'])
    objects.append({'ref': native, 'value': {'ref': native, 'source_kind': 'synthetic', 'basis_kind': 'observed',
        'locator': 'actual-own-native-' + event_type + '-reception', 'content_hash': None, 'effective_window': window}})

    def put(reference, *, authored=True, **fields):
        value = {'ref': reference, 'scope': scope, 'available_at': point, 'effective_window': window,
            'evidence_refs': [basis, native]}
        if authored:
            value.update(author_actor_id=context['actor_id'], author_organization_id=org,
                author_function_ref=context['function_ref'], author_authority_ref=grant['ref'],
                author_action_id=role.upper() + '-A12', authored_at=point)
        objects.append({'ref': reference, 'value': {**value, **fields}})

    put(strategy, organization_id=org, learning_state_ref=state, decision_profile_ref=decision,
        judgments=[], effect='future_business_judgments_only')
    extra_state = ({'qualification_refs': [], 'applied_qualification_event_refs': []} if role == 'Engineer' else
        {'forecast_refs': [], 'outcome_refs': [], 'applied_error_pair_keys': []} if role == 'QS' else {})
    put(state, authored=False, organization_id=org, strategy_ref=strategy, capability_ref=capability,
        learning_profile_ref=None, received_feedback_refs=[feedback], applied_feedback_refs=[], execution_refs=[],
        coverage='complete', as_of=point, **extra_state)
    extra_decision = ({'qualification_ref': None, 'qualification_update_basis_ref': None} if role == 'Engineer' else
        {'forecast_ref': None, 'outcome_ref': None, 'error_result_ref': None} if role == 'QS' else {})
    put(decision, organization_id=org, strategy_ref=strategy, actor_id=context['actor_id'],
        function_ref=context['function_ref'], authority_ref=grant['ref'], business_key=tag,
        choice='record_feedback', feedback_refs=[feedback], interpretation='Await actual own native decision reception.',
        assessment_ref=None, training_profile_ref=None, **extra_decision)
    put(capability, organization_id=org, verified_capability_codes=[], qualification_refs=[], status='current')
    put(feedback, recipient_organization_id=org, received_at=point,
        event={'event_key': tag + '-unbound', 'subject_ref': native, 'subject_sha256': None,
            'occurred_at': point, 'kind': 'performance' if event_type == 'final_account_settled' else 'market', 'outcomes': []},
        event_sha256=None, verified=known(True), status='verified')
    objects.extend([{'ref': grant['ref'], 'value': grant}, {'ref': candidates, 'value': {
        'operation_id': tag, 'scope': scope, 'as_of': point,
        'candidates': [{'ref': decision, 'permitted_choices': ['record_feedback']}],
        'search_profile_ref': rr('Profile', 'private-record')}}])
    inputs = {'scope': scope, 'strategy_ref': strategy, 'feedback_refs': [feedback], 'learning_profile_ref': None}
    if role == 'Architect':
        inputs['capability_ref'] = capability
    elif role == 'Engineer':
        inputs['qualification_refs'] = []
    else:
        inputs.update(forecast_refs=[], outcome_refs=[], comparability_result_ref=None)
    context.update(operation_id=tag, contract_ref=ref('ActionContract', role.upper() + '-A12'),
        task_ref=rr('DecisionTask', 'record'), read_token=tag + '-read',
        visible_refs=[r['ref'] for r in objects], candidate_set_ref=candidates)
    grant['readable_refs'].extend(deepcopy(context['visible_refs']))
    if role.upper() + '-A12' not in grant['action_ids']:
        grant['action_ids'].append(role.upper() + '-A12')
    return NativeLifecyclePlan.model_validate({'plan_id': tag, 'organization_id': org,
        'project_id': intake['project_id'], 'tick': intake['tick'], 'event_type': event_type,
        'context': context, 'action_input': inputs, 'objects': objects,
        'native_evidence_ref': native,
        'settlement_feedback_ref' if event_type == 'final_account_settled' else 'appointment_feedback_ref': feedback}).model_dump(mode='json')
