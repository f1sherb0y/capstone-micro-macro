"""Prepare a consolidated remaining-work GOAL snapshot; never starts experiments."""
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'Capstone报告/验证体系'
PACK = BASE / '实验/2026-11-12_CP零调用准备'
PHASE = BASE / '实验/2026-11-12_第一阶段48组微观结果'
OUT = BASE / '指标补充/2026-11-13_总收尾GOAL'
GOAL = BASE / '2026-11-13_GOAL_Capstone剩余实验与结果收尾.md'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    if path.exists():
        assert path.read_text(encoding='utf-8') == text, 'Current snapshot changed; preserve history and review actual state.'
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


def charged(path, expected):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        records = [json.loads(r[0]) for r in db.execute('SELECT record FROM model_call_budgets')]
        assert len(records) == 1 and records[0]['max_calls'] == 240
        assert records[0]['charged_calls'] == expected
        return expected
    finally:
        db.close()


def main():
    accounting_path = PHASE / 'execution_accounting.json'
    accounting = read(accounting_path)
    assert accounting['phase_new_attempts'] == 83 and accounting['CP01']['remaining'] == 238
    assert charged(BASE / '实验/2026-11-09_24项目扩样验证/run/budget.sqlite', 240) == 240
    assert charged(PACK / 'CP01/run/budget.sqlite', 2) == 2
    cont = PACK / 'CP01/continuation-001'
    ready = read(cont / 'readiness_manifest.json')
    assert sha(ROOT / 'scripts/continue_capstone_cp01_20261112.py') == ready['runner_sha256']
    assert sha(cont / 'plan.json') == ready['plan_sha256']
    assert sha(cont / 'preflight.json') == ready['preflight_sha256']
    for path, h in read(cont / 'plan.json')['source_sha256'].items():
        assert sha(ROOT / path) == h
    assert not (cont / 'run').exists() and not (cont / 'launch_authorization.json').exists()
    assert not (PACK / 'CP03/run').exists() and not (PACK / 'CP03/authorization.json').exists()
    v4_dir = BASE / '指标补充/2026-11-12_完整方案_v4'
    v4 = read(v4_dir / 'scope.json')
    assert v4['future_attempt_ceiling'] == 3571
    assert sha(ROOT / v4['plan']) == v4['plan_sha256']
    budgets = [
        {'batch': 'CP01', 'remaining_max': 238, 'first_max': 190, 'repair_max': 48,
         'parent_cap': 240, 'already_charged': 2},
        {'batch': 'CP08', 'remaining_max': 928, 'first_max': 928, 'repair_max': 0, 'actual_limit': '4*n, n<=232'},
        {'batch': 'CP07', 'remaining_max': 864, 'first_max': 864, 'repair_max': 0},
        {'batch': 'CP03', 'remaining_max': 324, 'first_max': 324, 'repair_max': 0},
        {'batch': 'CP03E', 'remaining_max': 162, 'first_max': 162, 'repair_max': 0},
        {'batch': 'CP03X', 'remaining_max': 972, 'first_max': 972, 'repair_max': 0, 'actual_limit': '54*m, m<=18'},
    ]
    assert sum(b['remaining_max'] for b in budgets) == 3488 == 3571 - 83
    assert sum(b['first_max'] for b in budgets) == 3440
    assert sum(b['repair_max'] for b in budgets) == 48
    assert 1588 + 4 * 232 + 54 * 18 == 3488
    sources = [accounting_path, PHASE / 'halt_manifest.json', v4_dir / 'scope.json', v4_dir / 'manifest.json',
        cont / 'plan.json', cont / 'preflight.json', cont / 'readiness_manifest.json',
        PACK / 'CP01/run/budget.sqlite', PACK / 'CP01/run/budget_usage.json',
        BASE / '实验/2026-11-09_24项目扩样验证/run/budget.sqlite',
        ROOT / 'scripts/continue_capstone_cp01_20261112.py']
    snapshot = {
        'state': 'master_GOAL_prepared_not_executed', 'date': '2026-11-13',
        'goal_sha256': sha(GOAL), 'v4_initial_future_envelope': 3571,
        'already_accounted_against_v4': 83, 'remaining_envelope': 3488,
        'older159_not_subtracted_twice': True, 'CP00_additional_calls': 0,
        'budgets': budgets, 'eligible_limit_formula': '1588+4*n_CP08+54*m_CP03X, n<=232,m<=18',
        'existing_unknowns_never_replayed': accounting['unknown_attempts_never_replayed'],
        'paid_order': ['CP01', 'CP08', 'CP07', 'CP03', 'CP03E', 'CP03X', 'CP04_deterministic'],
        'max_simultaneously_active_paid_batches': 1,
        'offline_preparation_and_review_may_overlap_paid_waits': True,
        'known_existing_readiness': {'CP01': 'offline_prepared_8_preflight_checks_9_guard_tests',
            'CP08': 'runtime_and_inputs_pending', 'CP07': 'runtime_and_prompts_pending',
            'CP03': 'existing6_configs_and_native_adapter_remaining_business_influence_and_full_input_checks',
            'CP03E': '3_configs_and_runner_scope_pending',
            'CP03X': '18_candidates_domain_region_family_and_runtime_adaptation_pending',
            'CP04': 'requires_actual_source_chains_and_deterministic_replay_assembly'},
        'formal_business_scoring_complete': False, 'draft_initial_reviews_retained': 4,
        'new_calls_during_preparation': 0, 'new_simulations_during_preparation': 0,
        'paid_execution_authorized_by_this_file': False, 'original_goal_resumed_by_this_preparation': False,
        'source_sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in sources},
    }
    save(OUT / 'snapshot.json', snapshot)
    save(OUT / 'manifest.json', {'state': snapshot['state'], 'goal_sha256': sha(GOAL),
        'snapshot_sha256': sha(OUT / 'snapshot.json'), 'builder_sha256': sha(Path(__file__)),
        'remaining_max': 3488, 'new_calls': 0, 'paid_execution_authorized': False})
    print(json.dumps({'goal': 'remaining_experiments_and_results', 'already_accounted': 83,
        'remaining_max': 3488, 'CP01_remaining_max': 238, 'CP00_new_calls_allowed': 0,
        'new_calls': 0, 'original_goal_remains_paused': True}))


if __name__ == '__main__':
    main()
