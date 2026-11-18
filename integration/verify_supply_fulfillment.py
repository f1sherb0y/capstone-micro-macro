"""GOAL 3F actual supply-state provenance and explicit detailed-source waits."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys

from integration.contractor_tender_development import _write,_write_launch_files,verify_bundle
from integration.supply_fulfillment_native import GATES,SupplyFulfillmentObservation
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from src.coordination.tasks import TaskIdentity,task_digest


def validate_config(config):
    require(config['schema_version']=='supply-fulfillment-source-gates.v1' and config['ticks']==4
        and config['verified_detailed_issuers']=={} and config['scenarios']=={
            'reliable':dict(supply_reliability=1.0,material_quality=0.9),
            'low_reliability':dict(supply_reliability=0.0,material_quality=0.4)},'Unsupported fixed supply source-gate configuration')


def build_inputs(directory,*,run_id,profile,ticks):
    from integration.supplier_order_native_development import build_bundle
    directory.mkdir(parents=True,exist_ok=False);foundation=directory/'foundation'
    actors={org:org+'-execution-actor' for org in ('supply-owner','supply-contractor','supply-a','supply-b')}
    build_bundle(foundation,run_id=run_id,with_quote=True,with_product=True,with_screening=True,
        with_contractor=True,organization_actor_ids=actors)
    request=read(foundation/'macro-request.json');request['ticks']=ticks
    for agent in request['agents']:
        if agent['role']=='Supplier':agent.update(profile)
    _write(directory,'macro-request.json',request)
    _write(directory,'native-host.json',read(foundation/'native-host.json'))
    host=read(foundation/'assembly-host.json')
    _write(directory,'assembly-host.json',{**host,'settings':{'supplier':host['settings'],
        'supply_feedback':{'version':'1','verified_detailed_issuers':{}}}})
    _write(directory,'initial-profile.json',{'native_initial_supplier_profile':profile,'ticks':ticks,
        'phase':'authored_before_final_input_sealing_and_engine_construction',
        'boundary':'Only original native initial profiles/window. Foundation sources remain unchanged; normalized reliability/quality are not physical inventory, production, inspection, shipping or receipt facts.'})
    _write_launch_files(directory,assembly_hook='integration.supply_fulfillment_native:configure_assembly',readme_override=__doc__)


def run_scenario(directory,*,run_id,profile,ticks):
    build_inputs(directory/'input',run_id=run_id,profile=profile,ticks=ticks)
    verify_bundle(directory/'input')
    args=[sys.executable,'-m','integration.run','--input',str(directory/'input/macro-request.json'),
        '--output',str(directory/'runtime'),'--offline','--input-format','gba_request','--macro-mode','gba_v1_module',
        '--agent-client-factory','integration.native_routes:build_agent_client',
        '--agent-client-config',str(directory/'input/native-host.json'),
        '--module-assembly-hook','integration.supply_fulfillment_native:configure_assembly',
        '--module-assembly-config',str(directory/'input/assembly-host.json')]
    _write(directory,'command.json',args)
    with (directory/'stdout.log').open('xb') as stdout,(directory/'stderr.log').open('xb') as stderr:
        result=subprocess.run(args,cwd=ROOT,stdout=stdout,stderr=stderr)
    _write(directory,'exit.json',{'exit_code':result.returncode})
    require(result.returncode==0,'Original supply-state run failed; inspect preserved stderr and task journal')


def verify_scenario(directory):
    for manifest in (directory/'input').rglob('input-manifest.json'):verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Native supply-state process failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    require(simulation['status']=='completed' and simulation['current_tick']==4,'Original supply-state window incomplete')
    initial=read(directory/'input/macro-request.json')
    require(all(not p['selected_supplier_ids'] and not p['event_log'] for p in initial['initial_projects']),
        'Native supply execution/selection prefilled')
    events=[e for p in simulation['project_results'] for e in p['event_log']]
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Actual source observer failed')
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        records=[json.loads(v) for v, in db.execute('SELECT value FROM metadata WHERE key LIKE ?',
            (SupplyFulfillmentObservation.PREFIX+'%',))]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),
        'Earlier actual procurement or native transport unresolved')
    require(not any(t['identity']['role']=='Supplier' and t['identity']['action_id'] in GATES for t in tasks),
        'A detailed action was invoked without its authentic source/issuer')
    require(host['micro_fulfillment_actions_invoked']==0 and host['detailed_stage_status']=='blocked_missing_verified_native_sources'
        and {r['key']:r for r in host['supply_feedback']}=={r['key']:r for r in records},
        'Source waiting was misreported as micro fulfilment or export changed')
    require(len(host['supply']['requests'])==4 and len(host['supply']['contractor']['requests'])==2,
        'Existing actual supply selection prefix missing')
    for exported in host['supply']['requests']+host['supply']['contractor']['requests']:
        require(exported==metadata[exported['key']] and exported['state']=='formed','Original procurement export changed')
        digest_valid(exported)
    proofs=[]
    for r in records:
        digest_valid(r)
        e=one(events,lambda e:e['event_id']==r['event_id'],'Source observation lost actual native event')
        raw=json.loads(json.dumps(e));raw['data'].pop('agent_observer_errors',None)
        project=one(simulation['project_results'],lambda p:p['project_id']==r['project_id'],'Source project missing')
        engagements=[g for g in project['engagements'] if g['agent_id']==r['organization_id'] and g['role']=='Supplier']
        require(e['project_id']==r['project_id'] and e['tick']==r['tick'] and e['event_type']==r['event_type']
            and task_digest(raw)==r['source_event_sha256'] and r['organization_id'] in project['selected_supplier_ids']
            and any(task_digest(g)==r['engagement_sha256'] for g in engagements),
            'Source borrowed another Supplier/project/event or engagement')
        require(r['projection_fields']==['material_availability','material_quality','supply_delay_risk']
            and r['micro_actions_invoked']==0 and r['formal_effects_created'] is False
            and r['gates']=={a:{**v,'status':'blocked_missing_verified_native_sources','micro_identity':None} for a,v in GATES.items()},
            'Aggregate state was promoted into detailed facts or executed micro coverage')
        p=r['native_supplier_profile_averages'];s=r['native_state']
        if e['event_type']=='construction_progress_updated':
            require(math.isclose(s['material_quality'],p['average_material_quality'])
                and math.isclose(s['supply_delay_risk'],max(0,min(1,1-p['average_reliability']))),
                'Actual original supply calculation differs from current native supplier profiles')
        if e['event_type']=='supply_delay':
            require(math.isclose(round(s['material_availability'],3),e['data']['material_availability'])
                and e['data']['previous_material_availability']>e['data']['material_availability'],
                'Original supply delay did not actually reduce aggregate material availability')
        proofs.append({'organization_id':r['organization_id'],'project_id':r['project_id'],'tick':r['tick'],
            'event_id':e['event_id'],'event_type':e['event_type'],'source_event_sha256':r['source_event_sha256'],
            'native_state':s,'native_supplier_profile_averages':p,'gates':r['gates']})
    expected={(e['event_id'],org) for e in events if e['event_type'] in {'supplier_selected','construction_progress_updated','supply_delay'}
        for p in simulation['project_results'] if p['project_id']==e['project_id'] for org in p['selected_supplier_ids']}
    require({(r['event_id'],r['organization_id']) for r in records}==expected,
        'Actual selected Supplier source observation missing or leaked to unselected institution')
    progress=[r for r in proofs if r['event_type']=='construction_progress_updated']
    require({r['project_id'] for r in progress}=={p['project_id'] for p in simulation['project_results']},
        'A selected project never produced an actual construction-period supply update')
    require(before==hashlib.sha256(database.read_bytes()).hexdigest(),'Read-only source check modified journal')
    return {'status':'native_observations_verified_detailed_fulfillment_blocked','native_ticks':4,
        'technical_tasks':len(tasks),'original_prefix_micro_actions':dict(Counter(t['identity']['action_id'] for t in tasks if t['identity']['purpose']=='action')),
        'detailed_supplier_fulfillment_actions':0,'actual_observations':proofs,'observed_event_counts':dict(Counter(r['event_type'] for r in records)),
        'native_event_counts':dict(Counter(e['event_type'] for e in events)),
        'original_final_stages':{p['project_id']:p['current_stage'] for p in simulation['project_results']},
        'native_validation_diagnostics':[e for e in events if e['event_type']=='invalid_action'],
        'gates':{a:'blocked_missing_verified_native_sources' for a in GATES},'journal_sha256':before,'read_only':True}


def source_boundaries():
    from integration.contractor_construction_source_review import _source
    from integration.supplier_fulfillment_source_review import _ACTIONS,_REUSE
    macro=ROOT/macro_hashes()['root']/'gba_construction_sim/backend'
    native=[_source(macro,'simulation/project_state_update_engine.py','ProjectStateUpdateEngine.'+n)
        for n in ('update_supply_state','record_construction_process_events')]
    native += [_source(macro,'simulation/project_lifecycle_engine.py','ProjectLifecycleEngine._select_supplier_after_contract')]
    for row in native:row['path']=(macro/row['path']).relative_to(ROOT).as_posix()
    stages={}
    for action,gate in GATES.items():
        module,symbol,_=_ACTIONS[action]
        stages[action]={'status':'blocked_missing_verified_native_sources',**gate,
            'existing_processor':_source(ROOT,'src/actions/roles/'+module+'.py',symbol),
            'existing_components':[_source(ROOT,path,name) for path,name in _REUSE[action]],
            'micro_invocations':0,'boundary':'Existing component/schema or fixture factory is not a verified equivalent native source/issuer. Aggregate state is not detailed order, release, batch, inspection, shipment or receipt.'}
    return {'batch':'3F','native_producers':native,'stages':stages,
        'coverage':'Own actual normalized source observations only; all five detailed stages remain blocked.',
        'next_step':'Locate independently equivalent original detailed issuer/query and authorized exact source versions, then reuse existing typed assembler/worker/handoff. Do not synthesize an OrderFormationRecord or core_event_id from a supply event.'}


def write_delivery(directory,checks):
    lines=['# GOAL 3F 供应履约来源与等待记录','',
        '**五段详细微观履约均未接通。** 本批交付真实汇总供应状态接收、来源检查和明确等待；不把观察器或绿色检查当作履约完成。','',
        '| 场景 | 原宏观时点 | 实际来源观察 | 详细 A05—A09 执行 |',
        '| --- | --- | --- | --- |']
    for name,s in checks['scenarios'].items():
        lines.append(f"| {name} | {s['native_ticks']} | {len(s['actual_observations'])} | 0，缺真实详细来源/接口 |")
    lines += ['',f"原宏观供应风险最大值：reliable={checks['profile_effect']['reliable_max_risk']}；low_reliability={checks['profile_effect']['low_reliability_max_risk']}。这验证原宏观计算，未证明详细微观决策消费。",
        '低质量场景首项目在时点 4 被原宏观安全/质量门槛暂停，故施工期来源观察次数不同；检查逐个核对实际项目/事件，不要求两个场景固定产生相同事件数量。两场景均未实际触发 supply_delay，此观察分支仍待实际事件联调。',
        '原生 invalid_action 本地校验诊断保存在 runtime/result.json 及 checks.json，没有屏蔽或算作成功动作；观察器错误均为零。']
    lines+=['','新目录运行：','```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_supply_fulfillment `",
        '  --config config/supply_fulfillment.json `','  --output output/integration/goal3f_my_run','```','',
        '只读核对：','```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_supply_fulfillment --check-only --output '{directory.as_posix()}'",'```','',
        '两组差异通过原宏观初始 Supplier reliability/quality 配置与时窗构造，未改运行状态。原 update_supply_state 实算 normalized material_quality/supply_delay_risk；原实际事件触发本机构来源观察，原宏观继续维护状态。',
        '实际观察按原全局/项目事件、当前已选供应商和 ACTIVE engagement 核对，限定三个汇总供应字段；不是细粒度微观输入或完成结果。每个观察保存原事件/状态摘要与五段来源缺口，micro_identity 均为空。',
        'input/ 与 source-config.json 保存独立初始输入，runtime/ 保存原进程结果、观察和任务库；checks.json 为只读来源对应关系；source-boundaries.json 定位原生产者、原微观处理器及缺失资料。',
        f"宏观 {checks['macro']['file_count']} 文件基线及全部宏观 Python 源码未变。五段详细履约仍为 blocked_missing_verified_native_sources，GOAL 3 与原 PLAN 均未完成。",'']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines),encoding='utf-8')
    names=['integration/supply_fulfillment_native.py','integration/verify_supply_fulfillment.py',
        'config/supply_fulfillment.json','config/gba_v1_business_wiring.json',
        'docs/供应履约接线与来源等待.md','docs/宏观动作接线清单.md',
        'integration/supplier_fulfillment_source_review.py','integration/supplier_order_native.py',
        'integration/supplier_order_native_development.py']
    files={p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'}
    _write(directory,'artifact-manifest.json',{'schema_version':'supply-fulfillment-source-artifacts.v1','files':files,
        'implementations':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,default=ROOT/'config/supply_fulfillment.json')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--check-only',action='store_true');args=p.parse_args(argv)
    directory=args.output.resolve()
    if not args.check_only:
        config=read(args.config);validate_config(config);directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
        for name,profile in config['scenarios'].items():
            run_scenario(directory/name,run_id=config['run_id']+'-'+name,profile=profile,ticks=config['ticks'])
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    config=read(directory/'source-config.json');validate_config(config)
    scenarios={name:verify_scenario(directory/name) for name in config['scenarios']}
    risk=lambda name:max(r['native_state']['supply_delay_risk'] for r in scenarios[name]['actual_observations']
        if r['event_type']=='construction_progress_updated')
    require(risk('reliable')<risk('low_reliability'),'Original profile difference did not enter native supply calculation')
    checks={'batch':'3F','status':'native_observations_verified_all_detailed_stages_blocked','scenarios':scenarios,
        'profile_effect':{'reliable_max_risk':risk('reliable'),'low_reliability_max_risk':risk('low_reliability'),
            'micro_decision_influence_claimed':False},'macro':macro_hashes(),'overall_goal3_complete':False}
    require(read(directory/'macro-before.json')==checks['macro'],'Frozen macro sources changed')
    if not args.check_only:
        _write(directory,'checks.json',checks);_write(directory,'source-boundaries.json',source_boundaries());write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'output':str(directory),'macro_unchanged_files':checks['macro']['file_count']}))


if __name__=='__main__':main()
