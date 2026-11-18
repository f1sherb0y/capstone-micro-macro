"""Read the first fixed four-arm block only after all four native chains finish.

Retain the catalogue of324 slots; other slots never become failed or zero-valued
metrics. Avoid hashing a live journal or all not-yet-executed giant input files.
No frozen runner, extraction formula or protocol is changed.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import json
from load_capstone_macro_results_20261113 import (
    BATCHES,MASTER,ROOT,read,save,sha,locator,no_provider,extract_chain,chain_table_row,write_csv)


def main(tag=None):
    catalogue=[];pins={};jobs_by_key={}
    family_path=MASTER/'macro_preparation/source_scope_and_families.json'
    families={r['case_id']:r for r in read(family_path)}
    pins[locator(family_path)]=sha(family_path)
    for batch,directory in BATCHES.items():
        protocol=directory/'protocol.json';p=read(protocol);pins[locator(protocol)]=sha(protocol)
        for job in p['jobs']:
            chain=directory/'chains'/job['chain_id'];family=families[job['case_id']]
            config=ROOT/job['config_path'];assert sha(config)==job['config_sha256']
            pins[locator(config)]=sha(config)
            state=('saved_terminal_exit' if (chain/'exit.json').exists() else
                   'saved_started_without_exit' if (chain/'command.json').exists() else 'no_saved_start')
            catalogue.append({'batch':batch,**job,'macro_family_id':family['macro_family_id'],
                'scope_stratum':family['scope_is_full_project_or_package'],'source_region':family['location'],
                'source_project_name':family['project_name'],'formal_chain_directory':locator(chain),
                'observed_execution_state':state,'metric_scope':'outside_first_fixed_block_not_extracted'})
            jobs_by_key[(batch,job['chain_id'])]=(job,chain)
    assert len(catalogue)==len(jobs_by_key)==324
    first=[r for r in catalogue if r['batch']=='CP03'][:4]
    assert len({(r['case_id'],r['repeat'],r['seed']) for r in first})==1
    assert {r['arm'] for r in first}=={'R','S','D3','S4'}
    ready=all((jobs_by_key[('CP03',r['chain_id'])][1]/'exit.json').exists() for r in first)
    print(json.dumps({'first_block':[r['chain_id'] for r in first],'all_four_terminal':ready,
        'execution_states':dict(Counter(r['observed_execution_state'] for r in first)),
        'new_model_calls':0},ensure_ascii=False))
    if not tag or not ready:return
    assert all(c.isalnum() or c in '_-' for c in tag)
    target=MASTER/'macro_results'/tag;assert not target.exists()
    started=datetime.now(timezone.utc).isoformat();rows=[]
    with no_provider() as counts:
        for selected in first:
            job,chain=jobs_by_key[('CP03',selected['chain_id'])]
            assert read(chain/'exit.json')['exit_code']==0,'No metrics from a failed native chain'
            assert read(chain/'input/case-config.json')==read(ROOT/job['config_path'])
            for p in (chain/'input').rglob('*'):
                if p.is_file():pins[locator(p)]=sha(p)
            for name in ['exit.json','command.json','runtime/tasks.sqlite','runtime/result.json','runtime/native-run-state.json']:
                p=chain/name
                if p.is_file():pins[locator(p)]=sha(p)
            for p in (BATCHES['CP03']/'run/provider_attempts'/job['chain_id']).glob('*.json'):
                assert read(p)['status']=='returned'
                pins[locator(p)]=sha(p)
            extracted=extract_chain(chain,job)
            assert extracted['original_model_calls']<=job['expected_max_provider_calls']
            rows.append({**selected,'state':'verified_complete_horizon_observations',
                'metric_scope':'first_fixed_four_arm_block',**extracted})
        assert len({r['fixed_fact_block_sha256'] for r in rows})==1
        for p,digest in pins.items():assert sha(ROOT/p)==digest,'Source changed during extraction: '+p
    for r in catalogue:
        if r['chain_id'] in {x['chain_id'] for x in rows} and r['batch']=='CP03':
            r['metric_scope']='first_fixed_four_arm_block'
    save(target/'all324_planned_catalogue.json',catalogue)
    save(target/'first_block_observations.json',rows)
    write_csv(target/'first_block_metrics.csv',[chain_table_row(r) for r in rows])
    save(target/'manifest.json',{'started_at_UTC':started,'finished_at_UTC':datetime.now(timezone.utc).isoformat(),
        'selection':'First four jobs in frozen CP03 protocol execution order; no performance-based selection.',
        'planned_catalogue_slots':324,'observed_metric_chains':4,'source_project_groups_with_metrics':1,
        'result_identity':'First-block descriptive extraction; not a324-chain result or project-level effect estimate.',
        'source_sha256':pins,'extractor_sha256':sha(Path(__file__)),
        'existing_extraction_code_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [
            ROOT/'scripts/load_capstone_macro_results_20261113.py',
            ROOT/'scripts/capstone_macro_observations_20261113.py',
            ROOT/'scripts/capstone_pricing_observations_20261113.py',
            ROOT/'integration/capstone_mechanism_results.py']},
        'artifact_sha256':{p.name:sha(p) for p in target.iterdir() if p.is_file()},
        'new_model_calls':0,'new_simulations':0,**counts})
    print('First fixed four-arm native block extracted with original worker/bid/state evidence;324 catalogue slots retained.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--tag');main(p.parse_args().tag)
