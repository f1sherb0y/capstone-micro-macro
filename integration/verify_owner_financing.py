"""Freeze OWN-A05 regressions and independently reconstruct funding sources."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree as ET

from integration.action_catalog import ROOT, write_new
from integration.coverage import coverage_report
from integration.owner_financing_oracle import source_oracle
from integration.verify_owner_commission import TEST_MODULES as COMMISSION_MODULES
from integration.verify_supplier import sha
from src.actions.contracts.catalog import ContractCatalog
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.methods.capacity import local_method_registry

TEST_MODULES = (*COMMISSION_MODULES, 'owner_financing', 'owner_financing_contracts', 'owner_financing_method')
CHECKS = {
    'CHECK-OWN-005': 'partial: insufficient cash and unavailable offers require declared adjustment, application, waiting or no financing; formal lender refusals and execution remain unbound',
    'CHECK-OWN-006': 'partial: local failure/rejection creates no financing state, old pinned offers are not substituted; final formal provider and submission feedback remain unbound',
    'CHECK-OWN-007': 'partial: exact lender/application/product/purpose/principal/tenor/pricing/fees/repayment/conditions/validity are source checked; formal independent confirmation remains unbound',
    'CHECK-OWN-039': 'partial: actual account counted once with restricted cash and complete original cross-project obligations; atomic formal competition/reservation remains unbound',
    'CHECK-OWN-065': 'partial: borrower-specific source separation, no copied account and no automatic currency conversion; actual inter-region and FX paths remain unsupported/unbound',
}
LIMITATIONS = [
    'All organizations, accounts, offers, fixed schedules, approvals and ordinal priorities are explicitly synthetic',
    'Single currency and clock, source-separated full-draw fixed schedules; no real bank/finance/jurisdiction calibration',
    'No floating-rate prediction, automatic FX, unregistered inter-region transfer, rolling credit or partial draw method',
    'A completed decision creates no application, arrangement, counterparty acceptance, principal, cash, payment, reservation or receipt',
    'Actual producers, application registration, independent Bank A02/A05 processing, arrangement submit/query and feedback recovery remain unbound',
]


def run_tests(output, workers):
    commands = [[sys.executable, '-m', 'pytest', *[f'tests/test_{name}.py' for name in TEST_MODULES[i::workers]],
        '-q', '--disable-warnings', '-o', 'faulthandler_timeout=60', f'--junitxml={output / f"tests-worker-{i}.xml"}'] for i in range(workers)]

    def worker(i):
        with (output / f'tests-worker-{i}.log').open('x', encoding='utf-8') as stream:
            status = subprocess.run(commands[i], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        print(f'Worker {i} finished: {status.returncode}', flush=True)
        return status.returncode

    with ThreadPoolExecutor(max_workers=workers) as executor:
        statuses = list(executor.map(worker, range(workers)))
    combined = ET.Element('testsuites')
    for i in range(workers):
        combined.extend(ET.parse(output / f'tests-worker-{i}.xml').getroot().findall('testsuite'))
    ET.ElementTree(combined).write(output / 'tests.xml', encoding='utf-8', xml_declaration=True)
    (output / 'tests.log').write_text('\n'.join((output / f'tests-worker-{i}.log').read_text() for i in range(workers)), encoding='utf-8')
    totals = {key: sum(int(s.get(key, '0')) for s in combined) for key in ('tests', 'failures', 'errors', 'skipped')}
    keys = {(row.get('classname'), row.get('name')) for row in combined.findall('.//testcase')}
    counts = {name: sum(module == f'tests.test_{name}' for module, _ in keys)
              for name in ('owner_financing', 'owner_financing_contracts', 'owner_financing_method')}
    if (any(statuses) or len(keys) != totals['tests'] or any(totals[k] for k in ('failures', 'errors', 'skipped'))
            or counts['owner_financing'] < 85 or counts['owner_financing_method'] < 18 or counts['owner_financing_contracts'] < 29):
        raise ValueError(f'Incomplete funding/shared regression: {totals}, {counts}; preserve this output')
    return totals, len(keys), commands, counts


def replay_cases():
    from tests.test_owner_financing import facts, policy, balance, named, known, ref, point, unknown, sync_lines
    cases = []
    for choice in ('own_funds', 'apply', 'accept_offer', 'negotiate', 'resize', 'no_finance'):
        data = facts()
        policy(data, choice)
        cases.append((choice, data, 'completed', choice))
    for label in ('first_apply', 'no_bank_cash_shortage', 'finance_cash_shortage', 'earlier_payment', 'overdue_payment',
                  'received_not_added', 'forecast_not_added', 'cancelled_not_added', 'restricted_cash', 'expired_reselect',
                  'pinned_expired', 'withdrawn_reselect', 'over_cost_cap', 'priority_tie', 'infeasible_apply',
                  'infeasible_resize', 'infeasible_defer', 'explicit_defer'):
        data = facts()
        profile = named(data, 'FundingProfile')
        expected, choice = 'completed', 'no_finance'
        if label == 'first_apply':
            policy(data, 'apply'); data['input']['offers'] = []; choice = 'apply'
        elif label in {'no_bank_cash_shortage', 'finance_cash_shortage', 'earlier_payment', 'overdue_payment'}:
            balance(data, 5)
            if label == 'no_bank_cash_shortage': data['input']['offers'] = []
            elif label == 'finance_cash_shortage': choice = 'accept_offer'
            elif label == 'earlier_payment': named(data, 'Obligation')['due_at'] = point(11)
            else: named(data, 'Obligation')['due_at'] = point(8)
        elif label.endswith('_not_added'):
            balance(data, 5)
            named(data, 'FundingSource')['releases'][0]['state'] = label.split('_')[0]
        elif label == 'restricted_cash':
            policy(data, 'own_funds'); balance(data, 100, 90)
        elif label in {'expired_reselect', 'pinned_expired', 'withdrawn_reselect', 'over_cost_cap', 'priority_tie'}:
            policy(data, 'accept_offer')
            if label in {'expired_reselect', 'pinned_expired'}:
                named(data, 'FinanceOffer', 'primary')['effective_window']['end']['offset'] = 10
                if label == 'pinned_expired': profile['selected_offer_ref'] = ref('FinanceOffer', 'primary')
                else: choice = 'accept_offer'
            elif label == 'withdrawn_reselect':
                named(data, 'FinanceOffer', 'primary')['status'] = 'withdrawn'; choice = 'accept_offer'
            elif label == 'over_cost_cap':
                named(data, 'PricingRule', 'primary-interest')['schedule']['value'][0]['amount']['value'] = '9'; choice = 'accept_offer'
            else:
                named(data, 'FinanceOffer', 'secondary')['priority'] = known(1); expected, choice = 'needs_information', None
        elif label.startswith('infeasible_'):
            policy(data, 'own_funds'); balance(data, 25)
            fallback = label.split('_')[1]
            profile['on_unavailable'] = known(fallback)
            expected, choice = ('deferred', None) if fallback == 'defer' else ('completed', fallback)
        else:
            policy(data, 'defer'); expected, choice = 'deferred', None
        cases.append((label, data, expected, choice))
    for choice, total, expected in [('own_funds', 100, 'own_funds'), ('own_funds', 5, 'no_finance'),
                                   ('accept_offer', 100, 'accept_offer'), ('resize', 100, 'resize')]:
        data = facts()
        policy(data, choice)
        balance(data, total)
        named(data, 'FundingProfile')['funding_lines'][0]['available'] = unknown()
        named(data, 'FundingPlan')['revised_lines'][0]['available'] = unknown()
        sync_lines(data)
        cases.append((f'unknown_forecast_{choice}_{total}', data, 'completed', expected))
    return cases


def verify(output, workers=4):
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists() or not 1 <= workers <= 8:
        raise ValueError('Use a new repository output directory and 1-8 workers')
    baseline = ROOT / 'output/integration/plan_20261002_implementation/baseline.json'
    protected = json.loads(baseline.read_text())['protected_hashes']
    paths = {p for directory in ('src', 'integration', 'tests', 'skills', 'config') for p in (ROOT / directory).rglob('*')
             if p.is_file() and p.suffix in {'.py', '.md', '.json', '.yaml', '.yml'}}
    paths.update(ROOT / name for name in ('pyproject.toml', 'uv.lock'))
    code_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    if any(sha(ROOT / name) != digest for name, digest in protected.items()):
        raise ValueError('Protected source changed before verification')
    output.mkdir(parents=True)
    write_new(output / 'freeze.json', {'code_hashes': code_hashes, 'protected_hashes': protected})
    print('Running frozen funding and shared regression', flush=True)
    totals, unique_tests, commands, counts = run_tests(output, workers)
    from tests.test_owner_financing import build_run
    catalogue = ContractCatalog()
    registry = register_representative_processors(ActionRegistry(catalog=catalogue))
    methods = local_method_registry()
    runtime, inputs, oracles = [], [], []
    print('Replaying funding choices against independent source arithmetic', flush=True)
    for label, data, expected_kind, expected_choice in replay_cases():
        run = build_run(data, catalog=catalogue, run_id=f'{output.name}:{label}')
        before = deepcopy(run.objects)
        result = run.execute()
        if result.kind != expected_kind or expected_choice is not None and result.payload.choice != expected_choice:
            raise ValueError(f'Unexpected {label}: {result}')
        if run.objects != before:
            raise ValueError('A local funding decision changed source state')
        audit = run.runner.audit_records[-1].as_dict()
        if audit['method_registry_digest'] != methods.content_digest or any(c['registry_digest'] != methods.content_digest for c in audit['method_calls']):
            raise ValueError('Method snapshot changed or was omitted from audit')
        oracles.append({'label': label, 'oracle': source_oracle(data, result, audit, before)})
        inputs.append({'label': label, 'origin': 'synthetic', 'context': run.context.model_dump(mode='json'), 'input': run.input, 'projections': before})
        runtime.append({'label': label, 'result': result.model_dump(mode='json'), 'audit': audit, 'formal_submission': None, 'macro_receipt': None})
    inventory = json.loads((ROOT / 'config/action_registry.json').read_text())
    coverage = json.loads((ROOT / '宏微观衔接方案/新版方案/action_coverage.json').read_text())
    record = next(row for row in coverage['actions'] if row['action_id'] == 'OWN-A05')
    skill = registry.get('OWN-A05').skill.manifest
    branches = {row['result']['payload']['choice'] for row in runtime if row['result']['kind'] == 'completed'}
    if branches != set(catalogue.get('OWN-A05').choices):
        raise ValueError('Incomplete source branch replay')
    record.update(decision='partial_local_verified', method='partial_local_verified', validation='partial_local_verified',
        binding='unverified', feedback='pending', branches={choice: 'partial_local_verified' for choice in sorted(branches)},
        local_processor={'processor_id': skill.processor_id, 'code': 'src/actions/roles/owner_financing.py',
                         'scope': 'Authorized synthetic funding decisions only; no formal financing or cash effects'},
        local_methods={'code': 'src/methods/owner_financing.py', 'registry_status': 'registered_host_method',
                       'registry_digest': methods.content_digest, 'support': 'Exact source-separated cash calendars and declared full-draw cost/ordinal selection',
                       'calibration': 'mathematical_only'},
        gaps=[{'kind': 'formal_binding', 'detail': 'Actual funding input producers, application registration, independent Bank A02/A05, arrangement submit/query remain unbound'},
              {'kind': 'feedback_recovery', 'detail': 'Formal independent acceptance, principal, cash, payment, receipt and feedback recovery remain unbound'},
              {'kind': 'real_method_calibration', 'detail': 'Bank schedules, approved releases, source preferences and currency/region paths are synthetic or unsupported'}])
    record['evidence'] = list(dict.fromkeys([*record['evidence'], (output / 'manifest.json').relative_to(ROOT).as_posix()]))
    artifacts = {'runtime.json': runtime, 'inputs.json': inputs, 'source_oracle.json': oracles,
        'methods.json': {'registry_digest': methods.content_digest, 'catalog': methods.catalog()},
        'coverage_record.json': record, 'coverage.json': coverage_report(inventory, coverage), 'skill_audit.json': registry.skill_audit(),
        'binding.json': {'action_id': 'OWN-A05', 'status': 'not_bound', 'macro_receipt': None, 'limitations': LIMITATIONS},
        'checks.json': {'tests': totals, 'unique_tests': unique_tests, 'test_commands': commands, 'source_checks': CHECKS,
                        'formal_receipts': 0, 'model_calls': 0, 'runtime_cases': len(runtime)}}
    for name, value in artifacts.items():
        write_new(output / name, value)
    check = subprocess.run([sys.executable, '-m', 'integration.action_catalog', '--check'], cwd=ROOT, capture_output=True, text=True)
    if check.returncode:
        raise ValueError(check.stdout + check.stderr)
    names = ['src/actions/contracts/owner_financing_objects.py', 'src/actions/roles/owner_financing.py',
        'src/actions/processors.py', 'src/actions/contracts/role_rules.py', 'src/methods/capacity.py',
        'src/methods/owner_financing.py', 'src/methods/OWNER_FINANCING.md', 'skills/actions/owner/OWN-A05/SKILL.md',
        'skills/actions/owner/OWN-A05/manifest.json', 'tests/fixtures/roles/owner_financing.v1.json',
        'integration/owner_financing_oracle.py', 'integration/verify_owner_financing.py', *[f'tests/test_{m}.py' for m in TEST_MODULES]]
    for name in names:
        checked = subprocess.run(['git', '-c', 'core.whitespace=cr-at-eol', 'diff', '--no-index', '--check', '/dev/null', name], cwd=ROOT, capture_output=True, text=True)
        if checked.stdout or checked.stderr or checked.returncode not in (0, 1):
            raise ValueError(f'Whitespace: {name}: {checked.stdout}{checked.stderr}')
    if any(sha(ROOT / name) != digest for name, digest in {**code_hashes, **protected}.items()):
        raise ValueError('Frozen source changed; preserve this run and use a fresh directory')
    write_new(output / 'manifest.json', {'schema_version': 'plan-owner-financing-evidence.v1', 'action_id': 'OWN-A05',
        'evidence_id': output.name, 'recorded_at': datetime.now(timezone.utc).isoformat(), 'status': 'partial_local_verified',
        'source_sha256': catalogue.get('OWN-A05').source_sha256, 'processor_id': skill.processor_id, 'skill_version': skill.skill_version,
        'method_registry_digest': methods.content_digest, 'tests': totals, 'unique_tests': unique_tests, 'test_counts': counts,
        'code_hashes': code_hashes, 'runtime_cases': len(runtime), 'branches': sorted(branches), 'checks': CHECKS,
        'protected': {'baseline': baseline.relative_to(ROOT).as_posix(), 'files': len(protected), 'unchanged': True},
        'artifact_hashes': {name: sha(output / name) for name in [*artifacts, 'freeze.json', 'tests.xml', 'tests.log',
            *[f'tests-worker-{i}.{suffix}' for i in range(workers) for suffix in ('xml', 'log')]]},
        'limitations': LIMITATIONS, 'environment': {'python': sys.version, 'packages': {name: version(name) for name in ('pytest', 'pydantic', 'lark')}}})
    print(json.dumps({'output': str(output), 'tests': totals, 'unique_tests': unique_tests, 'runtime_cases': len(runtime)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    verify(args.output, args.workers)
