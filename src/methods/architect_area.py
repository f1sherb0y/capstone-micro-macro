"""Declared disjoint equal-floor groups; no statutory or technical conclusions."""
import hashlib
from fractions import Fraction
from pathlib import Path
from typing import Annotated

from pydantic import Field

from src.actions.contracts.common import Measured, Reference, StrictRecord, TextId, ValueState, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.pricing import decimal_fraction, exact_decimal

AREA_METHOD = ref_type('Method')(kind='Method', id='micro.architect.area_schedule_sum', version='1')


class ArchitectAreaGroup(StrictRecord):
    local_key: TextId
    floor_keys: Annotated[list[TextId], Field(min_length=1)]
    area_per_floor: ValueState[Measured]
    missing_evidence_refs: list[ref_type('Evidence')]


class ArchitectAreaInput(StrictRecord):
    groups: Annotated[list[ArchitectAreaGroup], Field(min_length=1)]
    unit: TextId
    total_basis_ref: ref_type('Evidence')
    source_refs: Annotated[list[Reference], Field(min_length=1)]


class ArchitectAreaResultGroup(StrictRecord):
    local_key: TextId
    floor_count: Annotated[int, Field(gt=0)]
    modeled_area: ValueState[Measured]


class ArchitectAreaReport(StrictRecord):
    groups: list[ArchitectAreaResultGroup]
    total: ValueState[Measured]
    issues: list[TextId]


def calculate_area_schedule(data):
    unique_refs(data.source_refs)
    if data.unit != 'm²': raise ValueError('Area method requires explicit modeled m²; no unit conversion')
    if len({row.local_key for row in data.groups}) != len(data.groups): raise ValueError('Area schedule repeats a group identity')
    floors, result, issues, missing = set(), [], [], {}
    total = Fraction()
    for row in data.groups:
        overlap = len(set(row.floor_keys)) != len(row.floor_keys) or bool(floors.intersection(row.floor_keys))
        floors.update(row.floor_keys)
        if overlap: issues.append('overlapping_floor_coverage')
        state = row.area_per_floor
        if state.state == 'known' and state.value.unit == data.unit and not overlap:
            amount = decimal_fraction(state.value.value)
            if amount < 0: raise ValueError('Modeled floor area cannot be negative')
            amount *= len(row.floor_keys); total += amount
            area = {'state': 'known', 'value': {'value': exact_decimal(amount), 'unit': data.unit, 'basis_ref': state.value.basis_ref}}
        else:
            issues.append('incomplete_or_incompatible_area_group')
            refs = row.missing_evidence_refs + (state.missing_refs if state.state == 'unknown' else [])
            if state.state == 'known': refs.append(state.value.basis_ref)
            for ref in refs: missing[ref.key()] = ref
            area = {'state': 'unknown', 'reason_code': 'area_group_requires_original_compatible_nonoverlapping_inputs', 'missing_refs': refs}
        result.append({'local_key': row.local_key, 'floor_count': len(row.floor_keys), 'modeled_area': area})
    complete = {'state': 'known', 'value': {'value': exact_decimal(total), 'unit': data.unit, 'basis_ref': data.total_basis_ref}}
    if issues: complete = {'state': 'unknown', 'reason_code': 'modeled_total_area_incomplete', 'missing_refs': list(missing.values())}
    return ArchitectAreaReport(groups=result, total=complete, issues=sorted(set(issues)))


def register_architect_area_method(registry):
    basis = Path(__file__).with_name('ARCHITECT_AREA.md')
    registry.register({'method_ref': AREA_METHOD, 'namespace': 'micro_local', 'effect_kind': 'pure_calculation',
        'invocation': 'trusted_processor', 'input_schema_id': AREA_METHOD.id + ':input', 'output_schema_id': AREA_METHOD.id + ':report',
        'action_ids': ['ARCHITECT-A05'], 'unit_rule': 'exact_declared_units_no_conversion',
        'support_domain': ['Disjoint explicit floor identities with equal modeled area per floor within each group',
                           'Exact m² sums; any missing, overlapping or incompatible group makes the total unknown'],
        'basis_locator': 'src/methods/ARCHITECT_AREA.md', 'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration': 'mathematical_only', 'limitations': ['No statutory floor area, structure, fire, planning or functional certification',
            'No inferred site measurements, geometry, floors or unit conversions; supplied assumptions remain assumptions']},
        ArchitectAreaInput, ArchitectAreaReport, calculate_area_schedule)
