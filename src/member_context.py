from __future__ import annotations

from src.discussion_context import recent_discussion_context
from src.models import Company, DiscussionMessage, MemberAgent


def build_member_context(
    stage: str,
    round_type: str,
    company: Company,
    package_id: str,
    agent: MemberAgent,
    context: str,
    previous: list[DiscussionMessage],
    memory: list[DiscussionMessage] | None = None,
) -> str:
    return (
        f"Stage: {stage}\nRound type: {round_type}\n"
        f"Company: {company.company_name} ({company.company_role})\n"
        f"Package: {package_id}\nAgent: {agent.agent_name}, {agent.position}, {agent.department}\n"
        f"Personal profile: {agent.personal_profile}\n"
        f"Decision authority: {agent.decision_authority}\n"
        f"Communication style: {agent.communication_style}\n"
        f"Responsibilities: {agent.responsibilities}\nContext: {context}\n"
        f"Relevant earlier company memory:\n{recent_discussion_context(memory or [], 5)}\n"
        f"Previous messages to consider:\n{recent_discussion_context(previous)}"
    )
