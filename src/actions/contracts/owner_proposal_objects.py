"""Closed OWN-A16 host projections for private, bounded proposal research."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import Measured, Money, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_objects import SourcedOwnerProjection, OwnerCaseView, OwnerObjectiveView, OwnerDemandObservationView, OwnerManagementCapacityView, OwnerOrganizationView


Intervention = Literal["new_build", "alter", "extend", "non_build"]


class ProposalScaleRange(StrictRecord):
    lower: ValueState[Measured]
    upper: ValueState[Measured]
    basis_ref: ref_type("ScaleMethod")

    @model_validator(mode="after")
    def ordered(self):
        if self.lower.state == self.upper.state == "known":
            if self.lower.value.unit != self.upper.value.unit or Decimal(self.lower.value.value) > Decimal(self.upper.value.value):
                raise ValueError("Proposal scale must use ordered bounds in the same unit")
        return self


class ProposalBriefDraft(StrictRecord):
    purpose_ref: ref_type("PurposeProfile")
    region_ids: Annotated[list[TextId], Field(min_length=1)]
    intervention: Intervention
    scale: ProposalScaleRange
    delivery_window_ref: ref_type("TimeWindow")
    alternatives: list[ref_type("TechnologyCandidate")]
    rights_refs: list[ref_type("RightsEvidence")]
    unresolved_refs: list[ref_type("Issue")]

    @model_validator(mode="after")
    def unique_scope(self):
        if len(set(self.region_ids)) != len(self.region_ids):
            raise ValueError("Proposal region repeated")
        for rows in (self.alternatives, self.rights_refs, self.unresolved_refs):
            if len({(ref.kind, ref.id) for ref in rows}) != len(rows):
                raise ValueError("Proposal physical identity repeated across versions")
        return self


class ProposalCaseView(OwnerCaseView):
    prior_brief_refs: list[ref_type("OwnerBrief")]


class ProposalInternalNeedView(SourcedOwnerProjection):
    ref: ref_type("InternalNeed")
    organization_id: TextId
    case_ref: ref_type("OwnerCase")
    region_id: TextId
    use_code: TextId
    signal_code: TextId
    measure: ValueState[Measured]
    research_permitted: ValueState[bool]
    observed_at: TimePoint
    available_at: TimePoint
    effective_window: TimeWindow


class ProposalFundingView(SourcedOwnerProjection):
    ref: ref_type("FundingPosition")
    organization_id: TextId
    as_of: TimePoint
    coverage: Literal["complete", "partial", "unknown"]
    actual_cash: ValueState[Money]
    committed_cash: ValueState[Money]
    restricted_cash: ValueState[Money]
    deduction_policy: ValueState[Literal["disjoint_committed_and_restricted"]]


class ProposalPurposeView(SourcedOwnerProjection):
    ref: ref_type("PurposeProfile")
    organization_id: TextId
    template: Literal["investment_return", "own_use", "public_service"]
    use_code: TextId
    asset_kind: TextId
    effective_window: TimeWindow


class ProposalTechnologyView(SourcedOwnerProjection):
    ref: ref_type("TechnologyCandidate")
    purpose_ref: ref_type("PurposeProfile")
    region_ids: list[TextId]
    interventions: list[Intervention]
    research_permitted: ValueState[bool]
    available_at: TimePoint
    effective_window: TimeWindow


class ProposalRightsView(SourcedOwnerProjection):
    ref: ref_type("RightsEvidence")
    case_ref: ref_type("OwnerCase")
    purpose_ref: ref_type("PurposeProfile")
    region_ids: list[TextId]
    status: Literal["current_right", "prospective_route", "excluded"]
    holder_organization_id: ValueState[TextId]
    research_permitted: ValueState[bool]
    available_at: TimePoint
    effective_window: TimeWindow


class ProposalIssueView(SourcedOwnerProjection):
    ref: ref_type("Issue")
    case_ref: ref_type("OwnerCase")
    purpose_ref: ref_type("PurposeProfile")
    check_code: TextId
    status: Literal["unresolved", "resolved"]
    available_at: TimePoint
    effective_window: TimeWindow


class ProposalScaleMethodView(SourcedOwnerProjection):
    ref: ref_type("ScaleMethod")
    purpose_ref: ref_type("PurposeProfile")
    asset_kind: TextId
    interventions: list[Intervention]
    algorithm_code: TextId
    applicability: Literal["range", "not_applicable"]
    minimum: ValueState[Measured]
    maximum: ValueState[Measured]
    applicability_rule_ref: ref_type("Rule") | None
    effective_window: TimeWindow

    @model_validator(mode="after")
    def explicit_applicability(self):
        if self.applicability == "not_applicable":
            if self.applicability_rule_ref is None or any(
                state.state != "not_applicable" or state.rule_ref != self.applicability_rule_ref
                for state in (self.minimum, self.maximum)
            ):
                raise ValueError("Non-applicable method bounds require the same explicit rule")
        elif self.applicability_rule_ref is not None:
            raise ValueError("Applicable scale cannot declare a non-applicability rule")
        return self


class ProposalApplicabilityRuleView(SourcedOwnerProjection):
    ref: ref_type("Rule")
    purpose_ref: ref_type("PurposeProfile")
    asset_kind: TextId
    interventions: list[Intervention]
    rule_code: Literal["proposal_scale_not_applicable"]
    effective_window: TimeWindow


class ProposalCandidateView(SourcedOwnerProjection):
    ref: ref_type("ProposalCandidate")
    local_key: TextId
    organization_id: TextId
    case_ref: ref_type("OwnerCase")
    objective_ref: ref_type("OwnerObjective")
    brief: ProposalBriefDraft
    prior_brief_ref: ref_type("OwnerBrief") | None
    demand_refs: list[ref_type("DemandObservation")]
    internal_need_refs: list[ref_type("InternalNeed")]
    research_permitted: ValueState[bool]
    priority: ValueState[int]
    review_cost: ValueState[Money]
    review_effort: ValueState[Measured]
    available_at: TimePoint
    effective_window: TimeWindow


class ProposalSpaceView(SourcedOwnerProjection):
    ref: ref_type("ProposalSpace")
    organization_id: TextId
    case_ref: ref_type("OwnerCase")
    objective_ref: ref_type("OwnerObjective")
    policy: Literal["evaluate", "no_proposal"]
    mode: Literal["propose", "revise"]
    algorithm_code: TextId
    maximum_briefs: ValueState[Annotated[int, Field(ge=0)]]
    allowed_purpose_refs: list[ref_type("PurposeProfile")]
    allowed_region_ids: list[TextId]
    allowed_interventions: list[Intervention]
    allowed_technology_refs: list[ref_type("TechnologyCandidate")]
    candidate_refs: list[ref_type("ProposalCandidate")]
    capacity_ref: ref_type("ManagementCapacity")
    available_at: TimePoint
    effective_window: TimeWindow


class ProposalPriorBriefView(SourcedOwnerProjection):
    ref: ref_type("OwnerBrief")
    organization_id: TextId
    case_ref: ref_type("OwnerCase")
    objective_ref: ref_type("OwnerObjective")
    brief: ProposalBriefDraft
    status: Literal["active", "superseded", "withdrawn"]
    available_at: TimePoint
    effective_window: TimeWindow


def owner_proposal_schemas():
    registry = common_projection_schemas()
    for kind, schema in (
        ("Organization", OwnerOrganizationView), ("OwnerCase", ProposalCaseView), ("OwnerObjective", OwnerObjectiveView),
        ("DemandObservation", OwnerDemandObservationView), ("InternalNeed", ProposalInternalNeedView), ("FundingPosition", ProposalFundingView),
        ("ManagementCapacity", OwnerManagementCapacityView), ("PurposeProfile", ProposalPurposeView), ("ProposalSpace", ProposalSpaceView),
        ("ProposalCandidate", ProposalCandidateView), ("TechnologyCandidate", ProposalTechnologyView), ("RightsEvidence", ProposalRightsView),
        ("Issue", ProposalIssueView), ("ScaleMethod", ProposalScaleMethodView), ("Rule", ProposalApplicabilityRuleView),
        ("OwnerBrief", ProposalPriorBriefView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
