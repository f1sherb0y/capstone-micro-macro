from __future__ import annotations

from pathlib import Path
from src.verification import EVIDENCE_POLICY


PROMPT_ROOT = Path(__file__).resolve().parents[1] / "prompts"
SIMULATION_ONLY = PROMPT_ROOT / "shared" / "simulation_only.md"
AGENT_COMMUNICATION = PROMPT_ROOT / "shared" / "agent_communication.md"
EXTERNAL_NEGOTIATION = PROMPT_ROOT / "shared" / "external_negotiation.md"


CHINESE_OUTPUT_POLICY = """
Output language policy:
- Keep JSON keys, enum values, ids, and code-facing field names exactly as requested in English.
- Write all human-readable values in Chinese, including company display names, project names, profiles, reasoning, discussion messages, bid text, evaluation text, and award reasons.
- Use Macau construction tendering vocabulary where appropriate, such as 招标包, 投标, 开标, 评标, 判给, 组合体, 监管服务, 工期, 报价, 风险应对.
- Currency may remain `MOP`, but surrounding explanation should be Chinese.
- Do not translate required enum values such as owner, designer, supplier, contractor, supervisor, bid, no_bid, bid_with_consortium, company, and consortium.
""".strip()


SIMULATION_PROMPT_GROUPS = {
    "company",
    "contractor",
    "designer",
    "owner",
    "supplier",
    "supervisor",
}


def load_prompt(*parts: str) -> str:
    path = PROMPT_ROOT.joinpath(*parts)
    text = path.read_text(encoding="utf-8").strip()
    if parts and parts[0] in SIMULATION_PROMPT_GROUPS:
        text = f"{text}\n\n{SIMULATION_ONLY.read_text(encoding='utf-8').strip()}"
    return f"{text}\n\n{CHINESE_OUTPUT_POLICY}"


def member_prompt(company_role: str, communication: str = "internal") -> str:
    guide = EXTERNAL_NEGOTIATION if communication == "external" else AGENT_COMMUNICATION
    return f"{load_prompt(company_role, 'member.md')}\n\n{guide.read_text(encoding='utf-8').strip()}\n\n{EVIDENCE_POLICY}"
