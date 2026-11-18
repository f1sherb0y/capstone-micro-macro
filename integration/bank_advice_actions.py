"""Prepare original BANK-A13 without inventing borrower or funding-plan facts."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import BaseModel

from integration.bank_intake_actions import BankIntakeActionAssembler, PreparedBankIntake
from src.actions.contracts.bank_advice_objects import (
    AdviceAuthorizationView, AdviceBriefView, AdviceForecastView, AdviceMethodView,
    AdviceSubjectView, bank_advice_schemas,
)
from src.actions.contracts.common import Reference
from src.actions.contracts.owner_study_objects import unique_refs


def validate_advice_selection(action_input, *, organization_id, resolve):
    """Check exact disclosed sources; feasibility and missing data stay in the processor."""
    def read(ref, schema):
        row = resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Advice selection changes an original typed source reference')
        return row

    brief = read(action_input.brief_ref, AdviceBriefView)
    advisory = read(action_input.advisory_scope_ref, AdviceAuthorizationView)
    method = read(action_input.feasibility_method_ref, AdviceMethodView)
    if (advisory.lender_id != organization_id or method.lender_id != organization_id
            or advisory.owner_id != brief.owner_id or advisory.brief_ref.key() != brief.ref.key()
            or action_input.scope_ref != brief.scope_ref or advisory.scope_ref != brief.scope_ref
            or action_input.borrower != brief.borrower):
        raise ValueError('Advice selection changes original lender, owner, brief, scope or borrower state')
    selected = [(ref, AdviceSubjectView) for ref in [*action_input.option_refs, *action_input.demand_refs]]
    selected.extend((ref, AdviceForecastView) for ref in action_input.cashflow_refs)
    if action_input.funding_plan.state == 'known':
        selected.append((action_input.funding_plan.value, AdviceSubjectView))
    for ref, schema in selected:
        row = read(ref, schema)
        if row.owner_id != brief.owner_id or row.brief_ref.key() != brief.ref.key() or row.scope_ref != brief.scope_ref:
            raise ValueError('Advice subject changes original owner, brief version or scope')
    # Preserve unknown funding/borrower states. Do not estimate a range,
    # select assumptions or turn an indicative opinion into an A04 offer.


@dataclass(frozen=True)
class PreparedBankAdvice(PreparedBankIntake):
    """Local scenario advice, without reserved capacity, funds or financing approval."""


class BankAdviceActionAssembler(BankIntakeActionAssembler):
    ACTION_ID = 'BANK-A13'
    SOURCE_SCHEMAS = staticmethod(bank_advice_schemas)

    def build(self, context, *, scope_ref, borrower, brief_ref, option_refs, demand_refs,
            cashflow_refs, funding_plan, feasibility_method_ref, advisory_scope_ref):
        def supplied(value):
            return value.model_dump(mode='python') if isinstance(value, BaseModel) else deepcopy(value)

        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in
            (('option_refs', option_refs), ('demand_refs', demand_refs), ('cashflow_refs', cashflow_refs))}
        for refs in selected.values():
            unique_refs(refs)
        return self._prepare_supplied_snapshot(context, input_values={**selected,
            'scope_ref': supplied(scope_ref), 'borrower': supplied(borrower),
            'brief_ref': Reference.model_validate(brief_ref), 'funding_plan': supplied(funding_plan),
            'feasibility_method_ref': Reference.model_validate(feasibility_method_ref),
            'advisory_scope_ref': Reference.model_validate(advisory_scope_ref)},
            prepared_type=PreparedBankAdvice, validate_sources=validate_advice_selection)
