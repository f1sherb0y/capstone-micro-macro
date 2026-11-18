"""Declare an existing construction relationship and independent A12 review thresholds."""
from copy import deepcopy
from pathlib import Path
from integration.professional_methods_development import build_bundle as methods_foundation
from integration.contractor_tender_development import _write, _write_launch_files, ref
from integration.verify_tender_closed_loop import read
from integration.bootstrap import enable_gba_imports


def build_bundle(directory, *, run_id, config):
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=False)
    foundation = directory / 'methods-foundation'
    methods_foundation(foundation, run_id=run_id, regulatory_pressure_index=0.2, ticks=config['ticks'])
    document = read(foundation / 'professional-methods-input.json')
    own = {p['role']: p['organization_id'] for p in document['plans']}
    for plan in document['plans']:
        for row in plan['objects']:
            value = row['value']
            if row['ref']['kind'] == 'MonthlyMethodPolicy':
                value['baseline_requirement']['value'] = '0'
                value['regulatory_pressure_weight']['value'] = '0'
                value['maximum_prior_improvements'] = config['ticks']
                value['construction_review'] = deepcopy(config['review_policy'])
                value['method_focus'] = 'Review own actual aggregate construction feedback; no formal work or certification'
            if row['ref']['kind'] == 'MonthlyMethodObservation':
                value['construction_results'] = None
    source = _write(directory, 'professional-methods-input.json', document)
    host = read(foundation / 'assembly-host.json'); host['settings'].update(source)
    macro = deepcopy(config['initial_macro_request']); macro['ticks'] = config['ticks']
    rename = {'construction-architect': own['Architect'], 'construction-engineer': own['Engineer']}
    macro['agents'] = [a for a in macro['agents'] if a['agent_id'] not in {'terms-architect', 'terms-engineer'}]
    for agent in macro['agents']:
        agent['agent_id'] = rename.get(agent['agent_id'], agent['agent_id'])
    for project in macro['initial_projects']:
        for field in ('selected_architect_id', 'selected_engineer_id'):
            project[field] = rename[project[field]]
        for engagement in project['engagements']:
            engagement['agent_id'] = rename.get(engagement['agent_id'], engagement['agent_id'])
    enable_gba_imports()
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    _write(directory, 'macro-request.json', SimulationCreateRequest.model_validate(macro).model_dump(mode='json'))
    snapshot = host['settings']['authority']['organization_snapshot']
    declared = {o['organization_id'] for o in snapshot['organizations']}
    for agent in macro['agents']:
        organization = agent['agent_id']
        if organization in declared: continue
        basis = deepcopy(snapshot['organizations'][0]['evidence_refs'][0])
        snapshot['organizations'].append({'organization_id': organization, 'actor_id': organization,
            'source_ids': ['synthetic:' + organization],
            'public_description': 'Explicit background native participant; no micro action claimed.',
            'public_location': {'state': 'known', 'value': agent['region']}, 'members': [], 'evidence_refs': [basis],
            'assignments': [{'role': agent['role'], 'function_ref': ref('FunctionAssignment', organization + '-native-function'),
                'configuration_version': '1', 'basis_refs': [basis]}]})
    _write(directory, 'assembly-host.json', host)
    roles = sorted({a['role'] for a in macro['agents']} - set(own))
    _write(directory, 'native-host.json', {'schema_version': 'gba-module-host-config.v1', 'host_id': run_id,
        'version': '1', 'settings': {'run_id': run_id,
            'native_proposals': [{'role': r, 'operation': 'decide_monthly_operation'} for r in roles],
            'native_decisions': [{'role': r, 'decision_type': 'monthly_enterprise_operation'} for r in roles]}})
    _write_launch_files(directory, assembly_hook='integration.professional_construction_feedback:configure_assembly',
        readme_override=__doc__, source_note=config['source_note'])
