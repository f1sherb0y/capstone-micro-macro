from __future__ import annotations

import asyncio

from src.agent_runtime import AgentRuntime
from src.discussion_context import public_discussion_line
from src.models import Company, ParticipationDecision, SimulationState, TenderPackage
from src.progress import log as progress_log
from src.prompt_contracts import require_management_decision
from src.prompt_loader import load_prompt
from src.response_recovery import normalize_management_decision
from src.state_ops import company_by_id, final_agent, log_event
from src.verification import conditions, evidence_context, guarded_validator, disposition_fields, DecisionOutputError, output_verification_requests
from src.company_grounding import company_evidence
from src.task_role_contract import role_context


async def run_bid_participation(state: SimulationState, runtime: AgentRuntime) -> None:
    candidates = [
        (package, company)
        for package in state.tender_packages
        for company in state.companies
        if company.company_role == package.required_company_role
    ]
    progress_log(f"participation: preparing {len(candidates)} company-package decisions")
    raw_results = await asyncio.gather(
        *[_participation_task(state, runtime, package, company) for package, company in candidates],
        return_exceptions=True,
    )
    results = []
    for (package, company), result in zip(candidates, raw_results):
        if isinstance(result, Exception):
            if runtime.company_narrative_grounding:
                runtime.import_messages(state,getattr(result,'discussion_messages',[]))
                pending={'company_id':company.company_id,'package_id':package.package_id,
                    'status':'output_validation_pending_not_business_no_bid','error':str(result),
                    'attempts':getattr(result,'output_attempts',[]),'review':getattr(result,'output_review',None)}
                state.validation_context.setdefault('micro_output_pending',[]).append(pending)
                runtime.record_recovery('participation_output_pending',**pending)
                continue
            runtime.record_recovery(
                "participation_conservative_fallback",
                company_id=company.company_id,
                package_id=package.package_id,
                error=f"{type(result).__name__}: {result}",
            )
            result = (
                getattr(result, "discussion_messages", []),
                ParticipationDecision(
                    company.company_id,
                    package.package_id,
                    "no_bid",
                    "Degraded fallback: the company decision could not be validated.",
                    unresolved_condition_ids=getattr(result, "unresolved_condition_ids", []),
                ),
            )
        elif isinstance(result, BaseException):
            raise result
        results.append(result)
    for index, (messages, decision) in enumerate(results, start=1):
        runtime.import_messages(state, messages)
        state.participation_decisions.append(decision)
        log_event(state, "bid_participation_decided", decision.__dict__)
        progress_log(
            f"participation: recorded {index}/{len(results)} "
            f"{decision.company_id} -> {decision.package_id}: {decision.decision}"
        )


async def _participation_task(
    state: SimulationState,
    runtime: AgentRuntime,
    package: TenderPackage,
    company: Company,
) -> tuple[list, ParticipationDecision]:
    progress_log(f"participation {company.company_id}/{package.package_id}: start")
    local_state = SimulationState()
    local_runtime = runtime.isolated_clone()
    agents = state.company_agent_rosters[company.company_id]
    await local_runtime.discuss_async(
        local_state,
        "bid_participation_decision",
        company,
        package.package_id,
        agents,
        [(1, "initial_opinion"), (2, "response_and_revision")],
        _participation_context(company, package),
    )
    manager = final_agent(agents)
    records = conditions(state, company.company_id, package.package_id, local_state.agent_discussion_history)
    sources = company_evidence(company) if runtime.company_grounding else None
    try:
        data = await runtime.for_entity(company.company_id).ask_json_async(
            load_prompt("company", "management_decision.md"),
            "MANAGEMENT_DECISION",
            _management_prompt(local_state, company, package) + "\n" + evidence_context(records, company_sources=sources, narrative_grounding=runtime.company_narrative_grounding) + (role_context(company.company_role) if runtime.task_role_grounding else ""),
            validator=guarded_validator(require_management_decision, records, company_sources=sources, narrative_grounding=runtime.company_narrative_grounding, task_role=company.company_role if runtime.task_role_grounding else None),
            normalizer=normalize_management_decision,
        )
    except Exception as exc:
        raise DecisionOutputError(exc, local_state.agent_discussion_history, records) from exc
    local_runtime.add_message(
        local_state,
        "bid_participation_decision",
        3,
        "management_decision",
        company,
        package.package_id,
        manager,
        "decision",
        data["thoughts"],
        data["content"],
        ["owner_requirements", "tender_package", "company_profile", "internal_discussion"],
        [],
        data["decision"],
        "final",
        data["decision"],
        verification_requests=output_verification_requests(data),
    )
    final_records = conditions(state, company.company_id, package.package_id, local_state.agent_discussion_history)
    decision = ParticipationDecision(company.company_id, package.package_id, data["decision"], data["reason"], **disposition_fields(data, final_records))
    progress_log(f"participation {company.company_id}/{package.package_id}: done ({decision.decision})")
    return local_state.agent_discussion_history, decision


def _management_prompt(state: SimulationState, company: Company, package: TenderPackage) -> str:
    discussion = [
        public_discussion_line(msg)
        for msg in state.agent_discussion_history
        if msg.stage == "bid_participation_decision" and msg.package_id == package.package_id and msg.company_id == company.company_id
    ]
    return (
        f"Company id: {company.company_id}\nCompany name: {company.company_name}\n"
        f"Company role: {company.company_role}\nProfile: {company.profile}\n"
        f"Strengths: {company.strengths}\nWeaknesses: {company.weaknesses}\n"
        f"Company capability notes: {company.qualifications}\nPast experience: {company.past_project_experience}\n"
        f"Capacity: {company.capacity}\nRisk signals: {company.risk_signals}\n"
        f"Package id: {package.package_id}\nPackage name: {package.package_name}\n"
        f"Scope: {package.scope}\nPackage capability needs: {package.qualification_requirements}\n"
        f"Owner bid content asks: {package.proposal_requirements}\nPricing asks: {package.pricing_requirements}\n"
        f"Internal discussion:\n" + "\n".join(f"- {item}" for item in discussion[-8:])
    )


def _participation_context(company: Company, package: TenderPackage) -> str:
    return (
        f"The company is deciding whether to pursue this tender package.\n\n"
        f"Company profile:\n{company.profile}\n"
        f"Strengths: {_lines(company.strengths)}\n"
        f"Weaknesses: {_lines(company.weaknesses)}\n"
        f"Capability notes: {_lines(company.qualifications)}\n"
        f"Past simulation experience: {_lines(company.past_project_experience)}\n"
        f"Capacity: {company.capacity}\n"
        f"Risk signals: {_lines(company.risk_signals)}\n\n"
        f"Tender package:\n"
        f"Package id: {package.package_id}\n"
        f"Package name: {package.package_name}\n"
        f"Scope: {package.scope}\n"
        f"Required role: {package.required_company_role}\n"
        f"Capability needs: {_lines(package.qualification_requirements)}\n"
        f"Proposal asks: {_lines(package.proposal_requirements)}\n"
        f"Pricing asks: {package.pricing_requirements}\n\n"
        f"Discuss the opportunity as a real internal team. Consider whether the company can bid alone, "
        f"should avoid the package, or should pursue a joint bid because shared bidder responsibility would "
        f"make the tender credible. Do not treat ordinary subcontracting or supplier support as a consortium."
    )


def _lines(items: list[str]) -> str:
    return "; ".join(items)


def participating_company_ids(state: SimulationState, package_id: str) -> list[str]:
    return [
        item.company_id
        for item in state.participation_decisions
        if item.package_id == package_id and item.decision in {"bid", "bid_with_consortium"}
    ]


def companies_requesting_consortium(state: SimulationState) -> list[str]:
    return [
        item.company_id
        for item in state.participation_decisions
        if item.decision == "bid_with_consortium" and company_by_id(state, item.company_id)
    ]
