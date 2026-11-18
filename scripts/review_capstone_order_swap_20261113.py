"""Read-only, source-bound presentation checks; preferences are authored, never inferred."""
import argparse
import json
from pathlib import Path

from review_capstone_all_20261113 import MASTER, ROOT, cards, source, locate, read, save, sha

OUT = MASTER / 'order_check/CP01_001'


def prepare():
    selection = MASTER / 'order_swap_selection.json'
    chosen = [p for p in read(selection)['pairs'] if p['cohort'] == 'CP01']
    assert len(chosen) == 12
    card_path, by_id = cards('CP01')
    bindings = []
    for i, p in enumerate(chosen, 1):
        pair_id = f'PAIR-{i:02d}'
        wid = p['window_id']
        answers = {}
        for arm in p['first_presentation_order']:
            path, _, outward = source('CP01', wid, arm, 1, 1)
            assert isinstance(outward, dict)
            grade = MASTER / 'business_review/CP01' / f'{wid}-{arm}-r1-a1.json'
            assert read(grade)['response_sha256'] == sha(path)
            answers[arm] = {'response_path': str(path.relative_to(ROOT)), 'response_sha256': sha(path),
                            'grade_path': str(grade.relative_to(ROOT)), 'grade_sha256': sha(grade),
                            'outward': outward}
        card = by_id[wid]
        public_input = {k: card[k] for k in ['role', 'assessment_stage', 'business_objective',
            'project_facts', 'scope_basis', 'provided_company_fields', 'not_supplied',
            'ordinary_support', 'conditions', 'case_specific_attention', 'factors', 'common_scoring_rules']}
        for round_id, order_key in [(1, 'first_presentation_order'), (2, 'second_presentation_order')]:
            packet = {'pair_id': pair_id, 'round': round_id, 'input': public_input,
                      'answers_in_display_order': [{'label': label, 'outward': answers[arm]['outward']}
                          for label, arm in zip(['A', 'B'], p[order_key])]}
            save(OUT / 'packets' / f'{pair_id}-round{round_id}.json', packet)
        bindings.append({'pair_id': pair_id, 'selection': p, 'answers': answers})
    save(OUT / 'source_binding.json', {'selection_path': str(selection.relative_to(ROOT)),
        'selection_sha256': sha(selection), 'input_card_path': str(card_path.relative_to(ROOT)),
        'input_card_sha256': sha(card_path), 'pairs': bindings,
        'limitations': ['Same assistant already saw labeled responses and authored initial grades.',
            'Removing version metadata here cannot create independent or true blind review.',
            'Order check concerns pair preference; initial per-dimension scores remain preserved.',
            'No weighted aggregate or automatic preference is computed.'], 'new_model_calls': 0})
    print('Prepared 12 fixed pairs, 24 source-bound presentations; no preferences inferred.')


def binding(pair_id):
    doc = read(OUT / 'source_binding.json')
    assert sha(ROOT / doc['selection_path']) == doc['selection_sha256']
    assert sha(ROOT / doc['input_card_path']) == doc['input_card_sha256']
    pair = next(p for p in doc['pairs'] if p['pair_id'] == pair_id)
    for a in pair['answers'].values():
        for prefix in ['response', 'grade']:
            assert sha(ROOT / a[prefix + '_path']) == a[prefix + '_sha256']
    return pair


def show(pair_id, round_id):
    binding(pair_id)
    if round_id == 2:
        assert (OUT / 'judgments' / f'{pair_id}-round1.json').is_file(), 'Commit initial preference first'
    packet = read(OUT / 'packets' / f'{pair_id}-round{round_id}.json')
    print(json.dumps(packet, ensure_ascii=False))


def ingest(path):
    rows = read(path)
    prepared = []
    for row in rows:
        pid, rnd = row['pair_id'], row['round']
        assert rnd in {1, 2} and type(rnd) is int
        pair = binding(pid)
        if rnd == 2:
            assert (OUT / 'judgments' / f'{pid}-round1.json').is_file()
        packet_path = OUT / 'packets' / f'{pid}-round{rnd}.json'
        packet = read(packet_path)
        assert row['preference'] in {'A', 'B', 'tie', 'not_judgable'}
        assert row['reason'].strip() and row['input_basis'].strip()
        assert {e['label'] for e in row['evidence']} == {'A', 'B'}
        evidence = []
        for e in row['evidence']:
            answer = next(a for a in packet['answers_in_display_order'] if a['label'] == e['label'])
            position = locate(answer['outward'], e['quote'])
            assert position, 'Exact public quotation required: ' + e['quote']
            evidence.append({**e, 'location': position})
        order = pair['selection']['first_presentation_order' if rnd == 1 else 'second_presentation_order']
        preference = row['preference']
        selected_arm = order[['A', 'B'].index(preference)] if preference in {'A', 'B'} else preference
        record = {**row, 'evidence': evidence, 'preferred_source_arm': selected_arm,
            'presentation_sha256': sha(packet_path), 'source_binding_sha256': sha(OUT/'source_binding.json'),
            'authored_path': str(path.resolve().relative_to(ROOT)), 'authored_sha256': sha(path),
            'rating_changes': 'No numerical rescore in this pair-preference order check; original dimension grades retained.',
            'reviewer': 'same design-participating assistant; not independent or truly blinded', 'new_model_calls': 0}
        prepared.append((OUT/'judgments'/f'{pid}-round{rnd}.json', record))
    assert len({str(p) for p, _ in prepared}) == len(prepared)
    for p, record in prepared:
        save(p, record)
    print(json.dumps({'authored_preferences_saved': len(prepared), 'new_model_calls': 0}))


def summarize():
    pairs = read(OUT/'source_binding.json')['pairs']
    rows = []
    for p in pairs:
        pid = p['pair_id']
        paths = [OUT/'judgments'/f'{pid}-round{r}.json' for r in [1, 2]]
        if not all(q.is_file() for q in paths):
            continue
        first, swapped = map(read, paths)
        rows.append({'pair_id': pid, 'window_id': p['selection']['window_id'],
            'role': p['selection']['role'], 'first': first['preferred_source_arm'],
            'swapped': swapped['preferred_source_arm'],
            'preference_changed': first['preferred_source_arm'] != swapped['preferred_source_arm'],
            'judgment_hashes': [sha(q) for q in paths]})
    save(OUT/'summary_001.json', {'selected_pairs': len(pairs), 'completed_pairs': len(rows),
        'changed_preferences': sum(r['preference_changed'] for r in rows), 'pairs': rows,
        'scope': 'Descriptive same-assistant order check only; no independent reliability or accuracy estimate.',
        'initial_dimension_scores_modified': False, 'source_binding_sha256': sha(OUT/'source_binding.json'),
        'new_model_calls': 0})
    print(json.dumps({'completed_pairs': len(rows), 'changed_preferences': sum(r['preference_changed'] for r in rows)}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--prepare', action='store_true')
    p.add_argument('--show', nargs=2, metavar=('PAIR_ID', 'ROUND'))
    p.add_argument('--ingest', type=Path)
    p.add_argument('--summarize', action='store_true')
    a = p.parse_args()
    if a.prepare: prepare()
    elif a.show: show(a.show[0], int(a.show[1]))
    elif a.ingest: ingest(a.ingest)
    elif a.summarize: summarize()
    else: p.error('Choose prepare/show/ingest/summarize')
