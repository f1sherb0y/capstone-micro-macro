"""Initial opportunity through existing micro tender/closeout in one native run."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from integration.front_to_closeout_case import build_bundle as build_front, read
from integration.origin_lifecycle_sources import compose_late
from integration.contractor_tender_development import _write, _write_launch_files, verify_bundle
from integration.verify_goal3_minimal_native_fix import macro_snapshot


ROOT=Path(__file__).resolve().parents[1]


def build_bundle(directory, config):
    mode=config.get('mode','offline')
    if mode not in {'offline','model'}:
        raise ValueError('Declare offline or model mode explicitly')
    if mode=='model':
        from integration.origin_model_lifecycle import author_initial_options, configure_model_inputs
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    front=directory/'front-foundation'
    build_front(front,config)
    host,request,native=compose_late(directory/'integration-sources',config=config,
        front_host=read(front/'assembly-host.json'),request=read(front/'macro-request.json'),
        native=read(front/'native-host.json'),
        initial_source_editor=author_initial_options if mode=='model' else None)
    if mode=='model':
        host,native=configure_model_inputs(directory/'model-input',host,native,config)
    for agent in request['agents']:
        if agent['role']=='Contractor':
            agent.update(config['contractor_profile'])
    if request['initial_projects']:
        raise ValueError('A full origin case cannot adopt child projects or outcomes')
    _write(directory,'macro-request.json',request)
    _write(directory,'assembly-host.json',host)
    _write(directory,'native-host.json',native)
    _write(directory,'macro-before.json',macro_snapshot())
    _write(directory,'case-config.json',config)
    _write(directory,'source-declaration.json',{'source_kind':'synthetic',
        'initial_projects':[],'project_creation':'original opportunity generator only',
        'profile_settings':'Original supported initial enterprise profiles; no runtime state patches',
        'initial_late_templates':'Independent private contract, capacity, costs and regulatory material, not executed events',
        'late_money_scale':config['late_money_scale'],'native_budget_currency':'HKD',
        'forecast_contract_duration':config['contract_duration'],
        'tender_open_tick':config['tender_open_tick'],
        'boundary':'Fixed normal scenario. Unmet schedules or source mismatches remain errors; no automatic fallback.'})
    _write_launch_files(directory,offline=mode=='offline',
        assembly_hook=('integration.front_to_closeout_case:configure_assembly' if mode=='offline'
            else 'integration.origin_model_lifecycle:configure_assembly'),
        agent_client_factory=('integration.native_routes:build_agent_client' if mode=='offline'
            else 'integration.model_tender_native:build_agent_client'),
        allow_native_project_generation=True,
        readme_override=('No initial project. Original Owner/Bank/professional actions precede existing tender, contract, supply and settlement handlers. Fixed initial synthetic declarations; no runtime state edits. '
            + ('No live API calls.' if mode=='offline' else 'Only Contractor A02 pricing selection calls the declared model, within its separate four-attempt cap. No automatic retries or offline fallback.')))
    return {'status':'origin-lifecycle-sources-authored-not-executed','directory':str(directory)}


def run(directory):
    directory=Path(directory).resolve();source=directory/'input';verify_bundle(source)
    mode=read(source/'case-config.json').get('mode','offline')
    if mode not in {'offline','model'}:raise ValueError('Unknown execution mode')
    if mode=='model':
        from integration.origin_model_lifecycle import prior_attempts
        prior_attempts(read(source/'case-config.json'))
    if (directory/'runtime').exists() or (directory/'command.json').exists():
        raise ValueError('Use a fresh output directory; completed or failed runs are retained')
    command=[sys.executable,'-m','integration.run','--input',str(source/'macro-request.json'),
        '--output',str(directory/'runtime'),'--offline' if mode=='offline' else '--llm','--input-format','gba_request',
        '--macro-mode','gba_v1_module','--allow-native-project-generation',
        '--agent-client-factory',('integration.native_routes:build_agent_client' if mode=='offline'
            else 'integration.model_tender_native:build_agent_client'),
        '--agent-client-config',str(source/'native-host.json'),
        '--module-assembly-hook',('integration.front_to_closeout_case:configure_assembly' if mode=='offline'
            else 'integration.origin_model_lifecycle:configure_assembly'),
        '--module-assembly-config',str(source/'assembly-host.json')]
    if read(source/'case-config.json').get('entry_kind')=='case_library_initial_project':
        command.append('--allow-native-initial-projects-with-generation')
    _write(directory,'command.json',command)
    with (directory/'stdout.log').open('xb') as out,(directory/'stderr.log').open('xb') as err:
        result=subprocess.run(command,cwd=ROOT,stdout=out,stderr=err)
    _write(directory,'exit.json',{'exit_code':result.returncode})
    if result.returncode:
        raise RuntimeError('Origin lifecycle run stopped. Retain actual log and journal; no fallback.')
    return {'status':'run-finished-needs-business-verification','directory':str(directory)}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True,type=Path)
    group=p.add_mutually_exclusive_group(required=True);group.add_argument('--build',type=Path);group.add_argument('--run',action='store_true')
    args=p.parse_args(argv)
    result=build_bundle(args.directory/'input',read(args.build)) if args.build else run(args.directory)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
