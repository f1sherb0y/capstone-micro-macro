"""Zero-network preflight for24-project expansion, not simulated model answers."""
import asyncio
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from prepare_capstone_expansion_20261109 import OUT,CAP,PREVIOUS,REPAIR,read,save,sha
from run_capstone_expansion_20261109 import verify_frozen,evaluate,run
from run_capstone_core_validation_20261108 import NoProviderNetwork
from tests.test_bid_document_stage import BidLLM
from src.company_grounding import company_evidence
from src.coordination.tasks import TaskStore
from src.coordination.model_budget import ModelCallBudget


def main():
    assert not (OUT/'run').exists() and not (OUT/'authorization.json').exists()
    protocol=verify_frozen();windows=read(OUT/'windows.json');manifest=read(OUT/'sample_manifest.json')
    assert len(manifest)==24 and len(windows)==48 and len(protocol['jobs'])==192
    assert len({m['project_group'] for m in manifest})==24 and len({m['company_id'] for m in manifest})==24
    assert set(Counter(m['role'] for m in manifest).values())=={6}
    assert not {m['project_group'] for m in manifest}&set(protocol['excluded_process_groups'])
    fixture_bid=json.loads(asyncio.run(BidLLM().achat([{}, {'content':'BID_DOCUMENT'}])))
    guard=NoProviderNetwork();constructors=[];probes=[]
    def deny(*args,**kwargs):constructors.append(True);raise AssertionError('Do not construct a paid client in preflight')
    with patch.object(socket.socket,'connect',guard.block),patch.object(socket.socket,'connect_ex',guard.block),patch('src.llm_client.OpenAICompatibleClient.from_env',side_effect=deny):
        for old_cap in (None,0,1,24,40,80,96):
            try:run(old_cap)
            except ValueError:pass
            else:raise AssertionError('Missing/historical authorization accepted')
        for wid,w in windows.items():
            left,right=w['messages']['v2_4'],w['messages']['v2_5']
            assert left[0]==right[0]
            assert left[-1]['content'].split('Evidence and decision conditions:')[0]==right[-1]['content'].split('Evidence and decision conditions:')[0]
            for messages in (left,right):
                records,_=json.JSONDecoder().raw_decode(messages[-1]['content'].rsplit('Complete condition register (not truncated):\n',1)[1]);assert records==w['conditions']
            projection,_=json.JSONDecoder().raw_decode(right[-1]['content'].split('Company evidence projection (host, not model-invented facts):\n',1)[1])
            assert projection==w['company_evidence']==company_evidence(w['facts']['real_input_dossier']['company'])
            data=deepcopy(fixture_bid) if w['marker']=='BID_DOCUMENT' else {'thoughts':'','decision':'bid','reason':'Synthetic interface probe.','content':'Proposed work only.'}
            data.update(unresolved_condition_ids=[c['condition_id'] for c in w['conditions']],verified_condition_ids=[],bid_assumptions=['Synthetic probe, not a model response or correct business answer.'])
            assessment={'company_id':projection['company_id'],'projection_sha256':projection['projection_sha256'],'topics':{}}
            for topic,spec in projection['topics'].items():
                ref=spec['allowed_source_refs'][0] if spec['allowed_source_refs'] else None
                assessment['topics'][topic]={'status':spec['status'],'source_ref':ref,'quote':projection['sources'][ref]['text'] if ref else ''}
            data['company_assessment']=assessment
            old=evaluate(json.dumps(data),w,'v2_4');assert old['status']=='accepted',(wid,old.get('error'))
            data['task_role']=w['role'];new=evaluate(json.dumps(data),w,'v2_5');assert new['status']=='accepted',(wid,new.get('error'))
            probes.append({'window_id':wid,'baseline_reference_probe':old['status'],'candidate_reference_probe':new['status'],'same_external_facts':True,'is_model_quality_result':False})
        for m in manifest:
            f,missing=[windows[m['base_unit']+'-'+v] for v in ('full','missing_core')]
            assert f['conditions']==missing['conditions'] and f['facts']['real_input_dossier']['project']==missing['facts']['real_input_dossier']['project']
            removed={'business_scope','industry','certifications','staff_scale','talent_structure'}
            assert all(missing['facts']['real_input_dossier']['company'][k]==('' if k in removed else value) for k,value in f['facts']['real_input_dossier']['company'].items())
            assert missing['company_evidence']['topics']['scope']['status']=='unknown'
        with tempfile.TemporaryDirectory(prefix='capstone-expand24-preflight-') as tmp:
            store=TaskStore(run_id='offline-expanded24',organization_ids=['host'],path=Path(tmp)/'budget.sqlite')
            try:
                budget=ModelCallBudget(store=store,budget_id='planning-only',max_calls=CAP)
                assert budget.reserve('firsts',192) and budget.reserve('retries',48) and not budget.reserve('over',1)
                budget.finish('firsts');budget.finish('retries');assert budget.usage()['charged_or_reserved_calls']==0
            finally:store.close()
    assert not constructors and guard.attempts==0
    old_manifest=read(PREVIOUS/'live_release_manifest.json')
    assert all(sha(REPAIR/p)==h for p,h in old_manifest['files'].items()),'Previous released artifacts changed'
    save(OUT/'review_template.json',{'status':'unscored; do not treat interface probes as model outputs','ratings':[
      {'job':j,'source_met':None,'source_lenient':None,'role_met':None,'gate_met':None,'unknown_assertions':None,'new_prerequisites':None,'substantive_proposal':None,'quotes':[],'reason':None} for j in protocol['jobs']]})
    result={'passed':True,'source_groups':24,'controlled_tasks':48,'first_jobs':192,'synthetic_interface_probes':96,
      'probes':probes,'budget_cap_preflight':CAP,'first_priority':192,'max_final_retries':48,
      'provider_requests':0,'client_constructions':0,'network_attempts':0,'authorized_cap_now':0,
      'new_project_group_overlap':0,'previous_release_unchanged':True,'production_code_unchanged':True,
      'status':'Ready for independent new budget authorization; no real model run started',
      'limits':'Reference/status/schema wiring only, not semantic accuracy. Known dataset, one role per project, no full macro lifecycle or new organizational experiment.'}
    save(OUT/'preflight.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='probes'},ensure_ascii=False))


if __name__=='__main__':main()
