"""Run the fixed 3B financing scenario and audit its saved native/micro chain."""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from integration.bank_financing_development import build_bundle
from integration.contractor_tender_development import verify_bundle, _write
from integration.verify_tender_closed_loop import ROOT, read, require, one, digest_valid, macro_hashes
from src.coordination.tasks import TaskIdentity, task_digest


def verify_scenario(directory, config, *, macro_snapshot_reader=macro_hashes):
    """Inspect original saved records; never open a writable store or replay work."""
    require(config['schema_version'] == 'financing-chain-acceptance.v1'
        and config['bundle_options'] == dict(with_owner=True, feedback_followup=True,
            with_bank_strategy=True, with_arrangement=True), 'Unsupported fixed financing configuration')
    verify_bundle(directory/'input')
    initial = read(directory/'input/macro-request.json')
    require(not initial['initial_projects'],
        'Projects or formal financing outcomes must not be prefilled')
    require(read(directory/'exit.json')['exit_code'] == 0, 'Native process did not succeed')
    simulation = read(directory/'runtime/result.json')['simulation']
    expected = config['expected']
    require(simulation['status'] == 'completed' and simulation['current_tick'] == expected['ticks']
        and len(simulation['project_results']) == expected['projects'], 'Incomplete native financing window')
    events = [e for p in simulation['project_results'] for e in p['event_log']]
    require(not any(e['data'].get('agent_observer_errors') for e in events), 'Native feedback observer failed')
    database = directory/'runtime/tasks.sqlite'
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True) as db:
        tasks = [json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata = {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers = [json.loads(v) for table in ('bank_strategy_results', 'bank_intake_results',
            'bank_credit_results', 'bank_quote_results', 'owner_financing_results', 'bank_arrangement_results')
            for v, in db.execute('SELECT record FROM '+table)]
    require(all(t['state'] == 'output_formed' and t['output_sha256'] == task_digest(t['output'])
        for t in tasks), 'Unformed or altered durable task')
    by_key = {TaskIdentity(**t['identity']).key:t for t in tasks}
    saved = {TaskIdentity(**r['identity']).key:r for r in workers}
    for r in workers:
        digest_valid(r)
        key = TaskIdentity(**r['identity']).key
        require(r['result']['kind'] == 'completed' and r['result_sha256'] == task_digest(r['result'])
            and r['source_reading_sha256'] == task_digest(r['source_reading'])
            and by_key[key]['output'] == r['result'], 'Worker, original sources and task disagree')

    def worker(identity):
        return saved[TaskIdentity(**identity).key]

    def source(record, kind):
        return one(record['source_reading'], lambda r:r['ref']['kind'] == kind,
            'Missing unique original '+kind)['projection']

    def event_for(scope, kind, agent=None):
        return one(events, lambda e:e['project_id'] == scope['project_id'] and e['tick'] == scope['tick']
            and e['event_type'] == kind and (agent is None or e['agent_id'] == agent), 'Missing native '+kind)

    def transport(record, *, org, operation, decision, micro):
        scope = record['scope']
        proposal = one(tasks, lambda t:t['identity']['organization_id'] == org
            and t['identity']['purpose'] == 'propose' and t['identity']['action_id'] == operation
            and t['output'].get('factors',{}).get('native_financing_scope') == scope, 'Missing original proposal')
        final = one(tasks, lambda t:t['identity']['organization_id'] == org
            and t['identity']['purpose'] == 'decide' and t['identity']['action_id'] == decision
            and t['output'].get('data',{}).get('native_financing_scope') == scope, 'Missing original final decision')
        key = TaskIdentity(**micro['identity']).key
        require(task_digest(proposal['output']) == record['proposal_response_sha256']
            == final['output']['data']['proposal_response_sha256'], 'Transport changed the original proposal')
        for data in (proposal['output']['factors'], final['output']['data']):
            require(data['micro_task_key'] == key and data['micro_result_sha256'] == micro['result_sha256'],
                'Final decision substituted the micro result')
        require(proposal['output']['accepted'] == final['output']['decision'], 'Final acceptance differs from micro proposal')
        return proposal, final

    def history(row, tick, recipient):
        e = one(events, lambda e:e['event_id'] == row['event_id'], 'History lost its actual event')
        require(e['event_type'] == 'project_financing_selected' and e['tick'] == row['tick'] < tick
            and e['project_id'] == row['project_id'] and e['agent_id'] == row['owner_id']
            and e['data']['selected_bank_id'] == row['selected_bank_id']
            and row['recipient_organization_id'] == recipient, 'History scope or recipient changed')
        p = one(tasks, lambda t:t['identity']['purpose'] == 'propose'
            and task_digest(t['output']) == row['proposal_response_sha256'], 'Missing historical proposal')
        f = one(tasks, lambda t:t['identity']['purpose'] == 'decide'
            and task_digest(t['output']) == row['final_response_sha256'], 'Missing historical final')
        require(p['output']['data']['selected_bank_id'] == f['output']['data']['selected_bank_id']
            == e['data']['selected_bank_id'] and e['data']['proposal_response_sha256'] == task_digest(p['output']),
            'History is not the actual originally executed choice')
        if recipient == row['owner_id']:
            require(row['micro_result_sha256'] == saved[row['micro_task_key']]['result_sha256']
                == e['data']['micro_result_sha256'], 'Owner history lost its own original micro source')
        else:
            require(recipient == row['selected_bank_id'] and not any(k.startswith('micro_') for k in row),
                'Bank received Owner private task identity')
        return {'event_id':e['event_id'], 'event_sha256':task_digest(e), 'tick':e['tick']}

    banks = [v for k,v in metadata.items() if k.startswith('bank_financing_native_request:')]
    owners = [v for k,v in metadata.items() if k.startswith('owner_financing_native_request:')]
    reviews = [v for k,v in metadata.items() if k.startswith('bank_arrangement_received:')]
    require((len(banks),len(owners),len(reviews)) == (expected['bank_requests'],
        expected['owner_selections'],expected['private_arrangement_reviews']), 'Financing contact counts differ')
    bank_proofs, owner_proofs, review_proofs, later = [], [], [], []
    for row in banks:
        digest_valid(row)
        require(row['state'] == 'formed' and set(row['steps']) == {'BANK-A01','BANK-A02','BANK-A03','BANK-A04'},
            'Original Bank stages incomplete')
        steps = {a:worker(r['identity']) for a,r in row['steps'].items()}
        for action,r in steps.items():
            require(r['result_sha256'] == row['steps'][action]['result_sha256'], 'Saved Bank stage changed')
        org,scope = row['native_request']['agent']['agent_id'],row['scope']
        amount = row['native_request']['inputs']['requested_amount']
        project = one(simulation['project_results'],lambda p:p['project_id']==scope['project_id'],'Missing native project')
        owner = one(initial['agents'],lambda a:a['agent_id']==scope['owner_id'],'Missing native Owner')
        ratio = max(.25,min(.65,.65-.35*owner['financial_capacity']))
        require(amount == project['initial_budget']*ratio, 'Requested amount lost its actual macro calculation')
        for action in ('BANK-A02','BANK-A03','BANK-A04'):
            application = source(steps[action], 'FinanceApplication')
            require(Decimal(application['requested']['value']) == Decimal(str(amount))
                and application['requested']['currency'] == 'HKD', 'Native amount did not reach actual micro stage')
        a01,a02,a03,a04 = [steps[a] for a in ('BANK-A01','BANK-A02','BANK-A03','BANK-A04')]
        feedback = row['strategy_feedback']
        require(any(s['ref']['kind']=='Evidence' and s['projection'].get('content_hash')==task_digest(feedback)
            for s in a01['source_reading']), 'A01 source did not bind the actual feedback')
        expected_count = int(scope['tick'] == 2 and org == 'finance-bank-a')
        require(feedback['selected_count'] == len(feedback['history']) == expected_count,
            'Strategy did not use expected strictly earlier own selection')
        observation = source(a01,'Observation')['interval']['value']
        require(observation['lower']['value'] == observation['upper']['value'] == str(expected_count)
            and a01['result']['payload']['choice'] == ('revise_strategy' if expected_count else 'retain_strategy')
            and a02['result']['payload']['choice'] == 'accept_for_review'
            and a03['result']['payload']['choice'] == 'recommend'
            and a04['result']['payload']['choice'] == ('decline' if expected_count else 'offer'),
            'Feedback failed to affect the original strategy/quote decisions')
        policy = source(a04,'QuoteAuthorityPolicy')['maximum_principal']['value']
        require(Decimal(policy['value']) == (0 if expected_count else 100000000), 'A01 policy did not constrain A04')
        consumed = [history(h,scope['tick'],org) for h in feedback['history']]
        proposal, final = transport(row, org=org, operation='consider_financing',
            decision='bank_project_financing', micro=a04)
        e = event_for(scope,'bank_financing_decision',org)
        require(e['data']['micro_result_sha256'] == a04['result_sha256']
            and e['data']['micro_task_key'] == TaskIdentity(**a04['identity']).key
            and e['data']['accepted'] is (not bool(expected_count))
            and e['data']['requested_amount'] == amount
            and e['data']['proposal_response_sha256'] == row['proposal_response_sha256'], 'Macro did not execute Bank micro result')
        if not expected_count:
            principal = Decimal(a04['result']['payload']['terms']['principal_limit']['value'])
            require(Decimal(str(e['data']['approved_amount'])) == principal
                and abs(Decimal(str(amount))-principal) < Decimal('.01'), 'Native amount/principal linkage lost')
        proof = {'scope':scope,'bank_id':org,'requested_amount_HKD':amount,'micro_A04_task_key':TaskIdentity(**a04['identity']).key,
            'micro_A04_result_sha256':a04['result_sha256'],'micro_A01_choice':a01['result']['payload']['choice'],
            'own_selected_count':expected_count,'quote_ceiling_HKD':policy['value'],
            'micro_A04_choice':a04['result']['payload']['choice'],'actual_event':e,'consumed_actual_history':consumed}
        bank_proofs.append(proof)
        if consumed:
            later.append(proof)
    for row in owners:
        digest_valid(row)
        org,scope = row['identity']['organization_id'],row['scope']
        original = worker(row['identity'])
        require(row['state'] == 'formed' and original['result_sha256'] == row['result_sha256']
            and original['result']['payload']['choice'] == 'accept_offer', 'Owner original choice not formed')
        proposal,final = transport(row,org=org,operation='select_financing_offer',
            decision='owner_financing_selection',micro=original)
        observed = row['observed']
        amount = observed['funding_requirement']['requested_amount']
        funding = source(original,'FundingProfile')
        require(Decimal(funding['funding_lines'][0]['planned_use']['value']['value']) == Decimal(str(amount)),
            'Current native requirement did not enter Owner calculation')
        preference = observed['feedback_preference']
        consumed = [history(h,scope['tick'],org) for h in preference['history']]
        require(len(consumed) == int(scope['tick']==2), 'Owner did not read own previous actual financing')
        for p in preference['priorities']:
            require(p['priority'] == p['base_priority'] + preference['repeat_lender_priority_penalty']*p['earlier_selection_count'],
                'Actual history did not affect the comparison preference')
        for origin in observed['bank_origins']:
            e = one(events,lambda e:e['event_id']==origin['event_id'],'Missing actual disclosed quote')
            require(task_digest(e)==origin['native_event_sha256']
                and saved[origin['task_key']]['result_sha256']==origin['result_sha256']
                == e['data']['micro_result_sha256'], 'Owner consumed a substituted quote')
        e = event_for(scope,'project_financing_selected',org)
        project = one(simulation['project_results'],lambda p:p['project_id']==scope['project_id'],'Missing project')
        selected = 'finance-bank-a' if scope['tick']==1 else 'finance-bank-b'
        require(e['data']['selected_bank_id'] == project['selected_bank_id'] == selected
            == final['output']['data']['selected_bank_id']
            and e['data']['micro_result_sha256'] == original['result_sha256']
            and e['data']['accepted'] is True, 'Native selection did not execute the same micro choice')
        owner_proofs.append({'scope':scope,'micro_task_key':TaskIdentity(**original['identity']).key,
            'micro_result_sha256':original['result_sha256'],'funding_requirement':observed['funding_requirement'],
            'actual_event':e,'consumed_actual_history':consumed,'priorities':preference['priorities']})
    for row in reviews:
        digest_valid(row)
        original = worker(row['identity'])
        observed = row['observed']
        e = one(events,lambda e:e['event_id']==row['event_id'],'Missing actual selected Bank receipt')
        require(row['state']=='formed' and row['choice']=='confirm'
            and row['result_sha256']==original['result_sha256'] and observed['event_sha256']==task_digest(e)
            and e['data']['selected_bank_id']==row['organization_id']
            and saved[observed['quote_task_key']]['result_sha256']==observed['quote_result_sha256']
            and saved[observed['owner_task_key']]['result_sha256']==observed['owner_result_sha256']
            and original['result']['payload']['choice']=='confirm', 'A05 lost its actual offer/acceptance provenance')
        quote_event = one(events,lambda e:e['event_id']==observed['quote_event_id'],'Missing accepted native quote')
        require(quote_event['project_id']==e['project_id'] and quote_event['tick']==e['tick']
            and quote_event['agent_id']==row['organization_id']
            and quote_event['data']['micro_task_key']==observed['quote_task_key']
            and e['data']['micro_task_key']==observed['owner_task_key']
            and any(s['ref']['kind']=='PartyAcceptance' and
                s['projection'].get('agreement_sha256')==observed['accepted_agreement_sha256']
                for s in original['source_reading']), 'A05 acceptance does not refer to this same project/offer')
        require(not {r['ref']['kind'] for r in original['source_reading']}
            & {'FinanceArrangement','Account','Debt','Payment','Disbursement'}, 'Private A05 replaced formal finance/cash')
        review_proofs.append({'event_id':row['event_id'],'event_sha256':task_digest(e),
            'identity':row['identity'],'result_sha256':row['result_sha256'],'choice':row['choice'],
            'quote_task_key':observed['quote_task_key'],'owner_task_key':observed['owner_task_key']})
    require(len(later)==2 and len(workers)==40, 'Expected original micro feedback consumers absent')
    require(before==hashlib.sha256(database.read_bytes()).hexdigest(), 'Verification wrote the original journal')
    return {'batch':'3B','status':'passed_for_financing_decision_and_private_confirmation',
        'native_ticks':simulation['current_tick'],'projects':len(simulation['project_results']),
        'technical_tasks':len(tasks),'original_micro_actions':dict(Counter(r['identity']['action_id'] for r in workers)),
        'bank_requests':bank_proofs,'owner_selections':owner_proofs,'private_arrangement_reviews':review_proofs,
        'later_bank_strategy_consumers':len(later),'later_owner_history_consumers':2,
        'journal_sha256':before,'read_only':True,'macro':macro_snapshot_reader(),'overall_goal3_complete':False,
        'boundary':'Private indicative financing and A05 conditions; no formal credit/arrangement registration, signature, reservation, drawdown, payment or received cash.'}


def run_scenario(directory, config):
    build_bundle(directory/'input', run_id=config['run_id'], **config['bundle_options'])
    verify_bundle(directory/'input')
    args = [sys.executable, '-m', 'integration.run', '--input', str(directory/'input/macro-request.json'),
        '--output', str(directory/'runtime'), '--offline', '--input-format', 'gba_request',
        '--macro-mode', 'gba_v1_module', '--allow-native-project-generation',
        '--agent-client-factory', 'integration.native_routes:build_agent_client',
        '--agent-client-config', str(directory/'input/native-host.json'),
        '--module-assembly-hook', 'integration.bank_financing_native:configure_assembly',
        '--module-assembly-config', str(directory/'input/assembly-host.json')]
    _write(directory, 'command.json', args)
    with (directory/'stdout.log').open('xb') as stdout, (directory/'stderr.log').open('xb') as stderr:
        completed = subprocess.run(args, cwd=ROOT, stdout=stdout, stderr=stderr)
    _write(directory, 'exit.json', {'exit_code': completed.returncode})
    require(completed.returncode == 0, 'Native run failed; inspect preserved stderr and journal')


def audit_historical_monthly(directory):
    """Reuse historical actual monthly events with an explicit source-version boundary."""
    directory = Path(directory)
    path = directory/'monthly-strategy-loop.json'
    original = read(path)
    require(original['simulation']['status']=='completed' and original['simulation']['current_tick']==3,
        'Historical monthly window incomplete')
    database = directory/'tasks.sqlite'
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks = {TaskIdentity(**r['identity']).key:r
            for r in (json.loads(v) for v, in db.execute('SELECT record FROM tasks'))}
        records = {TaskIdentity(**r['identity']).key:r
            for r in (json.loads(v) for v, in db.execute('SELECT record FROM bank_strategy_results'))}
        quotes = {TaskIdentity(**r['identity']).key:r
            for r in (json.loads(v) for v, in db.execute('SELECT record FROM bank_quote_results'))}
    monthly = original['host']['monthly_strategy']
    events = {e['event_id']:e for e in original['events']}
    require(len(monthly['requests'])==len(events)==6, 'Historical monthly contact count differs')
    proofs = []
    for parent in monthly['requests']:
        digest_valid(parent)
        r = records[TaskIdentity(**parent['identity']).key]
        digest_valid(r)
        require(r['result_sha256']==parent['result_sha256']==task_digest(r['result'])
            and r['source_reading_sha256']==task_digest(r['source_reading'])
            and tasks[TaskIdentity(**r['identity']).key]['output']==r['result'], 'Historical strategy result changed')
        scope = parent['scope']
        e = one(list(events.values()),lambda e:e['tick']==scope['tick']
            and e['agent_id']==scope['organization_id'],'Missing actual monthly operation')
        require(e['data']['operation']==('review_credit_pipeline' if scope['tick']==1 else 'adjust_credit_terms'),
            'Original macro did not execute historical strategy')
        earlier = parent['observed']['prior_own_monthly_strategy']
        require(len(earlier)==scope['tick']-1,'Historical consumer lost earlier own outcomes')
        for h in earlier:
            require(h['tick'] < scope['tick'] and h['organization_id']==scope['organization_id']
                and h['source_event_sha256']==task_digest(events[h['event_id']])
                and h['micro_result_sha256']==records[h['micro_task_key']]['result_sha256']
                and h['final_response_sha256'] in {task_digest(t['output']) for t in tasks.values()
                    if t['identity']['purpose']=='decide'}, 'Monthly history lost its exact actual source')
        proofs.append({'scope':scope,'micro_identity':r['identity'],'micro_result_sha256':r['result_sha256'],
            'actual_event_id':e['event_id'],'actual_event_sha256':task_digest(e),
            'earlier_consumed_event_ids':[h['event_id'] for h in earlier]})
    late_quotes = []
    for parent in original['host']['requests']:
        if parent['scope']['tick']<2:
            continue
        q = quotes[TaskIdentity(**parent['steps']['BANK-A04']['identity']).key]
        digest_valid(q)
        paused = parent['scope']['tick']==3 and q['identity']['organization_id']=='finance-bank-a'
        policy = one(q['source_reading'],lambda s:s['ref']['kind']=='QuoteAuthorityPolicy','Missing historical policy')['projection']
        require((policy['maximum_principal']['value']['value']=='0') is paused
            and q['result']['payload']['choice']==('decline' if paused else 'offer'), 'Historical quote did not use strategy ceiling')
        late_quotes.append({'identity':q['identity'],'result_sha256':q['result_sha256'],
            'maximum_principal':policy['maximum_principal']['value'],'choice':q['result']['payload']['choice']})
    require(len(late_quotes)==8 and before==hashlib.sha256(database.read_bytes()).hexdigest(), 'Historical audit changed data')
    current_reader = hashlib.sha256((ROOT/'integration/bank_monthly_native_sources.py').read_bytes()).hexdigest()
    return {'status':'historical_actual_events_read_only_reused','source':str(path.relative_to(ROOT)),
        'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'journal_sha256':before,
        'actual_monthly_contacts':proofs,'later_quotes':late_quotes,
        'historical_source_implementations':monthly['source_implementations'],
        'current_source_reader_sha256':current_reader,
        'source_reader_unchanged':all(v['source_sha256']==current_reader for v in monthly['source_implementations'].values()),
        'current_combined_monthly_configuration_reaccepted':False,
        'boundary':'Historical monthly strategy and quote records only; current Bank application has evolved. Current combined monthly configuration remains pending integration.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=ROOT/'config/financing_chain.json')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    directory = args.output.resolve()
    if not args.check_only:
        directory.mkdir(parents=True, exist_ok=False)
        _write(directory, 'macro-before.json', macro_hashes())
        config = read(args.config)
        _write(directory, 'source-config.json', config)
        run_scenario(directory, config)
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    checks = verify_scenario(directory, read(directory/'source-config.json'))
    require(read(directory/'macro-before.json') == macro_hashes(), 'Frozen macro sources changed')
    if not args.check_only:
        _write(directory, 'checks.json', checks)
        write_delivery(directory, checks)
    print(json.dumps({'status': checks['status'], 'output': str(directory),
        'macro_unchanged_files': macro_hashes()['file_count']}))


def write_delivery(directory, checks):
    """Save a compact run record and byte hashes after business verification."""
    lines = ['# GOAL 3B 固定融资链运行记录', '',
        '状态：融资决策及私有条件确认通过；GOAL 3 整体未完成。', '',
        '原生运行 2 个时点、4 个生成项目；40 个原微观动作、168 个技术任务均形成结果。',
        '宏观基线 174 个文件及额外 Python 源文件在运行前后相同。', '',
        '| 项目 | 时点 | 实际选择 | 原宏观事件 | 微观结果摘要 |',
        '| --- | --- | --- | --- | --- |']
    for row in sorted(checks['owner_selections'],key=lambda r:r['scope']['project_id']):
        e = row['actual_event']
        lines.append(f"| {e['project_id']} | {e['tick']} | {e['data']['selected_bank_id']} | {e['event_id']} | {row['micro_result_sha256']} |")
    lines += ['', '宏观按项目 initial_budget × clamp(0.65 − 0.35 × 业主 financial_capacity, 0.25, 0.65) 计算 requested_amount。',
        '该数值进入原 A02/A03/A04 的 FinanceApplication.requested 和原 OWN-A05 的 FundingProfile.planned_use。',
        '第一轮实际选行被第二轮本行 A01 读取，观察计数从 0 变 1；原策略修订使 A04 新报价上限变为 0，原宏观执行拒绝。',
        '两名业主的后轮 OWN-A05 也读取各自实际历史；仅比较中的银行可得到其偏好序号调整，未形成新资金。', '',
        '复核：', '```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_financing_chain --check-only --output {directory.relative_to(ROOT).as_posix() if directory.is_relative_to(ROOT) else directory.as_posix()}",
        '```', '', '独立重跑：', '```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_financing_chain --config config/financing_chain.json --output output/integration/goal3b_new_run",
        '```', '',
        'command.json 保存实际原 CLI 参数，source-config.json 和 input/ 保存执行前输入；runtime/ 保存原结果、观察和任务库。',
        'checks.json 保存原任务→原宏观事件→后轮消费者的完整对应关系。',
        'BANK-A05 仅为私有协议条件确认。未生成正式授信/融资安排登记、签署、容量预留、提款或到账回执。',
        '月度策略、受理拒绝、附条件报价等已有分支证据与当前版本边界见 docs/融资链接线与验收.md。', '']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines),encoding='utf-8')
    files = {p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'}
    sources = ['config/financing_chain.json','integration/verify_financing_chain.py',
        'config/gba_v1_business_wiring.json','docs/融资链接线与验收.md','docs/宏观动作接线清单.md',
        'integration/bank_financing_development.py','integration/bank_financing_native.py',
        'integration/bank_financing_private.py','integration/bank_financing_strategy.py',
        'integration/owner_financing_native.py','integration/owner_financing_quote_views.py',
        'integration/bank_arrangement_native.py','integration/bank_arrangement_native_sources.py',
        'integration/bank_monthly_native.py','integration/bank_monthly_native_sources.py',
        'integration/project_financing_native.py','integration/project_financing_feedback.py']
    _write(directory,'artifact-manifest.json',{'schema_version':'financing-chain-artifacts.v1','files':files,
        'implementations':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources}})


if __name__ == '__main__':
    main()
