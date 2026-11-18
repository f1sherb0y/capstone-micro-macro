"""Read source packets and persist explicitly authored business labels; no judge API."""
import argparse
import hashlib
import json
from pathlib import Path

from capstone_cp_common_20261112 import ROOT, CP00, CP01, PARENT, read, save, sha

BASE = ROOT / 'Capstone报告/验证体系'
OUT = BASE / '实验/2026-11-12_第一阶段48组微观结果'
PREP = BASE / '指标补充/2026-11-12_第一阶段微观启动准备'
MEASURE = BASE / '指标补充/2026-11-12_业务结果评价规范_v2'


def source(cohort, window_id, arm, repeat, attempt=1):
    assert cohort in {'CP00', 'CP01'} and arm in {'v2_4', 'v2_5'}
    root = CP00 if cohort == 'CP00' else CP01
    path = root / 'run/jobs' / f'{window_id}-{arm}-r{repeat}' / f'attempt-{attempt}.json'
    data = read(path)
    payload = data.get('parsed')
    if not isinstance(payload, dict):
        try:
            payload = json.loads(data.get('raw_content', ''))
        except (ValueError, TypeError):
            payload = None
    if isinstance(payload, dict):
        payload = {k: v for k, v in payload.items() if k not in {'thoughts', 'company_assessment'}}
    return path, data, payload


def cards(cohort):
    path = PREP / 'CP00_task_cards.json' if cohort == 'CP00' else MEASURE / 'task_cards.json'
    return path, {r['window_id']: r for r in read(path)}


def locate(value, quote, pointer=''):
    if isinstance(value, str) and quote in value:
        offset = value.index(quote)
        return {'json_pointer': pointer, 'start': offset, 'end': offset + len(quote), 'quote': quote}
    if isinstance(value, dict):
        for key, child in value.items():
            hit = locate(child, quote, pointer + '/' + key.replace('~', '~0').replace('/', '~1'))
            if hit:
                return hit
    if isinstance(value, list):
        for i, child in enumerate(value):
            hit = locate(child, quote, pointer + '/' + str(i))
            if hit:
                return hit
    return None


def packet(cohort, window_id):
    _, by_id = cards(cohort)
    card = by_id[window_id]
    print(json.dumps({'input': {k: card[k] for k in ['window_id', 'role', 'project_facts', 'provided_company_fields', 'conditions']},
        'factor_criteria': [{'id': f['factor_id'], 'criterion': f['adequate_handling']} for f in card['factors']]}, ensure_ascii=False))
    for arm in ['v2_4', 'v2_5']:
        for repeat in [1, 2]:
            try:
                path, data, payload = source(cohort, window_id, arm, repeat)
            except FileNotFoundError:
                print(json.dumps({'cohort': cohort, 'window_id': window_id, 'arm': arm, 'repeat': repeat, 'state': 'not_present'}))
                continue
            print(json.dumps({'cohort': cohort, 'window_id': window_id, 'arm': arm, 'repeat': repeat,
                'status': data['status'], 'outward': payload if payload is not None else data.get('raw_content'),
                'response_sha256': sha(path)}, ensure_ascii=False))


def ingest(path):
    rows = read(path)
    for row in rows:
        cohort, wid, arm, repeat = (row[k] for k in ['cohort', 'window_id', 'arm', 'repeat'])
        card_path, by_id = cards(cohort)
        card = by_id[wid]
        response_path, data, payload = source(cohort, wid, arm, repeat, row.get('attempt', 1))
        assert isinstance(payload, dict), 'No synthetic labels for unreadable or missing content'
        assert row['D1'] in {'appropriate', 'inappropriate', 'not_judgable'}
        assert row['D1_reason'] and row['D1_quote']
        d1_location = locate(payload, row['D1_quote'])
        assert d1_location, 'D1 quote must be exact outward response text'
        assert len(row['factors']) == len(card['factors'])
        factors = []
        for label, criterion in zip(row['factors'], card['factors']):
            assert label['id'] == criterion['factor_id']
            assert label['rating'] in criterion['states']
            assert label['reason']
            quote = label.get('quote')
            location = locate(payload, quote) if quote else None
            if quote:
                assert location, (wid, label['id'], quote)
            else:
                assert label['rating'] in {'missing', 'not_judgable'}
            factors.append({'factor_id': label['id'], 'rating': label['rating'], 'reason': label['reason'],
                'response_evidence': location, 'source_card_ref': str(card_path.relative_to(ROOT)).replace('\\', '/') + '#' + wid,
                'input_pointers': criterion['input_pointers'], 'criterion': criterion['adequate_handling']})
        record = {'cohort': cohort, 'window_id': wid, 'arm': arm, 'repeat': repeat,
            'attempt': row.get('attempt', 1), 'project_group': card['project_group'], 'role': card['role'],
            'response_path': str(response_path.relative_to(ROOT)).replace('\\', '/'), 'response_sha256': sha(response_path),
            'call_id': data['call_id'], 'program_status_retained': data['status'],
            'annotated_action': row['action'], 'D1_appropriateness': row['D1'], 'D1_reason': row['D1_reason'],
            'D1_evidence': d1_location, 'factor_ratings': factors,
            'D2_correct_coverage': sum(f['rating'] == 'correct' for f in factors) / len(factors),
            'D3_feasibility': row.get('D3'), 'D4_tradeoff': row.get('D4'),
            'initial_review_complete': True, 'evidence_recheck': None,
            'reviewer': 'Current author-assisting AI involved in design; not independent or blinded',
            'evaluation_identity': 'exploratory_old_material' if cohort == 'CP00' else 'fixed_new_cohort'}
        name = f'{wid}-{arm}-r{repeat}-a{record["attempt"]}.json'
        save(OUT / 'business_review' / cohort / name, record)
    print(json.dumps({'explicit_review_rows_saved': len(rows), 'model_calls': 0}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--packet', nargs=2, metavar=('COHORT', 'WINDOW'))
    p.add_argument('--ingest', type=Path)
    a = p.parse_args()
    if a.packet:
        packet(*a.packet)
    elif a.ingest:
        ingest(a.ingest)
    else:
        p.error('Choose an input packet or explicitly authored rating rows')
