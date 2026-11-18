"""Freeze and independently replay the local OWN-A03 investment boundary."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

from integration.action_catalog import ROOT, write_new
from integration.coverage import coverage_report
from integration.verify_supplier import sha
from integration.verify_owner_study import TEST_MODULES as STUDY_TEST_MODULES
from src.actions.contracts.catalog import ContractCatalog
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.methods.capacity import local_method_registry

TEST_MODULES = (*STUDY_TEST_MODULES, "owner_investment", "owner_investment_methods")
CHECKS = {
    "CHECK-OWN-004": "partial: existing shared-project debt competes with proposed cash uses and account openings are counted once; formal atomic submission and commitment competition remain unverified",
    "CHECK-OWN-019": "partial: investment_return, own_use and public_service templates are checked with explicit criteria; real demand and outcome calibration remain unbound",
    "CHECK-OWN-030": "partial: exact case/brief/analysis versions and conservative intervals are enforced; formal professional producer binding remains unverified",
    "CHECK-OWN-032": "partial: hard unmet/unknown rights and registration conditions prevent investment while allowing bounded preparation; formal permit binding remains unverified",
    "CHECK-OWN-038": "partial: exact source-separated cash calendar retains debts, restrictions, timing and conditional releases; formal finance ledger binding remains unverified",
    "CHECK-OWN-055": "partial: public budget is an independent public_service investment gate; formal public authorization and budget receipt remain unbound",
}
LIMITATIONS = [
    "All source records are explicitly synthetic and use one declared clock/currency; no real financial, professional, public-budget or outcome calibration",
    "The local decision creates no project, contract, loan, receipt, permit, payment, reservation, resource commitment or non-build transaction entry",
    "Actual producers, registration/transaction submit/query, formal finance ledger, independent acceptance, feedback and recovery remain unbound",
]


def _run_tests(output: Path, workers: int):
    xml = output / "tests.xml"
    log = output / "tests.log"
    commands = [[sys.executable, "-m", "pytest", *[f"tests/test_{m}.py" for m in TEST_MODULES[index::workers]], "-q", "--disable-warnings",
               "-o", "faulthandler_timeout=60", f"--junitxml={output / f'tests-worker-{index}.xml'}"] for index in range(workers)]
    def worker(index):
        with (output / f"tests-worker-{index}.log").open('x', encoding='utf-8') as stream:
            result = subprocess.run(commands[index], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        print(f"Worker {index} finished: {result.returncode}", flush=True)
        return result.returncode
    with ThreadPoolExecutor(max_workers=workers) as executor:
        returncodes = list(executor.map(worker, range(workers)))
    root = ElementTree.Element('testsuites')
    for index in range(workers): root.extend(ElementTree.parse(output / f"tests-worker-{index}.xml").getroot().findall('testsuite'))
    ElementTree.ElementTree(root).write(xml, encoding='utf-8', xml_declaration=True)
    log.write_text('\n'.join((output / f"tests-worker-{index}.log").read_text(encoding='utf-8') for index in range(workers)), encoding='utf-8')
    suites = root.findall(".//testsuite")
    totals = {key: sum(int(row.get(key, "0")) for row in suites) for key in ("tests", "failures", "errors", "skipped")}
    tests = {(row.get("classname"), row.get("name")) for row in root.findall(".//testcase")}
    role_count = sum(module == 'tests.test_owner_investment' for module, _ in tests)
    method_count = sum(module == 'tests.test_owner_investment_methods' for module, _ in tests)
    if any(returncodes) or len(tests) != totals["tests"] or role_count < 120 or method_count < 29 or any(totals[k] for k in ("failures", "errors", "skipped")):
        raise RuntimeError(f"incomplete regression: {totals}")
    return totals, len(tests), commands, role_count, method_count


def _source_oracle(data, result, audit, projections):
    """Recompute source scores, cash endpoints and physical segments without methods."""
    def key(ref): return ref['kind'], ref['id'], ref['version']
    source = {key(row['ref']): row['value'] for row in projections}
    def get(ref): return source[key(ref)]
    def check(test, message):
        if not test: raise ValueError(message)
    def number(row): return Fraction(row['value'])
    def in_window(window, tick): return window['start']['offset'] <= tick < window['end']['offset']
    check(all(get(row['ref']) == row['value'] for row in data['objects']), 'Received projection differs from frozen source')
    now = data['business_time']['offset']
    portfolio = get(data['input']['portfolio_ref'])
    objective = get(data['input']['objective_ref'])
    comparison = get(data['input']['comparison_ref'])
    profiles = get(data['input']['registration_profile_ref'])
    criteria = objective['criteria'].get('value')
    score_calls = [c for c in audit['method_calls'] if c['method_ref']['id'] == 'micro.owner.declared_option_intervals']
    scores = {}
    for call in score_calls:
        check(call['input']['criteria'] == criteria, 'Method changes objective criteria')
        expected = {}
        for option in call['input']['options']:
            raw_option = get(option['option_ref'])
            metrics = {m['code']: m['value']['value'] for a in raw_option['analysis_refs'] for m in get(a)['metrics']}
            check({m['code']: {'lower': m['lower'], 'upper': m['upper']} for m in option['metrics']} == metrics,
                  'Comparison method changes professional forecast source')
            low, high = Fraction(), Fraction()
            for criterion in criteria:
                metric = metrics[criterion['code']]
                a, b = number(metric['lower']), number(metric['upper'])
                if criterion['direction'] == 'minimize': a, b = -b, -a
                factor = Fraction(criterion['weight']) / number(criterion['scale'])
                low += a * factor; high += b * factor
            expected[key(option['option_ref'])] = (low, high)
        report = call['result']['value']
        for row in report['scores']:
            actual = tuple(Fraction(row[field]['numerator'], row[field]['denominator']) for field in ('conservative', 'optimistic'))
            check(actual == expected[key(row['option_ref'])], 'Conservative or optimistic score differs from source oracle')
        best = max(value[0] for value in expected.values())
        check({key(r) for r in report['preferred_refs']} == {k for k,v in expected.items() if v[0] == best}, 'Score preference differs')
        scores.update(expected)
    cash_checks, capacity_checks = [], []
    for call in audit['method_calls']:
        if call['method_ref']['id'] != 'micro.owner.declared_cash_calendar': continue
        supplied = call['input']
        plan = get(next(r for r in supplied['source_refs'] if r['kind'] == 'InvestmentPlan'))
        accounts = {key(r['source_ref']): number(r['opening_available']) for r in supplied['accounts']}
        check(accounts == {key(r): number(get(r)['actual_cash']['value']) - number(get(r)['restricted_cash']['value']) for r in portfolio['source_refs']},
              'Cash calculation changes account balances or duplicates sources')
        debts = {}
        for r in portfolio['obligation_refs']:
            debt = get(r)
            outstanding = number(debt['actual_due']['value']) - number(debt['actual_paid']['value'])
            if outstanding: debts['debt:'+r['id']] = (key(debt['source_ref']), max(now,debt['due_at']['offset']), outstanding)
        actual_debts = {r['local_key']: (key(r['source_ref']), r['time']['offset'], number(r['amount'])) for r in supplied['existing_outflows']}
        check(actual_debts == debts, 'Cash calculation drops or changes original debt')
        proposed = {'proposal:'+r['local_key']: (key(r['source_ref']), get(r['window_ref'])['start']['offset'], number(r['amount']['value'])) for r in plan['cash_uses']}
        check({r['local_key']: (key(r['source_ref']), r['time']['offset'], number(r['amount'])) for r in supplied['proposed_outflows']} == proposed,
              'Cash calculation changes source plan outflows')
        releases, drawn = {}, {}
        for r in portfolio['source_refs']:
            for release in get(r)['releases']:
                if release['state'] != 'committed': continue
                arrangement = get(release['arrangement_ref'])
                if arrangement['status'] != 'active': continue
                if any(get(c)['verification'] != 'met' for c in release['condition_refs']): continue
                check(set(map(key,arrangement['condition_refs'])) <= set(map(key,release['condition_refs'])), 'Missing finance condition')
                check(arrangement['source_ref'] == r and arrangement['borrower_organization_id'] == data['organization_id'], 'Finance identity changed')
                identity = key(arrangement['ref'])
                drawn[identity] = drawn.get(identity,Fraction()) + number(release['amount']['value'])
                check(drawn[identity] <= number(arrangement['undrawn_amount']['value']), 'Finance undrawn limit exceeded')
                releases['release:'+release['ref']['id']] = (key(r),release['time']['offset'],number(release['amount']['value']))
        check({r['local_key']: (key(r['source_ref']),r['time']['offset'],number(r['amount'])) for r in supplied['inflows']} == releases,
              'Cash calculation adds unreceived, forecast or unqualified finance')
        checkpoints = {}
        for identity, opening in accounts.items():
            endpoints = {now, *[t for s,t,a in [*debts.values(),*proposed.values(),*releases.values()] if s == identity]}
            for tick in endpoints:
                balance = opening + sum(a for s,t,a in releases.values() if s == identity and t <= tick)
                balance -= sum(a for s,t,a in [*debts.values(),*proposed.values()] if s == identity and t <= tick)
                checkpoints[(identity,tick)] = balance
        report = call['result']['value']
        actual = {(key(r['source_ref']),r['time']['offset']): Fraction(r['available']['numerator'],r['available']['denominator']) for r in report['checkpoints']}
        check(actual == checkpoints and report['feasible'] == all(v >= 0 for v in checkpoints.values()), 'Cash checkpoints differ from source ledger')
        cash_checks.append({'plan':plan['ref'], 'feasible':report['feasible'], 'checkpoints':[{"source":s,"time":t,"balance":str(v)} for (s,t),v in sorted(checkpoints.items())]})
    for call in audit['method_calls']:
        if call['method_ref']['id'] != 'micro.capacity.fixed_location': continue
        plan = get(next(r for r in call['input']['source_refs'] if r['kind'] == 'InvestmentPlan'))
        used = {key(r['resource_ref']) for r in plan['allocations']}
        supplied_resources = {key(r['resource_ref']): r for r in call['input']['resources']}
        check(set(supplied_resources) == used, 'Capacity method drops or imports a physical pool')
        for identity,row in supplied_resources.items():
            pool = source[identity]
            check(row['total'] == pool['total']['value'] and row['effective_window'] == pool['effective_window'], 'Capacity method changes source total/window')
        wanted_loads = {key(load['ref']):(identity,load['quantity'],load['window']) for identity in used for load in source[identity]['commitments']}
        supplied_loads = {key(load['commitment_ref']):(key(load['resource_ref']),load['quantity'],load['window']) for load in call['input']['commitments']}
        check(wanted_loads == supplied_loads, 'Capacity method drops existing project commitments')
        demands = {}
        for allocation in plan['allocations']:
            identity = key(allocation['resource_ref'])
            period = key(allocation['window_ref'])
            demands[(identity[1],period)] = demands.get((identity[1],period),Fraction()) + number(allocation['quantity']['value'])
        check(len(call['input']['demands']) == len(demands), 'Capacity method changes demanded windows')
        for demand in call['input']['demands']:
            periods = [period for name,period in demands if name == demand['resource_kind'] and source[period] == demand['window']]
            check(len(periods) == 1 and Fraction(demand['amount']['numerator'],demand['amount']['denominator']) == demands[(demand['resource_kind'],periods[0])],
                  'Capacity method changes aggregated plan allocation')
        feasible = True
        for identity in used:
            pool = source[identity]
            allocations = [a for a in plan['allocations'] if key(a['resource_ref']) == identity]
            endpoints = {point['offset'] for a in allocations for point in (get(a['window_ref'])['start'],get(a['window_ref'])['end'])}
            endpoints.update(point['offset'] for load in pool['commitments'] for point in (load['window']['start'],load['window']['end']))
            endpoints.update([pool['effective_window']['start']['offset'],pool['effective_window']['end']['offset']])
            points = sorted(endpoints)
            for start,end in zip(points,points[1:]):
                needed = sum((number(a['quantity']['value']) for a in allocations if in_window(get(a['window_ref']),start)),Fraction())
                if not needed: continue
                total = number(pool['total']['value']) if in_window(pool['effective_window'],start) else Fraction()
                load = sum((number(l['quantity']) for l in pool['commitments'] if in_window(l['window'],start)),Fraction())
                feasible &= needed <= max(Fraction(),total-load)
                capacity_checks.append({'plan':plan['ref'], 'pool':pool['ref'], 'start':start,'end':end,'needed':str(needed),'available':str(max(Fraction(),total-load))})
        check(call['result']['value']['feasible'] == feasible, 'Physical capacity report differs from source segments')
    choice = result.payload.choice if result.kind == "completed" else None
    if choice in {"invest", "authorize_preparation"}:
        payload = result.payload.model_dump(mode='json')
        raw = get(payload['option_ref'])
        plan = get(raw['investment_plan_ref' if choice == 'invest' else 'preparation_plan_ref'])
        check(payload['scope'] == plan['scope'], 'Returned scope differs from selected source plan')
        check(any(c['plan'] == plan['ref'] and c['feasible'] for c in cash_checks), 'Chosen plan did not pass cash oracle')
        for condition in payload['conditions']:
            item = get(condition['requirement_ref'])
            check(item['verification'] == condition['verification'] and item['verification_evidence_refs'] == condition['evidence_refs'] and item['responsible_id'] == condition['responsible_id'], 'Condition source differs')
        expected_conditions = [get(r) for r in raw['condition_refs'] if choice == 'authorize_preparation' or r in plan['scope']['condition_refs']]
        check([c['requirement_ref'] for c in payload['conditions']] == [c['ref'] for c in expected_conditions], 'Output drops or imports selected scope conditions')
        hard = {key(r) for r in plan['scope']['condition_refs']}
        check(all(source[r]['verification'] == 'met' for r in hard), 'Selected work bypasses a hard gate')
        if choice == 'invest':
            codes = {source[r]['condition_code'] for r in hard}
            required = {'rights','investment_authority','project_registration',*profiles['required_investment_condition_codes']}
            if objective['template'] == 'public_service': required.add('public_budget')
            check(required <= codes, 'Investment omits registration/public-budget gates')
            forecast = next(m['value']['value']['upper'] for a in raw['analysis_refs'] for m in get(a)['metrics'] if m['code'] == 'lifecycle_cost')
            check(number(plan['incurred_cost']['value']) + sum((number(u['amount']['value']) for u in plan['cash_uses']),Fraction()) == number(forecast), 'Cost schedule incomplete')
        check(score_calls[-1]['result']['value']['preferred_refs'] == [payload['option_ref']], 'Output bypasses unique conservative preference')
    if choice == "reject":
        check(set(result.payload.model_dump(mode="python")) == {"choice", "note"}, 'Reject creates phantom work')
    method_ids = [row["method_ref"]["id"] for row in audit["method_calls"]]
    if choice in {"invest", "authorize_preparation"}:
        check(method_ids.count("micro.owner.declared_option_intervals") >= 2 and "micro.owner.declared_cash_calendar" in method_ids and "micro.capacity.fixed_location" in method_ids, 'Successful decision bypasses host methods')
    return {'scores':[{"option":k,"conservative":str(v[0]),"optimistic":str(v[1])} for k,v in scores.items()], 'cash':cash_checks,'capacity':capacity_checks}


def verify(output: Path, workers=4):
    if not 1 <= workers <= 4: raise ValueError('Use one to four test processes')
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        raise ValueError("Choose a new repository evidence directory")
    baseline = ROOT / "output/integration/plan_20261002_implementation/baseline.json"
    protected = json.loads(baseline.read_text(encoding="utf-8"))["protected_hashes"]
    if any(sha(ROOT / name) != value for name, value in protected.items()):
        raise ValueError("Protected baseline changed")
    paths = [ROOT / f'tests/test_{m}.py' for m in TEST_MODULES]
    for directory in ('src/actions','src/methods','src/skills','src/organization','skills','config/roles','tests/fixtures/roles'):
        paths.extend(p for p in (ROOT / directory).rglob('*') if p.is_file() and p.suffix in {'.py','.md','.json'})
    paths.extend(ROOT / p for p in ('integration/verify_owner_investment.py','integration/macro_views.py','integration/coverage.py','integration/action_catalog.py','config/action_registry.json'))
    whitespace_paths = {p.relative_to(ROOT).as_posix() for p in paths}
    for directory in ('src','integration'):
        paths.extend((ROOT / directory).rglob('*.py'))
    code_hashes = {p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    output.mkdir(parents=True)
    write_new(output / 'freeze.json', {'code_hashes':code_hashes,'protected_hashes':protected})
    print('Running frozen investment and shared regression',flush=True)
    totals, unique_tests, command, role_count, method_count = _run_tests(output,workers)
    catalog = ContractCatalog()
    registry = register_representative_processors(ActionRegistry(catalog=catalog))
    methods = local_method_registry()
    from tests.test_owner_investment import build_run, facts, investment_only, template, followup, view, known, money, add_release, named, measured, set_metric
    scenarios, inputs, oracles = [], [], []
    case_rows = [
        ("invest", facts(), "completed", "invest"), ("preparation", facts(), "completed", "authorize_preparation"),
        ("return_template", facts(), "completed", "invest"), ("own_use", facts(), "completed", "invest"),
        ("public_service", facts(), "completed", "invest"), ("revise", facts(), "completed", "revise"),
        ("study_more", facts(), "completed", "study_more"), ("reject_policy", facts(), "completed", "reject"),
        ("defer_policy", facts(), "deferred", None), ("non_build", facts(), "unsupported", None),
    ]
    for label,kind,choice in [
        ('target_revise','completed','revise'),('target_study','completed','study_more'),
        ('unmet_budget','completed','authorize_preparation'),('unknown_budget','completed','authorize_preparation'),
        ('unmet_rights','completed','authorize_preparation'),('unmet_registration','completed','authorize_preparation'),
        ('early_funding','completed','invest'),('same_time_funding','completed','invest'),('late_funding','completed','reject'),
        ('forecast_funding','completed','reject'),('received_funding','completed','reject'),
        ('other_project_debt','completed','reject'),('paid_debt','completed','invest'),
        ('management_conflict','completed','reject'),('management_released','completed','invest'),
        ('partial_portfolio','needs_information',None),('unknown_cash','needs_information',None),
        ('future_analysis','needs_information',None),('brief_version','needs_information',None),
        ('foreign_debtor','technical_error',None),('region_scope','technical_error',None),
        ('reverse_accessibility','technical_error',None),('registration_path','unsupported',None),
        ('foreign_currency','unsupported',None),('infeasible_defer','deferred',None),
        ('plural_rights_met','completed','invest'),('plural_rights_unmet','completed','authorize_preparation'),('plural_rights_unknown','completed','authorize_preparation'),
    ]:
        data = facts()
        if label.startswith('target_'): followup(data,'revise' if label == 'target_revise' else 'study_more',targeted=True)
        elif label in {'unmet_budget','unknown_budget'}:
            template(data,'public_service'); named(data,'Requirement','build-public_budget')['verification'] = 'unmet' if label.startswith('unmet') else 'unknown'
        elif label.startswith('unmet_'): named(data,'Requirement','build-'+('rights' if label == 'unmet_rights' else 'project_registration'))['verification'] = 'unmet'
        elif label in {'early_funding','same_time_funding','late_funding','forecast_funding','received_funding'}:
            investment_only(data); view(data,'FundingSource')['actual_cash'] = known(money('10'))
            release = add_release(data,time=11 if label == 'early_funding' else 18 if label == 'late_funding' else 12)
            if label == 'forecast_funding': release['state'] = 'forecast'
            if label == 'received_funding': release.update(state='received',time=deepcopy(data['business_time']))
        elif label in {'other_project_debt','paid_debt'}:
            investment_only(data); view(data,'FundingSource')['actual_cash'] = known(money('35'))
            if label == 'paid_debt': view(data,'Obligation')['actual_paid'] = known(money('5'))
        elif label in {'management_conflict','management_released'}:
            investment_only(data); named(data,'InvestmentPlan','build-investment')['allocations'][0]['quantity'] = known(measured('2','manager'))
            if label == 'management_released': view(data,'ResourcePool')['commitments'][0]['window']['end']['offset'] = 12
        elif label == 'partial_portfolio': view(data,'OwnerPortfolio')['coverage'] = 'partial'
        elif label == 'unknown_cash': view(data,'FundingSource')['actual_cash'] = {'state':'unknown','reason_code':'not_supplied','missing_refs':[]}
        elif label == 'future_analysis': named(data,'OptionAnalysis','build-cost')['available_at']['offset'] = 11
        elif label == 'brief_version': named(data,'OptionAnalysis','build-cost')['brief_ref']['version'] = '2'
        elif label == 'foreign_debtor': view(data,'Obligation')['debtor_organization_id'] = 'foreign'
        elif label == 'region_scope': view(data,'OwnerCase')['region_id'] = 'MO'
        elif label == 'reverse_accessibility':
            template(data,'public_service'); view(data,'OwnerObjective')['criteria']['value'][-1]['direction'] = 'minimize'
        elif label == 'registration_path': view(data,'ProjectRegistrationProfile')['registration_code'] = 'unbound'
        elif label == 'foreign_currency': view(data,'FundingSource')['actual_cash']['value']['currency'] = 'USD'
        elif label == 'infeasible_defer':
            investment_only(data); view(data,'FundingSource')['actual_cash'] = known(money('5')); view(data,'ProjectRegistrationProfile')['on_infeasible'] = known('defer')
        elif label.startswith('plural_rights_'):
            from tests.test_owner_investment import add
            condition = deepcopy(named(data,'Requirement','build-rights')); condition.pop('ref')
            condition['verification'] = label.removeprefix('plural_rights_')
            extra = add(data,'Requirement','second-rights',**condition)
            named(data,'ProjectOption','build')['condition_refs'].append(extra['ref'])
            plan = named(data,'InvestmentPlan','build-investment')
            plan['required_condition_refs'].append(extra['ref']); plan['scope']['condition_refs'].append(extra['ref'])
        case_rows.append((label,data,kind,choice))
    print('Replaying investment branches and source oracles',flush=True)
    for label, data, expected_kind, expected_choice in case_rows:
        if label == "preparation": view(data, "ProjectRegistrationProfile")["policy"] = known("prepare_only")
        elif label == "return_template": template(data, "investment_return")
        elif label == "own_use": template(data, "own_use")
        elif label == "public_service": template(data, "public_service")
        elif label in {"revise", "study_more"}: followup(data, label)
        elif label == "reject_policy": view(data, "ProjectRegistrationProfile")["policy"] = known("reject")
        elif label == "defer_policy": view(data, "ProjectRegistrationProfile")["policy"] = known("defer")
        elif label == "non_build":
            set_metric(data, "baseline", "expected_return", "1000")
        run = build_run(data, catalog=catalog, run_id=f"{output.name}:{label}")
        before = deepcopy(run.objects)
        result = run.execute()
        if result.kind != expected_kind or (expected_choice is not None and result.payload.choice != expected_choice):
            raise ValueError(f"Unexpected {label}: {result}")
        if run.objects != before:
            raise ValueError(f"source mutation for {label}")
        audit = run.runner.audit_records[-1].as_dict()
        if audit['method_registry_digest'] != methods.content_digest or any(c['registry_digest'] != methods.content_digest for c in audit['method_calls']):
            raise ValueError('Method registry changed or audit omitted its snapshot')
        oracles.append({'label':label, 'oracle':_source_oracle(data, result, audit, before)})
        inputs.append({'label':label,'origin':'synthetic','context':run.context.model_dump(mode='json'),'input':run.input,'projections':before})
        scenarios.append({"label": label, "result": result.model_dump(mode="json"), "audit": audit,
                          "formal_submission": None, "macro_receipt": None})
    inventory = json.loads((ROOT / "config/action_registry.json").read_text(encoding="utf-8"))
    coverage = json.loads((ROOT / "宏微观衔接方案/新版方案/action_coverage.json").read_text(encoding="utf-8"))
    record = next(row for row in coverage["actions"] if row["action_id"] == "OWN-A03")
    skill = registry.get("OWN-A03").skill.manifest
    branches = {row['result']['payload']['choice'] for row in scenarios if row['result']['kind'] == 'completed'}
    if branches != set(catalog.get('OWN-A03').choices): raise ValueError('Source branch coverage incomplete')
    record.update(decision="partial_local_verified", method="partial_local_verified", validation="partial_local_verified",
        binding="unverified", feedback="pending", branches={label: "partial_local_verified" for label in sorted(branches)},
        local_processor={"processor_id": skill.processor_id, "code": "src/actions/roles/owner_investment.py", "scope": "Authorized synthetic bounded comparison/finance/capacity only"},
        local_methods={"code": "src/methods/owner_investment.py", "support": "Exact option interval and source-separated cash calendar through host MethodRegistry", "registry_status": "registered_host_method", "calibration": "mathematical_only", "registry_digest": methods.content_digest},
        gaps=[{"kind": "formal_binding", "detail": "Actual option/registration/finance/public-budget producers and formal submit/query unbound"},
              {"kind": "feedback_recovery", "detail": "Formal project, transaction, receipt, acceptance and recovery remain unbound"},
              {"kind": "real_method_calibration", "detail": "Forecasts, rights, budget, cash and management pools are synthetic"}])
    record["evidence"] = list(dict.fromkeys([*record["evidence"], (output / "manifest.json").relative_to(ROOT).as_posix()]))
    artifacts = {
        "inputs.json": inputs, 'source_oracle.json':oracles,
        "runtime.json": scenarios, "methods.json": {"registry_digest": methods.content_digest, "catalog": methods.catalog()},
        "coverage_record.json": record, "coverage.json": coverage_report(inventory, coverage),
        "skill_audit.json": registry.skill_audit(),
        "binding.json": {"action_id": "OWN-A03", "status": "not_bound", "macro_receipt": None, "limitations": LIMITATIONS},
        "checks.json": {"tests": totals, "unique_tests": unique_tests, "test_command": command, "source_checks": CHECKS,
                         "formal_receipts": 0, "runtime_cases": len(scenarios), "model_calls": 0},
    }
    for name, value in artifacts.items(): write_new(output / name, value)
    indexed = subprocess.run([sys.executable,'-m','integration.action_catalog','--check'],cwd=ROOT,capture_output=True,text=True)
    if indexed.returncode: raise ValueError(indexed.stdout+indexed.stderr)
    for name in whitespace_paths:
        checked = subprocess.run(['git','-c','core.whitespace=cr-at-eol','diff','--no-index','--check','/dev/null',name],cwd=ROOT,capture_output=True,text=True)
        if checked.stdout or checked.stderr or checked.returncode not in (0,1): raise ValueError(f'Whitespace: {name}: {checked.stdout}{checked.stderr}')
    if any(sha(ROOT / name) != value for name,value in {**protected,**code_hashes}.items()): raise ValueError('Frozen source changed; use a fresh directory')
    manifest = {"schema_version": "plan-owner-investment-evidence.v1", "action_id": "OWN-A03", "evidence_id": output.name,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "partial_local_verified", "source_sha256": catalog.get("OWN-A03").source_sha256,
        "processor_id": skill.processor_id, "skill_version": skill.skill_version, "method_registry_digest": methods.content_digest,
        "tests": totals, "unique_tests": unique_tests, 'role_tests':role_count,'method_tests':method_count, 'code_hashes':code_hashes, "runtime_cases": len(scenarios), "branches": sorted(branches),
        "checks": CHECKS, "protected": {"unchanged": True, "files": len(protected), "baseline": baseline.relative_to(ROOT).as_posix()},
        "artifact_hashes": {name: sha(output / name) for name in [*artifacts, "tests.xml", "tests.log", 'freeze.json', *[f'tests-worker-{i}.{suffix}' for i in range(workers) for suffix in ('xml','log')]]}, "limitations": LIMITATIONS,
        "environment": {"python": sys.version, "packages": {name: version(name) for name in ("pytest", "pydantic", "lark")}}}
    write_new(output / "manifest.json", manifest)
    print(json.dumps({"output": str(output), "tests": totals, "unique_tests": unique_tests, "runtime_cases": len(scenarios)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument('--workers',type=int,default=4)
    args = parser.parse_args()
    verify(args.output,args.workers)
