"""Inspect one retained invalid JSON response; never repair/overwrite it."""
import json
import re

from capstone_cp_common_20261112 import CP00, read

path = CP00 / 'run/jobs/EXPAND-18-missing_core-v2_4-r1/attempt-1.json'
data = read(path)
raw = data['raw_content']
try:
    json.loads(raw)
except json.JSONDecodeError as exc:
    print(json.dumps({'error': str(exc), 'position': exc.pos,
        'near_error': raw[max(0, exc.pos - 60):exc.pos + 100]}, ensure_ascii=False))
try:
    relaxed = json.loads(raw, strict=False)
except json.JSONDecodeError as exc:
    print('Non-strict read view also fails: ' + str(exc))
else:
    print(json.dumps({'view_only_non_strict_json': {k: v for k, v in relaxed.items()
          if k not in {'thoughts', 'company_assessment'}}, 'original_status_retained': data['status']}, ensure_ascii=False))
print(json.dumps({'named_field_offsets': [(m.group(1), m.start()) for m in re.finditer(
    r'"(decision|reason|content|company_assessment|unresolved_condition_ids|verified_condition_ids|bid_assumptions|verification_requests)"\s*:', raw)]}, ensure_ascii=False))
