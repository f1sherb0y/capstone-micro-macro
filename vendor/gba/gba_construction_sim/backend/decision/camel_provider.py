from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, Optional

from gba_construction_sim.backend.decision.decision_provider import DecisionProvider
from gba_construction_sim.backend.decision.output_parser import DecisionOutputParser
from gba_construction_sim.backend.decision.prompts import build_decision_prompt, build_system_message
from gba_construction_sim.backend.decision.rule_based_provider import RuleBasedDecisionProvider
from gba_construction_sim.backend.models.action import AgentAction, find_forbidden_action_mutation_keys
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.rag.enterprise_retriever import enterprise_retriever
from gba_construction_sim.backend.services.agent_cognitive_service import agent_cognitive_service


class CamelDecisionError(RuntimeError):
    """Raised when CAMEL produces an invalid or unusable enterprise decision."""


class CamelDecisionUnavailable(CamelDecisionError):
    """Raised when camel-ai, model configuration, or credentials are unavailable."""


class _ExternalCamelModelType:
    """Adapter for provider model names not present in this camel-ai version."""

    def __init__(
        self,
        value: str,
        token_limit: int = 8192,
        *,
        is_openai: bool = False,
        is_zhipuai: bool = True,
    ) -> None:
        self.value = value
        self.value_for_tiktoken = "gpt-4o-mini"
        self.token_limit = token_limit
        self.is_anthropic = False
        self.is_azure_openai = False
        self.is_gemini = False
        self.is_groq = False
        self.is_mistral = False
        self.is_nvidia = False
        self.is_open_source = False
        self.is_openai = is_openai
        self.is_samba = False
        self.is_zhipuai = is_zhipuai

    def __str__(self) -> str:
        return self.value


class _LocalApproxTokenCounter:
    """Offline token counter used when camel-ai would otherwise download tiktoken data."""

    def count_tokens_from_messages(self, messages: list[dict]) -> int:
        total = 0
        for message in messages or []:
            if isinstance(message, dict):
                content = message.get("content", "")
                role = message.get("role", "")
            else:
                content = getattr(message, "content", "")
                role = getattr(message, "role", "")
            total += max(1, len(str(content)) // 4) + len(str(role)) + 4
        return total


class CamelDecisionProvider(DecisionProvider):
    def __init__(
        self,
        camel_agent: Optional[object] = None,
        fallback: Optional[DecisionProvider] = None,
        model: Optional[object] = None,
        auto_create_agent: Optional[bool] = None,
        strict: Optional[bool] = None,
    ) -> None:
        self.camel_agent = camel_agent
        allow_rule_fallback = os.getenv("CAMEL_DECISION_ALLOW_RULE_FALLBACK", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.fallback = fallback or (RuleBasedDecisionProvider() if allow_rule_fallback else None)
        self.model = model
        self.auto_create_agent = (
            auto_create_agent
            if auto_create_agent is not None
            else os.getenv("CAMEL_DECISION_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
        )
        if strict is not None:
            self.strict = strict
        else:
            self.strict = os.getenv("CAMEL_DECISION_STRICT", "true").lower() not in {"0", "false", "no", "off"}
        self.parser = DecisionOutputParser()
        self.last_error: Optional[str] = None

    def decide(self, agent: EnterpriseAgentProfile, context: Dict) -> AgentAction:
        project = context.get("project")
        stage_rule = context.get("stage_rule")
        allowed_actions = list(
            context.get("allowed_actions")
            or (stage_rule.allowed_actions.get(agent.role, []) if stage_rule else [])
        )
        if not stage_rule or not allowed_actions:
            reason = "CAMEL decision requires a stage_rule and a non-empty bounded action set"
            return self._fallback_or_raise(
                agent,
                context,
                CamelDecisionError(reason),
                camel_used=False,
                fallback_reason=reason,
            )

        enriched_context = context
        try:
            # Keep CAMEL decisions stateless. The simulation already persists
            # enterprise memory/belief explicitly; reusing one ChatAgent would
            # mix hidden chat history across agents and make each tick slower.
            camel_agent = self.camel_agent or self._ensure_camel_agent()
            if not camel_agent:
                reason = self.last_error or "CAMEL agent is unavailable"
                raise CamelDecisionUnavailable(reason)

            enriched_context = self._enrich_context(agent, context)
            prompt = build_decision_prompt(agent, project, stage_rule, enriched_context)
            response, retry_info = self._step(camel_agent, prompt)
            action = self.parser.parse(self._extract_response_payload(response))
            guarded_action = self._guard_action(action, agent, enriched_context)
            self._record_trace(
                agent,
                enriched_context,
                guarded_action,
                True,
                False,
                "valid",
                retry_info=retry_info,
                model_info=self._model_info(camel_agent),
            )
            context["trace_recorded_by_provider"] = True
            enriched_context["trace_recorded_by_provider"] = True
            return guarded_action
        except CamelDecisionUnavailable as exc:
            self.last_error = str(exc)
            return self._fallback_or_raise(agent, context, exc, camel_used=False)
        except Exception as exc:
            self.last_error = str(exc)
            action = exc.args[1] if len(getattr(exc, "args", ())) > 1 and isinstance(exc.args[1], AgentAction) else None
            return self._fallback_or_raise(agent, enriched_context, exc, camel_used=True, action=action)

    async def decide_async(self, agent: EnterpriseAgentProfile, context: Dict) -> AgentAction:
        return await asyncio.to_thread(self.decide, agent, context)

    def _ensure_camel_agent(self) -> object:
        if not self.auto_create_agent:
            raise CamelDecisionUnavailable("CAMEL auto-create is disabled and no camel_agent was provided")
        try:
            from camel.agents import ChatAgent

            kwargs: Dict[str, Any] = {"system_message": self._camel_system_message()}
            model = self.model or self._model_from_environment()
            if model:
                kwargs["model"] = model
            kwargs["token_limit"] = int(
                os.getenv(
                    "CAMEL_DECISION_CONTEXT_TOKEN_LIMIT",
                    str(getattr(getattr(model, "model_type", None), "token_limit", 8192) if model else 8192),
                )
            )
            tools = self._read_only_tools()
            if tools:
                kwargs["tools"] = tools
            return ChatAgent(**kwargs)
        except Exception as exc:
            self.last_error = str(exc)
            raise CamelDecisionUnavailable(f"Unable to create CAMEL ChatAgent: {exc}") from exc

    @staticmethod
    def _model_from_environment() -> object:
        try:
            from camel.models import ModelFactory
            from camel.types import ModelPlatformType, ModelType
        except Exception as exc:
            raise CamelDecisionUnavailable(f"camel-ai model modules are unavailable: {exc}") from exc

        model_spec = (os.getenv("CAMEL_DECISION_MODEL") or os.getenv("CAMEL_MODEL") or "GPT_4O_MINI").strip()
        configured_platform = os.getenv("CAMEL_MODEL_PLATFORM")
        platform_spec = (configured_platform or "OPENAI").strip()
        if ":" in model_spec:
            platform_spec, model_spec = [part.strip() for part in model_spec.split(":", 1)]
        elif not configured_platform and model_spec.lower().startswith("glm"):
            platform_spec = "ZHIPU"

        platform_key = platform_spec.upper().replace("-", "_")
        model_url = os.getenv("CAMEL_MODEL_URL") or None
        is_openai_compatible_custom = (
            platform_key == "OPENAI"
            and isinstance(model_spec, str)
            and (
                model_spec.lower().startswith("deepseek")
                or (model_url is not None and "deepseek" in model_url.lower())
            )
        )
        if is_openai_compatible_custom and not model_url:
            model_url = "https://api.deepseek.com"
        model_key = model_spec.upper().replace("-", "_").replace(".", "_")
        platform = getattr(ModelPlatformType, platform_key, platform_spec)
        model_type = getattr(ModelType, model_key, model_spec)

        api_key = os.getenv("CAMEL_API_KEY")
        if platform_key == "OPENAI":
            if is_openai_compatible_custom:
                api_key = api_key or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
            else:
                api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                raise CamelDecisionUnavailable(
                    "OPENAI_API_KEY, DEEPSEEK_API_KEY, or CAMEL_API_KEY is required for CAMEL OPENAI decisions"
                )
        elif platform_key == "ZHIPU":
            api_key = api_key or os.getenv("ZHIPUAI_API_KEY") or os.getenv("ZHIPU_API_KEY") or os.getenv("BIGMODEL_API_KEY")
            if not api_key:
                raise CamelDecisionUnavailable(
                    "ZHIPUAI_API_KEY, ZHIPU_API_KEY, BIGMODEL_API_KEY, or CAMEL_API_KEY is required for CAMEL ZHIPU decisions"
                )

        model_config: Dict[str, Any] = {}
        temperature = os.getenv("CAMEL_DECISION_TEMPERATURE")
        if temperature:
            model_config["temperature"] = float(temperature)
        max_tokens = os.getenv("CAMEL_DECISION_MAX_TOKENS")
        if max_tokens:
            model_config["max_tokens"] = int(max_tokens)
        elif platform_key == "ZHIPU":
            model_config["max_tokens"] = 512
        top_p = os.getenv("CAMEL_DECISION_TOP_P")
        if top_p:
            model_config["top_p"] = float(top_p)
        zhipu_extra_body: Dict[str, Any] | None = None
        zhipu_thinking = os.getenv("CAMEL_ZHIPU_THINKING")
        if platform_key == "ZHIPU" and (zhipu_thinking or "4.7" in model_spec.lower()):
            thinking_type = (zhipu_thinking or "disabled").strip().lower()
            if thinking_type not in {"", "default", "auto"}:
                zhipu_extra_body = {"thinking": {"type": thinking_type}}
        if platform_key == "ZHIPU" and isinstance(model_type, str):
            try:
                from camel.models.zhipuai_model import ZhipuAIModel
            except Exception as exc:
                raise CamelDecisionUnavailable(f"camel-ai ZhipuAIModel is unavailable: {exc}") from exc
            zhipu_url = os.getenv("CAMEL_MODEL_URL") or os.getenv("ZHIPUAI_API_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4/"
            external_model_type = _ExternalCamelModelType(
                model_spec,
                token_limit=getattr(getattr(ModelType, "GLM_4", None), "token_limit", 8192),
            )
            model = ZhipuAIModel(
                model_type=external_model_type,
                model_config_dict=model_config,
                api_key=api_key,
                url=zhipu_url,
                token_counter=_LocalApproxTokenCounter(),
            )
            timeout = float(os.getenv("CAMEL_DECISION_TIMEOUT_SECONDS", os.getenv("MODEL_TIMEOUT", "180")))
            max_retries = int(os.getenv("CAMEL_DECISION_MODEL_MAX_RETRIES", "1"))
            try:
                from openai import OpenAI

                model._client = OpenAI(
                    timeout=timeout,
                    max_retries=max_retries,
                    api_key=api_key,
                    base_url=zhipu_url,
                )
            except Exception:
                # Older camel-ai versions hard-code the OpenAI-compatible
                # client. If patching fails, keep the model usable and let
                # the decision path surface the real CAMEL error.
                pass
            if zhipu_extra_body:
                from types import MethodType

                def run_with_extra_body(self, messages):
                    return self._client.chat.completions.create(
                        messages=messages,
                        model=self.model_type.value,
                        extra_body=zhipu_extra_body,
                        **self.model_config_dict,
                    )

                model.run = MethodType(run_with_extra_body, model)
            return model
        if is_openai_compatible_custom:
            try:
                from camel.models.openai_compatibility_model import OpenAICompatibilityModel
            except Exception as exc:
                raise CamelDecisionUnavailable(f"camel-ai OpenAICompatibilityModel is unavailable: {exc}") from exc
            model = OpenAICompatibilityModel(
                model_type=model_spec,
                model_config_dict=model_config,
                api_key=api_key,
                url=model_url or "https://api.deepseek.com",
                token_counter=_LocalApproxTokenCounter(),
            )
            model.model_type = _ExternalCamelModelType(
                model_spec,
                token_limit=getattr(getattr(ModelType, "GPT_4O_MINI", None), "token_limit", 128000),
                is_openai=False,
                is_zhipuai=False,
            )
            timeout = float(os.getenv("CAMEL_DECISION_TIMEOUT_SECONDS", os.getenv("MODEL_TIMEOUT", "180")))
            max_retries = int(os.getenv("CAMEL_DECISION_MODEL_MAX_RETRIES", "1"))
            try:
                from openai import OpenAI

                model._client = OpenAI(
                    timeout=timeout,
                    max_retries=max_retries,
                    api_key=api_key,
                    base_url=model_url or "https://api.deepseek.com",
                )
            except Exception:
                pass
            from types import MethodType

            def run_with_external_model_type(self, messages):
                return self._client.chat.completions.create(
                    messages=messages,
                    model=self.model_type.value,
                    **self.model_config_dict,
                )

            model.run = MethodType(run_with_external_model_type, model)
            return model
        return ModelFactory.create(
            model_platform=platform,
            model_type=model_type,
            model_config_dict=model_config,
            api_key=api_key,
            url=model_url,
        )

    def _camel_system_message(self) -> object:
        content = build_system_message()
        try:
            from camel.messages import BaseMessage

            return BaseMessage.make_assistant_message(
                role_name="GBA construction simulation rule-bounded decision advisor",
                content=content,
            )
        except Exception as exc:
            raise CamelDecisionUnavailable(f"Unable to create CAMEL BaseMessage: {exc}") from exc

    def _step(self, camel_agent: object, prompt: str) -> tuple[object, dict[str, Any]]:
        try:
            from camel.messages import BaseMessage

            input_message = BaseMessage.make_user_message(
                role_name="enterprise_decision_request",
                content=prompt,
            )
        except Exception as exc:
            raise CamelDecisionUnavailable(f"Unable to create CAMEL input message: {exc}") from exc
        if self._supports_output_schema_tool(camel_agent):
            call_prompt = prompt
            output_schema = AgentAction
        else:
            call_prompt = (
                f"{prompt}\n\n"
                "Return exactly one raw JSON object and no markdown fences. "
                "The object must match the AgentAction schema."
            )
            input_message = BaseMessage.make_user_message(
                role_name="enterprise_decision_request",
                content=call_prompt,
            )
            output_schema = None

        max_retries = int(os.getenv("CAMEL_DECISION_MAX_RETRIES", "2"))
        retry_delay = float(os.getenv("CAMEL_DECISION_RETRY_DELAY_SECONDS", "1.0"))
        last_exc: Exception | None = None
        retry_errors: list[str] = []
        for attempt in range(max_retries + 1):
            try:
                if output_schema:
                    response = camel_agent.step(input_message, output_schema=output_schema)
                else:
                    response = camel_agent.step(input_message)
                return response, {
                    "attempts": attempt + 1,
                    "max_retries": max_retries,
                    "errors": retry_errors,
                }
            except Exception as exc:
                last_exc = exc
                message = str(exc).lower()
                retry_errors.append(str(exc))
                transient = "429" in message or "rate limit" in message or "访问量过大" in message
                if not transient or attempt >= max_retries:
                    raise
                time.sleep(retry_delay * (attempt + 1))
        raise last_exc or CamelDecisionError("CAMEL decision failed without an exception")

    @staticmethod
    def _supports_output_schema_tool(camel_agent: object) -> bool:
        model_type = getattr(camel_agent, "model_type", None)
        if model_type is None:
            model_backend = getattr(camel_agent, "model_backend", None)
            model_type = getattr(model_backend, "model_type", None)
        if model_type is None:
            return True
        if isinstance(model_type, str):
            return False
        if getattr(model_type, "is_zhipuai", False):
            return False
        if isinstance(model_type, _ExternalCamelModelType):
            return False
        return bool(getattr(model_type, "is_openai", True) or getattr(model_type, "is_gemini", False))

    def _extract_response_payload(self, response: object) -> object:
        candidates = []
        msgs = getattr(response, "msgs", None)
        if msgs:
            candidates.extend(msgs)
        msg = getattr(response, "msg", None)
        if msg:
            candidates.append(msg)
        candidates.append(response)

        for candidate in candidates:
            parsed = getattr(candidate, "parsed", None)
            if parsed is not None:
                return parsed
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if content is not None:
                return content
        for candidate in candidates:
            reasoning_content = getattr(candidate, "reasoning_content", None)
            if reasoning_content:
                return reasoning_content
        for candidate in candidates:
            payload = self._extract_payload_from_mapping(candidate)
            if payload is not None:
                return payload
        return response

    def _extract_payload_from_mapping(self, candidate: object) -> object | None:
        if isinstance(candidate, dict):
            for key in ["parsed", "content", "reasoning_content"]:
                value = candidate.get(key)
                if value:
                    return value
            for key in ["message", "delta"]:
                if key in candidate and candidate.get(key):
                    value = self._extract_payload_from_mapping(candidate[key])
                    if value is not None:
                        return value
            choices = candidate.get("choices")
            if isinstance(choices, list):
                for choice in choices:
                    value = self._extract_payload_from_mapping(choice)
                    if value is not None:
                        return value
        info = getattr(candidate, "info", None)
        if isinstance(info, dict):
            return self._extract_payload_from_mapping(info)
        return None

    def _guard_action(self, action: AgentAction, agent: EnterpriseAgentProfile, context: Dict) -> AgentAction:
        project = context.get("project")
        stage_rule = context.get("stage_rule")
        allowed_actions = list(
            context.get("allowed_actions")
            or (stage_rule.allowed_actions.get(agent.role, []) if stage_rule else [])
        )
        if action.agent_id != agent.agent_id:
            raise ValueError("CAMEL output agent_id does not match the requesting agent")
        if project and action.project_id != project.project_id:
            raise ValueError("CAMEL output project_id does not match the current project")
        if allowed_actions and action.action_type not in allowed_actions:
            raise ValueError("CAMEL output action is outside allowed stage actions", action)
        forbidden_keys = find_forbidden_action_mutation_keys(action.data)
        if forbidden_keys:
            raise ValueError(f"CAMEL output attempts to mutate simulation state: {sorted(forbidden_keys)}", action)
        return action

    def _enrich_context(self, agent: EnterpriseAgentProfile, context: Dict) -> Dict:
        enriched = dict(context)
        if "cognitive_context" not in enriched:
            try:
                enriched["cognitive_context"] = agent_cognitive_service.build_agent_decision_context(
                    agent,
                    enriched.get("project"),
                    enriched,
                )
            except Exception as exc:
                enriched["cognitive_context_error"] = str(exc)
                enriched["cognitive_context"] = {}
        if "rag_context" not in enriched:
            try:
                query = " ".join(
                    str(part)
                    for part in [
                        agent.role,
                        agent.region,
                        getattr(getattr(enriched.get("project"), "current_stage", None), "value", ""),
                        enriched.get("cognitive_context", {}).get("strategy_summary", {}).get("primary_strategy", ""),
                    ]
                    if part
                )
                enriched["rag_context"] = enterprise_retriever.search(query, limit=3)
            except Exception as exc:
                enriched["rag_context_error"] = str(exc)
                enriched["rag_context"] = []
        return enriched

    def _record_trace(
        self,
        agent: EnterpriseAgentProfile,
        context: Dict,
        action: AgentAction,
        camel_used: bool,
        fallback_used: bool,
        validation_reason: str,
        retry_info: dict[str, Any] | None = None,
        model_info: dict[str, Any] | None = None,
    ) -> None:
        try:
            agent_cognitive_service.record_decision_trace(
                agent,
                context,
                action,
                camel_used=camel_used,
                fallback_used=fallback_used,
                validation_result={
                    "valid": validation_reason == "valid" or fallback_used,
                    "reason": validation_reason,
                },
                explanation=action.reason,
                retry_info=retry_info,
                model_info=model_info,
                error_info=None if validation_reason == "valid" else {"message": validation_reason},
            )
            if camel_used and not fallback_used and validation_reason == "valid":
                agent_cognitive_service.record_agent_decision_memory(agent, context, action)
        except Exception as exc:
            self.last_error = f"{self.last_error or ''}; trace failed: {exc}".strip("; ")

    def _fallback_or_raise(
        self,
        agent: EnterpriseAgentProfile,
        context: Dict,
        exc: Exception,
        *,
        camel_used: bool,
        action: AgentAction | None = None,
        fallback_reason: str | None = None,
    ) -> AgentAction:
        reason = fallback_reason or str(exc)
        self.last_error = reason
        if self.strict or not self.fallback:
            self._record_rejection_trace(agent, context, reason, camel_used=camel_used, action=action)
            if isinstance(exc, CamelDecisionError):
                raise exc
            raise CamelDecisionError(reason) from exc

        fallback_action = self.fallback.decide(agent, context)
        suffix = "CAMEL unavailable" if not camel_used else "CAMEL rejected"
        fallback_action.reason = f"{fallback_action.reason}; {suffix}: {reason}"
        self._record_trace(agent, context, fallback_action, camel_used, True, reason)
        return fallback_action

    def _record_rejection_trace(
        self,
        agent: EnterpriseAgentProfile,
        context: Dict,
        reason: str,
        *,
        camel_used: bool,
        action: AgentAction | None = None,
    ) -> None:
        try:
            agent_cognitive_service.record_decision_trace(
                agent,
                context,
                action,
                camel_used=camel_used,
                fallback_used=False,
                validation_result={"valid": False, "reason": reason},
                explanation=reason,
                retry_info={"attempts": 0, "errors": [reason]},
                model_info=self._model_info(self.camel_agent) if self.camel_agent else None,
                error_info={"message": reason},
            )
        except Exception as exc:
            self.last_error = f"{self.last_error or reason}; trace failed: {exc}".strip("; ")

    @staticmethod
    def _model_info(camel_agent: object | None) -> dict[str, Any]:
        if not camel_agent:
            return {
                "provider": os.getenv("CAMEL_MODEL_PLATFORM") or os.getenv("CAMEL_DECISION_MODEL", "unknown"),
                "model": os.getenv("CAMEL_DECISION_MODEL") or os.getenv("CAMEL_MODEL") or "unknown",
            }
        model_backend = getattr(camel_agent, "model_backend", None)
        model_type = getattr(camel_agent, "model_type", None) or getattr(model_backend, "model_type", None)
        platform = getattr(model_backend, "model_platform", None) or getattr(model_backend, "model_platform_type", None)
        return {
            "provider": str(platform or os.getenv("CAMEL_MODEL_PLATFORM") or "camel-ai"),
            "model": str(getattr(model_type, "value", model_type) or os.getenv("CAMEL_DECISION_MODEL") or "unknown"),
            "agent_class": camel_agent.__class__.__name__,
        }

    def _read_only_tools(self) -> list[object]:
        try:
            from camel.toolkits import OpenAIFunction
        except Exception as exc:
            raise CamelDecisionUnavailable(f"CAMEL tool calling is unavailable: {exc}") from exc

        def get_agent_profile(agent_id: str) -> Dict[str, Any]:
            """Return a read-only summarized enterprise profile for one agent."""
            return agent_cognitive_service.get_agent_cognitive_state(agent_id).get("profile_summary", {})

        def retrieve_agent_memory(agent_id: str, limit: int = 5) -> list[Dict[str, Any]]:
            """Return recent read-only enterprise memories for one agent."""
            return agent_cognitive_service.get_agent_memory(agent_id, limit=limit)

        def get_agent_belief(agent_id: str) -> list[Dict[str, Any]]:
            """Return read-only belief records for one agent."""
            return agent_cognitive_service.get_agent_beliefs(agent_id)

        def get_agent_strategy(agent_id: str) -> Dict[str, Any]:
            """Return read-only strategy parameters for one agent."""
            return agent_cognitive_service.get_agent_strategy(agent_id) or {}

        def calculate_bid_utility(expected_profit: float, risk_level: float, resource_fit: float) -> float:
            """Calculate a bounded bid utility score from profit, risk, and resource fit."""
            return max(0.0, min(1.0, 0.45 * expected_profit + 0.35 * resource_fit + 0.20 * (1.0 - risk_level)))

        def estimate_cashflow_pressure(agent_id: str) -> float:
            """Estimate cashflow pressure from the agent cash-preservation strategy."""
            strategy = agent_cognitive_service.get_agent_strategy(agent_id) or {}
            return float(strategy.get("cash_preservation_level") or 0.5)

        def get_partner_trust(agent_id: str, partner_id: str) -> float:
            """Return a bounded trust estimate toward a potential partner."""
            beliefs = agent_cognitive_service.get_agent_beliefs(agent_id)
            trust = next((item for item in beliefs if item.get("belief_type") == "partner_trust_belief"), None)
            return float((trust or {}).get("belief_value") or 0.5)

        def check_stage_allowed_actions(role: str, allowed_actions: list[str]) -> list[str]:
            """Echo the stage allowed actions for guardrail-aware decision making."""
            return list(allowed_actions or [])

        def schema(name: str, description: str, properties: Dict[str, Any], required: list[str]) -> Dict[str, Any]:
            return {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }

        agent_id_property = {
            "type": "string",
            "description": "Enterprise agent identifier to read from the local cognitive state store.",
        }
        return [
            OpenAIFunction(
                get_agent_profile,
                schema(
                    "get_agent_profile",
                    "Return a read-only summarized enterprise profile for one agent.",
                    {"agent_id": agent_id_property},
                    ["agent_id"],
                ),
            ),
            OpenAIFunction(
                retrieve_agent_memory,
                schema(
                    "retrieve_agent_memory",
                    "Return recent read-only enterprise memories for one agent.",
                    {
                        "agent_id": agent_id_property,
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of memory records to return.",
                        },
                    },
                    ["agent_id"],
                ),
            ),
            OpenAIFunction(
                get_agent_belief,
                schema(
                    "get_agent_belief",
                    "Return read-only belief records for one agent.",
                    {"agent_id": agent_id_property},
                    ["agent_id"],
                ),
            ),
            OpenAIFunction(
                get_agent_strategy,
                schema(
                    "get_agent_strategy",
                    "Return read-only strategy parameters for one agent.",
                    {"agent_id": agent_id_property},
                    ["agent_id"],
                ),
            ),
            OpenAIFunction(
                calculate_bid_utility,
                schema(
                    "calculate_bid_utility",
                    "Calculate a bounded bid utility score from profit, risk, and resource fit.",
                    {
                        "expected_profit": {
                            "type": "number",
                            "description": "Expected contractor profit ratio for the bid.",
                        },
                        "risk_level": {
                            "type": "number",
                            "description": "Estimated project or tender risk level from 0 to 1.",
                        },
                        "resource_fit": {
                            "type": "number",
                            "description": "Available enterprise resource fit from 0 to 1.",
                        },
                    },
                    ["expected_profit", "risk_level", "resource_fit"],
                ),
            ),
            OpenAIFunction(
                estimate_cashflow_pressure,
                schema(
                    "estimate_cashflow_pressure",
                    "Estimate cashflow pressure from the agent cash-preservation strategy.",
                    {"agent_id": agent_id_property},
                    ["agent_id"],
                ),
            ),
            OpenAIFunction(
                get_partner_trust,
                schema(
                    "get_partner_trust",
                    "Return a bounded trust estimate toward a potential partner.",
                    {
                        "agent_id": agent_id_property,
                        "partner_id": {
                            "type": "string",
                            "description": "Potential partner enterprise agent identifier.",
                        },
                    },
                    ["agent_id", "partner_id"],
                ),
            ),
            OpenAIFunction(
                check_stage_allowed_actions,
                schema(
                    "check_stage_allowed_actions",
                    "Echo the stage allowed actions for guardrail-aware decision making.",
                    {
                        "role": {
                            "type": "string",
                            "description": "Enterprise role currently making the decision.",
                        },
                        "allowed_actions": {
                            "type": "array",
                            "description": "Action types allowed by the hard stage rule for this role.",
                            "items": {"type": "string"},
                        },
                    },
                    ["role", "allowed_actions"],
                ),
            ),
        ]
