from __future__ import annotations

from src.models import Company, MemberAgent


ROLE_HEADERS = {
    "owner": "You are an owner-side company member agent.",
    "designer": "You are a designer company member agent.",
    "supplier": "You are a supplier company member agent.",
    "contractor": "You are a contractor company member agent.",
    "supervisor": "You are a third-party supervision service company member agent.",
}


class CapturingLLM:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def achat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        self.calls.append(messages)
        return (
            '{"thoughts":"I am judging this from my assigned role.",'
            '"content":"I see a credible path, but colleagues should check risk and capacity.",'
            '"recommendation":"support",'
            '"decision_impact":"positive"}'
        )


def no_other_headers(text: str, own_role: str) -> bool:
    return all(header not in text for role, header in ROLE_HEADERS.items() if role != own_role)


def company(role: str) -> Company:
    return Company(
        f"{role}_001",
        f"{role.title()} Co.",
        role,
        "profile",
        ["strength"],
        ["weakness"],
        ["capability"],
        ["experience"],
        "medium",
        ["risk"],
        [f"{role}_package"],
    )


def agent(role: str, agent_id: str | None = None, position: str = "Manager", authority: str = "final") -> MemberAgent:
    return MemberAgent(agent_id or f"{role}_agent", "Alex", f"{role}_001", role, "Delivery", position, "role-focused", ["advise"], authority, "direct")
