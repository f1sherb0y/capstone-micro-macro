"""Exact own quote/borrower-acceptance handoff, without a formal finance ledger."""
from copy import deepcopy

from integration.bank_financing_private import checked_result, evidence_binding
from integration.project_financing_feedback import project_financing_event
from src.actions.contracts.bank_arrangement_objects import ArrangementOfferView, accepted_offer_digest
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def received_selection(app, *, plan, entry):
    from gba_construction_sim.backend.agents.contracts import AgentObservationV1
    bank = app.bank
    client, engine = bank.assembly.client, bank.assembly.engine
    project = engine.projects.get(plan.project_id)
    events = [] if project is None else [e for e in project.event_log if e['event_id'] == entry['event_id']]
    if len(events) != 1:
        raise TaskConflict('Bank arrangement has no unique actual native selected-financing event')
    event = events[0]
    expected = project_financing_event(AgentObservationV1.model_validate(event), client.organization_roles)
    scope = {'project_id': plan.project_id, 'owner_id': plan.borrower_id, 'tick': plan.tick}
    if (event['event_type'] != 'project_financing_selected' or event['tick'] != plan.tick
            or event['agent_id'] != plan.borrower_id or project.owner_id != plan.borrower_id
            or event['data'].get('selected_bank_id') != plan.organization_id
            or event['data'].get('financing_mode') != 'bank_finance'
            or event['data'].get('native_financing_scope') != scope
            or plan.organization_id not in expected or entry['payload'] != expected[plan.organization_id]
            or client.organization_roles.get(plan.organization_id) != 'Bank'):
        raise TaskConflict('Bank arrangement substitutes its actual bank, borrower, financing mode or received selection')
    return event


def _transport(bank, *, organization_id, scope, proposal_action, final_action):
    tasks = bank.assembly.client.tasks.for_organization(run_id=bank.assembly.client.run_id, organization_id=organization_id)
    proposal, = [t['output'] for t in tasks if t['state'] == 'output_formed'
        and t['identity']['purpose'] == 'propose' and t['identity']['action_id'] == proposal_action
        and t['output'].get('factors', {}).get('native_financing_scope') == scope]
    final, = [t['output'] for t in tasks if t['state'] == 'output_formed'
        and t['identity']['purpose'] == 'decide' and t['identity']['action_id'] == final_action
        and t['output'].get('data', {}).get('native_financing_scope') == scope]
    if (proposal['accepted'] is not True or final['decision'] is not True
            or final['data'].get('proposal_response_sha256') != task_digest(proposal)
            or final['data'].get('micro_task_key') != proposal['factors'].get('micro_task_key')
            or final['data'].get('micro_result_sha256') != proposal['factors'].get('micro_result_sha256')):
        raise TaskConflict('Bank arrangement changes the original successful independent proposal/final decision')
    return proposal, final


def arrangement_sources(app, *, plan, entry):
    bank = app.bank
    event = received_selection(app, plan=plan, entry=entry)
    scope = event['data']['native_financing_scope']
    records = [r for r in bank._records() if r['state'] == 'formed' and r['scope'] == scope
        and r['native_request']['agent']['agent_id'] == plan.organization_id]
    owner_records = [r for r in bank._records(prefix=bank.owner.PREFIX) if r['state'] == 'formed'
        and r['scope'] == scope and r['native_request']['agent']['agent_id'] == plan.borrower_id]
    if len(records) != 1 or len(owner_records) != 1:
        raise TaskConflict('Bank arrangement lost its original independently saved Bank/Owner financing request')
    technical, owner_technical = records[0], owner_records[0]
    quote_identity = TaskIdentity(**technical['steps']['BANK-A04']['identity'])
    owner_identity = TaskIdentity(**owner_technical['identity'])
    quote = checked_result(bank.workers['BANK-A04'], quote_identity)
    owner = checked_result(bank.owner.worker, owner_identity)
    quote_snapshot, owner_snapshot = bank.snapshots.get(quote_identity), bank.snapshots.get(owner_identity)
    proposal, final = _transport(bank, organization_id=plan.organization_id, scope=scope,
        proposal_action='consider_financing', final_action='bank_project_financing')
    owner_proposal, owner_final = _transport(bank, organization_id=plan.borrower_id, scope=scope,
        proposal_action='select_financing_offer', final_action='owner_financing_selection')
    quotes = [e for e in bank.assembly.engine.projects[plan.project_id].event_log
        if e['event_type'] == 'bank_financing_decision' and e['tick'] == plan.tick and e['agent_id'] == plan.organization_id]
    if (len(quotes) != 1 or quotes[0]['data'].get('accepted') is not True
            or quotes[0]['data'].get('micro_task_key') != quote_identity.key
            or quotes[0]['data'].get('micro_result_sha256') != quote['result_sha256']
            or quote['result']['payload']['choice'] != 'offer'
            or owner['result']['payload']['choice'] != 'accept_offer'
            or owner['result']['payload']['offer_ref'] != plan.action_input['offer_ref']
            or technical['source_file_sha256'] != bank.settings.file_sha256
            or technical['steps']['BANK-A04']['result_sha256'] != quote['result_sha256']
            or technical['proposal_response_sha256'] != task_digest(proposal)
            or owner_technical['result_sha256'] != owner['result_sha256']
            or owner_technical['proposal_response_sha256'] != task_digest(owner_proposal)
            or event['data'].get('micro_task_key') != owner_identity.key
            or event['data'].get('micro_result_sha256') != owner['result_sha256']
            or event['data'].get('proposal_response_sha256') != task_digest(owner_proposal)
            or owner_final['data'].get('selected_bank_id') != plan.organization_id
            or proposal['factors'].get('micro_task_key') != quote_identity.key):
        raise TaskConflict('Bank arrangement changes original exact offered/accepted terms or actual bank selection provenance')
    for snapshot in (quote_snapshot, owner_snapshot):
        if snapshot['context']['business_time'] != plan.context.business_time.model_dump(mode='json'):
            raise TaskConflict('Bank arrangement reception changes its original quotation or acceptance business time')
    original = {task_digest(r['ref']): r['projection'] for r in quote['source_reading']}
    own_sources = {task_digest(r['ref']): r['projection'] for r in owner['source_reading']}
    own_plan, = [p for p in bank.owner.plans if (p.organization_id, p.project_id, p.tick)
        == (plan.borrower_id, plan.project_id, plan.tick)]
    if (own_sources[task_digest(own_plan.native_evidence_ref.model_dump(mode='json'))]['content_hash']
            != task_digest(owner_technical['observed'])):
        raise TaskConflict('Bank arrangement substitutes the audited original independent borrower input evidence')
    disclosure, = [d for d in own_plan.disclosures if d.bank_id == plan.organization_id]
    origins = [o for o in owner_technical['observed']['bank_origins'] if o['bank_id'] == plan.organization_id]
    if (len(origins) != 1 or origins[0]['task_key'] != quote_identity.key
            or origins[0]['result_sha256'] != quote['result_sha256']
            or origins[0]['record_sha256'] != quote['record_sha256']
            or origins[0]['source_reading_sha256'] != quote['source_reading_sha256']):
        raise TaskConflict('Bank arrangement borrower did not actually receive this original quotation result')
    communicated = deepcopy(own_sources[task_digest(disclosure.offer_ref.model_dump(mode='json'))])
    if (communicated['lender_id'] != plan.organization_id or communicated['terms']['borrower_id'] != plan.borrower_id
            or communicated['application_ref'] != quote_snapshot['action_input']['application_ref']
            or communicated['scope_ref'] != plan.context.scope.model_dump(mode='json')
            or communicated['status'] != 'offered'):
        raise TaskConflict('Bank arrangement changes its independently communicated commercial quote or adds releases')
    objects = deepcopy(plan.objects)
    copied = []
    allowed = {'Evidence', 'Authorization', 'FunctionAssignment', 'FinanceApplication', 'Project', 'OwnerCase',
        'LendingCapacity', 'FinancePortfolio', 'FinanceCommitment', 'ReservationPolicy', 'TimeWindow', 'Requirement', 'QuoteAuthorityPolicy'}
    commitment_origins = {task_digest(r['ref']): r for r in plan.prior_commitment_origins}
    for ref in plan.quote_read_refs:
        if ref['kind'] not in allowed or task_digest(ref) not in original:
            raise TaskConflict('Bank arrangement quote disclosure exceeds its explicit original authorized source whitelist')
        value = deepcopy(original[task_digest(ref)])
        if ref['kind'] == 'FinanceCommitment':
            extra = commitment_origins.get(task_digest(ref))
            if extra is None or set(extra) != {'ref', 'origin_offer_ref', 'origin_arrangement_ref'}:
                raise TaskConflict('Bank arrangement needs explicit independent prior commitment origins')
            value.update({k: deepcopy(v) for k, v in extra.items() if k != 'ref'})
        copied.append({'ref': ref, 'value': value})
    # Only actual acceptance-author mandates and their basis are disclosed from
    # the Owner. Cash, forecasts, debts and comparison preferences stay private.
    for ref in plan.borrower_read_refs:
        if ref['kind'] not in {'Evidence', 'Authorization', 'FunctionAssignment'} or task_digest(ref) not in own_sources:
            raise TaskConflict('Bank arrangement receipt discloses private borrower financial or decision data')
        copied.append({'ref': ref, 'value': deepcopy(own_sources[task_digest(ref)])})
    by_ref = {task_digest(r['ref']): r['value'] for r in copied}
    reservation = next(v for v in by_ref.values() if isinstance(v, dict) and v.get('ref', {}).get('kind') == 'ReservationPolicy'
        and v['application_ref'] == communicated['application_ref'])
    # Owner comparison priority is not communicated to the bank. It is not part
    # of the exact accepted commercial agreement digest.
    communicated['priority'] = {'state': 'unknown', 'reason_code': 'private_owner_ranking_not_disclosed', 'missing_refs': []}
    communicated['evidence_refs'] = [plan.quote_evidence_ref.model_dump(mode='json')]
    communicated['reservation_policy_ref'] = reservation['ref']
    copied.append({'ref': plan.action_input['offer_ref'], 'value': communicated})
    digest = accepted_offer_digest(ArrangementOfferView.model_validate(communicated))
    acceptance_ref = plan.action_input['borrower_acceptance_ref']
    acceptance = {'ref': acceptance_ref, 'offer_ref': plan.action_input['offer_ref'],
        'scope_ref': communicated['scope_ref'], 'organization_id': plan.borrower_id,
        'actor_id': owner_snapshot['context']['actor_id'], 'function_ref': owner_snapshot['context']['function_ref'],
        'authority_ref': owner_snapshot['context']['authorization_refs'][0], 'action_id': 'OWN-A05', 'decision': 'accept',
        'accepted_terms': deepcopy(communicated['terms']), 'agreement_sha256': digest,
        'recorded_decision_ref': {'kind': 'RecordedDecision', 'id': acceptance_ref['id'] + '-original-owner-decision', 'version': acceptance_ref['version']},
        'accepted_at': owner_snapshot['context']['business_time'], 'available_at': plan.context.business_time.model_dump(mode='json'),
        'evidence_refs': [plan.acceptance_evidence_ref.model_dump(mode='json')]}
    recorded = {k: deepcopy(v) for k, v in acceptance.items() if k not in {'ref', 'recorded_decision_ref', 'accepted_at', 'available_at'}}
    recorded.update(ref=acceptance['recorded_decision_ref'], decided_at=acceptance['accepted_at'])
    copied.extend([{'ref': acceptance_ref, 'value': acceptance}, {'ref': recorded['ref'], 'value': recorded}])
    observed = {'event_id': event['event_id'], 'event_sha256': task_digest(event), 'scope': scope,
        'organization_id': plan.organization_id, 'borrower_id': plan.borrower_id,
        'quote_task_key': quote_identity.key, 'quote_result_sha256': quote['result_sha256'],
        'quote_source_reading_sha256': quote['source_reading_sha256'], 'quote_event_id': quotes[0]['event_id'],
        'quote_proposal_sha256': task_digest(proposal), 'quote_final_sha256': task_digest(final),
        'owner_task_key': owner_identity.key, 'owner_result_sha256': owner['result_sha256'],
        'owner_proposal_sha256': task_digest(owner_proposal), 'owner_final_sha256': task_digest(owner_final),
        'accepted_agreement_sha256': digest}
    evidence_binding(objects, plan.native_evidence_ref.model_dump(mode='json'), observed)
    evidence_binding(objects, plan.quote_evidence_ref.model_dump(mode='json'), quote['result'])
    evidence_binding(objects, plan.acceptance_evidence_ref.model_dump(mode='json'), owner['result'])
    unique = {}
    for row in objects + copied:
        key = task_digest(row['ref'])
        if key in unique and unique[key] != row:
            raise TaskConflict('Bank arrangement substitutes an immutable original received source version')
        unique[key] = row
    return list(unique.values()), observed
