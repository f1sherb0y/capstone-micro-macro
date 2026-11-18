from __future__ import annotations

import asyncio

from src.agent_runtime import AgentRuntime
from src.models import Company, Consortium, MemberAgent, ParticipationDecision, SimulationState, TenderPackage
from src.stages.bid_documents import generate_bid_documents
from src.stages.bid_prompt_context import bid_document_discussion_context


class BidLLM:
    def __init__(self, quotation: int = 1000000, breakdown_amount: int = 1000000):
        self.quotation = quotation
        self.breakdown_amount = breakdown_amount
        self.agent_prompts: list[str] = []

    async def achat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        marker = messages[1]["content"].splitlines()[0]
        if marker == "AGENT_MESSAGE":
            self.agent_prompts.append(messages[1]["content"])
            return (
                '{"thoughts":"I need to keep the bid credible.",'
                '"content":"Our submission should explain the scope, risk allowance, and delivery basis clearly enough for reviewers to compare it.",'
                '"recommendation":"submit",'
                '"decision_impact":"supports a complete bid"}'
            )
        return (
            '{"technical_proposal":"Complete technical proposal.",'
            '"implementation_plan":"Complete implementation plan.",'
            f'"quotation":{self.quotation},'
            '"schedule_commitment":"Complete schedule commitment.",'
            '"owner_control_response":"Accept owner review and reporting.",'
            '"risk_response":"Risk response covers delivery interfaces.",'
            '"submission_summary":"Bid is priced for the accepted package scope.",'
            f'"quotation_breakdown":[{{"item":"package delivery","amount":{self.breakdown_amount},"basis":"test basis"}}]}}'
        )


def test_overlapping_consortium_lead_still_submits_own_bid() -> None:
    state = _state()
    asyncio.run(generate_bid_documents(state, AgentRuntime(BidLLM(), profile="smoke")))
    bidders = [bid.bidder_id for bid in state.bid_documents]
    assert bidders == ["consortium_design_package_001", "consortium_design_package_002"]


def test_bid_document_rejects_mismatched_quotation_breakdown_without_changing_costs() -> None:
    state = _state()
    llm = BidLLM(quotation=950000, breakdown_amount=1000000)
    runtime = AgentRuntime(llm, profile="smoke")
    asyncio.run(generate_bid_documents(state, runtime))
    assert state.bid_documents == []
    assert llm.quotation == 950000 and llm.breakdown_amount == 1000000
    assert sum(e['kind'] == 'bid_submission_skipped' for e in runtime.recovery_events) == 2
    assert all('quotation minus breakdown = -50000' in e['error']
               for e in runtime.recovery_events if e['kind'] == 'bid_submission_skipped')


def test_bid_document_member_prompt_receives_decided_structure_context() -> None:
    state = _state()
    llm = BidLLM()
    asyncio.run(generate_bid_documents(state, AgentRuntime(llm, profile="smoke")))
    text = "\n".join(llm.agent_prompts)
    assert "The current bidder is A-B as a consortium bidder" in text
    assert "Do not reopen whether to bid alone or form a consortium" in text


def test_bid_document_discussion_context_preserves_decided_bidder_structure() -> None:
    package = TenderPackage("design_package", "design", "Design", "scope", "designer", [], [], "pricing", [], "owner")
    decision = ParticipationDecision("designer_001", "design_package", "bid", "solo bid")
    text = bid_document_discussion_context(package, decision, None, "Designer One")
    assert "single-company bidder" in text
    assert "participation decision already recorded" in text
    assert "Do not reopen whether to bid alone or form a consortium" in text


def test_bid_document_discussion_context_names_consortium_structure() -> None:
    package = TenderPackage("design_package", "design", "Design", "scope", "designer", [], [], "pricing", [], "owner")
    decision = ParticipationDecision("designer_001", "design_package", "bid_with_consortium", "joint bid")
    text = bid_document_discussion_context(package, decision, object(), "Design Alliance")
    assert "Design Alliance as a consortium bidder" in text
    assert "bid_with_consortium" in text


def _state() -> SimulationState:
    state = SimulationState()
    state.tender_packages = [
        TenderPackage("design_package", "design", "Design", "scope", "designer", [], [], "pricing", [], "owner")
    ]
    state.companies = [_company("designer_001"), _company("designer_002"), _company("designer_003")]
    state.company_agent_rosters = {company.company_id: [_agent(company)] for company in state.companies}
    state.participation_decisions = [
        ParticipationDecision("designer_001", "design_package", "bid_with_consortium", "lead first consortium"),
        ParticipationDecision("designer_003", "design_package", "bid_with_consortium", "lead second consortium"),
    ]
    state.consortiums = [
        Consortium("consortium_design_package_001", "A-B", "design_package", "designer_001", ["designer_001", "designer_002"], "fit", {}, "agreement", "formed"),
        Consortium("consortium_design_package_002", "C-A", "design_package", "designer_003", ["designer_003", "designer_001"], "fit", {}, "agreement", "formed"),
    ]
    return state


def _company(company_id: str) -> Company:
    return Company(company_id, f"{company_id} Co.", "designer", "profile", [], [], [], [], "medium", [], ["design_package"])


def _agent(company: Company) -> MemberAgent:
    return MemberAgent(f"{company.company_id}_gm", "Alex", company.company_id, "designer", "Management", "Director", "decisive", ["approve"], "final", "direct")
