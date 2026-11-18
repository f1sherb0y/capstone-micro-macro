"""Optional sourced monthly constraints on original professional discovery."""
from pydantic import Field
from src.actions.contracts.common import StrictRecord,TextId,ScopeRef,TimePoint,Measured,ref_type


class ProfessionalOutreachLimits(StrictRecord):
    observation_ref: ref_type('OutreachObservation')
    minimum_market_demand: Measured
    maximum_prior_outreach: int = Field(ge=1)


class ProfessionalOutreachObservation(StrictRecord):
    ref: ref_type('OutreachObservation')
    organization_id: TextId
    scope: ScopeRef
    as_of: TimePoint
    market_demand: Measured
    prior_outreach_count: int = Field(ge=0)
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)
