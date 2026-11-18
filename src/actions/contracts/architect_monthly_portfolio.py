"""Private selection portfolio: selected appointments are not delivered services."""
from typing import Literal
from pydantic import Field
from src.actions.contracts.common import Measured, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ref_type
from src.methods.models import Digest


class PortfolioEntry(StrictRecord):
    organization_id: TextId
    project_id: TextId
    region: TextId
    client_organization_id: TextId
    tick: int = Field(ge=1)
    event_id: TextId
    source_event_sha256: Digest
    appointment_identity: dict
    appointment_result_sha256: Digest
    receipt_record_sha256: Digest
    status: Literal['selected_and_privately_confirmed'] = 'selected_and_privately_confirmed'


class MonthlyPortfolioPolicy(StrictRecord):
    ref: ref_type('MonthlyPortfolioPolicy')
    organization_id: TextId
    scope: ScopeRef
    authority_ref: ref_type('Authorization')
    effective_window: TimeWindow
    permitted_regions: list[TextId]
    minimum_market_demand: Measured
    minimum_free_ratio: Measured
    use: Literal['private_selection_portfolio_only']
    evidence_refs: list[ref_type('Evidence')]


class MonthlyPortfolioObservation(StrictRecord):
    ref: ref_type('MonthlyPortfolioObservation')
    organization_id: TextId
    scope: ScopeRef
    as_of: TimePoint
    market_demand: Measured
    native_free_ratio: Measured
    selected_entries: list[PortfolioEntry]
    prior_own_outcomes: list[dict]
    evidence_refs: list[ref_type('Evidence')]


class MonthlyPortfolioJudgment(StrictRecord):
    schema_version: Literal['architect-monthly-portfolio-judgment.v1'] = 'architect-monthly-portfolio-judgment.v1'
    operation: Literal['build_cross_region_reputation'] = 'build_cross_region_reputation'
    participate: bool
    market_demand: Measured
    native_free_ratio: Measured
    market_gate: bool
    capacity_gate: bool
    selected_entries: list[PortfolioEntry]
    new_entry_event_ids: list[TextId]
    adopted_entries: list[PortfolioEntry]
    consumed_monthly_event_ids: list[TextId]
    interpretation: TextId
