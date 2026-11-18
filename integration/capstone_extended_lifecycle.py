"""Independent CP03X domain/region compiler over unchanged native processors.

Only pre-execution declarations are authored. No runtime source/result is
renamed, no procurement mode changed and no local-law validation claimed.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
from unittest.mock import patch

from integration.catalog import SharedCatalog, DEFAULT_SOURCE
from integration.capstone_extended_catalog import scenario
from integration.case_library_lifecycle import LibraryInitialSources
from integration.contractor_tender_development import _write, _write_launch_files
from src.coordination.tasks import task_digest

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_bytes())


def existing_opportunity_domain(policy, region, project_type):
    """Read the real policy contract; never widen its existing permissions."""
    regions, uses = policy['allowed_regions'], policy['project_use_codes']
    if (not isinstance(regions, list) or not all(isinstance(r, str) for r in regions)
            or not isinstance(uses, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in uses.items())):
        raise ValueError('Owner opportunity policy requires region list and type-to-use mapping')
    if region not in regions or project_type not in uses:
        raise ValueError('New domain is not supported by the original opportunity permission policy')
    return deepcopy(regions), deepcopy(uses)


class ExtendedInitialSources(LibraryInitialSources):
    """Rebind every reachable private source and dependent digest consistently."""
    def __init__(self, directory, *, config, public_project, companies, identities):
        super().__init__(directory, config=config, public_project=public_project, companies=companies, identities=identities)
        self.domain = deepcopy(config['domain_region'])
        self.names.update({'Hong Kong': self.domain['region'], 'industrial': self.domain['native_project_type'],
                           'synthetic-work': self.domain['work_type_code']})
        self.pattern = re.compile('|'.join(re.escape(k) for k in sorted(self.names, key=len, reverse=True)))
        self.declaration = task_digest({'compiler': 'CP03X-domain-region.v1', 'config': config,
            'public_project': public_project, 'public_companies': companies, 'identities': identities})

    def transform(self, value):
        result = super().transform(value)
        if not isinstance(value, dict):
            return result
        if 'allowed_regions' in value and 'project_use_codes' in value:
            regions, uses = existing_opportunity_domain(value, self.domain['region'], self.domain['native_project_type'])
            result['allowed_regions'], result['project_use_codes'] = regions, uses
        if result.get('ref', {}).get('kind') == 'Requirement' and 'description' in result:
            result['description'] += '; CONTROLLED_DOMAIN_SCOPE=' + self.domain['construction_scope']
        if result.get('basis_kind') == 'assumed' and result.get('locator'):
            # Explicit assumptions remain assumptions. Do not rewrite the
            # exact file-backed/native observation locators or observed hashes.
            result['locator'] += '; CP03X_CONTROLLED_DOMAIN=' + json.dumps({
                'domain': self.domain['domain'], 'design': self.domain['design_scope'],
                'works': self.domain['construction_scope'], 'supply': self.domain['supply_scope'],
                'scope_class': self.domain['scope_class'],
                'boundary': 'Normalized quantity/cost/capacity, not a physical quantity takeoff, confirmed method competence or local regulatory approval.'}, ensure_ascii=False, sort_keys=True)
        return result


def build_bundle(directory, config):
    from integration.capstone_mechanism_native import allowed_model_options
    import integration.origin_model_lifecycle as origin
    from integration.origin_lifecycle_case import build_bundle as build_origin
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    arm = config['research_arm']
    assert arm in {'R', 'S', 'D3', 'S4'}
    assert config['model_options']['strategy'] == ('organization_discussion' if arm == 'D3' else 'single_agent')
    catalog = SharedCatalog(directory / 'case-catalog.sqlite3')
    imported = catalog.import_inputs(DEFAULT_SOURCE)
    dataset = scenario(catalog, config)
    project, = dataset.payload['projects']
    domain = config['domain_region']
    assert project['region'] == domain['region'] and project['project_type'] == domain['native_project_type']
    assert project['currency'] == 'HKD' and project['delivery_mode'] == 'DBB'
    companies = dataset.payload['companies']
    def role(name):
        return [c for c in companies if c['company_role'] == name]
    owner, = role('owner')
    designers, supervisors, contractors, suppliers = [role(name) for name in ['designer', 'supervisor', 'contractor', 'supplier']]
    identities = {'finance-owner-a': owner['company_id'],
        'finance-architect': designers[0]['company_id'], 'finance-architect-b': designers[1]['company_id'],
        'finance-qs': supervisors[0]['company_id'], 'finance-engineer': supervisors[1]['company_id'],
        'finance-contractor': contractors[0]['company_id'], 'origin-contractor-b': contractors[1]['company_id'],
        'finance-supplier': suppliers[0]['company_id'], 'origin-supplier-b': suppliers[1]['company_id']}
    base = read(ROOT / config['base_config'])
    base.update(run_id=config['run_id'], model_options=deepcopy(config['model_options']),
        api_total_attempt_cap=config['api_total_attempt_cap'], contract_duration=config['contract_duration'])
    original_configure = origin.configure_model_inputs
    def configure(path, host, native, base_config):
        host, native = original_configure(path, host, native, base_config)
        app = host['settings']['tender']['settings']['source_settings']['application_settings']['owner_contractor']['contractor']
        if arm in {'R', 'S4'}:
            app['model_host_factory'] = 'integration.capstone_mechanism_controls:build_model_host'
            app['model_host_settings']['research_control_arm'] = arm
        native['settings']['cp03_control'] = deepcopy(config['cp03_control'])
        return host, native
    foundation = directory / 'origin-foundation'
    with patch.object(origin, 'model_options', allowed_model_options), patch.object(origin, 'configure_model_inputs', configure):
        build_origin(foundation, base)
    transformer = ExtendedInitialSources(directory / 'case-declarations', config=config,
        public_project=project, companies=companies, identities=identities)
    host = transformer.settings(read(foundation / 'assembly-host.json'))
    host = transformer.bind_initial_digests(host)
    request = transformer.transform(read(foundation / 'macro-request.json'))
    by_company = {c['company_id']: c for c in companies}
    for agent in request['agents']:
        if agent['agent_id'] in by_company:
            agent['name'] = by_company[agent['agent_id']]['company_name']
    authority = host['settings']['bank']['authority']
    for organization in authority['organization_snapshot']['organizations']:
        company = by_company.get(organization['organization_id'])
        if company:
            organization['public_description'] = company['company_name'] + '; ' + company['profile']
    for name in ['bank', 'professional', 'opportunity', 'formation', 'supplier', 'government']:
        host['settings'][name]['authority'] = deepcopy(authority)
    host['settings']['tender']['settings']['source_settings']['application_settings']['owner_contractor']['contractor']['authority'] = deepcopy(authority)
    request.update(ticks=config['ticks'], random_seed=config['random_seed'],
        initial_projects=[{'project_id': project['project_id'], 'name': project['name'],
            'project_type': project['project_type'], 'region': project['region'], 'owner_id': project['owner_id'],
            'current_stage': 'initiation', 'initial_budget': project['budget'], 'technical_complexity': config['technical_complexity'],
            'performance': {'planned_duration': config['contract_duration']},
            'flags': {'case_library_public_background': deepcopy(project), 'controlled_domain_scope': deepcopy(domain)}}])
    native = transformer.transform(read(foundation / 'native-host.json'))
    for name, data in [('macro-request.json', request), ('assembly-host.json', host), ('native-host.json', native),
                       ('case-config.json', config), ('macro-before.json', read(foundation / 'macro-before.json')),
                       ('case-library-input.json', dataset.payload)]:
        _write(directory, name, data)
    _write(directory, 'source-declaration.json', {'source_kind': 'CP03X-input-background-with-domain-region-control-assumptions',
        'catalog_inputs': imported, 'project': project, 'domain_region': domain, 'actor_identity_mapping': identities,
        'source_fields_used': ['case_id', 'project_name', 'project_type', 'location', 'delivery_mode', 'owner_name', 'scale',
                             'company_id', 'company_name', 'business_scope', 'industry', 'certifications', 'office_location'],
        'excluded': 'Historical winners/partners, reserve prices, evaluation hints and historical outcomes.',
        'assumptions': {'currency': 'HKD mechanism unit, not local historical denomination or FX conversion',
            'budget': config['scenario_budget'], 'duration': config['contract_duration'], 'complexity': config['technical_complexity'],
            'local_qualification_and_operating_capacity': 'Explicit scenario eligibility, not verified actual enterprise capability',
            'technical_numbers': 'Original normalized methods/costs and document-code checks; no calibrated domain-specific physical dynamics or local-law verification.',
            'active_A02_contractor_count': 2, 'unused_catalog_contractor': contractors[2]['company_id'],
            'supply_handoffs_if_signed': 8},
        'scope_stratum': domain['scope_class'], 'whole_parent_project_claim': False,
        'outcomes_prefilled': False, 'request_consumption': 'Final native publication and actual model-request evidence must still be checked after execution.'})
    _write_launch_files(directory, offline=False,
        assembly_hook='integration.origin_model_lifecycle:configure_assembly',
        agent_client_factory='integration.capstone_finish_native:build_agent_client',
        allow_native_project_generation=True, allow_native_initial_projects_with_generation=True,
        source_note='CP03X native named-scope DBB lifecycle with real source region/type and explicit domain assumptions; no outcomes, physical calibration, local-law validation or FX conversion.',
        readme_override='Prepared sources only. Use the scoped CP03X runner and separate batch ledger. Work-package scopes stay work packages; current global paid stop must not be bypassed.')
    return {'status': 'sources_authored_not_executed', 'case_id': config['case_id'], 'domain': domain['domain'],
            'region': domain['region'], 'native_project_type': domain['native_project_type']}
