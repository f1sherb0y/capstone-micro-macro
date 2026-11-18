import pytest

from gba_construction_sim.backend.core.enums import ProjectStage
from gba_construction_sim.backend.decision.camel_provider import (
    CamelDecisionError,
    CamelDecisionProvider,
    CamelDecisionUnavailable,
)
from gba_construction_sim.backend.decision.rule_based_provider import RuleBasedDecisionProvider
from gba_construction_sim.backend.models.action import AgentAction
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.models.project_performance import ProjectPerformanceState
from gba_construction_sim.backend.models.stage_rule import StageRule
from gba_construction_sim.backend.storage.agent_database import agent_database


class _FakeMessage:
    def __init__(self, parsed=None, content=None):
        self.parsed = parsed
        self.content = content


class _FakeResponse:
    def __init__(self, message):
        self.msgs = [message]


class _FakeReasoningResponse:
    def __init__(self, reasoning_content):
        self.msgs = []
        self.info = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": reasoning_content,
                    }
                }
            ]
        }


class _FakeCamelAgent:
    def __init__(self, message, model_type=None):
        self.message = message
        self.model_type = model_type
        self.last_input_message = None
        self.last_output_schema = None

    def step(self, input_message, output_schema=None):
        self.last_input_message = input_message
        self.last_output_schema = output_schema
        return _FakeResponse(self.message)


class _FlakyCamelAgent(_FakeCamelAgent):
    def __init__(self, message):
        super().__init__(message)
        self.calls = 0

    def step(self, input_message, output_schema=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("429 model busy")
        return super().step(input_message, output_schema=output_schema)


class _FakeModelType:
    def __init__(self, *, is_zhipuai=False):
        self.is_zhipuai = is_zhipuai


class _FakeReasoningCamelAgent(_FakeCamelAgent):
    def step(self, input_message, output_schema=None):
        self.last_input_message = input_message
        self.last_output_schema = output_schema
        return _FakeReasoningResponse(
            '{"action_type":"submit_bid","project_id":"PTEST_CAMEL_REASONING",'
            '"agent_id":"CTEST_CAMEL_REASONING","decision":true,'
            '"data":{"bid_price":117000000},"reason":"Reasoning content carried the JSON payload."}'
        )


def _contractor(agent_id: str = "CTEST_CAMEL_001"):
    return EnterpriseAgentProfile(
        agent_id=agent_id,
        name="Test Contractor",
        role="Contractor",
        region="Shenzhen",
        enterprise_type="contractor",
        financial_capacity=0.8,
        construction_capability=0.75,
        risk_preference=0.6,
    )


def _project(project_id: str = "PTEST_CAMEL_001"):
    return ConstructionProject(
        project_id=project_id,
        name="Test Project",
        project_type="public_housing",
        region="Shenzhen",
        owner_id="OTEST_CAMEL_001",
        initial_budget=120_000_000,
        current_stage=ProjectStage.TENDERING,
        performance=ProjectPerformanceState(planned_duration=24),
    )


def _stage_rule():
    return StageRule(
        stage=ProjectStage.TENDERING,
        required_roles=["Owner", "QS", "Contractor"],
        allowed_actions={"Contractor": ["evaluate_tender", "submit_bid", "decline_bid"]},
        next_stage=ProjectStage.BID_EVALUATION,
    )


def _latest_trace(agent_id: str):
    traces = agent_database.get_agent_decision_trace(agent_id, limit=1)
    assert traces
    return traces[0]


def test_camel_provider_uses_structured_output_schema_and_parsed_output():
    agent = _contractor("CTEST_CAMEL_STRUCTURED")
    project = _project("PTEST_CAMEL_STRUCTURED")
    action = AgentAction(
        action_type="submit_bid",
        project_id=project.project_id,
        agent_id=agent.agent_id,
        decision=True,
        data={"bid_price": 118_000_000, "expected_profit": 0.11},
        reason="Good margin and sufficient resources.",
    )
    fake_camel = _FakeCamelAgent(_FakeMessage(parsed=action))
    provider = CamelDecisionProvider(camel_agent=fake_camel, auto_create_agent=False, strict=True)

    result = provider.decide(agent, {"project": project, "stage_rule": _stage_rule(), "tick": 6})

    assert result == action
    assert fake_camel.last_output_schema is AgentAction
    prompt = fake_camel.last_input_message.content
    assert "allowed_actions_for_role" in prompt
    assert "forbidden_action_data_keys" in prompt
    assert "Role-specific decision logic for Contractor" in prompt
    assert "You do not control lifecycle transitions" in prompt
    trace = _latest_trace(agent.agent_id)
    assert trace["camel_used"] is True
    assert trace["fallback_used"] is False
    assert trace["validation_result"]["valid"] is True
    assert trace["role"] == "Contractor"
    assert "submit_bid" in trace["available_actions"]
    assert trace["input_context"]["project"]["project_id"] == project.project_id
    assert trace["decision_reason"] == action.reason
    assert trace["model_name"]


def test_camel_provider_parses_json_content_from_message():
    agent = _contractor("CTEST_CAMEL_JSON")
    project = _project("PTEST_CAMEL_JSON")
    fake_camel = _FakeCamelAgent(
        _FakeMessage(
            content=(
                "```json\n"
                '{"action_type":"decline_bid","project_id":"PTEST_CAMEL_JSON",'
                '"agent_id":"CTEST_CAMEL_JSON","decision":false,'
                '"reason":"Insufficient margin."}\n'
                "```"
            )
        )
    )
    provider = CamelDecisionProvider(camel_agent=fake_camel, auto_create_agent=False, strict=True)

    result = provider.decide(agent, {"project": project, "stage_rule": _stage_rule(), "tick": 7})

    assert result.action_type == "decline_bid"
    assert result.decision is False
    trace = _latest_trace(agent.agent_id)
    assert trace["camel_used"] is True
    assert trace["fallback_used"] is False


def test_camel_provider_retries_transient_camel_rate_limit_without_fallback(monkeypatch):
    agent = _contractor("CTEST_CAMEL_RETRY")
    project = _project("PTEST_CAMEL_RETRY")
    action = AgentAction(
        action_type="evaluate_tender",
        project_id=project.project_id,
        agent_id=agent.agent_id,
        decision=True,
        reason="Evaluate tender before deciding bid price.",
    )
    fake_camel = _FlakyCamelAgent(_FakeMessage(parsed=action))
    monkeypatch.setenv("CAMEL_DECISION_RETRY_DELAY_SECONDS", "0")
    provider = CamelDecisionProvider(camel_agent=fake_camel, auto_create_agent=False, strict=True)

    result = provider.decide(agent, {"project": project, "stage_rule": _stage_rule(), "tick": 7})

    assert result.action_type == "evaluate_tender"
    assert fake_camel.calls == 2
    trace = _latest_trace(agent.agent_id)
    assert trace["camel_used"] is True
    assert trace["fallback_used"] is False


def test_camel_provider_uses_json_only_structured_path_for_zhipu_compatibility():
    agent = _contractor("CTEST_CAMEL_ZHIPU_JSON")
    project = _project("PTEST_CAMEL_ZHIPU_JSON")
    fake_camel = _FakeCamelAgent(
        _FakeMessage(
            content=(
                '{"action_type":"submit_bid","project_id":"PTEST_CAMEL_ZHIPU_JSON",'
                '"agent_id":"CTEST_CAMEL_ZHIPU_JSON","decision":true,'
                '"data":{"bid_price":119000000},"reason":"Resources and margin fit."}'
            )
        ),
        model_type=_FakeModelType(is_zhipuai=True),
    )
    provider = CamelDecisionProvider(camel_agent=fake_camel, auto_create_agent=False, strict=True)

    result = provider.decide(agent, {"project": project, "stage_rule": _stage_rule(), "tick": 7})

    assert result.action_type == "submit_bid"
    assert fake_camel.last_output_schema is None
    assert "Return exactly one raw JSON object" in fake_camel.last_input_message.content
    trace = _latest_trace(agent.agent_id)
    assert trace["camel_used"] is True
    assert trace["fallback_used"] is False


def test_camel_provider_extracts_zhipu_reasoning_content_payload():
    agent = _contractor("CTEST_CAMEL_REASONING")
    project = _project("PTEST_CAMEL_REASONING")
    fake_camel = _FakeReasoningCamelAgent(_FakeMessage(content=""), model_type=_FakeModelType(is_zhipuai=True))
    provider = CamelDecisionProvider(camel_agent=fake_camel, auto_create_agent=False, strict=True)

    result = provider.decide(agent, {"project": project, "stage_rule": _stage_rule(), "tick": 7})

    assert result.action_type == "submit_bid"
    assert result.reason == "Reasoning content carried the JSON payload."
    trace = _latest_trace(agent.agent_id)
    assert trace["camel_used"] is True
    assert trace["fallback_used"] is False


def test_camel_provider_rejects_output_outside_stage_actions_without_fallback():
    agent = _contractor("CTEST_CAMEL_BAD_ACTION")
    project = _project("PTEST_CAMEL_BAD_ACTION")
    fake_camel = _FakeCamelAgent(
        _FakeMessage(
            parsed=AgentAction(
                action_type="award_contract",
                project_id=project.project_id,
                agent_id=agent.agent_id,
                decision=True,
            )
        )
    )
    provider = CamelDecisionProvider(camel_agent=fake_camel, auto_create_agent=False, strict=True)

    with pytest.raises(CamelDecisionError, match="outside allowed stage actions"):
        provider.decide(agent, {"project": project, "stage_rule": _stage_rule(), "tick": 8})

    trace = _latest_trace(agent.agent_id)
    assert trace["selected_action"] == "award_contract"
    assert trace["camel_used"] is True
    assert trace["fallback_used"] is False
    assert trace["validation_result"]["valid"] is False


def test_camel_provider_rejects_state_mutation_without_fallback():
    agent = _contractor("CTEST_CAMEL_MUTATION")
    project = _project("PTEST_CAMEL_MUTATION")
    fake_camel = _FakeCamelAgent(
        _FakeMessage(
            parsed=AgentAction(
                action_type="submit_bid",
                project_id=project.project_id,
                agent_id=agent.agent_id,
                decision=True,
                data={"bid_price": 118_000_000, "current_stage": "construction"},
            )
        )
    )
    provider = CamelDecisionProvider(camel_agent=fake_camel, auto_create_agent=False, strict=True)

    with pytest.raises(CamelDecisionError, match="mutate simulation state"):
        provider.decide(agent, {"project": project, "stage_rule": _stage_rule(), "tick": 9})

    trace = _latest_trace(agent.agent_id)
    assert trace["selected_action"] == "submit_bid"
    assert trace["fallback_used"] is False
    assert trace["validation_result"]["valid"] is False
    assert "current_stage" in trace["validation_result"]["reason"]


def test_camel_provider_requires_bounded_stage_rule_context():
    agent = _contractor("CTEST_CAMEL_CONTEXT")
    provider = CamelDecisionProvider(
        camel_agent=_FakeCamelAgent(_FakeMessage(content="{}")),
        auto_create_agent=False,
        strict=True,
    )

    with pytest.raises(CamelDecisionError, match="stage_rule and a non-empty bounded action set"):
        provider.decide(agent, {"tick": 1})

    trace = _latest_trace(agent.agent_id)
    assert trace["camel_used"] is False
    assert trace["fallback_used"] is False
    assert trace["validation_result"]["valid"] is False


def test_camel_provider_does_not_create_rule_fallback_when_camel_is_unavailable():
    agent = _contractor("CTEST_CAMEL_UNAVAILABLE")
    project = _project("PTEST_CAMEL_UNAVAILABLE")
    provider = CamelDecisionProvider(auto_create_agent=False, strict=True)

    with pytest.raises(CamelDecisionUnavailable, match="auto-create is disabled"):
        provider.decide(agent, {"project": project, "stage_rule": _stage_rule(), "tick": 10})

    trace = _latest_trace(agent.agent_id)
    assert trace["selected_action"] is None
    assert trace["camel_used"] is False
    assert trace["fallback_used"] is False


def test_camel_provider_requires_explicit_rule_fallback_when_camel_is_unavailable():
    agent = _contractor("CTEST_CAMEL_NO_DEFAULT_FALLBACK")
    project = _project("PTEST_CAMEL_NO_DEFAULT_FALLBACK")
    provider = CamelDecisionProvider(auto_create_agent=False, strict=False)

    with pytest.raises(CamelDecisionUnavailable, match="auto-create is disabled"):
        provider.decide(agent, {"project": project, "stage_rule": _stage_rule(), "tick": 10})

    trace = _latest_trace(agent.agent_id)
    assert trace["camel_used"] is False
    assert trace["fallback_used"] is False


def test_camel_provider_allows_explicit_legacy_rule_fallback_when_camel_is_unavailable():
    agent = _contractor("CTEST_CAMEL_FALLBACK")
    project = _project("PTEST_CAMEL_FALLBACK")
    provider = CamelDecisionProvider(
        auto_create_agent=False,
        strict=False,
        fallback=RuleBasedDecisionProvider(),
    )

    result = provider.decide(agent, {"project": project, "stage_rule": _stage_rule(), "tick": 10})

    assert result.action_type in {"submit_bid", "decline_bid", "evaluate_tender"}
    assert "CAMEL unavailable" in result.reason
    trace = _latest_trace(agent.agent_id)
    assert trace["camel_used"] is False
    assert trace["fallback_used"] is True
    assert trace["validation_result"]["valid"] is True


def test_camel_provider_requires_configured_model_credentials(monkeypatch):
    agent = _contractor("CTEST_CAMEL_NO_KEY")
    project = _project("PTEST_CAMEL_NO_KEY")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CAMEL_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("CAMEL_DECISION_MODEL", "GPT_4O_MINI")
    monkeypatch.setenv("CAMEL_MODEL_PLATFORM", "OPENAI")
    provider = CamelDecisionProvider(auto_create_agent=True, strict=True)

    with pytest.raises(CamelDecisionUnavailable, match="OPENAI_API_KEY, DEEPSEEK_API_KEY, or CAMEL_API_KEY"):
        provider.decide(agent, {"project": project, "stage_rule": _stage_rule(), "tick": 11})

    trace = _latest_trace(agent.agent_id)
    assert trace["camel_used"] is False
    assert trace["fallback_used"] is False


def test_camel_provider_infers_zhipu_platform_for_glm_models(monkeypatch):
    monkeypatch.delenv("CAMEL_MODEL_PLATFORM", raising=False)
    monkeypatch.setenv("CAMEL_DECISION_MODEL", "GLM-4.7-Flash")
    monkeypatch.setenv("CAMEL_API_KEY", "test-key")

    model = CamelDecisionProvider._model_from_environment()

    assert getattr(getattr(model, "model_type", None), "value", None) == "GLM-4.7-Flash"
    assert getattr(getattr(model, "model_type", None), "token_limit", 0) > 0


def test_camel_provider_uses_openai_compatibility_for_deepseek(monkeypatch):
    monkeypatch.delenv("CAMEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CAMEL_MODEL_URL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("CAMEL_MODEL_PLATFORM", "OPENAI")
    monkeypatch.setenv("CAMEL_DECISION_MODEL", "deepseek-v4-flash")

    model = CamelDecisionProvider._model_from_environment()

    from camel.models.openai_compatibility_model import OpenAICompatibilityModel

    assert isinstance(model, OpenAICompatibilityModel)
    assert model.model_type.value == "deepseek-v4-flash"
    assert model.model_type.is_openai is False

    class _Backend:
        model_type = model.model_type

    class _Agent:
        model_backend = _Backend()

    assert CamelDecisionProvider._supports_output_schema_tool(_Agent()) is False
