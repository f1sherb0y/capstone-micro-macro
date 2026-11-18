from __future__ import annotations

import os
import random
from typing import Dict, Optional

from gba_construction_sim.backend.agents.agent_registry import AgentBehaviorRegistry
from gba_construction_sim.backend.agents.contracts import AgentModulePort
from gba_construction_sim.backend.core.enums import EngagementStatus, ProjectStage
from gba_construction_sim.backend.decision.camel_provider import CamelDecisionProvider
from gba_construction_sim.backend.decision.decision_provider import DecisionProvider
from gba_construction_sim.backend.models.action import AgentAction
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.network.collaboration_prior import CollaborationPrior
from gba_construction_sim.backend.simulation.action_applier import ActionApplier
from gba_construction_sim.backend.simulation.action_validator import ActionValidator
from gba_construction_sim.backend.simulation.agent_pool_service import AgentPoolService
from gba_construction_sim.backend.simulation.decision_request import DecisionPriority, DecisionRequest
from gba_construction_sim.backend.simulation.decision_request_collector import DecisionRequestCollector
from gba_construction_sim.backend.simulation.engagement_manager import EngagementManager
from gba_construction_sim.backend.simulation.enterprise_decision_scheduler import EnterpriseDecisionScheduler
from gba_construction_sim.backend.simulation.event_system import EventSystem
from gba_construction_sim.backend.simulation.interaction_session import InteractionSession, InteractionSessionManager
from gba_construction_sim.backend.simulation.stage_rule_registry import StageRuleRegistry
from gba_construction_sim.backend.services.agent_cognitive_service import agent_cognitive_service


class ProjectLifecycleEngine:
    MIN_INITIATION_TICKS = 2
    MIN_TENDER_PREPARATION_TICKS = 2
    MIN_BID_EVALUATION_TICKS = 2
    MIN_COMPLETION_TICKS = 2
    MIN_FINAL_ACCOUNT_TICKS = 2

    def __init__(
        self,
        events: EventSystem,
        engagement_manager: EngagementManager,
        stage_rules: StageRuleRegistry,
        action_validator: ActionValidator,
        rng: Optional[random.Random] = None,
        max_tender_invites: int = 40,
        collaboration_prior: Optional[CollaborationPrior] = None,
        decision_provider: Optional[DecisionProvider] = None,
        agent_registry: Optional[AgentModulePort] = None,
        agent_module: Optional[AgentModulePort] = None,
    ) -> None:
        self.events = events
        self.engagement_manager = engagement_manager
        self.stage_rules = stage_rules
        self.action_validator = action_validator
        self.agent_module = agent_module or agent_registry or AgentBehaviorRegistry()
        self.agent_registry = self.agent_module
        module_provider = getattr(self.agent_module, "decision_provider", None)
        self.decision_provider = decision_provider or module_provider or CamelDecisionProvider()
        self.rng = rng or random.Random()
        self.max_tender_invites = max(1, max_tender_invites)
        self.max_tender_camel_advisors = self._default_tender_camel_advisor_limit()
        self.decision_scheduler = EnterpriseDecisionScheduler(self.decision_provider)
        self.agent_module.attach_decision_scheduler(self.decision_scheduler)
        self.decision_collector = getattr(
            self.agent_module,
            "decision_collector",
            DecisionRequestCollector(),
        )
        self.action_applier = ActionApplier()
        self.interaction_sessions = InteractionSessionManager()
        self.agent_pool = AgentPoolService(
            self.rng,
            max_tender_invites=self.max_tender_invites,
            collaboration_prior=collaboration_prior,
        )

    def _scheduler(self) -> EnterpriseDecisionScheduler:
        if self.decision_scheduler.decision_provider is not self.decision_provider:
            self.decision_scheduler = EnterpriseDecisionScheduler(self.decision_provider)
            self.agent_module.attach_decision_scheduler(self.decision_scheduler)
        return self.decision_scheduler

    def sync_decision_scheduler(self) -> EnterpriseDecisionScheduler:
        """Keep every agent entry point attached to the active model provider."""

        return self._scheduler()

    @staticmethod
    def _default_tender_camel_advisor_limit() -> int:
        configured = os.getenv("CAMEL_TENDER_ADVISOR_LIMIT")
        if configured is not None:
            return max(0, int(configured))
        platform = (os.getenv("CAMEL_MODEL_PLATFORM") or "").strip().upper().replace("-", "_")
        model = (os.getenv("CAMEL_DECISION_MODEL") or os.getenv("CAMEL_MODEL") or "").strip().lower()
        if platform == "ZHIPU" or model.startswith("glm"):
            return 1
        return 3

    def decide_now(
        self,
        agent: EnterpriseAgentProfile,
        context: dict,
        *,
        decision_type: str,
        priority: DecisionPriority,
        project_id: Optional[str] = None,
    ) -> Optional[AgentAction]:
        standard_context = self.decision_collector.standard_context(
            agent,
            context,
            decision_type=decision_type,
            project=context.get("project"),
            stage_rule=context.get("stage_rule"),
            allowed_actions=context.get("allowed_actions"),
            recent_messages=context.get("recent_messages", []),
            risk_inputs=context.get("risk_inputs"),
        )
        return self._scheduler().decide_now(
            agent,
            standard_context,
            decision_type=decision_type,
            priority=priority,
            project_id=project_id,
        )

    def decision_queue_metrics(self) -> dict:
        self._scheduler()
        return self._scheduler_metrics()

    @staticmethod
    def _scheduler_metrics() -> dict:
        from gba_construction_sim.backend.services.camel_queue_metrics_service import camel_queue_metrics_service

        return camel_queue_metrics_service.snapshot()

    def _start_interaction_session(
        self,
        project: ConstructionProject,
        tick: int,
        *,
        session_type: str,
        participants: list[str],
        event_type: str,
        description: str,
        messages: list[dict],
        metadata: Optional[dict] = None,
        agent_id: Optional[str] = None,
    ) -> InteractionSession:
        unique_participants = []
        for participant in participants:
            if participant and participant not in unique_participants:
                unique_participants.append(participant)
        session = self.interaction_sessions.get_or_create(
            project.project_id,
            session_type,
            unique_participants,
            metadata=metadata,
        )
        for message in messages:
            self.interaction_sessions.append_message(
                session,
                tick=tick,
                sender_id=message["sender_id"],
                recipient_ids=message.get("recipient_ids", []),
                topic=message.get("topic", session_type),
                content=message["content"],
                metadata=message.get("metadata"),
            )
        project.flags.setdefault("interaction_sessions", {})[session_type] = session.session_id
        event_data = session.to_event_data()
        event_data.update(metadata or {})
        event_data["session_participants"] = unique_participants
        self.events.record(
            tick,
            event_type,
            description,
            project=project,
            agent_id=agent_id or (unique_participants[0] if unique_participants else None),
            data=event_data,
        )
        return session

    def step(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        tick: int,
    ) -> None:
        if project.current_stage in {ProjectStage.CLOSED, ProjectStage.FAILED, ProjectStage.SUSPENDED}:
            return
        financing = project.flags.get("financing_decision")
        if (project.current_stage == ProjectStage.INITIATION and isinstance(financing, dict)
                and financing.get("accepted") is False):
            # Native refusal/defer is not owner-equity funding. Initial
            # scenarios without this decision remain backward compatible.
            return

        project.stage_tick += 1
        self._validate_representative_actions(project, agents, policy, macro_environment, tick)

        if project.current_stage == ProjectStage.INITIATION:
            self._handle_initiation(project, agents, policy, macro_environment, tick)
        elif project.current_stage == ProjectStage.DESIGN:
            self._handle_design(project, tick)
        elif project.current_stage == ProjectStage.APPROVAL:
            self._handle_approval(project, agents, policy, tick)
        elif project.current_stage == ProjectStage.TENDER_PREPARATION:
            self._handle_tender_preparation(project, tick)
        elif project.current_stage == ProjectStage.TENDERING:
            self._handle_tendering(project, agents, policy, macro_environment, tick)
        elif project.current_stage == ProjectStage.BID_EVALUATION:
            self._handle_bid_evaluation(project, agents, policy, macro_environment, tick)
        elif project.current_stage == ProjectStage.CONTRACT_AWARD:
            self._handle_contract_award(project, agents, tick)
        elif project.current_stage == ProjectStage.CONSTRUCTION:
            self._handle_construction(project, agents, tick)
        elif project.current_stage == ProjectStage.COMPLETION:
            self._handle_completion(project, agents, policy, tick)
        elif project.current_stage == ProjectStage.FINAL_ACCOUNT:
            self._handle_final_account(project, agents, tick)

        self.engagement_manager.normalize_agent_resources(agents)

    def _handle_initiation(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        tick: int,
    ) -> None:
        if project.stage_tick < self.MIN_INITIATION_TICKS:
            return

        owner = agents[project.owner_id]
        self._ensure_engagement(project, owner, "Owner", EngagementStatus.ACTIVE, tick, 0.25)
        financing_bank = agents.get(project.selected_bank_id or "")
        if financing_bank:
            self._ensure_engagement(
                project,
                financing_bank,
                "Bank",
                EngagementStatus.ACTIVE,
                tick,
                0.10,
            )
        architect_candidates = self._collect_appointment_decisions(
            project,
            agents,
            policy,
            macro_environment,
            tick,
            role="Architect",
            purpose="design",
            required_resource=0.4,
            participant_ids=[owner.agent_id],
        )
        architect_selection = self.agent_module.propose(
            owner,
            "select_appointment",
            candidates=architect_candidates,
            purpose="architect",
        )
        architect_selection = self._resolve_owner_appointment_selection(
            owner,
            architect_selection,
            architect_candidates,
            "architect",
            project,
            policy,
            macro_environment,
            tick,
        )
        architect = agents.get(architect_selection.data.get("selected_agent_id", ""))
        qs_candidates = self._collect_appointment_decisions(
            project,
            agents,
            policy,
            macro_environment,
            tick,
            role="QS",
            purpose="cost management",
            required_resource=0.3,
            participant_ids=[owner.agent_id, architect.agent_id] if architect else [owner.agent_id],
        )
        qs_selection = self.agent_module.propose(
            owner,
            "select_appointment",
            candidates=qs_candidates,
            purpose="qs",
        )
        qs_selection = self._resolve_owner_appointment_selection(
            owner,
            qs_selection,
            qs_candidates,
            "qs",
            project,
            policy,
            macro_environment,
            tick,
        )
        qs = agents.get(qs_selection.data.get("selected_agent_id", ""))
        if not architect or not qs:
            project.performance.delay_days += 30
            self.events.record(
                tick,
                "project_suspended",
                "No independently accepting consultant team was available",
                project=project,
                agent_id=owner.agent_id,
                data={
                    "architect_selection": architect_selection.to_event_data(),
                    "qs_selection": qs_selection.to_event_data(),
                },
            )
            project.current_stage = ProjectStage.SUSPENDED
            return

        project.selected_architect_id = architect.agent_id
        project.selected_qs_id = qs.agent_id
        engineer_candidates = self._collect_appointment_decisions(
            project,
            agents,
            policy,
            macro_environment,
            tick,
            role="Engineer",
            purpose="engineering",
            required_resource=0.25,
            participant_ids=[owner.agent_id, architect.agent_id, qs.agent_id],
        )
        engineer_selection = self.agent_module.propose(
            owner,
            "select_appointment",
            candidates=engineer_candidates,
            purpose="engineer",
        )
        engineer_selection = self._resolve_owner_appointment_selection(
            owner,
            engineer_selection,
            engineer_candidates,
            "engineer",
            project,
            policy,
            macro_environment,
            tick,
        )
        engineer = agents.get(engineer_selection.data.get("selected_agent_id", ""))
        if engineer:
            project.selected_engineer_id = engineer.agent_id
        project.performance.planned_cost = project.initial_budget
        self._ensure_engagement(project, architect, "Architect", EngagementStatus.ACTIVE, tick, 0.5, can_be_recalled=True)
        self._ensure_engagement(project, qs, "QS", EngagementStatus.ACTIVE, tick, 0.35)
        if engineer:
            self._ensure_engagement(project, engineer, "Engineer", EngagementStatus.ACTIVE, tick, 0.25, can_be_recalled=True)
        self.events.record(
            tick,
            "consultant_team_appointed",
            "Owner appointed design and cost consultants for the project",
            project=project,
            agent_id=owner.agent_id,
            data={
                "owner_id": owner.agent_id,
                "owner_name": owner.name,
                "architect_id": architect.agent_id,
                "architect_name": architect.name,
                "qs_id": qs.agent_id,
                "qs_name": qs.name,
                "engineer_id": engineer.agent_id if engineer else None,
                "engineer_name": engineer.name if engineer else None,
                "owner_selections": {
                    "architect": architect_selection.to_event_data(),
                    "qs": qs_selection.to_event_data(),
                    "engineer": engineer_selection.to_event_data(),
                },
                "selection_basis": [
                    "candidate eligibility and market visibility",
                    "consultant independent acceptance",
                    "role-specific capability and workload",
                    "regional and collaboration fit",
                    "owner selection among accepting candidates",
                ],
            },
        )
        self._transition(project, ProjectStage.DESIGN, tick, "Owner initiated project and appointed consultant team")

    def _collect_appointment_decisions(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        tick: int,
        *,
        role: str,
        purpose: str,
        required_resource: float,
        participant_ids: list[str],
    ) -> list[tuple[EnterpriseAgentProfile, object]]:
        candidates = self.agent_pool.visible_candidates(
            agents.values(),
            role,
            required_resource,
            self.engagement_manager,
            project,
            participant_ids,
            limit=12 if len(agents) > 1000 else 48,
        )
        decisions = []
        for candidate in candidates:
            prior_fit = self.agent_pool.collaboration_prior.participant_fit(
                candidate.agent_id,
                participant_ids,
                0.5,
            )
            if role in {"Architect", "QS"}:
                decision = self.agent_module.propose(
                    candidate,
                    "consider_appointment",
                    project=project,
                    policy=policy,
                    macro_environment=macro_environment,
                    required_resource=required_resource,
                    prior_fit=prior_fit,
                )
            else:
                decision = self.agent_module.propose(
                    candidate,
                    "consider_appointment",
                    project=project,
                    required_resource=required_resource,
                    prior_fit=prior_fit,
                )
            decision = self.agent_registry.resolve_decision(
                candidate,
                decision,
                decision_type=f"{role.lower()}_appointment_acceptance",
                tick=tick,
                project=project,
                stage_rule=self.stage_rules.get(project.current_stage),
                policy=policy,
                macro_environment=macro_environment,
                priority=DecisionPriority.P2_INTERACTION,
                decision_task=(
                    f"Decide independently whether {candidate.name} should accept the {purpose} appointment "
                    "given its own workload, capabilities, regional experience, memory, strategy, and current resources."
                ),
                allowed_actions={
                    "Architect": ["accept_design_appointment", "decline_design_appointment"],
                    "Engineer": ["accept_engineering_appointment", "decline_engineering_appointment"],
                    "QS": ["accept_qs_appointment", "decline_qs_appointment"],
                }[role],
                negative_actions={
                    "decline_design_appointment",
                    "decline_engineering_appointment",
                    "decline_qs_appointment",
                },
            )
            decisions.append((candidate, decision))
            self.events.record(
                tick,
                "appointment_decision",
                f"{role} {candidate.agent_id} independently decided whether to accept the {purpose} appointment",
                project=project,
                agent_id=candidate.agent_id,
                data={
                    "role": role,
                    "purpose": purpose,
                    "required_resource": required_resource,
                    **decision.to_event_data(),
                },
            )
        return decisions

    def _resolve_owner_appointment_selection(
        self,
        owner: EnterpriseAgentProfile,
        proposal,
        candidates: list[tuple[EnterpriseAgentProfile, object]],
        purpose: str,
        project: ConstructionProject,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        tick: int,
    ):
        options = [
            {
                "id": candidate.agent_id,
                "name": candidate.name,
                "role": candidate.role,
                "region": candidate.region,
                "accepted_appointment": bool(decision.accepted),
                "evidence_utility": round(float(decision.utility), 4),
                "available_resource": round(candidate.available_resource(), 4),
                "candidate_reason": decision.reason,
            }
            for candidate, decision in candidates
            if decision.accepted
        ]
        return self.agent_registry.resolve_decision(
            owner,
            proposal,
            decision_type=f"owner_select_{purpose}",
            tick=tick,
            project=project,
            stage_rule=self.stage_rules.get(project.current_stage),
            policy=policy,
            macro_environment=macro_environment,
            priority=DecisionPriority.P0_STAGE_CRITICAL,
            decision_task=(
                f"Select one accepting {purpose} candidate for the project, or reject the appointment if none "
                "fits the owner's financing, delivery, collaboration, and risk objectives."
            ),
            choice_options=options,
            choice_field="selected_agent_id",
        )

    def _handle_design(self, project: ConstructionProject, tick: int) -> None:
        if project.performance.design_quality >= 0.70 and project.performance.information_quality >= 0.65:
            self._transition(project, ProjectStage.APPROVAL, tick, "Design quality threshold reached")

    def _handle_approval(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        policy: PolicyRegime,
        tick: int,
    ) -> None:
        government, assignment_decision = self._select_government_reviewer(
            project,
            agents,
            tick,
            purpose="design approval",
            participant_ids=[project.owner_id, project.selected_architect_id or ""],
            policy=policy,
        )
        if not government:
            if project.stage_tick >= 2:
                project.performance.delay_days += 15
            self.events.record(
                tick,
                "approval_review_unassigned",
                "No regulator independently accepted the design approval review this month",
                project=project,
                agent_id=project.owner_id,
                data={
                    "delay_days_added": 15 if project.stage_tick >= 2 else 0,
                    "assignment_decision": assignment_decision,
                },
            )
            return
        self._ensure_engagement(project, government, "Government", EngagementStatus.ACTIVE, tick, 0.2)
        approval_decision = self.agent_module.propose(
            government,
            "decide_approval",
            project=project,
            policy=policy,
        )
        approval_decision = self.agent_registry.resolve_decision(
            government,
            approval_decision,
            decision_type="government_design_approval",
            tick=tick,
            project=project,
            stage_rule=self.stage_rules.get(project.current_stage),
            policy=policy,
            priority=DecisionPriority.P0_STAGE_CRITICAL,
            decision_task=(
                "Decide whether to approve the submitted design now or require revision, using statutory "
                "requirements, evidence completeness, current risk, institutional memory, and regulator capacity."
            ),
            allowed_actions=["approve", "request_revision"],
            negative_actions={"request_revision"},
        )
        approval_prob = approval_decision.probability
        if approval_decision.accepted:
            self.events.record(
                tick,
                "approval_approved",
                "Government approval granted",
                project=project,
                agent_id=government.agent_id if government else None,
                data={
                    "reviewer_id": government.agent_id if government else None,
                    "reviewer_name": government.name if government else "Government reviewer",
                    "result": "approved",
                    "approval_probability": round(float(approval_prob), 3),
                    "design_quality": round(project.performance.design_quality, 3),
                    "information_quality": round(project.performance.information_quality, 3),
                    "policy_approval_success_prob": round(policy.approval_success_prob, 3),
                    "procedural_uncertainty": round(policy.procedural_uncertainty, 3),
                    "regulatory_intensity": round(policy.regulatory_intensity, 3),
                    "information_transparency": round(policy.information_transparency, 3),
                    "assignment_decision": assignment_decision,
                    "individual_decision": approval_decision.to_event_data(),
                },
            )
            self._release_role(project, agents, "Government", tick, "Approval completed")
            self._standby_role(project, agents, "Architect", tick, "Design and approval support completed")
            self._transition(project, ProjectStage.TENDER_PREPARATION, tick, "Approval approved")
        elif project.stage_tick >= 2:
            project.performance.delay_days += 30
            self.events.record(
                tick,
                "approval_rejected",
                "Approval returned for design revision",
                project=project,
                agent_id=government.agent_id if government else None,
                data={
                    "reviewer_id": government.agent_id if government else None,
                    "reviewer_name": government.name if government else "Government reviewer",
                    "result": "revision required",
                    "approval_probability": round(float(approval_prob), 3),
                    "design_quality": round(project.performance.design_quality, 3),
                    "information_quality": round(project.performance.information_quality, 3),
                    "policy_approval_success_prob": round(policy.approval_success_prob, 3),
                    "procedural_uncertainty": round(policy.procedural_uncertainty, 3),
                    "regulatory_intensity": round(policy.regulatory_intensity, 3),
                    "information_transparency": round(policy.information_transparency, 3),
                    "assignment_decision": assignment_decision,
                    "individual_decision": approval_decision.to_event_data(),
                },
            )
            self._release_role(project, agents, "Government", tick, "Approval review finished with rejection")
            self._recall_or_activate_role(project, agents, "Architect", tick, 0.4, "Approval revision required")
            self._transition(project, ProjectStage.DESIGN, tick, "Approval rejected, returning to design")

    def _select_government_reviewer(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        tick: int,
        *,
        purpose: str,
        participant_ids: list[str],
        policy: PolicyRegime | None = None,
        macro_environment: MacroEnvironment | None = None,
    ) -> tuple[Optional[EnterpriseAgentProfile], dict]:
        candidates = self.agent_pool.visible_candidates(
            agents.values(),
            "Government",
            0.2,
            self.engagement_manager,
            project,
            participant_ids,
            limit=6 if len(agents) > 1000 else 24,
        )
        accepted = []
        candidate_decisions = []
        for candidate in candidates:
            decision = self.agent_module.propose(
                candidate,
                "consider_review_assignment",
                project=project,
                required_resource=0.2,
            )
            decision = self.agent_registry.resolve_decision(
                candidate,
                decision,
                decision_type="government_review_assignment",
                tick=tick,
                project=project,
                stage_rule=self.stage_rules.get(project.current_stage),
                policy=policy,
                macro_environment=macro_environment,
                priority=DecisionPriority.P2_INTERACTION,
                decision_task=(
                    f"Decide whether this regulator should accept the {purpose} assignment based on jurisdiction, "
                    "capacity, current workload, policy evidence, risk, and its own institutional memory."
                ),
                allowed_actions=["accept_regulatory_review", "defer_regulatory_review"],
                negative_actions={"defer_regulatory_review"},
            )
            decision_data = {
                "government_id": candidate.agent_id,
                "government_name": candidate.name,
                "purpose": purpose,
                **decision.to_event_data(),
            }
            candidate_decisions.append(decision_data)
            if decision.accepted:
                accepted.append((candidate, decision))
            self.events.record(
                tick,
                "regulatory_review_decision",
                f"Government {candidate.agent_id} independently decided whether to accept {purpose}",
                project=project,
                agent_id=candidate.agent_id,
                data=decision_data,
            )
        if not accepted:
            return None, {
                "decision_process": "GovernmentAgent.consider_review_assignment",
                "candidate_count": len(candidates),
                "accepted_candidate_count": 0,
                "candidate_decisions": candidate_decisions,
            }
        selected, selected_decision = max(
            accepted,
            key=lambda item: (item[1].utility, item[0].agent_id),
        )
        return selected, {
            "decision_process": "independent regulator acceptance followed by jurisdiction routing",
            "candidate_count": len(candidates),
            "accepted_candidate_count": len(accepted),
            "selected_government_id": selected.agent_id,
            "selected_utility": round(selected_decision.utility, 4),
            "candidate_decisions": candidate_decisions,
        }

    def _handle_tender_preparation(self, project: ConstructionProject, tick: int) -> None:
        if (
            project.stage_tick >= self.MIN_TENDER_PREPARATION_TICKS
            and project.performance.information_quality >= 0.60
            and not project.flags.get("tender_documents_ready")
        ):
            project.flags["tender_documents_ready"] = True
            self.events.record(
                tick,
                "tender_documents_prepared",
                "QS prepared tender documents, bill of quantities, and contractor evaluation criteria",
                project=project,
                agent_id=project.selected_qs_id,
                data={
                    "qs_id": project.selected_qs_id,
                    "information_quality": round(project.performance.information_quality, 3),
                    "planned_cost": project.performance.planned_cost,
                    "evaluation_criteria": [
                        "bid price",
                        "technical capability",
                        "construction capability",
                        "quality management",
                        "safety management",
                        "financial capacity",
                        "collaboration history",
                    ],
                },
            )
            self._transition(project, ProjectStage.TENDERING, tick, "Tender documents ready")

    def _handle_tendering(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        tick: int,
    ) -> None:
        if not project.flags.get("contractors_invited"):
            project.flags["contractors_invited"] = True
            project.bids.clear()
            attractiveness = self._tender_attractiveness(project, policy, macro_environment)
            market_candidates = self.agent_pool.visible_candidates(
                agents.values(),
                "Contractor",
                0.15,
                self.engagement_manager,
                project,
                [project.owner_id, project.selected_architect_id or "", project.selected_qs_id or ""],
                limit=max(self.max_tender_invites * 4, self.max_tender_invites),
            )
            owner = agents[project.owner_id]
            shortlist_decision = self.agent_module.propose(
                owner,
                "select_tender_invitees",
                candidates=market_candidates,
                project=project,
                policy=policy,
                macro_environment=macro_environment,
                limit=self.max_tender_invites,
            )
            ranked_by_id = {
                item["agent_id"]: item.get("score")
                for item in shortlist_decision.data.get("ranked_candidates", [])
            }
            shortlist_decision = self.agent_registry.resolve_decision(
                owner,
                shortlist_decision,
                decision_type="owner_tender_shortlist",
                tick=tick,
                project=project,
                stage_rule=self.stage_rules.get(project.current_stage),
                policy=policy,
                macro_environment=macro_environment,
                priority=DecisionPriority.P0_STAGE_CRITICAL,
                decision_task=(
                    f"Select up to {self.max_tender_invites} contractors to invite. Use capability, workload, "
                    "regional fit, collaboration memory, competition quality, and delivery risk; return their ids."
                ),
                choice_options=[
                    {
                        "id": contractor.agent_id,
                        "name": contractor.name,
                        "region": contractor.region,
                        "available_resource": round(contractor.available_resource(), 4),
                        "construction_capability": contractor.construction_capability,
                        "quality_management_capability": contractor.quality_management_capability,
                        "safety_management_capability": contractor.safety_management_capability,
                        "evidence_score": ranked_by_id.get(contractor.agent_id),
                    }
                    for contractor in market_candidates
                ],
                choice_field="selected_agent_ids",
                choice_multiple=True,
                choice_limit=self.max_tender_invites,
            )
            invited_ids = set(shortlist_decision.data.get("selected_agent_ids", []))
            invited_contractors = [
                contractor
                for contractor in market_candidates
                if contractor.agent_id in invited_ids
            ]
            self.events.record(
                tick,
                "tender_opened",
                "Tender opened and qualified contractors were invited to decide whether to bid",
                project=project,
                agent_id=project.owner_id,
                data={
                    "invited_count": len(invited_contractors),
                    "invited_contractors": [
                        {
                            "contractor_id": contractor.agent_id,
                            "contractor_name": contractor.name,
                            "region": contractor.region,
                            "available_resource": round(contractor.available_resource(), 3),
                        }
                        for contractor in invited_contractors[:12]
                    ],
                    "attractiveness": round(attractiveness, 3),
                    "budget": project.initial_budget,
                    "camel_tender_advisor_limit": self.max_tender_camel_advisors,
                    "owner_shortlist_decision": shortlist_decision.to_event_data(),
                },
            )
            for contractor in invited_contractors:
                self._ensure_engagement(project, contractor, "Contractor", EngagementStatus.INVITED, tick, 0.1)
                self.events.record(
                    tick,
                    "tender_invitation_received",
                    "Contractor received a tender invitation and must decide whether to bid",
                    project=project,
                    agent_id=contractor.agent_id,
                    data={
                        "owner_id": project.owner_id,
                        "qs_id": project.selected_qs_id,
                        "contractor_id": contractor.agent_id,
                        "contractor_name": contractor.name,
                        "region": contractor.region,
                        "available_resource": round(contractor.available_resource(), 3),
                        "tender_attractiveness": round(attractiveness, 3),
                        "initial_budget": project.initial_budget,
                    },
                )
            project.flags["invited_contractor_ids"] = [contractor.agent_id for contractor in invited_contractors]
            project.flags["tender_attractiveness"] = round(attractiveness, 6)
            session_contractors = invited_contractors[:8]
            if session_contractors:
                recipients = [contractor.agent_id for contractor in session_contractors]
                participants = [project.owner_id, project.selected_qs_id or "", *recipients]
                self._start_interaction_session(
                    project,
                    tick,
                    session_type="tender_clarification",
                    participants=participants,
                    event_type="tender_clarification_session_started",
                    description="Tender clarification session opened for shortlisted contractors",
                    agent_id=project.owner_id,
                    metadata={
                        "owner_id": project.owner_id,
                        "qs_id": project.selected_qs_id,
                        "contractor_ids": recipients,
                        "invited_count": len(invited_contractors),
                        "session_scope": "shortlisted_contractors",
                    },
                    messages=[
                        {
                            "sender_id": project.owner_id,
                            "recipient_ids": recipients,
                            "topic": "tender_invitation",
                            "content": (
                                "Owner issued tender invitation and expects contractors to assess price, "
                                "resource capacity, risk allocation, and delivery programme before bidding."
                            ),
                        },
                        {
                            "sender_id": project.selected_qs_id or project.owner_id,
                            "recipient_ids": recipients,
                            "topic": "tender_clarification",
                            "content": (
                                "QS opened a controlled clarification channel for tender documents, "
                                "bill-of-quantities assumptions, and submission requirements."
                            ),
                        },
                    ],
                )
            return

        if not project.flags.get("bids_collected"):
            project.flags["bids_collected"] = True
            attractiveness = float(
                project.flags.get("tender_attractiveness")
                or self._tender_attractiveness(project, policy, macro_environment)
            )
            contractor_ids = project.flags.get("invited_contractor_ids", [])
            contractors = [
                agents[contractor_id]
                for contractor_id in contractor_ids
                if contractor_id in agents
            ]
            bid_decision_inputs = []
            for contractor in contractors:
                engagement = self.engagement_manager.find(project, contractor.agent_id, "Contractor")
                if not engagement or engagement.status != EngagementStatus.INVITED:
                    continue
                bid_assessment = self._contractor_bid_assessment(
                    contractor,
                    project,
                    policy,
                    macro_environment,
                    attractiveness,
                )
                bid_decision_inputs.append(
                    {
                        "contractor": contractor,
                        "engagement": engagement,
                        "bid_assessment": bid_assessment,
                        "advisor_requested": True,
                    }
                )

            advisor_results = self._batch_tender_advisor_decisions(
                project,
                policy,
                macro_environment,
                tick,
                attractiveness,
                bid_decision_inputs,
            )

            for bid_decision_input in bid_decision_inputs:
                contractor = bid_decision_input["contractor"]
                bid_assessment = bid_decision_input["bid_assessment"]
                advisor_skipped_reason = None
                advisor_action = None
                advisor_result = advisor_results.get(contractor.agent_id)
                if advisor_result:
                    advisor_action = advisor_result.get("action")
                    advisor_skipped_reason = advisor_result.get("skipped_reason")
                else:
                    advisor_skipped_reason = "llm_agent_decision_unavailable"
                bid_probability = self._apply_tender_advisor(
                    bid_assessment["bid_probability"],
                    advisor_action,
                )
                advisor_event_data = self._advisor_event_data(advisor_action, advisor_skipped_reason)
                engagement = self.engagement_manager.find(project, contractor.agent_id, "Contractor")
                individual_decision = bid_assessment["individual_decision"]
                submit_bid = self._should_submit_bid(
                    bid_probability,
                    advisor_action,
                    individual_decision.get("accepted", False),
                )
                self.events.record(
                    tick,
                    "contractor_tender_decision",
                    f"Contractor {contractor.agent_id} independently evaluated the tender before any advisor adjustment",
                    project=project,
                    agent_id=contractor.agent_id,
                    data={
                        **individual_decision,
                        "advisor_adjusted_probability": round(bid_probability, 4),
                        "final_submit_bid": submit_bid,
                        "decision_advisor": advisor_event_data,
                    },
                )
                if submit_bid:
                    if engagement:
                        contractor.occupied_resource += 0.15 - engagement.resource_allocation
                        engagement.status = EngagementStatus.BIDDING
                        engagement.resource_allocation = 0.15
                    project.bids.append(
                        {
                            "contractor_id": contractor.agent_id,
                            "contractor_name": contractor.name,
                            "bid_price": bid_assessment["bid_price"],
                            "expected_profit": bid_assessment["expected_profit"],
                            "risk_level": bid_assessment["risk_level"],
                            "bid_probability": bid_probability,
                            "technical_score": contractor.construction_capability,
                            "safety_score": contractor.safety_management_capability,
                            "quality_score": contractor.quality_management_capability,
                            "decision_factors": bid_assessment["decision_factors"],
                            "individual_decision": individual_decision,
                            "decision_advisor": advisor_event_data,
                            "submitted_tick": tick,
                        }
                    )
                    self.events.record(
                        tick,
                        "bid_submitted",
                        f"Contractor {contractor.agent_id} submitted bid",
                        project=project,
                        agent_id=contractor.agent_id,
                        data={
                            "contractor_id": contractor.agent_id,
                            "contractor_name": contractor.name,
                            "bid_price": bid_assessment["bid_price"],
                            "expected_profit": bid_assessment["expected_profit"],
                            "risk_level": bid_assessment["risk_level"],
                            "bid_probability": bid_probability,
                            "technical_score": contractor.construction_capability,
                            "safety_score": contractor.safety_management_capability,
                            "quality_score": contractor.quality_management_capability,
                            "decision_factors": bid_assessment["decision_factors"],
                            "individual_decision": individual_decision,
                            "decision_advisor": advisor_event_data,
                        },
                    )
                else:
                    if engagement:
                        self.engagement_manager.release_engagement(
                            engagement,
                            contractor,
                            project,
                            tick,
                            "Contractor declined tender",
                        )
                    self.events.record(
                        tick,
                        "bid_declined",
                        f"Contractor {contractor.agent_id} declined bid",
                        project=project,
                        agent_id=contractor.agent_id,
                        data={
                            "contractor_id": contractor.agent_id,
                            "contractor_name": contractor.name,
                            "decline_reason": bid_assessment["decline_reason"],
                            "bid_probability": bid_probability,
                            "risk_level": bid_assessment["risk_level"],
                            "expected_profit": bid_assessment["expected_profit"],
                            "decision_factors": bid_assessment["decision_factors"],
                            "individual_decision": individual_decision,
                            "decision_advisor": advisor_event_data,
                        },
                    )

        if len(project.bids) >= 1:
            self._transition(project, ProjectStage.BID_EVALUATION, tick, "Minimum valid bids received")
        elif project.stage_tick >= 2:
            project.performance.delay_days += 30
            invited_contractor_ids = list(project.flags.get("invited_contractor_ids", []))
            project.flags["contractors_invited"] = False
            project.flags["bids_collected"] = False
            project.flags["invited_contractor_ids"] = []
            self.events.record(
                tick,
                "bid_failed",
                "Tender failed due to insufficient valid bids",
                project=project,
                agent_id=project.owner_id,
                data={
                    "owner_id": project.owner_id,
                    "qs_id": project.selected_qs_id,
                    "invited_contractor_ids": invited_contractor_ids,
                    "valid_bid_count": len(project.bids),
                    "failure_reason": "insufficient valid bids",
                    "delay_days_added": 30,
                },
            )

    def _handle_bid_evaluation(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        tick: int,
    ) -> None:
        if project.stage_tick < self.MIN_BID_EVALUATION_TICKS:
            return

        if not project.bids:
            self._transition(project, ProjectStage.TENDERING, tick, "No valid bids, return to tendering")
            return

        qs = agents.get(project.selected_qs_id or "")
        owner = agents.get(project.owner_id)
        if not qs or not owner:
            project.performance.delay_days += 15
            self.events.record(
                tick,
                "bid_evaluation_deferred",
                "Bid evaluation was deferred because the owner or QS was unavailable",
                project=project,
                data={"owner_id": project.owner_id, "qs_id": project.selected_qs_id, "delay_days_added": 15},
            )
            return

        evaluated_bids = []
        for bid in project.bids:
            contractor = agents[bid["contractor_id"]]
            prior_fit = self.agent_pool.collaboration_prior.participant_fit(
                contractor.agent_id,
                [project.owner_id, project.selected_architect_id or "", project.selected_qs_id or ""],
                0.5,
            )
            qs_decision = self.agent_module.propose(
                qs,
                "evaluate_bid",
                bid=bid,
                contractor=contractor,
                project=project,
                policy=policy,
                prior_fit=prior_fit,
            )
            qs_decision = self.agent_registry.resolve_decision(
                qs,
                qs_decision,
                decision_type="qs_bid_evaluation",
                tick=tick,
                project=project,
                stage_rule=self.stage_rules.get(project.current_stage),
                policy=policy,
                macro_environment=macro_environment,
                priority=DecisionPriority.P0_STAGE_CRITICAL,
                decision_task=(
                    f"Review contractor {contractor.agent_id}'s bid for admissibility and evaluation integrity. "
                    "Use the formal score as evidence, together with cost certainty, delivery risk, prior memory, "
                    "and the QS firm's current professional obligations."
                ),
                allowed_actions=["evaluate_bid", "exclude_bid"],
                negative_actions={"exclude_bid"},
            )
            if not qs_decision.accepted:
                continue
            evaluated_bids.append(
                {
                    **bid,
                    "evaluation_score": qs_decision.data["evaluation_score"],
                    "contractor_region": contractor.region,
                    "qs_decision": qs_decision.to_event_data(),
                }
            )
        owner_decision = self.agent_module.propose(
            owner,
            "select_preferred_bid",
            evaluated_bids=evaluated_bids,
            agents=agents,
        )
        owner_decision = self.agent_registry.resolve_decision(
            owner,
            owner_decision,
            decision_type="owner_preferred_bidder_selection",
            tick=tick,
            project=project,
            stage_rule=self.stage_rules.get(project.current_stage),
            policy=policy,
            macro_environment=macro_environment,
            priority=DecisionPriority.P0_STAGE_CRITICAL,
            decision_task=(
                "Select the preferred bidder from the valid QS-evaluated bids, balancing price, technical delivery, "
                "quality, safety, financial resilience, workload, collaboration memory, and project risk."
            ),
            choice_options=[
                {
                    "id": bid["contractor_id"],
                    "contractor_name": agents[bid["contractor_id"]].name,
                    "bid_price": bid.get("bid_price"),
                    "evaluation_score": bid.get("evaluation_score"),
                    "expected_profit": bid.get("expected_profit"),
                    "risk_level": bid.get("risk_level"),
                }
                for bid in evaluated_bids
            ],
            choice_field="selected_contractor_id",
        )
        if not owner_decision.accepted:
            project.performance.delay_days += 15
            self.events.record(
                tick,
                "bid_evaluation_deferred",
                "Owner did not select a preferred bidder after the QS evaluation",
                project=project,
                agent_id=owner.agent_id,
                data={"owner_decision": owner_decision.to_event_data(), "delay_days_added": 15},
            )
            return
        project.selected_contractor_id = owner_decision.data["selected_contractor_id"]
        project.bids = owner_decision.data["ranked_bids"]
        winning_bid = next(
            bid for bid in project.bids if bid["contractor_id"] == project.selected_contractor_id
        )
        project.contract_sum = winning_bid["bid_price"]
        for bid in project.bids:
            contractor = agents[bid["contractor_id"]]
            engagement = self.engagement_manager.find(project, contractor.agent_id, "Contractor")
            if not engagement:
                continue
            if contractor.agent_id == project.selected_contractor_id:
                engagement.status = EngagementStatus.BIDDING
            else:
                self.engagement_manager.release_engagement(engagement, contractor, project, tick, "Bid unsuccessful")

        self.events.record(
            tick,
            "bid_evaluation_completed",
            f"Preferred bidder {project.selected_contractor_id} selected after bid evaluation",
            project=project,
            agent_id=project.selected_contractor_id,
            data={
                "contract_sum": project.contract_sum,
                "selected_contractor_id": project.selected_contractor_id,
                "selected_contractor_name": agents[project.selected_contractor_id].name,
                "valid_bid_count": len(project.bids),
                "ranked_bids": project.bids,
                "evaluation_committee": {
                    "owner_id": project.owner_id,
                    "qs_id": project.selected_qs_id,
                },
                "owner_decision": owner_decision.to_event_data(),
                "qs_decision_process": "QSAgent.evaluate_bid",
            },
        )
        self._transition(project, ProjectStage.CONTRACT_AWARD, tick, "Bid evaluation completed")

    def _handle_contract_award(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        tick: int,
    ) -> None:
        if not project.selected_contractor_id or not project.contract_sum:
            self._transition(project, ProjectStage.BID_EVALUATION, tick, "Contract award failed")
            return
        if not project.flags.get("contract_negotiation_started"):
            contractor = agents[project.selected_contractor_id]
            owner = agents.get(project.owner_id)
            preferred_bid = next(
                (bid for bid in project.bids if bid.get("contractor_id") == project.selected_contractor_id),
                {},
            )
            project.flags["contract_negotiation_started"] = True
            self._start_interaction_session(
                project,
                tick,
                session_type="contract_negotiation",
                participants=[project.owner_id, contractor.agent_id, project.selected_qs_id or ""],
                event_type="contract_negotiation_session_started",
                description="Controlled contract negotiation session opened before contract signing",
                agent_id=project.owner_id,
                metadata={
                    "owner_id": project.owner_id,
                    "contractor_id": contractor.agent_id,
                    "qs_id": project.selected_qs_id,
                    "proposed_contract_sum": project.contract_sum,
                    "expected_profit": preferred_bid.get("expected_profit"),
                    "risk_level": preferred_bid.get("risk_level"),
                },
                messages=[
                    {
                        "sender_id": project.owner_id,
                        "recipient_ids": [contractor.agent_id, project.selected_qs_id or ""],
                        "topic": "contract_terms",
                        "content": (
                            "Owner requested confirmation of contract sum, payment milestones, programme duration, "
                            "risk allocation, and mobilization readiness before signing."
                        ),
                    },
                    {
                        "sender_id": contractor.agent_id,
                        "recipient_ids": [project.owner_id, project.selected_qs_id or ""],
                        "topic": "contract_terms",
                        "content": (
                            "Preferred contractor confirmed the bid basis and highlighted resource commitment, "
                            "cashflow exposure, and delivery risk items for QS review."
                        ),
                    },
                ],
            )
            self.events.record(
                tick,
                "contract_negotiation_started",
                "Owner and preferred contractor started contract confirmation before signing",
                project=project,
                agent_id=project.selected_contractor_id,
                data={
                    "owner_id": project.owner_id,
                    "owner_name": owner.name if owner else project.owner_id,
                    "contractor_id": contractor.agent_id,
                    "contractor_name": contractor.name,
                    "proposed_contract_sum": project.contract_sum,
                    "expected_profit": preferred_bid.get("expected_profit"),
                    "risk_level": preferred_bid.get("risk_level"),
                    "contract_checks": [
                        "price confirmation",
                        "payment reliability",
                        "programme duration",
                        "risk allocation",
                        "resource commitment",
                    ],
                },
            )
            return
        if not project.flags.get("contract_negotiation_recommendation_recorded"):
            self._record_contract_negotiation_recommendation(project, agents, tick)
            project.flags["contract_negotiation_recommendation_recorded"] = True
            return
        if project.flags.get("contractor_contract_decision") != "accept_terms":
            project.performance.delay_days += 7
            project.flags["contract_negotiation_recommendation_recorded"] = False
            self.events.record(
                tick,
                "contract_terms_not_accepted",
                "Contract signing was deferred because the contractor did not accept the current terms",
                project=project,
                agent_id=project.selected_contractor_id,
                data={
                    "selected_action": project.flags.get("contractor_contract_decision"),
                    "delay_days_added": 7,
                },
            )
            return
        if not project.flags.get("owner_contract_decision_recorded"):
            owner = agents[project.owner_id]
            preferred_bid = next(
                (bid for bid in project.bids if bid.get("contractor_id") == project.selected_contractor_id),
                {},
            )
            owner_decision = self.agent_module.propose(
                owner,
                "decide_contract_award",
                project=project,
                preferred_bid=preferred_bid,
            )
            owner_decision = self.agent_registry.resolve_decision(
                owner,
                owner_decision,
                decision_type="owner_contract_award",
                tick=tick,
                project=project,
                stage_rule=self.stage_rules.get(ProjectStage.CONTRACT_AWARD),
                priority=DecisionPriority.P0_STAGE_CRITICAL,
                decision_task=(
                    "Decide whether to accept the final contract award terms or request revision, using bid value, "
                    "delivery confidence, risk allocation, financing, organizational memory, and portfolio strategy."
                ),
                allowed_actions=["accept_contract", "request_contract_revision"],
                negative_actions={"request_contract_revision"},
            )
            project.flags["owner_contract_decision_recorded"] = True
            project.flags["owner_contract_accepted"] = owner_decision.accepted
            self.events.record(
                tick,
                "owner_contract_award_decision",
                "Owner independently decided whether to accept the final contract award terms",
                project=project,
                agent_id=owner.agent_id,
                data=owner_decision.to_event_data(),
            )
            if not owner_decision.accepted:
                project.performance.delay_days += 7
                project.flags["contract_negotiation_recommendation_recorded"] = False
                project.flags["owner_contract_decision_recorded"] = False
            return
        if not project.flags.get("owner_contract_accepted"):
            return
        if not project.flags.get("contract_signed"):
            contractor = agents[project.selected_contractor_id]
            engagement = self.engagement_manager.find(project, contractor.agent_id, "Contractor")
            if engagement:
                self.engagement_manager.activate_engagement(
                    engagement,
                    contractor,
                    project,
                    tick,
                    resource_allocation=0.8,
                    reason="Construction contract signed",
                )
            else:
                self._ensure_engagement(project, contractor, "Contractor", EngagementStatus.ACTIVE, tick, 0.8)
            project.contracts.append(
                {
                    "contractor_id": project.selected_contractor_id,
                    "contractor_name": contractor.name,
                    "contract_sum": project.contract_sum,
                    "contract_duration": project.performance.planned_duration,
                    "signed_tick": tick,
                }
            )
            project.flags["contract_signed"] = True
            self.events.record(
                tick,
                "contract_awarded",
                "Owner and preferred contractor signed the construction contract",
                project=project,
                agent_id=project.selected_contractor_id,
                data={
                    "owner_id": project.owner_id,
                    "owner_name": agents[project.owner_id].name if project.owner_id in agents else project.owner_id,
                    "contractor_id": project.selected_contractor_id,
                    "contractor_name": agents[project.selected_contractor_id].name,
                    "qs_id": project.selected_qs_id,
                    "contract_sum": project.contract_sum,
                    "contract_duration": project.performance.planned_duration,
                },
            )
            return
        if not project.flags.get("supplier_selected"):
            self._select_supplier_after_contract(project, agents, tick)
            return
        if not project.flags.get("mobilization_completed"):
            self._complete_mobilization(project, agents, tick)
            if project.flags.get("mobilization_completed"):
                self._transition(project, ProjectStage.CONSTRUCTION, tick, "Contract signed and supplier mobilized")

    def _record_contract_negotiation_recommendation(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        tick: int,
    ) -> None:
        if not project.selected_contractor_id or project.selected_contractor_id not in agents:
            return
        contractor = agents[project.selected_contractor_id]
        owner = agents.get(project.owner_id)
        qs = agents.get(project.selected_qs_id or "")
        session = self.interaction_sessions.get_or_create(
            project.project_id,
            "contract_negotiation",
            [project.owner_id, contractor.agent_id, project.selected_qs_id or ""],
        )
        allowed_recommendations = ["accept_terms", "request_revision", "escalate_dispute", "defer_negotiation"]
        contract_stage_rule = self.stage_rules.get(ProjectStage.CONTRACT_AWARD)
        bounded_stage_rule = (
            contract_stage_rule.model_copy(
                update={
                    "allowed_actions": {
                        **contract_stage_rule.allowed_actions,
                        "Contractor": allowed_recommendations,
                    }
                }
            )
            if hasattr(contract_stage_rule, "model_copy")
            else contract_stage_rule.copy(
                update={
                    "allowed_actions": {
                        **contract_stage_rule.allowed_actions,
                        "Contractor": allowed_recommendations,
                    }
                }
            )
        )
        preferred_bid = next(
            (bid for bid in project.bids if bid.get("contractor_id") == project.selected_contractor_id),
            {},
        )
        individual_decision = self.agent_module.propose(
            contractor,
            "decide_contract_terms",
            project=project,
            preferred_bid=preferred_bid,
        )
        context = {
            "tick": tick,
            "project": project,
            "stage_rule": bounded_stage_rule,
            "allowed_actions": allowed_recommendations,
            "recent_messages": [
                {
                    "sender_id": message.sender_id,
                    "recipient_ids": message.recipient_ids,
                    "content": message.content,
                    "topic": message.topic,
                }
                for message in session.recent_messages(limit=4)
            ],
            "risk_inputs": {
                "contract_sum": project.contract_sum,
                "planned_duration": project.performance.planned_duration,
                "expected_profit": preferred_bid.get("expected_profit"),
                "risk_level": preferred_bid.get("risk_level"),
                "bid_price": preferred_bid.get("bid_price"),
                "owner_id": project.owner_id,
                "contractor_id": contractor.agent_id,
                "qs_id": project.selected_qs_id,
            },
            "session_summary": session.compact_summary(),
            "individual_decision": individual_decision.to_event_data(),
            "instruction": (
                "Recommend one negotiation posture only. Do not award a contract, sign a contract, "
                "change budget, or mutate project state."
            ),
        }
        action: Optional[AgentAction] = None
        skipped_reason: Optional[str] = None
        error: Optional[str] = None
        try:
            action = self.decide_now(
                contractor,
                context,
                decision_type="contract_negotiation",
                priority=DecisionPriority.P2_INTERACTION,
                project_id=project.project_id,
            )
        except Exception as exc:
            error = str(exc)

        selected_action = action.action_type if action else "defer_negotiation"
        if action is None and error is None:
            skipped_reason = "llm_interaction_decision_unavailable"
        if selected_action not in allowed_recommendations:
            if selected_action:
                skipped_reason = "llm_interaction_action_invalid"
            selected_action = "defer_negotiation"

        reason = (
            getattr(action, "reason", None)
            or error
            or skipped_reason
            or "Contractor deferred the contract decision because no valid LLM decision was available."
        )
        content_by_action = {
            "accept_terms": "CAMEL recommendation: accept the negotiated contract terms subject to final QS checks.",
            "request_revision": "CAMEL recommendation: request limited revisions to payment, programme, or risk allocation before signing.",
            "escalate_dispute": "CAMEL recommendation: escalate unresolved commercial risk before signing.",
            "defer_negotiation": "LLM decision unavailable: defer contract signing and retain the current terms for review.",
        }
        self.interaction_sessions.append_message(
            session,
            tick=tick,
            sender_id=contractor.agent_id,
            recipient_ids=[project.owner_id, project.selected_qs_id or ""],
            topic="contract_negotiation_recommendation",
            content=content_by_action[selected_action],
            metadata={
                "decision_type": "contract_negotiation",
                "selected_action": selected_action,
                "decision_reason": reason,
                "individual_decision": individual_decision.to_event_data(),
                "error": error,
                "skipped_reason": skipped_reason,
                "provider": self.decision_provider.__class__.__name__,
            },
        )
        session.metadata["latest_recommendation"] = {
            "tick": tick,
            "selected_action": selected_action,
            "decision_reason": reason,
            "error": error,
            "skipped_reason": skipped_reason,
        }
        project.flags["contractor_contract_decision"] = selected_action
        self.events.record(
            tick,
            "contract_negotiation_recommendation",
            "CAMEL produced a bounded contract negotiation recommendation",
            project=project,
            agent_id=contractor.agent_id,
            data={
                "session_id": session.session_id,
                "session_type": session.session_type,
                "session_participants": session.participants,
                "owner_id": project.owner_id,
                "owner_name": owner.name if owner else project.owner_id,
                "contractor_id": contractor.agent_id,
                "contractor_name": contractor.name,
                "qs_id": project.selected_qs_id,
                "qs_name": qs.name if qs else project.selected_qs_id,
                "allowed_recommendations": allowed_recommendations,
                "selected_action": selected_action,
                "decision_reason": reason,
                "individual_decision": individual_decision.to_event_data(),
                "error": error,
                "skipped_reason": skipped_reason,
                "contract_sum": project.contract_sum,
                "stage_state_mutated": False,
            },
        )
        trace_action = AgentAction(
            action_type=selected_action,
            project_id=project.project_id,
            agent_id=contractor.agent_id,
            decision=selected_action == "accept_terms",
            reason=reason,
            data={"stage_state_mutated": False},
        )
        agent_cognitive_service.record_decision_trace(
            contractor,
            context,
            trace_action,
            camel_used=bool(action or error),
            fallback_used=False,
            validation_result={
                "valid": selected_action in allowed_recommendations,
                "bounded_interaction_recommendation": True,
                "stage_state_mutated": False,
                "skipped_reason": skipped_reason,
            },
            explanation=reason,
            candidate_actions=allowed_recommendations,
            retry_info={
                "attempts": 1 if action or error else 0,
                "errors": [error] if error else [],
                "skipped_reason": skipped_reason,
                "decision_type": "contract_negotiation",
            },
            error_info={"message": error} if error else {},
        )

    def _select_supplier_after_contract(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        tick: int,
    ) -> None:
        contractor = agents[project.selected_contractor_id]
        supplier_candidates = self.agent_pool.visible_candidates(
            agents.values(),
            "Supplier",
            0.35,
            self.engagement_manager,
            project,
            [contractor.agent_id],
            limit=16 if len(agents) > 1000 else 64,
        )
        supplier_offers = []
        for candidate in supplier_candidates:
            prior_fit = self.agent_pool.collaboration_prior.score(
                candidate.agent_id,
                contractor.agent_id,
                0.5,
            )
            decision = self.agent_module.propose(
                candidate,
                "consider_supply_order",
                project=project,
                contractor_id=contractor.agent_id,
                required_resource=0.35,
                prior_fit=prior_fit,
            )
            decision = self.agent_registry.resolve_decision(
                candidate,
                decision,
                decision_type="supplier_order_acceptance",
                tick=tick,
                project=project,
                stage_rule=self.stage_rules.get(project.current_stage),
                priority=DecisionPriority.P0_STAGE_CRITICAL,
                decision_task=(
                    "Decide whether to accept this supply order using inventory and delivery capacity, material "
                    "quality, price and logistics risk, contractor trust, regional experience, memory, and workload."
                ),
                allowed_actions=["accept_supply_order", "decline_supply_order"],
                negative_actions={"decline_supply_order"},
            )
            supplier_offers.append((candidate, decision))
            self.events.record(
                tick,
                "supplier_order_decision",
                f"Supplier {candidate.agent_id} independently decided whether to accept the project order",
                project=project,
                agent_id=candidate.agent_id,
                data=decision.to_event_data(),
            )
        contractor_decision = self.agent_module.propose(
            contractor,
            "select_supplier",
            offers=supplier_offers,
        )
        contractor_decision = self.agent_registry.resolve_decision(
            contractor,
            contractor_decision,
            decision_type="contractor_supplier_selection",
            tick=tick,
            project=project,
            stage_rule=self.stage_rules.get(project.current_stage),
            priority=DecisionPriority.P0_STAGE_CRITICAL,
            decision_task=(
                "Select one supplier that accepted the order, balancing reliability, material quality, regional "
                "delivery, collaboration memory, capacity, and construction programme risk."
            ),
            choice_options=[
                {
                    "id": candidate.agent_id,
                    "name": candidate.name,
                    "region": candidate.region,
                    "accepted_order": bool(decision.accepted),
                    "evidence_utility": round(float(decision.utility), 4),
                    "supply_reliability": candidate.supply_reliability,
                    "material_quality": candidate.material_quality,
                    "available_resource": round(candidate.available_resource(), 4),
                }
                for candidate, decision in supplier_offers
                if decision.accepted
            ],
            choice_field="selected_supplier_id",
        )
        supplier = agents.get(contractor_decision.data.get("selected_supplier_id", ""))
        ranked_suppliers = sorted(
            supplier_offers,
            key=lambda item: (item[1].utility, item[0].agent_id),
            reverse=True,
        )
        if supplier:
            project.selected_supplier_ids = [supplier.agent_id]
            project.flags["supplier_selected"] = True
            self._ensure_engagement(project, supplier, "Supplier", EngagementStatus.ACTIVE, tick, 0.35)
            supplier_score = next(
                decision.utility
                for candidate, decision in supplier_offers
                if candidate.agent_id == supplier.agent_id
            )
            self.events.record(
                tick,
                "supplier_selected",
                "Selected contractor appointed a supplier for construction delivery",
                project=project,
                agent_id=supplier.agent_id,
                data={
                    "contractor_id": project.selected_contractor_id,
                    "contractor_name": agents[project.selected_contractor_id].name,
                    "supplier_id": supplier.agent_id,
                    "supplier_name": supplier.name,
                    "material_quality": round(supplier.material_quality, 3),
                    "supply_reliability": round(supplier.supply_reliability, 3),
                    "supplier_selection_score": round(supplier_score, 3),
                    "candidate_count": len(supplier_offers),
                    "shortlisted_suppliers": [
                        {
                            "supplier_id": candidate.agent_id,
                            "supplier_name": candidate.name,
                            "region": candidate.region,
                            "selection_score": round(decision.utility, 3),
                            "accepted_order": decision.accepted,
                            "supply_reliability": round(candidate.supply_reliability, 3),
                            "material_quality": round(candidate.material_quality, 3),
                            "available_resource": round(candidate.available_resource(), 3),
                        }
                        for candidate, decision in ranked_suppliers[:6]
                    ],
                    "contractor_decision": contractor_decision.to_event_data(),
                    "selection_basis": [
                        "supply reliability",
                        "material quality",
                        "contractor collaboration prior",
                        "local delivery fit",
                        "available resource",
                    ],
                },
            )
        else:
            project.performance.delay_days += 15
            self.events.record(
                tick,
                "supplier_selection_failed",
                "Contract signed, but no available supplier could be mobilized this month",
                project=project,
                agent_id=project.selected_contractor_id,
                data={
                    "contractor_id": project.selected_contractor_id,
                    "contractor_name": agents[project.selected_contractor_id].name,
                    "required_resource": 0.35,
                    "delay_days_added": 15,
                    "contractor_decision": contractor_decision.to_event_data(),
                },
            )

    def _complete_mobilization(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        tick: int,
    ) -> None:
        supplier_id = project.selected_supplier_ids[0] if project.selected_supplier_ids else None
        supplier = agents.get(supplier_id or "")
        if not supplier:
            project.performance.delay_days += 15
            self.events.record(
                tick,
                "mobilization_delayed",
                "Construction mobilization delayed because the selected supplier was unavailable",
                project=project,
                agent_id=project.selected_contractor_id,
                data={
                    "contractor_id": project.selected_contractor_id,
                    "supplier_id": supplier_id,
                    "delay_days_added": 15,
                },
            )
            return
        project.flags["mobilization_completed"] = True
        self.events.record(
            tick,
            "mobilization_completed",
            "Contractor confirmed construction plan, resource allocation, and supplier readiness before site works",
            project=project,
            agent_id=project.selected_contractor_id,
            data={
                "contractor_id": project.selected_contractor_id,
                "contractor_name": agents[project.selected_contractor_id].name,
                "supplier_id": supplier.agent_id,
                "supplier_name": supplier.name,
                "contract_sum": project.contract_sum,
                "planned_duration": project.performance.planned_duration,
                "contractor_resource_allocation": 0.8,
                "supplier_resource_allocation": 0.35,
                "construction_plan": {
                    "method_statement_ready": True,
                    "site_team_allocated": True,
                    "supplier_delivery_window_confirmed": True,
                    "baseline_quality_plan": "linked to design quality and inspection regime",
                },
                "mobilization_risks": {
                    "supply_delay_risk": round(project.performance.supply_delay_risk, 3),
                    "material_availability": round(project.performance.material_availability, 3),
                    "project_failure_risk": round(project.performance.project_failure_risk, 3),
                },
            },
        )

    def _handle_construction(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        tick: int,
    ) -> None:
        if project.performance.safety_risk > 0.85 or project.performance.defect_rate > 0.75:
            project.current_stage = ProjectStage.SUSPENDED
            self.events.record(tick, "project_suspended", "Serious safety or quality issue", project=project)
            return

        variation_resolved_this_tick = False
        if project.flags.get("variation_open") and project.stage_tick >= int(project.flags.get("variation_tick", 0)) + 1:
            architect_id = project.selected_architect_id
            contractor_id = project.selected_contractor_id
            self.events.record(
                tick,
                "variation_resolved",
                "Architect clarified the construction-stage design variation and returned to standby",
                project=project,
                agent_id=architect_id,
                data={
                    "architect_id": architect_id,
                    "architect_name": agents[architect_id].name if architect_id in agents else architect_id,
                    "contractor_id": contractor_id,
                    "contractor_name": agents[contractor_id].name if contractor_id in agents else contractor_id,
                    "resolved_progress": round(project.performance.actual_progress, 4),
                    "variation_risk": round(project.performance.variation_risk, 3),
                    "claim_risk": round(project.performance.claim_risk, 3),
                },
            )
            self._standby_role(project, agents, "Architect", tick, "Construction variation resolved")
            project.flags["variation_open"] = False
            variation_resolved_this_tick = True

        if (
            not project.flags.get("variation_open")
            and not variation_resolved_this_tick
            and project.performance.variation_risk > 0.42
            and self.rng.random() < 0.12
        ):
            architect_id = project.selected_architect_id
            contractor_id = project.selected_contractor_id
            owner_id = project.owner_id
            self.events.record(
                tick,
                "variation_requested",
                "Contractor requested design clarification because variation risk exceeded the construction threshold",
                project=project,
                agent_id=contractor_id,
                data={
                    "owner_id": owner_id,
                    "owner_name": agents[owner_id].name if owner_id in agents else owner_id,
                    "contractor_id": contractor_id,
                    "contractor_name": agents[contractor_id].name if contractor_id in agents else contractor_id,
                    "architect_id": architect_id,
                    "architect_name": agents[architect_id].name if architect_id in agents else architect_id,
                    "request_reason": "design clarification during construction",
                    "actual_progress": round(project.performance.actual_progress, 4),
                    "progress_deviation": round(project.performance.progress_deviation, 4),
                    "variation_risk": round(project.performance.variation_risk, 3),
                    "design_quality": round(project.performance.design_quality, 3),
                    "detected_defect_rate": round(project.performance.detected_defect_rate, 3),
                    "claim_risk": round(project.performance.claim_risk, 3),
                    "potential_impacts": ["programme delay", "variation cost", "claim risk"],
                },
            )
            self._recall_or_activate_role(project, agents, "Architect", tick, 0.2, "Construction design variation")
            project.flags["variation_open"] = True
            project.flags["variation_tick"] = project.stage_tick

        if project.performance.actual_progress >= 1.0 and project.performance.overall_quality >= 0.60:
            government, assignment_decision = self._select_government_reviewer(
                project,
                agents,
                tick,
                purpose="completion inspection",
                participant_ids=[project.owner_id, project.selected_contractor_id or ""],
            )
            if not government:
                project.performance.delay_days += 15
                self.events.record(
                    tick,
                    "completion_inspection_unassigned",
                    "No regulator independently accepted the completion inspection this month",
                    project=project,
                    agent_id=project.owner_id,
                    data={"delay_days_added": 15, "assignment_decision": assignment_decision},
                )
                return
            self._ensure_engagement(project, government, "Government", EngagementStatus.ACTIVE, tick, 0.2)
            project.flags["completion_reviewer_assignment"] = assignment_decision
            self._transition(project, ProjectStage.COMPLETION, tick, "Construction complete")

    def _handle_completion(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        policy: PolicyRegime,
        tick: int,
    ) -> None:
        if not project.flags.get("completion_inspection_started"):
            project.flags["completion_inspection_started"] = True
            self.events.record(
                tick,
                "completion_inspection_started",
                "Contractor submitted completion documents and regulator started final inspection",
                project=project,
                agent_id=project.selected_contractor_id,
                data={
                    "contractor_id": project.selected_contractor_id,
                    "detected_defect_rate": round(project.performance.detected_defect_rate, 3),
                    "overall_quality": round(project.performance.overall_quality, 3),
                },
            )
            return
        government_engagement = self.engagement_manager.find(
            project,
            role="Government",
            statuses=[EngagementStatus.ACTIVE],
        )
        government = agents.get(government_engagement.agent_id) if government_engagement else None
        completion_decision = None
        if project.stage_tick >= self.MIN_COMPLETION_TICKS and government:
            completion_decision = self.agent_module.propose(
                government,
                "decide_approval",
                project=project,
                policy=policy,
            )
            completion_decision = self.agent_registry.resolve_decision(
                government,
                completion_decision,
                decision_type="government_completion_approval",
                tick=tick,
                project=project,
                stage_rule=self.stage_rules.get(project.current_stage),
                policy=policy,
                engagement=government_engagement,
                priority=DecisionPriority.P0_STAGE_CRITICAL,
                decision_task=(
                    "Decide whether final completion evidence is sufficient to approve handover or whether "
                    "rectification is required, using inspection findings, defects, quality, risk, and regulator memory."
                ),
                allowed_actions=["approve", "request_revision"],
                negative_actions={"request_revision"},
            )
        if (
            project.stage_tick >= self.MIN_COMPLETION_TICKS
            and project.performance.detected_defect_rate <= 0.35
            and completion_decision
            and completion_decision.accepted
        ):
            self.events.record(tick, "project_completed", "Completion approved", project=project)
            self._release_role(project, agents, "Government", tick, "Final inspection completed")
            self._release_role(project, agents, "Supplier", tick, "Supply obligation completed")
            self._transition(project, ProjectStage.FINAL_ACCOUNT, tick, "Completion approved")
        elif project.stage_tick >= 2:
            project.performance.delay_days += 30
            project.performance.defect_rate = max(0.0, project.performance.defect_rate - 0.10)
            self.events.record(
                tick,
                "quality_issue",
                "Rectification required before completion",
                project=project,
                agent_id=government.agent_id if government else None,
                data={
                    "completion_decision": completion_decision.to_event_data() if completion_decision else None,
                },
            )

    def _handle_final_account(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        tick: int,
    ) -> None:
        if not project.flags.get("final_account_review_started"):
            project.flags["final_account_review_started"] = True
            participants = [project.owner_id, project.selected_contractor_id or "", project.selected_qs_id or ""]
            self._start_interaction_session(
                project,
                tick,
                session_type="final_account_dispute",
                participants=participants,
                event_type="final_account_dispute_session_started",
                description="Final account review session opened to resolve payment and claim items",
                agent_id=project.selected_qs_id or project.owner_id,
                metadata={
                    "owner_id": project.owner_id,
                    "contractor_id": project.selected_contractor_id,
                    "qs_id": project.selected_qs_id,
                    "contract_sum": project.contract_sum or project.initial_budget,
                    "actual_cost": project.performance.actual_cost,
                    "claim_risk": round(project.performance.claim_risk, 3),
                    "dispute_risk": round(project.performance.dispute_risk, 3),
                },
                messages=[
                    {
                        "sender_id": project.selected_qs_id or project.owner_id,
                        "recipient_ids": [project.owner_id, project.selected_contractor_id or ""],
                        "topic": "final_account_review",
                        "content": (
                            "QS opened final account review and requested evidence for variations, payment records, "
                            "delay responsibility, and claim valuation."
                        ),
                    },
                    {
                        "sender_id": project.selected_contractor_id or project.owner_id,
                        "recipient_ids": [project.owner_id, project.selected_qs_id or ""],
                        "topic": "final_account_claim",
                        "content": (
                            "Contractor submitted final account basis covering actual cost, delay exposure, "
                            "variation claims, and unresolved payment items."
                        ),
                    },
                ],
            )
            self.events.record(
                tick,
                "final_account_review_started",
                "QS started final account review before settlement",
                project=project,
                agent_id=project.selected_qs_id or project.owner_id,
                data={
                    "owner_id": project.owner_id,
                    "contractor_id": project.selected_contractor_id,
                    "qs_id": project.selected_qs_id,
                    "contract_sum": project.contract_sum or project.initial_budget,
                    "actual_cost": project.performance.actual_cost,
                    "claim_risk": round(project.performance.claim_risk, 3),
                },
            )
            return
        if project.stage_tick >= self.MIN_FINAL_ACCOUNT_TICKS:
            contract_sum = project.contract_sum or project.initial_budget
            final_account_amount = max(contract_sum, project.performance.actual_cost)
            self.events.record(
                tick,
                "final_account_settled",
                "Owner, contractor, and QS settled final account and payment obligations",
                project=project,
                agent_id=project.selected_qs_id or project.owner_id,
                data={
                    "owner_id": project.owner_id,
                    "owner_name": agents[project.owner_id].name if project.owner_id in agents else project.owner_id,
                    "contractor_id": project.selected_contractor_id,
                    "contractor_name": (
                        agents[project.selected_contractor_id].name
                        if project.selected_contractor_id in agents
                        else project.selected_contractor_id
                    ),
                    "qs_id": project.selected_qs_id,
                    "qs_name": (
                        agents[project.selected_qs_id].name
                        if project.selected_qs_id in agents
                        else project.selected_qs_id
                    ),
                    "contract_sum": contract_sum,
                    "final_account_amount": final_account_amount,
                    "cost_overrun_ratio": round(project.performance.cost_overrun_ratio, 4),
                    "delay_days": project.performance.delay_days,
                    "claim_risk": round(project.performance.claim_risk, 3),
                    "dispute_risk": round(project.performance.dispute_risk, 3),
                },
            )
            for role in ["Contractor", "QS", "Architect", "Owner"]:
                self._release_role(project, agents, role, tick, "Final account settled")
            self._transition(project, ProjectStage.CLOSED, tick, "Final account settled")

    def _validate_representative_actions(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        tick: int,
    ) -> None:
        if project.current_stage not in self.stage_rules.rules:
            return
        stage_rule = self.stage_rules.get(project.current_stage)
        for role in stage_rule.required_roles:
            engagement = self.engagement_manager.find(
                project,
                role=role,
                statuses=[EngagementStatus.ACTIVE, EngagementStatus.BIDDING, EngagementStatus.INVITED],
            )
            if not engagement:
                continue
            agent = agents.get(engagement.agent_id)
            if not agent:
                continue
            participant_ids = [
                agent_id
                for agent_id in [
                    project.owner_id,
                    project.selected_architect_id,
                    project.selected_qs_id,
                    project.selected_contractor_id,
                ]
                if agent_id and agent_id != agent.agent_id
            ]
            action_type = self._default_action_for_role(role, project.current_stage, stage_rule.allowed_actions)
            if not action_type:
                continue
            action = AgentAction(
                action_type=action_type,
                project_id=project.project_id,
                agent_id=agent.agent_id,
                decision=True,
                data={
                    "validation_only": True,
                    "available_resource": round(agent.available_resource(), 4),
                    "regional_friction": round(
                        self._regional_friction(agent.region, project.region, macro_environment),
                        4,
                    ),
                    "previous_collaboration": round(
                        self.agent_pool.collaboration_prior.participant_fit(
                            agent.agent_id,
                            participant_ids,
                            0.5,
                        ),
                        4,
                    ),
                },
                reason=(
                    "Local guardrail validation for the current lifecycle role. "
                    "CAMEL is reserved for explicit enterprise decision points."
                ),
            )
            self.action_validator.validate(action, project, engagement, stage_rule, policy, tick)

    def _default_action_for_role(self, role: str, stage: ProjectStage, allowed_actions: dict[str, list[str]]) -> Optional[str]:
        actions = allowed_actions.get(role, [])
        return actions[0] if actions else None

    def _transition(self, project: ConstructionProject, next_stage: ProjectStage, tick: int, description: str) -> None:
        if project.current_stage == next_stage:
            return
        previous_stage = project.current_stage
        project.current_stage = next_stage
        project.stage_tick = 0
        self.events.record(
            tick,
            "stage_transition",
            description,
            project=project,
            stage=next_stage,
            data={"from_stage": previous_stage.value, "to_stage": next_stage.value},
        )
        self._record_lifecycle_task(project, next_stage, tick, description)

    def _record_lifecycle_task(
        self,
        project: ConstructionProject,
        stage: ProjectStage,
        tick: int,
        description: str,
    ) -> None:
        task_type_by_stage = {
            ProjectStage.INITIATION: "owner_initiation_task",
            ProjectStage.DESIGN: "design_coordination_task",
            ProjectStage.APPROVAL: "approval_review_task",
            ProjectStage.TENDER_PREPARATION: "tender_preparation_task",
            ProjectStage.TENDERING: "contractor_bid_decision_task",
            ProjectStage.BID_EVALUATION: "bid_evaluation_task",
            ProjectStage.CONTRACT_AWARD: "contract_award_task",
            ProjectStage.CONSTRUCTION: "construction_delivery_task",
            ProjectStage.COMPLETION: "completion_inspection_task",
            ProjectStage.FINAL_ACCOUNT: "final_account_task",
            ProjectStage.CLOSED: "final_account_task",
        }
        task_type = task_type_by_stage.get(stage)
        if not task_type:
            return
        try:
            agent_cognitive_service.record_simulation_task(
                project_id=project.project_id,
                agent_id=project.owner_id,
                stage=stage.value,
                task_type=task_type,
                content=description,
                state="done",
                created_tick=tick,
                completed_tick=tick,
                result={"stage": stage.value, "project_name": project.name},
                source="lifecycle_engine",
            )
        except Exception:
            return

    def _ensure_engagement(
        self,
        project: ConstructionProject,
        agent: EnterpriseAgentProfile,
        role: str,
        status: EngagementStatus,
        tick: int,
        resource_allocation: float,
        can_be_recalled: bool = False,
    ) -> None:
        existing = self.engagement_manager.find(project, agent.agent_id, role)
        if existing and existing.status == EngagementStatus.STANDBY and status == EngagementStatus.ACTIVE:
            self.engagement_manager.recall_standby_agent(
                project,
                agent,
                role,
                tick,
                resource_allocation,
                f"{role} required in {project.current_stage.value}",
            )
            return
        if existing and existing.status in {EngagementStatus.ACTIVE, EngagementStatus.INVITED, EngagementStatus.BIDDING}:
            return
        self.engagement_manager.create_engagement(
            project,
            agent,
            role,
            status,
            tick,
            resource_allocation,
            can_be_recalled=can_be_recalled,
        )

    def _release_role(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        role: str,
        tick: int,
        reason: str,
    ) -> None:
        for engagement in self.engagement_manager.by_role(project, role):
            agent = agents.get(engagement.agent_id)
            if agent and engagement.status not in {EngagementStatus.RELEASED, EngagementStatus.TERMINATED}:
                self.engagement_manager.release_engagement(engagement, agent, project, tick, reason)

    def _standby_role(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        role: str,
        tick: int,
        reason: str,
    ) -> None:
        for engagement in self.engagement_manager.by_role(project, role):
            agent = agents.get(engagement.agent_id)
            if agent and engagement.status == EngagementStatus.ACTIVE:
                self.engagement_manager.set_standby(engagement, agent, project, tick, reason)

    def _recall_or_activate_role(
        self,
        project: ConstructionProject,
        agents: Dict[str, EnterpriseAgentProfile],
        role: str,
        tick: int,
        resource_allocation: float,
        reason: str,
    ) -> None:
        for engagement in self.engagement_manager.by_role(project, role):
            agent = agents.get(engagement.agent_id)
            if not agent:
                continue
            if engagement.status == EngagementStatus.STANDBY:
                self.engagement_manager.recall_standby_agent(project, agent, role, tick, resource_allocation, reason)
            elif engagement.status == EngagementStatus.ACTIVE:
                return

    def _tender_attractiveness(
        self,
        project: ConstructionProject,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
    ) -> float:
        budget_reasonableness = min(
            1.25,
            project.initial_budget / max(project.performance.planned_cost or project.initial_budget, 1.0),
        )
        attractiveness = (
            0.28 * budget_reasonableness
            + 0.22 * project.performance.information_quality
            + 0.18 * (1.0 - project.performance.project_failure_risk)
            + 0.14 * policy.information_transparency
            + 0.10 * macro_environment.market_demand_index
            + 0.08 * macro_environment.financing_condition_index
            - 0.16 * policy.compliance_cost
            - 0.10 * policy.procedural_uncertainty
        )
        return max(0.05, min(0.95, attractiveness))

    def _contractor_bid_assessment(
        self,
        contractor: EnterpriseAgentProfile,
        project: ConstructionProject,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        attractiveness: float,
    ) -> dict:
        decision = self.agent_module.propose(
            contractor,
            "consider_tender",
            project=project,
            policy=policy,
            macro_environment=macro_environment,
            attractiveness=attractiveness,
        )
        return {
            "bid_probability": decision.data["bid_probability"],
            "bid_price": decision.data["bid_price"],
            "expected_profit": decision.data["expected_profit"],
            "risk_level": decision.data["risk_level"],
            "decline_reason": decision.data["decline_reason"],
            "decision_factors": decision.factors,
            "individual_decision": decision.to_event_data(),
        }

    def _advisor_tender_decision(
        self,
        contractor: EnterpriseAgentProfile,
        project: ConstructionProject,
        engagement,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        tick: int,
        bid_assessment: dict,
        attractiveness: float,
    ) -> Optional[AgentAction]:
        stage_rule, context = self._tender_decision_context(
            contractor,
            project,
            engagement,
            policy,
            macro_environment,
            tick,
            bid_assessment,
            attractiveness,
        )
        action = self.decide_now(
            contractor,
            context,
            decision_type="tender_decision",
            priority=DecisionPriority.P0_STAGE_CRITICAL,
            project_id=project.project_id,
        )
        if not action:
            return None
        if self.action_validator.validate(action, project, engagement, stage_rule, policy, tick):
            return action
        return None

    def _batch_tender_advisor_decisions(
        self,
        project: ConstructionProject,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        tick: int,
        attractiveness: float,
        bid_decision_inputs: list[dict],
    ) -> dict[str, dict]:
        requests: list[DecisionRequest] = []
        metadata_by_request_id: dict[str, dict] = {}
        scheduler = self._scheduler()
        for bid_decision_input in bid_decision_inputs:
            if not bid_decision_input.get("advisor_requested"):
                continue
            contractor = bid_decision_input["contractor"]
            engagement = bid_decision_input["engagement"]
            bid_assessment = bid_decision_input["bid_assessment"]
            stage_rule, context = self._tender_decision_context(
                contractor,
                project,
                engagement,
                policy,
                macro_environment,
                tick,
                bid_assessment,
                attractiveness,
            )
            request = self.decision_collector.build_request(
                scheduler,
                contractor,
                context,
                decision_type="tender_decision",
                priority=DecisionPriority.P0_STAGE_CRITICAL,
                project_id=project.project_id,
                project=project,
                stage_rule=stage_rule,
                allowed_actions=stage_rule.allowed_actions.get("Contractor", []),
                risk_inputs={
                    "tender_attractiveness": attractiveness,
                    "bid_assessment": bid_assessment,
                    "regional_friction": bid_assessment["decision_factors"]["regional_friction"],
                    "previous_collaboration": context.get("previous_collaboration"),
                },
            )
            requests.append(request)
            metadata_by_request_id[request.request_id] = {
                "contractor": contractor,
                "engagement": engagement,
                "stage_rule": stage_rule,
            }

        decisions: dict[str, dict] = {}
        if not requests:
            return decisions
        def apply_advisor_result(result) -> None:
            metadata = metadata_by_request_id[result.request.request_id]
            contractor = metadata["contractor"]
            engagement = metadata["engagement"]
            stage_rule = metadata["stage_rule"]
            if result.error:
                decisions[contractor.agent_id] = {
                    "action": None,
                    "skipped_reason": f"camel_decision_failed: {result.error}",
                }
                return
            if result.skipped_reason:
                decisions[contractor.agent_id] = {
                    "action": None,
                    "skipped_reason": result.skipped_reason,
                }
                return
            action = result.action
            if action and self.action_validator.validate(action, project, engagement, stage_rule, policy, tick):
                decisions[contractor.agent_id] = {"action": action, "skipped_reason": None}
            else:
                decisions[contractor.agent_id] = {
                    "action": None,
                    "skipped_reason": "camel_action_invalid",
                }

        self.action_applier.apply_results(
            scheduler.run_sync(requests),
            apply_advisor_result,
            include_non_ok=True,
        )
        return decisions

    def _tender_decision_context(
        self,
        contractor: EnterpriseAgentProfile,
        project: ConstructionProject,
        engagement,
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        tick: int,
        bid_assessment: dict,
        attractiveness: float,
    ):
        stage_rule = self.stage_rules.get(ProjectStage.TENDERING)
        return stage_rule, {
            "project": project,
            "stage_rule": stage_rule,
            "engagement": engagement,
            "policy": policy,
            "macro_environment": macro_environment,
            "regional_friction": bid_assessment["decision_factors"]["regional_friction"],
            "previous_collaboration": self.agent_pool.collaboration_prior.participant_fit(
                contractor.agent_id,
                [project.owner_id, project.selected_architect_id or "", project.selected_qs_id or ""],
                0.5,
            ),
            "tick": tick,
            "allowed_actions": stage_rule.allowed_actions.get("Contractor", []),
            "tender_attractiveness": attractiveness,
            "bid_assessment": bid_assessment,
        }

    @staticmethod
    def _apply_tender_advisor(
        base_probability: float,
        advisor_action: Optional[AgentAction],
    ) -> float:
        if not advisor_action:
            return max(0.03, min(0.96, base_probability))
        advisor_probability = advisor_action.data.get("bid_probability")
        if isinstance(advisor_probability, (int, float)):
            base_probability = 0.70 * base_probability + 0.30 * float(advisor_probability)
        if advisor_action.action_type == "decline_bid" or advisor_action.decision is False:
            base_probability *= 0.65
        elif advisor_action.action_type in {"submit_bid", "decide_bid"} and advisor_action.decision is True:
            base_probability += 0.04
        return max(0.03, min(0.96, base_probability))

    def _should_submit_bid(
        self,
        bid_probability: float,
        advisor_action: Optional[AgentAction],
        individual_accepted: bool,
    ) -> bool:
        if advisor_action:
            if advisor_action.action_type == "decline_bid" or advisor_action.decision is False:
                return False
            if advisor_action.action_type in {"submit_bid", "decide_bid"} and advisor_action.decision is True:
                return True
        # Local utility is decision support only. Without a valid model action,
        # the contractor does not submit a bid.
        return False

    @staticmethod
    def _advisor_event_data(
        advisor_action: Optional[AgentAction],
        skipped_reason: Optional[str] = None,
    ) -> dict:
        if not advisor_action:
            data = {"available": False}
            if skipped_reason:
                data["skipped_reason"] = skipped_reason
            return data
        return {
            "available": True,
            "action_type": advisor_action.action_type,
            "decision": advisor_action.decision,
            "reason": advisor_action.reason,
            "data": advisor_action.data,
        }

    def _regional_friction(
        self,
        source_region: str,
        target_region: str,
        macro_environment: MacroEnvironment,
    ) -> float:
        if source_region == target_region:
            return 0.0
        matrix = macro_environment.regional_friction_matrix or {}
        return float(matrix.get(source_region, {}).get(target_region, matrix.get(target_region, {}).get(source_region, 0.25)))
