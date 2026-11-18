"""Freeze assistant review rubrics, A/B mapping and complete input-only sample."""
import hashlib
from pathlib import Path

from capstone_cp_common_20261112 import CP01, CP02, ROOT, no_provider, read, save, sha


def key(value):
    return hashlib.sha256(('CP02-fixed-review/20261112/' + value).encode()).hexdigest()


def main():
    windows = read(CP01 / 'windows.json')
    manifest = read(CP01 / 'sample_manifest.json')
    rubric = {
        'version': 'CP02-author-assisted-review.v1', 'reviewer': 'current_conversation_assistant',
        'independent_expert': False, 'true_blinding_claimed': False,
        'paid_judge_client': False, 'provider_requests': 0,
        'dimensions': {
            'evidence_support': ['Key assertion unsupported or contradicted', 'Partially supported with material gaps', 'Key judgments supported by supplied facts'],
            'business_feasibility': ['Violates hard authority/condition/resource constraints', 'Requires unresolved material checks', 'Feasible within declared bounds or justified wait/refusal'],
            'tradeoff_reasonableness': ['Ignores decisive tradeoff or irrelevant rationale', 'Addresses only some relevant tradeoffs', 'Tradeoffs consistent with objectives and constraints'],
            'uncertainty_handling': ['Fabricates or treats unknown as certain', 'Acknowledges unknown but incomplete handling', 'Appropriate clarification/wait/scoped proposal'],
        },
        'scores': [0, 1, 2, 'not_judgable'], 'preference': ['A', 'B', 'tie', 'not_judgable'],
        'required_evidence': ['response_quote_locator', 'decision_time_source_locator', 'applicable_rule', 'reason'],
        'critical_flags': ['unsupported_capability', 'unauthorized_action', 'premature_condition_release', 'arithmetic_or_unit_error'],
        'do_not_reward': ['verbosity', 'more refusals', 'more comments', 'model_reported_decision_impact'],
        'procedure': ['score_each_answer', 'form_pair_preference', 'one_same_assistant_evidence_recheck', 'retain_initial_and_revised_ratings'],
        'missing': 'Unavailable answers retain their slots and receive not_judgable, never invented text or a semantic zero.',
        'scope': 'Diagnostic assistant labels alongside reproducible checks and execution evidence; not independent professional validation.'}
    pairs, mapping, ratings = [], [], []
    with no_provider() as counts:
        for index, wid in enumerate(sorted(windows, key=key), 1):
            pair_id = f'CP02-PAIR-{index:02d}'
            order = ['v2_4', 'v2_5'] if int(key(wid + '/order'), 16) % 2 else ['v2_5', 'v2_4']
            w = windows[wid]
            pairs.append({'pair_id': pair_id, 'window_id': wid, 'case_id': w['case_id'],
                          'project_group': w['project_group'], 'role': w['role'], 'variant': w['variant'],
                          'repeat': 1, 'input_window_sha256': hashlib.sha256(__import__('json').dumps(w, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                          'facts': w['facts'], 'conditions': w['conditions'],
                          'state': 'awaiting_real_outputs_not_scored'})
            for label, arm in zip(('A', 'B'), order):
                jid = f'{wid}-{arm}-r1'
                mapping.append({'pair_id': pair_id, 'label': label, 'arm': arm, 'job_id': jid,
                                'response_path': str((CP01 / 'run/jobs' / jid / 'attempt-1.json').relative_to(ROOT)),
                                'response_sha256': None, 'state': 'future_response_not_present'})
                ratings.append({'pair_id': pair_id, 'label': label, 'state': 'unscored',
                                'scores': {k: None for k in rubric['dimensions']},
                                'critical_flags': [], 'evidence_items': [], 'reason': None,
                                'initial_rating': None, 'recheck_rating': None, 'revision_reason': None})
        assert len(manifest) == 24 and len(pairs) == 48 and len(ratings) == 96
        old = ROOT / 'Capstone报告/验证体系/实验/2026-11-08_后续模型实验/attempt-002'
        protocol = read(old / 'protocol.json')
        jobs = protocol['jobs']['organization']
        process_blocks = []
        for wid in sorted({j['window_id'] for j in jobs}, key=key):
            rep = 1 if int(key(wid + '/process-repeat'), 16) % 2 else 2
            source_paths = {}
            for arm in ['single_agent', 'role_discussion']:
                path = old / 'organization/jobs' / f'{wid}-{arm}-r{rep}' / 'final-attempt-1.json'
                assert path.is_file(), path
                source_paths[arm] = {'path': str(path.relative_to(ROOT)), 'sha256': sha(path)}
                if arm == 'role_discussion':
                    source_paths['comments'] = [{'path': str((path.parent / f'role-{i}-attempt-1.json').relative_to(ROOT)),
                                                 'sha256': sha(path.parent / f'role-{i}-attempt-1.json')}
                                                for i in range(1, 4)]
            process_blocks.append({'window_id': wid, 'repeat': rep, 'sources': source_paths,
                                   'items': [], 'state': 'selected_not_scored',
                                   'item_fields': ['item_id', 'comment_quote', 'source_support', 'new_or_repeated', 'final_response_quote', 'adopted_or_rejected_or_omitted', 'reason']})
        assert len(process_blocks) == 12
        calibration = []
        old_confirm = ROOT / 'Capstone报告/验证体系/实验/2026-11-09_V2_5_角色与语境最终确认/confirmation-prepared'
        old_protocol = read(old_confirm / 'protocol.json')
        for wid in sorted({j['window_id'] for j in old_protocol['jobs']}, key=key)[:6]:
            calibration.append({'window_id': wid, 'repeat': 1, 'source_root': str(old_confirm.relative_to(ROOT)),
                                'state': 'old_material_for_format_calibration_only_not_a_new_sample'})
        save(CP02 / 'rubric.json', rubric)
        save(CP02 / 'pair_inputs.json', pairs)
        save(CP02 / 'pair_source_projections.json', [
            {'pair_id': p['pair_id'], 'company_evidence': windows[p['window_id']]['company_evidence']}
            for p in pairs])
        save(CP02 / 'ab_mapping.json', mapping)
        save(CP02 / 'ratings_template.json', ratings)
        save(CP02 / 'pair_preferences_template.json', [{'pair_id': p['pair_id'], 'preference': None, 'reason': None, 'evidence_items': []} for p in pairs])
        save(CP02 / 'organization_blocks.json', process_blocks)
        save(CP02 / 'calibration_selection.json', calibration)
        save(CP02 / 'preparation.json', {'passed': True, 'pairs': 48, 'answers': 96,
             'source_project_groups': 24, 'fixed_repeat': 1, 'process_blocks': 12,
             'ratings_completed': 0, 'no_future_outputs_invented': True,
             'new_input_sha256': sha(CP01 / 'windows.json'), 'provider_requests': 0, **counts})
    print('CP02 prepared:48 pairs/96 unscored slots;12 existing process blocks; no judge/model requests')


if __name__ == '__main__':
    main()
