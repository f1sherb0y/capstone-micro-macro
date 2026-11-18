"""Offline behavioral checks for the legacy free-generation tender workflow."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.agent_runtime import AgentRuntime
from src.agent_message_contracts import require_agent_message
from src.models import DiscussionMessage, ParticipationDecision, SimulationState, dump, load_simulation_state
from src.stages.bid_documents import generate_bid_documents, _bid_prompt
from src.stages.participation import run_bid_participation
from src.stages.reconsideration import reconsider_after_failed_consortiums, _prompt
from src.stages.opening import _opening_context
from src.stages.evaluation import _evaluation_prompt
from src.stages.award import _award_discussion_context, _award_prompt, _award_task
from src.stages.execution_handoff import _package_handoff
from src.models import OpeningRecord, EvaluationReport
from src.verification import conditions, record_review, require_condition_disposition, evidence_context
from tests.test_bid_document_stage import _state, BidLLM


def message(content="请项目经理本周内提交人员分配情况", *, company_id="designer_001", package_id="design_package", **extra):
    return DiscussionMessage(
        message_id="msg_000001", stage="bid_participation_decision", round=1, round_type="initial_opinion",
        company_id=company_id, company_role="designer", package_id=package_id, agent_id="agent", agent_name="甲",
        department="技术", position="经理", message_type="opinion", thoughts="private",
        content=content, references=[], response_to=[], recommendation="", decision_impact="", final_decision="",
        timestamp="2026-11-08T00:00:00", **extra)


def disposition(records):
    return dict(decision="bid", content="拟安排人员，并在内部排期复核后落实。",
                unresolved_condition_ids=[r["condition_id"] for r in records if r["status"] != "verified"],
                verified_condition_ids=[], bid_assumptions=["人员排期待核实，普通分包为拟采用的交付方案。"])


def scoped(state):
    return conditions(state, "designer_001", "design_package")


def test_all_conditions_survive_truncation_import_and_checkpoint():
    state = SimulationState(agent_discussion_history=[message()])
    original = scoped(state)
    state.agent_discussion_history += [message(f"普通讨论{i}") for i in range(20)]
    assert scoped(state) == original
    runtime = AgentRuntime(BidLLM())
    imported = SimulationState()
    runtime.message_counter = 100
    runtime.import_messages(imported, deepcopy(state.agent_discussion_history))
    assert scoped(imported) == original
    restored = load_simulation_state(dump(imported))
    assert scoped(restored) == original
    assert original[0]["condition_id"] in evidence_context(scoped(restored))


@pytest.mark.parametrize("claim", ["关键角色均有充足人员可调配", "关键岗位人员档期已初步确认", "人员可用性已核实，将准备投标文件", "计划编制标书，但关键岗位人员档期已初步确认"])
def test_old_unsupported_availability_claims_are_rejected(claim):
    records = scoped(SimulationState(agent_discussion_history=[message()]))
    data = disposition(records) | {"content": claim}
    with pytest.raises(ValueError, match="Unsupported confirmation"):
        require_condition_disposition(data, records)


@pytest.mark.parametrize("plan", ["拟投入7人。", "人员档期尚未确认。", "若人员档期已确认，可按此计划实施。", "计划在核实后安排分包。"])
def test_plans_and_unverified_disclosures_are_not_treated_as_confirmations(plan):
    records = scoped(SimulationState(agent_discussion_history=[message()]))
    require_condition_disposition(disposition(records) | {"content": plan}, records)


def test_model_cannot_clear_omit_or_invent_conditions():
    records = scoped(SimulationState(agent_discussion_history=[message()]))
    with pytest.raises(ValueError, match="Carry ALL"):
        require_condition_disposition(disposition(records) | {"unresolved_condition_ids": []}, records)
    with pytest.raises(ValueError, match="cannot verify"):
        require_condition_disposition(disposition(records) | {"verified_condition_ids": [records[0]["condition_id"]]}, records)
    with pytest.raises(ValueError, match="cannot verify"):
        require_condition_disposition(disposition(records) | {"verified_condition_ids": ["invented"]}, records)


def test_received_source_does_not_verify_and_scope_hash_are_checked():
    state = SimulationState(agent_discussion_history=[message()])
    key = scoped(state)[0]["condition_id"]
    review = dict(source_ref="fixture:hr-roster", source_text="Synthetic HR roster: personnel available for this package.",
                  reviewer="fixture:independent-reviewer", status="received")
    with pytest.raises(ValueError, match="Unknown condition"):
        record_review(state, "other_company", "design_package", key, **review)
    with pytest.raises(ValueError, match="Unknown condition"):
        record_review(state, "designer_001", "other_package", key, **review)
    record_review(state, "designer_001", "design_package", key, **review)
    assert scoped(state)[0]["status"] == "received"
    bad = disposition(scoped(state)) | {"content": "关键岗位人员档期已初步确认"}
    with pytest.raises(ValueError, match="Unsupported confirmation"):
        require_condition_disposition(bad, scoped(state))
    record_review(state, "designer_001", "design_package", key, **(review | {"status": "verified"}))
    restored = load_simulation_state(dump(state))
    good = disposition(scoped(restored)) | {"content": bad["content"], "verified_condition_ids": [key]}
    require_condition_disposition(good, scoped(restored))
    restored.verification_reviews[key]["source_text"] = "tampered"
    with pytest.raises(ValueError, match="hash mismatch"):
        scoped(restored)


def test_qualification_prerequisite_blocks_submission_but_not_conditional_intent():
    state = SimulationState(agent_discussion_history=[message(
        "若市场部能确认分包业绩可计入我方资格，则可投标；否则退出。")])
    records = scoped(state)
    assert records and all(r["required_before_submission"] for r in records)
    data = disposition(records)
    require_condition_disposition(data, records)
    with pytest.raises(ValueError, match="Submission blocked"):
        require_condition_disposition(data, records, submission=True)


def test_pending_submission_is_distinct_from_no_bid_and_needs_no_model_call():
    state = _state()
    state.agent_discussion_history = [message("若市场部能确认分包业绩可计入我方资格，则可投标；否则退出。", company_id="designer_002")]
    class NeverCall:
        async def achat(self, *args, **kwargs):
            raise AssertionError("Preflight must block without any LLM calls")
    # First consortium is blocked by its non-leading member; remove the second task.
    state.participation_decisions = state.participation_decisions[:1]
    asyncio.run(generate_bid_documents(state, AgentRuntime(NeverCall())))
    assert state.bid_documents == []
    assert state.participation_decisions[0].decision == "bid_with_consortium"
    assert state.tender_process_log[-1]["event_type"] == "bid_submission_pending_verification"


def test_source_failure_remains_pending_not_verified():
    state = SimulationState(agent_discussion_history=[message()])
    key = scoped(state)[0]["condition_id"]
    record_review(state, "designer_001", "design_package", key, source_ref="fixture:negative",
                  source_text="Synthetic review: not available", reviewer="fixture:reviewer", status="rejected")
    assert scoped(state)[0]["status"] == "rejected"
    require_condition_disposition(disposition(scoped(state)), scoped(state))


def test_malformed_request_rejected_and_legacy_checkpoint_loads():
    data = dict(thoughts="", content="", recommendation="", decision_impact="",
                verification_requests=[{"question": "availability", "required_before_submission": "false"}])
    with pytest.raises(ValueError, match="boolean"):
        require_agent_message(data)
    assert load_simulation_state({}).verification_reviews == {}
    assert load_simulation_state({"participation_decisions": [dict(company_id="c", package_id="p", decision="bid", reason="")]}).participation_decisions[0].bid_assumptions == []


class ConditionalLLM(BidLLM):
    def __init__(self, *, bad_confirmation=False, new_blocker=False):
        super().__init__()
        self.bad_confirmation = bad_confirmation
        self.new_blocker = new_blocker
        self.final_bid_calls = 0
        self.prompts = []

    async def achat(self, messages, temperature=0.2):
        prompt = messages[1]["content"]
        self.prompts.append(prompt)
        marker = prompt.splitlines()[0]
        if marker == "AGENT_MESSAGE":
            question = ("若市场部能确认分包业绩计入资格，则可投标；否则退出。"
                        if self.new_blocker and "bid_document_generation" in prompt else "请人力资源部核实人员档期。")
            return json.dumps(dict(thoughts="", content=question, recommendation="conditional", decision_impact="check",
                                   verification_requests=[dict(question=question, required_before_submission=self.new_blocker)]))
        records, _ = json.JSONDecoder().raw_decode(prompt.rsplit("Complete condition register (not truncated):\n", 1)[1])
        data = disposition(records)
        if marker == "BID_DOCUMENT":
            self.final_bid_calls += 1
            return json.dumps(json.loads(await super().achat(messages, temperature)) | data)
        data |= dict(thoughts="", reason="保持责任边界与排期假设", decision="bid_with_consortium" if marker == "MANAGEMENT_DECISION" else "bid")
        if self.bad_confirmation:
            data["content"] = "关键岗位人员档期已初步确认"
        return json.dumps(data)


def solo_state():
    state = _state()
    state.companies = state.companies[:1]
    state.consortiums = []
    state.participation_decisions = []
    return state


def test_actual_stage_chain_retains_conditions_into_bid_after_reconsideration():
    state = solo_state()
    llm = ConditionalLLM()
    runtime = AgentRuntime(llm, profile="smoke")
    asyncio.run(run_bid_participation(state, runtime))
    first = list(state.participation_decisions[0].unresolved_condition_ids)
    assert first
    asyncio.run(reconsider_after_failed_consortiums(state, runtime))
    assert state.participation_decisions[0].decision == "bid"
    assert set(first) <= set(state.participation_decisions[0].unresolved_condition_ids)
    restored = load_simulation_state(dump(state))
    asyncio.run(generate_bid_documents(restored, runtime))
    assert len(restored.bid_documents) == 1
    assert set(first) <= set(restored.bid_documents[0].unresolved_condition_ids)
    assert restored.bid_documents[0].verified_condition_ids == []
    assert restored.bid_documents[0].bid_assumptions
    assert "Your documented company context" in "\n".join(llm.prompts)


def test_actual_management_guard_records_invalid_output_as_degraded():
    state = solo_state()
    runtime = AgentRuntime(ConditionalLLM(bad_confirmation=True), profile="smoke")
    asyncio.run(run_bid_participation(state, runtime))
    assert state.participation_decisions[0].decision == "no_bid"
    assert "Degraded fallback" in state.participation_decisions[0].reason
    assert state.participation_decisions[0].unresolved_condition_ids
    assert state.agent_discussion_history  # failed output must not erase valid discussion
    assert any(e["kind"] == "participation_conservative_fallback" for e in runtime.recovery_events)


def test_new_drafting_prerequisite_preserves_messages_and_defers_submission():
    state = solo_state()
    state.participation_decisions = [ParticipationDecision("designer_001", "design_package", "bid", "conditional")]
    llm = ConditionalLLM(new_blocker=True)
    asyncio.run(generate_bid_documents(state, AgentRuntime(llm, profile="smoke")))
    assert state.bid_documents == [] and llm.final_bid_calls == 0
    assert state.agent_discussion_history
    assert any(r["required_before_submission"] for r in scoped(state))


def test_private_company_notes_not_in_other_company_reconsideration():
    state = solo_state()
    secret = message("another firm's private resources", company_id="other")
    secret.stage = "consortium_formation"
    state.agent_discussion_history = [secret]
    text = _prompt(state, SimulationState(), state.companies[0], state.tender_packages[0],
                   ParticipationDecision("designer_001", "design_package", "bid_with_consortium", ""))
    assert secret.content not in text
    assert scoped(state) == []


def test_colliding_local_message_ids_do_not_discard_current_drafting():
    state = solo_state()
    old = message("earlier discussion")
    state.agent_discussion_history = [old]
    current = message("new bid drafting is visible")
    current.stage = "bid_document_generation"
    text = _bid_prompt(state, "designer_001", "One", "company", "design_package", [current])
    assert old.message_id == current.message_id
    assert current.content in text


@pytest.mark.parametrize("process", ["03", "04", "07", "08"])
def test_saved_review_excerpts_supply_pending_conditions_without_rewriting_sources(process):
    path = Path("Capstone报告/验证体系/论文图表/微观验证证据图册/评审准备") / f"PROCESS-{process}.json"
    if not path.exists():
        pytest.skip("Historical evidence is only in the full handoff repository (XiongBT49/capstone-micro-macro)")
    before =hashlib.sha256(path.read_bytes()).hexdigest()
    source = json.loads(path.read_text(encoding="utf-8"))
    state = SimulationState()
    for row in source["messages"]:
        item = message(row["content"], company_id=row["company_id"], package_id=source["package_id"])
        item.recommendation = row.get("recommendation", "")
        state.agent_discussion_history.append(item)
    records = [r for cid in {m.company_id for m in state.agent_discussion_history}
               for r in conditions(state, cid, source["package_id"])]
    assert records and all(r["status"] == "requested" and r["evidence"] is None for r in records)
    if process == "07":
        assert any(r["required_before_submission"] for r in records)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_submitted_conditions_remain_visible_through_award_and_handoff():
    state = solo_state()
    llm = ConditionalLLM()
    runtime = AgentRuntime(llm, profile="smoke")
    state.participation_decisions = [ParticipationDecision("designer_001", "design_package", "bid", "plan")]
    asyncio.run(generate_bid_documents(state, runtime))
    bid = state.bid_documents[0]
    report = EvaluationReport("design_package", [], [], "comparison", bid.bidder_id, "review")
    record = OpeningRecord("design_package", [dict(bidder_id=bid.bidder_id, bidder_name=bid.bidder_name,
        bidder_type=bid.bidder_type, quotation=bid.quotation, successfully_submitted=True,
        quotation_breakdown=bid.quotation_breakdown, submission_summary=bid.submission_summary,
        unresolved_condition_ids=bid.unresolved_condition_ids, bid_assumptions=bid.bid_assumptions)], "opened")
    for text in (_opening_context(record), _evaluation_prompt(state, state.tender_packages[0], [bid]),
                 _award_discussion_context(report, [bid]), _award_prompt(report, [bid], [])):
        assert bid.unresolved_condition_ids[0] in text
        assert bid.bid_assumptions[0] in text
        assert "fixture:hr-roster" not in text  # private review source is not disclosed
    from src.mock_llm import MockLLMClient
    # Deterministic mock is used only to exercise final artifact propagation.
    _, award = asyncio.run(_award_task(state, AgentRuntime(MockLLMClient(), profile="smoke"), report,
                                      state.companies[0], state.company_agent_rosters["designer_001"], 1, 1))
    assert set(bid.unresolved_condition_ids) <= set(award.unresolved_condition_ids)
    assert award.pending_clarifications  # newly raised owner checks are retained too
    assert award.bid_assumptions == bid.bid_assumptions
    handoff = _package_handoff(state, dump(award))
    assert handoff["unresolved_condition_ids"] == award.unresolved_condition_ids
    assert handoff["pending_clarifications"] == award.pending_clarifications


def test_run_outputs_persist_requests_reviews_and_decision_conditions(tmp_path):
    from src.writers import write_outputs
    from src.models import ProjectIdea
    state = solo_state()
    state.project_idea = ProjectIdea("fixture", "Local test", "design", "Macau", "Build", "", "", "", [], "fixture")
    state.agent_discussion_history = [message()]
    key = scoped(state)[0]["condition_id"]
    record_review(state, "designer_001", "design_package", key, source_ref="fixture:hr",
                  source_text="Synthetic roster", reviewer="fixture:reviewer", status="received")
    state.participation_decisions = [ParticipationDecision("designer_001", "design_package", "bid", "plan",
                                                          unresolved_condition_ids=[key], bid_assumptions=["排期待核实"])]
    files = write_outputs(state, tmp_path)
    records = json.loads(Path(files["verification_conditions"]).read_text(encoding="utf-8"))
    decisions = json.loads(Path(files["participation_decisions"]).read_text(encoding="utf-8"))
    assert records[0]["status"] == "received"
    assert records[0]["evidence"]["source_ref"] == "fixture:hr"
    assert decisions[0]["unresolved_condition_ids"] == [key]


@pytest.mark.parametrize("statement", [
    "投标前须完成团队可用性核查，确认现场人员可覆盖工期。",
    "由项目经理提交当前人员分配情况，作为提交前的硬性确认事项。",
    "提交前须完成关键人员档期确认、团队可用性摘要和价格基础核实。",
    "We must verify personnel availability before submission.",
])
def test_new_explicit_submission_prerequisites_are_retained(statement):
    state = SimulationState(agent_discussion_history=[message(statement)])
    records = scoped(state)
    assert records and any(r["required_before_submission"] for r in records)


@pytest.mark.parametrize("statement", [
    "拟投入7人，由公司统一承担责任。",
    "拟在提交前联系普通分包商了解情况。",
    "We will prepare a proposal before submission.",
])
def test_ordinary_plans_are_not_promoted_to_submission_prerequisites(statement):
    records = scoped(SimulationState(agent_discussion_history=[message(statement)]))
    assert not any(r["required_before_submission"] for r in records)
