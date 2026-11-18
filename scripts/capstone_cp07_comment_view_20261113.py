"""Lossless process-comment read view; no generated text or source edits.

Only the original comment string enters later stages. Optional metadata must
repeat the already assigned task role or the JSON-object type. Unknown public
fields, duplicate keys, conflicting roles, and empty comments remain errors.
"""
import hashlib
import json


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('Duplicate response key is ambiguous')
        obj[key] = value
    return obj


def comment_read_view(raw, *, expected_role):
    clean = raw.strip()
    if clean.startswith('```'):
        clean = clean.strip('`')
        if clean.startswith('json'):
            clean = clean[4:].strip()
    try:
        value = json.loads(clean, object_pairs_hook=unique_object)
    except json.JSONDecodeError:
        start, end = clean.find('{'), clean.rfind('}')
        if start < 0 or end <= start:
            raise ValueError('No unambiguous process JSON object')
        value = json.loads(clean[start:end + 1], object_pairs_hook=unique_object)
    if not isinstance(value, dict) or not set(value) <= {'comment', 'task_role', 'type'}:
        raise ValueError('Unexpected public fields in a process comment')
    comment = value.get('comment')
    if not isinstance(comment, str) or not comment.strip():
        raise ValueError('Process requires one nonempty comment string')
    if 'task_role' in value and value['task_role'] != expected_role:
        raise ValueError('Response metadata conflicts with the original assigned role')
    if 'type' in value and value['type'] != 'json_object':
        raise ValueError('Unexpected process response type metadata')
    metadata = {key: value[key] for key in value if key != 'comment'}
    return {'comment': comment, 'ignored_matching_metadata': metadata,
        'read_view_mode': 'original_comment_only' if not metadata else 'original_comment_with_redundant_metadata_ignored',
        'raw_content_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
        'forwarded_comment_sha256': hashlib.sha256(comment.encode('utf-8')).hexdigest(),
        'comment_text_changed': False}
