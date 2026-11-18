"""Run a project created by the original opportunity entry, never a tender seed."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from integration.bootstrap import enable_gba_imports
enable_gba_imports()
from integration.contractor_tender_development import _write, _write_launch_files, verify_bundle
from integration.financing_professional_development import build_bundle as build_front
from integration.financing_professional_native import configure_assembly as configure_front
from integration.module_host import GbaModuleHostExtension
from integration.verify_goal3_minimal_native_fix import macro_snapshot, save_or_match


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_bytes())


def build_bundle(directory, config):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    base = directory/'front-sources'
    build_front(base, run_id=config['run_id'], with_owner_opportunity=True,
        with_owner_observation=True, with_owner_proposal=True,
        with_professional_opportunity=True, with_professional_feedback=True,
        max_prior_final_accounts=1)
    request = read(base/'macro-request.json')
    if request['initial_projects']:
        raise ValueError('The new case must start without any project, appointment, bid or contract')
    request.update(ticks=config['ticks'], target_project_count=2, max_active_projects=1)
    native = read(base/'native-host.json')
    routes = native['settings']
    # Explicit native background for this diagnostic run. None of these routes
    # is counted as micro coverage. Front-end micro handlers remain exclusive.
    proposals = [('Government','consider_review_assignment'), ('Government','decide_approval'),
        ('Owner','select_tender_invitees'), ('Contractor','consider_tender'), ('QS','evaluate_bid'),
        ('Owner','select_preferred_bid'), ('Contractor','decide_contract_terms'),
        ('Owner','decide_contract_award'), ('Supplier','consider_supply_order'), ('Contractor','select_supplier')]
    decisions = [('Government','government_review_assignment'), ('Government','government_design_approval'),
        ('Government','government_completion_approval'), ('Owner','owner_tender_shortlist'),
        ('Contractor','tender_decision'), ('QS','qs_bid_evaluation'), ('Owner','owner_preferred_bidder_selection'),
        ('Contractor','contract_negotiation'), ('Owner','owner_contract_award'),
        ('Supplier','supplier_order_acceptance'), ('Contractor','contractor_supplier_selection')]
    for name, rows, field in [('native_proposals',proposals,'operation'), ('native_decisions',decisions,'decision_type')]:
        for role, value in rows:
            row = {'role':role, field:value}
            if row not in routes[name]:
                routes[name].append(row)
    routes['direct_native_proposals'] = [{'role':'Owner','operation':'select_preferred_bid'}]
    _write(directory,'macro-before.json',macro_snapshot())
    _write(directory,'case-config.json',config)
    _write(directory,'macro-request.json',request)
    _write(directory,'native-host.json',native)
    _write(directory,'assembly-host.json',read(base/'assembly-host.json'))
    _write_launch_files(directory, assembly_hook='integration.front_to_closeout_case:configure_assembly',
        allow_native_project_generation=True,
        readme_override='Original opportunity generation starts with no projects. Front micro actions use existing processors. Later native background is explicitly labelled, not counted as micro or model coverage.')
    return {'status':'initial-front-entry-input-not-executed','directory':str(directory)}


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    original = configure_front(assembly=assembly,request=request,output_directory=output_directory,
        offline=offline,configuration=configuration)

    def evidence():
        events=[e.model_dump(mode='json') for e in assembly.engine.events.events]
        # Retain the actual native result before any component export can
        # fail. This is read-only capture, not a replacement success receipt.
        if assembly.engine.status=='completed':
            save_or_match(Path(output_directory),'native-run-state.json',{
                'schema_version':'origin-native-run-state.v1',
                'simulation':assembly.engine.response().model_dump(mode='json'),
                'original_global_events':events,
                'boundary':'Original native state captured before component evidence export; does not certify export or chain checks.'})
        return {**original.evidence(),'original_global_events':events}

    return GbaModuleHostExtension(version='front-to-closeout-case.v1',evidence=evidence,
        close=original.close,writer_guard=original.writer_guard)


def run(directory):
    directory = Path(directory).resolve()
    source = directory/'input'
    verify_bundle(source)
    if (directory/'runtime').exists() or (directory/'command.json').exists():
        raise ValueError('Preserve the original run; use a fresh independent directory')
    command = [sys.executable,'-m','integration.run','--input',str(source/'macro-request.json'),
        '--output',str(directory/'runtime'),'--offline','--input-format','gba_request',
        '--macro-mode','gba_v1_module','--allow-native-project-generation',
        '--agent-client-factory','integration.native_routes:build_agent_client',
        '--agent-client-config',str(source/'native-host.json'),
        '--module-assembly-hook','integration.front_to_closeout_case:configure_assembly',
        '--module-assembly-config',str(source/'assembly-host.json')]
    _write(directory,'command.json',command)
    with (directory/'stdout.log').open('xb') as out,(directory/'stderr.log').open('xb') as err:
        result = subprocess.run(command,cwd=ROOT,stdout=out,stderr=err)
    _write(directory,'exit.json',{'exit_code':result.returncode})
    if result.returncode:
        raise RuntimeError('Front-entry run stopped; retain its actual journal and diagnostics')
    return {'status':'actual-run-finished-needs-business-checks','directory':str(directory)}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',required=True,type=Path)
    action=p.add_mutually_exclusive_group(required=True)
    action.add_argument('--build',type=Path)
    action.add_argument('--run',action='store_true')
    args=p.parse_args(argv)
    result=build_bundle(args.directory/'input',read(args.build)) if args.build else run(args.directory)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
