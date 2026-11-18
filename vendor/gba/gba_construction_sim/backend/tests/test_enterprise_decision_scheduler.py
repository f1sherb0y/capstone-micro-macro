import asyncio

from gba_construction_sim.backend.models.action import AgentAction
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.services.camel_queue_metrics_service import camel_queue_metrics_service
from gba_construction_sim.backend.simulation.decision_request import DecisionPriority
from gba_construction_sim.backend.simulation.enterprise_decision_scheduler import EnterpriseDecisionScheduler
from gba_construction_sim.backend.storage.agent_database import agent_database


def _agent(agent_id: str = "A001") -> EnterpriseAgentProfile:
    return EnterpriseAgentProfile(
        agent_id=agent_id,
        name=f"Agent {agent_id}",
        role="Contractor",
        region="Guangzhou",
        enterprise_type="contractor",
    )


def _request(
    scheduler: EnterpriseDecisionScheduler,
    agent: EnterpriseAgentProfile,
    tick: int = 1,
    priority: DecisionPriority = DecisionPriority.P0_STAGE_CRITICAL,
):
    return scheduler.build_request(
        agent,
        {
            "tick": tick,
            "allowed_actions": ["submit_bid", "decline_bid"],
            "recent_messages": [],
        },
        decision_type="tender_decision",
        priority=priority,
        project_id="P001",
    )


def test_scheduler_runs_model_decisions_with_concurrency_limit():
    class AsyncDecisionProvider:
        def __init__(self):
            self.active = 0
            self.max_active = 0

        async def decide_async(self, agent, context):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return AgentAction(
                action_type="submit_bid",
                project_id="P001",
                agent_id=agent.agent_id,
                decision=True,
                reason="async decision",
            )

    provider = AsyncDecisionProvider()
    scheduler = EnterpriseDecisionScheduler(
        provider,
        concurrency_limit=3,
        tick_max_decisions=10,
        project_max_decisions=10,
        agent_max_decisions=1,
    )
    requests = [_request(scheduler, _agent(f"A{i:03d}")) for i in range(8)]

    results = scheduler.run_sync(requests)
    metrics = camel_queue_metrics_service.snapshot()

    assert all(result.ok for result in results)
    assert provider.max_active == 3
    assert metrics["completed"] == 8
    assert metrics["failed"] == 0
    trace = agent_database.get_agent_decision_trace("A000", limit=1)[0]
    assert trace["retry_info"]["scheduler_status"] == "completed"
    assert "queue_ms" in trace["retry_info"]
    assert "model_ms" in trace["retry_info"]


def test_scheduler_skips_requests_after_tick_budget():
    class SyncDecisionProvider:
        def decide(self, agent, context):
            return AgentAction(
                action_type="submit_bid",
                project_id="P001",
                agent_id=agent.agent_id,
                decision=True,
                reason="sync decision",
            )

    scheduler = EnterpriseDecisionScheduler(
        SyncDecisionProvider(),
        concurrency_limit=4,
        tick_max_decisions=2,
        project_max_decisions=10,
        agent_max_decisions=10,
    )
    requests = [_request(scheduler, _agent(f"B{i:03d}")) for i in range(5)]

    results = scheduler.run_sync(requests)
    completed = [result for result in results if result.ok]
    skipped = [result for result in results if result.skipped_reason]
    metrics = camel_queue_metrics_service.snapshot()

    assert len(completed) == 2
    assert len(skipped) == 3
    assert {result.skipped_reason for result in skipped} == {"camel_tick_budget_exhausted"}
    assert metrics["completed"] == 2
    assert metrics["skipped_by_budget"] == 3
    trace = agent_database.get_agent_decision_trace(skipped[0].request.agent_id, limit=1)[0]
    assert trace["retry_info"]["scheduler_status"] == "skipped"
    assert trace["retry_info"]["skipped_reason"] == "camel_tick_budget_exhausted"


def test_scheduler_supports_legacy_sync_decision_provider():
    calls = []

    class SyncDecisionProvider:
        def decide(self, agent, context):
            calls.append(context["request_id"])
            return AgentAction(
                action_type="submit_bid",
                project_id="P001",
                agent_id=agent.agent_id,
                decision=True,
                reason="sync decision",
            )

    scheduler = EnterpriseDecisionScheduler(
        SyncDecisionProvider(),
        concurrency_limit=2,
        tick_max_decisions=5,
        project_max_decisions=5,
        agent_max_decisions=5,
    )

    results = scheduler.run_sync([_request(scheduler, _agent("A001"))])

    assert results[0].ok
    assert calls == ["tick1-P001-A001-tender_decision"]


def test_scheduler_uses_provider_aware_default_rate_limit(monkeypatch):
    monkeypatch.delenv("CAMEL_MODEL_MIN_INTERVAL_MS", raising=False)
    monkeypatch.setenv("CAMEL_MODEL_PLATFORM", "ZHIPU")
    scheduler = EnterpriseDecisionScheduler(object())

    assert scheduler.model_min_interval_ms == 1200


def test_scheduler_rate_limit_env_override_wins(monkeypatch):
    monkeypatch.setenv("CAMEL_MODEL_PLATFORM", "ZHIPU")
    monkeypatch.setenv("CAMEL_MODEL_MIN_INTERVAL_MS", "250")
    scheduler = EnterpriseDecisionScheduler(object())

    assert scheduler.model_min_interval_ms == 250


def test_scheduler_rate_limit_cooldown_skips_low_priority_but_keeps_p1(monkeypatch):
    monkeypatch.setenv("CAMEL_RATE_LIMIT_COOLDOWN_SECONDS", "30")
    monkeypatch.setenv("CAMEL_RATE_LIMIT_MIN_INTERVAL_MS", "2000")

    class Provider:
        def __init__(self):
            self.calls = 0

        def decide(self, agent, context):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("429 Too Many Requests")
            return AgentAction(
                action_type="submit_bid",
                project_id="P001",
                agent_id=agent.agent_id,
                decision=True,
                reason="protected priority decision",
            )

    provider = Provider()
    scheduler = EnterpriseDecisionScheduler(
        provider,
        concurrency_limit=1,
        tick_max_decisions=10,
        project_max_decisions=10,
        agent_max_decisions=10,
    )

    first = scheduler.run_sync([
        _request(scheduler, _agent("RL0"), priority=DecisionPriority.P0_STAGE_CRITICAL)
    ])
    assert first[0].status == "failed"
    assert "429" in first[0].error

    second = scheduler.run_sync([
        _request(scheduler, _agent("RL1"), priority=DecisionPriority.P1_RESOURCE_CASHFLOW),
        _request(scheduler, _agent("RL2"), priority=DecisionPriority.P2_INTERACTION),
    ])
    by_agent = {result.request.agent_id: result for result in second}
    metrics = camel_queue_metrics_service.snapshot()

    assert by_agent["RL1"].ok
    assert by_agent["RL2"].skipped_reason == "camel_rate_limit_cooldown_low_priority"
    assert metrics["skipped_by_rate_limit"] == 1
    assert metrics["cooldown_remaining_ms"] > 0
    assert metrics["adaptive_min_interval_ms"] >= 2000
