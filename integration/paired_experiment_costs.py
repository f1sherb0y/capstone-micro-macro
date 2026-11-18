"""Explicit invocation cost evidence; never infer prices from token counts."""
from decimal import Decimal, localcontext
import re
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from src.actions.contracts.common import StrictRecord, TextId
from src.coordination.tasks import TaskConflict, task_digest


Digest = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]


class PairedInvocationCost(StrictRecord):
    """One complete invocation allocation from an independently checked source.

    The application's gate verifies the original source, allocation, currency,
    billed/estimated classification and coverage of every adapter attempt.
    """
    schema_version: Literal['paired-invocation-cost.v1'] = 'paired-invocation-cost.v1'
    identity_sha256: Digest
    audit_sha256: Digest | None
    model_version: TextId
    adapter_attempts: Annotated[int, Field(strict=True, ge=0)]
    record_id: TextId
    source_sha256: Digest
    kind: Literal['billed', 'estimated']
    currency: Annotated[str, StringConstraints(pattern=r'^[A-Z]{3}$')]
    amount: Annotated[Decimal, Field(ge=0, allow_inf_nan=False, max_digits=30, decimal_places=12)]

    @field_validator('amount', mode='before')
    @classmethod
    def original_decimal_amount(cls, value):
        # model_dump(mode='json') preserves Decimal as text. Restore that exact
        # representation when reading saved evidence; floats stay rejected.
        if isinstance(value, str):
            if re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', value) is None:
                raise ValueError('Cost amount requires finite decimal text')
            return Decimal(value)
        return value


def checked_paired_cost(value, *, identity, audit, model_version, adapter_attempts):
    """Check correlation only; actual source validation is separately mandatory."""
    cost = PairedInvocationCost.model_validate(value)
    cost = PairedInvocationCost.model_validate(cost.model_dump(mode='python'))
    if (cost.identity_sha256 != task_digest(identity.as_dict())
            or cost.audit_sha256 != (task_digest(audit) if audit is not None else None)
            or cost.model_version != model_version
            or adapter_attempts is not None and cost.adapter_attempts != adapter_attempts):
        raise TaskConflict('Paired cost evidence differs from its original invocation, audit or attempts')
    return cost.model_dump(mode='json')


def summarize_paired_costs(rows):
    """Sum independent invocation allocations without mixing kinds/currencies."""
    groups = {}
    missing = 0
    for row in rows:
        evidence = row.get('cost_evidence')
        if evidence is None:
            missing += 1
            continue
        cost = PairedInvocationCost.model_validate(evidence)
        groups.setdefault((cost.kind, cost.currency), []).append(cost.amount)
    totals = []
    for (kind, currency), amounts in sorted(groups.items()):
        with localcontext() as context:
            context.prec = max(28, max(value.adjusted() for value in amounts)
                - min(value.as_tuple().exponent for value in amounts) + len(str(len(amounts))) + 3)
            subtotal = format(sum(amounts, Decimal(0)), 'f')
        totals.append({'kind': kind, 'currency': currency, 'observed_task_count': len(amounts),
            'known_subtotal': subtotal,
            'total_for_observed_tasks': subtotal if len(amounts) == len(rows) else None})
    return {'missing_cost_task_count': missing, 'groups': totals,
        'scope': 'Observed tasks only; missing actions are separately reported. Estimates and billed costs stay separate.'}
