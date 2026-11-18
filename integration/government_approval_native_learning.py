"""Private original GOV-A12 reflection on authenticated own native history."""
from copy import deepcopy

from pydantic import model_validator

from integration.bank_financing_private import checked_result, evidence_binding
from src.actions.contracts.common import ActionContext, StrictRecord, ref_type
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class GovernmentApprovalFeedbackPlan(StrictRecord):
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    history_evidence_ref: ref_type('Evidence')
    history_feedback_ref: ref_type('Feedback')

    @model_validator(mode='after')
    def exact_sources(self):
        if (self.context.contract_ref.id!='GOV-A12' or self.context.execution_mode=='offline_fixture'
                or self.context.scope.model_dump(mode='json')!=self.action_input.get('scope')
                or self.action_input.get('feedback_refs')!=[self.history_feedback_ref.model_dump(mode='json')]
                or self.action_input.get('visible_statistic_refs')!=[]
                or self.action_input.get('policy_control_profile_ref') is not None
                or len({task_digest(r['ref']) for r in self.objects})!=len(self.objects)):
            raise ValueError('Native approval feedback changes its original action, scope or own history sources')
        by_ref={task_digest(r['ref']):r['value'] for r in self.objects}
        profile=by_ref.get(task_digest(self.action_input['observation_profile_ref']))
        authority=by_ref.get(task_digest(self.action_input['working_authority_ref']))
        feedback=by_ref.get(task_digest(self.history_feedback_ref.model_dump(mode='json')))
        if (profile is None or authority is None or feedback is None or profile['choice']!='record_feedback'
                or authority['allowed_choices']!=['record_feedback'] or profile['execution_refs']
                or profile['investigation_request'] is not None or profile['work_plan'] is not None
                or profile['policy_proposal'] is not None
                or feedback['event_source_ref']!=self.history_evidence_ref.model_dump(mode='json')
                or feedback['status']!='verified' or feedback['kind']!='case_experience'):
            raise ValueError('Native history reflection cannot invent work, policy, formal execution or external feedback')
        return self


def feedback_sources(plan,*,observed):
    """Bind the actual own authorized query, without claiming external delivery."""
    feedback=plan.feedback
    objects=deepcopy(feedback.objects)
    history={'source':'authorized_own_native_approval_history_query',
        'organization_id':plan.organization_id,'as_of_tick':plan.tick,
        'outcomes':deepcopy(observed['prior_approval_decisions']),
        'limits':'Own actual approval outcomes only; no complaint, policy effect, payment or external delivered receipt.'}
    if 'prior_monthly_feedback' in observed:
        history['prior_monthly_feedback']=deepcopy(observed['prior_monthly_feedback'])
        history['limits']='Own actual approval and monthly feedback operations only; no complaint, policy effect, payment or external delivered receipt.'
    evidence_binding(objects,feedback.history_evidence_ref.model_dump(mode='json'),history)
    source,=[r['value'] for r in objects if r['ref']==feedback.history_evidence_ref.model_dump(mode='json')]
    row,=[r['value'] for r in objects if r['ref']==feedback.history_feedback_ref.model_dump(mode='json')]
    if row['event_source_sha256'] is not None:
        raise TaskConflict('Own feedback history requires its explicitly unbound source digest')
    row['event_source_sha256']=task_digest(source)
    # This is the received result of this actual private query. It does not
    # pretend that every source event was externally delivered at this time.
    row['event_key']='own-native-history-query:'+task_digest(history)
    profile,=[r['value'] for r in objects if r['ref']==feedback.action_input['observation_profile_ref']]
    outcomes=history['outcomes'];completed=sum(r.get('completed') is True for r in outcomes)
    rectification=sum(r.get('native_outcome')=='rectification_required' for r in outcomes)
    approval=sum(r['accepted'] is True for r in outcomes)
    profile['interpretation']=(f'Own authenticated prior approval outcomes: {len(outcomes)}; '
        f'micro approval opinions: {approval}; actual completed: {completed}; '
        f'actual completion rectification: {rectification}. Approval opinions do not certify '
        'physical inspection, payment, debt clearance or native completion. '
        'Empty history means no authenticated earlier outcome, not zero defects or proven performance.')
    if 'prior_monthly_feedback' in observed:
        profile['interpretation']+=f" Prior own actual monthly feedback operations: {len(observed['prior_monthly_feedback'])}; no policy change is inferred."
    evidence_binding(objects,feedback.native_evidence_ref.model_dump(mode='json'),observed)
    if profile.get('monthly_policy_ref') is not None:
        from integration.government_monthly_business import bind_observation
        bind_observation(plan,objects,observed)
    return objects


def feedback_origin(app,plan,record):
    saved=checked_result(app.feedback_worker,TaskIdentity(**record['feedback_identity']))
    from integration.government_history_authority import authorize_government_history
    authorize_government_history(app.assembly,TaskIdentity(**record['feedback_identity']),
        organizations=app.parent.organizations,tick=app.assembly.engine.current_tick,saved=saved)
    original=saved['result'].get('payload',{})
    if (saved['result_sha256']!=record['feedback_result_sha256'] or original.get('choice')!='record_feedback'
            or original.get('scope')!=plan.feedback.action_input['scope']
            or original.get('feedback_refs')!=plan.feedback.action_input['feedback_refs']):
        raise TaskConflict('Approval needs its original completed own GOV-A12 feedback record')
    sources={task_digest(r['ref']):r['projection'] for r in saved['source_reading']}
    evidence=sources.get(task_digest(plan.feedback.native_evidence_ref.model_dump(mode='json')))
    history=sources.get(task_digest(plan.feedback.history_evidence_ref.model_dump(mode='json')))
    feedback=sources.get(task_digest(plan.feedback.history_feedback_ref.model_dump(mode='json')))
    profile=sources.get(task_digest(plan.feedback.action_input['observation_profile_ref']))
    if (evidence is None or evidence.get('content_hash')!=task_digest(record['feedback_observed'])
            or history is None or feedback is None or feedback['event_source_sha256']!=task_digest(history)
            or profile is None or original.get('interpretation')!=profile['interpretation']):
        raise TaskConflict('Approval feedback lost its actual original history query or interpretation')
    return {'action_id':'GOV-A12','task_key':TaskIdentity(**record['feedback_identity']).key,
        'result_sha256':saved['result_sha256'],'record_sha256':saved['record_sha256'],
        'source_reading_sha256':saved['source_reading_sha256'],'interpretation':original['interpretation'],
        'observed_history_sha256':task_digest(record['feedback_observed']['prior_approval_decisions'])}
