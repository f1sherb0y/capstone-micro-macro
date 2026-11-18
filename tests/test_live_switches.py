"""Offline checks for the opt-in live-simulation switches of AgentRuntime.

Covers the internal review desk, organization_mode and targeted repair retries.
No network: every model answer comes from a scripted stub.
"""
import asyncio
import json

from src.agent_runtime import AgentRuntime
from src.condition_review import review_blocking_conditions
from src.models import Company, DiscussionMessage, MemberAgent, SimulationState, TenderPackage, dump, load_simulation_state
from src.verification import conditions, evidence_context

COMPANY = Company("designer_001", "甲设计公司", "designer", "市政设计企业", ["管线设计"], ["人员信息未披露"],
                  ["工程设计"], ["未提供"], "未提供明确规模", [], ["design_package"])
PACKAGE = TenderPackage("design_package", "design", "设计包", "排放管改道设计", "designer", ["市政设计能力"],
                        ["技术方案"], "总价报价", ["技术匹配"], "业主评审后决定")
QUESTIONS = ["情景是否允许本企业以设计角色独立投标", "拟派项目负责人的姓名和档期", "第三方检测机构的书面报价"]


def message(requests):
    return DiscussionMessage("msg_000001", "bid_participation_decision", 1, "initial_opinion", "designer_001", "designer",
                             "design_package", "agent", "甲", "技术", "经理", "opinion", "", "讨论记录", [], [], "", "", "",
                             "2026-11-18T00:00:00", verification_requests=requests)


def blocking_state():
    return SimulationState(agent_discussion_history=[
        message([{"question": question, "required_before_submission": True} for question in QUESTIONS])])


class Scripted:
    """Return the scripted answers in order and record every request."""

    def __init__(self, answers):
        self.answers, self.requests = list(answers), []

    async def achat(self, messages, temperature=0.2):
        self.requests.append(messages)
        answer = self.answers.pop(0)
        return answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)


def desk_runtime(answers):
    runtime = AgentRuntime(Scripted(answers))
    runtime.internal_condition_review = True
    return runtime


def run(coroutine):
    return asyncio.run(coroutine)


def test_switches_are_off_by_default():
    runtime = AgentRuntime(Scripted([]))
    assert runtime.internal_condition_review is False
    assert runtime.organization_mode == "multi" and runtime.targeted_repair_retries == 0
    state = blocking_state()
    assert run(review_blocking_conditions(state, runtime, COMPANY, PACKAGE)) == []
    assert state.verification_reviews == {} and runtime.llm.requests == []


def test_desk_records_established_assumed_and_unavailable_outcomes():
    state = blocking_state()
    ids = {r["question"]: r["condition_id"] for r in conditions(state, "designer_001", "design_package")}
    runtime = desk_runtime([{"reviews": [
        {"condition_id": ids[QUESTIONS[0]], "finding": "established", "source_ids": ["P3"], "note": "包要求的角色即设计。", "disposition": None},
        {"condition_id": ids[QUESTIONS[1]], "finding": "not_in_record", "source_ids": [], "note": "资料没有人员名单。",
         "disposition": "proceed_as_disclosed_assumption"},
        {"condition_id": ids[QUESTIONS[2]], "finding": "not_in_record", "source_ids": [], "note": "没有任何报价。", "disposition": "withdraw"}]}])
    outcomes = run(review_blocking_conditions(state, runtime, COMPANY, PACKAGE))
    assert {o["question"]: o["status"] for o in outcomes} == dict(zip(QUESTIONS, ["verified", "assumed", "unavailable"]))
    records = {r["question"]: r for r in conditions(state, "designer_001", "design_package")}
    # A silent record is never promoted to verified; the assumption stays unresolved but stops gating.
    assert records[QUESTIONS[1]]["status"] == "assumed" and records[QUESTIONS[1]]["required_before_submission"] is False
    assert records[QUESTIONS[2]]["required_before_submission"] is True
    assert records[QUESTIONS[0]]["evidence"]["source_text"].startswith("[P3] package.required_role")
    blockers = [r for r in records.values() if r["required_before_submission"] and r["status"] != "verified"]
    assert [r["question"] for r in blockers] == [QUESTIONS[2]]
    assert "Internal review desk results" in evidence_context(list(records.values()))
    assert state.validation_context["internal_condition_review"] is True
    assert any(e["event_type"] == "internal_condition_review" for e in state.tender_process_log)
    restored = load_simulation_state(dump(state))
    assert conditions(restored, "designer_001", "design_package") == list(records.values())
    # Already reviewed prerequisites are not sent to the model again.
    assert run(review_blocking_conditions(state, runtime, COMPANY, PACKAGE)) == []
    assert len(runtime.llm.requests) == 1


def test_desk_leaves_conditions_unreviewed_when_the_answer_cites_unknown_sources():
    state = blocking_state()
    ids = [r["condition_id"] for r in conditions(state, "designer_001", "design_package")]
    invalid = {"reviews": [{"condition_id": cid, "finding": "established", "source_ids": ["Z9"], "note": "编造来源。",
                            "disposition": None} for cid in ids]}
    runtime = desk_runtime([invalid, invalid])
    assert run(review_blocking_conditions(state, runtime, COMPANY, PACKAGE)) == []
    assert state.verification_reviews == {}
    assert all(r["status"] == "requested" for r in conditions(state, "designer_001", "design_package"))


def agents():
    return [MemberAgent(f"designer_001_{i:02d}", name, "designer_001", "designer", department, "经理", "", [], authority, "直接")
            for i, (name, department, authority) in enumerate([("乙", "技术", "review"), ("丙", "商务", "review"), ("丁", "管理", "final")], start=1)]


def test_organization_modes_change_who_deliberates():
    reply = {"thoughts": "", "content": "意见", "recommendation": "投标", "decision_impact": "中"}
    rounds = [(1, "initial_opinion"), (2, "response_and_revision"), (3, "summary")]
    spoken = {}
    for mode in ("single", "solo", "multi"):
        runtime = AgentRuntime(Scripted([reply] * 20), profile="full")
        runtime.organization_mode = mode
        state = SimulationState()
        run(runtime.discuss_async(state, "bid_participation_decision", COMPANY, "design_package", agents(), rounds, "context"))
        spoken[mode] = [m.agent_name for m in state.agent_discussion_history]
    assert spoken["single"] == []
    assert spoken["solo"] == ["丁", "丁", "丁"]
    assert spoken["multi"] == ["乙", "丙", "丁", "乙", "丙", "丁", "丁"]


def test_targeted_repair_shows_the_rejected_answer_and_is_bounded():
    def validate(data):
        if data["total"] != sum(data["items"]):
            raise ValueError(f"items sum {sum(data['items'])} does not match total {data['total']}")
    bad = {"items": [1, 2], "total": 4}
    runtime = AgentRuntime(Scripted([bad, bad, {"items": [1, 2], "total": 3}]))
    runtime.targeted_repair_retries = 2
    assert run(runtime.ask_json_async("system", "MARK", "prompt", validator=validate))["total"] == 3
    repair = runtime.llm.requests[1][-1]["content"]
    assert "TARGETED_REPAIR_REQUIRED" in repair and '"total": 4' in repair and "items sum 3" in repair
    assert [e["kind"] for e in runtime.recovery_events] == ["response_contract_retry"] * 2

    limited = AgentRuntime(Scripted([bad, bad]))
    try:
        run(limited.ask_json_async("system", "MARK", "prompt", validator=validate))
    except ValueError:
        pass
    else:
        raise AssertionError("Without the switch only one regeneration is allowed")
    assert "SCHEMA_REPAIR_REQUIRED" in limited.llm.requests[1][-1]["content"]
