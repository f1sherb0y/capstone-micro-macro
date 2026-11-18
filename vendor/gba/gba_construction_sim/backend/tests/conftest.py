import json
from typing import Any

import pytest


class _DeterministicCamelMessage:
    def __init__(self, content: str):
        self.content = content


class _DeterministicCamelResponse:
    def __init__(self, content: str):
        self.msgs = [_DeterministicCamelMessage(content)]


class _DeterministicCamelAgent:
    """Test double for CAMEL ChatAgent; keeps tests offline without rule fallback."""

    def step(self, input_message, output_schema=None):
        content = getattr(input_message, "content", "")
        decision_context = self._extract_decision_context(content)
        stage_rule = decision_context.get("stage_rule") or {}
        project = decision_context.get("project") or {}
        agent = decision_context.get("agent") or {}
        allowed_actions = stage_rule.get("allowed_actions_for_role") or []
        action_type = self._select_action(allowed_actions)
        action = {
            "action_type": action_type,
            "project_id": project.get("project_id"),
            "agent_id": agent.get("agent_id"),
            "decision": True,
            "data": self._action_data(action_type, decision_context),
            "reason": "Deterministic CAMEL test agent selected a valid stage action.",
        }
        if output_schema:
            return _DeterministicCamelResponse(json.dumps(action))
        return _DeterministicCamelResponse(json.dumps(action))

    @staticmethod
    def _extract_decision_context(content: str) -> dict:
        marker = "Decision context:\n"
        if marker not in content:
            return {}
        raw = content.split(marker, 1)[1].strip()
        raw = raw.split("\n\nReturn exactly one raw JSON object", 1)[0].strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _select_action(allowed_actions: list[str]) -> str:
        preferred = [
            "initiate_project",
            "submit_bid",
            "accept_contract",
            "approve_completion",
            "prepare_final_account",
            "execute_work",
            "prepare_tender_documents",
            "approve",
        ]
        for action in preferred:
            if action in allowed_actions:
                return action
        return allowed_actions[0] if allowed_actions else "maintain_operations"

    @staticmethod
    def _action_data(action_type: str, context: dict) -> dict:
        if action_type == "initiate_project":
            return {
                "decision_score": context.get("owner_decision_score", 0.75),
                "initiation_probability": context.get("initiation_probability", 0.75),
            }
        if action_type == "submit_bid":
            assessment = context.get("bid_assessment") or {}
            data = dict(assessment)
            data.setdefault("bid_probability", 0.78)
            data.setdefault("expected_profit", 0.12)
            data.setdefault("risk_level", 0.28)
            return data
        return {}


def _minimal_decision_prompt(agent: Any, project: Any, stage_rule: Any, context: dict) -> str:
    stage_allowed = []
    if stage_rule:
        stage_allowed = stage_rule.allowed_actions.get(agent.role, [])
    payload = {
        "agent": {"agent_id": agent.agent_id, "role": agent.role, "region": agent.region},
        "project": {
            "project_id": getattr(project, "project_id", None),
            "stage": getattr(getattr(project, "current_stage", None), "value", None),
        },
        "stage_rule": {"allowed_actions_for_role": stage_allowed},
        "owner_decision_score": context.get("owner_decision_score"),
        "initiation_probability": context.get("initiation_probability"),
        "bid_assessment": context.get("bid_assessment"),
    }
    return "Decision context:\n" + json.dumps(payload, ensure_ascii=False)


@pytest.fixture(autouse=True)
def deterministic_camel_decisions_for_engine_tests(request, monkeypatch):
    if request.node.fspath.basename == "test_camel_decision_provider.py":
        return

    from gba_construction_sim.backend.decision import camel_provider

    CamelDecisionProvider = camel_provider.CamelDecisionProvider

    original_init = CamelDecisionProvider.__init__

    def patched_init(self, camel_agent=None, fallback=None, model=None, auto_create_agent=None, strict=None):
        if camel_agent is None and model is None:
            camel_agent = _DeterministicCamelAgent()
            auto_create_agent = False
        original_init(
            self,
            camel_agent=camel_agent,
            fallback=fallback,
            model=model,
            auto_create_agent=auto_create_agent,
            strict=strict,
        )

    monkeypatch.setattr(CamelDecisionProvider, "__init__", patched_init)
    monkeypatch.setattr(camel_provider, "build_decision_prompt", _minimal_decision_prompt)
