"""Fresh independent synthetic sources for native final-account communication.

These declarations are authored before runtime registration. They supply no
native-produced debt, actual cash, agreed settlement or prior project history.
"""
from copy import deepcopy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def shared_initial_sources(*, run_id, project_id, organization_snapshot,
        owner_id, contractor_id, qs_id, clock_id, with_owner_response=False, with_contractor_response=False,
        review_tick=1,source_namespace=None):
    """Bind fresh declarations to existing shared identities before sealing.

    Existing actors/locations remain authoritative. New function assignments
    and grants are explicit initial declarations, never native-derived rights.
    This function must not be used to migrate registered runtime sources.
    """
    from integration.native_lifecycle_actions import NativeLifecycleInput
    from src.organization.registry import OrganizationSnapshot
    if type(review_tick) is not int or review_tick < 1:
        raise ValueError('Final-account source review tick must be an explicit positive integer')
    if source_namespace is not None and (not isinstance(source_namespace,str) or not source_namespace.strip()):
        raise ValueError('Final-account source namespace must be a nonempty string')
    prefix='shared-final-account'+(':'+source_namespace if source_namespace is not None else '')

    existing = {o['organization_id']:o for o in organization_snapshot['organizations']}
    roles = {owner_id:'Owner', contractor_id:'Contractor', qs_id:'QS'}
    if (organization_snapshot['run_id'] != run_id or len(roles) != 3
            or any(org not in existing or role not in {a['role'] for a in existing[org]['assignments']}
                for org,role in roles.items())):
        raise ValueError('Final-account discussion requires its three original shared organizations and assigned roles')
    snapshot, document = initial_sources(run_id=run_id, project_id=project_id, with_contractor=True,
        with_owner_response=with_owner_response, with_contractor_response=with_contractor_response)
    orgs = {'owner':owner_id,'native-contractor':contractor_id,'native-qs':qs_id}
    actors = {'owner-actor':existing[owner_id]['actor_id'],
        'qs-actor':existing[qs_id]['actor_id'],'native-contractor':existing[contractor_id]['actor_id'],
        'contractor-actor':existing[contractor_id]['actor_id']}
    names = {p['plan_id']:prefix+'-'+p['plan_id'] for p in document['plans']}
    def bind(value, key=None):
        if isinstance(value,str):
            if key and key.endswith('actor_id') and value in actors:return actors[value]
            if key in {'operation_id','read_token'}:return prefix+':'+value
            return orgs.get(value,names.get(value,value))
        if isinstance(value,list):return [bind(v,key) for v in value]
        if not isinstance(value,dict):
            return value+review_tick-1 if key in {'tick','message_tick','contractor_message_tick'} and type(value) is int else value
        if set(value)=={'clock_ref','offset'}:
            return {'clock_ref':bind(value['clock_ref']),
                'offset':value['offset']+review_tick-1 if value['offset']>0 else value['offset']}
        if set(value)=={'kind','id','version'}:
            row=deepcopy(value)
            if row['kind']=='ClockProfile':row['id']=clock_id
            elif row['kind'] not in {'ActionContract','Project'}:row['id']=prefix+':'+row['id']
            return row
        return {k:bind(v,k) for k,v in value.items()}
    snapshot, document = bind(snapshot), bind(document)
    for org in snapshot['organizations']:
        actual = existing[org['organization_id']]
        org['actor_id']=actual['actor_id']
        org['public_location']=deepcopy(actual['public_location'])
        org['public_description']='Explicit independent initial final-account communication sources.'
        if source_namespace is not None:
            org['source_ids']=['synthetic:final-account-communication:'+org['organization_id']+':'+source_namespace]
    snapshot=OrganizationSnapshot.model_validate(snapshot).model_dump(mode='json')
    document=NativeLifecycleInput.model_validate(document).model_dump(mode='json')
    project={'project_id':project_id,'name':'Explicit initial final-account communication case',
        'region':'Hong Kong','owner_id':owner_id,'initial_budget':100,'contract_sum':100,
        'current_stage':'final_account','selected_contractor_id':contractor_id,'selected_qs_id':qs_id}
    return snapshot, document, project


def initial_sources(*, run_id='native-final-account-position-test', project_id='synthetic-final-review',
        successor=True, with_qs=True, with_contractor=False, with_owner_response=False, with_contractor_response=False):
    if with_contractor and not with_qs:
        raise ValueError('Three-party final-account communication requires the original QS question consumer')
    if with_owner_response and not with_qs:
        raise ValueError('Owner response requires its actual original QS question producer')
    if with_contractor_response and not with_contractor:
        raise ValueError('Contractor response requires its original own proposal producer')
    step = json.loads((ROOT / 'tests/fixtures/roles/lifecycle_v5_owner_payment_inputs.v1.json').read_bytes())['steps'][0]
    context = step['offline_binding']['invocation']['context']
    prior_scope = deepcopy(context['scope'])
    scope = {**deepcopy(prior_scope), 'kind': 'project',
        'ref': {'kind':'Project','id':project_id,'version':'1'}}
    old_ref = prior_scope['ref']
    def fresh(value):
        if isinstance(value, list):return [fresh(v) for v in value]
        if not isinstance(value, dict):return value
        if value == old_ref:return deepcopy(scope['ref'])
        if value == prior_scope:return deepcopy(scope)
        if set(value) == {'clock_ref','offset'}:
            return {**deepcopy(value), 'offset': 0 if value['offset'] < 25 else 1 if value['offset'] == 25 else 6}
        return {k: fresh(v) for k,v in value.items()}
    context = fresh(context)
    context.update(run_id=run_id, execution_mode='rule')
    snapshot = fresh(step['offline_binding']['organization_snapshot'])
    snapshot['run_id'] = context['run_id']
    for org, role in (('native-contractor','Contractor'),('native-qs','QS')):
        party = deepcopy(snapshot['organizations'][0])
        party.update(organization_id=org, actor_id=org+'-actor',
            source_ids=['synthetic:final-account-message-recipient:'+org],
            public_description='Explicit synthetic native final-account message recipient.')
        party['assignments'][0].update(role=role,
            function_ref={'kind':'FunctionAssignment','id':org+'-function','version':'1'})
        snapshot['organizations'].append(party)
    rows = fresh(step['input_fixture']['objects'])
    grant, = snapshot['authorizations']
    decision, = [r['value'] for r in rows if r['ref']['kind'] == 'PaymentAuthorization']
    due = {'kind':'Obligation','id':'independent-unquantified-disputed-work','version':'1'}
    decision.update(choice='dispute', account_ref=None, lines=[], obligation_refs=[due],
        note='Independent Owner position: retain the disputed work item for discussion.')
    unknown = {'state':'unknown','reason_code':'independent_unquantified_dispute','missing_refs':[]}
    basis = next(r['ref'] for r in rows if r['ref']['kind'] == 'Evidence')
    rows.append({'ref':due,'value':{'ref':due,'evidence_refs':[basis], 'debtor_id':'owner',
        'payee_id':'native-contractor','source_ref':{'kind':'FundingSource','id':'independent-source','version':'1'},
        'origin_scope':scope,'debt_ref':None,
        'component_refs':[{'kind':'SettlementComponent','id':'independent-disputed-component','version':'1'}],
        'actual_due':unknown,'actual_paid':unknown,'actual_offset':unknown,'payable':unknown,
        'due_at':context['business_time'],'as_of':context['business_time'],
        'status':'disputed','kind':'works','verification_evidence_refs':[basis]}})
    native = {'kind':'Evidence','id':'actual-native-final-review-trigger','version':'1'}
    evidence = deepcopy(next(r['value'] for r in rows if r['ref']['kind']=='Evidence'))
    evidence.update(ref=native, source_kind='synthetic', basis_kind='observed', content_hash=None)
    rows.append({'ref':native,'value':evidence})
    candidate, = [r['value'] for r in rows if r['ref']['kind']=='CandidateSet']
    candidate['candidates']=[{'ref':deepcopy(due),'permitted_choices':['dispute']}]
    inputs = fresh(step['offline_binding']['invocation']['action_input'])
    inputs.update(account_refs=[],due_refs=[due])
    context['visible_refs'] = [r['ref'] for r in rows]
    grant['readable_refs'] = deepcopy(context['visible_refs'])
    plans = [{'plan_id':'owner-position','organization_id':'owner','project_id':scope['ref']['id'],
        'tick':1,'event_type':'final_account_review_started','context':context,'action_input':inputs,
        'objects':rows,'native_evidence_ref':native,
        'final_account_disclosure':{'recipient_ids':['native-contractor','native-qs'],'fields':'choice_and_note'}}]
    if successor:
        later = deepcopy(plans[0])
        later.update(plan_id='owner-after-native-communication', final_account_disclosure=None,
            depends_on=['owner-position'],
            dependency_evidence_ref={'kind':'Evidence','id':'actual-native-position-receipt','version':'1'})
        later['context'].update(operation_id=context['operation_id']+'-after-message',
            read_token=context['read_token']+'-after-message')
        later['context']['task_ref']['id'] += '-after-message'
        later['context']['candidate_set_ref']['id'] += '-after-message'
        for row in later['objects']:
            if row['ref']['kind']=='CandidateSet':
                row['ref']=deepcopy(later['context']['candidate_set_ref'])
                row['value']['operation_id']=later['context']['operation_id']
        later['context']['visible_refs']=[r['ref'] for r in later['objects']]
        grant['readable_refs'].append(deepcopy(later['context']['candidate_set_ref']))
        dependency = deepcopy(evidence)
        dependency['ref'] = later['dependency_evidence_ref']
        later['objects'].append({'ref':dependency['ref'],'value':dependency})
        later['context']['visible_refs'].append(dependency['ref'])
        grant['readable_refs'].append(dependency['ref'])
        plans.append(later)
    for plan in plans:
        for row in plan['objects']:
            if row['ref']['kind']=='Authorization':row['value']=deepcopy(grant)
    additional = []
    if with_contractor:
        additional.append(_contractor_reception_sources(context['run_id'],scope,tick=1))
    if with_qs:
        additional.append(_qs_reception_sources(context['run_id'],scope['ref'],tick=1,with_contractor=with_contractor))
    for next_plan, next_snapshot in additional:
        # These are fresh, unsealed initial sources, not revisions of a running
        # organization's identity or an existing registered invocation.
        from integration.financing_professional_development import _merge_snapshot
        incoming={o['organization_id'] for o in next_snapshot['organizations']}
        authorized={g['organization_id'] for g in snapshot['authorizations']}
        # Replace initial recipient placeholders, but merge real function
        # assignments/grants without overwriting another action's authority.
        snapshot['organizations']=[o for o in snapshot['organizations']
            if o['organization_id'] not in incoming or o['organization_id'] in authorized]
        snapshot=_merge_snapshot(snapshot,next_snapshot)
        plans.append(next_plan)
    if with_owner_response:
        # A later Owner position must not change the earlier QS action's
        # explicit original message selection when it is queried or restored.
        qs_plan, = [p for p in plans if p.get('final_account_question_reception')]
        qs_plan['final_account_question_reception']['message_index'] = 0
        answer, grant = _owner_question_response_sources(plans[0])
        snapshot['authorizations'].append(grant)
        plans.append(answer)
    if with_contractor_response:
        qs_plan, = [p for p in plans if p.get('final_account_question_reception')]
        qs_plan['final_account_question_reception']['contractor_message_index'] = 0
        proposal, = [p for p in plans if p.get('final_account_position_reception')]
        answer, grant = _contractor_settlement_response_sources(proposal)
        snapshot['authorizations'].append(grant)
        plans.append(answer)
    document = {'schema_version':'native-lifecycle-actions-input.v1','run_id':context['run_id'],
        'source_declaration':'independent_inputs_not_native_execution_proof','plans':plans}
    return snapshot, document


def _contractor_settlement_response_sources(proposal):
    """Declare a new invocation, not a pre-existing or registered account.

    Only the original completed proposal can supply the history view at runtime.
    Original contract/components, residual duties and unknown amounts are kept.
    This response quotes only the Owner position actually addressed to Contractor;
    the Owner-only QS question is never copied from another party's task.
    """
    from integration.contractor_tender_development import ref
    original_grant, = [r['value'] for r in proposal['objects']
        if r['ref'] == proposal['context']['authorization_refs'][0]]
    local = [proposal['native_evidence_ref'], proposal['final_account_position_reception']['evidence_ref']]
    def fresh(value):
        if isinstance(value, list):return [fresh(v) for v in value]
        if not isinstance(value, dict):return value
        if set(value) == {'kind','id','version'}:
            row = deepcopy(value)
            if row['kind'] in {'HandoverProfile','HandoverProcedure','CandidateSet','DecisionTask'} or row in local:
                row['id'] += ':settlement-response'
            return row
        return {k:fresh(v) for k,v in value.items()}
    answer = fresh(proposal)
    context = answer['context']
    context['operation_id'] += ':settlement-response'
    context['read_token'] += ':settlement-response'
    grant = deepcopy(original_grant)
    grant['ref']['id'] += ':settlement-response'
    context['authorization_refs'] = [deepcopy(grant['ref'])]
    account = ref('FinalAccount','contractor-own-original-account-proposal')
    dependency = ref('Evidence','contractor-own-original-account-result')
    answer.update(plan_id='contractor-after-own-final-account-proposal', depends_on=[proposal['plan_id']],
        dependency_evidence_ref=dependency,
        contractor_final_account_history={'plan_id':proposal['plan_id'],'final_account_ref':account})
    rows = answer['objects']
    for row in rows:
        value = row['value']
        if row['ref'] == original_grant['ref']:
            row['value'] = deepcopy(original_grant)  # Historical author grant is immutable.
        elif row['ref']['kind'] == 'HandoverProfile':
            value.update(choice='respond_settlement', authority_ref=deepcopy(grant['ref']),
                final_account_ref=deepcopy(account), business_key='response-to-own-unquantified-proposal',
                note='Contractor response to its own retained proposal: keep all disputed items, unknown amounts and continuing duties; no settlement agreement or payment is asserted.')
        elif row['ref']['kind'] == 'HandoverProcedure':
            value['permitted_choices'] = ['respond_settlement']
        elif row['ref']['kind'] == 'CandidateSet':
            value['operation_id'] = context['operation_id']
            value['candidates'][0]['permitted_choices'] = ['respond_settlement']
    basis = deepcopy(next(r['value'] for r in rows if r['ref']['kind'] == 'Evidence'))
    basis.update(ref=dependency, content_hash=None)
    rows.append({'ref':deepcopy(dependency),'value':basis})
    rows.append({'ref':deepcopy(grant['ref']),'value':grant})
    context['visible_refs'] = [deepcopy(r['ref']) for r in rows] + [deepcopy(account)]
    grant['readable_refs'] = deepcopy(context['visible_refs'])
    return answer, grant


def _owner_question_response_sources(original):
    """Declare a separate private A06 view; bind only the actual QS receipt later.

    This is an initial negotiation policy for unquantified disputed work, not a
    conversion of QS communication into supplied evidence or a settled debt.
    """
    def fresh(value):
        if isinstance(value, list):
            return [fresh(item) for item in value]
        if not isinstance(value, dict):
            return value
        if set(value) == {'kind', 'id', 'version'}:
            row = deepcopy(value)
            if row['kind'] in {'Project', 'WorkScope', 'Obligation'}:
                row['version'] = 'owner-question-response-1'
            elif row['kind'] == 'Evidence' and value != original['native_evidence_ref']:
                pass  # Unchanged independent basis and original role assignment.
            elif row['kind'] in {'Authorization', 'PaymentAuthorization', 'CandidateSet', 'DecisionTask'} or value == original['native_evidence_ref']:
                row['id'] = 'owner-question-response:' + row['id']
            return row
        return {key: fresh(item) for key, item in value.items()}
    plan = fresh(original)
    plan['plan_id'] = 'owner-after-received-qs-question'
    plan['context']['operation_id'] += '-after-qs-question'
    plan['context']['read_token'] += '-after-qs-question'
    plan['final_account_disclosure']['recipient_ids'] = ['native-qs']
    decision, = [r['value'] for r in plan['objects'] if r['ref']['kind'] == 'PaymentAuthorization']
    decision.update(choice='negotiate', note='Owner response: retain the disputed item and negotiate the requested evidence; no evidence, agreed amount or payment is asserted.')
    receipt = {'kind': 'Evidence', 'id': 'owner-actual-qs-question-reception', 'version': '1'}
    evidence = deepcopy(next(r['value'] for r in plan['objects'] if r['ref'] == plan['native_evidence_ref']))
    evidence.update(ref=receipt, content_hash=None)
    plan['objects'].append({'ref': receipt, 'value': evidence})
    plan['action_input']['evidence_refs'].append(receipt)
    decision['evidence_refs'].append(receipt)
    grant, = [r['value'] for r in plan['objects'] if r['ref']['kind'] == 'Authorization']
    grant['readable_refs'] = [r['ref'] for r in plan['objects']]
    plan['context']['visible_refs'] = deepcopy(grant['readable_refs'])
    candidate, = [r['value'] for r in plan['objects'] if r['ref']['kind'] == 'CandidateSet']
    candidate['operation_id'] = plan['context']['operation_id']
    for item in candidate['candidates']:
        item['permitted_choices'] = ['negotiate']
    plan['final_account_owner_reception'] = {'message_tick': plan['tick'], 'evidence_ref': receipt,
        'decision_ref': decision['ref']}
    return plan, deepcopy(grant)


def _qs_reception_sources(run_id, project_ref, *, tick, with_contractor=False):
    step = json.loads((ROOT / 'tests/fixtures/roles/lifecycle_v6_qs_final_evidence_inputs.v1.json').read_bytes())['steps'][0]
    old_scope = step['request']['context']['scope']
    scope = {**deepcopy(old_scope),'kind':'project','ref':project_ref}
    def fresh(value):
        if isinstance(value,str):return {'qs':'native-qs','contractor':'native-contractor'}.get(value,value)
        if isinstance(value,list):return [fresh(v) for v in value]
        if not isinstance(value,dict):return value
        if value==old_scope:return deepcopy(scope)
        if value==old_scope['ref']:return deepcopy(project_ref)
        if set(value)=={'clock_ref','offset'}:
            return {**deepcopy(value),'offset':0 if value['offset']<30 else tick if value['offset']==30 else tick+5}
        return {k:fresh(v) for k,v in value.items()}
    context=fresh(step['request']['context'])
    context.update(run_id=run_id,execution_mode='rule')
    declared=step['configuration']['settings']['source_settings']
    snapshot=fresh(declared['organization_snapshot']);snapshot['run_id']=run_id
    rows=fresh(declared['source_projection']['objects'])
    # Project's professional-service view has no OwnerCase organization field.
    for row in rows:
        if row['ref']==project_ref:row['value'].pop('organization_id',None)
        if row['ref']['kind']=='ClockProfile':row['value']['tick_unit']='month'
    basis=deepcopy(next(r['value'] for r in rows if r['ref']['kind']=='Evidence'))
    native={'kind':'Evidence','id':'qs-actual-final-review-trigger','version':'1'}
    reception={'kind':'Evidence','id':'qs-actual-owner-position-reception','version':'1'}
    contractor_reception={'kind':'Evidence','id':'qs-actual-contractor-position-reception','version':'1'}
    receptions=[reception]+([contractor_reception] if with_contractor else [])
    for ref in (native,*receptions):
        value=deepcopy(basis);value.update(ref=ref,content_hash=None)
        rows.append({'ref':ref,'value':value})
        context['visible_refs'].append(ref)
    question, = [r['value'] for r in rows if r['ref']['kind']=='EvidenceTarget']
    response, = [r['value'] for r in rows if r['ref']['kind']=='ResponseRequirement']
    question.update(question='Please provide the evidence supporting your received final-account position.',
        recipient_ids=['owner'])
    question['evidence_refs'].extend(receptions)
    response['recipient_ids']=['owner']
    qs_grant, = [g for g in snapshot['authorizations'] if g['organization_id']=='native-qs']
    qs_grant['readable_refs'].extend([native,*receptions])
    for row in rows:
        if row['ref']==qs_grant['ref']:row['value']=deepcopy(qs_grant)
    return {'plan_id':'qs-after-received-owner-position','organization_id':'native-qs',
        'project_id':project_ref['id'],'tick':tick,'event_type':'final_account_review_started',
        'context':context,'action_input':fresh(step['request']['action_input']),'objects':rows,
        'native_evidence_ref':native,'final_account_question_reception':{
            'message_tick':tick,'evidence_ref':reception,'question_ref':question['ref'],
            'publish_question_text':True,
            **({'contractor_message_tick':tick,'contractor_evidence_ref':contractor_reception}
                if with_contractor else {})}},snapshot


def _contractor_reception_sources(run_id, scope, *, tick):
    """Declare private unquantified components, not macro-produced debt/work.

    The original A11 partitions the independent disputed component. Its note
    later incorporates actual addressed Owner communication and is the only
    disclosed output; private components and obligations stay local.
    """
    from integration.contractor_tender_development import ref, known
    step=json.loads((ROOT/'tests/fixtures/roles/lifecycle_v6_contractor_handover_inputs.v1.json').read_bytes())['steps'][0]
    old_scope=step['request']['context']['scope']
    scope={**deepcopy(old_scope),'kind':'project','ref':deepcopy(scope['ref'])}
    def fresh(value):
        if isinstance(value,str):return {'contractor':'native-contractor','contractor-actor':'native-contractor'}.get(value,value)
        if isinstance(value,list):return [fresh(v) for v in value]
        if not isinstance(value,dict):return value
        if value==old_scope:return deepcopy(scope)
        if value==old_scope['ref']:return deepcopy(scope['ref'])
        if set(value)=={'clock_ref','offset'}:
            return {**deepcopy(value),'offset':0 if value['offset']<30 else tick if value['offset']==30 else tick+5}
        return {k:fresh(v) for k,v in value.items()}
    context=fresh(step['request']['context']);context.update(run_id=run_id,execution_mode='rule')
    declared=step['configuration']['settings']['source_settings']
    snapshot=fresh(declared['organization_snapshot']);snapshot['run_id']=run_id
    original=fresh(declared['source_projection']['objects'])
    keep={'Evidence','FunctionAssignment','Project','WorkScope','ClockProfile','Authorization','ContinuingResponsibility'}
    rows=[r for r in original if r['ref']['kind'] in keep or r['ref']==scope['ref']]
    for row in rows:
        if row['ref']==scope['ref']:row['value'].pop('organization_id',None)
        if row['ref']['kind']=='ClockProfile':row['value']['tick_unit']='month'
    grant,=snapshot['authorizations']
    basis=deepcopy(next(r['value'] for r in rows if r['ref']['kind']=='Evidence'))
    rr=lambda kind,name:ref(kind,'contractor-final-account-'+name)
    contract,profile,procedure=(rr('Contract','private'),rr('HandoverProfile','proposal'),rr('HandoverProcedure','communication'))
    obligation,component=rr('Obligation','unquantified'),rr('SettlementComponent','disputed')
    native,reception=rr('Evidence','actual-trigger'),rr('Evidence','actual-owner-reception')
    issue,candidates=rr('Issue','unquantified'),context['candidate_set_ref']
    point=context['business_time'];window=deepcopy(grant['validity'])
    common={'scope':deepcopy(scope),'available_at':point,'effective_window':window,'evidence_refs':[basis['ref']]}
    def put(reference,**fields):rows.append({'ref':reference,'value':{'ref':reference,**deepcopy(common),**fields}})
    responsibilities=[r['ref'] for r in rows if r['ref']['kind']=='ContinuingResponsibility']
    for row in rows:
        if row['ref']['kind']=='ContinuingResponsibility':row['value']['contract_ref']=contract
    put(contract,contractor_id='native-contractor',client_id='owner',currency='HKD',as_built_refs=[],
        verification_refs=[],defect_refs=[],issue_refs=[issue],obligation_refs=[obligation],
        settlement_component_refs=[component],continuing_responsibility_refs=responsibilities,
        handover_request_refs=[],final_account_refs=[],coverage='complete',as_of=point)
    put(procedure,contract_ref=contract,permitted_choices=['propose_final_account'],permitted=known(True),
        recipient_ids=['owner','native-qs'],required_as_built_scope_refs=[],required_requirement_refs=[],
        require_independent_verification=True,allow_pending_handover=False)
    put(profile,contract_ref=contract,organization_id='native-contractor',actor_id=context['actor_id'],
        function_ref=context['function_ref'],authority_ref=grant['ref'],procedure_ref=procedure,
        choice='propose_final_account',business_key='independent-unquantified-final-account-proposal',
        remaining_issue_refs=[issue],evidence_refs=[basis['ref'],reception],evidence_refs_received=[basis['ref'],reception],
        remedy_plan_ref=None,final_account_ref=None,component_refs=[],disputed_refs=[component],
        note='Independent Contractor proposal: retain the unquantified disputed component and continuing guarantee; no payment or agreement is asserted.')
    unknown={'state':'unknown','reason_code':'independent_unquantified_settlement','missing_refs':[]}
    source=rr('FundingSource','independent')
    rows.append({'ref':obligation,'value':{'ref':obligation,'evidence_refs':[basis['ref']],
        'debtor_id':'owner','payee_id':'native-contractor','source_ref':source,'origin_scope':deepcopy(scope),
        'debt_ref':None,'component_refs':[component],'actual_due':unknown,'actual_paid':unknown,
        'actual_offset':unknown,'due_at':point,'as_of':point,'status':'disputed','kind':'works',
        'payable':unknown,'verification_evidence_refs':[basis['ref']]}})
    put(component,contract_ref=contract,obligation_ref=obligation,debt_ref=None,debtor_id='owner',
        payee_id='native-contractor',source_ref=source,as_of=point,category='works',settlement_mode='cash',
        actual_due=unknown,actual_cash_paid=unknown,actual_offset=unknown,certificate_ref=None,requestable=unknown)
    put(issue,contract_ref=contract,as_built_refs=[],defect_refs=[],requirement_refs=[],component_refs=[component],status='disputed')
    for reference in (native,reception):
        value=deepcopy(basis);value.update(ref=reference,content_hash=None)
        rows.append({'ref':reference,'value':value})
    candidate=deepcopy(next(r['value'] for r in original if r['ref']['kind']=='CandidateSet'))
    candidate['candidates']=[{'ref':profile,'permitted_choices':['propose_final_account']}]
    rows.append({'ref':candidates,'value':candidate})
    context['visible_refs']=[r['ref'] for r in rows];grant['readable_refs']=deepcopy(context['visible_refs'])
    for row in rows:
        if row['ref']==grant['ref']:row['value']=deepcopy(grant)
    return {'plan_id':'contractor-after-received-owner-position','organization_id':'native-contractor',
        'project_id':scope['ref']['id'],'tick':tick,'event_type':'final_account_review_started',
        'context':context,'action_input':{'contract_ref':contract,'scope_ref':deepcopy(scope),
            'as_built_refs':[],'verification_refs':[],'defect_refs':[],
            'settlement_components':[component],'handover_profile_ref':profile},'objects':rows,
        'native_evidence_ref':native,'final_account_position_reception':{
            'message_tick':tick,'evidence_ref':reception,'profile_ref':profile},
        'final_account_disclosure':{'recipient_ids':['owner','native-qs'],'fields':'choice_and_note'}},snapshot

