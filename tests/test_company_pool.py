from __future__ import annotations

import asyncio
from collections import Counter

from src.mock_llm import MockLLMClient
from src.agent_runtime import AgentRuntime
from src.llm_throttle import LLMThrottle
from src.models import ProjectIdea
from src.prompt_loader import load_prompt
from src.stages.project_setup import generate_companies


def test_company_pool_prompt_requires_unique_role_fit_names() -> None:
    prompt = load_prompt("company", "pool.md").lower()
    assert "every `company_name` must be globally unique" in prompt
    assert "do not reuse the same brand or company name" in prompt
    assert "names should signal role fit" in prompt
    assert "not builders or construction" in prompt


def test_company_pool_prompt_requires_solo_capable_design_competition() -> None:
    prompt = load_prompt("company", "pool.md").lower()
    assert "`designer_001` and `designer_002`" in prompt
    assert "credible single accountable design bidders" in prompt
    assert "ordinary subconsultant management" in prompt
    assert "must not say they lack a core design discipline" in prompt
    assert "weak or limited bim capability" in prompt


def test_company_pool_prompt_requires_solo_capable_supplier_competition() -> None:
    prompt = load_prompt("company", "pool.md").lower()
    assert "`supplier_001` and `supplier_002`" in prompt
    assert "credible single accountable supplier bidders" in prompt
    assert "warranty and spare parts support capability" in prompt
    assert "contractor interface information capability" in prompt
    assert "must not say they cannot cover the main supplier package" in prompt


def test_company_pool_prompt_requires_solo_capable_contractor_competition() -> None:
    prompt = load_prompt("company", "pool.md").lower()
    assert "`contractor_001` and `contractor_002`" in prompt
    assert "credible single accountable prime-contractor bidders" in prompt
    assert "construction management capability" in prompt
    assert "subcontractor coordination capability" in prompt
    assert "require a consortium for ordinary mep/specialist subcontracting" in prompt


def test_roster_prompt_requires_compact_rosters() -> None:
    prompt = load_prompt("company", "roster.md").lower()
    assert "compact prototype roster" in prompt
    assert "create 4 to 6 key members only" in prompt
    assert "do not split one repeated viewpoint" in prompt
    assert "independent personal profile" in prompt


def test_consortium_prompt_preserves_competition() -> None:
    prompt = load_prompt("company", "consortium.md").lower()
    assert "preserve live competition" in prompt
    assert "not a package-wide merger" in prompt
    assert "minimum members needed" in prompt
    assert "independent competing bids" in prompt
    assert "do not create a different consortium among candidate partners without the lead" in prompt
    assert "if the lead company is not a member" in prompt


def test_management_prompt_distinguishes_designer_subconsultants() -> None:
    prompt = load_prompt("company", "management_decision.md").lower()
    assert "for designer companies" in prompt
    assert "remain the accountable design lead" in prompt
    assert "control subconsultant scope" in prompt
    assert "facade over unmanaged engineering specialists" in prompt


def test_management_prompt_distinguishes_contractor_subcontractors() -> None:
    prompt = load_prompt("company", "management_decision.md").lower()
    assert "for contractor companies" in prompt
    assert "prime contractor" in prompt
    assert "subcontractor control" in prompt
    assert "ordinary subcontracting" in prompt


def test_bid_document_prompt_requires_commercially_coherent_quotation() -> None:
    prompt = load_prompt("company", "bid_document.md").lower()
    assert "commercially coherent" in prompt
    assert "whole package" in prompt
    assert "not a token number" in prompt
    assert "partial-scope number" in prompt
    assert "quotation_breakdown" in prompt
    assert "set `quotation` to that subtotal" in prompt
    assert "five to seven cost buckets" in prompt
    assert "recalculate the subtotal" in prompt
    assert "never leave a near-miss total" in prompt
    assert "full construction-and-installation package" in prompt
    assert "construction-scale amounts" in prompt
    assert "do not let \"compact\" shrink" in prompt
    assert "full prime-contractor accountability" in prompt
    assert "consistent with the resources you claim" in prompt
    assert "long-duration resources" in prompt
    assert "resource plausibility check" in prompt
    assert "revise the bucket upward" in prompt


def test_bid_document_prompt_keeps_supervision_service_period() -> None:
    prompt = load_prompt("company", "bid_document.md").lower()
    assert "full project-duration supervision" in prompt
    assert "states a month count" in prompt
    assert "carry that same duration through the schedule" in prompt
    assert "if the owner does not state a month count" in prompt
    assert "do not invent 12, 18, 24, or any other month count anywhere" in prompt
    assert "`quotation_breakdown.basis`" in prompt
    assert "do not write monthly rates" in prompt
    assert "per-month bases" in prompt
    assert "month-equivalent coverage" in prompt
    assert "do not claim no month count and then hide an estimated month count" in prompt
    assert "full project-duration resident staffing allowance" in prompt
    assert "first 3 months of extension" in prompt
    assert "monthly-rate times invented months" in prompt
    assert "normal estimating precision" in prompt
    assert "repeated comfort-anchor amounts" in prompt
    assert "using a different assumed duration from competitors" in prompt
    assert "do not create a cheaper bid by shortening the service period" in prompt
    assert "making the remaining months optional" in prompt


def test_smoke_profile_keeps_three_competitors_per_role() -> None:
    asyncio.run(_check_smoke_profile_keeps_three_competitors_per_role())


async def _check_smoke_profile_keeps_three_competitors_per_role() -> None:
    project = ProjectIdea(
        "project_001",
        "Compact Public Facility",
        "user_defined",
        "Macau",
        "Build a compact public service and transport interchange facility.",
        "medium",
        "MOP simulated budget",
        "24 months",
        ["compact site"],
        "test",
    )
    runtime = AgentRuntime(MockLLMClient(), LLMThrottle())
    companies = await generate_companies(runtime, project, "smoke")
    counts = Counter(company.company_role for company in companies)
    assert counts == {
        "owner": 1,
        "designer": 3,
        "supplier": 3,
        "contractor": 3,
        "supervisor": 3,
    }
