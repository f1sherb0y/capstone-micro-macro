"""Planned-slot accounting and input-hash order checks; no semantic scoring."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib

from capstone_cp_common_20261112 import ROOT, CP00, CP01, read, save, sha
from review_capstone_all_20261113 import MASTER, PACKS, source, cards


def rank(value):
    return hashlib.sha256(('Capstone-order-check-20261112|' + value).encode()).hexdigest()


def cp07_missing_disposition(jid):
    stopped = MASTER / 'CP07_stop_snapshot.json'
    if stopped.exists() and jid == read(stopped)['unknown_entire_D3_job_excluded_no_comment_to_continue']:
        return {'status': 'historical_process_step_unknown_no_final',
            'process_unknown_source_path': str(stopped.relative_to(ROOT)).replace('\\', '/'),
            'process_unknown_source_sha256': sha(stopped)}
    status_path = PACKS['CP07'] / 'continuation-002/run/jobs' / jid / 'continuation-002-job-status.json'
    if status_path.exists():
        job_state = read(status_path)
        if job_state['state'] == 'returned_process_format_unreadable_remaining_steps_skipped':
            return {'status': 'known_returned_process_format_no_final_remaining_steps_skipped',
                'review_state': 'no_final_after_known_returned_process_format',
                'process_missing_source_path': str(status_path.relative_to(ROOT)).replace('\\', '/'),
                'process_missing_source_sha256': sha(status_path),
                'unused_following_steps_not_transferred': job_state['unused_remaining_steps']}
    return {}


def summarize_first_slots(rows):
    summary = {}
    for cohort in ['CP00', 'CP01', 'CP08', 'CP07']:
        own = [r for r in rows if r['cohort'] == cohort]
        grouped = defaultdict(list)
        for row in own:
            grouped[row['project_group']].append(row)
        summary[cohort] = {'planned_final_slots': len(own),
            'readable_outward_content_views': sum(r['readable_outward_json'] for r in own),
            'raw_first_answers_available': sum(r['raw_available'] for r in own),
            'status_counts': dict(Counter(r['status'] for r in own)),
            'review_counts': dict(Counter(r['review_state'] for r in own)),
            'groups_with_all_planned_first_answers_readable': sum(all(r['readable_outward_json'] for r in group) for group in grouped.values())}
    return summary


def main(tag):
    assert tag and all(c.isalnum() or c in '_-' for c in tag), 'Use a new simple snapshot tag'
    started = datetime.now(timezone.utc).isoformat()
    rows, card_hashes = [], {}
    for cohort in ['CP00', 'CP01', 'CP08', 'CP07']:
        path, by_id = cards(cohort)
        card_hashes[cohort] = {'path': str(path.relative_to(ROOT)).replace('\\', '/'), 'sha256': sha(path)}
        for wid, card in by_id.items():
            for arm in (['S', 'D3', 'S4'] if cohort == 'CP07' else ['v2_4', 'v2_5']):
                for repeat in ([1, 2] if cohort in {'CP00', 'CP01'} else [1]):
                    row = {'cohort': cohort, 'window_id': wid, 'project_group': card['project_group'],
                        'case_id': card['case_id'], 'role': card['role'], 'variant': card['variant'],
                        'arm': arm, 'repeat': repeat, 'attempt': 1, 'response_path': None,
                        'status': 'no_saved_first_attempt_yet', 'raw_available': False,
                        'readable_outward_json': False, 'review_state': 'no_readable_response_yet'}
                    try:
                        path, data, outward = source(cohort, wid, arm, repeat)
                    except FileNotFoundError:
                        if cohort == 'CP07':
                            row.update(cp07_missing_disposition(f'{wid}-{arm}-r{repeat}'))
                    else:
                        row.update(response_path=str(path.relative_to(ROOT)).replace('\\', '/'),
                            response_sha256=sha(path), call_id=data['call_id'], status=data['status'],
                            raw_available=bool(data.get('raw_content')),
                            readable_outward_json=isinstance(outward, dict))
                        row['content_review_read_view'] = data['content_review_read_view']
                        if row['readable_outward_json']:
                            review_path = MASTER / 'business_review' / cohort / f'{wid}-{arm}-r{repeat}-a1.json'
                            if review_path.exists():
                                rating = read(review_path)
                                assert rating['response_sha256'] == sha(path)
                                rechecked = bool(rating.get('evidence_recheck'))
                                recheck_path = MASTER / 'business_recheck' / cohort / review_path.name
                                if recheck_path.exists():
                                    recheck = read(recheck_path)
                                    assert recheck['initial_record_sha256'] == sha(review_path)
                                    assert recheck['response_sha256'] == sha(path)
                                    rechecked = recheck['complete']
                                row['review_state'] = 'evidence_rechecked' if rechecked else 'initial_explicit_review_complete_recheck_pending'
                            else:
                                row['review_state'] = 'explicit_business_review_pending'
                        elif row['raw_available']:
                            row['review_state'] = 'raw_unparsed_requires_manual_readability_review'
                    rows.append(row)
    summary = summarize_first_slots(rows)
    assert len(rows) == 1600
    assert [summary[c]['planned_final_slots'] for c in ['CP00', 'CP01', 'CP08', 'CP07']] == [192, 192, 928, 288]
    assert all(0 <= s['readable_outward_content_views'] <= s['raw_first_answers_available'] <= s['planned_final_slots'] for s in summary.values())
    snapshot = {'started_at_UTC': started, 'finished_at_UTC': datetime.now(timezone.utc).isoformat(),
        'indexer_sha256': sha(__file__),
        'live_run_boundary': 'Saved first-attempt files observed during this indexing interval; in-flight requests without a saved attempt are not classified as unstarted or halted.'}
    save(MASTER / f'response_index_{tag}.json', {'unit_key': ['cohort', 'window_id', 'arm', 'repeat', 'attempt'],
        'scope': 'First final answers only; repairs and intermediate comments are separate evidence, not independent projects.',
        'snapshot': snapshot, 'task_card_hashes': card_hashes, 'rows': rows})
    save(MASTER / f'business_readiness_{tag}.json', {'summary': summary,
        'snapshot': snapshot,
        'total_raw_first_answers_available': sum(s['raw_first_answers_available'] for s in summary.values()),
        'total_readable_outward_content_views': sum(s['readable_outward_content_views'] for s in summary.values()),
        'read_view_exception': 'One original invalid_json response has two top-level objects, of which exactly one is a complete public business answer; status/raw kept unchanged, no merge or protocol acceptance.',
        'planned_first_final_slots': len(rows),
        'business_outcome_aggregate': 'Not yet available; no automatic inference from return/program states.',
        'actual_model_calls_for_this_index': 0})
    pairs = []
    for cohort in ['CP01', 'CP08', 'CP07']:
        _, by_id = cards(cohort)
        candidates = list(by_id.values())
        if cohort == 'CP08':
            selected = set(read(PACKS['CP08'] / 'detailed_score_groups.json'))
            candidates = [c for c in candidates if c['project_group'] in selected]
        by_role = defaultdict(dict)
        for card in candidates:
            by_role[card['role']].setdefault(card['project_group'], []).append(card)
        for role in sorted(by_role):
            groups = sorted(by_role[role], key=lambda g: rank(cohort + '|' + role + '|' + g))[:3]
            for group in groups:
                card = min(by_role[role][group], key=lambda c: rank(cohort + '|' + c['window_id']))
                arms = ['D3', 'S4'] if cohort == 'CP07' else ['v2_4', 'v2_5']
                first_order = arms if int(rank(cohort + '|' + group)[0], 16) % 2 == 0 else arms[::-1]
                pairs.append({'cohort': cohort, 'project_group': group, 'role': role,
                    'window_id': card['window_id'], 'repeat': 1, 'attempt': 1,
                    'first_presentation_order': first_order, 'second_presentation_order': first_order[::-1],
                    'first_preference': None, 'swapped_preference': None, 'rating_changes': None,
                    'state': 'input_selected_order_check_not_completed'})
    assert len(pairs) == 36
    save(MASTER / 'order_swap_selection.json', {'pairs': pairs,
        'selection': 'Fixed input hash; three different project groups per role per cohort, within preselected CP08 detailed groups; no response score or preference is read.',
        'timing': 'Concrete list materialized after CP01 execution/partial CP08 execution, before any pair preference/order recheck and before CP07 output; not claimed as independently preregistered before all outputs.',
        'reviewer_boundary': 'Same assistant ordering sensitivity check, not independent/blinded inter-rater agreement.', 'new_model_calls': 0})
    print(summary)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True, help='New immutable snapshot suffix; never overwrite an earlier grading snapshot')
    main(parser.parse_args().tag)
