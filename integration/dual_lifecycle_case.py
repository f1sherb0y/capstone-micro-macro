"""Author and run comparable offline/model tender-to-settlement demonstrations.

All alternatives and agreement views are authored before either engine starts.
The model selects an authorized A02 pricing input. Original processors and the
native engine retain calculation, execution and subsequent feedback handling.
"""
import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from integration.bootstrap import enable_gba_imports
enable_gba_imports()
from integration.contractor_tender_development import _write, _write_launch_files, verify_bundle
from integration.tender_closeout_followup_development import build_bundle as build_base
from integration.tender_model_development import TenderModelDevelopmentSettings, add_initial_model_options
from src.actions.contracts.contractor_formation_objects import ContractorFormationTermsView, contractor_agreement_digest
from src.coordination.tasks import task_digest


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_bytes())


def remap(value, prefix, suffix):
    """Namespace only the original independently authored agreement identities."""
    if isinstance(value, str):
        return value.replace(prefix, prefix + suffix)
    if isinstance(value, list):
        return [remap(v, prefix, suffix) for v in value]
    if isinstance(value, dict):
        return {k: remap(v, prefix, suffix) for k, v in value.items()}
    return value


def add_agreement_variant(plan, *, price, snapshot):
    """A new initial declaration, never a runtime adjustment to an accepted bid."""
    prefix = plan['organization_id'] + '-actual-terms'
    suffix = '-price-' + price
    result = remap(plan, prefix, suffix)
    terms, = [r['value'] for r in result['objects'] if r['ref'] == result['action_input']['terms_ref']]
    terms['price']['value'] = price
    for row in result['objects']:
        if row['ref']['kind'] in {'FundingCommitment', 'SettlementComponent', 'ContractPayment'}:
            if 'amount' in row['value'] and 'new-contract-cost' not in row['ref']['id']:
                row['value']['amount']['value']['value'] = price
        if row['ref']['kind'] == 'ContractFormationProfile':
            row['value']['reviewed_agreement_sha256'] = contractor_agreement_digest(
                ContractorFormationTermsView.model_validate(terms))
        if row['ref']['kind'] == 'Evidence' and row['value']['basis_kind'] != 'observed':
            row['value']['content_hash'] = task_digest({'initial_original_plan_sha256': task_digest(plan),
                'independently_declared_price': price, 'namespace': prefix + suffix})
    # Clone the final shared grants, including the original read horizon. Keep
    # all original authorities and add distinct functions for this declaration.
    grants = [remap(g, prefix, suffix) for g in snapshot['authorizations']
              if g['ref']['id'].startswith(prefix) and '-price-' not in g['ref']['id']]
    snapshot['authorizations'].extend(grants)
    for org in snapshot['organizations']:
        org['assignments'].extend([remap(a, prefix, suffix) for a in org['assignments']
            if a['function_ref']['id'].startswith(prefix) and '-price-' not in a['function_ref']['id']])
    by_ref = {task_digest(g['ref']): g for g in grants}
    for row in result['objects']:
        if row['ref']['kind'] == 'Authorization' and task_digest(row['ref']) in by_ref:
            row['value'] = deepcopy(by_ref[task_digest(row['ref'])])
    return result


def execution_contexts(value, mode):
    """Change only original A01/A02 invocation modes in a newly authored copy."""
    if isinstance(value, list):
        return [execution_contexts(v, mode) for v in value]
    if isinstance(value, dict):
        result = {k: execution_contexts(v, mode) for k, v in value.items()}
        if result.get('contract_ref', {}).get('id') in {'CONTRACTOR-A01', 'CONTRACTOR-A02'}:
            result['execution_mode'] = mode
        return result
    return value


def snapshot_file(directory, name, document):
    source = _write(directory, name, document)
    return {'version': '1', 'snapshot_path': source['file_path'],
        'snapshot_sha256': source['file_sha256'], 'bind_native_on_request': True}


def align_source_contexts(value, contexts):
    if isinstance(value, list):
        return [align_source_contexts(v, contexts) for v in value]
    if isinstance(value, dict):
        if 'contract_ref' in value and value.get('read_token') in contexts:
            return deepcopy(contexts[value['read_token']])
        return {k: align_source_contexts(v, contexts) for k, v in value.items()}
    return value


def build_pair(directory, config):
    from integration.owner_award_native_development import build_owner_sources
    from src.organization.registry import OrganizationRegistry, OrganizationSnapshot
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    model = TenderModelDevelopmentSettings.model_validate(config['model_options'])
    if model.strategy != 'single_agent' or model.max_calls > 4:
        raise ValueError('This demonstration declares single-agent pricing and at most four API attempts')
    # Preserve the previously supported bundle as provenance. Author new final
    # inputs in separate directories; never unseal or rewrite a child manifest.
    base = directory / 'base-input'
    build_base(base, run_id=config['run_id'], with_owner_award=True,
        with_government_completion=True, authorization_read_until_tick=25)
    host = read(base / 'assembly-host.json')
    settings = host['settings']
    authority = settings['formation']['authority']
    snapshot = authority['organization_snapshot']
    sources = settings['tender']['settings']['source_settings']
    app = sources['application_settings']['owner_contractor']['contractor']
    source_doc = read(sources['snapshots']['snapshot_path'])
    quantity_doc = read(sources['quantity_snapshots']['snapshot_path'])
    plans = app['request_work_settings']['requests']
    auths = {p['organization_id']: next(g for g in snapshot['authorizations']
        if g['ref'] in p['screening_context']['authorization_refs']) for p in plans}
    add_initial_model_options(config=model, snapshots=source_doc['snapshots'],
        quantity_snapshots=quantity_doc['snapshots'], plans=plans, authorizations=auths)
    # The sealed base has independent JSON copies of its pipeline contexts.
    # Keep every copied context identical to its original reader after adding
    # the same initial candidate to all views of that immutable CandidateSet.
    contexts = {s['context']['read_token']: s['context'] for s in source_doc['snapshots']}
    plans = align_source_contexts(plans, contexts)
    app['request_work_settings']['requests'] = plans
    for source in quantity_doc['snapshots']:
        source['context'] = deepcopy(contexts[source['context']['read_token']])
    formations = read(settings['formation']['file_path'])
    original_plans = list(formations['plans'])
    for plan in original_plans:
        profiles = [r['ref'] for s in source_doc['snapshots']
            if s['projection']['organization_id'] == plan['organization_id']
            for r in s['projection']['objects']
            if r['ref']['kind'] == 'ContractorPricingProfile' and r['ref']['id'].endswith('-model-alternative')]
        for reference in profiles:
            if reference not in plan['context']['visible_refs']:
                plan['context']['visible_refs'].append(deepcopy(reference))
            for grant in snapshot['authorizations']:
                if grant['ref'] in plan['context']['authorization_refs'] and reference not in grant['readable_refs']:
                    grant['readable_refs'].append(deepcopy(reference))
            for row in plan['objects']:
                if row['ref']['kind'] == 'Authorization' and reference not in row['value']['readable_refs']:
                    row['value']['readable_refs'].append(deepcopy(reference))
    alternative_price = str(Decimal('100') * (Decimal('1') + Decimal(model.alternate_markup_fraction)))
    for plan in original_plans:
        formations['plans'].append(add_agreement_variant(plan, price=alternative_price, snapshot=snapshot))
    shared = directory / 'shared-input'
    shared.mkdir()
    owner, snapshot = build_owner_sources(shared, run_id=config['run_id'],
        formation_plans=formations['plans'], snapshot=snapshot, max_prior_accepts=1)
    authority['organization_snapshot'] = snapshot
    checked = OrganizationSnapshot.model_validate(snapshot)
    registry = OrganizationRegistry(config['run_id'])
    for org in checked.organizations:
        registry.register(org)
    for grant in checked.authorizations:
        registry.authorize(grant)
    settings['formation'].update(**_write(shared, 'contractor-formation-input.json', formations),
        owner=owner.model_dump(mode='json'), authority=authority)
    for name in ['supplier', 'government', 'opportunity']:
        settings[name]['authority'] = authority
    app['authority'] = authority
    request = read(base / 'macro-request.json')
    native = read(base / 'native-host.json')
    _write(shared, 'source-declaration.json', {
        'schema_version': 'dual-lifecycle-initial-sources.v1', 'run_id': config['run_id'],
        'source_kind': 'synthetic', 'initial_native_request_sha256': task_digest(request),
        'original_markup_fraction': '0.1', 'alternate_markup_fraction': model.alternate_markup_fraction,
        'initial_authorized_agreement_prices_HKD': ['110', alternative_price],
        'initial_independent_formation_plans_sha256': task_digest(formations),
        'model_scope': 'Contractor A02 chooses between original-processor-validated pricing policies.',
        'later_judgment': 'Owner A03 uses actual own settlement under the existing predefined policy.',
        'source_or_result_modified_after_engine_start': False})
    # These common documents are retained for checking that each mode changes
    # only execution settings, not initial business assumptions or native state.
    _write(shared, 'tender-sources-rule.json', source_doc)
    _write(shared, 'quantity-sources-rule.json', quantity_doc)
    _write(shared, 'request-work-rule.json', plans)
    for mode in ['offline', 'model']:
        folder = directory / mode / 'input'
        folder.mkdir(parents=True)
        current = deepcopy(host)
        ss = current['settings']['tender']['settings']['source_settings']
        application = ss['application_settings']['owner_contractor']['contractor']
        execution = 'rule' if mode == 'offline' else 'llm'
        ss['snapshots'] = snapshot_file(folder, 'sources.json', execution_contexts(source_doc, execution))
        ss['quantity_snapshots'] = snapshot_file(folder, 'quantity-sources.json', execution_contexts(quantity_doc, execution))
        application['request_work_settings']['requests'] = execution_contexts(plans, execution)
        if mode == 'model':
            application.update(model_host_factory='integration.contractor_tender_model_options:build_model_host',
                model_host_settings=model.host_settings(config['run_id']))
        _write(folder, 'assembly-host.json', current)
        _write(folder, 'macro-request.json', request)
        routes = deepcopy(native)
        if mode == 'model':
            routes['settings'] = {'native': routes['settings'], 'expected_provider': model.provider,
                'expected_model': model.model}
        _write(folder, 'native-host.json', routes)
        _write_launch_files(folder, offline=mode == 'offline',
            assembly_hook='integration.dual_lifecycle_case:configure_assembly',
            agent_client_factory=('integration.native_routes:build_agent_client' if mode == 'offline'
                else 'integration.model_tender_native:build_agent_client'),
            allow_native_project_generation=True, allow_native_initial_projects_with_generation=True,
            source_note='Same synthetic long-chain initial facts; independent offline/model journals.',
            readme_override='Run run.ps1 with a NEW output directory. Model mode may make paid requests. '
                'Only configured Contractor pricing uses a model; later settlement policy is rule based.')
    # Top-level manifest also covers cross-directory sources and all child
    # input bytes. Native run output belongs outside these input directories.
    _write(directory, 'case-config.json', config)
    files = {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in directory.rglob('*') if p.is_file()}
    _write(directory, 'pair-input-manifest.json', {'schema_version': 'dual-lifecycle-input.v1', 'files': files})
    return {'status': 'initial-pair-authored-not-executed', 'directory': str(directory)}


def verify_inputs(directory):
    directory = Path(directory).resolve()
    for name, expected in read(directory / 'pair-input-manifest.json')['files'].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Dual case input changed: ' + name)
    if read(directory/'offline/input/macro-request.json') != read(directory/'model/input/macro-request.json'):
        raise ValueError('The pair changes original macro inputs')
    for mode in ['offline', 'model']:
        verify_bundle(directory / mode / 'input')
    return {'status': 'frozen-pair-input-bytes-verified'}


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    from integration.contractor_tender_formation_development import TenderFormationComposition
    from integration.model_tender_native import ModelTenderAgentClient
    from integration.module_host import GbaModuleHostExtension
    if not offline and not isinstance(assembly.client, ModelTenderAgentClient):
        raise ValueError('Live full lifecycle requires its declared model transport')
    app = TenderFormationComposition(assembly=assembly, request=request, output_directory=output_directory,
        offline=offline, configuration=configuration)

    def evidence():
        return {**app.evidence(), 'original_global_events': [e.model_dump(mode='json')
            for e in assembly.engine.events.events]}

    return GbaModuleHostExtension(version='dual-lifecycle-case.v1', evidence=evidence,
        close=app.close, writer_guard=app.authority.read_guard)


def run_mode(directory, mode):
    directory = Path(directory).resolve()
    verify_inputs(directory)
    folder = directory / mode
    runtime = folder / 'runtime'
    if runtime.exists() or (folder / 'command.json').exists():
        raise ValueError('Preserve existing executions; author a new case, never silently retry')
    command = [sys.executable, '-m', 'integration.run', '--input', str(folder/'input/macro-request.json'),
        '--output', str(runtime), '--offline' if mode == 'offline' else '--llm',
        '--input-format', 'gba_request', '--macro-mode', 'gba_v1_module',
        '--allow-native-project-generation', '--allow-native-initial-projects-with-generation',
        '--agent-client-factory', ('integration.native_routes:build_agent_client' if mode == 'offline'
            else 'integration.model_tender_native:build_agent_client'),
        '--agent-client-config', str(folder/'input/native-host.json'),
        '--module-assembly-hook', 'integration.dual_lifecycle_case:configure_assembly',
        '--module-assembly-config', str(folder/'input/assembly-host.json')]
    _write(folder, 'command.json', command)
    with (folder/'stdout.log').open('xb') as out, (folder/'stderr.log').open('xb') as err:
        result = subprocess.run(command, cwd=ROOT, stdout=out, stderr=err)
    _write(folder, 'exit.json', {'exit_code': result.returncode})
    if result.returncode != 0:
        raise RuntimeError('Actual run failed; retain original logs and journal: ' + str(folder))
    return {'mode': mode, 'exit_code': result.returncode, 'runtime': str(runtime)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--build', type=Path, metavar='CONFIG')
    action.add_argument('--verify-inputs', action='store_true')
    action.add_argument('--run', choices=['offline', 'model'])
    args = parser.parse_args(argv)
    if args.build:
        result = build_pair(args.directory, read(args.build))
    elif args.run:
        result = run_mode(args.directory, args.run)
    else:
        result = verify_inputs(args.directory)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
