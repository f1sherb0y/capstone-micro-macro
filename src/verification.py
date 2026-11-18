"""Micro tender conditions. Discussion is a request, never a verification receipt.

Reviews are supplied by the application/operator after checking a source. This
module checks scope and consistency, not the real-world authenticity of a source.
The prose recognizers are compatibility safeguards, not a semantic fact checker.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Iterable

from src.models import DiscussionMessage, SimulationState
from src.company_grounding import company_evidence_context, require_company_assessment, assessment_fields


class DecisionOutputError(ValueError):
    """Preserve valid discussion when the final generated decision is invalid."""
    def __init__(self, cause: Exception, messages: list[DiscussionMessage], records: list[dict]):
        super().__init__(f"{type(cause).__name__}: {cause}")
        self.discussion_messages = messages
        self.unresolved_condition_ids = [r["condition_id"] for r in records if r["status"] != "verified"]
        self.output_attempts = getattr(cause,'output_attempts',[])
        self.output_review = getattr(cause,'report',None)


EVIDENCE_POLICY = """Evidence and decision conditions:
Separate documented company capabilities, current availability, proposed plans, and verified facts.
Total staff or past projects do not establish personnel availability for this package.
Discussion, consensus, repeated memory, and your own 'confirmed' statement are not source receipts.
For each concrete check you request, add verification_requests: [{"question": "specific check",
"required_before_submission": false}]. Set true only for an explicit prerequisite to submission,
such as qualification acceptance without which you would withdraw. Ordinary planned subcontracting
may remain an explicit bid assumption; do not invent a procurement-confirmation requirement.
Counterparty names do not prove specialism, available resources, or accepted commitments.
Do not invent missing documents or describe proposed support as already secured.
Do not assert a supplier has passed an audit, or that there is no affiliation/conflict,
unless a scoped reviewed source establishes that particular fact. A suggested audit or
independence safeguard is a plan, not its outcome. Use unknown / pending review otherwise.
Keep draft cost allowances distinct from received supplier quotations.
If you make a check an explicit prerequisite in the text, mark its verification_request
required_before_submission true. Do not simultaneously say those same checks must be
completed before submission and that they do not block it. An intention is not submission.
Application-reviewed status is authoritative for the exact recorded company, package and question.
A verified condition is satisfied in that recorded scope; do not turn it back into a submission
prerequisite, create a duplicate request, or treat its original required_before_submission flag
as an active blocker. Other unresolved conditions still apply. A genuinely new date, personnel
change, expired source or different question needs its own explicit check; it does not erase the review.
Synthetic fixture evidence can satisfy a condition ONLY inside its declared fictional task.
That never asserts availability, qualifications, finances or commitments of an actual company.
""".strip()

_DESK_STATUSES = {"assumed", "unavailable"}
_DESK_NOTE = (
    "\nInternal review desk results for this bid window are final. The simulation record holds no further "
    "documents. status 'assumed' means the record is silent and management decided to bid with that unknown "
    "as a disclosed assumption: it is NOT verified, it stays in unresolved_condition_ids, it MUST be written "
    "into bid_assumptions with its pricing or risk boundary, and it is no longer a submission prerequisite. "
    "Do not raise the same question again as a new required_before_submission request; raise a prerequisite "
    "only for a genuinely different question. status 'unavailable' or 'rejected' still blocks submission.")

_REQUEST = re.compile(
    r"(?:请.{0,45}(?:确认|核实|提交|提供)|(?:必须|需要|须|先|待|尚待|尚需|尚未|未能|有待).{0,25}(?:确认|核实|核验)|"
    r"(?:若|如果).{0,55}(?:确认|可行|计入)|"
    r"\b(?:please|must|should|need to|pending|awaiting|subject to)\b.{0,70}\b(?:confirm|verify|check|provide|confirmation|verification)\b)", re.I)
_BLOCKING = re.compile(
    r"否则.{0,18}(?:退出|不投标|放弃)|"
    r"(?:确认|核实|核验).{0,12}(?:后方可|才能|才可).{0,8}(?:投标|提交)|"
    r"(?:投标|提交)前.{0,35}(?:须|必须|硬性|实质).{0,35}(?:确认|核实|核查)|"
    r"(?:须|必须).{0,12}(?:在)?提交前.{0,30}(?:确认|核实|核查|核验)|"
    r"(?:未|尚未).{0,30}(?:完成|核实|核查|确认|通过|落实).{0,12}(?:前|则|就)?不(?:能|得)?(?:提交|递标|投标)|"
    r"(?:must|shall|required|verify|confirm|check).{0,50}before (?:bid )?submission|"
    r"before (?:bid )?submission.{0,40}(?:must|shall|required|verify|confirm|check)", re.I)
_CONFIRMED = re.compile(
    r"(?:档期|可用性|人员|关键岗位|关键角色).{0,16}已(?:初步)?确认|"
    r"(?:档期|可用性|人员).{0,12}(?:已落实|已核实)|"
    r"关键(?:岗位|角色).{0,12}充足人员可调配|"
    r"(?:staff|personnel|team|availability|subcontractors?).{0,35}(?:has been|have been|is|are) (?:already )?(?:confirmed|secured|verified)", re.I)
_QUALIFIED = re.compile(r"(?:资质|资格|业绩).{0,18}已(?:被)?(?:确认|认可|核实)|(?:分包业绩|合作方业绩).{0,12}(?:可计入|满足资格)")
_AUDITED = re.compile(
    r"(?:经|經|已通过|已通過)(?:我方|我司|本公司)?(?:审核|審核).{0,14}(?:供应商|供應商|供货渠道|供貨渠道)|"
    r"(?:供应商|供應商|供货渠道|供貨渠道).{0,12}已(?:经|經|通过|通過)?(?:我方|我司)?(?:审核|審核)|"
    r"\b(?:suppliers?|vendors?).{0,24}(?:has|have|is|are) (?:been )?(?:audited|approved)\b", re.I)
_NO_CONFLICT = re.compile(
    r"(?:与|與)(?:承包商|承建商|投标人|投標人).{0,6}(?:无|無)(?:隶属|隸屬|利益|关联|關聯)|"
    r"\b(?:we|our company).{0,12}(?:has|have) no (?:affiliation|conflict of interest)\b", re.I)


def _business_texts(data: dict) -> list[str]:
    """Outward claims include assumptions and cost bases, never private thoughts/IDs.

    Questions are requests, not assertions. This is bounded compatibility checking,
    not an inference engine for arbitrary claims or source authenticity.
    """
    values = []
    def visit(value):
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)
    for key, value in data.items():
        if key not in {'thoughts', 'verification_requests', 'unresolved_condition_ids', 'verified_condition_ids', 'company_assessment','company_narrative_review','repair_explanation'}:
            visit(value)
    return values


def _claim_is_nonassertive(clause: str, match: re.Match) -> bool:
    # A trailing plan does not cancel an earlier unsupported assertion. Look only
    # through the matched claim, including a modal inside '人员只能写已核实...'.
    before_end = clause[:match.end()]
    # A plan heading cannot negate an affirmative completed fact in its body.
    before_end = re.sub(r'^\s*(?:拟议实施计划|拟议计划|计划|proposed plan|planned implementation)\s*[:：]\s*','',before_end,flags=re.I)
    # Lists can put a negation BETWEEN a topic and the matched status token:
    # "qualification, assets and costs all have NO verified source". Do not
    # turn that negated evidence noun phrase into a confirmed qualification.
    if re.search(r'(?:均|皆|全部|目前)?(?:无|無|没有|沒有)已(?:核实|核實|确认|確認)(?:来源|來源|证据|證據|记录|記錄|资料|資料|文件)', clause):
        if re.search(r'(?:无|無|没有|沒有)已(?:核实|核實|确认|確認)', match.group()):
            return True
    # A negated reporting/interpretation operator governs the quoted proposition;
    # the proposition itself may contain positive words such as '已确认'. This
    # differs from an affirmative status followed by an unrelated disclaimer.
    operator = r'(?:不能|不得|不应|不應|不要|不|未曾|未能|未|无法|無法|没有|沒有)'
    mention = r'(?:视为|視為|假设|假設|声称|聲稱|断言|斷言|认定|認定|推断|推斷|提供|写成|寫成|表述为|表述為)'
    double_negative = re.search(r'(?:不能不|不得不|无法不|無法不)', before_end)
    if not double_negative and re.search(operator + r'\s*' + mention, before_end):
        return True
    if re.search(r'(?:没有|沒有|无|無)(?:足够|充分|相关|相關)?(?:证据|證據|资料|資料|记录|記錄)(?:证明|證明|表明|显示|顯示)', before_end):
        return True
    if re.search(r'\b(?:cannot|must not|do not|does not|did not|have not|has not)\s+(?:claim|assert|assume|treat|provide)\b|\bno evidence (?:that|of|to show)\b', before_end, re.I):
        return True
    return bool(re.search(
        r"尚未|未能|尚待|待核实|有待|若|如果|拟|擬|计划|計劃|将|將|"
        r"不代表|不构成|不構成|不表示|不意味着|不意味著|并非|並非|不等于|不等於|"
        r"只能写|只能寫|仅可写|僅可寫|不得写|不得寫|不能写|不能寫|不要写|不要寫|"
        r"须采用|須採用|必须采用|必須採用|须使用|須使用|"
        r"\bnot yet\b|\bdoes not (?:mean|establish|prove)\b|\bnot (?:confirmed|secured|verified)\b|"
        r"\bif\b|\bplan to\b|\bonly (?:write|state)\b|\bmust not (?:write|state|claim)\b",
        before_end, re.I))


def _is_blocking(text: str) -> bool:
    for match in _BLOCKING.finditer(text):
        if not re.search(r"无需|无须|不必|不再|不需要|need not|no need", text[max(0, match.start()-12):match.start()], re.I):
            return True
    return False


def _text_requests(text: str) -> list[dict]:
    result = []
    for sentence in re.split(r"[。！？\n]|(?<=[.!?])\s+", text):
        blocking = _is_blocking(sentence)
        requested = any(not re.search(
            r"(?:无|無|不)(?:需|须|須|必|用)?$|不需要$|无需$|無需$|无须$|無須$|no need to\s*$|need not\s*$",
            sentence[:match.start()], re.I) for match in _REQUEST.finditer(sentence))
        if requested or blocking:
            result.append({'question': sentence.strip(), 'required_before_submission': blocking})
    return result


def output_verification_requests(data: dict) -> list[dict]:
    """Persist final structured requests and explicit prose gates via existing messages.

    No evidence is created. Text extraction remains conservative: an ordinary
    support plan is not automatically a prerequisite.
    """
    require_verification_requests(data)
    requests = [dict(item) for item in data.get('verification_requests', [])]
    for text in _business_texts(data):
        requests.extend(_text_requests(text))
    return requests


def require_verification_requests(data: dict[str, Any]) -> None:
    requests = data.get("verification_requests", [])
    if not isinstance(requests, list):
        raise ValueError("verification_requests must be a list")
    for item in requests:
        if (not isinstance(item, dict) or not isinstance(item.get("question"), str)
                or not item["question"].strip()
                or type(item.get("required_before_submission", False)) is not bool):
            raise ValueError("Each verification request needs a question and a boolean required_before_submission")


def conditions(state: SimulationState, company_id: str, package_id: str,
               extra_messages: Iterable[DiscussionMessage] = ()) -> list[dict[str, Any]]:
    """Collect the complete scope, independently of the short discussion window."""
    found: dict[str, dict[str, Any]] = {}
    for msg in [*state.agent_discussion_history, *extra_messages]:
        if msg.company_id != company_id or msg.package_id != package_id:
            continue
        requests = list(msg.verification_requests)
        # Old saved messages and responses without the optional structured field.
        requests.extend(_text_requests(f"{msg.content}\n{msg.recommendation}"))
        for request in requests:
            question = request["question"].strip()
            digest = hashlib.sha256(f"{company_id}\0{package_id}\0{question}".encode()).hexdigest()
            key = f"condition_{digest[:20]}"
            record = found.setdefault(key, {
                "condition_id": key, "company_id": company_id, "package_id": package_id,
                "question": question, "required_before_submission": False,
                "source_message_sha256": [], "status": "requested", "evidence": None,
            })
            record["required_before_submission"] |= request.get("required_before_submission", False)
            source_hash = hashlib.sha256(msg.content.encode()).hexdigest()
            if source_hash not in record["source_message_sha256"]:
                record["source_message_sha256"].append(source_hash)
    for key, record in found.items():
        review = state.verification_reviews.get(key)
        if review is not None:
            _require_review(review, record)
            record["status"] = review["status"]
            record["evidence"] = dict(review)
            if review["status"] == "assumed":
                # Internal review desk: the scenario record is silent and management
                # chose to bid with a disclosed assumption. Still unresolved and never
                # verified, but no longer an active submission gate.
                record["required_before_submission"] = False
                record["prerequisite_disposition"] = "proceed_as_disclosed_assumption"
    return list(found.values())


def record_review(state: SimulationState, company_id: str, package_id: str, condition_id: str,
                  *, source_ref: str, source_text: str, reviewer: str, status: str) -> None:
    """Application/operator entry point, NOT a model tool or model output field.

    'received' means a source was received; 'verified' requires an actual review;
    'rejected' preserves a failed check. No implicit promotion by the LLM.
    """
    record = next((item for item in conditions(state, company_id, package_id)
                   if item["condition_id"] == condition_id), None)
    if record is None:
        raise ValueError("Unknown condition in this company/package scope")
    review = dict(company_id=company_id, package_id=package_id, status=status,
                  source_ref=source_ref, source_text=source_text, reviewer=reviewer,
                  source_sha256=hashlib.sha256(source_text.encode()).hexdigest())
    _require_review(review, record)
    state.verification_reviews[condition_id] = review


def _require_review(review: dict, record: dict) -> None:
    if any(review.get(key) != record[key] for key in ("company_id", "package_id")):
        raise ValueError("Evidence review scope mismatch")
    if review.get("status") not in {"received", "verified", "rejected", "assumed", "unavailable"}:
        raise ValueError("Evidence review has invalid status")
    if any(not isinstance(review.get(key), str) or not review[key].strip()
           for key in ("source_ref", "source_text", "reviewer")):
        raise ValueError("Evidence review needs a source reference, source text and reviewer")
    if review.get("source_sha256") != hashlib.sha256(review["source_text"].encode()).hexdigest():
        raise ValueError("Evidence review source hash mismatch")


def evidence_context(records: list[dict[str, Any]], *, company_sources: dict | None = None,
                     narrative_grounding: bool = False) -> str:
    pending = [r["condition_id"] for r in records if r["status"] != "verified"]
    verified = [r["condition_id"] for r in records if r["status"] == "verified"]
    blockers = [r["condition_id"] for r in records if r["status"] != "verified" and r["required_before_submission"]]
    from src.company_narrative import narrative_context
    return (EVIDENCE_POLICY
            + (company_evidence_context(company_sources) if company_sources is not None else '')
            + (narrative_context() if narrative_grounding else '')
            + "\nHost-derived current disposition (IDs, not new evidence):\n"
            + json.dumps({"unresolved_condition_ids": pending, "verified_condition_ids": verified,
                          "active_submission_prerequisite_ids": blockers}, ensure_ascii=False)
            + "\nThe original required_before_submission flag is historical importance; "
            "only ACTIVE unresolved prerequisites block submission. Verified records are not waiting for another receipt."
            + (_DESK_NOTE if any(r["status"] in _DESK_STATUSES for r in records) else "")
            + "\nComplete condition register (not truncated):\n"
            + json.dumps(records, ensure_ascii=False) + "\n"
            "Final JSON must include unresolved_condition_ids for ALL non-verified conditions, "
            "ALL verified_condition_ids shown above, and bid_assumptions as a list of strings. "
            "A conditional bid intent is allowed; it does not verify conditions. "
            "An unresolved required_before_submission condition prevents submission, not discussion.\n")


def require_condition_disposition(data: dict, records: list[dict[str, Any]], *, submission: bool = False) -> None:
    expected = {r["condition_id"] for r in records if r["status"] != "verified"}
    verified = {r["condition_id"] for r in records if r["status"] == "verified"}
    for key in ("unresolved_condition_ids", "verified_condition_ids", "bid_assumptions"):
        values = data.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(f"{key} must be a list of nonempty strings")
        if len(values) != len(set(values)):
            raise ValueError(f"{key} must not contain duplicates")
    if set(data.get("unresolved_condition_ids", [])) != expected:
        raise ValueError(f"Carry ALL unresolved_condition_ids: {sorted(expected)}")
    claimed = set(data.get("verified_condition_ids", []))
    if not claimed.issubset(verified):
        raise ValueError("Model cannot verify a condition: checked source evidence is required")
    if claimed != verified:
        raise ValueError(f"Carry ALL application-verified condition ids without reopening them: {sorted(verified)}")
    _require_no_verified_reopening(data, records)
    if expected and data.get("decision") != "no_bid" and not data.get("bid_assumptions"):
        raise ValueError("Unresolved conditions need explicit bid_assumptions / risk boundaries")
    if submission and any(r["required_before_submission"] and r["status"] != "verified" for r in records):
        raise ValueError("Submission blocked by an unresolved explicit prerequisite")
    text = "\n".join(_business_texts(data))
    # Adversative boundaries prevent a prior disclaimer from licensing a new
    # affirmative claim: 'not confirmed, but ... already secured'.
    for clause in re.split(r"[。；;，,！？\n]|但是|然而|但|而是|\bbut\b|\bhowever\b", text, flags=re.I):
        for pattern, topic in ((_CONFIRMED, r"人员|岗位|角色|档期|可用|staff|personnel|availability|team|subcontract"),
                               (_QUALIFIED, r"资质|资格|业绩|qualification"),
                               (_AUDITED, r"供应商|供應商|供应渠道|供货渠道|供貨渠道|supplier|vendor"),
                               (_NO_CONFLICT, r"利益|关联|關聯|隶属|隸屬|conflict|affiliation")):
            for match in pattern.finditer(clause):
                if _claim_is_nonassertive(clause, match):
                    continue
                if pattern is _AUDITED:
                    # A future inquiry directed at audited vendors is a
                    # selection criterion, not a receipt that an audit passed.
                    # Modal context is required in this same outward field;
                    # later affirmative clauses remain independently checked.
                    planned = any(clause in value and re.search(
                        r'拟议实施计划|拟议计划|拟按|计划[:：]|planned implementation|proposed plan', value, re.I)
                        for value in _business_texts(data))
                    if planned and not re.search(r'已(?:经)?向|已完成|已经完成',clause) and re.search(r'向.{0,60}经审核的.{0,25}供应商.{0,8}询价',clause) and match.group().endswith('供应商'):
                        continue
                    if planned and not re.search(r'已(?:经)?由|已通过|已经审核',clause) and re.search(
                        r'由经审核的(?:外部)?(?:供应商|供货渠道).{0,8}(?:承担|提供|负责)',clause):
                        continue
                relevant = {r["condition_id"] for r in records if re.search(topic, r["question"], re.I)}
                if not relevant or not relevant.issubset(claimed):
                    raise ValueError("Unsupported confirmation: retain the condition or cite an application-reviewed source")
    if re.search(r"(?:所有|上述|这些).{0,15}(?:核查|核实|条件|事项).{0,15}(?:在)?提交前完成.{0,12}(?:不设|不作).{0,12}(?:前置|前提|门槛)", text):
        raise ValueError('Conflicting submission boundary: distinguish mandatory prerequisites from optional checks')


def _require_no_verified_reopening(data: dict, records: list[dict[str, Any]]) -> None:
    """Bounded compatibility checks; not general semantic condition matching.

    Exact repeated questions cover any topic. The prose check only covers the
    observed staffing-recheck problem when no staffing question remains open.
    It does not merge paraphrased questions or infer that a new source is valid.
    """
    require_verification_requests(data)
    closed = {re.sub(r"[\s。？！?！]", "", r["question"]) for r in records if r["status"] == "verified"}
    for request in data.get("verification_requests", []):
        question = re.sub(r"[\s。？！?！]", "", request["question"])
        if request.get("required_before_submission") and question in closed:
            raise ValueError("Verified condition reopened: the same application-reviewed question is not an active prerequisite")

    personnel = re.compile(r"人员|岗位|团队|档期|排期|\bstaff\b|personnel|availability|\bteam\b", re.I)
    staff_records = [r for r in records if personnel.search(r["question"])]
    if not staff_records or any(r["status"] != "verified" for r in staff_records):
        return
    staff_words = r"(?:人员|岗位|团队|档期|排期)"
    check_words = r"(?:确认|核实|核查|核验)"
    gate = re.compile(
        rf"(?:提交|投标)前.{{0,15}}{check_words}.{{0,18}}{staff_words}|"
        rf"(?:提交|投标)前.{{0,15}}{staff_words}.{{0,18}}{check_words}|"
        rf"(?:投标|提交)(?:前提|条件).{{0,20}}{staff_words}.{{0,15}}{check_words}|"
        rf"(?:档期|排期|人员可用性).{{0,8}}{check_words}.{{0,5}}未.{{0,8}}(?:闭环|完成|落实).{{0,8}}(?:前不提交|不提交)|"
        r"(?:confirm|verify|check).{0,12}(?:staff|personnel|team|availability).{0,25}before (?:bid )?submission", re.I)
    values = [v for k, v in data.items() if isinstance(v, str) and k != "thoughts"]
    values.extend(data.get("bid_assumptions", []))
    for text in values:
        for clause in re.split(r"[。；;，,\n]", text):
            match = gate.search(clause)
            if not match or not personnel.search(clause):
                continue
            # A stated change/expiry is a new question, not reuse of old status.
            if re.search(r"变更|更换|延期|过期|失效|新(?:的)?(?:包期|档期|排期|人员|岗位)|expired|changed|new period", clause, re.I):
                continue
            if re.search(r"无需|无须|不必|不再|不需要|已完成|已通过|need not|no need|already completed", clause[:match.start()], re.I):
                continue
            if re.search(r"已(?:经)?(?:完成|确认|核实|核查|核验)", match.group()):
                continue
            raise ValueError(
                "Verified condition reopened: staffing checks are already application-reviewed in this scope; "
                "do not require the same check again before submission. Preserve any distinct unresolved prerequisites."
            )


def guarded_validator(base: Callable[[dict], None], records: list[dict[str, Any]], *, submission: bool = False,
                      company_sources: dict | None = None, narrative_grounding: bool = False, task_role: str | None = None):
    def validate(data: dict) -> None:
        base(data)
        if company_sources is not None:
            require_company_assessment(data, company_sources)
        require_condition_disposition(data, records, submission=submission)
        role_review=None
        if task_role is not None:
            from src.task_role_contract import require_task_role
            role_review=require_task_role(data,task_role)
        if narrative_grounding:
            if company_sources is None:
                raise ValueError('Narrative grounding requires an explicit company evidence projection')
            from src.company_narrative import require_company_narrative
            data['company_narrative_review'] = require_company_narrative(data, company_sources,contextual=task_role is not None)
            if role_review is not None:
                data['company_narrative_review']['task_role_review']=role_review
    return validate


def disposition_fields(data: dict, records: list[dict] | None = None) -> dict[str, Any]:
    fields = {key: list(data.get(key, [])) for key in
              ("unresolved_condition_ids", "verified_condition_ids", "bid_assumptions")}
    if records is not None:
        # Host-derived IDs include newly persisted final requests. No model fact
        # is rewritten and no new request is promoted to verified.
        fields['unresolved_condition_ids'] = [r['condition_id'] for r in records if r['status'] != 'verified']
        fields['verified_condition_ids'] = [r['condition_id'] for r in records if r['status'] == 'verified']
    fields.update(assessment_fields(data))
    if 'task_role' in data:
        fields['task_role']=data['task_role']
    if 'company_narrative_review' in data:
        from copy import deepcopy
        fields['company_narrative_review'] = deepcopy(data['company_narrative_review'])
    return fields


def submitted_condition_context(bid) -> str:
    """Only submitted assumptions/ids, never the bidder's private evidence register."""
    return (f"Submitted unresolved condition ids: {bid.unresolved_condition_ids}\n"
            f"Submitted bid assumptions: {bid.bid_assumptions}\n"
            "These remain conditional; bid opening, evaluation or simulated award does not verify them "
            "or establish contract formation or available resources.")
