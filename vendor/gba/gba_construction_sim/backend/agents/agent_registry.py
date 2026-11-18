from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, Iterable, Type

from gba_construction_sim.backend.agents.architect_agent import ArchitectAgent
from gba_construction_sim.backend.agents.bank_agent import BankAgent
from gba_construction_sim.backend.agents.base_agent import AgentDecision, BaseEnterpriseAgent
from gba_construction_sim.backend.agents.contractor_agent import ContractorAgent
from gba_construction_sim.backend.agents.engineer_agent import EngineerAgent
from gba_construction_sim.backend.agents.government_agent import GovernmentAgent
from gba_construction_sim.backend.agents.owner_agent import OwnerAgent
from gba_construction_sim.backend.agents.qs_agent import QSAgent
from gba_construction_sim.backend.agents.supplier_agent import SupplierAgent
from gba_construction_sim.backend.agents.contracts import (
    AgentOperationContractV1,
    AgentModuleCapabilitiesV1,
    AgentModuleHealthV1,
)
from gba_construction_sim.backend.agents.operation_specs import (
    get_operation_contract as lookup_operation_contract,
    list_operation_contracts,
)
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.stage_rule import StageRule
from gba_construction_sim.backend.core.enums import ProjectStage
from gba_construction_sim.backend.simulation.decision_request import DecisionPriority
from gba_construction_sim.backend.simulation.decision_request_collector import DecisionRequestCollector
from gba_construction_sim.backend.simulation.enterprise_decision_scheduler import EnterpriseDecisionScheduler


ROLE_AGENT_TYPES: Dict[str, Type[BaseEnterpriseAgent]] = {
    "Owner": OwnerAgent,
    "Architect": ArchitectAgent,
    "Engineer": EngineerAgent,
    "QS": QSAgent,
    "Contractor": ContractorAgent,
    "Supplier": SupplierAgent,
    "Government": GovernmentAgent,
    "Bank": BankAgent,
}


class AgentBehaviorRegistry:
    """Persistent one-to-one mapping from agent profiles to decision processes."""

    def __init__(
        self,
        profiles: Iterable[EnterpriseAgentProfile] = (),
        random_seed: int | None = None,
        decision_scheduler: EnterpriseDecisionScheduler | None = None,
    ) -> None:
        self.random_seed = int(random_seed or 0)
        self.decision_scheduler = decision_scheduler
        self.decision_collector = DecisionRequestCollector()
        self._agents: Dict[str, BaseEnterpriseAgent] = {}
        for profile in profiles:
            self.for_profile(profile)

    def register_profiles(self, profiles: Iterable[EnterpriseAgentProfile]) -> None:
        """Register profiles without exposing lifecycle internals to the agent module."""

        for profile in profiles:
            self.for_profile(profile)

    def for_profile(self, profile: EnterpriseAgentProfile) -> BaseEnterpriseAgent:
        self._ensure_agent_background(profile)
        existing = self._agents.get(profile.agent_id)
        if existing is not None:
            existing.profile = profile
            return existing
        agent_type = ROLE_AGENT_TYPES.get(profile.role, BaseEnterpriseAgent)
        agent = agent_type(profile, random.Random(self._seed_for(profile.agent_id)))
        self._agents[profile.agent_id] = agent
        return agent

    def get(self, agent_id: str) -> BaseEnterpriseAgent | None:
        return self._agents.get(agent_id)

    def propose(
        self,
        profile: EnterpriseAgentProfile,
        operation: str,
        **inputs: Any,
    ) -> AgentDecision:
        """Run one role-specific professional reasoning operation.

        Simulation code calls this stable operation boundary instead of a
        concrete OwnerAgent/ContractorAgent class. An external agent module can
        therefore replace proposal generation without changing lifecycle code.
        """

        behavior = self.for_profile(profile)
        method = getattr(behavior, operation, None)
        if not callable(method):
            raise ValueError(
                f"Agent role {profile.role!r} does not implement proposal operation {operation!r}."
            )
        decision = method(**inputs)
        if not isinstance(decision, AgentDecision):
            raise TypeError(
                f"Proposal operation {operation!r} must return AgentDecision, got {type(decision).__name__}."
            )
        return decision

    def proposal_process_name(
        self,
        profile: EnterpriseAgentProfile,
        operation: str,
    ) -> str:
        return f"{self.for_profile(profile).__class__.__name__}.{operation}"

    def get_operation_contract(
        self,
        operation: str,
        role: str,
    ) -> AgentOperationContractV1:
        return lookup_operation_contract(operation, role)

    def attach_decision_scheduler(self, decision_scheduler: EnterpriseDecisionScheduler) -> None:
        """Attach the shared model gateway without sharing agent identity or memory."""

        self.decision_scheduler = decision_scheduler

    def observe_event(self, event: Any, project: Any | None = None) -> None:
        """Default module already learns through AgentCognitiveService.

        External adapters override this method to receive committed events.
        """

    def capabilities(self) -> AgentModuleCapabilitiesV1:
        contracts = list_operation_contracts()
        operations = sorted({contract.operation for contract in contracts})
        return AgentModuleCapabilitiesV1(
            module_name=self.__class__.__name__,
            module_version="builtin-v1",
            roles=sorted(ROLE_AGENT_TYPES),
            proposal_operations=operations,
            operation_contracts=contracts,
            supports_batch_decisions=True,
        )

    def health(self) -> AgentModuleHealthV1:
        return AgentModuleHealthV1(
            status="ready",
            module_name=self.__class__.__name__,
            message="Built-in agent module is available.",
            details={
                "registered_agents": len(self._agents),
                "decision_scheduler_attached": self.decision_scheduler is not None,
            },
        )

    def resolve_decision(
        self,
        profile: EnterpriseAgentProfile,
        proposal: AgentDecision,
        *,
        decision_type: str,
        tick: int,
        project: Any | None = None,
        stage_rule: StageRule | None = None,
        policy: Any | None = None,
        macro_environment: Any | None = None,
        engagement: Any | None = None,
        recent_messages: list[dict[str, Any]] | None = None,
        priority: DecisionPriority = DecisionPriority.P1_RESOURCE_CASHFLOW,
        decision_task: str | None = None,
        choice_options: list[dict[str, Any]] | None = None,
        choice_field: str | None = None,
        choice_multiple: bool = False,
        choice_limit: int | None = None,
        allowed_actions: list[str] | None = None,
        negative_actions: set[str] | None = None,
    ) -> AgentDecision:
        """Let this subject's LLM make the final bounded choice.

        Role methods calculate auditable evidence such as cost, capacity, risk,
        and ranked options. Those calculations are decision support only. The
        model chooses whether to act and, when supplied, which valid option to
        select. The simulation engine remains responsible for validation and
        state mutation.
        """

        if self.decision_scheduler is None:
            return proposal

        bounded_actions = list(dict.fromkeys(allowed_actions or [proposal.action_type]))
        if proposal.action_type not in bounded_actions:
            bounded_actions.append(proposal.action_type)
        bounded_rule = self._bounded_rule(profile, project, stage_rule, bounded_actions)
        task = {
            "objective": decision_task or proposal.reason,
            "decision_support_only": proposal.to_event_data(),
            "candidate_options": choice_options or [],
            "choice_output_field": choice_field,
            "choice_multiple": choice_multiple,
            "choice_limit": choice_limit,
            "instruction": (
                "Use your own identity, background, memory, beliefs, strategy, resources, and current situation. "
                "Choose the bounded action independently. Do not recalculate or invent formal cost and engineering values."
            ),
        }
        context = self.decision_collector.standard_context(
            profile,
            {
                "tick": tick,
                "project": project,
                "stage_rule": bounded_rule,
                "policy": policy,
                "macro_environment": macro_environment,
                "engagement": engagement,
                "allowed_actions": bounded_actions,
                "recent_messages": recent_messages or [],
                "decision_task": task,
                "decision_support": proposal.to_event_data(),
            },
            decision_type=decision_type,
            project=project,
            stage_rule=bounded_rule,
            allowed_actions=bounded_actions,
            recent_messages=recent_messages or [],
            risk_inputs=proposal.factors,
        )
        try:
            action = self.decision_scheduler.decide_now(
                profile,
                context,
                decision_type=decision_type,
                priority=priority,
                project_id=getattr(project, "project_id", None),
            )
        except Exception as exc:
            resolved = AgentDecision(
                action_type=proposal.action_type,
                accepted=False,
                utility=proposal.utility,
                probability=0.0,
                reason=(
                    "Decision deferred because this agent's language-model call failed; "
                    "no local rule was substituted as the final decision."
                ),
                factors={
                    **proposal.factors,
                    "decision_source": "llm_error_deferred",
                    "decision_error": str(exc),
                    "local_evidence_utility": proposal.utility,
                },
                data=dict(proposal.data),
            )
            self._remember_decision(profile, resolved, decision_type, tick, project)
            return resolved
        if action is None:
            resolved = AgentDecision(
                action_type=proposal.action_type,
                accepted=False,
                utility=proposal.utility,
                probability=0.0,
                reason="Decision deferred because no LLM decision was available within the configured model budget.",
                factors={
                    **proposal.factors,
                    "decision_source": "llm_deferred",
                    "local_evidence_utility": proposal.utility,
                },
                data=dict(proposal.data),
            )
            self._remember_decision(profile, resolved, decision_type, tick, project)
            return resolved

        if action.agent_id != profile.agent_id or action.action_type not in bounded_actions:
            resolved = AgentDecision(
                action_type=proposal.action_type,
                accepted=False,
                utility=proposal.utility,
                probability=0.0,
                reason="The LLM response was rejected because it did not match this agent or the bounded action set.",
                factors={
                    **proposal.factors,
                    "decision_source": "llm_invalid",
                    "returned_agent_id": action.agent_id,
                    "returned_action_type": action.action_type,
                    "returned_decision": action.decision,
                    "returned_reason": action.reason,
                    "returned_data": dict(action.data),
                    "allowed_actions": bounded_actions,
                },
                data=dict(proposal.data),
            )
            self._remember_decision(profile, resolved, decision_type, tick, project)
            return resolved

        accepted = bool(action.decision) and action.action_type not in (negative_actions or set())
        if (accepted and decision_type == "owner_financing_selection"
                and action.action_type == "self_finance_project"
                and (action.data.get("financing_mode") != "owner_equity"
                     or "selected_bank_id" not in action.data
                     or action.data["selected_bank_id"] is not None)):
            # Naming the equity action cannot silently retain a proposal bank.
            accepted = False
        payload = dict(proposal.data)
        choice_source = None
        if choice_field and choice_options:
            valid_choices = {
                str(option.get("id")): option
                for option in choice_options
                if option.get("id") is not None
            }
            selected_choice = action.data.get(choice_field)
            equity_choice = (
                decision_type == "owner_financing_selection" and profile.role == "Owner"
                and choice_field == "selected_bank_id" and not choice_multiple
                and action.action_type == "self_finance_project"
                and action.data.get("financing_mode") == "owner_equity"
                and "selected_bank_id" in action.data and selected_choice is None
            )
            if equity_choice:
                choice_source = "llm_agent"
            elif selected_choice is None:
                selected_choice = proposal.data.get(choice_field)
                choice_source = "bounded_evidence_default"
            else:
                choice_source = "llm_agent"
            if choice_multiple:
                selected_values = list(selected_choice or []) if isinstance(selected_choice, (list, tuple, set)) else []
                invalid_values = [value for value in selected_values if str(value) not in valid_choices]
                exceeds_limit = choice_limit is not None and len(selected_values) > choice_limit
                if accepted and (not selected_values or invalid_values or exceeds_limit):
                    accepted = False
                    selected_choice = []
                    choice_source = "invalid_llm_choice_rejected"
                else:
                    selected_choice = selected_values
            elif accepted and not equity_choice and str(selected_choice) not in valid_choices:
                accepted = False
                selected_choice = None
                choice_source = "invalid_llm_choice_rejected"
            if selected_choice is not None or equity_choice:
                payload[choice_field] = selected_choice
            else:
                payload.pop(choice_field, None)
            if accepted and decision_type == "owner_financing_selection" and choice_field == "selected_bank_id":
                # Final bounded choice supersedes proposal-derived bank terms.
                if equity_choice:
                    payload["financing_mode"] = "owner_equity"
                    payload.pop("selected_offer", None)
                    payload.pop("accepted_bank_ids", None)
                elif selected_choice is not None:
                    payload["financing_mode"] = "bank_finance"

        # Formal calculations from the role/environment remain authoritative.
        # The model may add rationale metadata but cannot overwrite them.
        for key, value in action.data.items():
            if key == choice_field:
                continue
            if key not in payload:
                payload[key] = value
        if choice_source:
            payload["choice_source"] = choice_source
        if decision_type == "owner_financing_selection" and not accepted:
            payload["selected_bank_id"] = None
            payload["financing_mode"] = "unfinanced"
            payload.pop("selected_offer", None)
            payload.pop("accepted_bank_ids", None)
        model_confidence = action.data.get("confidence")
        probability = (
            self.for_profile(profile).clamp(float(model_confidence))
            if isinstance(model_confidence, (int, float))
            else proposal.probability
        )
        resolved = AgentDecision(
            action_type=action.action_type,
            accepted=accepted,
            utility=proposal.utility,
            probability=probability,
            reason=action.reason,
            factors={
                **proposal.factors,
                "decision_source": "llm_agent",
                "decision_type": decision_type,
                "agent_identity": {
                    "agent_id": profile.agent_id,
                    "role": profile.role,
                    "region": profile.region,
                    "enterprise_type": profile.enterprise_type,
                },
                "local_evidence_utility": round(proposal.utility, 4),
                "local_evidence_probability": round(proposal.probability, 4),
                "llm_action_type": action.action_type,
                "llm_decision": action.decision,
                "llm_reason": action.reason,
            },
            data=payload,
        )
        self._remember_decision(profile, resolved, decision_type, tick, project)
        return resolved

    @staticmethod
    def _bounded_rule(
        profile: EnterpriseAgentProfile,
        project: Any | None,
        stage_rule: StageRule | None,
        allowed_actions: list[str],
    ) -> StageRule:
        stage = getattr(project, "current_stage", None) or getattr(stage_rule, "stage", None) or ProjectStage.INITIATION
        return StageRule(
            stage=stage,
            required_roles=[profile.role],
            allowed_actions={profile.role: allowed_actions},
            entry_conditions=list(getattr(stage_rule, "entry_conditions", []) or []),
            exit_conditions=list(getattr(stage_rule, "exit_conditions", []) or []),
            failure_conditions=list(getattr(stage_rule, "failure_conditions", []) or []),
            next_stage=getattr(stage_rule, "next_stage", None),
        )

    @staticmethod
    def _remember_decision(
        profile: EnterpriseAgentProfile,
        decision: AgentDecision,
        decision_type: str,
        tick: int,
        project: Any | None,
    ) -> None:
        profile.episodic_memory.append(
            {
                "tick": tick,
                "memory_type": "llm_decision",
                "decision_type": decision_type,
                "project_id": getattr(project, "project_id", None),
                "stage": getattr(getattr(project, "current_stage", None), "value", None),
                "action_type": decision.action_type,
                "accepted": decision.accepted,
                "reason": decision.reason,
                "decision_source": decision.factors.get("decision_source"),
            }
        )
        if len(profile.episodic_memory) > 200:
            del profile.episodic_memory[:-200]

    def _seed_for(self, agent_id: str) -> int:
        raw = f"{self.random_seed}:{agent_id}".encode("utf-8")
        return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")

    @staticmethod
    def _ensure_agent_background(profile: EnterpriseAgentProfile) -> None:
        mandates = {
            "Owner": "Create viable projects, secure finance, appoint teams, procure delivery, and protect investment value.",
            "Architect": "Translate the brief into an approvable design and manage design quality and change.",
            "Engineer": "Protect technical feasibility, constructability, safety, and engineering performance.",
            "QS": "Maintain cost certainty, procurement integrity, commercial control, and fair settlement.",
            "Contractor": "Win deliverable work at acceptable risk and margin, then mobilize and construct safely.",
            "Supplier": "Accept feasible orders and deliver compliant materials reliably within logistics capacity.",
            "Government": "Apply statutory requirements, review evidence, control public risk, and maintain procedural fairness.",
            "Bank": "Allocate credit to financeable projects while controlling exposure, liquidity, and default risk.",
        }
        background = profile.semantic_memory.setdefault("identity_background", {})
        background.setdefault("organization", profile.name)
        background.setdefault("role", profile.role)
        background.setdefault("home_region", profile.region)
        background.setdefault("enterprise_type", profile.enterprise_type)
        background.setdefault("mandate", mandates.get(profile.role, "Act within the enterprise role and current resource constraints."))
        background.setdefault(
            "decision_style",
            {
                "risk_preference": profile.risk_preference,
                "collaboration_preference": profile.collaboration_preference,
                "decision_speed": profile.decision_speed,
                "cross_region_experience": profile.cross_region_experience,
            },
        )
        background.setdefault("active_regions", list(profile.active_regions or [profile.region]))
