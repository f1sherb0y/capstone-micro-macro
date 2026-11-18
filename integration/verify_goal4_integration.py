"""Run a fixed integrated demonstration; verify saved actual business without replay."""
import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from integration.contractor_tender_development import _write, verify_bundle
from integration.verify_tender_closed_loop import ROOT, read, require, one, digest_valid
from integration.verify_goal3_minimal_native_fix import macro_snapshot, save_or_match, verify_financing_case
from src.coordination.tasks import TaskIdentity, task_digest


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_tender(directory, config):
    from integration.tender_closeout_followup_development import build_bundle
    directory.mkdir(parents=True, exist_ok=False)
    source = directory / 'input'
    build_bundle(source, **config)
    verify_bundle(source)
    command = [sys.executable, '-m', 'integration.run', '--input', str(source/'macro-request.json'),
        '--output', str(directory/'runtime'), '--offline', '--input-format', 'gba_request',
        '--macro-mode', 'gba_v1_module', '--allow-native-project-generation',
        '--allow-native-initial-projects-with-generation', '--agent-client-factory',
        'integration.native_routes:build_agent_client', '--agent-client-config', str(source/'native-host.json'),
        '--module-assembly-hook', 'integration.goal4_tender_host:configure_assembly',
        '--module-assembly-config', str(source/'assembly-host.json')]
    _write(directory, 'command.json', command)
    with (directory/'stdout.log').open('xb') as out, (directory/'stderr.log').open('xb') as err:
        result = subprocess.run(command, cwd=ROOT, stdout=out, stderr=err)
    _write(directory, 'exit.json', {'exit_code': result.returncode})
    require(result.returncode == 0, 'Tender chain failed; preserve original logs and journal')


def run_cases(directory, config):
    print('Running one tender-to-settlement chain', flush=True)
    run_tender(directory/'tender-full', config['tender'])
    from integration.verify_financing_chain import run_scenario
    normal = read(ROOT/config['financing_config'])
    for name, case in [('normal', normal), *[(n, c) for n, c in
            read(ROOT/config['financing_controls'])['financing'].items() if n != 'normal']]:
        print('Running independent financing scenario: '+name, flush=True)
        target = directory/('financing-'+name)
        target.mkdir()
        _write(target, 'scenario.json', case)
        run_scenario(target, case)
    from integration.professional_construction_development import build_bundle
    from integration.verify_professional_monthly_chain import run_existing_input
    target = directory/'construction'
    target.mkdir()
    construction = read(ROOT/config['construction_config'])
    _write(target, 'source-config.json', construction)
    _write(target, 'macro-before.json', macro_snapshot())
    print('Running independent existing-project professional construction feedback', flush=True)
    build_bundle(target/'construction/input', run_id=construction['run_id'], config=construction)
    run_existing_input(target/'construction', assembly_hook='integration.professional_construction_feedback:configure_assembly')


def journal(directory, *, allowed_pending=()):
    database = directory/'runtime/tasks.sqlite'
    before = sha(database)
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True) as db:
        tasks = [json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata = {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        names = [n for n, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if n.endswith('_results')]
        workers = {}
        for name in names:
            for value, in db.execute('SELECT record FROM "'+name.replace('"','""')+'"'):
                row = json.loads(value)
                if 'identity' in row and 'result' in row:
                    workers[TaskIdentity(**row['identity']).key] = row
    by_key = {TaskIdentity(**t['identity']).key:t for t in tasks}
    pending=set(allowed_pending)
    require({key for key,t in by_key.items() if t['state']!='output_formed'}==pending,
        'Original journal contains undeclared unresolved tasks')
    require(all((t['state']=='waiting_input' and t['output'] is None and t['output_sha256'] is None)
        if key in pending else (t['state']=='output_formed' and task_digest(t['output'])==t['output_sha256'])
        for key,t in by_key.items()),'Original journal contains changed tasks or invalid declared waits')
    require(pending<=set(workers),'Declared wait lost its original saved worker result')
    for key, worker in workers.items():
        digest_valid(worker)
        require(worker['result_sha256']==task_digest(worker['result']),
            'Micro result differs from original durable task')
        if key in pending:
            require(worker['result']['kind']=='needs_information'
                and any(c.get('result_sha256')==worker['result_sha256'] for c in by_key[key]['conditions']),
                'Declared wait does not match its original needs-information result')
        else:
            require(worker['result']==by_key[key]['output'],'Micro result differs from original durable task')
        if 'source_reading_sha256' in worker:
            require(worker['source_reading_sha256']==task_digest(worker['source_reading']), 'Micro source digest differs')
        else:
            require(worker['audit']['reading'] and worker['audit']['input_sha256']==worker['identity']['input_sha256'],
                'Original action audit lost its input binding or source reading')
    require(sha(database)==before, 'Read-only verification changed original journal')
    return tasks, metadata, workers, before


def verify_tender(directory):
    for manifest in (directory/'input').rglob('input-manifest.json'):
        verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0, 'Original tender CLI did not succeed')
    initial = read(directory/'input/macro-request.json')
    starting, = initial['initial_projects']
    require(starting['current_stage']=='tendering' and not starting['bids'] and not starting['contracts']
        and starting['selected_contractor_id'] is None and not starting['selected_supplier_ids'],
        'Tender outcomes were prefilled')
    output = read(directory/'runtime/result.json')
    simulation = output['simulation']; host = output['module_host_extension']['host']
    require(simulation['status']=='completed' and simulation['current_tick']==25
        and len(simulation['project_results'])==1, 'Incomplete original long chain')
    project, = simulation['project_results']; events = host['original_global_events']
    event_map = {e['event_id']:e for e in events}
    require(len(events)==len(event_map) and project['current_stage']=='closed'
        and not any(e['data'].get('agent_observer_errors') for e in events), 'Native chain or observer failed')
    log_enrichments = []
    for event in project['event_log']:
        actual = event_map[event['event_id']]
        if event != actual:
            # Native global session metadata retains a mutable latest
            # recommendation; the project event keeps the opening copy.
            # Do not rehash either view as if it were the other.
            view = deepcopy(actual)
            enrichment = view['data'].get('metadata', {}).pop('latest_recommendation', None)
            require(event['event_type']=='contract_negotiation_session_started'
                and enrichment is not None and view==event, 'Unexpected project/global event discrepancy')
            log_enrichments.append({'event_id':event['event_id'], 'later_global_view_sha256':task_digest(actual),
                'original_project_view_sha256':task_digest(event), 'field':'data.metadata.latest_recommendation'})
    kinds = ['bid_evaluation_completed','contract_negotiation_recommendation','owner_contract_award_decision',
        'contract_awarded','supplier_selected','project_completed','final_account_review_started','final_account_settled']
    milestones = [one(events, lambda e:e['event_type']==kind and e['project_id']==project['project_id'],
        'Missing or repeated actual milestone: '+kind) for kind in kinds]
    require([e['tick'] for e in milestones]==sorted(e['tick'] for e in milestones)
        and milestones[-1]['tick']<25 and len(project['contracts'])==1, 'Original business order or signature invalid')
    require(sum(e['event_type']=='bid_submitted' for e in events)==2, 'Missing actual submitted bids')
    tasks, metadata, workers, db_sha = journal(directory)
    proofs = []
    def saved(record):
        digest_valid(record)
        require(record==metadata[record['key']], 'Export differs from original journal record')
        key = TaskIdentity(**record['identity']).key
        original = workers[key]
        require(record['result_sha256']==original['result_sha256'], 'Host replaced original micro result')
        return key, original
    formation, = host['formation']['requests']
    key, original = saved(formation)
    selection = formation['observed']['actual_original_tender']['own_selection']
    require(selection['event_id']==milestones[0]['event_id']
        and selection['source_event_sha256']==task_digest(milestones[0]), 'Contractor lost actual evaluated bid')
    owner, = host['formation']['owner_award']['requests']
    owner_key, owner_result = saved(owner)
    reception = owner['observed']['received_contractor_acceptance']
    require(reception['micro_task_key']==key and reception['micro_result_sha256']==original['result_sha256']
        and owner_result['result']['payload']['choice']=='accept', 'Owner did not consume actual Contractor terms')
    require(milestones[2]['data']['decision_factors']['micro_task_key']==owner_key
        and milestones[2]['data']['decision_factors']['micro_result_sha256']==owner_result['result_sha256'],
        'Macro award differs from actual Owner decision')
    proofs.append({'from_event':selection['event_id'], 'to_micro_task':key,
        'then_micro_task':owner_key, 'executed_event':milestones[2]['event_id']})
    # Both sides of the signed award authenticate it before supply decisions.
    suppliers = host['supplier']['requests']
    require(len(suppliers)==2, 'Expected two actual Supplier decisions')
    for record in suppliers:
        _, micro = saved(record)
        require(micro['result']['kind']=='completed', 'Supply action not completed')
        for stage in [record, *[record[name] for name in ('screening','product','quote')]]:
            stage_key = TaskIdentity(**stage['identity']).key; stage_result = workers[stage_key]
            signed = stage['observed']['native_signed_contract']
            require(stage['result_sha256']==stage_result['result_sha256']
                and signed['event_id']==milestones[3]['event_id']
                and signed['source_event_sha256']==task_digest(milestones[3])
                and signed['signed_tick']<signed['read_tick']==record['scope']['tick']
                and signed['contractor_id']==project['selected_contractor_id']
                and signed['receiving_organization_id']==stage['identity']['organization_id']
                and any(s['projection'].get('content_hash')==task_digest(stage['observed'])
                    for s in stage_result['source_reading']), 'Signed award did not enter original Supplier stage reading')
            proofs.append({'from_event':signed['event_id'], 'event_sha256':signed['source_event_sha256'],
                'to_micro_task':stage_key, 'micro_result_sha256':stage_result['result_sha256']})
    procurement = host['supplier']['contractor']['requests']
    require(len(procurement)==1, 'Expected one actual Contractor selection')
    supply_key, supply_result = saved(procurement[0])
    require(milestones[4]['data']['contractor_decision']['micro_task_key']==supply_key
        and milestones[4]['data']['contractor_decision']['micro_result_sha256']==supply_result['result_sha256'],
        'Original macro did not commit the same Supplier selection')
    origin = procurement[0]['observed']['origin']
    require(workers[origin['A03_task_key']]['result_sha256']==origin['A03_result_sha256']
        and workers[origin['A04_task_key']]['result_sha256']==origin['A04_result_sha256']
        and origin['supplier_id']==project['selected_supplier_ids'][0], 'Contractor selected a substituted offer/acceptance')
    approval, = host['government']['approval']['requests']; digest_valid(approval)
    require(approval==metadata[approval['key']], 'Government approval export changed')
    assignment = event_map[approval['review_observed']['assignment']['event_id']]
    require(assignment['event_type']=='regulatory_review_decision' and assignment['data']['accepted'] is True
        and assignment['tick']<approval['scope']['tick']==milestones[5]['tick'], 'Completion approval lacks actual assignment')
    government_proofs = []
    for stage, action in [('feedback','GOV-A12'),('review','GOV-A04'),('decision','GOV-A07')]:
        identity = TaskIdentity(**approval[stage+'_identity']); micro = workers[identity.key]
        require(identity.action_id==action and identity.organization_id==assignment['agent_id']
            and micro['result_sha256']==approval[stage+'_result_sha256'], 'Government review stage substituted')
        government_proofs.append({'identity':identity.as_dict(), 'result_sha256':micro['result_sha256']})
    final_government = one(tasks, lambda t:t['identity']['purpose']=='decide'
        and t['identity']['action_id']=='government_completion_approval', 'Actual Government final missing')['output']
    require(final_government['decision'] is True and final_government['data']['micro_result_sha256']==approval['decision_result_sha256']
        and final_government['data']['proposal_response_sha256']==approval['proposal_response_sha256'],
        'Native completion final differs from original Government review')
    lifecycle = host['lifecycle']; actions = lifecycle['actions']
    require(lifecycle['all_triggered_private_actions_formed'] and not lifecycle['formal_commands_submitted'],
        'Triggered lifecycle actions unresolved or submitted as formal execution')
    settlement = milestones[-1]; review = milestones[-2]
    for record in actions:
        key, micro = saved(record)
        actual = event_map[record['observed']['event_id']]
        require(actual['project_id']==project['project_id'] and micro['result']['kind']=='completed',
            'Private lifecycle action borrowed another project or result')
        require(any(s['projection'].get('content_hash')==task_digest(record['observed'])
            for s in micro['source_reading']), 'Actual event not in original micro reading')
        for dep in record['dependencies']:
            dep_key = TaskIdentity(**dep['identity']).key
            require(workers[dep_key]['result_sha256']==dep['result_sha256'], 'Lifecycle dependency substituted')
        proofs.append({'from_event':actual['event_id'], 'event_sha256':task_digest(actual),
            'to_micro_task':key, 'micro_result_sha256':micro['result_sha256']})
    learning = one(actions, lambda r:r['identity']['action_id']=='QS-A12'
        and r['observed']['event_id']==settlement['event_id'], 'Same settlement missing from QS feedback')
    require(learning['dependencies'] and learning['dependencies'][0]['identity']['action_id']=='QS-A09',
        'QS feedback lost the actual review result')
    consumers = []
    cash = None
    opportunity_settings = read(directory/'input/assembly-host.json')['settings']['opportunity']
    template = read(Path(opportunity_settings['file_path']))
    policy, = template['policies']
    initial_cash = {project['owner_id']+'-'+r['ref']['id']:{k:Decimal(r['value'][k]['value']['value'])*Decimal(policy['money_scale'])
        for k in ('actual_cash','restricted_cash')} for r in template['template']['objects'] if r['ref']['kind']=='FundingSource'}
    for record in host['opportunity']['requests']:
        key, micro = saved(record)
        item, = record['observed']['own_final_accounts']['settlements']
        require(record['scope']['tick']>settlement['tick'] and item['event_id']==settlement['event_id']
            and item['source_event_sha256']==task_digest(settlement)
            and item['observed_review_event_id']==review['event_id']
            and record['identity']['organization_id']==project['owner_id'], 'Later Owner read wrong settlement')
        require(item['payment_execution_status']==item['obligation_clearance_status']=='not_proven',
            'Aggregate settlement invented cash or obligation clearance')
        policies = [s['projection']['policy'] for s in micro['source_reading'] if s['ref']['kind']=='ProjectRegistrationProfile']
        require(record['observed']['final_account_review_preference_pauses_initiation'] and policies
            and all(p=={'state':'known','value':'reject'} for p in policies)
            and micro['result']['payload']['choice']=='reject', 'Settlement was printed but did not affect judgment')
        funding = [{k:s['projection'][k] for k in ('actual_cash','restricted_cash')}
            for s in micro['source_reading'] if s['ref']['kind']=='FundingSource']
        require(funding and (cash is None or cash==funding), 'Private cash changed after aggregate settlement')
        cash = funding
        actual_cash = {s['ref']['id']:{k:Decimal(s['projection'][k]['value']['value'])
            for k in ('actual_cash','restricted_cash')} for s in micro['source_reading'] if s['ref']['kind']=='FundingSource'}
        require(actual_cash==initial_cash, 'Aggregate settlement increased declared independent initial cash')
        final = one(tasks, lambda t:t['identity']['purpose']=='decide'
            and t['output'].get('data',{}).get('micro_task_key')==key, 'Later Owner final missing')['output']
        native = one(events, lambda e:e['event_type']=='project_opportunity_declined'
            and e['tick']==record['scope']['tick'] and e['agent_id']==project['owner_id'], 'Later actual decline missing')
        require(final['decision'] is False and final['data']['micro_result_sha256']==micro['result_sha256'],
            'Later Owner result did not return to original macro')
        consumers.append({'event_id':settlement['event_id'], 'event_sha256':task_digest(settlement),
            'consumer_task_key':key, 'consumer_tick':record['scope']['tick'],
            'source_reading_sha256':micro['source_reading_sha256'], 'result_sha256':micro['result_sha256'],
            'applied_registration_policy':policies, 'actual_decline_event_id':native['event_id']})
    require(consumers and not any(e['event_type']=='project_opportunity_initiated' for e in events),
        'Later settlement consumer or actual waiting missing')
    diagnostics = [e for e in events if e['event_type']=='invalid_action']
    require(all(e['data'].get('action',{}).get('data',{}).get('validation_only') is True
        and e['data'].get('reason')=='engagement status cannot execute action'
        and e['stage'] in {'bid_evaluation','contract_award'} for e in diagnostics),
        'Unexpected native rejection outside pre-signature representative diagnostics')
    return {'status':'passed', 'simulation_id':simulation['simulation_id'], 'project_id':project['project_id'],
        'initial_stage':'tendering', 'final_stage':project['current_stage'], 'ticks':25,
        'milestones':milestones, 'micro_links':proofs, 'later_owner_consumers':consumers,
        'technical_tasks':len(tasks), 'micro_actions':dict(Counter(t['identity']['action_id'] for t in tasks
            if t['identity']['purpose']=='action')), 'journal_sha256':db_sha,
        'native_session_log_enrichments':log_enrichments,
        'completion_government_micro_stages':government_proofs,
        'native_pre_signature_diagnostics':diagnostics,
        'diagnostic_boundary':'Rejected validation_only probes before active Contractor engagement; retained as rejections, never counted as micro decisions or executed work.',
        'preferred_bid_selection':'original_native_rule_in_this_chain; bounded micro selection verified separately',
        'boundary':'Actual aggregate macro completion/settlement and private communication; no cash clearance, physical work receipt or legal release.'}


def verify_cases(directory, config):
    result = {'tender':verify_tender(directory/'tender-full')}
    result['financing'] = {name:verify_financing_case(directory/('financing-'+name), expected_choice=choice)
        for name, choice in [('normal','accept_offer'),('equity','own_funds'),('limited_cash','no_finance')]}
    from integration.verify_financing_chain import verify_scenario
    result['financing_full'] = verify_scenario(directory/'financing-normal',
        read(ROOT/config['financing_config']), macro_snapshot_reader=macro_snapshot)
    initial = [read(directory/('financing-'+name)/'input/macro-request.json') for name in result['financing']]
    require(all(x==initial[0] for x in initial), 'Controlled initial macro requests differ')
    from integration.verify_professional_construction_feedback import verify
    result['construction'] = verify(directory/'construction', macro_snapshot_reader=macro_snapshot)
    require(macro_snapshot()==read(directory/'macro-before.json'), 'GOAL 3 macro baseline changed')
    return result


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def verify_reused_monthly():
    """Match each existing monthly subaction to original micro, execution and later reading."""
    inventory = read(ROOT/'config/gba_v1_monthly_business_wiring.json')
    from integration.verify_owner_monthly_pipeline import verify_scenario as pipeline
    from integration.verify_government_monthly_business_chain import verify_scenario as government
    from integration.verify_contractor_monthly_strategy import verify_scenario as bid_strategy
    from integration.verify_supplier_monthly_prices import verify_scenario as prices
    special = {
        'pipeline':pipeline(ROOT/'output/integration/goal3i_owner_pipeline_20261018_05/review_after_two', limit=2),
        'government_high':government(ROOT/'output/integration/goal3d_monthly_20261018_02/high', high=True),
        'government_low':government(ROOT/'output/integration/goal3d_monthly_20261018_02/low', high=False),
        'bid_strategy':bid_strategy(ROOT/'output/integration/goal3a_bid_strategy_20261018_10/high', high=True),
        'supplier_prices':prices(ROOT/'output/integration/goal3f_supplier_prices_20261018_02/high', high=True)}
    cache = {}; proofs = []
    for row in inventory['entries']:
        require(sha(ROOT/row['native_source']['path'])==row['native_source']['file_sha256'],
            'Reused monthly native implementation changed: '+row['operation'])
        evidence = ROOT/row['evidence']
        if row['operation']=='monitor_material_prices':
            require(special['supplier_prices']['later_own_A01_consumers']==2
                and special['supplier_prices']['later_own_A03_quote_consumers']==2, 'Actual later Supplier quote consumers absent')
            proofs.append({'role':row['role'], 'operation':row['operation'], 'evidence':row['evidence'],
                'verification':'Original monthly price-risk calculation, native execution and later original A03 quote method checked'})
            continue
        if row['operation']=='adjust_bid_strategy':
            require(special['bid_strategy']['later_own_A12_consumers']==1
                and special['bid_strategy']['later_own_A02_consumers']==1, 'Actual later bid pricing/strategy consumers absent')
            proofs.append({'role':row['role'], 'operation':row['operation'], 'evidence':row['evidence'],
                'verification':'Original A12 execution, own memory and later original A02 actual pricing method checked',
                'events':[p['actual_event']['event_id'] for p in special['bid_strategy']['proofs']]})
            continue
        if row['operation']=='screen_investment_pipeline':
            require(special['pipeline']['proofs'] and special['pipeline']['investment_proofs'], 'Pipeline consumers absent')
            proofs.append({'role':row['role'], 'operation':row['operation'], 'evidence':row['evidence'],
                'verification':'pipeline original candidate results, actual scheduler and later A03 checked',
                'events':[p['actual_event']['event_id'] for p in special['pipeline']['proofs']]})
            continue
        if row['role']=='Government' and row['operation']!='review_policy_feedback':
            matching = [p for label in ('government_high','government_low') for p in special[label]['proofs']
                if p['original_final']['action_type']==row['operation']]
            require(matching, 'Government monthly operation absent: '+row['operation'])
            proofs.append({'role':row['role'], 'operation':row['operation'], 'evidence':row['evidence'],
                'verification':'original GOV-A12 source, own native receipt, memory and later operation counts checked',
                'proofs':matching})
            continue
        chosen = None
        for path in sorted(evidence.parent.rglob('runtime/result.json')):
            if path not in cache:
                output = read(path)
                events = {v['event_id']:v for v in objects(output)
                    if {'event_id','event_type','tick','description','data'} <= v.keys()}
                cache[path] = (events, None)
            events, cached = cache[path]
            matching = [e for e in events.values() if e['event_type']=='agent_operation'
                and e['data'].get('operation')==row['operation']]
            if not matching:
                continue
            if cached is None:
                cached = journal(path.parent.parent)
                cache[path] = (events, cached)
            tasks, metadata, workers, db_sha = cached
            for event in matching:
                for final_task in tasks:
                    identity = final_task['identity']; final = final_task['output']
                    key = final.get('data',{}).get('micro_task_key')
                    if not (identity['purpose']=='decide' and identity['action_id']=='monthly_enterprise_operation'
                            and identity['role']==row['role'] and identity['organization_id']==event['agent_id']
                            and final.get('action_type')==row['operation'] and key in workers):
                        continue
                    parents = [m for m in metadata.values() if isinstance(m,dict) and m.get('identity')
                        and TaskIdentity(**m['identity']).key==key and m.get('scope',{}).get('tick')==event['tick']]
                    if not parents:
                        continue
                    parent, = parents; digest_valid(parent); micro = workers[key]
                    proposal = one(tasks, lambda t:t['identity']['purpose']=='propose'
                        and t['output'].get('factors',{}).get('micro_task_key')==key, 'Monthly proposal absent')['output']
                    require(final['decision'] is True and proposal['accepted'] is True
                        and final['data']['micro_result_sha256']==proposal['factors']['micro_result_sha256']
                        ==parent['result_sha256']==micro['result_sha256']
                        and final['data']['proposal_response_sha256']==parent['proposal_response_sha256']==task_digest(proposal)
                        and event['description']==proposal['data']['description'], 'Monthly original execution/result mismatch')
                    later = []
                    for consumer in metadata.values():
                        if not (isinstance(consumer,dict) and consumer.get('identity',{}).get('organization_id')==event['agent_id']
                                and consumer.get('scope',{}).get('tick',-1)>event['tick']
                                and task_digest(event) in json.dumps(consumer)):
                            continue
                        consumer_key = TaskIdentity(**consumer['identity']).key
                        if consumer_key not in workers:
                            continue
                        digest_valid(consumer); original = workers[consumer_key]
                        require(consumer['result_sha256']==original['result_sha256'], 'Monthly later consumer changed')
                        observed = consumer.get('observed')
                        reading = original.get('source_reading', original.get('audit',{}).get('reading'))
                        if not (reading and ((observed is not None and any(
                            s.get('content_hash')==task_digest(observed) for s in objects(reading)))
                                or task_digest(event) in json.dumps(reading))):
                            # A reference in a parent record alone is not proof
                            # that this worker read it. Count only bound reads.
                            continue
                        later.append({'identity':consumer['identity'], 'result_sha256':original['result_sha256'],
                            'source_reading_sha256':task_digest(reading)})
                    if later:
                        chosen = {'role':row['role'], 'operation':row['operation'], 'evidence':row['evidence'],
                            'runtime':path.parent.relative_to(ROOT).as_posix(), 'journal_sha256':db_sha,
                            'event':event, 'event_sha256':task_digest(event), 'micro_identity':micro['identity'],
                            'micro_result_sha256':micro['result_sha256'], 'original_proposal':proposal,
                            'original_final':final, 'later_consumers':later}
                        break
                if chosen:
                    break
            if chosen:
                break
        require(chosen is not None, 'No actual original monthly execution/later reading: '+row['role']+'/'+row['operation'])
        proofs.append(chosen)
    require(len(proofs)==32 and len({(p['role'],p['operation']) for p in proofs})==32, 'Monthly inventory differs')
    return {'status':'passed_read_only_reuse', 'subactions':proofs, 'specialized_business_checks':special,
        'boundary':'Existing scenario-specific original actions and later consumers; not 32 new same-run operations.'}


def verify_reused_business():
    """Reuse existing business verifiers on their original journals, not stored summary flags."""
    from integration.verify_professional_chain import verify_scenario as professional
    from integration.verify_regulatory_chain import verify_scenario as regulatory
    from integration.verify_professional_design_feedback import verify_scenario as design
    from integration.verify_tender_award_review import verify_scenario as selection
    from integration.verify_tender_clarification_loop import verify_run as clarification
    from integration.verify_procurement_negative_selection import verify_scenario as procurement
    from integration.verify_supplier_inventory_chain import verify_case as supply
    from integration.verify_construction_chain import verify_scenario as suspension
    from integration.verify_payment_chain import verify_scenario as payment
    runs = ROOT/'output/integration'
    results = {
        'professional':professional(runs/'goal3c_professional_20261018_01', read(ROOT/'config/professional_chain.json'),
            macro_snapshot_reader=macro_snapshot),
        'regulatory_design':regulatory(runs/'goal3d_regulatory_20261018_01/design', completion=False),
        'regulatory_completion':regulatory(runs/'goal3d_regulatory_20261018_01/completion_revision', completion=True),
        'design_lower':design(runs/'goal3c_design_20261019_01/verified/lower_qs_accuracy'),
        'design_higher':design(runs/'goal3c_design_20261019_01/verified/higher_qs_accuracy'),
        'micro_selection':selection(runs/'goal3_macro_minfix_20261022_01/selection', accepted=True),
        'invitation_evaluation_award':selection(runs/'goal3a_20261018_05/normal', accepted=True),
        'clarification':clarification(runs/'goal3a_clarification_20261018_01'),
        'procurement_accepted':procurement(runs/'goal3e_closeout_20261019_01/accepted/accepted_control', refused=False),
        'procurement_refused':procurement(runs/'goal3e_closeout_20261019_01/accepted/all_refused', refused=True),
        'supply_delay':supply(runs/'goal3_remaining_20261019_01/supply-delay/delay_feedback'),
        'suspension':suspension(runs/'goal3g_construction_20261018_01/suspended', suspended=True, quality=0.0),
        'healthy_construction':suspension(runs/'goal3g_construction_20261018_01/healthy', suspended=False, quality=1.0),
        'payment_delayed':payment(runs/'goal3h_payment_20261018_01/low_reliability', reliability=0.0, expect_delay=True),
        'payment_reliable':payment(runs/'goal3h_payment_20261018_01/high_reliability', reliability=1.0, expect_delay=False)}
    # Retained safety run uses the earlier native baseline. Read its original
    # event/worker bindings directly, without substituting a baseline reader.
    target = runs/'goal3_remaining_20261019_01/safety-feedback'
    checks = read(target/'checks.json'); case = target/'construction'
    output = read(case/'runtime/result.json'); host = output['module_host_extension']['host']
    events = {e['event_id']:e for e in host['original_global_events']}
    tasks, metadata, workers, db_sha = journal(case)
    for proof in checks['proofs']:
        key = TaskIdentity(**proof['identity']).key; micro = workers[key]
        require(micro['result_sha256']==proof['result_sha256']
            and proof['actual_event']==events[proof['actual_event']['event_id']], 'Retained safety execution changed')
        require(any(s['projection'].get('content_hash')==task_digest(proof['observed']) for s in micro['source_reading']),
            'Actual safety observation never entered original micro reading')
        for obj in objects(proof['observed']):
            if 'source_event_sha256' in obj and obj.get('event_id') in events:
                require(task_digest(events[obj['event_id']])==obj['source_event_sha256'], 'Safety source event substituted')
    require('safety_issue' in checks['consumed_event_types'] and checks['actual_improvement_followups']>0,
        'Safety threshold/actual later execution consumer missing')
    results['safety'] = {'original_checks':checks, 'rechecked_journal_sha256':db_sha,
        'verification':'Archived original safety event/input/result/execution bindings rechecked; old macro-unchanged header is historical only.'}
    return {'status':'passed_read_only_reuse', 'cases':results,
        'applicability':'GOAL 3 native changes are bounded to selection, financing semantics and redundant diagnostic payload. Old archive diagnostics are not successful execution evidence. Current native baseline and new business cases are checked separately.'}


def verify_operation_links(directory):
    """Require durable micro/transport/original event correspondence for every nonmonthly operation."""
    directory = directory.resolve()
    runs = ROOT/'output/integration'
    cases = [directory/'tender-full', directory/'financing-normal', runs/'goal3c_professional_20261018_01',
        runs/'goal3d_regulatory_20261018_01/design', runs/'goal3_macro_minfix_20261022_01/selection',
        runs/'goal3e_closeout_20261019_01/accepted/accepted_control',
        runs/'goal3i_owner_pipeline_20261018_05/review_after_two']
    prepared = []
    for case in cases:
        output = read(case/'runtime/result.json')
        events = {e['event_id']:e for e in objects(output) if {'event_id','event_type','tick','data'}<=e.keys()}
        tasks, metadata, workers, db_sha = journal(case)
        prepared.append((case, events, tasks, workers))
    proofs = []
    for row in read(ROOT/'config/gba_v1_goal3_delivery.json')['operation_contracts']:
        if row['operation']=='decide_monthly_operation':
            continue
        point = 'owner_preferred_bidder_selection' if row['operation']=='select_preferred_bid' else row['operation']
        purpose = 'decide' if row['operation']=='select_preferred_bid' else 'propose'
        proof = None
        for case, events, tasks, workers in prepared:
            for task in tasks:
                identity = task['identity']; response = task['output']
                if (identity['role'],identity['action_id'],identity['purpose'])!=(row['role'],point,purpose):
                    continue
                data = response.get('factors', response.get('data',{})); digest = data.get('micro_result_sha256')
                actual = [w for k,w in workers.items() if digest and w['result_sha256']==digest
                    and w['identity']['organization_id']==identity['organization_id'] and w['identity']['role']==row['role']
                    and (not data.get('micro_task_key') or data['micro_task_key']==k)]
                native = [e for e in events.values() if digest and any(v.get('micro_result_sha256')==digest for v in objects(e['data']))]
                if actual and native:
                    micro, = actual
                    proof = {'role':row['role'], 'operation':row['operation'], 'runtime':case.relative_to(ROOT).as_posix(),
                        'micro_identity':micro['identity'], 'micro_result_sha256':digest, 'transport_identity':identity,
                        'transport_sha256':task_digest(response), 'actual_events':[
                            {'event_id':e['event_id'],'event_type':e['event_type'],'tick':e['tick'],
                             'event_sha256':task_digest(e)} for e in native]}
                    break
            if proof:
                break
        require(proof is not None, 'Operation lacks actual micro/transport/event evidence: '+str((row['role'],row['operation'])))
        proofs.append(proof)
    require(len(proofs)==17, 'Nonmonthly native operation count differs')
    return proofs


def coverage(reused, monthly, fresh, links):
    from gba_construction_sim.backend.agents.operation_specs import list_operation_contracts
    index = read(ROOT/'config/gba_v1_goal3_delivery.json')
    current = {(c.role,c.operation) for c in list_operation_contracts()}
    require(current=={(r['role'],r['operation']) for r in index['operation_contracts']} and len(current)==25,
        'Current native operation contract inventory differs')
    by_operation = {
        'consider_appointment':'professional', 'select_appointment':'professional',
        'consider_review_assignment':'regulatory_design', 'decide_approval':'regulatory_completion',
        'consider_supply_order':'procurement_accepted', 'select_supplier':'procurement_refused',
        'select_preferred_bid':'micro_selection', 'select_tender_invitees':'invitation_evaluation_award',
        'evaluate_bid':'invitation_evaluation_award', 'consider_tender':'invitation_evaluation_award',
        'decide_contract_terms':'invitation_evaluation_award', 'decide_contract_award':'invitation_evaluation_award',
        'evaluate_project_opportunity':'monthly_pipeline', 'consider_financing':'fresh_financing',
        'select_financing_offer':'fresh_financing'}
    require(set(by_operation.values())-{'fresh_financing','monthly_pipeline'}<=set(reused['cases'])
        and fresh['financing_full']['owner_selections'] and monthly['specialized_business_checks']['pipeline']['proofs'],
        'Coverage references a missing actual business verification')
    operations = []
    for row in index['operation_contracts']:
        operation = row['operation']
        if operation=='decide_monthly_operation':
            actual = [p for p in monthly['subactions'] if p['role']==row['role']]
            require(actual, 'Role has no actual monthly links')
            evidence = {'file':'monthly-reuse-checks.json', 'role':row['role'], 'subaction_count':len(actual)}
        else:
            key = by_operation[operation]
            evidence = {'file':'business-final-checks.json' if key=='fresh_financing' else
                'monthly-reuse-checks.json' if key=='monthly_pipeline' else 'reused-business-checks.json', 'case':key}
        operations.append({'role':row['role'], 'operation':operation, 'status':'actual_records_verified',
            **{k:row[k] for k in ('macro_input','micro_handler','return_to_macro','feedback_consumer')},
            'evidence':evidence, 'original_evidence':row['evidence']})
    family_keys = {'opportunity':'monthly_pipeline', 'financing':'fresh_financing', 'professional_appointment':'professional',
        'design':'design_higher', 'regulatory':'regulatory_design', 'tender_clarification':'clarification',
        'bid_evaluation_award_signature':'fresh_tender_and_micro_selection', 'procurement':'fresh_tender_and_procurement_refused',
        'supply_progress_delay':'supply_delay', 'construction_inspection':'fresh_construction', 'site_safety':'safety',
        'variation':'fresh_construction', 'suspension':'suspension', 'payment':'payment_delayed', 'final_account':'fresh_tender'}
    require(set(family_keys)=={r['family'] for r in index['lifecycle_business_families']}, 'Lifecycle family inventory differs')
    return {'status':'passed_combined_scenarios_and_explicit_compatible_reuse', 'operation_contracts':operations,
        'nonmonthly_actual_links':links,
        'monthly_subactions':32, 'lifecycle_families':[{'family':r['family'],'status':'actual_records_verified',
            'verification_case':family_keys[r['family']], 'handler':r['micro_handler'],
            'feedback_consumer':r['feedback_consumer']} for r in index['lifecycle_business_families']],
        'required_blockers':[], 'pending_joint_validation':[], 'original_plan_complete':False,
        'scope':'All current macro business operation identities and representative event families. Counts overlap. Pure macro diagnostics, physical receipts, cash clearance and 438 detailed branches are separate.'}


def verify_preservation(config):
    previous = ROOT/config['macro_baseline_delivery']
    pins = read(previous/'delivered-implementation-pins.json')['files']
    current = macro_snapshot()
    for name, digest in current['files'].items():
        require(pins[(Path(current['root'])/name).as_posix()]==digest, 'Macro differs from final GOAL 3 baseline: '+name)
    require(len(current['python_sources'])==120 and set(current['python_sources'])=={
        n for n in current['files'] if n.endswith('.py')}, 'Added or removed macro Python source')
    counts = {}
    for label, base in [('goal3_final', previous), ('prior_delivery', ROOT/'output/integration/goal3_remaining_20261019_01')]:
        files = read(base/'artifact-manifest.json')['files']
        for name, digest in files.items():
            require(sha(base/name)==digest, 'Historical artifact changed: '+str(base/name))
        counts[label] = len(files)
    historical = read(ROOT/'output/integration/goal3_remaining_20261019_01/preflight.json')['historical_files']
    for name, digest in historical.items():
        require(sha(ROOT/name)==digest, 'Earlier historical evidence changed: '+name)
    return {'macro_files_unchanged_from_goal3':len(current['files']), 'macro_python_files':120,
        'historical_files_unchanged':len(historical), 'sealed_delivery_artifacts_unchanged':counts,
        'macro_changes_in_goal4':[], 'old_source_version_headers_retained_as_history':True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'config/goal4_integration.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv); directory = args.output.resolve(); config = read(args.config)
    require(directory.is_relative_to(ROOT), 'Use a new output directory inside this repository')
    require(config['schema_version']=='goal4-integration.v1', 'Unknown GOAL 4 configuration')
    if not args.check_only:
        directory.mkdir(parents=True, exist_ok=False)
        _write(directory, 'source-config.json', config)
        _write(directory, 'macro-before.json', macro_snapshot())
        run_cases(directory, config)
    require(read(directory/'source-config.json')==config, 'Saved scenario configuration differs')
    checks = verify_cases(directory, config)
    save_or_match(directory, 'business-final-checks.json', checks)
    print('Checking applicable archived business and monthly evidence without replay', flush=True)
    reused = verify_reused_business(); monthly = verify_reused_monthly()
    save_or_match(directory, 'reused-business-checks.json', reused)
    # Original comparison oracles contain reference tuples. Compare the same
    # JSON representation that was persisted, preserving values and order.
    save_or_match(directory, 'monthly-reuse-checks.json', json.loads(json.dumps(monthly, allow_nan=False)))
    links = verify_operation_links(directory)
    save_or_match(directory, 'coverage-checks.json', coverage(reused, monthly, checks, links))
    save_or_match(directory, 'preservation-checks.json', verify_preservation(config))
    if (directory/'artifact-manifest.json').exists():
        for name, digest in read(directory/'artifact-manifest.json')['files'].items():
            require(sha(directory/name)==digest, 'Sealed GOAL 4 artifact changed: '+name)
    if (directory/'implementation-pins.json').exists():
        for name, digest in read(directory/'implementation-pins.json')['files'].items():
            require(sha(ROOT/name)==digest, 'Delivered GOAL 4 implementation changed: '+name)
    print(json.dumps({'status':'business_and_coverage_checks_passed','output':str(directory)}), flush=True)


if __name__ == '__main__':
    main()
