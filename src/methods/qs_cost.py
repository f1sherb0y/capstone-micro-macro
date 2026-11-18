"""Exact arithmetic on original quantities/rates and declared physical coverage."""
from fractions import Fraction
import hashlib
from pathlib import Path
from typing import Annotated

from pydantic import Field, model_validator

from src.actions.contracts.common import Measured, Money, Reference, StrictRecord, TextId, ValueState, ref_type
from src.actions.contracts.owner_study_objects import unique_refs
from src.methods.pricing import decimal_fraction, exact_decimal

COST_METHOD = ref_type('Method')(kind='Method', id='micro.qs.declared_quantity_cost', version='1')


class CostArithmeticLine(StrictRecord):
    line_key: TextId
    quantity: ValueState[Measured]
    unit_rate: ValueState[Money] | None
    price_unit: TextId | None
    price_applicable: bool
    coverage_keys: Annotated[list[TextId], Field(min_length=1)]
    basis_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]


class CostArithmeticInput(StrictRecord):
    currency: TextId
    lines: Annotated[list[CostArithmeticLine], Field(min_length=1)]
    source_refs: Annotated[list[Reference], Field(min_length=1)]

    @model_validator(mode='after')
    def original_domain(self):
        unique_refs(self.source_refs)
        if len({r.line_key for r in self.lines}) != len(self.lines):
            raise ValueError('Cost arithmetic repeats a line identity')
        for row in self.lines:
            if len(set(row.coverage_keys)) != len(row.coverage_keys):
                raise ValueError('Cost arithmetic repeats a coverage key within a line')
            if row.quantity.state == 'known' and decimal_fraction(row.quantity.value.value) < 0:
                raise ValueError('Negative design quantities require a separate correction method')
            if row.unit_rate is not None and row.unit_rate.state == 'known' and decimal_fraction(row.unit_rate.value.value) < 0:
                raise ValueError('Negative prices require a separate correction method')
        return self


class CostArithmeticResultLine(StrictRecord):
    line_key: TextId
    quantity: ValueState[Measured]
    amount: ValueState[Money]
    issues: list[TextId]
    basis_refs: list[ref_type('Evidence')]


class CostArithmeticReport(StrictRecord):
    lines: list[CostArithmeticResultLine]
    known_subtotal: ValueState[Money]
    complete_total: Money | None


def unknown(code):
    return {'state': 'unknown', 'reason_code': code, 'missing_refs': []}


def calculate_cost(data):
    occurrences = {}
    for line in data.lines:
        for key in line.coverage_keys:
            occurrences.setdefault(key, set()).add(line.line_key)
    overlapping = set().union(*(rows for rows in occurrences.values() if len(rows) > 1))
    lines, total, known_count = [], Fraction(), 0
    for line in data.lines:
        issues = []
        if line.quantity.state != 'known': issues.append('quantity')
        if line.unit_rate is None or line.unit_rate.state != 'known': issues.append('price')
        if line.unit_rate is not None and not line.price_applicable: issues.append('price')
        if line.quantity.state == 'known' and line.price_unit is not None and line.quantity.value.unit != line.price_unit:
            issues.append('price')
        if line.unit_rate is not None and line.unit_rate.state == 'known' and line.unit_rate.value.currency != data.currency:
            issues.append('price')
        if line.line_key in overlapping: issues.append('coverage')
        issues = list(dict.fromkeys(issues))
        amount = unknown('cost_' + '_'.join(issues))
        if not issues:
            value = decimal_fraction(line.quantity.value.value) * decimal_fraction(line.unit_rate.value.value)
            total += value; known_count += 1
            amount = {'state': 'known', 'value': {'value': exact_decimal(value), 'currency': data.currency, 'basis_ref': line.basis_refs[0]}}
        lines.append(CostArithmeticResultLine(line_key=line.line_key, quantity=line.quantity, amount=amount,
            issues=issues, basis_refs=line.basis_refs))
    money = Money(value=exact_decimal(total), currency=data.currency, basis_ref=data.lines[0].basis_refs[0])
    return CostArithmeticReport(lines=lines,
        known_subtotal={'state': 'known', 'value': money} if known_count else unknown('no_computable_cost_lines'),
        complete_total=money if known_count == len(lines) else None)


def register_qs_cost_method(registry):
    basis = Path(__file__).with_name('QS_COST.md')
    registry.register({'method_ref': COST_METHOD, 'namespace': 'micro_local', 'effect_kind': 'pure_calculation',
        'invocation': 'trusted_processor', 'input_schema_id': 'micro-qs-cost.v1:input', 'output_schema_id': 'micro-qs-cost.v1:report',
        'action_ids': ['QS-A04'], 'unit_rule': 'exact_declared_units_no_conversion',
        'support_domain': ['Original nonnegative measured or explicitly sourced proxy quantities', 'One explicit currency',
            'Exact quantity times applicable sourced rate', 'Disjoint declared physical coverage; overlap blocks affected amounts',
            'Partial known subtotal; complete total only when every declared line is computable'],
        'basis_locator': 'src/methods/QS_COST.md', 'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(),
        'calibration': 'mathematical_only', 'limitations': ['No geometry measurement, proxy inference, FX, unit/time/region conversion or market calibration',
            'No budget approval, contract price, debt, payment or resource effect; host records remain independently authorized']},
        CostArithmeticInput, CostArithmeticReport, calculate_cost)
