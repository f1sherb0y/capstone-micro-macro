from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def dump(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [dump(item) for item in value]
    if isinstance(value, dict):
        return {key: dump(item) for key, item in value.items()}
    return value


@dataclass
class ProjectIdea:
    project_id: str
    project_name: str
    project_type: str
    location: str
    owner_intent: str
    scale_hint: str
    budget_hint: str
    schedule_hint: str
    constraints: list[str]
    source_mode: str


@dataclass
class Company:
    company_id: str
    company_name: str
    company_role: str
    profile: str
    strengths: list[str]
    weaknesses: list[str]
    qualifications: list[str]
    past_project_experience: list[str]
    capacity: str
    risk_signals: list[str]
    eligible_packages: list[str]


@dataclass
class MemberAgent:
    agent_id: str
    agent_name: str
    company_id: str
    company_role: str
    department: str
    position: str
    personal_profile: str
    responsibilities: list[str]
    decision_authority: str
    communication_style: str


@dataclass
class TenderPackage:
    package_id: str
    package_type: str
    package_name: str
    scope: str
    required_company_role: str
    qualification_requirements: list[str]
    proposal_requirements: list[str]
    pricing_requirements: str
    evaluation_criteria: list[str]
    owner_decision_policy: str


@dataclass
class OwnerRequirements:
    project_id: str
    project_scope: str
    functional_requirements: list[str]
    technical_requirements: list[str]
    budget_policy: str
    schedule_policy: str
    compliance_requirements: list[str]
    risk_priorities: list[str]
    tender_package_plan: list[TenderPackage]


@dataclass
class DiscussionMessage:
    message_id: str
    stage: str
    round: int
    round_type: str
    company_id: str
    company_role: str
    package_id: str
    agent_id: str
    agent_name: str
    department: str
    position: str
    message_type: str
    thoughts: str
    content: str
    references: list[str]
    response_to: list[str]
    recommendation: str
    decision_impact: str
    final_decision: str
    timestamp: str
    verification_requests: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ParticipationDecision:
    company_id: str
    package_id: str
    decision: str
    reason: str
    unresolved_condition_ids: list[str] = field(default_factory=list)
    verified_condition_ids: list[str] = field(default_factory=list)
    bid_assumptions: list[str] = field(default_factory=list)
    company_assessment: dict[str, Any] = field(default_factory=dict)
    company_narrative_review: dict[str, Any] = field(default_factory=dict)
    task_role: str = ''


@dataclass
class Consortium:
    consortium_id: str
    consortium_name: str
    package_id: str
    lead_company_id: str
    member_company_ids: list[str]
    formation_reason: str
    role_split: dict[str, str]
    agreement_summary: str
    status: str


@dataclass
class BidDocument:
    bid_id: str
    package_id: str
    bidder_type: str
    bidder_id: str
    bidder_name: str
    technical_proposal: str
    implementation_plan: str
    quotation: float
    schedule_commitment: str
    compliance_statement: str
    risk_response: str
    submission_summary: str
    quotation_breakdown: list[dict[str, Any]] = field(default_factory=list)
    unresolved_condition_ids: list[str] = field(default_factory=list)
    verified_condition_ids: list[str] = field(default_factory=list)
    bid_assumptions: list[str] = field(default_factory=list)
    company_assessment: dict[str, Any] = field(default_factory=dict)
    company_narrative_review: dict[str, Any] = field(default_factory=dict)
    task_role: str = ''


@dataclass
class OpeningRecord:
    package_id: str
    opened_bids: list[dict[str, Any]]
    opening_summary: str
    disqualified_bids: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EvaluationReport:
    package_id: str
    evaluators: list[str]
    bid_evaluations: list[dict[str, Any]]
    comparison_summary: str
    recommended_winner: str | None
    owner_review_notes: str


@dataclass
class AwardResult:
    package_id: str
    selected_bidder_id: str | None
    selected_bidder_name: str
    bidder_type: str
    decision_reason: str
    unresolved_condition_ids: list[str] = field(default_factory=list)
    bid_assumptions: list[str] = field(default_factory=list)
    pending_clarifications: list[str] = field(default_factory=list)


@dataclass
class SimulationState:
    project_idea: ProjectIdea | None = None
    owner_requirements: OwnerRequirements | None = None
    tender_packages: list[TenderPackage] = field(default_factory=list)
    companies: list[Company] = field(default_factory=list)
    company_agent_rosters: dict[str, list[MemberAgent]] = field(default_factory=dict)
    agent_discussion_history: list[DiscussionMessage] = field(default_factory=list)
    participation_decisions: list[ParticipationDecision] = field(default_factory=list)
    consortiums: list[Consortium] = field(default_factory=list)
    bid_documents: list[BidDocument] = field(default_factory=list)
    opening_record: list[OpeningRecord] = field(default_factory=list)
    evaluation_report: list[EvaluationReport] = field(default_factory=list)
    simulated_award_result: dict[str, Any] = field(default_factory=dict)
    project_execution_log: dict[str, Any] = field(default_factory=dict)
    tender_process_log: list[dict[str, Any]] = field(default_factory=list)
    validation_context: dict[str, Any] = field(default_factory=dict)
    # Application-supplied documentary reviews; never populated from model JSON.
    verification_reviews: dict[str, dict[str, Any]] = field(default_factory=dict)


def load_simulation_state(data: dict[str, Any]) -> SimulationState:
    """Rebuild a SimulationState from a durable workflow checkpoint."""
    state = SimulationState()
    state.project_idea = _optional_dataclass(ProjectIdea, data.get("project_idea"))
    owner = data.get("owner_requirements")
    if isinstance(owner, dict):
        owner_data = dict(owner)
        owner_data["tender_package_plan"] = _dataclass_list(
            TenderPackage, owner_data.get("tender_package_plan", [])
        )
        state.owner_requirements = OwnerRequirements(**owner_data)
    state.tender_packages = _dataclass_list(TenderPackage, data.get("tender_packages", []))
    state.companies = _dataclass_list(Company, data.get("companies", []))
    state.company_agent_rosters = {
        str(company_id): _dataclass_list(MemberAgent, members)
        for company_id, members in (data.get("company_agent_rosters") or {}).items()
    }
    state.agent_discussion_history = _dataclass_list(
        DiscussionMessage, data.get("agent_discussion_history", [])
    )
    state.participation_decisions = _dataclass_list(
        ParticipationDecision, data.get("participation_decisions", [])
    )
    state.consortiums = _dataclass_list(Consortium, data.get("consortiums", []))
    state.bid_documents = _dataclass_list(BidDocument, data.get("bid_documents", []))
    state.opening_record = _dataclass_list(OpeningRecord, data.get("opening_record", []))
    state.evaluation_report = _dataclass_list(EvaluationReport, data.get("evaluation_report", []))
    state.simulated_award_result = dict(data.get("simulated_award_result") or {})
    state.project_execution_log = dict(data.get("project_execution_log") or {})
    state.tender_process_log = list(data.get("tender_process_log") or [])
    state.validation_context = dict(data.get("validation_context") or {})
    state.verification_reviews = dict(data.get("verification_reviews") or {})
    return state


def _dataclass_list(cls, values: Any) -> list[Any]:
    if not isinstance(values, list):
        raise TypeError(f"Checkpoint field for {cls.__name__} must be a list")
    return [cls(**item) for item in values]


def _optional_dataclass(cls, value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"Checkpoint field for {cls.__name__} must be an object")
    return cls(**value)
