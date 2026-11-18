"""A bounded private review of actually received native investment candidates."""
from pydantic import Field
from src.actions.contracts.common import StrictRecord, TextId, DecimalString
from src.methods.models import Digest


class OwnerPipelinePolicy(StrictRecord):
    organization_id: TextId
    minimum_market_demand: DecimalString
    maximum_prior_screens_before_portfolio_review: int = Field(ge=1, le=2, strict=True)
    authorized_ticks: list[int] = Field(min_length=1)
    purpose: str = 'review_received_native_candidates_only'


class OwnerPipelineJudgment(StrictRecord):
    organization_id: TextId
    tick: int = Field(ge=1, strict=True)
    participate: bool
    reason_code: TextId
    market_demand: DecimalString
    minimum_market_demand: DecimalString
    candidate_count: int = Field(ge=1)
    prior_completed_screens: int = Field(ge=0)
    candidate_source_sha256: Digest
    candidate_task_keys: list[TextId] = Field(min_length=1)
    investment_recommendations: list[TextId]
    consumed_event_ids: list[TextId]
    formal_investment_authorized: bool = False
