"""Freeze BANK-A03 regressions and reconstruct review decisions from raw sources."""
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
from integration.bank_credit_oracle import source_oracle
from integration.coverage import coverage_report
from integration.verify_owner_financing import TEST_MODULES as FINANCING_MODULES
from integration.verify_supplier import sha
from src.actions.contracts.catalog import ContractCatalog
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.methods.bank_credit import CREDIT_RISK_METHOD, CreditRiskInput, CreditRiskReport
from src.methods.capacity import local_method_registry
from src.methods.registry import MethodRegistry


TEST_MODULES = (*FINANCING_MODULES, 'bank_credit', 'bank_credit_contracts', 'bank_credit_method', 'bank_credit_oracle')
CHECKS = {
    'CHECK-BANK-015': 'partial: complete condition graphs retain cyclic/unknown blockers and responsible parties; formal condition resolution and approvals unbound',
    'CHECK-BANK-017': 'partial: material unknowns request information, unsupported/outage distinct from business refusal; assembler rejects private input and nested reads cannot expand authority',
    'CHECK-BANK-022': 'partial: owner funding and bank requirement cycle exposed as specific sourced requirements and responsible parties; no waiver, promise or commitment fabricated',
    'CHECK-BANK-045': 'partial: original shared borrower cash/debt and one complete visible bank occupancy bound reused across regions; atomic formal competition and private other-bank access remain unbound',
}
LIMITATIONS = [
    'All institutions, account balances, disclosed debt, bank capacity, paths, risk thresholds and cash assumptions are explicitly synthetic',
    'One currency and clock; conservative interval ordinary flows and explicitly complete unit-principal draw/repay/cost schedules',
    'Mathematical interval intersection only; no real credit calibration, floating rates, revolving/partial credit or implicit FX',
    'Completed is a bank review opinion, never approval, quote, commitment, reservation, arrangement, principal, cash, payment or receipt',
    'Actual authorized producers, formal professional review task/resource registration, submit/query and feedback recovery remain unbound',
    'Current visible bank occupancy limits an indicative range; final atomic capacity competition must be rechecked at formal commitment submission',
]


def replay_cases():
    from tests.test_bank_credit import facts, known, ref, unknown, view
    cases = []
    for label in ('recommend', 'condition_unknown', 'condition_unsatisfied', 'cycle', 'hard_decline', 'cash_decline',
                  'hard_unknown', 'straddling', 'nonhard_unknown', 'cash_unknown', 'missing_debt', 'partial_debt',
                  'partial_portfolio', 'unknown_flow', 'partial_forecast', 'unsupported_risk', 'unsupported_currency',
                  'wrong_verifier', 'stale_account', 'withdrawn', 'capacity_limited', 'capacity_exhausted',
                  'capacity_unknown', 'occupancy_unknown', 'released_occupancy', 'other_region', 'overdue',
                  'no_method', 'method_outage'):
        data = facts()
        kind, choice, methods = 'completed', 'recommend', 'default'
        if label in {'condition_unknown', 'condition_unsatisfied'}:
            condition = view(data, 'Requirement')
            condition['outcome'] = unknown() if label == 'condition_unknown' else known('unsatisfied')
            if label == 'condition_unknown': condition['verification'] = None
            choice = 'conditional'
        elif label == 'cycle':
            first = view(data, 'Requirement')
            second = deepcopy(next(row for row in data['objects'] if row['ref']['kind'] == 'Requirement'))
            second['ref'] = second['value']['ref'] = ref('Requirement', 'owner-funding-dependency')
            first['dependency_refs'] = [second['ref']]
            first['responsible_id'] = data['organization_id']
            second['value']['dependency_refs'] = [first['ref']]
            data['objects'].append(second)
            choice = 'conditional'
        elif label == 'hard_decline':
            interval = view(data, 'RiskObservation')['interval']['value']
            interval['lower']['value'] = interval['upper']['value'] = '6'; choice = 'decline'
        elif label == 'cash_decline':
            view(data, 'FinancialForecast')['flows'][1]['amount']['value']['lower']['value'] = '0'; choice = 'decline'
        elif label in {'hard_unknown', 'straddling', 'nonhard_unknown'}:
            observation = view(data, 'RiskObservation')
            if label == 'straddling': observation['interval']['value']['upper']['value'] = '6'
            else: observation['interval'] = unknown()
            if label == 'nonhard_unknown': view(data, 'RiskDimension')['hard'] = False; choice = 'conditional'
            else: kind, choice = 'needs_information', None
        elif label in {'cash_unknown', 'missing_debt', 'partial_debt', 'partial_portfolio', 'unknown_flow', 'partial_forecast',
                       'wrong_verifier', 'stale_account', 'capacity_unknown', 'occupancy_unknown'}:
            kind, choice = 'needs_information', None
            if label == 'cash_unknown': view(data, 'Account')['actual_cash'] = unknown()
            elif label == 'missing_debt': data['input']['debt_refs'] = []
            elif label == 'partial_debt': view(data, 'Debt')['coverage'] = 'partial'
            elif label == 'partial_portfolio': view(data, 'BorrowerPortfolio')['coverage'] = 'partial'
            elif label == 'unknown_flow': view(data, 'FinancialForecast')['flows'][0]['amount'] = unknown()
            elif label == 'partial_forecast': view(data, 'FinancialForecast')['coverage'] = 'partial'
            elif label == 'wrong_verifier': view(data, 'Requirement')['authorized_verifier_organization_ids'] = known(['another-org'])
            elif label == 'capacity_unknown': view(data, 'LendingCapacity')['commitment_limit'] = unknown()
            elif label == 'occupancy_unknown': view(data, 'FinanceCommitment')['amount'] = unknown()
            else: view(data, 'Account')['as_of']['offset'] = 1
        elif label in {'unsupported_risk', 'unsupported_currency'}:
            kind, choice = 'unsupported', None
            if label == 'unsupported_currency': view(data, 'FinanceFeasibilityMethod')['currency'] = 'USD'
            else: view(data, 'RiskObservation')['interval'] = {'state': 'not_supported', 'capability_ref': ref('Capability', 'risk-domain')}
        elif label == 'withdrawn': view(data, 'FinanceApplication')['status'] = 'withdrawn'; choice = 'decline'
        elif label in {'capacity_limited', 'capacity_exhausted', 'released_occupancy'}:
            view(data, 'LendingCapacity')['commitment_limit']['value']['value'] = {
                'capacity_limited': '260', 'capacity_exhausted': '200', 'released_occupancy': '60'}[label]
            if label == 'capacity_exhausted': choice = 'decline'
            elif label == 'released_occupancy':
                row = view(data, 'FinanceCommitment'); row['status'] = 'released'; row['release_evidence_ref'] = ref('Evidence', 'synthetic-basis')
        elif label == 'other_region':
            view(data, 'FundingPurpose')['project_region_id'] = known('SZ')
            view(data, 'FinanceProductProfile')['allowed_project_region_ids'] = known(['HK', 'SZ'])
        elif label == 'overdue':
            for object_kind in ('DebtComponent', 'Obligation'):
                view(data, object_kind)['due_at']['offset'] = 1
                view(data, object_kind)['actual_due']['value']['value'] = '25'
            choice = 'decline'
        elif label == 'no_method': methods, kind, choice = 'empty', 'unsupported', None
        elif label == 'method_outage': methods, kind, choice = 'outage', 'technical_error', None
        cases.append((label, data, kind, choice, methods))
    return cases


def host_methods(mode):
    if mode == 'default': return local_method_registry()
    registry = MethodRegistry()
    if mode == 'empty': return registry
    if mode != 'outage': raise ValueError('Unknown verification host mode')
    from tests.test_bank_credit import failed_credit_model
    definition = next(row['definition'] for row in local_method_registry().catalog()
                      if row['definition']['method_ref']['id'] == CREDIT_RISK_METHOD.id)
    registry.register(definition, CreditRiskInput, CreditRiskReport, failed_credit_model)
    return registry


def run_tests(output, workers):
    commands = [[sys.executable, '-m', 'pytest', *[f'tests/test_{name}.py' for name in TEST_MODULES[i::workers]],
        '-q', '--disable-warnings', '-o', 'faulthandler_timeout=60', f'--junitxml={output / f"tests-worker-{i}.xml"}']
        for i in range(workers)]
    def worker(i):
        with (output / f'tests-worker-{i}.log').open('x') as stream:
            status = subprocess.run(commands[i], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        print(f'Worker {i}: {status.returncode}', flush=True)
        return status.returncode
    with ThreadPoolExecutor(max_workers=workers) as executor:
        statuses = list(executor.map(worker, range(workers)))
    combined = ET.Element('testsuites')
    for i in range(workers):
        combined.extend(ET.parse(output / f'tests-worker-{i}.xml').getroot().findall('testsuite'))
    ET.ElementTree(combined).write(output / 'tests.xml', encoding='utf-8', xml_declaration=True)
    (output / 'tests.log').write_text('\n'.join((output / f'tests-worker-{i}.log').read_text() for i in range(workers)))
    totals = {key: sum(int(s.get(key, '0')) for s in combined) for key in ('tests', 'failures', 'errors', 'skipped')}
    keys = {(row.get('classname'), row.get('name')) for row in combined.findall('.//testcase')}
    counts = {name: sum(module == f'tests.test_{name}' for module, _ in keys)
              for name in ('bank_credit', 'bank_credit_contracts', 'bank_credit_method', 'bank_credit_oracle')}
    if (any(statuses) or len(keys) != totals['tests'] or any(totals[k] for k in ('failures', 'errors', 'skipped'))
            or any(counts[name] < minimum for name, minimum in zip(counts, (69, 37, 32, 51)))):
        raise ValueError(f'Incomplete credit/shared regression: {totals}, {counts}; preserve this output')
    return totals, len(keys), counts, commands


def verify(output, workers=4):
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists() or not 1 <= workers <= 8:
        raise ValueError('Use a new repository output directory and 1-8 workers')
    baseline = ROOT / 'output/integration/plan_20261002_implementation/baseline.json'
    protected = json.loads(baseline.read_text())['protected_hashes']
    paths = {p for directory in ('src', 'integration', 'tests', 'skills', 'config') for p in (ROOT / directory).rglob('*')
             if p.is_file() and p.suffix in {'.py', '.md', '.json', '.yaml', '.yml'}}
    paths.update(ROOT / name for name in ('pyproject.toml', 'uv.lock'))
    frozen = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    if any(sha(ROOT / name) != digest for name, digest in protected.items()): raise ValueError('Protected source changed')
    output.mkdir(parents=True)
    write_new(output / 'freeze.json', {'code_hashes': frozen, 'protected_hashes': protected})
    print('Running frozen credit and shared regression', flush=True)
    totals, unique, counts, commands = run_tests(output, workers)
    from tests.test_bank_credit import build_credit_run
    catalog = ContractCatalog()
    registry = register_representative_processors(ActionRegistry(catalog=catalog))
    runtime, inputs, oracles, method_runs = [], [], [], []
    print('Replaying bank review branches and independent source oracle', flush=True)
    for label, data, expected_kind, expected_choice, mode in replay_cases():
        methods = host_methods(mode)
        run = build_credit_run(data, catalog=catalog, run_id=f'{output.name}:{label}', methods=methods)
        before = deepcopy(run.objects)
        result = run.execute()
        if result.kind != expected_kind or expected_choice is not None and result.payload.choice != expected_choice:
            raise ValueError(f'Unexpected source replay {label}: {result}')
        if run.objects != before: raise ValueError('Credit review changed source state')
        audit = run.runner.audit_records[-1].as_dict()
        if audit['method_registry_digest'] != methods.content_digest or any(
                call['registry_digest'] != methods.content_digest for call in audit['method_calls']):
            raise ValueError('Host method registry omitted or changed')
        oracles.append({'label': label, 'oracle': source_oracle(data, result, audit, before,
            method_catalog=methods.catalog(), method_failures=[CREDIT_RISK_METHOD.model_dump(mode='json')] if mode == 'outage' else [])})
        inputs.append({'label': label, 'origin': 'synthetic', 'context': run.context.model_dump(mode='json'),
                       'input': run.input, 'projections': before})
        runtime.append({'label': label, 'result': result.model_dump(mode='json'), 'audit': audit,
                        'formal_submission': None, 'macro_receipt': None})
        method_runs.append({'label': label, 'host_mode': mode, 'registry_digest': methods.content_digest, 'catalog': methods.catalog()})
    branches = {row['result']['payload']['choice'] for row in runtime if row['result']['kind'] == 'completed'}
    if branches != set(catalog.get('BANK-A03').choices): raise ValueError('Incomplete bank source branches')
    coverage = json.loads((ROOT / '宏微观衔接方案/新版方案/action_coverage.json').read_text())
    record = next(row for row in coverage['actions'] if row['action_id'] == 'BANK-A03')
    skill = registry.get('BANK-A03').skill.manifest
    methods = local_method_registry()
    record.update(decision='partial_local_verified', method='partial_local_verified', validation='partial_local_verified',
        binding='unverified', feedback='pending', branches={choice: 'partial_local_verified' for choice in sorted(branches)},
        local_processor={'processor_id': skill.processor_id, 'code': 'src/actions/roles/bank_credit.py',
                         'scope': 'Authorized synthetic bank review opinions only; no formal loan or approval effects'},
        local_methods={'code': 'src/methods/bank_credit.py', 'registry_status': 'registered_host_method',
            'registry_digest': methods.content_digest, 'support': 'Exact per-dimension risk and original-account indicative interval bounds; current visible bank occupancy',
            'calibration': 'mathematical_only'},
        gaps=[{'kind': 'formal_binding', 'detail': 'Actual producers, professional work/resource registration, approval/commitment submit/query and final capacity competition remain unbound'},
              {'kind': 'feedback_recovery', 'detail': 'Formal review task/results, receipts and feedback recovery remain unbound'},
              {'kind': 'real_method_calibration', 'detail': 'Thresholds, complete disclosures, account paths, bank limits, loan factors and forecasts are synthetic'}])
    record['evidence'] = list(dict.fromkeys([*record['evidence'], (output / 'manifest.json').relative_to(ROOT).as_posix()]))
    inventory = json.loads((ROOT / 'config/action_registry.json').read_text())
    artifacts = {'runtime.json': runtime, 'inputs.json': inputs, 'source_oracle.json': oracles,
        'methods.json': {'registry_digest': methods.content_digest, 'catalog': methods.catalog(), 'run_hosts': method_runs},
        'coverage_record.json': record, 'coverage.json': coverage_report(inventory, coverage), 'skill_audit.json': registry.skill_audit(),
        'binding.json': {'action_id': 'BANK-A03', 'status': 'not_bound', 'macro_receipt': None, 'limitations': LIMITATIONS},
        'checks.json': {'tests': totals, 'unique_tests': unique, 'test_counts': counts, 'commands': commands,
                       'source_checks': CHECKS, 'formal_receipts': 0, 'model_calls': 0, 'runtime_cases': len(runtime)}}
    for name, value in artifacts.items(): write_new(output / name, value)
    check = subprocess.run([sys.executable, '-m', 'integration.action_catalog', '--check'], cwd=ROOT, capture_output=True, text=True)
    (output / 'catalog.log').write_text(check.stdout + check.stderr)
    if check.returncode: raise ValueError('Catalog verification failed')
    names = ['src/actions/contracts/bank_credit_objects.py', 'src/actions/roles/bank_credit.py',
        'src/methods/bank_credit.py', 'src/methods/BANK_CREDIT.md', 'src/methods/capacity.py',
        'src/actions/contracts/role_rules.py', 'src/actions/processors.py', 'skills/actions/bank/BANK-A03/SKILL.md',
        'skills/actions/bank/BANK-A03/manifest.json', 'tests/fixtures/roles/bank_credit.v1.json',
        'integration/bank_credit_oracle.py', 'integration/verify_bank_credit.py', 'tests/test_methods.py',
        'tests/test_action_runtime_boundaries.py', *[f'tests/test_{name}.py' for name in TEST_MODULES]]
    for name in names:
        checked = subprocess.run(['git', '-c', 'core.whitespace=cr-at-eol', 'diff', '--no-index', '--check', '/dev/null', name],
                                 cwd=ROOT, capture_output=True, text=True)
        if checked.stdout or checked.stderr or checked.returncode not in (0, 1): raise ValueError(f'Whitespace: {name}')
    if any(sha(ROOT / name) != digest for name, digest in {**frozen, **protected}.items()):
        raise ValueError('Frozen source changed; preserve this run and use a new output')
    write_new(output / 'manifest.json', {'schema_version': 'plan-bank-credit-evidence.v1', 'action_id': 'BANK-A03',
        'evidence_id': output.name, 'status': 'partial_local_verified', 'recorded_at': datetime.now(timezone.utc).isoformat(),
        'source_sha256': catalog.get('BANK-A03').source_sha256, 'processor_id': skill.processor_id,
        'skill_version': skill.skill_version, 'method_registry_digest': methods.content_digest, 'tests': totals,
        'unique_tests': unique, 'test_counts': counts, 'runtime_cases': len(runtime), 'branches': sorted(branches),
        'code_hashes': frozen, 'checks': CHECKS, 'protected': {'baseline': baseline.relative_to(ROOT).as_posix(),
        'files': len(protected), 'unchanged': True}, 'artifact_hashes': {name: sha(output / name) for name in
        [*artifacts, 'freeze.json', 'tests.xml', 'tests.log', 'catalog.log', *[f'tests-worker-{i}.{suffix}'
            for i in range(workers) for suffix in ('xml', 'log')]]}, 'limitations': LIMITATIONS,
        'environment': {'python': sys.version, 'packages': {name: version(name) for name in ('pytest', 'pydantic', 'lark')}}})
    print(json.dumps({'output': str(output), 'tests': totals, 'unique_tests': unique, 'runtime_cases': len(runtime)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    verify(args.output, args.workers)
