"""Compose existing appointment and A12 scenario builders before engine creation."""
from copy import deepcopy
from pathlib import Path

from integration.professional_intake_development import build_bundle as professional_foundation
from integration.professional_methods_development import build_bundle as methods_foundation
from integration.contractor_tender_development import _write, _write_launch_files
from integration.verify_tender_closed_loop import read
from src.actions.contracts.professional_monthly_methods import AggregateDesignPolicy
from src.coordination.tasks import task_digest


def build_bundle(directory, *, run_id, qs_accuracy, design_review):
    limits = AggregateDesignPolicy.model_validate(design_review).model_dump(mode='json')
    if type(qs_accuracy) not in (int, float) or not 0 <= qs_accuracy <= 1:
        raise ValueError('Initial QS accuracy must be a bounded native capability')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    professional = directory / 'professional-foundation'
    methods = directory / 'methods-foundation'
    professional_foundation(professional, run_id=run_id, with_owner=True,
        with_confirmation=True, with_opportunity=True)
    methods_foundation(methods, run_id=run_id, regulatory_pressure_index=0.2)
    settings = read(professional / 'assembly-host.json')['settings']
    authority = settings['authority']
    method_settings = read(methods / 'assembly-host.json')['settings']
    plans = read(methods / 'professional-methods-input.json')['plans']
    # A second actual Architect candidate keeps its own monthly route. Its
    # empty own-project observation is not another firm's design feedback.
    def peer(value):
        if isinstance(value, str): return value.replace('professional-architect', 'professional-architect-b')
        if isinstance(value, list): return [peer(v) for v in value]
        if isinstance(value, dict): return {k: peer(v) for k, v in value.items()}
        return value
    peers = []
    for original in plans:
        if original['role'] != 'Architect': continue
        copied = peer(original)
        clock = next(r for r in original['objects'] if r['ref']['kind'] == 'ClockProfile')
        copied['objects'] = [deepcopy(clock) if r['ref'] == clock['ref'] else r for r in copied['objects']]
        for basis in clock['value']['evidence_refs']:
            if not any(r['ref'] == basis for r in copied['objects']):
                copied['objects'].append(deepcopy(next(r for r in original['objects'] if r['ref'] == basis)))
        grant = next(r['value'] for r in copied['objects'] if r['ref'] in copied['context']['authorization_refs'])
        grant['readable_refs'] = [r['ref'] for r in copied['objects']]
        copied['context']['visible_refs'] = deepcopy(grant['readable_refs'])
        peers.append(copied)
    plans += peers
    organizations = {o['organization_id']: o for o in authority['organization_snapshot']['organizations']}
    for plan in plans:
        for row in plan['objects']:
            if row['ref']['kind'] == 'MonthlyMethodPolicy': row['value']['design_review'] = limits
        grant, = [r['value'] for r in plan['objects'] if r['ref'] in plan['context']['authorization_refs']]
        authority['organization_snapshot']['authorizations'].append(deepcopy(grant))
        assignment, = [r['value'] for r in plan['objects'] if r['ref'] == plan['context']['function_ref']]
        org = organizations[plan['organization_id']]
        if assignment not in org['assignments']: org['assignments'].append(deepcopy(assignment))
    immutable = {}
    for plan in plans:
        for row in plan['objects']:
            identity = (plan['role'], task_digest(row['ref']))
            digest = task_digest(row['value'])
            if identity in immutable and immutable[identity] != digest:
                raise ValueError('Scenario changes an immutable source within the original shared role assembler')
            immutable[identity] = digest
    sources = _write(directory, 'design-feedback-input.json',
        {'schema_version': 'professional-monthly-methods-input.v1', 'run_id': run_id, 'plans': plans})
    _write(directory, 'assembly-host.json', {'schema_version': 'gba-module-host-config.v1',
        'host_id': run_id, 'version': '1', 'settings': {'professional': settings,
            'monthly': {'authority': authority, **sources}}})
    native = read(professional / 'native-host.json')
    for field in ('native_proposals', 'native_decisions'):
        native['settings'][field] = [r for r in native['settings'][field]
            if not (r['role'] in {'Architect', 'Engineer'} and
                r.get('operation', r.get('decision_type')) in {'decide_monthly_operation', 'monthly_enterprise_operation'})]
    _write(directory, 'native-host.json', native)
    macro = read(professional / 'macro-request.json')
    # Original supported initial scenario input; no selected firms, events,
    # design results or decisions are prefilled.
    macro['initial_projects'] = macro['initial_projects'][:1]
    macro['macro_environment']['regulatory_pressure_index'] = 0.2
    for agent in macro['agents']:
        if agent['role'] == 'QS': agent['cost_estimation_capability'] = qs_accuracy
        if agent['role'] == 'Architect': agent['design_capability'] = 0.6
        if agent['role'] == 'Engineer': agent['technical_capability'] = 0.6
    _write(directory, 'macro-request.json', macro)
    _write_launch_files(directory, assembly_hook='integration.professional_design_feedback:configure_assembly', readme_override=__doc__)
