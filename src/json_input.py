"""Read unambiguous JSON objects before validating repository declarations."""
from __future__ import annotations

import json
import math
from pathlib import Path


def parse_json_object(text: str) -> dict:
    """Reject repeated fields at every depth and non-finite numeric transport."""
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f'Duplicate JSON field: {key}')
            value[key] = item
        return value

    def reject_constant(value):
        raise ValueError('Non-finite JSON number')

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('JSON number exceeds finite numeric transport')
        return number

    value = json.loads(text, object_pairs_hook=unique_object,
        parse_constant=reject_constant, parse_float=finite_float)
    if not isinstance(value, dict):
        raise ValueError('JSON input must be an object')
    return value


def read_json_object(path: Path) -> tuple[str, dict]:
    """Capture once; retain original JSON text for strict JSON-mode validation."""
    text = Path(path).read_bytes().decode('utf-8-sig')
    return text, parse_json_object(text)
