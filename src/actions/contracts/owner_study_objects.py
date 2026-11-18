"""Closed host projections for OWN-A02 bounded preliminary research."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import Measured, Money, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.owner_objects import OwnerCaseView, OwnerOrganizationView, SourcedOwnerProjection
from src.actions.contracts.owner_proposal_objects import ProposalFundingView, ProposalPriorBriefView


def unique_refs(values):
    if len({(ref.kind, ref.id) for ref in values}) != len(values):
        raise ValueError("Study projection repeats a physical identity across versions")


class StudyCaseView(OwnerCaseView):
    issue_refs: list[ref_type("Issue")]
    brief_refs: list[ref_type("OwnerBrief")]
    study_refs: list[ref_type("StudyPlan")]
    linked_project_ref: ref_type("Project") | None

    @model_validator(mode="after")
    def unique_history(self):
        for rows in (self.issue_refs, self.brief_refs, self.study_refs):
            unique_refs(rows)
        return self


class StudyIssueView(SourcedOwnerProjection):
    ref: ref_type("Issue")
    case_ref: ref_type("OwnerCase")
    scope: ScopeRef
    question_code: TextId
    status: Literal["unresolved", "resolved"]
    available_at: TimePoint
    effective_window: TimeWindow


class StudyWorkScopeView(SourcedOwnerProjection):
    ref: ref_type("WorkScope")
    case_ref: ref_type("OwnerCase")
    research_permitted: ValueState[bool]
    question_codes: Annotated[list[TextId], Field(min_length=1)]
    effective_window: TimeWindow


class StudyRequirementView(SourcedOwnerProjection):
    ref: ref_type("Requirement")
    case_ref: ref_type("OwnerCase")
    scope: ScopeRef
    verified: ValueState[bool]
    verified_at: TimePoint
    effective_window: TimeWindow


class StudyScopeChoice(StrictRecord):
    scope_ref: ScopeRef
    basis_refs: Annotated[list[ref_type("Evidence")], Field(min_length=1)]
    condition_refs: list[ref_type("Requirement")]


class StudyProposedTarget(StrictRecord):
    kind: Literal["proposed"]
    local_key: TextId
    scope_ref: ScopeRef


class StudyAllocation(StrictRecord):
    resource_ref: ref_type("ResourcePool")
    window_ref: ref_type("TimeWindow")
    quantity: Measured
    task_target: StudyProposedTarget


class StudyResourceLoad(StrictRecord):
    ref: ref_type("ResourceCommitment")
    quantity: Measured
    window: TimeWindow


class StudyResourceView(SourcedOwnerProjection):
    ref: ref_type("ResourcePool")
    organization_id: TextId
    authorization_ref: ref_type("Authorization")
    function_ref: ref_type("FunctionAssignment")
    supported_question_codes: ValueState[list[TextId]]
    qualified: ValueState[bool]
    research_permitted: ValueState[bool]
    total: ValueState[Measured]
    commitments: list[StudyResourceLoad]
    as_of: TimePoint
    coverage: Literal["complete", "partial", "unknown"]
    effective_window: TimeWindow

    @model_validator(mode="after")
    def one_physical_load(self):
        unique_refs([row.ref for row in self.commitments])
        return self


class StudyPriorPlanView(SourcedOwnerProjection):
    ref: ref_type("StudyPlan")
    organization_id: TextId
    case_ref: ref_type("OwnerCase")
    linked_project_ref: ref_type("Project") | None
    scope: ScopeRef
    remaining_work_refs: list[ref_type("WorkScope")]
    question_codes: Annotated[list[TextId], Field(min_length=1)]
    issue_refs: list[ref_type("Issue")]
    status: Literal["active", "completed", "failed", "stopped"]
    expenditure_cap: Money
    incurred_cost: ValueState[Money]
    obligation_refs: list[ref_type("Obligation")]
    information_basis_refs: Annotated[list[ref_type("Evidence")], Field(min_length=1)]
    available_at: TimePoint

    @model_validator(mode="after")
    def unique_associations(self):
        for rows in (self.remaining_work_refs, self.issue_refs, self.obligation_refs, self.information_basis_refs):
            unique_refs(rows)
        if len(set(self.question_codes)) != len(self.question_codes):
            raise ValueError("Prior study question repeated")
        return self


class StudyObligationView(SourcedOwnerProjection):
    ref: ref_type("Obligation")
    debtor_organization_id: TextId
    origin_case_ref: ref_type("OwnerCase")
    origin_study_ref: ref_type("StudyPlan")
    linked_project_ref: ref_type("Project") | None
    actual_due: Money
    actual_paid: Money
    as_of: TimePoint


class StudyReassessmentView(SourcedOwnerProjection):
    ref: ref_type("StudyReassessment")
    organization_id: TextId
    case_ref: ref_type("OwnerCase")
    prior_study_ref: ref_type("StudyPlan")
    question_codes: Annotated[list[TextId], Field(min_length=1)]
    trigger_code: Literal["changed_information", "scheduled_review", "failed_study_remedy"]
    changed_evidence_refs: list[ref_type("Evidence")]
    requirement_ref: ref_type("Requirement")
    permitted: ValueState[bool]
    available_at: TimePoint
    effective_window: TimeWindow


class StudyServiceOfferView(SourcedOwnerProjection):
    ref: ref_type("ServiceOffer")
    provider_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type("FunctionAssignment")
    authority_ref: ref_type("Authorization")
    authority_action_id: Literal["ARCHITECT-A02", "ENGINEER-A02", "QS-A02"]
    client_organization_id: TextId
    payer_organization_id: TextId
    case_ref: ref_type("OwnerCase")
    scope: ScopeRef
    issue_refs: Annotated[list[ref_type("Issue")], Field(min_length=1)]
    supported_question_codes: ValueState[list[TextId]]
    qualified: ValueState[bool]
    research_permitted: ValueState[bool]
    fee: ValueState[Money]
    window_ref: ref_type("TimeWindow")
    status: Literal["offered", "withdrawn"]
    available_at: TimePoint
    effective_window: TimeWindow


class StudyCandidateView(SourcedOwnerProjection):
    ref: ref_type("StudyCandidate")
    local_key: TextId
    organization_id: TextId
    case_ref: ref_type("OwnerCase")
    choice: Literal["internal_study", "commission", "narrow"]
    task_scope: StudyScopeChoice
    issue_refs: Annotated[list[ref_type("Issue")], Field(min_length=1)]
    expenditure_cap: ValueState[Money]
    future_cost: ValueState[Money]
    window_ref: ref_type("TimeWindow")
    allocations: list[StudyAllocation]
    offer_ref: ref_type("ServiceOffer") | None
    prior_study_ref: ref_type("StudyPlan") | None
    reassessment_refs: list[ref_type("StudyReassessment")]
    priority: ValueState[int]
    research_permitted: ValueState[bool]
    available_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode="after")
    def closed_branch(self):
        for rows in (self.issue_refs, self.reassessment_refs):
            unique_refs(rows)
        if self.choice == "internal_study" and (not self.allocations or self.offer_ref is not None or self.prior_study_ref is not None):
            raise ValueError("Internal study requires allocations and no external/prior branch fields")
        if self.choice == "commission" and (self.offer_ref is None or self.allocations or self.prior_study_ref is not None):
            raise ValueError("Commission requires an offer and no internal/prior branch fields")
        if self.choice == "narrow" and (self.prior_study_ref is None or self.allocations or self.offer_ref is not None or self.reassessment_refs):
            raise ValueError("Narrow references an existing plan without starting another task or offer")
        if any(row.task_target.local_key != self.local_key or row.task_target.scope_ref != self.task_scope.scope_ref
               or row.window_ref != self.window_ref for row in self.allocations):
            raise ValueError("Proposed allocations must bind the candidate identity, scope and window")
        return self


class StudyProfileView(SourcedOwnerProjection):
    ref: ref_type("StudyProfile")
    organization_id: TextId
    case_ref: ref_type("OwnerCase")
    permitted_scope: ScopeRef
    authority_ref: ref_type("Authorization")
    funding_ref: ref_type("FundingPosition")
    algorithm_code: TextId
    policy: ValueState[Literal["evaluate", "stop"]]
    on_unavailable: ValueState[Literal["defer", "stop"]]
    candidate_refs: list[ref_type("StudyCandidate")]
    history_refs: list[ref_type("StudyPlan")]
    history_coverage: Literal["complete", "partial", "unknown"]
    as_of: TimePoint
    available_at: TimePoint
    effective_window: TimeWindow

    @model_validator(mode="after")
    def unique_versions(self):
        for rows in (self.candidate_refs, self.history_refs):
            unique_refs(rows)
        return self


def owner_study_schemas():
    registry = common_projection_schemas()
    for kind, schema in (
        ("Organization", OwnerOrganizationView), ("OwnerCase", StudyCaseView), ("OwnerBrief", ProposalPriorBriefView),
        ("Issue", StudyIssueView), ("WorkScope", StudyWorkScopeView), ("Requirement", StudyRequirementView),
        ("ResourcePool", StudyResourceView), ("StudyPlan", StudyPriorPlanView), ("Obligation", StudyObligationView),
        ("StudyReassessment", StudyReassessmentView), ("ServiceOffer", StudyServiceOfferView),
        ("StudyCandidate", StudyCandidateView), ("StudyProfile", StudyProfileView), ("FundingPosition", ProposalFundingView),
    ):
        registry.register_kind(kind, schema, str)
    return registry
