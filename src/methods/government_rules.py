"""Exact declared rule checks on disclosed facts and scoped professional evidence."""
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import model_validator

from src.actions.contracts.common import DecimalString, Measured, Reference, StrictRecord, TextId, ValueState, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.pricing import decimal_fraction

GOV_RULE_METHOD = ref_type('Method')(kind='Method', id='micro.government.declared_rule_check', version='1')


class GovRuleInput(StrictRecord):
    criterion: Literal['numeric_interval', 'code_equals', 'professional_evidence']
    applicable: ValueState[bool]
    measured_value: ValueState[Measured] | None
    code_value: ValueState[TextId] | None
    unit: TextId | None
    minimum: DecimalString | None
    maximum: DecimalString | None
    expected_code: TextId | None
    professional_findings: list[Literal['conforms', 'nonconforms', 'unknown']]
    professional_complete: bool
    source_refs: list[Reference]

    @model_validator(mode='after')
    def declared_domain(self):
        unique_refs(self.source_refs)
        if self.criterion == 'numeric_interval':
            if self.unit is None or (self.minimum is None and self.maximum is None):
                raise ValueError('Numeric rule must declare its exact unit and at least one bound')
            if self.minimum is not None and self.maximum is not None and decimal_fraction(self.minimum) > decimal_fraction(self.maximum):
                raise ValueError('Original numeric rule interval is reversed')
        if self.criterion == 'code_equals' and self.expected_code is None:
            raise ValueError('Code rule must declare its original expected value')
        return self


class GovRuleReport(StrictRecord):
    finding: Literal['conforms', 'nonconforms', 'unknown', 'not_applicable']
    gaps: list[TextId]


def check_declared_rule(data):
    if data.applicable.state != 'known':
        return GovRuleReport(finding='unknown', gaps=['applicability'])
    if not data.applicable.value:
        return GovRuleReport(finding='not_applicable', gaps=[])
    findings, gaps = list(data.professional_findings), []
    if not data.professional_complete:
        gaps.append('professional_evidence')
    if data.criterion == 'numeric_interval':
        if data.measured_value is None or data.measured_value.state != 'known':
            gaps.append('measured_value')
        elif data.measured_value.value.unit != data.unit:
            gaps.append('exact_measurement_unit')
        else:
            value = decimal_fraction(data.measured_value.value.value)
            valid = ((data.minimum is None or value >= decimal_fraction(data.minimum))
                and (data.maximum is None or value <= decimal_fraction(data.maximum)))
            findings.append('conforms' if valid else 'nonconforms')
    elif data.criterion == 'code_equals':
        if data.code_value is None or data.code_value.state != 'known':
            gaps.append('code_value')
        else:
            findings.append('conforms' if data.code_value.value == data.expected_code else 'nonconforms')
    elif not findings:
        gaps.append('professional_evidence')
    if 'nonconforms' in findings:
        return GovRuleReport(finding='nonconforms', gaps=gaps)
    if 'unknown' in findings or gaps or not findings:
        return GovRuleReport(finding='unknown', gaps=gaps or ['professional_finding'])
    return GovRuleReport(finding='conforms', gaps=[])


def register_government_rule_method(registry):
    basis = Path(__file__).with_name('GOVERNMENT_RULES.md')
    registry.register({'method_ref': GOV_RULE_METHOD, 'namespace': 'micro_local', 'effect_kind': 'pure_calculation',
        'invocation': 'trusted_processor', 'input_schema_id': 'micro-gov-rule.v1:input', 'output_schema_id': 'micro-gov-rule.v1:report',
        'action_ids': ['GOV-A04', 'GOV-A06', 'GOV-A08', 'GOV-A10'], 'unit_rule': 'exact_declared_units_no_conversion',
        'support_domain': ['Exact inclusive numeric intervals and disclosed code equality',
            'Original applicability decisions and independently verified scoped professional findings',
            'Unknown facts, missing professional coverage and contradictory findings remain explicit'],
        'basis_locator': 'src/methods/GOVERNMENT_RULES.md', 'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration': 'mathematical_only', 'limitations': ['No hidden-state access, legal rule inference, unit conversion or physical safety inference',
            'No quality-score substitute for necessary evidence, no regulatory decision or permission effect',
            'Professional verification, applicability and rule provenance require independent authorized host records']},
        GovRuleInput, GovRuleReport, check_declared_rule)
