"""Fixed 3C business acceptance using the existing original simulation CLI.

Checks saved business inputs/results and actual consumers, not source discovery.
"""
import argparse
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from integration.contractor_tender_development import _write, verify_bundle
from integration.professional_design_feedback_development import build_bundle
from integration.professional_methods_native import result_judgment, OPERATIONS
from integration.verify_professional_monthly_chain import run_existing_input
from integration.verify_tender_basic import file_hash, verify_history
from integration.verify_tender_closed_loop import ROOT, read, require, one, digest_valid, macro_hashes
from src.coordination.tasks import TaskIdentity, task_digest


def verify_scenario(directory):
    for manifest in (directory / 'input').rglob('input-manifest.json'):
        verify_bundle(manifest.parent)
    require(read(directory / 'exit.json')['exit_code'] == 0, 'Original process failed')
    initial = read(directory / 'input/macro-request.json')
    require(len(initial['initial_projects']) == 1 and all(not p['engagements'] and not p['event_log']
        and not p['contracts'] and p['estimated_cost'] is None
        and all(p[k] is None for k in ('selected_architect_id','selected_engineer_id','selected_qs_id'))
        for p in initial['initial_projects']), 'Prefilled appointment or design execution result')
    output = read(directory / 'runtime/result.json')
    simulation = output['simulation']; host = output['module_host_extension']['host']
    require(simulation['status'] == 'completed' and simulation['current_tick'] == 2, 'Incomplete original business run')
    records = host['monthly']['requests']; events = host['monthly']['original_global_events']
    require(len(records) == 6 and not any(e['data'].get('agent_observer_errors') for e in events), 'Missing monthly records or failed event observer')
    database = directory / 'runtime/tasks.sqlite'; before = file_hash(database)
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        tasks = [json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata = {k: json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers = [json.loads(v) for table in ('architect_learning_results','engineer_learning_results',
            'architect_appointment_results','engineer_appointment_results','qs_appointment_results',
            'architect_intake_results','engineer_intake_results','qs_intake_results','owner_commission_results')
            for v, in db.execute('SELECT record FROM ' + table)]
        snapshots = {k:json.loads(v) for k,v in db.execute('SELECT task_key,record FROM invocation_snapshots')}
    key = lambda i: TaskIdentity(**i).key
    micros = {key(r['identity']):r for r in workers}
    task_map = {key(t['identity']):t for t in tasks}
    require(all(t['state'] == 'output_formed' and task_digest(t['output']) == t['output_sha256'] for t in tasks), 'Unformed/altered original task')
    plans = read(directory / 'input/design-feedback-input.json')['plans']
    proofs = []
    for record in sorted(records, key=lambda r:(r['scope']['tick'],r['scope']['organization_id'])):
        digest_valid(record)
        require(metadata[record['key']] == record and record['state'] == 'formed', 'Changed durable record')
        identity = record['identity']; org = identity['organization_id']; tick = record['scope']['tick']
        micro = micros[key(identity)]; digest_valid(micro)
        snapshot = snapshots[key(identity)]; digest_valid(snapshot, 'snapshot_sha256')
        require(micro['result'] == task_map[key(identity)]['output'] and micro['result_sha256'] == task_digest(micro['result'])
            == record['result_sha256'] and micro['source_reading_sha256'] == task_digest(micro['source_reading'])
            and task_digest(snapshot['context']) == identity['context_sha256']
            and task_digest(snapshot['action_input']) == identity['input_sha256'], 'Original micro result/reading/invocation mismatch')
        observed = record['observed']; judgment = result_judgment(micro)
        require(task_digest(record['native_request']) == observed['native_request_sha256'], 'Request identity changed')
        def source(kind):
            return one(micro['source_reading'], lambda s:s['ref']['kind'] == kind, 'Missing original '+kind)['projection']
        observation = source('MonthlyMethodObservation'); policy = source('MonthlyMethodPolicy')
        require(observation['design_results'] == observed['design_results']
            and any(s['projection'].get('content_hash') == task_digest(observed) for s in micro['source_reading']),
            'A12 did not read exact actual design feedback')
        plan = one(plans, lambda p:(p['organization_id'],p['tick']) == (org,tick), 'Missing original monthly plan')
        placeholder = one(plan['objects'],lambda r:r['ref'] == plan['observation_ref'], 'Missing observation placeholder')['value']
        require(all(placeholder[k] is None for k in ('regulatory_pressure','native_capability','native_free_ratio','prior_own_outcomes','design_results')),
            'Actual observations or prior execution were prefilled')
        require(source(identity['role']+'LearningState')['coverage'] == 'unknown' and source('Capability')['status'] == 'unknown',
            'Aggregate feedback became complete formal learning/qualification history')
        for result, review in zip(observed['design_results'], judgment.design_review, strict=True):
            event = one(events,lambda e:e['event_id'] == result['event']['event_id'],'Missing actual design update')
            require(event == result['event'] and task_digest(event) == result['event_sha256'] == review['event_sha256']
                and event['tick'] == tick and event['stage'] == 'design'
                and event['data']['design_quality'] == result['design_quality']
                and event['data']['information_quality'] == result['information_quality']
                and event['data']['planned_cost'] == result['estimated_cost'], 'Substituted design source')
            appointment = one(events,lambda e:e['event_id'] == result['appointment_event']['event_id'],'Missing actual appointment')
            transition = one(events,lambda e:e['event_id'] == result['coordination_transition']['event_id'],'Missing actual design transition')
            confirmed = micros[key(result['appointment_identity'])]; digest_valid(confirmed)
            require(appointment == result['appointment_event'] and transition == result['coordination_transition']
                and task_digest(appointment) == result['appointment_event_sha256']
                and task_digest(transition) == result['coordination_transition_sha256']
                and confirmed['result_sha256'] == result['appointment_result_sha256'] == task_digest(confirmed['result'])
                and confirmed['result']['payload']['choice'] == 'confirm'
                and confirmed['identity']['organization_id'] == org, 'Not an actual own confirmed appointment')
            ratio = Decimal(str(result['estimated_cost'])) / Decimal(str(result['initial_budget']))
            dgap = max(Decimal(0),Decimal(str(policy['design_review']['minimum_design_quality']))-Decimal(str(result['design_quality'])))
            igap = max(Decimal(0),Decimal(str(policy['design_review']['minimum_information_quality']))-Decimal(str(result['information_quality'])))
            excess = max(Decimal(0),ratio-Decimal(str(policy['design_review']['maximum_estimate_budget_ratio'])))
            require(Decimal(review['design_gap']) == dgap and Decimal(review['information_gap']) == igap
                and Decimal(review['estimate_budget_ratio']) == ratio and Decimal(review['cost_excess']) == excess
                and review['priority'] == ('cost_review' if excess else 'information_coordination' if igap else 'design_review' if dgap else 'no_aggregate_gap'),
                'Parameters did not enter the actual gap/ratio/priority calculation')
        history = observed['prior_own_monthly_outcomes']
        require(history == observation['prior_own_outcomes'] and len(history) == tick-1, 'Incomplete actual prior history')
        for h in history:
            actual = one(events,lambda e:e['event_id'] == h['event_id'],'Missing earlier actual operation')
            prior = micros[key(h['micro_identity'])]
            require(actual['agent_id'] == org and actual['tick'] < tick and task_digest(actual) == h['source_event_sha256']
                and prior['result_sha256'] == h['micro_result_sha256']
                and result_judgment(prior).design_review == h['design_review'], 'Substituted prior actual execution/design judgment')
        if tick == 2 and judgment.design_review:
            require(all(r['prior_review_event_ids'] and r['prior_executed_operation_ids'] for r in judgment.design_review)
                and judgment.prior_actual_improvement_count == 1 and not judgment.participate,
                'Later A12 did not use the same prior actual execution to constrain repetition')
        pressure = Decimal(observation['regulatory_pressure']['value'])
        current = Decimal(observation['native_capability']['value']); free = Decimal(observation['native_free_ratio']['value'])
        target = min(Decimal(1),Decimal(policy['baseline_requirement']['value'])+Decimal(policy['regulatory_pressure_weight']['value'])*pressure)
        needs = any(r['needs_review'] for r in judgment.design_review)
        count = sum(h['participated'] for h in history)
        participate = (target-current >= Decimal(policy['minimum_shortfall']['value']) or needs) and free >= Decimal(policy['minimum_free_ratio']['value']) and count < policy['maximum_prior_improvements']
        require(judgment.participate == participate and judgment.prior_actual_improvement_count == count, 'Actual design-based decision changed')
        proposal = one(tasks, lambda t:t['identity']['purpose']=='propose' and t['output'].get('factors',{}).get('micro_task_key')==key(identity),'Missing original proposal')['output']
        final = one(tasks, lambda t:t['identity']['purpose']=='decide' and t['output'].get('data',{}).get('micro_task_key')==key(identity),'Missing final confirmation')['output']
        actual = one(events,lambda e:e['event_type']=='agent_operation' and e['agent_id']==org and e['tick']==tick,'Missing actual monthly execution')
        require(final['decision'] == judgment.participate == actual['data']['decision_accepted']
            and actual['data']['operation'] == (OPERATIONS[identity['role']] if participate else 'maintain_operations')
            and proposal['factors']['micro_result_sha256'] == final['data']['micro_result_sha256'] == micro['result_sha256']
            and task_digest(proposal) == record['proposal_response_sha256'] == final['data']['proposal_response_sha256']
            and actual['description'] == proposal['data']['description'] == judgment.interpretation+' '+judgment.method_focus,
            'Native execution was not the formed micro proposal/final decision')
        proofs.append({'identity':identity,'result_sha256':micro['result_sha256'],'observed':observed,
            'policy':policy,'judgment':judgment.model_dump(mode='json'),'proposal':proposal,'final':final,'actual_event':actual})
    require(file_hash(database) == before, 'Read-only verification changed the task database')
    return {'proofs':proofs,'technical_tasks':len(tasks),'all_tasks_formed':True,'database_sha256':before,
        'actual_design_consumers':sum(bool(p['judgment']['design_review']) for p in proofs),
        'later_actual_execution_consumers':sum(bool(p['judgment']['design_review']) and p['judgment']['prior_actual_improvement_count']>0 for p in proofs)}


def collect_checks(directory, config):
    require(config['schema_version']=='professional-design-feedback.v1' and config['ticks']==2
        and config['scenarios']=={'lower_qs_accuracy':0.2,'higher_qs_accuracy':0.9}, 'Unsupported fixed acceptance configuration')
    cases={name:verify_scenario(directory/name) for name in config['scenarios']}
    originals={name:read(directory/name/'input/macro-request.json') for name in cases}
    normalized=[]
    for name, request in originals.items():
        request=deepcopy(request)
        for a in request['agents']:
            if a['agent_id']=='professional-qs':
                require(a.pop('cost_estimation_capability')==config['scenarios'][name], 'Initial controlled capability changed')
        normalized.append(request)
    require(normalized[0]==normalized[1], 'Controlled macro inputs differ beyond initial QS accuracy')
    normalized_plans=[]
    for name in cases:
        plans=read(directory/name/'input/design-feedback-input.json')
        normalized_plans.append(json.dumps(plans,sort_keys=True).replace(config['run_id']+'-'+name,'SAME_RUN'))
    require(normalized_plans[0]==normalized_plans[1], 'Private review policy or initial decision sources differ across cases')
    comparison=[]
    for name,case in cases.items():
        require(case['actual_design_consumers']==4 and case['later_actual_execution_consumers']==2, 'Missing own design or later actual execution consumers')
        first=one(case['proofs'],lambda p:p['identity']['organization_id']=='professional-architect' and p['observed']['scope']['tick']==1,'Missing first Architect judgment')
        result,=first['observed']['design_results'];review,=first['judgment']['design_review']
        require(abs(result['estimated_cost']-1000*(.90+.20*(1-config['scenarios'][name])))<1e-9, 'Estimated cost not the original native QS formula')
        require(review['priority']==('cost_review' if name=='lower_qs_accuracy' else 'information_coordination'), 'Controlled difference did not change actual review priority')
        require(first['judgment']['participate'] and Decimal(first['judgment']['capability_shortfall'])<0,
            'Design gap did not influence the actual method decision independently of the capability shortfall')
        comparison.append({'scenario':name,'initial_qs_accuracy':config['scenarios'][name],
            'actual_native_result':result,'actual_micro_review':review,'actual_method_operation':first['actual_event']})
    return {'batch':'3C-design-feedback','status':'aggregate_design_feedback_executed_remaining_professional_gaps_blocked',
        'comparison':comparison,'cases':cases,'macro':macro_hashes(),'overall_goal3_complete':False,'whole_3c_complete':False,
        'boundary':'Three native design aggregate fields are consumed. Owner design_coordination_task detailed dispatch and N03 qualification judgment remain blocked; no detailed work or credential completion inferred.'}


def seal(directory, checks):
    _write(directory,'checks.json',checks)
    names=['src/actions/contracts/professional_monthly_methods.py','src/actions/roles/professional_monthly_methods.py',
        'integration/professional_methods_development.py','integration/professional_design_feedback.py',
        'integration/professional_design_feedback_development.py','integration/verify_professional_design_feedback.py',
        'config/professional_design_feedback.json','config/gba_v1_business_wiring.json','config/gba_v1_goal3_scope.json',
        'docs/3C设计聚合反馈接线与验收.md','docs/宏观动作接线清单.md','docs/GOAL3范围校准与剩余接线.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'professional-design-feedback-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():file_hash(p) for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{n:file_hash(ROOT/n) for n in names if (ROOT/n).is_file()}})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'config/professional_design_feedback.json')
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args(argv);directory=args.output.resolve()
    if not args.check_only:
        directory.mkdir(parents=True,exist_ok=False)
        config=read(args.config);_write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,accuracy in config['scenarios'].items():
            build_bundle(directory/name/'input',run_id=config['run_id']+'-'+name,qs_accuracy=accuracy,design_review=config['design_review'])
            run_existing_input(directory/name,assembly_hook='integration.professional_design_feedback:configure_assembly')
    else:
        config=read(directory/'source-config.json')
        if (directory/'artifact-manifest.json').is_file(): verify_history(directory)
    checks=collect_checks(directory,config)
    require(checks['macro']==read(directory/'macro-before.json'), 'Frozen macro changed')
    if not args.check_only: seal(directory,checks)
    print(json.dumps({'status':checks['status'],'output':str(directory),'cases':len(checks['cases'])}))


if __name__=='__main__':main()
