"""Check the saved origin-to-settlement case without replaying business actions."""
import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

from integration.contractor_tender_development import verify_bundle
from integration.verify_goal4_integration import journal, objects
from integration.verify_goal3_minimal_native_fix import macro_snapshot, save_or_match
from integration.verify_tender_closed_loop import digest_valid
from src.coordination.tasks import TaskIdentity, task_digest


def read(path):
    return json.loads(Path(path).read_bytes())


def verify(directory, *, source_directory=None):
    directory = Path(directory).resolve()
    source = directory/'input' if source_directory is None else Path(source_directory).resolve()
    verify_bundle(source)
    initial = read(source/'macro-request.json')
    case_config=read(source/'case-config.json')
    library_entry=case_config.get('entry_kind')=='case_library_initial_project'
    if library_entry:
        imported,=initial['initial_projects']
        public,=read(source/'case-library-input.json')['projects']
        assert imported['project_id']==public['project_id']==case_config['case_id']
        assert all(imported[k]==public[k] for k in ['name','project_type','region','owner_id'])
        assert imported['initial_budget']==public['budget'] and imported['current_stage']=='initiation'
        assert not any(imported.get(k) for k in ['bids','contracts','engagements','selected_bank_id',
            'selected_architect_id','selected_engineer_id','selected_qs_id','selected_contractor_id'])
    else:
        assert initial['initial_projects'] == [], 'The case must start without a project'
    assert read(directory/'exit.json')['exit_code'] == 0
    output = read(directory/'runtime/result.json')
    simulation = output['simulation']
    host = output['module_host_extension']['host']
    events = host['original_global_events']
    captured = read(directory/'runtime/native-run-state.json')
    for field in ['simulation_id', 'status', 'current_tick', 'project_results']:
        assert captured['simulation'][field] == simulation[field]
    assert captured['original_global_events'] == events
    event_map = {e['event_id']: e for e in events}
    assert len(event_map) == len(events)
    assert simulation['status'] == 'completed' and simulation['current_tick'] == initial['ticks']
    project, = simulation['project_results']
    assert project['current_stage'] == 'closed'
    assert not any(e['data'].get('agent_observer_errors') for e in events)
    declared_payment_waits={}
    if library_entry:
        # A real native delay may reveal the already modelled absence of
        # detailed payment history. Keep that result unresolved and verify its
        # lineage; it is not a completed receipt or a completed micro action.
        for record in host['lifecycle']['actions']:
            assert record['state'] in {'formed','unresolved'}
            if record['state']=='formed':continue
            identity=TaskIdentity(**record['identity'])
            event=event_map[record['observed']['event_id']]
            assert identity.action_id=='CONTRACTOR-A10' and event['event_type']=='payment_delayed'
            assert identity.organization_id==project['selected_contractor_id']
            assert record['result_kind']=='needs_information' and record['formal_effect']=='not_submitted'
            declared_payment_waits[identity.key]=record
    tasks, metadata, workers, journal_sha = journal(directory,allowed_pending=declared_payment_waits)
    mode=read(source/'case-config.json').get('mode','offline')
    model_calls=[]
    call_budget=None
    if mode=='offline':
        assert all(t['identity']['versions']['model'] == 'offline-no-model.v1' for t in tasks)
    else:
        assert mode=='model'
        versions={t['identity']['versions']['model'] for t in tasks}
        assert len(versions)==1 and next(iter(versions)).startswith('tender-model:')
        for key,worker in workers.items():
            execution=worker['audit'].get('decision',{}).get('execution',{})
            if execution.get('model_calls',0):
                assert worker['identity']['action_id']=='CONTRACTOR-A02'
                assert execution['status']=='selected' and execution['model_calls']==1
                native,=[e for e in events if e['event_type']=='bid_submitted'
                    and e['agent_id']==worker['identity']['organization_id']]
                assert native['data']['decision_factors']['micro_result_sha256']==worker['result_sha256']
                assert Decimal(str(native['data']['bid_price']))==Decimal(worker['result']['payload']['bid']['price']['value'])
                model_calls.append({'micro_task_key':key,'micro_result_sha256':worker['result_sha256'],
                    'organization_id':worker['identity']['organization_id'],
                    'price_'+worker['result']['payload']['bid']['price']['currency']:worker['result']['payload']['bid']['price']['value'],
                    'native_event_id':native['event_id'],'native_event_sha256':task_digest(native),
                    'execution':execution})
        call_budget=host['tender']['model_host']['call_budget']
        expected_bidders=case_config.get('active_contractor_count',2)
        assert len(model_calls)==expected_bidders and call_budget['charged_or_reserved_calls']==expected_bidders
        assert call_budget['max_calls']==case_config['model_options']['max_calls']<=case_config.get('api_total_attempt_cap',4)

    def saved(record):
        digest_valid(record)
        assert record == metadata[record['key']]
        key = TaskIdentity(**record['identity']).key
        worker = workers[key]
        assert record['result_sha256'] == worker['result_sha256']
        return key, worker

    # A macro event must point to the exact durable micro result, not merely
    # share its action name or an aggregate success status.
    executed = []
    for event in events:
        # The native session opening event retains mutable
        # metadata.latest_recommendation. Its final view can contain a later
        # decision; it is not evidence that decision executed at opening time.
        if event['event_type'] == 'contract_negotiation_session_started':
            continue
        for item in objects(event['data']):
            key = item.get('micro_task_key')
            digest = item.get('micro_result_sha256')
            if digest and not key and item.get('micro_action_id'):
                # An Owner event can embed another party's earlier bid.
                # Bind its exact result/input, rather than relabelling that
                # worker as the actor of the enclosing macro event.
                candidates = [k for k, w in workers.items() if w['result_sha256'] == digest
                    and w['identity']['action_id'] == item['micro_action_id']
                    and (not item.get('micro_input_sha256')
                        or w['identity']['input_sha256'] == item['micro_input_sha256'])]
                if len(candidates) > 1:
                    candidates = [k for k in candidates if workers[k]['identity']['organization_id']
                        == item.get('organization_id', event['agent_id'])]
                key, = candidates
            if not key or not digest:
                continue
            worker = workers[key]
            assert worker['result_sha256'] == digest
            executed.append({'event_id': event['event_id'], 'tick': event['tick'],
                'event_type': event['event_type'], 'event_sha256': task_digest(event),
                'micro_task_key': key, 'micro_action_id': worker['identity']['action_id'],
                'micro_organization_id': worker['identity']['organization_id'],
                'micro_result_sha256': digest})
    executed = list({(r['event_id'], r['micro_task_key']): r for r in executed}.values())
    kinds = ['project_opportunity_initiated', 'consultant_team_appointed',
        'tender_documents_prepared', 'tender_opened', 'bid_evaluation_completed',
        'contract_negotiation_recommendation', 'owner_contract_award_decision',
        'contract_awarded', 'supplier_selected', 'project_completed',
        'final_account_review_started', 'final_account_settled']
    if library_entry:kinds.remove('project_opportunity_initiated')
    milestones = []
    for kind in kinds:
        event, = [e for e in events if e['event_type'] == kind
            and e['project_id'] == project['project_id']]
        milestones.append(event)
    assert [e['tick'] for e in milestones] == sorted(e['tick'] for e in milestones)
    required_bindings=['appointment_decision','bid_submitted','owner_contract_award_decision']
    if not library_entry:required_bindings+=['project_opportunity_initiated','project_financing_selected']
    for kind in required_bindings:
        assert any(r['event_type'] == kind for r in executed), 'No actual micro binding: '+kind
    assert len(project['contracts']) == 1
    if library_entry:
        assert project['selected_bank_id'] is None
        assert not any(e['event_type']=='project_financing_selected' and e['project_id']==project['project_id'] for e in events)
    else:assert project['selected_bank_id']
    for role in ['architect', 'engineer', 'qs', 'contractor']:
        assert project['selected_'+role+'_id']
    bids = [e for e in events if e['event_type'] == 'bid_submitted']
    assert len(bids) == case_config.get('active_contractor_count',2)
    for bid in bids:
        binding, = [r for r in executed if r['event_id'] == bid['event_id']]
        assert workers[binding['micro_task_key']]['identity']['organization_id'] == bid['agent_id']
        price = workers[binding['micro_task_key']]['result']['payload']['bid']['price']['value']
        assert Decimal(price) == Decimal(str(bid['data']['bid_price']))

    formation, = host['formation']['requests']
    formation_key, formation_worker = saved(formation)
    evaluated = next(e for e in milestones if e['event_type'] == 'bid_evaluation_completed')
    selection = formation['observed']['actual_original_tender']['own_selection']
    assert selection['event_id'] == evaluated['event_id']
    assert selection['source_event_sha256'] == task_digest(evaluated)
    award, = host['formation']['owner_award']['requests']
    award_key, award_worker = saved(award)
    reception = award['observed']['received_contractor_acceptance']
    assert reception['micro_task_key'] == formation_key
    assert reception['micro_result_sha256'] == formation_worker['result_sha256']
    assert award_worker['result']['payload']['choice'] == 'accept'
    award_event = next(e for e in milestones if e['event_type'] == 'owner_contract_award_decision')
    assert award_event['data']['decision_factors']['micro_task_key'] == award_key
    assert award_event['data']['decision_factors']['micro_result_sha256'] == award_worker['result_sha256']
    signed = next(e for e in milestones if e['event_type'] == 'contract_awarded')
    signed_consumers = []
    assert len(host['supplier']['requests']) == 2
    for supplier in host['supplier']['requests']:
        saved(supplier)
        for stage in [supplier, *[supplier[k] for k in ('screening', 'product', 'quote')]]:
            key = TaskIdentity(**stage['identity']).key
            worker = workers[key]
            received = stage['observed']['native_signed_contract']
            assert stage['result_sha256'] == worker['result_sha256']
            assert received['event_id'] == signed['event_id']
            assert received['source_event_sha256'] == task_digest(signed)
            assert received['signed_tick'] < received['read_tick'] == supplier['scope']['tick']
            assert received['contractor_id'] == project['selected_contractor_id']
            assert received['receiving_organization_id'] == stage['identity']['organization_id']
            assert any(s['projection'].get('content_hash') == task_digest(stage['observed'])
                for s in worker['source_reading'])
            signed_consumers.append({'event_id': signed['event_id'], 'task_key': key,
                'action_id': stage['identity']['action_id'], 'result_sha256': worker['result_sha256']})
    procurement, = host['supplier']['contractor']['requests']
    supply_key, supply_worker = saved(procurement)
    selected = next(e for e in milestones if e['event_type'] == 'supplier_selected')
    assert selected['data']['contractor_decision']['micro_task_key'] == supply_key
    assert selected['data']['contractor_decision']['micro_result_sha256'] == supply_worker['result_sha256']
    origin = procurement['observed']['origin']
    for action in ('A03', 'A04'):
        assert workers[origin[action+'_task_key']]['result_sha256'] == origin[action+'_result_sha256']
    assert origin['supplier_id'] == project['selected_supplier_ids'][0]

    front_parameters = []
    # Imported initiation projects have no first opportunity request. Their
    # first actual opportunity observation occurs after the project closes.
    parameter_tick=(min(r['scope']['tick'] for r in host['opportunity']['requests'])
        if library_entry else milestones[0]['tick'])
    for record in host['opportunity']['requests']:
        if record['scope']['tick'] != parameter_tick:
            continue
        observation = record['observation']
        key = TaskIdentity(**observation['identity']).key
        worker = workers[key]
        demand, = [s['projection'] for s in worker['source_reading'] if s['ref']['kind'] == 'DemandObservation']
        objective, = [s['projection'] for s in worker['source_reading'] if s['ref']['kind'] == 'OwnerObjective']
        rule, = objective['signal_rules']['value']
        native_index = record['native_request']['inputs']['macro_environment']['market_demand_index']
        assert demand['measure']['value']['value'] == str(native_index)
        assert demand['measure']['value']['unit'] == rule['threshold']['unit'] == 'index'
        assert rule['comparison'] == 'at_least'
        assert Decimal(str(native_index)) >= Decimal(rule['threshold']['value'])
        assert worker['result']['payload']['choice'] == 'follow'
        assert record['observed']['observation']['result_sha256'] == worker['result_sha256']
        proposal_key = TaskIdentity(**record['proposal']['identity']).key
        investment_key = TaskIdentity(**record['identity']).key
        assert record['observed']['proposal']['result_sha256'] == workers[proposal_key]['result_sha256']
        assert record['result_sha256'] == workers[investment_key]['result_sha256']
        front_parameters.append({'candidate_project_id': record['scope']['candidate_project_id'],
            'macro_parameter': 'market_demand_index', 'value': str(native_index),
            'comparison': rule['comparison'], 'threshold': rule['threshold']['value'],
            'observation_task_key': key, 'observation_choice': 'follow',
            'proposal_task_key': proposal_key, 'investment_task_key': investment_key,
            'investment_choice': workers[investment_key]['result']['payload']['choice']})
    assert front_parameters

    government_links = []
    approvals = host['government']['approval']['requests']
    assert len(approvals) == 2
    for approval in approvals:
        digest_valid(approval)
        assert approval == metadata[approval['key']]
        assignment = event_map[approval['review_observed']['assignment']['event_id']]
        assert assignment['event_type'] == 'regulatory_review_decision'
        assert assignment['data']['accepted'] is True
        assert assignment['project_id'] == project['project_id']
        stages = []
        for stage, action in [('feedback', 'GOV-A12'), ('review', 'GOV-A04'), ('decision', 'GOV-A07')]:
            identity = TaskIdentity(**approval[stage+'_identity'])
            worker = workers[identity.key]
            assert identity.action_id == action and identity.organization_id == assignment['agent_id']
            assert worker['result_sha256'] == approval[stage+'_result_sha256']
            stages.append({'action_id': action, 'task_key': identity.key,
                'result_sha256': worker['result_sha256']})
        completion = approval['scope']['purpose'] == 'completion_approval'
        native_action = 'government_completion_approval' if completion else 'government_design_approval'
        final, = [t['output'] for t in tasks if t['identity']['purpose'] == 'decide'
            and t['identity']['action_id'] == native_action]
        assert final['decision'] is True
        assert final['data']['micro_result_sha256'] == approval['decision_result_sha256']
        assert final['data']['proposal_response_sha256'] == approval['proposal_response_sha256']
        effect, = [e for e in events if e['event_type'] == ('project_completed' if completion else 'approval_approved')
            and e['project_id'] == project['project_id'] and e['tick'] == approval['scope']['tick']]
        assert assignment['tick'] <= effect['tick']
        government_links.append({'scope': approval['scope'], 'assignment_event_id': assignment['event_id'],
            'micro_stages': stages, 'actual_native_effect_event_id': effect['event_id']})

    # Check the saved original settlement is read in an actual later A03,
    # changes the declared registration policy, and returns to the macro.
    settlement = milestones[-1]
    consumers = []
    opportunity_settings = read(source/'assembly-host.json')['settings']['opportunity']
    opportunity_template = read(opportunity_settings['file_path'])
    policy, = opportunity_template['policies']
    initial_cash = {project['owner_id']+'-'+r['ref']['id']:
        {k: Decimal(r['value'][k]['value']['value'])*Decimal(policy['money_scale'])
            for k in ('actual_cash', 'restricted_cash')}
        for r in opportunity_template['template']['objects'] if r['ref']['kind'] == 'FundingSource'}
    for record in host['opportunity']['requests']:
        observed = record['observed']
        settled = observed['own_final_accounts']['settlements']
        if not settled:
            continue
        item, = settled
        key = TaskIdentity(**record['identity']).key
        micro = workers[key]
        assert record['result_sha256'] == micro['result_sha256']
        assert record['scope']['tick'] > settlement['tick']
        assert item['event_id'] == settlement['event_id']
        assert item['source_event_sha256'] == task_digest(settlement)
        assert item['payment_execution_status'] == item['obligation_clearance_status'] == 'not_proven'
        assert record['identity']['organization_id'] == project['owner_id']
        assert any(s['projection'].get('content_hash') == task_digest(observed)
            for s in micro['source_reading'])
        policies = [s['projection']['policy'] for s in micro['source_reading']
            if s['ref']['kind'] == 'ProjectRegistrationProfile']
        assert observed['final_account_review_preference_pauses_initiation']
        assert observed['max_prior_final_accounts'] == 1
        assert len(settled) >= observed['max_prior_final_accounts']
        assert policies and all(p == {'state': 'known', 'value': 'reject'} for p in policies)
        assessment_case, = [s['projection'] for s in micro['source_reading']
            if s['ref'] == record['action_input']['case_ref']]
        assert assessment_case['status'] == 'active', 'A closed private case already forced rejection'
        assert micro['result']['payload']['choice'] == 'reject'
        cash = {s['ref']['id']: {k: Decimal(s['projection'][k]['value']['value'])
            for k in ('actual_cash', 'restricted_cash')}
            for s in micro['source_reading'] if s['ref']['kind'] == 'FundingSource'}
        assert cash == initial_cash, 'Aggregate settlement changed independent private cash'
        native, = [e for e in events if e['event_type'] == 'project_opportunity_declined'
            and e['tick'] == record['scope']['tick'] and e['agent_id'] == project['owner_id']]
        final, = [t['output'] for t in tasks if t['identity']['purpose'] == 'decide'
            and t['output'].get('data', {}).get('micro_task_key') == key]
        assert final['decision'] is False
        assert final['data']['micro_result_sha256'] == micro['result_sha256']
        consumers.append({'settlement_event_id': settlement['event_id'],
            'settlement_sha256': task_digest(settlement), 'micro_task_key': key,
            'micro_result_sha256': micro['result_sha256'], 'tick': record['scope']['tick'],
            'private_cash_unchanged': True,
            'observed_settlement_count': len(settled),
            'declared_review_threshold': observed['max_prior_final_accounts'],
            'private_assessment_case_status': assessment_case['status'],
            'applied_registration_policy': policies, 'actual_decline_event_id': native['event_id']})
    assert consumers, 'No later judgment consumed the actual settlement'

    # Private lifecycle feedback is separate from the native construction and
    # settlement mechanism. Verify each triggered action read its own event.
    feedback = []
    open_payment_feedback=[]
    lifecycle = host['lifecycle']
    assert lifecycle['all_triggered_private_actions_formed']==(not declared_payment_waits)
    assert not lifecycle['formal_commands_submitted']
    lifecycle_plans={p['plan_id']:p for p in read(read(source/'assembly-host.json')['settings']['lifecycle']['file_path'])['plans']}
    for record in lifecycle['actions']:
        key, worker = saved(record)
        event = event_map[record['observed']['event_id']]
        assert event['project_id'] == project['project_id']
        assert record['result_sha256'] == worker['result_sha256']
        assert any(s['projection'].get('content_hash') == task_digest(record['observed'])
            for s in worker['source_reading'])
        if key in declared_payment_waits:
            assert record==declared_payment_waits[key]
            assert worker['result']=={'kind':'needs_information',
                'missing_fields':['complete_current_original_payment_history'],'requested_refs':[]}
            assert task_digest(lifecycle_plans[record['plan_id']]['context'])==worker['identity']['context_sha256']
            assert record['observed']['source_event_sha256']==task_digest(event)
            origin=record['observed']['payment_origin'];request=event_map[origin['request_event_id']]
            assert request['event_type']=='payment_requested' and request['project_id']==project['project_id']
            assert request['tick']==event['tick']
            assert origin['native_request_status']==request['data']['payment_status']=='delayed'
            assert origin['request_source_event_sha256']==task_digest(request)
            assert origin['delay_event_id']==event['event_id']
            assert origin['trigger_source_event_sha256']==task_digest(event)
            assert origin['earlier_native_signature']['event_id']==signed['event_id']
            assert origin['earlier_native_signature']['source_event_sha256']==task_digest(signed)
            histories=[s['projection'] for s in worker['source_reading']
                if s['ref']['kind']=='Contract' and 'payment_history_complete' in s['projection']]
            assert histories and all(h['payment_history_complete'] is False
                and h['contractor_id']==worker['identity']['organization_id']
                and h['as_of']['offset']==event['tick'] for h in histories)
            open_payment_feedback.append({'micro_task_key':key,'plan_id':record['plan_id'],
                'action_id':worker['identity']['action_id'],'state':'waiting_input',
                'request_event_id':request['event_id'],'delay_event_id':event['event_id'],
                'tick':event['tick'],'payment_amount':request['data']['payment_amount'],
                'source_event_sha256':task_digest(event),'result_sha256':worker['result_sha256'],
                'source_reading_sha256':worker['source_reading_sha256'],
                'missing_fields':worker['result']['missing_fields'],'formal_effect':'not_submitted'})
            continue
        assert record['state']=='formed' and worker['result']['kind']=='completed'
        for dependency in record['dependencies']:
            dep_key = TaskIdentity(**dependency['identity']).key
            assert workers[dep_key]['result_sha256'] == dependency['result_sha256']
        feedback.append({'event_id': event['event_id'], 'micro_task_key': key,
            'action_id': record['identity']['action_id'], 'result_sha256': worker['result_sha256']})
    assert any(r['action_id'] == 'QS-A12' and r['event_id'] == settlement['event_id'] for r in feedback)
    learning, = [r for r in lifecycle['actions'] if r['identity']['action_id'] == 'QS-A12'
        and r['observed']['event_id'] == settlement['event_id']]
    assert learning['dependencies'] and learning['dependencies'][0]['identity']['action_id'] == 'QS-A09'
    macro = macro_snapshot()
    assert macro == read(source/'macro-before.json'), 'Macro source changed'
    counts = Counter(t['identity']['action_id'] for t in tasks if t['identity']['purpose'] == 'action')
    diagnostics = [e for e in events if e['event_type'] == 'invalid_action']
    assert all(e['data'].get('action', {}).get('data', {}).get('validation_only') is True
        and e['data'].get('reason') == 'engagement status cannot execute action'
        and e['stage'] in {'bid_evaluation', 'contract_award'} for e in diagnostics)
    report = {'status': 'passed', 'mode': mode, 'initial_projects': [p['project_id'] for p in initial['initial_projects']],
        'simulation_id': simulation['simulation_id'], 'project_id': project['project_id'],
        'ticks': simulation['current_tick'], 'final_stage': project['current_stage'],
        'initial_budget': project['initial_budget'], 'estimated_cost': project['estimated_cost'],
        'contract_sum': project['contract_sum'], 'milestones': milestones,
        'amount_boundary': 'Macro budget/contract/settlement amounts have no currency field. Private inputs declare HKD and use explicit numeric correspondence; this is a scenario assumption, not an observed macro currency or an FX conversion.',
        'stage_transitions': [e for e in events if e['event_type'] == 'stage_transition'
            and e['project_id'] == project['project_id']],
        'native_design_results': [e for e in events if e['event_type'] == 'project_state_updated'
            and e['stage'] == 'design' and e['project_id'] == project['project_id']],
        'front_parameter_and_handoff_links': front_parameters,
        'government_approval_links': government_links,
        'actual_macro_micro_links': executed, 'lifecycle_consumers': feedback,
        'signed_contract_consumers': signed_consumers,
        'formation_handoff': {'evaluation_event_id': evaluated['event_id'],
            'contractor_task_key': formation_key, 'owner_task_key': award_key,
            'actual_award_decision_event_id': award_event['event_id'], 'signed_event_id': signed['event_id']},
        'later_owner_consumers': consumers, 'technical_tasks': len(tasks),
        'micro_actions': dict(sorted(counts.items())), 'distinct_micro_actions': len(counts),
        'actual_micro_roles': sorted({t['identity']['role'] for t in tasks
            if t['identity']['purpose'] == 'action'}),
        'live_api_calls': len(model_calls),
        'preferred_bid_selection': 'Original native ranking rule in this case; not counted as a micro selection action.',
        'journal_sha256': journal_sha, 'native_pre_signature_diagnostics': diagnostics,
        'original_native_state_capture': 'runtime/native-run-state.json',
        'mutable_native_session_views_excluded_from_execution_links': [e['event_id'] for e in events
            if e['event_type'] == 'contract_negotiation_session_started'],
        'macro_unchanged': {'files': len(macro['files']), 'python_sources': len(macro['python_sources']),
            'snapshot_sha256': task_digest(macro)},
        'boundary': ('One fixed synthetic normal scenario. Original native design, construction and aggregate settlement; no cash clearance, detailed design or all-106-action coverage. '
            + ('No live model calls. The native route label llm_agent does not prove an API call.' if mode=='offline'
                else 'Only Contractor A02 pricing selection uses the live model. Other micro actions and later feedback policy are rules. The earlier offline origin case has one pricing policy, so it is an engineering reference, not a matched-input strategy comparison.'))}
    if mode=='model':
        from integration.origin_model_lifecycle import prior_attempts
        prior=prior_attempts(read(source/'case-config.json'))
        report.update(model_calls=model_calls,call_budget=call_budget,
            previous_api_batches=prior,
            total_case_api_attempts=len(model_calls)+sum(b['verified_attempted_calls'] for b in prior),
            usage_metadata={name:sum(c['execution'].get('usage_metadata',{}).get(name,0) for c in model_calls)
                for name in ['input_tokens','output_tokens','total_tokens']})
    if library_entry:
        context_links=[]
        companies={c['company_id']:c for c in read(source/'case-library-input.json')['companies']}
        for call in model_calls:
            worker=workers[call['micro_task_key']]
            record,=[v for k,v in metadata.items() if k.startswith('action_option_snapshot:')
                and v['snapshot']['action_id']=='CONTRACTOR-A02'
                and task_digest(v['snapshot']['context'])==worker['identity']['context_sha256']
                and task_digest(v['snapshot']['action_input'])==worker['identity']['input_sha256']]
            assert record['record_sha256']==task_digest({k:v for k,v in record.items() if k!='record_sha256'})
            snapshot=record['snapshot']
            assert snapshot['source_reading_sha256']==task_digest(snapshot['source_reading'])
            content=json.dumps(snapshot['source_reading'],ensure_ascii=False)
            assert public['name'] in content and companies[call['organization_id']]['company_name'] in content
            assert snapshot['context']['scope']['ref']['id']==public['project_id']
            context_links.append({'micro_task_key':call['micro_task_key'],
                'option_snapshot_sha256':record['record_sha256'],
                'source_reading_sha256':snapshot['source_reading_sha256'],
                'public_case_name_present':True,'own_public_company_name_present':True,
                'actual_model_prompt_sha256':call['execution']['prompt_sha256']})
        report.update(entry_kind=case_config['entry_kind'],case_id=case_config['case_id'],
            case_library_model_context_links=context_links,
            source_declaration=read(source/'source-declaration.json'),
            initial_investment_and_bank_selection='outside imported-project entry; no choice prefilled',
            amount_boundary='Macro amounts have no currency field. Private inputs explicitly declare HKD scenario amounts; current formal bindings do not support MOP. These are not observed historical costs or an FX conversion.',
            boundary='Input-only case-library project and enterprise background with scenario budget, duration, eligibility and capacities. Native initiation entry, without first opportunity choice or initial bank selection. Only A02 pricing calls the model; later judgment is a predefined rule. No historical winner, actual cash clearance, detailed physical work or all-106-action claim.')
        report.update(open_payment_feedback=open_payment_feedback,
            technical_task_states=dict(Counter(t['state'] for t in tasks)),
            all_triggered_private_actions_formed=lifecycle['all_triggered_private_actions_formed'])
        if open_payment_feedback:
            report['status']='main-chain-passed-with-open-payment-feedback'
            report['boundary']+=' Actual native delays reached original A10 needs-information results; detailed payment history remains missing and those actions are not completed.'
    if case_config.get('response_cache_directory'):
        # Model-host invocations include cache reads. Batch ledger owns paid-attempt counts.
        report['model_host_invocations']=report.pop('live_api_calls')
        report['total_case_api_attempts']='see case model-cache/attempts.jsonl; includes retained attempts'
        report['api_count_boundary']='Host invocation is not necessarily a live API request when exact-response cache is enabled.'
    save_or_match(directory, 'chain-checks.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    args = parser.parse_args()
    report = verify(args.directory)
    print(json.dumps({k: report[k] for k in ['status', 'simulation_id', 'ticks',
        'final_stage', 'distinct_micro_actions']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
