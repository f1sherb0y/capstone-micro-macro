"""Declare private feedback authority before any original GOV-A12 execution."""
from copy import deepcopy

from integration.contractor_tender_development import known,ref
from integration.government_approval_native_learning import GovernmentApprovalFeedbackPlan
from integration.government_feedback_actions import GovernmentFeedbackActionAssembler
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def feedback_plan(intake,*,tick,tag,grants):
    org=intake['organization_id'];scope=intake['action_input']['scope']
    actor=intake['context']['actor_id']
    context=deepcopy(intake['context']);point={**context['business_time'],'offset':tick}
    function=context['function_ref'];rr=lambda kind,name:ref(kind,tag+'-feedback-'+name)
    function_source,=[r['value'] for r in intake['objects'] if r['ref']==function]
    basis=function_source['basis_refs'][0];objects=[]
    for reference in (basis,function,scope['ref']):
        objects.append(deepcopy(next(r for r in intake['objects'] if r['ref']==reference)))
    window=deepcopy(next(r['value']['effective_window'] for r in intake['objects'] if r['ref']==basis))
    grant_ref=rr('Authorization','record');profile=rr('ObservationProfile','own-history')
    authority=rr('Authority','private-record-only');native=rr('Evidence','actual-native-request')
    history=rr('Evidence','actual-own-history-query');feedback=rr('Feedback','query-result')
    calendar=rr('ResourceCalendar','unused-no-assignment');candidate=rr('CandidateSet','record')
    for reference,locator in [(native,'actual-native-approval-request'),(history,'authorized-own-native-approval-history-query')]:
        objects.append({'ref':reference,'value':{'ref':reference,'source_kind':'synthetic','basis_kind':'observed',
            'locator':locator,'content_hash':None,'effective_window':window}})
    def row(reference,**value):
        return {'ref':reference,'value':{'ref':reference,'scope':scope,'available_at':point,'effective_window':window,
            'evidence_refs':[basis,native,history],'author_actor_id':actor,'author_organization_id':org,
            'author_function_ref':function,'author_authority_ref':grant_ref,'author_action_id':'GOV-A12',
            'authored_at':point,**value}}
    objects.extend([
        row(feedback,recipient_organization_id=org,event_key=tag+'-pending-actual-own-query',kind='case_experience',
            event_source_ref=history,event_source_sha256=None,observed_at=point,received_at=point,status='verified'),
        row(profile,organization_id=org,actor_id=actor,function_ref=function,authority_ref=grant_ref,
            working_authority_ref=authority,policy_control_profile_ref=None,business_key=tag+'-private-feedback',
            choice='record_feedback',feedback_refs=[feedback],statistic_refs=[],interpretation='Await actual own query.',
            questions=[],investigation_request=None,work_plan=None,policy_proposal=None,execution_refs=[],
            coverage='complete',as_of=point),
        row(authority,organization_id=org,actor_id=actor,function_ref=function,permitted=known(True),
            allowed_choices=['record_feedback'],allowed_input_refs=[feedback,profile,history],allowed_output_requirement_refs=[],
            allowed_instrument_refs=[],allowed_recipient_refs=[],authorized_task_refs=[],required_task_refs=[],
            replacement_assignment_refs=[],calendar_ref=calendar,allowed_window=window,coverage='complete',as_of=point),
    ])
    # Recording feedback does not read or allocate the calendar. This distinct
    # reference grants no scheduling, assignment or resource release authority.
    grant={'ref':grant_ref,'organization_id':org,'actor_id':actor,'function_ref':function,'action_ids':['GOV-A12'],
        'scopes':[scope],'readable_refs':[],'tool_ids':[],'basis_refs':[basis],'validity':window}
    objects.extend([{'ref':grant_ref,'value':grant},{'ref':candidate,'value':{'operation_id':tag+'-GOV-A12',
        'scope':scope,'as_of':point,'candidates':[{'ref':profile,'permitted_choices':['record_feedback']}],
        'search_profile_ref':rr('Profile','private-query')}}])
    visible=[r['ref'] for r in objects];grant['readable_refs']=visible;grants.append(deepcopy(grant))
    context.update(operation_id=tag+'-GOV-A12',contract_ref=ref('ActionContract','GOV-A12'),
        task_ref=rr('DecisionTask','record'),business_time=point,read_token=tag+'-GOV-A12-read',visible_refs=visible,
        authorization_refs=[grant_ref],candidate_set_ref=candidate)
    plan=GovernmentApprovalFeedbackPlan.model_validate({'context':context,'action_input':{'scope':scope,
        'feedback_refs':[feedback],'visible_statistic_refs':[],'observation_profile_ref':profile,
        'working_authority_ref':authority,'policy_control_profile_ref':None},'objects':objects,
        'native_evidence_ref':native,'history_evidence_ref':history,'history_feedback_ref':feedback})
    for item in plan.objects:
        value=deepcopy(item['value'])
        if item['ref']['kind']=='Evidence' and value['content_hash'] is None:value['content_hash']='0'*64
        if item['ref']['kind']=='Feedback':value['event_source_sha256']='0'*64
        GovernmentFeedbackActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(item['ref']),value)
    return plan.model_dump(mode='json')
