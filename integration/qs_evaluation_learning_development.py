"""Declare private QS recording inputs before any actual evaluation exists."""
from copy import deepcopy

from integration.contractor_tender_development import known, ref
from integration.qs_evaluation_learning import QSEvaluationLearningPlan
from integration.qs_learning_actions import QSLearningActionAssembler
from src.actions.contracts.common import Reference


def learning_plan(evaluation, *, tick, authorizations):
    context = deepcopy(evaluation['context'])
    org = evaluation['organization_id']
    scope = context['scope']
    point = {**context['business_time'], 'offset': tick}
    tag = context['operation_id'] + '-learning-' + str(tick)
    rr = lambda kind, name: ref(kind, tag + '-' + name)
    original_grant, = [r['value'] for r in evaluation['objects'] if r['ref'] == context['authorization_refs'][0]]
    basis = original_grant['basis_refs'][0]
    window = original_grant['validity']
    # Reuse original scope, function and explicit initial assumption evidence.
    # Unbound per-bid evidence is not copied into the learning input.
    objects = [deepcopy(r) for r in evaluation['objects'] if
        r['ref'] in [scope['ref'], *scope['coverage_refs'], context['function_ref'], point['clock_ref']]
        or r['ref']['kind'] == 'Evidence' and r['value']['content_hash'] is not None]
    grant_ref = rr('Authorization', 'private-record-only')
    strategy, state = rr('Strategy', 'private'), rr('QSLearningState', 'current')
    decision, capability = rr('QSLearningDecision', 'record'), rr('Capability', 'unchanged')
    native, history = rr('Evidence', 'actual-monthly-request'), rr('Evidence', 'actual-own-query')
    feedback, candidate = rr('Feedback', 'query-result'), rr('CandidateSet', 'record')
    for reference, locator in [(native, 'original-native-monthly-request'), (history, 'authorized-own-qs-evaluation-query-not-delivery')]:
        objects.append({'ref': reference, 'value': {'ref': reference, 'source_kind': 'synthetic',
            'basis_kind': 'observed', 'locator': locator, 'content_hash': None, 'effective_window': window}})

    def put(reference, *, authored=True, **fields):
        value = {'ref': reference, 'scope': scope, 'available_at': point, 'effective_window': window,
                 'evidence_refs': [basis, native, history]}
        if authored:
            value.update(author_actor_id=context['actor_id'], author_organization_id=org,
                author_function_ref=context['function_ref'], author_authority_ref=grant_ref,
                author_action_id='QS-A12', authored_at=point)
        objects.append({'ref': reference, 'value': {**value, **fields}})

    put(strategy, organization_id=org, learning_state_ref=state, decision_profile_ref=decision,
        judgments=[], effect='future_business_judgments_only')
    put(state, authored=False, organization_id=org, strategy_ref=strategy, capability_ref=capability,
        learning_profile_ref=None, received_feedback_refs=[feedback], applied_feedback_refs=[], execution_refs=[],
        coverage='complete', as_of=point, forecast_refs=[], outcome_refs=[], applied_error_pair_keys=[])
    put(decision, organization_id=org, strategy_ref=strategy, actor_id=context['actor_id'],
        function_ref=context['function_ref'], authority_ref=grant_ref, business_key=tag,
        choice='record_feedback', feedback_refs=[feedback], interpretation='Await actual own evaluation query.',
        assessment_ref=None, training_profile_ref=None, forecast_ref=None, outcome_ref=None, error_result_ref=None)
    put(capability, organization_id=org, verified_capability_codes=[], qualification_refs=[], status='current')
    put(feedback, recipient_organization_id=org, received_at=point,
        event={'event_key': tag + '-pending-query', 'subject_ref': history, 'subject_sha256': None,
               'occurred_at': point, 'kind': 'review', 'outcomes': []},
        event_sha256=None, verified=known(True), status='verified')
    grant = {'ref': grant_ref, 'organization_id': org, 'actor_id': context['actor_id'],
        'function_ref': context['function_ref'], 'action_ids': ['QS-A12'], 'scopes': [scope],
        'readable_refs': [], 'tool_ids': [], 'basis_refs': [basis], 'validity': window}
    objects.extend([{'ref': grant_ref, 'value': grant}, {'ref': candidate, 'value': {
        'operation_id': tag, 'scope': scope, 'as_of': point, 'candidates': [
            {'ref': decision, 'permitted_choices': ['record_feedback']}], 'search_profile_ref': rr('Profile', 'private')}}])
    visible = [r['ref'] for r in objects]
    grant['readable_refs'] = deepcopy(visible)
    authorizations.append(deepcopy(grant))
    context.update(operation_id=tag, contract_ref=ref('ActionContract', 'QS-A12'),
        task_ref=rr('DecisionTask', 'record'), business_time=point, read_token=tag + '-read',
        visible_refs=visible, authorization_refs=[grant_ref], candidate_set_ref=candidate)
    plan = QSEvaluationLearningPlan.model_validate({'organization_id': org, 'tick': tick, 'context': context,
        'action_input': {'scope': scope, 'forecast_refs': [], 'outcome_refs': [], 'feedback_refs': [feedback],
            'comparability_result_ref': None, 'learning_profile_ref': None, 'strategy_ref': strategy},
        'objects': objects, 'native_evidence_ref': native, 'history_evidence_ref': history, 'feedback_ref': feedback})
    for item in plan.objects:
        value = deepcopy(item['value'])
        if item['ref']['kind'] == 'Evidence' and value['content_hash'] is None:
            value['content_hash'] = '0' * 64
        if item['ref']['kind'] == 'Feedback':
            value['event']['subject_sha256'] = value['event_sha256'] = '0' * 64
        QSLearningActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(item['ref']), value)
    return plan.model_dump(mode='json')
