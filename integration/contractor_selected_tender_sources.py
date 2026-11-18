"""Own actual preferred-bidder sources for the original Contractor A04.

No detailed submission receipt, independent signing consent or agreement is
created. The native bid and preferred-bidder result remain separate evidence.
"""
from copy import deepcopy
from decimal import Decimal

from src.actions.contracts.common import ActionContext
from src.coordination.tasks import TaskConflict, task_digest


def query_selected_tender_sources(host, original_request, identity, *, current_context):
    """Authenticate the selected own original bid without replay or disclosure."""
    with host.pipeline.read_guard():
        host._check(bound=True)
        context = ActionContext.model_validate(current_context)
        if context.contract_ref.id != 'CONTRACTOR-A04':
            raise TaskConflict('Selected tender sources require the current own A04 authority')
        source = host.query_source_history(original_request, identity, current_context=context)
        if source['status'] != 'saved' or source['outcome']['effect'] != 'native_bid_submitted':
            raise TaskConflict('Selected tender lacks its saved original sources and actual submitted bid')
        assembly = host.pipeline.assembly
        engine, client = assembly.engine, assembly.client
        project_id = original_request['inputs']['project']['project_id']
        project = engine.projects.get(project_id)
        org = identity.organization_id
        if (context.scope.kind != 'project' or context.scope.ref.id != project_id or project is None
                or project.selected_contractor_id != org or client.organization_roles.get(project.owner_id) != 'Owner'
                or project.current_stage.value != 'contract_award' or project.flags.get('contract_signed')):
            raise TaskConflict('Selected tender is outside its own actual pre-signature project')
        evaluations = [e for e in engine.events.events if e.event_type == 'bid_evaluation_completed'
            and e.project_id == project_id and e.tick <= engine.current_tick]
        if len(evaluations) != 1:
            raise TaskConflict('Selected tender requires its one unambiguous actual evaluation')
        event = evaluations[0]
        raw = event.model_dump(mode='json')
        logged = [e for e in project.event_log if e['event_id'] == event.event_id]
        own = [b for b in event.data.get('ranked_bids',[]) if b.get('contractor_id') == org]
        bids = [b for b in project.bids if b.get('contractor_id') == org]
        committee = event.data.get('evaluation_committee',{})
        if (len(logged) != 1 or task_digest(logged[0]) != task_digest(raw)
                or len(own) != 1 or len(bids) != 1 or event.agent_id != org
                or event.data.get('selected_contractor_id') != org
                or event.data.get('owner_decision',{}).get('accepted') is not True
                or committee.get('owner_id') != project.owner_id
                or committee.get('qs_id') != project.selected_qs_id
                or client.organization_roles.get(committee.get('qs_id')) != 'QS'
                or original_request['metadata']['tick'] != own[0].get('submitted_tick')
                or not original_request['metadata']['tick'] < event.tick):
            raise TaskConflict('Selected tender lost its original evaluation, parties or submission chronology')
        saved = host.pipeline.worker.get_record(identity)
        draft = saved['result']['payload'].get('bid')
        if (saved['result']['kind'] != 'completed' or saved['result']['payload']['choice'] != 'submit_bid'
                or not isinstance(draft,dict)
                or draft['price']['currency'] != 'HKD'
                or any(Decimal(str(price)) != Decimal(draft['price']['value']) for price in
                    [own[0].get('bid_price'),bids[0].get('bid_price'),project.contract_sum])):
            raise TaskConflict('Selected tender changes its actual submitted original price or currency domain')
        result = {'schema_version':'contractor-selected-tender-sources.v1',
            'run_id':identity.run_id,'simulation_id':client.simulation_id,'organization_id':org,
            'project_id':project_id,'owner_id':project.owner_id,'qs_id':committee['qs_id'],
            'as_of_tick':engine.current_tick,'original_identity':identity.as_dict(),
            'original_bid':deepcopy(draft),'original_planned_tasks':deepcopy(saved['result']['payload']['planned_tasks']),
            'history':source['history'],'native_submission':source['outcome'],
            'own_selection':{'event_id':event.event_id,'tick':event.tick,'source_event_sha256':task_digest(raw),
                'own_bid_price':own[0]['bid_price'],'own_evaluation_score':own[0].get('evaluation_score')},
            'limits':'Own observed original bid and preferred status only; no detailed submission receipt, '
                'counterparty consent, signed agreement, resource reservation or cash effect.'}
        result['record_sha256'] = task_digest(result)
        return result


def declare_selected_tender_history(configuration_input, *, query_tick):
    """Declare future own A04 read grants before initial configuration hashing.

    These contexts permit source preparation, not an A04 commercial choice.
    Existing tender grants and source snapshots are retained exactly.
    """
    if type(query_tick) is not int or query_tick < 1:
        raise ValueError('Selected tender history requires an explicit positive initial query tick')
    authority = configuration_input['authority']['organization_snapshot']
    contexts = []
    for plan in configuration_input['request_work_settings']['requests']:
        if 'bid_plan' not in plan:
            continue
        original = plan['bid_plan']['bid_context']
        org = plan['organization_id']
        old, = [g for g in authority['authorizations'] if g['ref'] == original['authorization_refs'][0]]
        grant = deepcopy(old)
        grant['ref'] = {'kind':'Authorization','id':original['operation_id']+'-A04-history','version':'1'}
        grant['action_ids'] = ['CONTRACTOR-A04']
        context = deepcopy(original)
        context.update(operation_id=original['operation_id']+'-selected-history',
            contract_ref={'kind':'ActionContract','id':'CONTRACTOR-A04','version':'1'},
            authorization_refs=[grant['ref']], business_time={**original['business_time'],'offset':query_tick},
            read_token=original['read_token']+'-selected-history')
        if grant['ref'] in [g['ref'] for g in authority['authorizations']]:
            raise ValueError('Selected tender history repeats an initial grant')
        authority['authorizations'].append(grant)
        contexts.append({'organization_id':org,'project_id':plan['project_id'],'context':context})
    if not contexts:
        raise ValueError('Selected tender history needs independently declared original bid plans')
    return contexts


def validate_formation_original_bid(app, plan, request, objects):
    """A04 source guard: independently supplied detailed views must agree.

    This deliberately does not relabel the old selected-bid example, generate
    a SubmissionExecution, or update an independently reviewed agreement.
    """
    from types import SimpleNamespace
    from src.coordination.tasks import TaskIdentity
    from integration.contractor_tender_request_trigger import read_request_record
    proposal = app.assembly.client.proposal_handlers.get(('Contractor','consider_tender'))
    recover = getattr(proposal,'_recovery_host',None)
    if not callable(recover):
        raise TaskConflict('Original contract bid requires its actual original tender host')
    host = recover()
    if (host.pipeline.assembly is not app.assembly or host.pipeline.worker.store is not app.worker.store
            or host.pipeline.assembler.organizations is not app.organizations):
        raise TaskConflict('Contract source guard substitutes original tender assembly, store or authority')
    origin = read_request_record(application=SimpleNamespace(host=host,store=app.worker.store,assembly=app.assembly),
        organization_id=plan.organization_id,request_id=plan.original_tender_request_id)
    if origin['state'] != 'selected':
        raise TaskConflict('Original tender remains unresolved before contract formation')
    source = query_selected_tender_sources(host,origin['native_request'],TaskIdentity(**origin['bid_identity']),
        current_context=plan.context)
    if source['project_id'] != request.inputs['project']['project_id']:
        raise TaskConflict('Original bid is selected for a different actual contract request')
    terms, = [r['value'] for r in objects if r['ref'] == plan.action_input['terms_ref']]
    bids = [r['value'] for r in objects if r['ref'] == terms['bid_ref']]
    if len(bids) != 1 or bids[0].get('draft') != source['original_bid']:
        raise TaskConflict('Detailed contract bid does not preserve the exact actually submitted original A02 draft')
    witness = {task_digest(r['ref']):r['projection'] for r in source['history']['witness']['source_reading']}
    supplied = {task_digest(r['ref']):r['value'] for r in objects}
    draft = source['original_bid']
    required = [draft['programme_ref'],*draft['cost_basis_refs']]
    programme = witness.get(task_digest(draft['programme_ref']),{})
    required.extend(programme.get('quantity_refs',[]))
    for ref in required:
        key = task_digest(ref)
        if key not in witness or supplied.get(key) != witness[key]:
            raise TaskConflict('Contract formation changes or omits an actual original programme, cost or quantity source')
    return source
