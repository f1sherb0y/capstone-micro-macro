"""Prepare original BANK-A01 from visible portfolio, capacity and strategy signals."""
from dataclasses import dataclass

from integration.bank_intake_actions import BankIntakeActionAssembler, PreparedBankIntake
from src.actions.contracts.bank_credit_objects import CreditLendingCapacityView
from src.actions.contracts.bank_strategy_objects import (
    StrategyMarketView, StrategyObligationView, StrategyPolicyView, StrategyPortfolioView,
    StrategySpaceView, bank_strategy_schemas,
)
from src.actions.contracts.common import Reference
from src.actions.contracts.owner_study_objects import unique_refs


def validate_strategy_selection(action_input, *, organization_id, resolve):
    """Check source ownership without recalculating capacity or choosing a strategy."""
    def read(ref, schema):
        row = resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Strategy selection changes an original typed source reference')
        return row

    portfolio = read(action_input.portfolio_ref, StrategyPortfolioView)
    capacity = read(action_input.capacity_ref, CreditLendingCapacityView)
    space = read(action_input.strategy_space_ref, StrategySpaceView)
    if (any(row.lender_id != organization_id for row in (portfolio, capacity, space))
            or capacity.portfolio_ref.key() != portfolio.ref.key()):
        raise ValueError('Strategy selection changes original bank, capacity portfolio or strategy space')
    for refs, schema, owner_field in (
            (action_input.obligation_refs, StrategyObligationView, 'lender_id'),
            (action_input.market_refs, StrategyMarketView, 'recipient_lender_id'),
            (action_input.policy_refs, StrategyPolicyView, 'lender_id')):
        for ref in refs:
            row = read(ref, schema)
            if getattr(row, owner_field) != organization_id:
                raise ValueError('Strategy source changes original lender or private signal recipient')
    # Candidate completeness, current occupancy, original signals and eligibility
    # stay in the processor. Retaining a strategy needs no new candidate here;
    # investigating neither reserves capacity nor changes existing contracts.


@dataclass(frozen=True)
class PreparedBankStrategy(PreparedBankIntake):
    """Local market/portfolio strategy invocation without existing-term or funding effects."""


class BankStrategyActionAssembler(BankIntakeActionAssembler):
    ACTION_ID = 'BANK-A01'
    SOURCE_SCHEMAS = staticmethod(bank_strategy_schemas)

    def build(self, context, *, portfolio_ref, capacity_ref, obligation_refs, market_refs,
            policy_refs, strategy_space_ref):
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in
            (('obligation_refs', obligation_refs), ('market_refs', market_refs), ('policy_refs', policy_refs))}
        for refs in selected.values():
            unique_refs(refs)
        return self._prepare_supplied_snapshot(context, input_values={**selected,
            'portfolio_ref': Reference.model_validate(portfolio_ref),
            'capacity_ref': Reference.model_validate(capacity_ref),
            'strategy_space_ref': Reference.model_validate(strategy_space_ref)},
            prepared_type=PreparedBankStrategy, validate_sources=validate_strategy_selection)
