"""Fixed original Supplier A01-A04 / Contractor A05 and actual signed handoff."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from integration.contractor_tender_development import _write, _write_launch_files, verify_bundle
from integration.verify_tender_closed_loop import ROOT, read, require, one, digest_valid, macro_hashes
from src.coordination.tasks import TaskIdentity, task_digest


def build_inputs(directory, *, run_id, options):
    if options['mode']=='supply':
        from integration.supplier_order_native_development import build_bundle
        actors={org:org+'-execution-actor' for org in ('supply-owner','supply-contractor','supply-a','supply-b')}
        build_bundle(directory,run_id=run_id,with_quote=True,with_product=True,with_screening=True,
            with_contractor=True,first_decline_stage=options['first_decline_stage'],
            decline_after_prior_declines=1 if options['first_decline_stage'] else None,
            organization_actor_ids=actors)
        return 'integration.supplier_order_native:configure_assembly'
    from integration.tender_fulfillment_development import build_bundle
    directory.mkdir(parents=True,exist_ok=False)
    foundation=directory/'foundation'
    build_bundle(foundation,run_id=run_id,with_owner_award=True)
    request=read(foundation/'macro-request.json')
    # Supported native SimulationCreateRequest input, authored before sealing.
    # Retain all declared future sources, stop after actual tick-9 selection.
    request['ticks']=options['ticks']
    _write(directory,'macro-request.json',request)
    for name in ('native-host.json','assembly-host.json'):
        _write(directory,name,read(foundation/name))
    _write(directory,'initial-window.json',{'source':'foundation/macro-request.json',
        'ticks':options['ticks'],'boundary':'Initial observation window only; no runtime state or decision changed. Future payment plans remain declared but outside this 3E run.'})
    hook='integration.contractor_tender_formation_development:configure_assembly'
    _write_launch_files(directory,assembly_hook=hook,readme_override=__doc__)
    return hook


def run_scenario(directory, *, run_id, options):
    hook=build_inputs(directory/'input',run_id=run_id,options=options)
    verify_bundle(directory/'input')
    args=[sys.executable,'-m','integration.run','--input',str(directory/'input/macro-request.json'),
        '--output',str(directory/'runtime'),'--offline','--input-format','gba_request','--macro-mode','gba_v1_module',
        '--agent-client-factory','integration.native_routes:build_agent_client',
        '--agent-client-config',str(directory/'input/native-host.json'),
        '--module-assembly-hook',hook,'--module-assembly-config',str(directory/'input/assembly-host.json')]
    _write(directory,'command.json',args)
    with (directory/'stdout.log').open('xb') as stdout,(directory/'stderr.log').open('xb') as stderr:
        completed=subprocess.run(args,cwd=ROOT,stdout=stdout,stderr=stderr)
    _write(directory,'exit.json',{'exit_code':completed.returncode})
    require(completed.returncode==0,'Original native procurement run failed; inspect saved stderr and journal')


def validate_config(config):
    require(config['schema_version']=='procurement-chain-acceptance.v1' and config['scenarios']=={
        'accepted_feedback':dict(mode='supply',first_decline_stage=None),
        'quote_refusal_feedback':dict(mode='supply',first_decline_stage='quote'),
        'signed_handoff':dict(mode='actual_tender',ticks=9)},'Unsupported fixed procurement scenarios')


def verify_scenario(directory, *, name):
    """Correlate original input/actions/transport/events/consumers without replay."""
    for manifest in (directory/'input').rglob('input-manifest.json'):
        verify_bundle(manifest.parent)
    require(read(directory/'exit.json')['exit_code']==0,'Native procurement process failed')
    output=read(directory/'runtime/result.json');simulation=output['simulation']
    require(simulation['status']=='completed' and simulation['current_tick']==(9 if name=='signed_handoff' else 2),
        'Native procurement window incomplete')
    host=output['module_host_extension']['host']
    if 'supplier' in host:host=host['supplier']
    initial=read(directory/'input/macro-request.json')
    require(all(not p['event_log'] and not p['selected_supplier_ids'] for p in initial['initial_projects']),
        'Actual supply results prefilled')
    events=[e for p in simulation['project_results'] for e in p['event_log']]
    inbox=read(directory/'runtime/observations.json')['records']
    require(not any(e['data'].get('agent_observer_errors') for e in events),'Procurement observer failed')
    roles={a['agent_id']:a['role'] for a in initial['agents']}
    database=directory/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')}
        workers=[json.loads(v) for table in ('supplier_screening_results','supplier_product_results',
            'supplier_quote_results','supplier_order_results','contractor_planning_results')
            for v, in db.execute('SELECT record FROM '+table)]
    task_map={TaskIdentity(**t['identity']).key:t for t in tasks}
    saved={TaskIdentity(**r['identity']).key:r for r in workers}
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),
        'Unresolved or altered original technical task')
    for r in workers:
        digest_valid(r)
        require(r['result']['kind']=='completed' and task_digest(r['result'])==r['result_sha256']
            and task_digest(r['source_reading'])==r['source_reading_sha256']
            and task_map[TaskIdentity(**r['identity']).key]['output']==r['result'],
            'Original worker/task/source binding lost')
    suppliers=[v for k,v in metadata.items() if k.startswith('supplier_order_native_request:')]
    contractors=[v for k,v in metadata.items() if k.startswith('contractor_supply_native_request:')]
    require((len(suppliers),len(contractors))==((2,1) if name=='signed_handoff' else (4,2)),
        'Actual procurement contacts missing')
    for exported,records in ((host['requests'],suppliers),(host['contractor']['requests'],contractors)):
        require({r['key']:r for r in exported}=={r['key']:r for r in records},'CLI and durable procurement export differ')

    def event(event_id):
        return one(events,lambda e:e['event_id']==event_id,'Missing actual original project event')

    def bound(record,observed):
        require(any(s['ref']['kind']=='Evidence' and s['projection'].get('content_hash')==task_digest(observed)
            for s in record['source_reading']),'Original micro reading did not bind this actual input/history')

    def receive(e):
        from integration.bootstrap import enable_gba_imports
        enable_gba_imports()
        from gba_construction_sim.backend.agents.contracts import AgentObservationV1
        from integration.supplier_order_native_feedback import project_supply_event
        expected=project_supply_event(AgentObservationV1.model_validate(e),roles)
        actual={r['organization_id']:r['payload'] for r in inbox if r['event_id']==e['event_id']}
        require(actual==expected,'Actual supply feedback lost its original private projection/recipients')

    def transport(row,operation,decision):
        org=row['native_request']['agent']['agent_id'];scope=row['scope']
        proposal=one(tasks,lambda t:t['identity']['organization_id']==org and t['identity']['purpose']=='propose'
            and t['identity']['action_id']==operation and t['output'].get('factors',{}).get('native_supply_scope')==scope,
            'Missing original procurement proposal')['output']
        final=one(tasks,lambda t:t['identity']['organization_id']==org and t['identity']['purpose']=='decide'
            and t['identity']['action_id']==decision and t['output'].get('data',{}).get('native_supply_scope')==scope,
            'Missing original procurement confirmation')['output']
        require(task_digest(proposal)==row['proposal_response_sha256']==final['data']['proposal_response_sha256']
            and proposal['accepted']==final['decision'] and proposal['action_type']==final['action_type'],
            'Final procurement confirmation changed original proposal')
        key=TaskIdentity(**row['identity']).key
        for value in (proposal['factors'],final['data']):
            require(value['micro_task_key']==key and value['micro_result_sha256']==row['result_sha256'],
                'Transport substituted original deciding micro result')
        return proposal,final

    def history(prior,*,org,tick,contractor=False):
        e=event(prior['event_id']);receive(e)
        require(e['tick']==prior['tick']<tick and e['project_id']==prior['project_id'],
            'Feedback borrowed future or different-project outcome')
        r=saved[prior['micro_task_key']]
        require(r['identity']['organization_id']==org and r['result_sha256']==prior['micro_result_sha256'],
            'History borrowed another institution micro result')
        records=contractors if contractor else suppliers
        original=one(records,lambda row:TaskIdentity(**row['identity']).key==prior['micro_task_key'],
            'Feedback lost original native request')
        require(original['scope']['tick']==prior['tick'] and original['scope']['project_id']==prior['project_id']
            and original['proposal_response_sha256']==prior['proposal_response_sha256'],
            'Feedback changed original source request/proposal')
        data=e['data']['contractor_decision'] if contractor else e['data']
        if not contractor and e['event_type']=='supplier_selected':
            accepted=event(prior['acceptance_event_id']);receive(accepted);data=accepted['data']
            require(e['data']['supplier_id']==org and accepted['agent_id']==org,'Supplier history borrowed a peer selection')
        require(data['micro_task_key']==prior['micro_task_key']
            and data['micro_result_sha256']==prior['micro_result_sha256'],
            'Feedback did not consume the exact actual execution')
        return {'event_id':e['event_id'],'event_sha256':task_digest(e),
            'micro_task_key':prior['micro_task_key'],'micro_result_sha256':prior['micro_result_sha256']}

    def signed_handoff(observed,*,org,scope):
        if name!='signed_handoff':return None
        h=observed['native_signed_contract'];e=event(h['event_id'])
        project=one(simulation['project_results'],lambda p:p['project_id']==scope['project_id'],'Signed project missing')
        contract=one(project['contracts'],lambda c:c['contractor_id']==scope['contractor_id'],'Actual signed contract missing')
        require(h['source']=='actual_earlier_native_contract_awarded' and e['event_type']=='contract_awarded'
            and h['source_event_sha256']==task_digest(e) and h['contract_sha256']==task_digest(contract)
            and h['receiving_organization_id']==org and h['read_tick']==scope['tick']>h['signed_tick']==e['tick']
            and h['project_id']==scope['project_id'] and h['contractor_id']==scope['contractor_id'],
            'Current A03/A04/A05 did not consume the same actual earlier signature')
        return h

    supplier_proofs=[]
    for row in suppliers:
        digest_valid(row);scope=row['scope'];org=row['native_request']['agent']['agent_id']
        key=TaskIdentity(**row['identity']).key;r=saved[key];stage=row['terminal_stage']
        accepted=stage=='order';expected_stage='order'
        if name=='quote_refusal_feedback' and org=='supply-a':
            expected_stage='quote' if scope['tick']==1 else 'screening'
        require(row['state']=='formed' and stage==expected_stage and row['result_sha256']==r['result_sha256']
            and row['observed']['native_request_sha256']==task_digest(row['native_request']),
            'Original supply request or terminal stage changed')
        require(r['result']['payload']['choice']==('accept' if accepted else ('decline_quote' if stage=='quote' else 'decline')),
            'Original supply willingness differs from computed micro result')
        expected_steps={'screening'} if stage=='screening' else {'screening','product','quote'}
        require({s for s in ('screening','product','quote') if s in row}==expected_steps,
            'Required original upstream micro stage missing')
        bound(r,row['observed'])
        stage_proofs=[]
        for current,previous in (('screening',None),('product','screening'),('quote','product'),('order','quote')):
            if current!='order' and current not in row:continue
            if current=='order' and not accepted:continue
            step=row if current=='order' else row[current]
            action=saved[TaskIdentity(**step['identity']).key];bound(action,step['observed'])
            expected_action={'screening':'SUPPLIER-A01','product':'SUPPLIER-A02','quote':'SUPPLIER-A03','order':'SUPPLIER-A04'}[current]
            require(step['result_sha256']==action['result_sha256'] and action['identity']['action_id']==expected_action,
                'Original stage action/result changed')
            handoff=step['observed'].get(previous) if previous else None
            if handoff:
                original=saved[TaskIdentity(**handoff['identity']).key]
                require(handoff['result_sha256']==original['result_sha256']
                    and handoff['record_sha256']==original['record_sha256']
                    and handoff['source_reading_sha256']==original['source_reading_sha256'],
                    'Current stage substituted actual original predecessor')
                # The full observed input, already bound above, includes this
                # exact handoff. Its typed basis has additional derived hashes;
                # do not require a second Evidence hash of the returned wrapper.
            if current=='quote' and accepted:
                price=action['result']['payload']['offer']['lines'][0]['price']
                expected_price='20' if name=='signed_handoff' else '200'
                require(len(action['audit']['method_calls'])==2 and action['result']['payload']['choice']=='quote',
                    'Original quote did not execute pricing/capacity methods')
                pricing=one(action['audit']['method_calls'],lambda m:m['result']['method_ref']['id']=='micro.supply.declared_cost_markup',
                    'Missing actual original pricing method')['result']['value']
                require(price['currency']=='HKD' and price['value']==pricing['rounded_price']==expected_price,
                    'Quoted price differs from actual original method calculation')
            if current=='order':
                quote=saved[TaskIdentity(**row['quote']['identity']).key]
                require(action['result']['payload']['accepted_lines']==quote['result']['payload']['offer']['lines'],
                    'A04 substituted the exact original quoted delivery/product/price lines')
            stage_proofs.append({'stage':current,'identity':action['identity'],'result_sha256':action['result_sha256'],
                'choice':action['result']['payload']['choice'],'method_calls':len(action['audit']['method_calls']),
                'quoted_offer':action['result']['payload'].get('offer') if current=='quote' else None,
                'signed_handoff':signed_handoff(step['observed'],org=org,scope=scope)})
        proposal,final=transport(row,'consider_supply_order','supplier_order_acceptance')
        e=one(events,lambda e:e['event_type']=='supplier_order_decision' and e['agent_id']==org
            and e['project_id']==scope['project_id'] and e['tick']==scope['tick'],'Missing actual supply willingness execution')
        require(e['data']['accepted']==proposal['accepted']==accepted and e['data']['micro_task_key']==key
            and e['data']['micro_result_sha256']==r['result_sha256']
            and e['data']['proposal_response_sha256']==task_digest(proposal),'Actual supply decision changed original micro output')
        receive(e)
        decisions=[history(h,org=org,tick=scope['tick']) for h in row['observed']['prior_supply_decisions']]
        selections=[history(h,org=org,tick=scope['tick']) for h in row['observed']['prior_supply_selections']]
        policy=row['screening']['observed'].get('screening_decline_feedback')
        if name=='quote_refusal_feedback' and org=='supply-a' and scope['tick']==2:
            effective=one(saved[TaskIdentity(**row['screening']['identity']).key]['source_reading'],
                lambda s:s['ref']['kind']=='SupplyScreeningProfile','Missing original A01 policy source')['projection']['policy']
            require(policy['actual_decline_count']==policy['threshold']==1
                and policy['baseline_policy']=='evaluate' and policy['effective_policy']==effective=='decline_new_work',
                'Earlier actual quote refusal did not constrain later original screening')
        supplier_proofs.append({'scope':scope,'organization_id':org,'terminal_identity':r['identity'],
            'terminal_result_sha256':r['result_sha256'],'stages':stage_proofs,'accepted':accepted,
            'actual_event':e,'consumed_decisions':decisions,'consumed_selections':selections,'screening_feedback':policy})

    contractor_proofs=[]
    for row in contractors:
        digest_valid(row);scope=row['scope'];org=row['native_request']['agent']['agent_id']
        r=saved[TaskIdentity(**row['identity']).key];o=row['observed'];bound(r,o)
        require(row['state']=='formed' and r['result']['payload']['choice']=='accept_supply_offer'
            and row['result_sha256']==r['result_sha256'] and o['native_request_sha256']==task_digest(row['native_request']),
            'Original A05 request/result changed')
        proposal,final=transport(row,'select_supplier','contractor_supplier_selection')
        offered={p['agent_id'] for p,d in row['native_request']['inputs']['offers'] if d['accepted']}
        actual_offers={r['organization_id']:r['accepted'] for r in supplier_proofs if r['scope']==scope}
        require({p['agent_id']:d['accepted'] for p,d in row['native_request']['inputs']['offers']}==actual_offers,
            'A05 native candidate list differs from actually executed Supplier decisions')
        selected=o['selected_supplier_id'];eligible=o['eligible_preferences']
        require({p['supplier_id'] for p in eligible}==offered and selected in offered
            and selected==min(eligible,key=lambda p:(p['priority'],p['base_priority']))['supplier_id']
            and proposal['data']['selected_supplier_id']==final['data']['selected_supplier_id']==selected,
            'A05 lost actual accepted macro candidates or its declared comparison')
        prior=[history(h,org=org,tick=scope['tick'],contractor=True) for h in o['prior_selections']]
        for p in eligible:
            count=sum(h['supplier_id']==p['supplier_id'] for h in o['prior_selections'])
            require(p['priority']==p['base_priority']+o['repeat_supplier_priority_penalty']*count,
                'Actual previous selection did not enter A05 preference calculation')
        origin=o['origin']
        for stage in ('A03','A04'):
            require(saved[origin[stage+'_task_key']]['result_sha256']==origin[stage+'_result_sha256'],
                'A05 did not consume the actual selected Supplier result')
        actual_supplier=one(suppliers,lambda s:s['scope']==scope
            and s['native_request']['agent']['agent_id']==selected,'Selected actual Supplier request missing')
        require(TaskIdentity(**actual_supplier['identity']).key==origin['A04_task_key']
            and TaskIdentity(**actual_supplier['quote']['identity']).key==origin['A03_task_key'],
            'A05 borrowed a quote/acceptance from another project or time')
        offer=one(r['source_reading'],lambda s:s['ref']==r['result']['payload']['offer_ref'],
            'A05 did not read its selected original commercial offer')['projection']
        quoted=saved[origin['A03_task_key']]['result']['payload']['offer']['lines']
        require(offer['supplier_id']==selected and [v['batch_price'] for v in offer['lines']]==[v['price'] for v in quoted],
            'A05 commercial view changed exact original Supplier batch prices')
        require(not {'InventorySnapshot','FundingPosition','SupplierCapacity','SupplyPricingProfile','CostBasis',
            'SupplyFormationProfile','SupplyScreeningProfile'} & {s['ref']['kind'] for s in r['source_reading']},
            'A05 received Supplier private cost/stock/strategy')
        e=one(events,lambda e:e['event_type']=='supplier_selected' and e['project_id']==scope['project_id']
            and e['tick']==scope['tick'],'Missing actual native supplier selection')
        require(e['data']['supplier_id']==selected and e['data']['contractor_decision']['micro_result_sha256']==r['result_sha256']
            and e['data']['contractor_decision']['proposal_response_sha256']==task_digest(proposal),
            'Native execution changed original A05 selection')
        receive(e)
        project=one(simulation['project_results'],lambda p:p['project_id']==scope['project_id'],'Selected project missing')
        engagement=one(project['engagements'],lambda g:g['role']=='Supplier' and g['agent_id']==selected
            and g['status']=='active','Actual selected Supplier engagement missing')
        require(project['selected_supplier_ids']==[selected] and project['flags']['supplier_selected'] is True
            and project['current_stage'] in ('contract_award','construction'),
            'Native selected state differs from executed A05')
        contractor_proofs.append({'scope':scope,'identity':r['identity'],'result_sha256':r['result_sha256'],
            'actual_accepted_supplier_ids':sorted(offered),'selected_supplier_id':selected,'eligible_preferences':eligible,
            'supplier_handoff':origin,'consumed_selections':prior,'actual_event':e,
            'signed_handoff':signed_handoff(o,org=org,scope=scope),'actual_supplier_engagement':engagement,
            'final_project_stage':project['current_stage'],'mobilization_completed':project['flags'].get('mobilization_completed',False)})
    ordered=sorted(contractor_proofs,key=lambda r:r['scope']['tick'])
    expected=['actual-supplier-a'] if name=='signed_handoff' else (['supply-a','supply-b'] if name=='accepted_feedback' else ['supply-b','supply-b'])
    require([r['selected_supplier_id'] for r in ordered]==expected,'Unexpected actual selected Suppliers')
    if name=='signed_handoff':
        require(all(not p['contracts'] and not p['bids'] and not p['selected_contractor_id'] for p in initial['initial_projects']),
            'Actual tender signature was prefilled')
        require(not any(e['event_type'].startswith('payment_') for e in events),'3E window entered later payment business')
    require(len(workers)=={'accepted_feedback':18,'quote_refusal_feedback':14,'signed_handoff':9}[name],
        'Original procurement action count differs from the executed fixed chain')
    require(before==hashlib.sha256(database.read_bytes()).hexdigest(),'Read-only verification modified journal')
    return {'status':'passed','native_ticks':simulation['current_tick'],'technical_tasks':len(tasks),
        'original_procurement_actions':dict(Counter(r['identity']['action_id'] for r in workers)),
        'suppliers':supplier_proofs,'contractors':contractor_proofs,'read_only':True,'journal_sha256':before,
        'boundary':'Actual normalized supply willingness/selection and private commercial acceptance; not detailed registered orders, stock reservation, factory execution, deliveries or payments.'}


def review_remaining_sources():
    """Pin actual native producer and retained detailed handoffs, not coverage."""
    from integration.contractor_construction_source_review import _source
    macro=ROOT/macro_hashes()['root']/'gba_construction_sim/backend'
    producers=[_source(macro,'simulation/project_lifecycle_engine.py','ProjectLifecycleEngine.'+name)
        for name in ('_handle_contract_award','_select_supplier_after_contract')]
    producers += [_source(macro,'simulation/engagement_manager.py','EngagementManager.create_engagement'),
        _source(macro,'agents/supplier_agent.py','SupplierAgent.decide_monthly_operation'),
        _source(macro,'agents/contractor_agent.py','ContractorAgent.decide_monthly_operation')]
    for row in producers:row['path']=(macro/row['path']).relative_to(ROOT).as_posix()
    existing=[_source(ROOT,'integration/native_contract_supply.py','signed_contract_for_supply'),
        _source(ROOT,'integration/supplier_order_handoff.py','prepare_supplier_order_handoff'),
        _source(ROOT,'integration/supplier_order_results.py','SupplierOrderResultWorker.prepare_planning_handoff'),
        _source(ROOT,'integration/supplier_submission.py','SupplierResultSubmission.execute'),
        _source(ROOT,'integration/contractor_supply_native.py','ContractorSupplyNativeApplication._sources'),
        _source(ROOT,'integration/qs_procurement_actions.py','QSProcurementActionAssembler.build')]
    return {'batch':'3E','status':'reviewed_source_boundaries_not_runtime_coverage',
        'native_producers':producers,'existing_processors_and_handoffs':existing,
        'remaining_handoffs':[
            {'business':'Formal detailed supply order/contract and exclusive reservations',
             'status':'blocked_missing_verified_equivalent_native_formation_issuer',
             'reason':'Native supplier_order_decision/supplier_selected and normalized ACTIVE engagement are real. They do not issue Order/OrderLine, SupplierOrderFormationRecord, detailed supplier contract or exclusive stock/cash/capacity reservations. Existing SupplierResultSubmission callbacks and original A04->A05 prepare_supplier_order_handoff require authentic equivalent issuer/query and exact formation evidence before downstream planning.',
             'next_step':'Bind original effective Order and OrderLine versions, agreement digest, actual core event and current work authority; reuse existing handoff. Do not fabricate formation from selection. Supply execution continues in 3F.'},
            {'business':'No accepted suppliers / partial acceptance / revised or unresolved terms',
             'status':'blocked_outside_current_native_supply_summary',
             'reason':'Current original willingness bridge supports complete accept/reject or complete-demand upstream decline; partial/revise/needs_information remain unresolved. A05 currently stops when no accepted authorized Supplier remains. Native supplier_selection_failed has no verified current micro feedback consumer on that path; do not force success or use native fallback.',
             'next_step':'Establish semantically equivalent original final disposition and authorized failure consumer before enabling this path. Full 438-branch expansion is not claimed.'},
            {'business':'Procurement-related monthly enterprise decisions',
             'status':'blocked_for_micro_monthly_business_judgment',
             'reason':'Native Supplier seek_supply_contract/monitor_material_prices/adjust_inventory and Contractor maintain_supplier_relationship remain original native decisions. This batch does not map an opportunity, quotation revision, stock change or relationship action solely from a monthly label or random capability update. Other monthly sub-actions remain allocated to 3F/3I.',
             'next_step':'Bind authorized actual opportunity/price/inventory/relationship sources and original role-specific judgment/effect consumers. Keep these monthly actions explicitly open.'}],
        'qs_boundary':'Native select_supplier has no separate QS preparation call. Existing original QS-A05 needs authentic design/measurement/quantity/publication authority and actual downstream demand; current supplier technical/commercial sources are explicit independent scenario assumptions. Do not create internal QS work merely to increase action counts.',
        'units_boundary':'Native normalized resource and contract_sum_unit are not physical factory/delivery units or HKD. Physical quantity, factory cost, cash, capacity, price and procurement limit below are independently declared synthetic inputs, not conversions.'}


def write_delivery(directory,checks):
    lines=['# GOAL 3E 采购选供接单运行记录','',
        '复用原 Supplier A01→A02→A03→A04、Contractor A05 和原生执行链。宏观源码冻结；GOAL 3 整体未完成。','',
        '| 场景 | 宏观时点 | 采购微观动作 | 全部技术任务 | 实际选择 |',
        '| --- | --- | --- | --- | --- |']
    for name,s in checks['scenarios'].items():
        selected=', '.join(r['selected_supplier_id'] for r in sorted(s['contractors'],key=lambda r:r['scope']['tick']))
        lines.append(f"| {name} | {s['native_ticks']} | {sum(s['original_procurement_actions'].values())} | {s['technical_tasks']} | {selected} |")
    lines+=['','accepted_feedback：原实际选供进入后轮 A05，A 的偏好分由 0 + 2×1 = 2，B 为 1，原 A05 选择 B。两个 Supplier 仍真实接受，没有预填承包商选择。',
        'quote_refusal_feedback：A 在第一轮实际 A03 decline_quote，原宏观记录拒单；后轮 A01 读取同一实际拒单，将 evaluate 变为 decline_new_work。原宏观候选约束使 A05 只能选择实际接受的 B。','',
        '真实签约交接：','']
    for row in checks['scenarios']['signed_handoff']['contractors']:
        h=row['signed_handoff'];e=row['actual_event']
        lines.append(f"- 同项目 {h['project_id']}：tick {h['signed_tick']} {h['event_id']} contract_awarded → tick {h['read_tick']} Supplier A01/A02/A03/A04 和 Contractor A05 → {e['event_id']} supplier_selected。合同和事件摘要见 checks.json。")
    lines+=['','新目录运行：','```powershell',
        "& '.venv-integration/Scripts/python.exe' -m integration.verify_procurement_chain `",
        '  --config config/procurement_chain.json `','  --output output/integration/goal3e_my_run','```','',
        '只读核对：','```powershell',
        f"& '.venv-integration/Scripts/python.exe' -m integration.verify_procurement_chain --check-only --output '{directory.as_posix()}'",'```','',
        'source-config.json 和 input/ 为运行前输入；command.json、stdout/stderr 与 runtime/ 为原进程、原结果、任务库和观察。checks.json 保存输入/原微观身份与结果/原执行/后轮消费的对应关系。source-boundaries.json 只定位剩余接线，不作为运行成功证据。',
        f"宏观 {checks['macro']['file_count']} 个基线文件和全部宏观 Python 源码哈希未变；只读核对不修改原任务库。",'',
        '前两个短窗口有明确初始合同/商议状态假设；不得据此宣称本次完成完整招标签约。signed_handoff 单独从无投标、无中标、无合同的招标阶段真实执行至 tick 9；未来付款计划虽预先声明，窗口未执行付款。',
        '原宏观选供当轮返回，后轮才动员并进入施工。短窗口首项目已在施工，后续项目及 signed_handoff 在窗口结束时仍为 contract_award；不把选供成功当作已完成动员。',
        '报价、物理容量、库存/现金快照、独立买方同意和采购权限均为明确合成假设；原 A03 实算并核对 A04/A05 同一价格/产品/服务。native contract_sum 无货币单位，不换算成 HKD 或物理容量。',
        '实际 normalized engagement 不是详细 Order/OrderLine、正式供货合同、库存预留、付款或交货回执。正式成单/资源转换、未决供货结果及采购相关月度微观判断仍阻塞，3F 另行启动。','']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines),encoding='utf-8')
    files={p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'}
    names=['config/procurement_chain.json','config/gba_v1_business_wiring.json',
        'docs/采购选供接单接线与验收.md','docs/宏观动作接线清单.md','integration/verify_procurement_chain.py',
        'integration/supplier_order_native_development.py','integration/contractor_supply_native_development.py',
        'integration/tender_fulfillment_development.py','integration/supplier_order_native.py',
        'integration/supplier_order_native_scope.py','integration/supplier_order_native_screening.py',
        'integration/supplier_order_native_product.py','integration/supplier_order_native_quote.py',
        'integration/supplier_screening_decline_feedback.py','integration/supplier_order_native_feedback.py',
        'integration/contractor_supply_native.py','integration/contractor_supply_native_sources.py',
        'integration/contractor_supply_native_feedback.py','integration/native_contract_supply.py',
        'integration/supply_native_outcome_query.py','integration/native_routes.py']
    _write(directory,'artifact-manifest.json',{'schema_version':'procurement-chain-artifacts.v1','files':files,
        'implementations':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'config/procurement_chain.json')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args(argv);directory=args.output.resolve()
    if not args.check_only:
        config=read(args.config);validate_config(config)
        directory.mkdir(parents=True,exist_ok=False)
        _write(directory,'macro-before.json',macro_hashes());_write(directory,'source-config.json',config)
        for name,options in config['scenarios'].items():
            run_scenario(directory/name,run_id=config['run_id']+'-'+name,options=options)
    elif (directory/'artifact-manifest.json').is_file():
        from integration.verify_tender_basic import verify_history
        verify_history(directory)
    config=read(directory/'source-config.json');validate_config(config)
    checks={'batch':'3E','status':'passed_for_bounded_native_procurement_chain',
        'scenarios':{name:verify_scenario(directory/name,name=name) for name in config['scenarios']},
        'macro':macro_hashes(),'overall_goal3_complete':False}
    require(read(directory/'macro-before.json')==checks['macro'],'Frozen macro sources changed')
    if not args.check_only:
        _write(directory,'checks.json',checks);_write(directory,'source-boundaries.json',review_remaining_sources())
        write_delivery(directory,checks)
    print(json.dumps({'status':checks['status'],'output':str(directory),'macro_unchanged_files':checks['macro']['file_count']}))


if __name__=='__main__':
    main()
