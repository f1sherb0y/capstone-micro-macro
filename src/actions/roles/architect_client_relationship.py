"""Original A12 private relationship record, with an explicit responsible actor."""
from copy import deepcopy
from decimal import Decimal
from src.actions.contracts.common import EvidenceRecord,Known,Unknown
from src.actions.contracts.architect_client_relationship import ClientRelationshipTask,ClientRelationshipObservation,ClientRelationshipJudgment


def analyze_client_relationship(context,action_input,reading,*,decision,state,capability):
    task=reading.resolve(decision.monthly_client_task_ref);obs=reading.resolve(decision.monthly_client_observation_ref)
    org=reading.organization_id;now=context.business_time
    if not isinstance(task,ClientRelationshipTask) or not isinstance(obs,ClientRelationshipObservation):
        raise ValueError('Client follow-up requires the original typed task and current observation')
    if (context.scope.kind!='organization' or context.scope.ref.id!=org or task.scope!=context.scope or obs.scope!=context.scope
            or task.organization_id!=org or obs.organization_id!=org or obs.as_of!=now or state.as_of!=now
            or not task.effective_window.contains(now) or task.authority_ref!=decision.authority_ref
            or task.authority_ref not in context.authorization_refs or task.responsible_actor_id!=context.actor_id
            or not isinstance(task.permitted,Known) or not task.permitted.value):
        raise ValueError('Client follow-up changes own scope, current authorization, permission or responsible actor')
    if (decision.choice!='record_feedback' or action_input.learning_profile_ref is not None or action_input.feedback_refs
            or decision.feedback_refs or decision.assessment_ref is not None or decision.training_profile_ref is not None
            or state.coverage!='unknown' or capability.status!='unknown' or state.received_feedback_refs
            or state.applied_feedback_refs or state.execution_refs or capability.verified_capability_codes or capability.qualification_refs
            or not isinstance(task.external_contact_consent,Unknown)):
        raise ValueError('Internal follow-up cannot assert formal learning, credential status or external contact consent')
    if len(set(task.allowed_party_ids))!=len(task.allowed_party_ids) or len(set(task.allowed_party_roles))!=len(task.allowed_party_roles):
        raise ValueError('Client follow-up task repeats its permitted counterparties')
    def evidence(ref):
        e=reading.resolve(ref)
        if not isinstance(e,EvidenceRecord) or e.content_hash is None or e.effective_window is None or not e.effective_window.contains(now):
            raise ValueError('Client follow-up lacks current received evidence')
    def number(m,unit,maximum=None):
        evidence(m.basis_ref);v=Decimal(m.value)
        if m.unit!=unit or v<0 or maximum is not None and v>maximum:raise ValueError('Invalid client review indicator or private policy units')
        return v
    for ref in [*task.evidence_refs,*obs.evidence_refs]:evidence(ref)
    market=number(obs.market_demand,'index');weight=number(task.private_review_weight,'ratio',1)
    priority=market*weight;priority_gate=priority>=number(task.minimum_priority,'priority')
    capacity_gate=number(obs.native_free_ratio,'ratio',1)>=number(task.minimum_free_ratio,'ratio',1)
    history=obs.prior_own_outcomes;previous=[]
    if len({h['event_id'] for h in history})!=len(history):raise ValueError('Repeated client follow-up execution history')
    for h in sorted(history,key=lambda h:h['tick']):
        i=h['micro_identity'];prior=ClientRelationshipJudgment.model_validate(h['client_judgment'])
        if (i['organization_id']!=org or i['run_id']!=context.run_id or i['action_id']!='ARCHITECT-A12'
                or not 0<h['tick']<now.offset or prior.participate!=h['participated']
                or h['operation']!=(prior.operation if prior.participate else 'maintain_operations')):
            raise ValueError('Client follow-up consumes another organization, run, future or unexecuted result')
        previous=deepcopy(prior.adopted_records)
    old={r['party_organization_id']:r for r in previous}
    if len(old)!=len(previous):raise ValueError('Prior relationship record repeats a party')
    grouped={};seen=set()
    for party in obs.parties:
        selected=party.selection;key=(party.organization_id,selected.event_id)
        if (party.organization_id==org or party.organization_id not in task.allowed_party_ids or party.role not in task.allowed_party_roles
                or selected.organization_id!=org or not 0<selected.tick<now.offset
                or selected.appointment_identity.get('organization_id')!=org
                or selected.appointment_identity.get('run_id')!=context.run_id
                or selected.appointment_identity.get('action_id')!='ARCHITECT-A03' or key in seen
                or party.role=='Owner' and party.organization_id!=selected.client_organization_id):
            raise ValueError('Client follow-up substitutes an unauthorized, future, duplicate or foreign collaboration party')
        seen.add(key);row=grouped.setdefault(party.organization_id,{'role':party.role,'selections':[]})
        if row['role']!=party.role:raise ValueError('Client follow-up aliases roles for one original party')
        row['selections'].append(selected.model_dump(mode='json'))
    proposals=[];due=[];not_due=[]
    for pid,row in sorted(grouped.items()):
        selections=sorted(row['selections'],key=lambda s:(s['tick'],s['event_id']))
        prior=old.get(pid);event_ids=[s['event_id'] for s in selections]
        if prior and (prior['party_role']!=row['role'] or not set(prior['selection_event_ids'])<=set(event_ids)
                or not 0<prior['last_updated_tick']<now.offset or prior['responsible_actor_id']!=context.actor_id):
            raise ValueError('Client follow-up rewrites the same previously accepted private relationship')
        changed=prior is None or prior['selection_event_ids']!=event_ids
        review_due=prior is None or now.offset>=prior['next_review_tick']
        record={'party_organization_id':pid,'party_role':row['role'],'responsible_actor_id':context.actor_id,
            'selection_event_ids':event_ids,'project_ids':sorted({s['project_id'] for s in selections}),
            'confirmed_selection_sources':selections,'last_updated_tick':now.offset,'next_review_tick':now.offset+task.review_interval_ticks,
            'private_review_priority':str(priority),'followup_agenda':['retain_confirmed_collaboration_context','review_future_work_scope_before_any_contact'],
            'external_contact_consent':'unknown','external_message_delivered':False,'detailed_service_relationship':'unknown'}
        proposals.append(record)
        if changed or review_due:due.append(pid)
        else:not_due.append(pid)
    if set(old)-set(grouped):raise ValueError('Client follow-up drops an earlier accepted own collaboration party')
    participate=priority_gate and capacity_gate and bool(due);adopted=deepcopy(old)
    if participate:
        for row in proposals:
            if row['party_organization_id'] in due:adopted[row['party_organization_id']]=deepcopy(row)
    result=ClientRelationshipJudgment(participate=participate,market_demand=obs.market_demand,
        private_priority={'value':str(priority),'unit':'priority','basis_ref':obs.market_demand.basis_ref},
        priority_gate=priority_gate,capacity_gate=capacity_gate,proposed_records=proposals,updated_party_ids=due if participate else [],
        not_due_party_ids=not_due,adopted_records=[adopted[k] for k in sorted(adopted)],
        consumed_monthly_event_ids=[h['event_id'] for h in history],consumed_micro_result_sha256=[h['micro_result_sha256'] for h in history],
        interpretation=('Update the authorized private client/consultant follow-up records and review schedule from actual own confirmed selections.' if participate else
            'Retain the accepted client/consultant follow-up records after current priority, free capacity and review-due checks.')+
            ' Internal relationship records only; no contact delivery, client consent, satisfaction, activated detailed service relationship or future commission is inferred.')
    reading.recheck();return result.model_dump_json()
