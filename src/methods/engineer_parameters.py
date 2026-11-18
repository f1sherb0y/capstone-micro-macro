"""Exact finite parameter domain validation; no physical engineering conclusion."""
import hashlib
from pathlib import Path
from typing import Literal

from src.actions.contracts.common import DecimalString, Measured, Reference, StrictRecord, TextId, ValueState, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.pricing import decimal_fraction

PARAMETER_METHOD = ref_type('Method')(kind='Method', id='micro.engineer.finite_parameter_domain', version='1')


class EngineerParameterInput(StrictRecord):
    parameter_ref: ref_type('ValidatedEngineeringParameter')
    catalog_ref: ref_type('EngineeringParameterCatalog')
    value_kind: Literal['measured', 'catalog']
    value: ValueState[Measured] | ValueState[ref_type('CatalogOption')]
    unit: TextId | None
    minimum: DecimalString | None
    maximum: DecimalString | None
    step: DecimalString | None
    option_refs: list[ref_type('CatalogOption')]
    source_refs: list[Reference]


class EngineerParameterReport(StrictRecord):
    finding: Literal['within_declared_domain', 'outside_declared_domain', 'unknown']
    missing_field_paths: list[TextId]


def validate_parameter(data):
    unique_refs(data.source_refs); unique_refs(data.option_refs)
    if data.value.state != 'known':
        return EngineerParameterReport(finding='unknown', missing_field_paths=['value'])
    value = data.value.value
    if data.value_kind == 'catalog':
        valid = getattr(value, 'kind', None) == 'CatalogOption' and value.key() in {r.key() for r in data.option_refs}
    else:
        if not isinstance(value, Measured) or value.unit != data.unit:
            return EngineerParameterReport(finding='outside_declared_domain', missing_field_paths=[])
        missing = [field for field in ('minimum', 'maximum', 'step') if getattr(data, field) is None]
        if missing: return EngineerParameterReport(finding='unknown', missing_field_paths=missing)
        low, high, step = (decimal_fraction(getattr(data, field)) for field in ('minimum', 'maximum', 'step'))
        if low > high or step <= 0: raise ValueError('Parameter domain requires ordered bounds and positive precision')
        number = decimal_fraction(value.value)
        valid = low <= number <= high and ((number - low) / step).denominator == 1
    return EngineerParameterReport(finding='within_declared_domain' if valid else 'outside_declared_domain', missing_field_paths=[])


def register_engineer_parameter_method(registry):
    basis = Path(__file__).with_name('ENGINEER_PARAMETERS.md')
    registry.register({'method_ref': PARAMETER_METHOD, 'namespace': 'micro_local', 'effect_kind': 'pure_calculation',
        'invocation': 'trusted_processor', 'input_schema_id': PARAMETER_METHOD.id + ':input',
        'output_schema_id': PARAMETER_METHOD.id + ':report', 'action_ids': ['ENGINEER-A05', 'ENGINEER-A09'],
        'support_domain': ['Exact declared numeric unit, inclusive finite bounds and grid anchored at minimum',
                           'Exact immutable finite catalog selection; missing input remains unknown'],
        'unit_rule': 'exact_declared_units_no_conversion', 'basis_locator': 'src/methods/ENGINEER_PARAMETERS.md',
        'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(), 'calibration': 'mathematical_only',
        'limitations': ['Only parameter domain membership, no physical calculation, compatibility or safety judgment',
                        'No inferred parameters, unit conversions or professional/regulatory approval']},
        EngineerParameterInput, EngineerParameterReport, validate_parameter)
