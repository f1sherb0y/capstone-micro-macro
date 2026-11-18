"""In-simulation internal review desk for explicit submission prerequisites.

Micro agents may request checks, and discussion never verifies them (see
``src.verification``). Earlier offline experiments supplied reviews through an
operator or a fixture. An unattended live simulation has no operator, so every
prerequisite marked ``required_before_submission`` blocked its bid forever and
no package could reach evaluation.

This desk answers such prerequisites ONLY from the scenario record already
authorized for that company. It never fabricates a document:

* ``established``    -> review status ``verified``, citing numbered source items
* ``contradicted``   -> review status ``rejected`` (still blocks submission)
* ``not_in_record``  -> the record is silent; management either proceeds with a
  disclosed bid assumption (status ``assumed``: unresolved, not verified, no
  longer a submission gate) or withdraws (status ``unavailable``: still blocks).

The desk is opt-in (``AgentRuntime.internal_condition_review``); frozen
experiments and offline fixtures keep their original behavior.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from src.models import Company, DiscussionMessage, SimulationState, TenderPackage
from src.progress import log as progress_log
from src.state_ops import log_event
from src.verification import conditions

REVIEWER = "simulated-internal-review-desk"
FINDINGS = {"established", "contradicted", "not_in_record"}
DISPOSITIONS = {"proceed_as_disclosed_assumption", "withdraw"}
_SKIPPED_CONTEXT = {"memory", "memory_selection", "environment", "policy", "snapshot_version", "data_version"}

SYSTEM_PROMPT = """You are the internal review desk of ONE company inside a construction procurement simulation: its commercial, resource-planning and qualification-records staff acting together.
Colleagues marked some checks as prerequisites that must be answered before the company's bid may be submitted.
The simulation world contains no documents beyond the numbered SOURCE ITEMS supplied to you. Nobody can obtain anything else, now or later in this bid window.

For every listed prerequisite return exactly one review:
- finding "established": one or more source items directly state the fact asked for, for example available resource is at least the required resource, or the scenario eligibility rule covers this role. Cite those item ids in source_ids.
- finding "contradicted": source items show the opposite, for example available resource is below the requirement. Cite them in source_ids.
- finding "not_in_record": the scenario record is silent, for example named personnel, signed letters, third-party quotations, or the buyer's future written position. Leave source_ids empty and, acting as the responsible management, choose a disposition:
  - "proceed_as_disclosed_assumption": the company still bids and openly discloses this unknown as a bid assumption or risk boundary that the bid prices, conditions or raises as a clarification;
  - "withdraw": the unknown is so fundamental that the company will not submit.

Rules:
- Never treat silence as proof and never invent a document, name, quotation or approval.
- A numeric scenario capability or the scenario eligibility rule is evidence only for exactly what it states. Do not mark established by general plausibility.
- An ordinary commercial unknown is normally handled by a disclosed assumption, contingency or clarification request. Choose withdraw only for a genuinely disqualifying gap.
- disposition is null unless finding is not_in_record.
- note is one sentence in the language of the question, saying what the cited items show or what is missing.

Return JSON: {"reviews": [{"condition_id": "...", "finding": "...", "source_ids": ["..."], "note": "...", "disposition": null}]}"""


def enabled(runtime) -> bool:
    return bool(getattr(runtime, "internal_condition_review", False))


def _text(value: Any, limit: int = 600) -> str:
    if isinstance(value, (list, tuple)):
        value = "; ".join(str(item) for item in value)
    text = str(value).strip()
    return text if len(text) <= limit else text[:limit] + "..."


def _leaves(value: Any, path: str, out: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _SKIPPED_CONTEXT:
                continue
            _leaves(item, f"{path}.{key}" if path else str(key), out)
    elif isinstance(value, list) and any(isinstance(item, (dict, list)) for item in value):
        for index, item in enumerate(value):
            _leaves(item, f"{path}[{index}]", out)
    elif value not in (None, "", [], {}):
        out.append((path, _text(value)))


def source_items(company: Company, package: TenderPackage, authorized: dict | None) -> dict[str, str]:
    """Numbered scenario record this company is authorized to read. No new facts."""
    items: dict[str, str] = {}
    company_rows = [("company", f"{company.company_id} {company.company_name} ({company.company_role})"),
                    ("company.profile", company.profile), ("company.strengths", company.strengths),
                    ("company.weaknesses", company.weaknesses), ("company.capabilities", company.qualifications),
                    ("company.past_experience", company.past_project_experience),
                    ("company.capacity", company.capacity), ("company.risk_signals", company.risk_signals)]
    package_rows = [("package", f"{package.package_id} {package.package_name}"), ("package.scope", package.scope),
                    ("package.required_role", package.required_company_role),
                    ("package.capability_needs", package.qualification_requirements),
                    ("package.bid_content_asks", package.proposal_requirements),
                    ("package.pricing_asks", package.pricing_requirements)]
    for prefix, rows in (("C", company_rows), ("P", package_rows)):
        for index, (label, value) in enumerate((row for row in rows if row[1] not in (None, "", [])), start=1):
            items[f"{prefix}{index}"] = f"{label}: {_text(value)}"
    if authorized:
        leaves: list[tuple[str, str]] = []
        _leaves(authorized, "", leaves)
        for index, (path, value) in enumerate(leaves, start=1):
            items[f"A{index}"] = f"{path} = {value}"
    return items


def _validator(blocker_ids: set[str], items: dict[str, str]):
    def validate(data: dict) -> None:
        reviews = data.get("reviews")
        if not isinstance(reviews, list) or any(not isinstance(row, dict) for row in reviews):
            raise ValueError("reviews must be a list of objects")
        seen = [row.get("condition_id") for row in reviews]
        if set(seen) != blocker_ids or len(seen) != len(set(seen)):
            raise ValueError(f"Review every listed condition exactly once: {sorted(blocker_ids)}")
        for row in reviews:
            finding, sources = row.get("finding"), row.get("source_ids") or []
            if finding not in FINDINGS:
                raise ValueError("finding must be established, contradicted or not_in_record")
            if not isinstance(row.get("note"), str) or not row["note"].strip():
                raise ValueError("Each review needs a one-sentence note")
            if not isinstance(sources, list) or any(item not in items for item in sources):
                raise ValueError("source_ids must be ids of the supplied SOURCE ITEMS")
            if finding == "not_in_record":
                if row.get("disposition") not in DISPOSITIONS:
                    raise ValueError("not_in_record needs disposition proceed_as_disclosed_assumption or withdraw")
            elif not sources:
                raise ValueError("established/contradicted findings must cite at least one source item id")
    return validate


def _review(company_id: str, package_id: str, status: str, source_ref: str, source_text: str) -> dict:
    return dict(company_id=company_id, package_id=package_id, status=status, source_ref=source_ref,
                source_text=source_text, reviewer=REVIEWER,
                source_sha256=hashlib.sha256(source_text.encode()).hexdigest())


async def review_blocking_conditions(state: SimulationState, runtime, company: Company, package: TenderPackage,
                                     extra_messages: Iterable[DiscussionMessage] = ()) -> list[dict]:
    """Answer not-yet-reviewed submission prerequisites; return the outcomes applied."""
    if not enabled(runtime):
        return []
    extra_messages = list(extra_messages)
    records = conditions(state, company.company_id, package.package_id, extra_messages)
    blockers = [r for r in records if r["required_before_submission"] and r["status"] == "requested"]
    if not blockers:
        return []
    authorized = runtime.context_resolver(company.company_id) if runtime.context_resolver is not None else None
    items = source_items(company, package, authorized)
    prompt = ("SOURCE ITEMS (the complete scenario record for this company and package):\n"
              + "\n".join(f"[{key}] {value}" for key, value in items.items())
              + "\n\nPREREQUISITES TO REVIEW:\n"
              + json.dumps([{"condition_id": r["condition_id"], "question": r["question"]} for r in blockers],
                           ensure_ascii=False))
    progress_log(f"condition_review {company.company_id}/{package.package_id}: reviewing {len(blockers)} prerequisites")
    try:
        data = await runtime.for_entity(company.company_id).ask_json_async(
            SYSTEM_PROMPT, "CONDITION_REVIEW", prompt,
            validator=_validator({r["condition_id"] for r in blockers}, items))
    except (KeyError, TypeError, ValueError) as exc:
        # Unreviewed prerequisites simply keep blocking; nothing is promoted.
        progress_log(f"condition_review {company.company_id}/{package.package_id}: left unreviewed ({exc})")
        return []
    questions = {r["condition_id"]: r["question"] for r in blockers}
    outcomes = []
    for row in data["reviews"]:
        finding, sources = row["finding"], list(row.get("source_ids") or [])
        if finding == "not_in_record":
            status = "assumed" if row["disposition"] == "proceed_as_disclosed_assumption" else "unavailable"
            source_ref = "scenario-record:silent"
            source_text = "No source item in the scenario record answers this question. " + row["note"].strip()
        else:
            status = "verified" if finding == "established" else "rejected"
            source_ref = "scenario-record:" + ",".join(sources)
            source_text = "\n".join(f"[{key}] {items[key]}" for key in sources)
        state.verification_reviews[row["condition_id"]] = _review(
            company.company_id, package.package_id, status, source_ref, source_text)
        outcomes.append({"condition_id": row["condition_id"], "question": questions[row["condition_id"]],
                         "finding": finding, "disposition": row.get("disposition"), "status": status,
                         "source_ids": sources, "note": row["note"].strip()})
    state.validation_context["internal_condition_review"] = True
    log_event(state, "internal_condition_review", {"company_id": company.company_id, "package_id": package.package_id,
                                                   "outcomes": outcomes})
    counts: dict[str, int] = {}
    for item in outcomes:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    progress_log(f"condition_review {company.company_id}/{package.package_id}: {counts}")
    return outcomes
