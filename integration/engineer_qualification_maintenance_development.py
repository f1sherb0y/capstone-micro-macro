"""Predeclare upkeep policy through existing scenario builders; bind real observations later."""
from pathlib import Path

from integration.professional_methods_development import build_bundle as methods_foundation
from integration.contractor_tender_development import _write, _write_launch_files
from integration.verify_tender_closed_loop import read


def build_bundle(directory, *, run_id, regulatory_pressure_index, minimum_pressure='0.6'):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    foundation = directory / 'methods-foundation'
    methods_foundation(foundation, run_id=run_id, regulatory_pressure_index=regulatory_pressure_index)
    settings = read(foundation / 'assembly-host.json')['settings']
    document = read(foundation / 'professional-methods-input.json')
    document['plans'] = [p for p in document['plans'] if p['role'] == 'Engineer']
    for plan in document['plans']:
        policy, = [r['value'] for r in plan['objects'] if r['ref']['kind'] == 'MonthlyMethodPolicy']
        policy['qualification_maintenance_pressure'] = {
            'value': minimum_pressure, 'unit': 'index', 'basis_ref': policy['evidence_refs'][0]}
        policy['method_focus'] = 'Review professional obligations and Hong Kong regional compliance knowledge'
    sources = _write(directory, 'qualification-maintenance-input.json', document)
    settings.update(sources)
    _write(directory, 'assembly-host.json', {'schema_version': 'gba-module-host-config.v1',
        'host_id': run_id, 'version': '1', 'settings': settings})
    native = read(foundation / 'native-host.json')
    native['settings']['native_proposals'].append({'role': 'Architect', 'operation': 'decide_monthly_operation'})
    native['settings']['native_decisions'].append({'role': 'Architect', 'decision_type': 'monthly_enterprise_operation'})
    _write(directory, 'native-host.json', native)
    _write(directory, 'macro-request.json', read(foundation / 'macro-request.json'))
    _write_launch_files(directory, assembly_hook='integration.engineer_qualification_maintenance:configure_assembly', readme_override=__doc__)
