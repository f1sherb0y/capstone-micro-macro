"""Declare a finite private intake preference before any simulated selection."""
from copy import deepcopy

from integration.contractor_tender_development import known, ref
from integration.professional_feedback_development import feedback_plan
from integration.native_lifecycle_actions import NativeLifecyclePlan
from src.methods.architect_learning import LEARNING_METHOD


def judgment_plan(intake, *, grant):
    plan = feedback_plan(intake, grant=grant, event_type='consultant_team_appointed')
    tag = plan['plan_id']
    rr = lambda kind, name: ref(kind, tag + '-' + name)
    find = lambda reference: next(row['value'] for row in plan['objects'] if row['ref'] == reference)
    strategy = find(plan['action_input']['strategy_ref'])
    state = find(strategy['learning_state_ref'])
    decision = find(strategy['decision_profile_ref'])
    profile, dimension, rule = rr('LearningProfile', 'private-policy'), rr('JudgmentDimension', 'cooperation'), rr('LearningRule', 'selected-policy')
    evaluate, pause = rr('JudgmentValue', 'evaluate-intake'), rr('JudgmentValue', 'pause-intake')
    assessment = rr(intake['role'] + 'LearningAssessment', 'saved-private-assessment')
    common = {key: deepcopy(value) for key, value in strategy.items() if key in {
        'scope', 'available_at', 'effective_window', 'evidence_refs', 'author_actor_id',
        'author_organization_id', 'author_function_ref', 'author_authority_ref', 'author_action_id', 'authored_at'}}

    def put(reference, **fields):
        plan['objects'].append({'ref': reference, 'value': {**deepcopy(common), 'ref': reference,
            'organization_id': intake['organization_id'], **fields}})

    put(profile, strategy_ref=strategy['ref'], enabled=known(True),
        calculation_method_ref=LEARNING_METHOD.model_dump(mode='json'), dimension_refs=[dimension],
        rule_refs=[rule], training_profile_refs=[], effect='future_judgments_and_training_proposals_only')
    put(dimension, learning_profile_ref=profile, value_refs=[evaluate, pause], outcome_codes=['appointed'], purpose='cooperation')
    put(evaluate, dimension_ref=dimension, description='Evaluate new intake under the original business policy.',
        effect='future_private_judgment_only')
    put(pause, dimension_ref=dimension, description='Recommend pausing new intake after actual own selection.',
        effect='future_private_judgment_only')
    put(rule, learning_profile_ref=profile,
        rule={'rule_ref': rule, 'dimension_ref': dimension, 'outcome_codes': ['appointed'],
            'selected_value_ref': pause, 'minimum_samples': 1, 'priority': 0},
        explanation='Actual own selection triggers the explicit private intake preference; it proves no physical capacity or performance improvement.')
    strategy['judgments'] = [{'dimension_ref': dimension, 'selected_value_ref': evaluate,
        'explanation': 'Initial explicit preference: evaluate new intake.'}]
    state['learning_profile_ref'] = profile
    decision.update(choice='update_judgment', assessment_ref=assessment,
        interpretation='Await actual own selection before simulation-only private assessment.')
    find(plan['context']['candidate_set_ref'])['candidates'] = [
        {'ref': pause, 'permitted_choices': ['update_judgment']}]
    plan['action_input']['learning_profile_ref'] = profile
    plan['context']['execution_mode'] = 'offline_fixture'
    plan['context']['visible_refs'] = [deepcopy(row['ref']) for row in plan['objects']] + [assessment]
    grant['readable_refs'].extend(deepcopy(plan['context']['visible_refs']))
    plan['private_intake_judgment'] = {'effect': 'simulation_private_intake_recommendation_only',
        'learning_profile_ref': profile, 'dimension_ref': dimension, 'evaluate_value_ref': evaluate,
        'pause_value_ref': pause, 'assessment_ref': assessment}
    return NativeLifecyclePlan.model_validate(plan).model_dump(mode='json')
