"""One explicit initial cash disclosure for composed synthetic source builders."""
from decimal import Decimal
from typing import Literal

from pydantic import model_validator

from src.actions.contracts.common import DecimalString, StrictRecord, TextId


class InitialOwnerFunding(StrictRecord):
    organization_id: TextId
    currency: Literal['HKD'] = 'HKD'
    actual_cash: DecimalString
    restricted_cash: DecimalString
    old_due: DecimalString = '15000000'
    actual_paid: DecimalString = '0'

    @model_validator(mode='after')
    def supported_initial_disclosure(self):
        if (any(Decimal(v)<0 for v in (self.actual_cash,self.restricted_cash,self.old_due,self.actual_paid))
                or Decimal(self.restricted_cash)>Decimal(self.actual_cash)
                or self.old_due!='15000000' or self.actual_paid!='0'):
            raise ValueError('Initial shared cash must retain the declared 15m unpaid old obligation')
        return self


def initial_owner_funding(value):
    return None if value is None else InitialOwnerFunding.model_validate(value).model_copy(deep=True)


def initial_owner_fundings(value):
    """Accept one or several independent declarations, never override duplicates."""
    values = [] if value is None else list(value) if isinstance(value, (list, tuple)) else [value]
    rows = [InitialOwnerFunding.model_validate(row).model_copy(deep=True) for row in values]
    if len({row.organization_id for row in rows}) != len(rows):
        raise ValueError('Initial funding declarations must identify distinct Owners')
    return {row.organization_id: row for row in rows}
