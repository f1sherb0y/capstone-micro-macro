"""Only actual native supply decisions and the buyer's earlier failed selections."""
from pydantic import Field
from src.actions.contracts.common import TextId, ref_type
from src.actions.contracts.qs_cost_objects import CostSource


class NativeSupplySelectionObservation(CostSource):
    ref: ref_type('NativeSupplySelectionObservation')
    organization_id: TextId
    project_id: TextId
    tick: int = Field(ge=1)
    supplier_decisions: list[dict] = Field(min_length=1)
    prior_failures: list[dict]
