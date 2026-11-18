"""Inspect qualification source boundaries without issuing or applying credentials."""
import argparse
import ast
import json
from pathlib import Path
import sqlite3

from integration.contractor_construction_source_review import _source
from integration.verify_professional_chain import verify_scenario
from integration.verify_tender_basic import file_hash, verify_history
from integration.verify_tender_closed_loop import ROOT, _write, macro_hashes, one, read, require
from src.coordination.tasks import task_digest


OPERATION = 'maintain_professional_qualifications'
MISSING = [
    'current_authorized_own_credential_holder_issuer_scope_validity_and_complete_history',
    'independently_received_original_issuer_event_and_verification_service_authority',
    'actual_equivalent_original_verification_application_issuer_and_query_binding',
    'later_original_micro_consumer_of_the_same_authentic_credential_result',
]
BOUNDARY = ('Source inspection only. Original monthly activity and normalized capability are real, '
    'but do not establish issuance, renewal, verification, changed validity or applied qualification. '
    'Appointment qualification inputs are explicit scenario assumptions. No original task is replayed, '
    'no source state is changed and no micro coverage is added.')
IMPLEMENTATIONS = [
    'integration/engineer_qualification_sources.py', 'config/engineer_qualification_sources.json',
    'integration/verify_professional_chain.py', 'integration/verify_tender_basic.py',
    'integration/verify_tender_closed_loop.py', 'integration/contractor_construction_source_review.py',
    'src/actions/roles/engineer_learning.py', 'src/actions/contracts/engineer_learning_objects.py',
    'integration/engineer_qualification_verification_handoff.py',
    'integration/engineer_qualification_application_handoff.py',
]


def inspect_sources(config):
    require(set(config) == {'schema_version', 'source_directory', 'source_manifest_sha256',
        'organization_id', 'purpose'} and config['schema_version'] == 'engineer-qualification-sources.v1',
        'Unsupported qualification source configuration')
    require(isinstance(config['purpose'], str) and config['purpose'].strip(), 'Source purpose required')
    source = (ROOT / config['source_directory']).resolve()
    require(source.is_relative_to((ROOT / 'output/integration').resolve()), 'Expected preserved integration source')
    require(file_hash(source / 'artifact-manifest.json') == config['source_manifest_sha256'],
        'Pinned professional source manifest changed')
    historical = verify_history(source)
    original = verify_scenario(source, read(source / 'source-config.json'))
    simulation = read(source / 'runtime/result.json')['simulation']
    organization_id = config['organization_id']
    agent = one(simulation['agent_results'], lambda a: a['agent_id'] == organization_id and a['role'] == 'Engineer',
        'Own original Engineer missing')
    database = source / 'runtime/tasks.sqlite'
    before = file_hash(database)
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        tasks = [json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        intake = [json.loads(v) for v, in db.execute('SELECT record FROM engineer_intake_results')]
        learning = [json.loads(v) for v, in db.execute('SELECT record FROM engineer_learning_results')]
    native = []
    for feedback in read(source / 'runtime/observations.json')['records']:
        payload = feedback['payload']
        if payload['event_type'] != 'agent_operation' or payload['data'].get('operation') != OPERATION:
            continue
        if feedback['organization_id'] != organization_id:
            continue
        tick = payload['tick']
        require(payload['committed'] is True and payload['agent_id'] == organization_id, 'Uncommitted or other holder feedback')
        proposal = one(tasks, lambda t: t['identity']['organization_id'] == organization_id
            and t['identity']['purpose'] == 'propose'
            and t['identity']['request_id'] == f'proposal-tick{tick}-none-{organization_id}-decide_monthly_operation',
            'Unique original monthly proposal missing')
        final = one(tasks, lambda t: t['identity']['organization_id'] == organization_id
            and t['identity']['purpose'] == 'decide'
            and t['identity']['request_id'] == f'tick{tick}-no_project-{organization_id}-monthly_enterprise_operation',
            'Unique original monthly final missing')
        require(proposal['identity']['run_id'] == final['identity']['run_id'] == feedback['run_id']
            and proposal['output']['accepted'] is True and final['output']['decision'] is True
            and proposal['output']['action_type'] == final['output']['action_type'] == OPERATION
            and proposal['output']['factors']['decision_source'] == final['output']['data']['decision_source'] == 'native_macro'
            and not proposal['output']['factors'].get('micro_task_key'), 'Expected native-only original monthly route')
        memory = one(agent['episodic_memory'], lambda m: m.get('tick') == tick and m.get('operation') == OPERATION,
            'Own original monthly memory missing')
        require(memory['label'] == payload['data']['label'] and memory.get('capability_update') == payload['data'].get('capability_update'),
            'Native monthly feedback and memory disagree')
        native.append({'organization_id': organization_id, 'tick': tick, 'event_id': feedback['event_id'],
            'feedback': feedback, 'feedback_sha256': task_digest(feedback), 'original_proposal': proposal,
            'original_final': final, 'original_memory': memory, 'counts_as_micro_coverage': False})
    require(native, 'Pinned professional run has no original qualification activity; review a different source explicitly')
    assumptions = []
    for row in intake:
        if row['identity']['organization_id'] != organization_id:
            continue
        sources = {task_digest(s['ref']): s['projection'] for s in row['source_reading']}
        for item in row['source_reading']:
            if item['ref']['kind'] != 'Qualification':
                continue
            qualification = item['projection']
            evidence = [sources[task_digest(ref)] for ref in qualification['evidence_refs']]
            require(evidence and all(e['source_kind'] == 'synthetic' for e in evidence),
                'Qualification source is no longer wholly synthetic; review the actual issuer separately')
            assumptions.append({'identity': row['identity'], 'result_sha256': row['result_sha256'],
                'qualification': qualification, 'evidence': evidence, 'is_original_issuer_event': False})
    require(assumptions, 'Expected explicitly declared appointment qualification assumptions')
    require(all(r['result']['payload']['choice'] == 'record_feedback' for r in learning),
        'Qualification request exists; inspect its actual verification and application lineage separately')
    macro = macro_hashes()
    backend = Path(macro['root']) / 'gba_construction_sim/backend'
    profile = ROOT / backend / 'models/agent.py'
    tree = ast.parse(profile.read_text(encoding='utf-8-sig'))
    profile_class = one(tree.body, lambda n: isinstance(n, ast.ClassDef) and n.name == 'EnterpriseAgentProfile', 'Native profile missing')
    fields = [n.target.id for n in profile_class.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
    keywords = ('qualification', 'credential', 'licence', 'license', 'certification')
    hits = []
    for name in sorted(macro['python_sources']):
        text = (ROOT / macro['root'] / name).read_text(encoding='utf-8-sig')
        ast.parse(text)
        for number, line in enumerate(text.splitlines(), 1):
            if any(word in line.lower() for word in keywords):
                hits.append({'path': name, 'line': number, 'text': line.strip()})
    anchors = [_source(ROOT, (backend / path).as_posix(), symbol) for path, symbol in [
        ('agents/engineer_agent.py', 'EngineerAgent.decide_monthly_operation'),
        ('models/agent.py', 'EnterpriseAgentProfile'),
        ('simulation/agent_operation_scheduler.py', 'AgentOperationScheduler.step'),
    ]]
    anchors.extend(_source(ROOT, path, symbol) for path, symbol in [
        ('src/actions/roles/engineer_learning.py', '_maintain_engineering_experience'),
        ('integration/engineer_qualification_verification_handoff.py', 'prepare_engineer_qualification_verification_handoff'),
        ('integration/engineer_qualification_application_handoff.py', 'prepare_engineer_qualification_application_handoff'),
    ])
    require(file_hash(database) == before and verify_history(source) == historical, 'Read-only inspection changed source artifacts')
    return {'schema_version': 'engineer-qualification-source-inspection.v1',
        'status': 'waiting_independent_qualification_sources', 'batch': '3C-Engineer-qualification-sources',
        'source_directory': source.relative_to(ROOT).as_posix(), 'source_manifest_sha256': historical['manifest_sha256'],
        'source_database_sha256': before, 'historical_professional_verification': original['status'],
        'macro': macro, 'native_only_monthly_observations': native, 'synthetic_appointment_qualifications': assumptions,
        'original_learning_choices': [r['result']['payload']['choice'] for r in learning],
        'native_profile_fields': fields, 'source_anchors': anchors, 'native_keyword_hits': hits,
        'review_conclusion': 'No equivalent credential issuer, verification/application query or current credential history found in the reviewed native profile, scheduler, qualification-related source hits and preserved professional run. Keyword matches are discovery aids; they do not prove interface equivalence.',
        'missing': MISSING, 'micro_invocations': 0, 'counts_as_micro_coverage': False,
        'overall_goal3_complete': False, 'boundary': BOUNDARY}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/engineer_qualification_sources.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    directory = args.output.resolve()
    require(directory.is_relative_to((ROOT / 'output/integration').resolve()), 'Output must remain in workspace integration artifacts')
    if args.check_only:
        verify_history(directory)
        require(all(file_hash(ROOT / p) == h for p, h in read(directory / 'artifact-manifest.json')['implementations'].items()),
            'Current source inspector differs from sealed implementation')
        report = inspect_sources(read(directory / 'source-config.json'))
        require(report == read(directory / 'checks.json'), 'Saved source inspection differs from current read-only checks')
    else:
        report = inspect_sources(read(args.config))
        directory.mkdir(parents=True, exist_ok=False)
        _write(directory, 'source-config.json', read(args.config))
        _write(directory, 'checks.json', report)
        record = '\n'.join([
            '# 3C 工程师月度资质来源实查记录', '',
            '结论：等待独立资质来源；本批没有执行资质更新，没有新增微观覆盖。', '',
            '只读复核已封存的专业委任运行，原专业链验证通过。来源数据库与封存清单前后哈希一致。',
            '核对本机构月度原生提议、最终决定、已提交反馈及自身记忆：一项 EVT000015 / tick 1。',
            '该提议与最终决定明确来自 native_macro；事件表层 decision_source=llm_agent 不足以证明微观处理器参与。',
            '两项 A02 资质输入均有明确 synthetic 证据；原 A12 仅记录委任结果反馈，没有资质更新请求或签发事件。',
            '原宏观模型只有 qualification_level 等归一化字段；月度调度器按自身随机机制更新 technical_capability，未签发或续期证书。',
            '完整检查 174 个冻结文件及全部 120 个 Python 源码，保存相关符号锚点、模型字段和关键词定位；未找到本链所需等价签发/核验接口。', '',
            '可重复命令（新目录）：', '```powershell',
            '.venv-integration/Scripts/python.exe -m integration.engineer_qualification_sources --output output/integration/qualification_sources_new',
            '```', '', '仅复核本记录：', '```powershell',
            '.venv-integration/Scripts/python.exe -m integration.engineer_qualification_sources --check-only --output ' + directory.relative_to(ROOT).as_posix(),
            '```', '',
            'checks.json 保存原提议、最终决定、事件、自身记忆、来源输入及哈希。退出码 0 表示来源检查成功，业务状态仍为 waiting_independent_qualification_sources。',
            '后续须提供同一持证主体的当前完整记录、独立签发事件与核验服务权限，绑定原有 verification/application handoff，再验证真实结果及后轮消费。',
            '月度累计仍为 30/32，全清单 38 项来源或接口阻塞。GOAL 3 及原 PLAN 均未全部完成。', '',
        ])
        with (directory / 'RUN_RECORD.md').open('x', encoding='utf-8') as stream:
            stream.write(record)
        _write(directory, 'artifact-manifest.json', {'schema_version': 'engineer-qualification-source-artifacts.v1',
            'files': {p.relative_to(directory).as_posix(): file_hash(p) for p in directory.rglob('*') if p.is_file()},
            'implementations': {p: file_hash(ROOT / p) for p in IMPLEMENTATIONS}})
    print(json.dumps({'status': report['status'], 'native_only_events': len(report['native_only_monthly_observations']),
        'synthetic_qualifications': len(report['synthetic_appointment_qualifications']),
        'micro_invocations': 0, 'counts_as_micro_coverage': False, 'macro_files_unchanged': report['macro']['file_count']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
