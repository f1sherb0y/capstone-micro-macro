from __future__ import annotations

import asyncio

from src.agent_message_contracts import require_agent_message
from src.agent_runtime import AgentRuntime
from src.discussion_context import recent_discussion_context
from src.models import Company, DiscussionMessage, MemberAgent, SimulationState
from src.prompt_loader import member_prompt
from src.progress import log as progress_log
from src.response_recovery import normalize_agent_message
from src.state_ops import final_agent


async def run_inter_company_discussion(
    state: SimulationState,
    runtime: AgentRuntime,
    stage: str,
    package_id: str,
    companies: list[Company],
    rounds: list[tuple[int, str]],
    context: str,
    company_contexts: dict[str, str] | None = None,
) -> None:
    previous: list[DiscussionMessage] = []
    active_rounds = rounds[: min(2, len(rounds))] if runtime.profile == "smoke" else rounds
    for round_no, round_type in active_rounds:
        speakers = [_speaker(state, company) for company in companies]
        progress_log(
            f"group discussion {stage}: round {round_no} {round_type}, "
            f"package={package_id}, speakers={len(speakers)}"
        )
        tasks = [
            _ask_speaker(runtime, stage, round_type, package_id, _context_for(context, company_contexts, item[0]), previous[-8:], item)
            for item in speakers
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        results = []
        for (company, agent), result in zip(speakers, raw_results):
            if isinstance(result, Exception):
                runtime.record_recovery(
                    "speaker_call_isolated",
                    stage=stage,
                    company_id=company.company_id,
                    package_id=package_id,
                    agent_id=agent.agent_id,
                    error=f"{type(result).__name__}: {result}",
                )
                progress_log(
                    f"group discussion {stage}: isolated speaker failure company={company.company_id}, "
                    f"agent={agent.agent_id}: {type(result).__name__}: {result}"
                )
                continue
            if isinstance(result, BaseException):
                raise result
            results.append(result)
        if not results:
            raise RuntimeError(
                f"group discussion {stage} failed because all {len(speakers)} speaker calls failed; package={package_id}"
            )
        for company, agent, prior_messages, data in results:
            previous.append(
                runtime.add_message(
                    state,
                    stage,
                    round_no,
                    round_type,
                    company,
                    package_id,
                    agent,
                    "negotiation",
                    data.get("thoughts", ""),
                    data["content"],
                    ["package_requirements", "company_profile", "negotiation_record"],
                    [message.message_id for message in prior_messages],
                    data["recommendation"],
                    data["decision_impact"],
                    "",
                    verification_requests=data.get("verification_requests", []),
                )
            )


async def _ask_speaker(
    runtime: AgentRuntime,
    stage: str,
    round_type: str,
    package_id: str,
    context: str,
    previous: list[DiscussionMessage],
    item: tuple[Company, MemberAgent],
) -> tuple[Company, MemberAgent, list[DiscussionMessage], dict]:
    company, agent = item
    prompt = _speaker_prompt(stage, round_type, company, package_id, agent, context, previous)
    data = await runtime.for_entity(company.company_id).ask_json_async(
        member_prompt(company.company_role, "external"),
        "AGENT_MESSAGE",
        prompt,
        validator=require_agent_message,
        normalizer=normalize_agent_message,
    )
    return company, agent, previous, data


def _speaker(state: SimulationState, company: Company) -> tuple[Company, MemberAgent]:
    return company, final_agent(state.company_agent_rosters[company.company_id])


def _context_for(context: str, company_contexts: dict[str, str] | None, company: Company) -> str:
    own_context = (company_contexts or {}).get(company.company_id, "")
    if not own_context:
        return context
    return f"{context}\n\nYour company's current position:\n{own_context}"


def _speaker_prompt(
    stage: str,
    round_type: str,
    company: Company,
    package_id: str,
    agent: MemberAgent,
    context: str,
    previous: list[DiscussionMessage],
) -> str:
    return (
        f"Stage: {stage}\nRound type: {round_type}\n"
        f"This is an external negotiation meeting between separate companies. "
        f"Speak for your own company only, protect its accountability, and address the other companies as negotiation counterparts.\n"
        f"Company you represent: {company.company_name} ({company.company_role})\n"
        f"Package: {package_id}\nAgent: {agent.agent_name}, {agent.position}, {agent.department}\n"
        f"Personal profile: {agent.personal_profile}\n"
        f"Decision authority: {agent.decision_authority}\n"
        f"Communication style: {agent.communication_style}\n"
        f"Responsibilities: {agent.responsibilities}\nContext: {context}\n"
        f"Previous negotiation messages to consider:\n{recent_discussion_context(previous, 8)}"
    )
