"""Allow semantic reading of a unique public object without repairing output."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from review_capstone_all_20261113 import content_view
from unittest.mock import patch
import pytest
import review_capstone_all_20261113 as reviewer


def test_concatenated_thoughts_and_business_objects_retain_original_failure_and_offsets():
    first = json.dumps({'thoughts': 'Excluded internal text'})
    second = json.dumps({'decision': 'bid', 'content': 'Conditional proposal only.'})
    data = {'status': 'invalid_json', 'raw_content': first + '\n' + second}
    payload, view = content_view(data)
    assert payload == {'decision': 'bid', 'content': 'Conditional proposal only.'}
    assert view['top_level_object_count'] == 2 and view['selected_object_index'] == 1
    assert data['raw_content'][view['raw_object_start']:view['raw_object_end']] == second
    assert data['status'] == 'invalid_json' and 'parsed' not in data


def test_two_public_answers_are_ambiguous_and_never_merged_or_selected():
    raw = '{"decision":"bid"}\n{"decision":"decline"}'
    payload, view = content_view({'status': 'invalid_json', 'raw_content': raw})
    assert payload is None and view['mode'] == 'multiple_or_no_public_objects_not_merged'


def test_malformed_private_prefix_does_not_expose_text_by_greedy_brace_recovery():
    payload, view = content_view({'raw_content': '{"thoughts":"bad prefix {"decision":"bid"}'})
    assert payload is None and view['mode'] == 'unparsed_raw_needs_manual_review'


def test_cp07_second_continuation_final_is_one_observation_and_prior_copies_must_match(tmp_path):
    relative = 'run/jobs/synthetic-S-r1/step-4.json'
    data = {'status': 'accepted', 'parsed': {'decision': 'bid', 'content': 'Synthetic only'}}
    for prefix in ['', 'continuation-001', 'continuation-002']:
        path = tmp_path / prefix / relative
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data), encoding='utf-8')
    with patch.dict(reviewer.PACKS, {'CP07': tmp_path}):
        path, retained, payload = reviewer.source('CP07', 'synthetic', 'S')
        assert path == tmp_path / 'continuation-002' / relative
        assert payload['content'] == 'Synthetic only'
        (tmp_path / 'continuation-001' / relative).write_text('{}', encoding='utf-8')
        with pytest.raises(AssertionError, match='duplicate final differs'):
            reviewer.source('CP07', 'synthetic', 'S')


def test_cp07_new_final_in_second_continuation_does_not_require_old_final(tmp_path):
    path = tmp_path / 'continuation-002/run/jobs/synthetic-D3-r1/step-4.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'status': 'validation_failed', 'parsed': {'content': 'Readable retained final'}}), encoding='utf-8')
    with patch.dict(reviewer.PACKS, {'CP07': tmp_path}):
        actual, data, payload = reviewer.source('CP07', 'synthetic', 'D3')
    assert actual == path and data['status'] == 'validation_failed'
    assert payload == {'content': 'Readable retained final'}
