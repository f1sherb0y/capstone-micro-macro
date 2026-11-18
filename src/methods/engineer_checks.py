"""Declared synthetic interface-code check, never a safety assessment."""
import hashlib
from pathlib import Path
from typing import Literal

from src.actions.contracts.common import Reference, StrictRecord, TextId, ValueState, ref_type

ENGINEER_INTERFACE_METHOD = ref_type('Method')(kind='Method', id='micro.engineer.declared_interface_code', version='1')


class EngineerInterfaceInput(StrictRecord):
    requested_check: TextId
    left_code: ValueState[TextId]
    right_code: ValueState[TextId]
    source_refs: list[Reference]


class EngineerInterfaceReport(StrictRecord):
    result: Literal['satisfied', 'conflict', 'undetermined', 'out_of_scope']
    missing_field_paths: list[TextId]


def check_interface(data):
    if data.requested_check != 'synthetic_interface_code_equality':
        return EngineerInterfaceReport(result='out_of_scope', missing_field_paths=[])
    missing = [field for field in ('left_code', 'right_code') if getattr(data, field).state != 'known']
    if missing:
        return EngineerInterfaceReport(result='undetermined', missing_field_paths=missing)
    return EngineerInterfaceReport(result='satisfied' if data.left_code.value == data.right_code.value else 'conflict',
                                   missing_field_paths=[])


def register_engineer_interface_method(registry):
    basis = Path(__file__).with_name('ENGINEER_CHECKS.md')
    registry.register({'method_ref': ENGINEER_INTERFACE_METHOD, 'namespace': 'micro_local',
        'effect_kind': 'pure_calculation', 'invocation': 'trusted_processor',
        'input_schema_id': ENGINEER_INTERFACE_METHOD.id + ':input', 'output_schema_id': ENGINEER_INTERFACE_METHOD.id + ':report',
        'action_ids': ['ENGINEER-A13', 'ENGINEER-A05', 'ENGINEER-A06', 'ENGINEER-A08', 'ENGINEER-A09'], 'support_domain': ['Synthetic interface code equality with explicit input states',
            'Other requested checks explicitly out_of_scope; missing codes undetermined'],
        'unit_rule': 'exact_declared_units_no_conversion', 'basis_locator': 'src/methods/ENGINEER_CHECKS.md',
        'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(), 'calibration': 'synthetic_only',
        'limitations': ['Equal codes show only the declared synthetic interface rule',
            'No physical compatibility, structural safety, hidden-state access, technical or regulatory approval']},
        EngineerInterfaceInput, EngineerInterfaceReport, check_interface)
