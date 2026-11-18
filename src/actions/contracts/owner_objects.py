"""Read-only Owner A01 facts; screening rules are explicit scenario policy."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import (
    EvidenceRef, Measured, StrictRecord, TextId, TimePoint, TimeWindow,
    ValueState, ref_type,
)
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_monthly_demand import MonthlyOwnerDemandObservation


class SourcedOwnerProjection(StrictRecord):
    evidence_refs: Annotated[list[EvidenceRef], Field(min_length=1)]


class OwnerOrganizationView(SourcedOwnerProjection):
    ref: ref_type("Organization")


class OwnerSignalRule(StrictRecord):
    signal_code: TextId
    comparison: Literal["at_least", "at_most"]
    threshold: Measured


class OwnerObjectiveView(SourcedOwnerProjection):
    monthly_demand_observation_ref:ref_type('MonthlyOwnerDemandObservation')|None=None
    ref: ref_type("OwnerObjective")
    organization_id: TextId
    template: Literal["investment_return", "own_use", "public_service"]
    effective_window: TimeWindow
    allowed_region_ids: ValueState[list[TextId]]
    allowed_use_codes: ValueState[list[TextId]]
    signal_rules: ValueState[list[OwnerSignalRule]]
    maximum_observation_age: ValueState[Annotated[int, Field(ge=0)]]
    new_signal_choice: ValueState[Literal["create_case", "propose"]]
    allow_reopen: ValueState[bool]

    @model_validator(mode="after")
    def unique_rules(self):
        if self.signal_rules.state == "known":
            codes = [rule.signal_code for rule in self.signal_rules.value]
            if len(set(codes)) != len(codes):
                raise ValueError("Objective signal rule repeated")
        return self


class OwnerDemandObservationView(SourcedOwnerProjection):
    ref: ref_type("DemandObservation")
    source_ref: ref_type("Observation")
    region_id: TextId
    use_code: TextId
    signal_code: TextId
    measure: ValueState[Measured]
    research_permitted: ValueState[bool]
    observed_at: TimePoint
    learned_at: TimePoint
    effective_window: TimeWindow


class OwnerObservationSourceView(SourcedOwnerProjection):
    ref: ref_type("Observation")
    demand_ref: ref_type("DemandObservation")


class OwnerOpportunityView(SourcedOwnerProjection):
    ref: ref_type("Opportunity")
    region_id: TextId
    use_code: TextId
    observation_refs: list[ref_type("DemandObservation")]
    effective_window: TimeWindow
    learned_at: TimePoint
    status: ValueState[Literal["active", "withdrawn"]]
    research_permitted: ValueState[bool]


class OwnerCaseView(SourcedOwnerProjection):
    ref: ref_type("OwnerCase")
    organization_id: TextId
    objective_ref: ref_type("OwnerObjective")
    region_id: TextId
    use_code: TextId
    observation_refs: list[ref_type("DemandObservation")]
    opportunity_refs: list[ref_type("Opportunity")]
    status: Literal["active", "closed"]
    updated_at: TimePoint

    @model_validator(mode="after")
    def stable_associations(self):
        for values in (self.observation_refs, self.opportunity_refs):
            keys = [(ref.kind, ref.id) for ref in values]
            if len(set(keys)) != len(keys):
                raise ValueError("Case associates multiple versions of the same source")
        return self


class OwnerManagementLoad(StrictRecord):
    commitment_ref: ref_type("ResourceCommitment")
    window: TimeWindow
    quantity: Measured


class OwnerManagementCapacityView(SourcedOwnerProjection):
    ref: ref_type("ManagementCapacity")
    organization_id: TextId
    effective_window: TimeWindow
    total: ValueState[Measured]
    screening_requirement: ValueState[Measured]
    commitments: list[OwnerManagementLoad]

    @model_validator(mode="after")
    def consistent_load(self):
        ids = [(load.commitment_ref.kind, load.commitment_ref.id) for load in self.commitments]
        if len(set(ids)) != len(ids):
            raise ValueError("Management commitment counted more than once")
        quantities = [load.quantity for load in self.commitments]
        quantities.extend(state.value for state in (self.total, self.screening_requirement) if state.state == "known")
        if any(Decimal(value.value) < 0 for value in quantities):
            raise ValueError("Management quantities cannot be negative")
        return self


def owner_observation_schemas():
    registry = common_projection_schemas()
    registry.register_kind('MonthlyOwnerDemandObservation',MonthlyOwnerDemandObservation,str)
    for kind, schema in (
        ("Organization", OwnerOrganizationView), ("OwnerObjective", OwnerObjectiveView),
        ("DemandObservation", OwnerDemandObservationView), ("Observation", OwnerObservationSourceView),
        ("Opportunity", OwnerOpportunityView), ("OwnerCase", OwnerCaseView),
        ("ManagementCapacity", OwnerManagementCapacityView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
