import random
import hashlib
import json
import time
from typing import Dict, Optional

from gba_construction_sim.backend.agents.agent_registry import AgentBehaviorRegistry
from gba_construction_sim.backend.agents.contracts import AgentModulePort
from gba_construction_sim.backend.core.enums import ProjectStage
from gba_construction_sim.backend.core.ids import new_id
from gba_construction_sim.backend.decision.decision_provider import DecisionProvider
from gba_construction_sim.backend.models.action import AgentAction
from gba_construction_sim.backend.models.agent import EnterpriseAgentProfile
from gba_construction_sim.backend.models.environment import MacroEnvironment
from gba_construction_sim.backend.models.metrics import SimulationMetrics
from gba_construction_sim.backend.models.policy import PolicyRegime
from gba_construction_sim.backend.models.project import ConstructionProject
from gba_construction_sim.backend.models.project_performance import ProjectPerformanceState
from gba_construction_sim.backend.models.simulation import SimulationCreateRequest, SimulationRunResponse, SimulationSummary
from gba_construction_sim.backend.models.procurement import ProcurementExecution, require_available
from gba_construction_sim.backend.network.collaboration_network import CollaborationNetwork
from gba_construction_sim.backend.network.collaboration_prior import CollaborationPrior, load_default_collaboration_prior
from gba_construction_sim.backend.simulation.action_validator import ActionValidator
from gba_construction_sim.backend.simulation.action_applier import ActionApplier
from gba_construction_sim.backend.simulation.agent_operation_scheduler import AgentOperationScheduler
from gba_construction_sim.backend.simulation.decision_request import DecisionPriority
from gba_construction_sim.backend.simulation.engagement_manager import EngagementManager
from gba_construction_sim.backend.simulation.event_system import EventSystem
from gba_construction_sim.backend.simulation.macro_environment import MacroEnvironmentUpdater
from gba_construction_sim.backend.simulation.metrics_calculator import MetricsCalculator
from gba_construction_sim.backend.simulation.project_generator import ProjectGenerator
from gba_construction_sim.backend.simulation.project_lifecycle_engine import ProjectLifecycleEngine
from gba_construction_sim.backend.simulation.project_state_update_engine import ProjectStateUpdateEngine
from gba_construction_sim.backend.simulation.stage_rule_registry import StageRuleRegistry
from gba_construction_sim.backend.simulation.workflow_runtime import (
    WorkflowRuntimeController,
    normalize_workflow_configuration,
)
from gba_construction_sim.backend.storage.agent_database import agent_database
from gba_construction_sim.backend.storage.result_store import ResultStore

GBA_REGULATOR_CITIES = [
    "Guangzhou",
    "Shenzhen",
    "Hong Kong",
    "Macau",
    "Zhuhai",
    "Foshan",
    "Dongguan",
    "Huizhou",
    "Zhongshan",
    "Jiangmen",
    "Zhaoqing",
]


class SimulationEngine:
    def __init__(
        self,
        simulation_id: str,
        name: str,
        ticks: int,
        random_seed: Optional[int],
        policy: PolicyRegime,
        macro_environment: MacroEnvironment,
        agents: Dict[str, EnterpriseAgentProfile],
        projects: Dict[str, ConstructionProject],
        enable_project_generation: bool = False,
        max_tender_invites: int = 40,
        collaboration_prior: Optional[CollaborationPrior] = None,
        store_full_agent_snapshots: bool = False,
        target_project_count: Optional[int] = None,
        max_active_projects: Optional[int] = None,
        workflow_configuration: Optional[Dict] = None,
        agent_module: Optional[AgentModulePort] = None,
        decision_provider: Optional[DecisionProvider] = None,
        procurement_execution: Optional[ProcurementExecution] = None,
        procurement_executor=None,
    ) -> None:
        self._procurement_execution = ProcurementExecution(**(
            procurement_execution.dict() if procurement_execution is not None else {}
        ))
        require_available(self._procurement_execution, procurement_executor)
        self.procurement_executor = procurement_executor
        self.simulation_id = simulation_id
        self.name = name
        self.ticks = ticks
        self.random_seed = random_seed
        self.rng = random.Random(random_seed)
        self.current_tick = 0
        self.policy = policy
        self.macro_environment = macro_environment
        self.agents = agents
        self.projects = projects
        self.agent_module = agent_module or AgentBehaviorRegistry(
            self.agents.values(),
            random_seed,
        )
        self.agent_module.register_profiles(self.agents.values())
        # Backward-compatible alias for existing analytics/tests. New code uses
        # the explicit agent_module boundary.
        self.agent_registry = self.agent_module
        self.enable_project_generation = enable_project_generation
        self.max_tender_invites = max_tender_invites
        self.target_project_count = (
            max(1, int(target_project_count))
            if target_project_count is not None
            else self._default_project_generation_target(len(agents), ticks)
        )
        self.max_active_projects = (
            max(1, int(max_active_projects))
            if max_active_projects is not None
            else self._default_max_active_projects(self.target_project_count)
        )
        self.collaboration_prior = collaboration_prior or CollaborationPrior()
        observers = [self.agent_module.observe_event]
        provider_observer = getattr(decision_provider, "observe_event", None)
        if callable(provider_observer) and provider_observer != self.agent_module.observe_event:
            observers.append(provider_observer)
        self.events = EventSystem(observers=observers)
        self.workflow_config = normalize_workflow_configuration(workflow_configuration)
        self.workflow_config.setdefault("configuration", {})["procurement_execution"] = self.procurement_execution.dict()
        self.workflow_runtime = WorkflowRuntimeController(
            self.workflow_config,
            self.policy,
            self.macro_environment,
            self.events,
        )
        self.stage_rules = StageRuleRegistry()
        self.engagement_manager = EngagementManager(self.events)
        self.action_validator = ActionValidator(self.events)
        self.action_applier = ActionApplier()
        self.lifecycle_engine = ProjectLifecycleEngine(
            self.events,
            self.engagement_manager,
            self.stage_rules,
            self.action_validator,
            self.rng,
            max_tender_invites=max_tender_invites,
            collaboration_prior=self.collaboration_prior,
            decision_provider=decision_provider,
            agent_module=self.agent_module,
        )
        self.state_update_engine = ProjectStateUpdateEngine(self.events, self.rng, self.collaboration_prior)
        self.macro_updater = MacroEnvironmentUpdater(self.rng)
        self.project_generator = ProjectGenerator(self.rng)
        self.agent_operation_scheduler = AgentOperationScheduler(self.rng, self.agent_registry)
        self.network = CollaborationNetwork(self.collaboration_prior)
        self.metrics_calculator = MetricsCalculator()
        compact_snapshots = len(agents) > 1000 and not store_full_agent_snapshots
        self.result_store = ResultStore(store_full_agent_snapshots=not compact_snapshots)
        self.metrics = SimulationMetrics()
        self.status = "created"
        self._generated_project_counter = 0
        self.current_phase = "created"
        self.current_operation = "waiting"
        self.last_step_profile: Dict = {}
        self.step_profile_history: list[Dict] = []
        if procurement_executor is not None:
            procurement_executor.attach(self)

    @classmethod
    def from_request(
        cls,
        request: SimulationCreateRequest,
        *,
        agent_module: Optional[AgentModulePort] = None,
        decision_provider: Optional[DecisionProvider] = None,
        procurement_executor=None,
    ) -> "SimulationEngine":
        # Reject unavailable modes before loading agents, projects or providers.
        require_available(request.procurement_execution, procurement_executor)
        agents = agents_from_request(request)
        if request.initial_projects:
            projects = request.initial_projects
        elif request.enable_project_generation:
            projects = []
        else:
            projects = default_projects_for_agents(agents)
        policy = PolicyRegime(**request.policy)
        macro_environment = MacroEnvironment(**request.macro_environment)
        collaboration_prior = (
            load_default_collaboration_prior()
            if request.use_prior_network_edges and request.agent_source.lower() == "database"
            else CollaborationPrior()
        )
        return cls(
            simulation_id=new_id("SIM"),
            name=request.name,
            ticks=request.ticks,
            random_seed=request.random_seed,
            policy=policy,
            macro_environment=macro_environment,
            agents={agent.agent_id: agent for agent in agents},
            projects={project.project_id: project for project in projects},
            enable_project_generation=request.enable_project_generation,
            max_tender_invites=max(1, request.max_tender_invites),
            collaboration_prior=collaboration_prior,
            store_full_agent_snapshots=request.store_full_agent_snapshots,
            target_project_count=request.target_project_count,
            max_active_projects=request.max_active_projects,
            workflow_configuration=request.workflow_configuration,
            procurement_execution=request.procurement_execution,
            agent_module=agent_module,
            decision_provider=decision_provider,
            procurement_executor=procurement_executor,
        )

    def step(self, return_snapshot: bool = True) -> Dict:
        if self.current_tick >= self.ticks:
            self.status = "completed"
            self.current_phase = "completed"
            self.current_operation = "completed"
            self._record_step_profile(
                {
                    "tick": self.current_tick,
                    "status": self.status,
                    "total_step_ms": 0.0,
                    "skipped_reason": "already_completed",
                }
            )
            return self.snapshot() if return_snapshot else self._step_summary()

        # External procurement may take time or fail. Prepare it before changing
        # the clock, environment, resources or project state for this tick.
        if self.procurement_executor is not None:
            self.procurement_executor.prepare_tick(self)
        previous_tick = self.current_tick
        self.status = "running"
        self.current_tick += 1
        self.current_phase = f"tick_{self.current_tick}"
        step_started_at = time.perf_counter()
        profile: Dict = {
            "tick": self.current_tick,
            "status": self.status,
            "project_count": len(self.projects),
            "agent_count": len(self.agents),
            "return_snapshot_requested": bool(return_snapshot),
        }
        try:
            # The provider may be replaced at runtime for a model switch, test,
            # or recovery path. Synchronize it before any subject can decide.
            self.lifecycle_engine.sync_decision_scheduler()

            self.current_operation = "updating_macro_environment"
            section_started_at = time.perf_counter()
            self.macro_updater.update(self.macro_environment, self.current_tick)
            profile["macro_environment_ms"] = self._elapsed_ms(section_started_at)

            self.current_operation = "applying_workflow_configuration"
            section_started_at = time.perf_counter()
            workflow_state = self.workflow_runtime.apply_tick(self.current_tick)
            if workflow_state.get("current_period"):
                self.current_phase = workflow_state["current_period"]["name"]
            profile["workflow_configuration_ms"] = self._elapsed_ms(section_started_at)
            profile["workflow_period"] = (
                workflow_state.get("current_period") or {}
            ).get("phase_id")
            profile["active_policy_count"] = len(workflow_state.get("active_interventions") or [])
            profile["workflow_event_count"] = len(workflow_state.get("events_applied_this_tick") or [])

            self.current_operation = "evaluating_owner_project_initiation"
            section_started_at = time.perf_counter()
            self._maybe_generate_projects()
            profile["owner_initiation_ms"] = self._elapsed_ms(section_started_at)

            section_started_at = time.perf_counter()
            active_projects = [
                project
                for project in self.projects.values()
                if project.current_stage not in {ProjectStage.CLOSED, ProjectStage.FAILED, ProjectStage.SUSPENDED}
            ]
            profile["active_project_scan_ms"] = self._elapsed_ms(section_started_at)
            profile["active_project_count"] = len(active_projects)
            profile["project_count_after_generation"] = len(self.projects)

            self.current_operation = "processing_project_lifecycle"
            section_started_at = time.perf_counter()
            lifecycle_project_count = 0
            for project in active_projects:
                lifecycle_project_count += 1
                self.action_applier.apply_project_update(
                    project,
                    self.agents,
                    lambda project=project: self.lifecycle_engine.step(
                        project,
                        self.agents,
                        self.policy,
                        self.macro_environment,
                        self.current_tick,
                    ),
                )
            profile["project_lifecycle_ms"] = self._elapsed_ms(section_started_at)
            profile["lifecycle_project_count"] = lifecycle_project_count

            self.current_operation = "updating_project_state"
            section_started_at = time.perf_counter()
            state_update_project_count = 0
            for project in active_projects:
                if project.current_stage not in {ProjectStage.CLOSED, ProjectStage.FAILED, ProjectStage.SUSPENDED}:
                    state_update_project_count += 1
                    self.action_applier.apply_project_update(
                        project,
                        self.agents,
                        lambda project=project: self.state_update_engine.update(
                            project,
                            self.agents,
                            self.policy,
                            self.macro_environment,
                            self.current_tick,
                        ),
                    )
            profile["project_state_update_ms"] = self._elapsed_ms(section_started_at)
            profile["state_update_project_count"] = state_update_project_count

            self.current_operation = "scheduling_agent_operations"
            section_started_at = time.perf_counter()
            self._run_agent_operations()
            profile["agent_operations_ms"] = self._elapsed_ms(section_started_at)

            self.current_operation = "updating_network_and_metrics"
            section_started_at = time.perf_counter()
            self.network.update(self.projects, self.agents, self.current_tick)
            self.metrics = self.metrics_calculator.calculate(self.projects, self.agents, self.network, self.policy)
            profile["network_metrics_ms"] = self._elapsed_ms(section_started_at)

            self.current_operation = "saving_tick_snapshot"
            section_started_at = time.perf_counter()
            self.result_store.save_tick_result(
                self.current_tick,
                self.projects,
                self.agents,
                self.network,
                self.metrics,
                workflow_runtime=self.workflow_runtime.state(),
            )
            profile["snapshot_save_ms"] = self._elapsed_ms(section_started_at)

            lifecycle_exhausted = all(
                project.current_stage in {ProjectStage.CLOSED, ProjectStage.FAILED, ProjectStage.SUSPENDED}
                for project in self.projects.values()
            )
            generation_exhausted = (not self.enable_project_generation) or len(self.projects) >= self.target_project_count
            if self.current_tick >= self.ticks or (lifecycle_exhausted and generation_exhausted):
                self.status = "completed"
                self.current_phase = "completed"
                self.current_operation = "completed"
            else:
                self.current_operation = "tick_ready"
            profile["status"] = self.status
            profile["current_operation"] = self.current_operation
            profile["total_step_ms"] = self._elapsed_ms(step_started_at)
            self._record_step_profile(profile)
            if return_snapshot:
                section_started_at = time.perf_counter()
                snapshot = self.snapshot()
                profile["return_snapshot_ms"] = self._elapsed_ms(section_started_at)
                profile["total_step_with_return_ms"] = self._elapsed_ms(step_started_at)
                self._record_step_profile(profile)
                return snapshot
            return self._step_summary()
        except Exception:
            failed_operation = self.current_operation
            self.current_tick = previous_tick
            self.current_phase = f"tick_{previous_tick + 1}"
            self.current_operation = f"failed_{failed_operation}"
            self.status = "running"
            profile["status"] = self.status
            profile["current_operation"] = self.current_operation
            profile["failed_operation"] = failed_operation
            profile["rolled_back_to_tick"] = previous_tick
            profile["total_step_ms"] = self._elapsed_ms(step_started_at)
            self._record_step_profile(profile)
            raise

    def run(self, ticks: Optional[int] = None) -> SimulationRunResponse:
        target_ticks = ticks or self.ticks
        while self.current_tick < min(self.ticks, target_ticks) and self.status != "completed":
            self.step(return_snapshot=False)
        if self.current_tick >= self.ticks:
            self.status = "completed"
        return self.response()

    def response(self) -> SimulationRunResponse:
        return SimulationRunResponse(
            simulation_id=self.simulation_id,
            status=self.status,
            current_tick=self.current_tick,
            project_results=[project.dict() for project in self.projects.values()],
            agent_results=[agent.dict() for agent in self.agents.values()],
            network_results=self.network.to_dict(),
            metrics=self.metrics.dict(),
        )

    @property
    def procurement_execution(self) -> ProcurementExecution:
        return self._procurement_execution

    def procurement_state(self) -> Dict:
        configuration = self.procurement_execution.dict()
        canonical = json.dumps(configuration, sort_keys=True, separators=(",", ":"))
        return {
            "simulation_id": self.simulation_id,
            "effective_mode": self.procurement_execution.mode,
            "scope": self.procurement_execution.scope,
            "locked": True,
            "effective_configuration": configuration,
            "configuration_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }

    def summary(self) -> SimulationSummary:
        return SimulationSummary(
            procurement=self.procurement_state(),
            simulation_id=self.simulation_id,
            name=self.name,
            current_tick=self.current_tick,
            ticks=self.ticks,
            project_count=len(self.projects),
            agent_count=len(self.agents),
            status=self.status,
        )

    def snapshot(self) -> Dict:
        return {
            "simulation_id": self.simulation_id,
            "status": self.status,
            "current_tick": self.current_tick,
            "projects": {project_id: project.dict() for project_id, project in self.projects.items()},
            "agents": self._agent_snapshot(),
            "events": [event.dict() for event in self.events.events],
            "metrics": self.metrics.dict(),
            "collaboration_prior": self.collaboration_prior.stats(),
            "camel_queue": self.lifecycle_engine.decision_queue_metrics(),
            "workflow_runtime": self.workflow_runtime.state(),
        }

    def _step_summary(self) -> Dict:
        return {
            "simulation_id": self.simulation_id,
            "status": self.status,
            "current_tick": self.current_tick,
            "current_phase": self.current_phase,
            "current_operation": self.current_operation,
            "camel_queue": self.lifecycle_engine.decision_queue_metrics(),
            "workflow_runtime": self.workflow_runtime.state(),
            "step_profile": self.last_step_profile,
        }

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        return round((time.perf_counter() - started_at) * 1000, 2)

    def _record_step_profile(self, profile: Dict) -> None:
        self.last_step_profile = dict(profile)
        self.step_profile_history.append(dict(profile))
        if len(self.step_profile_history) > 20:
            self.step_profile_history = self.step_profile_history[-20:]

    def project_timeline(self, project_id: str) -> Dict:
        return {
            "project_id": project_id,
            "timeline": [event.dict() for event in self.events.by_project(project_id)],
        }

    def project_performance(self, project_id: str) -> Dict:
        return {
            "project_id": project_id,
            "performance_history": self.result_store.get_project_performance(project_id),
        }

    def agent_engagements(self, agent_id: str) -> Dict:
        engagements = [
            engagement.dict()
            for project in self.projects.values()
            for engagement in project.engagements
            if engagement.agent_id == agent_id
        ]
        return {"agent_id": agent_id, "engagements": engagements}

    def _maybe_generate_projects(self) -> None:
        if not self.enable_project_generation:
            return
        if len(self.projects) >= self.target_project_count:
            return

        active_project_count = sum(
            1
            for project in self.projects.values()
            if project.current_stage not in {ProjectStage.CLOSED, ProjectStage.FAILED, ProjectStage.SUSPENDED}
        )
        if active_project_count >= self.max_active_projects:
            return

        generation_horizon = max(1, min(self.ticks, int(self.ticks * 0.75) or self.ticks))
        target_by_tick = max(1, int((self.target_project_count * self.current_tick + generation_horizon - 1) / generation_horizon))
        backlog = max(0, target_by_tick - len(self.projects))
        per_tick_limit = max(1, min(3, backlog))
        project_slots = min(
            per_tick_limit,
            backlog,
            max(0, self.max_active_projects - active_project_count),
            max(0, self.target_project_count - len(self.projects)),
        )
        if project_slots <= 0:
            return

        opportunities = self.project_generator.generate_candidate_set(
            self.macro_environment,
            count=max(4, project_slots * 2),
        )
        preferred_by_owner: dict[str, tuple[EnterpriseAgentProfile, dict, float, float, dict]] = {}
        evaluated_decisions: list[tuple[EnterpriseAgentProfile, dict, float, float, dict]] = []
        for opportunity in opportunities:
            for owner, decision_score, initiation_probability, decision_factors in self._rank_owner_project_decisions(
                opportunity,
                target_by_tick,
            ):
                evaluation = (owner, opportunity, decision_score, initiation_probability, decision_factors)
                evaluated_decisions.append(evaluation)
                independently_accepted = decision_factors.get("individual_accepted")
                if independently_accepted is None:
                    independently_accepted = self.rng.random() <= initiation_probability
                if not independently_accepted:
                    continue
                current = preferred_by_owner.get(owner.agent_id)
                if current is None or decision_score > current[2]:
                    preferred_by_owner[owner.agent_id] = evaluation

        owner_choices = sorted(
            preferred_by_owner.values(),
            key=lambda item: (item[2], item[0].available_resource(), item[0].agent_id),
            reverse=True,
        )
        if not owner_choices and evaluated_decisions:
            owner, opportunity, decision_score, initiation_probability, decision_factors = max(
                evaluated_decisions,
                key=lambda item: (item[2], item[0].agent_id),
            )
            decision_advisor = {
                "available": decision_factors.get("decision_source") in {
                    "llm_agent",
                    "llm_invalid",
                    "llm_error_deferred",
                    "llm_deferred",
                },
                "action_type": decision_factors.get(
                    "returned_action_type",
                    decision_factors.get("llm_action_type", decision_factors.get("individual_action")),
                ),
                "decision": decision_factors.get(
                    "returned_decision",
                    decision_factors.get("llm_decision", decision_factors.get("individual_accepted")),
                ),
                "reason": decision_factors.get(
                    "returned_reason",
                    decision_factors.get("llm_reason", decision_factors.get("individual_reason")),
                ),
            }
            self.events.record(
                self.current_tick,
                "project_opportunity_declined",
                f"Owner {owner.agent_id} evaluated the published project set but chose not to initiate a project",
                agent_id=owner.agent_id,
                data={
                    "region": opportunity["region"],
                    "project_type": opportunity["project_type"],
                    "project_scale": opportunity.get("scale", "custom"),
                    "budget": opportunity["budget"],
                    "planned_duration": opportunity["planned_duration"],
                    "candidate_opportunity_count": len(opportunities),
                    "decision_score": round(decision_score, 3),
                    "initiation_probability": round(initiation_probability, 3),
                    "decision_factors": decision_factors,
                    "decision_advisor": decision_advisor,
                },
            )
            return

        accepted = 0
        for owner, opportunity, decision_score, initiation_probability, decision_factors in owner_choices:
            if accepted >= project_slots:
                break
            project_id = f"PGEN{self._generated_project_counter + 1:04d}"
            advisor_action = self._owner_initiation_advisor(
                owner,
                project_id,
                opportunity,
                decision_score,
                initiation_probability,
                decision_factors,
            )
            if (
                not advisor_action
                or advisor_action.decision is False
                or advisor_action.action_type != "initiate_project"
            ):
                self.events.record(
                    self.current_tick,
                    "project_opportunity_declined",
                    f"Owner {owner.agent_id} reviewed but did not validly initiate project {project_id}",
                    agent_id=owner.agent_id,
                    data={
                        "region": opportunity["region"],
                        "project_type": opportunity["project_type"],
                        "project_scale": opportunity.get("scale", "custom"),
                        "budget": opportunity["budget"],
                        "planned_duration": opportunity["planned_duration"],
                        "candidate_opportunity_count": len(opportunities),
                        "decision_score": round(decision_score, 3),
                        "initiation_probability": round(initiation_probability, 3),
                        "decision_factors": decision_factors,
                        "decision_advisor": self._advisor_event_data(advisor_action),
                    },
                )
                continue

            def apply_project_creation() -> None:
                self._generated_project_counter += 1
                project = ConstructionProject(
                    project_id=project_id,
                    name=f"{opportunity['name']} {project_id}",
                    project_type=opportunity["project_type"],
                    region=opportunity["region"],
                    owner_id=owner.agent_id,
                    technical_complexity=opportunity["technical_complexity"],
                    initial_budget=opportunity["budget"],
                    performance=ProjectPerformanceState(planned_duration=opportunity["planned_duration"]),
                    flags={
                        "created_tick": self.current_tick,
                        "opportunity": {
                            "region": opportunity["region"],
                            "project_type": opportunity["project_type"],
                            "project_scale": opportunity.get("scale", "custom"),
                            "market_demand_index": self.macro_environment.market_demand_index,
                            "financing_condition_index": self.macro_environment.financing_condition_index,
                        },
                        "owner_decision": {
                            "decision_score": round(decision_score, 3),
                            "initiation_probability": round(initiation_probability, 3),
                            "available_resource": round(owner.available_resource(), 3),
                            "financial_capacity": round(owner.financial_capacity, 3),
                            "payment_reliability": round(owner.payment_reliability, 3),
                            "decision_factors": decision_factors,
                            "candidate_opportunity_count": len(opportunities),
                            "decision_advisor": self._advisor_event_data(advisor_action),
                        },
                    },
                )
                self.projects[project_id] = project
                financing_decision = self._arrange_project_financing(project, owner)
                project.flags["financing_decision"] = financing_decision
                self.events.record(
                    self.current_tick,
                    "project_opportunity_initiated",
                    f"Owner {owner.agent_id} initiated project {project_id} after evaluating market opportunity",
                    project=self.projects[project_id],
                    agent_id=owner.agent_id,
                    data={
                        "owner_id": owner.agent_id,
                        "owner_name": owner.name,
                        "region": opportunity["region"],
                        "project_type": opportunity["project_type"],
                        "project_scale": opportunity.get("scale", "custom"),
                        "budget": opportunity["budget"],
                        "planned_duration": opportunity["planned_duration"],
                        "candidate_opportunity_count": len(opportunities),
                        "decision_score": round(decision_score, 3),
                        "initiation_probability": round(initiation_probability, 3),
                        "decision_factors": decision_factors,
                        "decision_advisor": self._advisor_event_data(advisor_action),
                        "financing_decision": financing_decision,
                    },
                )

            self.action_applier.apply_project_mutation(project_id, [owner.agent_id], apply_project_creation)
            accepted += 1

    def _arrange_project_financing(
        self,
        project: ConstructionProject,
        owner: EnterpriseAgentProfile,
    ) -> dict:
        requested_ratio = max(0.25, min(0.65, 0.65 - 0.35 * owner.financial_capacity))
        requested_amount = project.initial_budget * requested_ratio
        project_risk = max(
            0.0,
            min(
                1.0,
                0.55 * project.technical_complexity
                + 0.25 * self.policy.procedural_uncertainty
                + 0.20 * max(0.0, 1.0 - self.macro_environment.financing_condition_index),
            ),
        )
        bank_candidates = self.lifecycle_engine.agent_pool.visible_candidates(
            self.agents.values(),
            "Bank",
            0.10,
            self.engagement_manager,
            project,
            [owner.agent_id],
            limit=12 if len(self.agents) > 1000 else 24,
        )
        offers = []
        for bank in bank_candidates:
            decision = self.agent_module.propose(
                bank,
                "consider_financing",
                requested_amount=requested_amount,
                borrower_financial_capacity=owner.financial_capacity,
                project_risk=project_risk,
                financing_condition_index=self.macro_environment.financing_condition_index,
            )
            decision = self.agent_registry.resolve_decision(
                bank,
                decision,
                decision_type="bank_project_financing",
                tick=self.current_tick,
                project=project,
                stage_rule=self.stage_rules.get(project.current_stage),
                policy=self.policy,
                macro_environment=self.macro_environment,
                priority=DecisionPriority.P0_STAGE_CRITICAL,
                decision_task=(
                    "Decide independently whether to finance this project using borrower capacity, project and "
                    "regional risk, requested exposure, current financing conditions, portfolio memory, and risk appetite."
                ),
                allowed_actions=["approve_financing", "reject_financing"],
                negative_actions={"reject_financing"},
            )
            offers.append((bank, decision))
            self.events.record(
                self.current_tick,
                "bank_financing_decision",
                f"Bank {bank.agent_id} independently decided whether to finance {project.project_id}",
                project=project,
                agent_id=bank.agent_id,
                data={
                    "owner_id": owner.agent_id,
                    "project_risk": round(project_risk, 4),
                    **decision.to_event_data(),
                },
            )

        owner_decision = self.agent_module.propose(
            owner,
            "select_financing_offer",
            offers=offers,
        )
        owner_decision = self.agent_registry.resolve_decision(
            owner,
            owner_decision,
            decision_type="owner_financing_selection",
            tick=self.current_tick,
            project=project,
            stage_rule=self.stage_rules.get(project.current_stage),
            policy=self.policy,
            macro_environment=self.macro_environment,
            priority=DecisionPriority.P0_STAGE_CRITICAL,
            decision_task=(
                "Choose one accepted bank financing offer or retain owner equity financing, considering rate, "
                "exposure, cash preservation, lender memory, delivery resilience, and the owner's strategy."
            ),
            choice_options=[
                {
                    "id": bank.agent_id,
                    "name": bank.name,
                    "accepted_financing": bool(decision.accepted),
                    "interest_rate": decision.data.get("interest_rate"),
                    "approved_amount": decision.data.get("approved_amount"),
                    "evidence_utility": round(float(decision.utility), 4),
                }
                for bank, decision in offers
                if decision.accepted
            ],
            choice_field="selected_bank_id",
            allowed_actions=["select_project_finance", "self_finance_project"],
        )
        decision_data = {
            "requested_ratio": round(requested_ratio, 4),
            "requested_amount": round(requested_amount, 2),
            "project_risk": round(project_risk, 4),
            **owner_decision.to_event_data(),
        }
        if not owner_decision.accepted:
            # A failed or refused choice must never create an equity/bank
            # commitment. Preserve the project for a later authorized decision.
            decision_data.update(financing_mode="unfinanced", selected_bank_id=None)
            decision_data.pop("selected_offer", None)
            decision_data.pop("accepted_bank_ids", None)
            self.events.record(
                self.current_tick, "project_financing_deferred",
                f"Owner {owner.agent_id} left {project.project_id} unfinanced pending a later decision",
                project=project, agent_id=owner.agent_id, data=decision_data,
            )
            return decision_data
        project.selected_bank_id = owner_decision.data.get("selected_bank_id")
        self.events.record(
            self.current_tick,
            "project_financing_selected",
            (
                f"Owner {owner.agent_id} selected bank financing for {project.project_id}"
                if project.selected_bank_id
                else f"Owner {owner.agent_id} retained {project.project_id} as owner-financed"
            ),
            project=project,
            agent_id=owner.agent_id,
            data=decision_data,
        )
        return decision_data

    def _owner_initiation_advisor(
        self,
        owner: EnterpriseAgentProfile,
        project_id: str,
        opportunity: dict,
        decision_score: float,
        initiation_probability: float,
        decision_factors: dict,
    ):
        if decision_factors.get("decision_source") == "llm_agent":
            return AgentAction(
                action_type="initiate_project",
                project_id=project_id,
                agent_id=owner.agent_id,
                decision=bool(decision_factors.get("individual_accepted")),
                data={
                    "decision_score": decision_score,
                    "initiation_probability": initiation_probability,
                },
                reason=decision_factors.get("individual_reason", "Owner completed its independent LLM decision."),
            )
        candidate_project = ConstructionProject(
            project_id=project_id,
            name=f"{opportunity['name']} {project_id}",
            project_type=opportunity["project_type"],
            region=opportunity["region"],
            owner_id=owner.agent_id,
            technical_complexity=opportunity["technical_complexity"],
            initial_budget=opportunity["budget"],
            performance=ProjectPerformanceState(planned_duration=opportunity["planned_duration"]),
        )
        stage_rule = self.stage_rules.get(ProjectStage.INITIATION)
        advisor_rule_update = {
            "allowed_actions": {"Owner": ["initiate_project"]},
            "exit_conditions": ["owner_decides_to_initiate_or_defer"],
        }
        advisor_stage_rule = (
            stage_rule.model_copy(update=advisor_rule_update)
            if hasattr(stage_rule, "model_copy")
            else stage_rule.copy(update=advisor_rule_update)
        )
        try:
            action = self.lifecycle_engine.decide_now(
                owner,
                {
                    "project": candidate_project,
                    "stage_rule": advisor_stage_rule,
                    "policy": self.policy,
                    "macro_environment": self.macro_environment,
                    "regional_friction": self.macro_environment.regional_friction_matrix.get(owner.region, {}).get(
                        opportunity["region"],
                        self.macro_environment.regional_friction_matrix.get(opportunity["region"], {}).get(owner.region, 0.0),
                    ),
                    "previous_collaboration": 0.5,
                    "tick": self.current_tick,
                    "allowed_actions": ["initiate_project"],
                    "decision_task": (
                        "Decide whether this owner should actively initiate this new project opportunity now. "
                        "Return action_type='initiate_project'. Use decision=true only if the opportunity is "
                        "financially and operationally credible; otherwise use decision=false with a concrete reason."
                    ),
                    "opportunity": opportunity,
                    "owner_decision_score": decision_score,
                    "initiation_probability": initiation_probability,
                    "decision_factors": decision_factors,
                    "generation_pressure": max(
                        0.0,
                        min(1.0, (self.target_project_count - len(self.projects)) / max(self.target_project_count, 1)),
                    ),
                },
                decision_type="owner_initiation",
                priority=DecisionPriority.P0_STAGE_CRITICAL,
                project_id=project_id,
            )
        except Exception as exc:
            raise RuntimeError(
                f"CAMEL owner initiation decision failed for {owner.agent_id} on project {project_id}: {exc}"
            ) from exc
        if not action:
            return None
        if action.agent_id != owner.agent_id or action.project_id != project_id:
            return None
        return action

    @staticmethod
    def _advisor_event_data(action) -> dict:
        if not action:
            return {"available": False}
        return {
            "available": True,
            "action_type": action.action_type,
            "decision": action.decision,
            "reason": action.reason,
            "data": action.data,
        }

    def _rank_owner_project_decisions(
        self,
        opportunity: dict,
        target_by_tick: int,
    ) -> list[tuple[EnterpriseAgentProfile, float, float, dict]]:
        eligible = [
            agent
            for agent in self.agents.values()
            if agent.role == "Owner" and agent.has_available_resource(0.25)
        ]
        if not eligible:
            return []

        # An opportunity is not broadcast to every owner in a large market.
        # Visibility is an information boundary only: every owner that sees it
        # still makes its own LLM decision, and the engine never assigns a winner.
        region = opportunity["region"]
        eligible.sort(
            key=lambda agent: (
                1.0 if agent.region == region else 0.0,
                1.0 if region in (agent.active_regions or []) else 0.0,
                agent.cross_region_experience,
                agent.available_resource(),
                agent.financial_capacity,
                agent.agent_id,
            ),
            reverse=True,
        )
        visibility_limit = 12 if len(self.agents) > 1000 else len(eligible)
        eligible = eligible[:visibility_limit]

        target_pressure = max(0.0, min(1.0, (target_by_tick - len(self.projects)) / max(self.target_project_count, 1)))

        def active_owner_projects(agent: EnterpriseAgentProfile) -> int:
            return sum(
                1
                for project in self.projects.values()
                if project.owner_id == agent.agent_id
                and project.current_stage not in {ProjectStage.CLOSED, ProjectStage.FAILED, ProjectStage.SUSPENDED}
            )

        ranked = []
        for agent in eligible:
            decision = self.agent_module.propose(
                agent,
                "evaluate_project_opportunity",
                opportunity=opportunity,
                macro_environment=self.macro_environment,
                policy=self.policy,
                active_project_count=active_owner_projects(agent),
                target_pressure=target_pressure,
            )
            candidate_project = ConstructionProject(
                project_id=(
                    f"OPPORTUNITY-{self.current_tick}-{agent.agent_id}-"
                    f"{opportunity['region']}-{opportunity['project_type']}-{int(opportunity['budget'])}"
                ),
                name=opportunity["name"],
                project_type=opportunity["project_type"],
                region=opportunity["region"],
                owner_id=agent.agent_id,
                technical_complexity=opportunity["technical_complexity"],
                initial_budget=opportunity["budget"],
                performance=ProjectPerformanceState(planned_duration=opportunity["planned_duration"]),
            )
            decision = self.agent_registry.resolve_decision(
                agent,
                decision,
                decision_type="owner_project_opportunity",
                tick=self.current_tick,
                project=candidate_project,
                stage_rule=self.stage_rules.get(ProjectStage.INITIATION),
                policy=self.policy,
                macro_environment=self.macro_environment,
                priority=DecisionPriority.P1_RESOURCE_CASHFLOW,
                decision_task=(
                    "Decide whether to initiate this specific project concept now. Consider location, project type, "
                    "scale, capital, portfolio load, financing, market demand, policy risk, organizational memory, "
                    "and the owner's own investment strategy."
                ),
                allowed_actions=["initiate_project", "defer_project"],
                negative_actions={"defer_project"},
            )
            decision_factors = {
                **decision.factors,
                "individual_action": decision.action_type,
                "individual_accepted": decision.accepted,
                "individual_reason": decision.reason,
            }
            ranked.append((agent, decision.utility, decision.probability, decision_factors))
        return sorted(ranked, key=lambda item: (item[1], item[0].available_resource(), item[0].agent_id), reverse=True)

    @staticmethod
    def _default_project_generation_target(agent_count: int, ticks: int) -> int:
        horizon_scaled = max(4, int(ticks * 0.85))
        if agent_count > 1000:
            agent_scaled = max(12, agent_count // 25)
            return max(12, min(90, agent_scaled, horizon_scaled))
        if agent_count > 100:
            return max(8, min(45, agent_count // 25, horizon_scaled))
        return max(2, min(10, ticks // 6 + 1))

    @staticmethod
    def _default_max_active_projects(target_project_count: int) -> int:
        return max(8, min(32, int(target_project_count * 0.75) + 4))

    def _run_agent_operations(self) -> None:
        aggregate_operations = len(self.agents) > 1000
        operation_counts: dict[str, int] = {}
        role_counts: dict[str, int] = {}
        if aggregate_operations:
            self._run_aggregated_agent_operations(operation_counts, role_counts)
            return
        for agent in self.agents.values():
            if not agent.has_available_resource(0.05):
                continue
            operation = self.agent_operation_scheduler.step(agent, self.macro_environment)
            operation_name = operation.get("operation")
            if operation_name == "fully_allocated":
                continue
            if aggregate_operations:
                operation_counts[operation_name] = operation_counts.get(operation_name, 0) + 1
                role_counts[agent.role] = role_counts.get(agent.role, 0) + 1
            else:
                self.events.record(
                    self.current_tick,
                    "agent_operation",
                    operation.get("description") or f"{agent.role} {agent.agent_id} performed {operation_name}",
                    agent_id=agent.agent_id,
                    data=operation,
                )
        if aggregate_operations and operation_counts:
            self.events.record(
                self.current_tick,
                "agent_operations_aggregated",
                "Free enterprise operations aggregated for large database-backed simulation",
                data={
                    "operation_counts": operation_counts,
                    "role_counts": role_counts,
                    "agent_count": len(self.agents),
                },
            )

    def _run_aggregated_agent_operations(
        self,
        operation_counts: dict[str, int],
        role_counts: dict[str, int],
    ) -> None:
        for agent in self.agents.values():
            if not agent.has_available_resource(0.05):
                continue
            operation_name = "awaiting_decision_event"
            operation_counts[operation_name] = operation_counts.get(operation_name, 0) + 1
            role_counts[agent.role] = role_counts.get(agent.role, 0) + 1
        if operation_counts:
            self.events.record(
                self.current_tick,
                "agent_operations_aggregated",
                "Inactive enterprises retained their individual state until a decision event was triggered",
                data={
                    "operation_counts": operation_counts,
                    "role_counts": role_counts,
                    "agent_count": len(self.agents),
                    "decision_mode": "event_driven_llm",
                    "llm_calls": 0,
                },
            )

    def _agent_snapshot(self) -> Dict:
        if len(self.agents) <= 1000:
            return {agent_id: agent.dict() for agent_id, agent in self.agents.items()}
        active_agent_ids = {
            engagement.agent_id
            for project in self.projects.values()
            for engagement in project.engagements
        }
        return {
            "summary": {
                "agent_count": len(self.agents),
                "active_or_engaged_agent_count": len(active_agent_ids),
            },
            "active_agents": {
                agent_id: agent.dict()
                for agent_id, agent in self.agents.items()
                if agent_id in active_agent_ids
            },
        }

    @staticmethod
    def _operation_for_role(role: str) -> str:
        return {
            "Owner": "evaluate_market_demand",
            "Architect": "build_cross_region_reputation",
            "Engineer": "review_technical_standards",
            "QS": "update_cost_database",
            "Contractor": "scan_tender_opportunities",
            "Supplier": "adjust_inventory",
            "Government": "publish_guidelines",
            "Bank": "review_credit_pipeline",
        }.get(role, "maintain_operations")


def agents_from_request(request: SimulationCreateRequest) -> list[EnterpriseAgentProfile]:
    if request.agent_source.lower() == "explicit":
        # The caller supplies all participants, including any scenario regulators.
        # Do not inject demonstration competitors into a shared candidate pool.
        return list(request.agents)
    if request.agents:
        return ensure_mvp_support_agents(request.agents)
    if request.agent_source.lower() == "database":
        agents = agent_database.list_agent_profiles(
            roles=request.agent_roles or None,
            regions=request.agent_regions or None,
            source_types=request.agent_source_types or None,
            limit=request.agent_count,
            random_seed=request.random_seed,
        )
        return ensure_mvp_support_agents(agents, regulator_regions=GBA_REGULATOR_CITIES)
    return default_agents()


def ensure_mvp_support_agents(
    agents: list[EnterpriseAgentProfile],
    regulator_regions: Optional[list[str]] = None,
) -> list[EnterpriseAgentProfile]:
    existing_roles = {agent.role for agent in agents}
    support_agents = {
        "Owner": default_agents()[0],
        "Architect": default_agents()[1],
        "QS": default_agents()[2],
        "Contractor": default_agents()[3],
        "Supplier": default_agents()[6],
    }
    if not regulator_regions:
        support_agents["Government"] = default_agents()[7]
    merged = list(agents)
    for role, support_agent in support_agents.items():
        if role not in existing_roles:
            if hasattr(support_agent, "model_copy"):
                merged.append(support_agent.model_copy(deep=True))
            else:
                merged.append(support_agent.copy(deep=True))
    if regulator_regions:
        existing_government_regions = {agent.region for agent in merged if agent.role == "Government"}
        for city in regulator_regions:
            if city not in existing_government_regions:
                merged.append(_city_regulator_agent(city))
    return merged


def _city_regulator_agent(city: str) -> EnterpriseAgentProfile:
    slug = city.upper().replace(" ", "_")
    return EnterpriseAgentProfile(
        agent_id=f"GOV_{slug}",
        name=f"{city} Construction Approval Office",
        role="Government",
        region=city,
        enterprise_type="city_construction_regulator",
        qualification_level=1.0,
        financial_capacity=0.7,
        technical_capability=0.65,
        management_capability=0.75,
        risk_preference=0.25,
        collaboration_preference=0.55,
        cross_region_experience=0.55 if city in {"Hong Kong", "Macau", "Shenzhen", "Guangzhou"} else 0.45,
        policy_adaptability=0.85,
        supervision_capability=0.9,
        decision_speed=0.65,
        total_resource_capacity=1.0,
        active_regions=[city],
        semantic_memory={
            "agent_type": "support_regulator",
            "is_synthetic": False,
            "approval_scope": city,
            "notes": f"City-level construction approval and compliance actor for {city}.",
        },
    )


def default_agents() -> list[EnterpriseAgentProfile]:
    return [
        EnterpriseAgentProfile(
            agent_id="O001",
            name="Shenzhen Bay Owner",
            role="Owner",
            region="Shenzhen",
            enterprise_type="developer",
            financial_capacity=0.85,
            payment_reliability=0.82,
            decision_speed=0.78,
            management_capability=0.70,
        ),
        EnterpriseAgentProfile(
            agent_id="A001",
            name="GBA Design Studio",
            role="Architect",
            region="Guangzhou",
            enterprise_type="consultant",
            design_capability=0.84,
            technical_capability=0.75,
            cross_region_experience=0.70,
            management_capability=0.68,
            collaboration_preference=0.75,
        ),
        EnterpriseAgentProfile(
            agent_id="Q001",
            name="Pearl QS Consulting",
            role="QS",
            region="Hong Kong",
            enterprise_type="consultant",
            cost_estimation_capability=0.82,
            management_capability=0.72,
            cross_region_experience=0.75,
        ),
        EnterpriseAgentProfile(
            agent_id="C001",
            name="Guangdong Contractor A",
            role="Contractor",
            region="Guangzhou",
            enterprise_type="contractor",
            construction_capability=0.76,
            quality_management_capability=0.72,
            safety_management_capability=0.70,
            financial_capacity=0.70,
            management_capability=0.72,
            risk_preference=0.58,
        ),
        EnterpriseAgentProfile(
            agent_id="C002",
            name="Hong Kong Contractor B",
            role="Contractor",
            region="Hong Kong",
            enterprise_type="contractor",
            construction_capability=0.80,
            quality_management_capability=0.78,
            safety_management_capability=0.82,
            financial_capacity=0.74,
            management_capability=0.76,
            cross_region_experience=0.82,
            risk_preference=0.62,
        ),
        EnterpriseAgentProfile(
            agent_id="C003",
            name="Shenzhen Contractor C",
            role="Contractor",
            region="Shenzhen",
            enterprise_type="contractor",
            construction_capability=0.74,
            quality_management_capability=0.76,
            safety_management_capability=0.78,
            financial_capacity=0.78,
            management_capability=0.74,
            risk_preference=0.68,
        ),
        EnterpriseAgentProfile(
            agent_id="S001",
            name="Foshan Supplier",
            role="Supplier",
            region="Foshan",
            enterprise_type="supplier",
            supply_reliability=0.82,
            material_quality=0.78,
            management_capability=0.65,
        ),
        EnterpriseAgentProfile(
            agent_id="G001",
            name="GBA Regulator",
            role="Government",
            region="Shenzhen",
            enterprise_type="government",
            policy_adaptability=0.80,
            management_capability=0.70,
        ),
        EnterpriseAgentProfile(
            agent_id="E001",
            name="GBA Building Engineering",
            role="Engineer",
            region="Shenzhen",
            enterprise_type="engineering_consultant",
            technical_capability=0.82,
            supervision_capability=0.78,
            management_capability=0.68,
            cross_region_experience=0.70,
            collaboration_preference=0.72,
        ),
        EnterpriseAgentProfile(
            agent_id="B001",
            name="GBA Project Finance Bank",
            role="Bank",
            region="Hong Kong",
            enterprise_type="financial_institution",
            financial_capacity=0.88,
            management_capability=0.76,
            risk_preference=0.48,
            decision_speed=0.70,
            cross_region_experience=0.82,
            policy_adaptability=0.74,
        ),
    ]


def default_projects_for_agents(agents: list[EnterpriseAgentProfile]) -> list[ConstructionProject]:
    owner = next((agent for agent in agents if agent.role == "Owner"), default_agents()[0])
    return default_projects(owner.agent_id, owner.region or "Shenzhen")


def default_projects(owner_id: str = "O001", region: str = "Shenzhen") -> list[ConstructionProject]:
    return [
        ConstructionProject(
            project_id="P001",
            name="GBA baseline building project",
            project_type="building",
            region=region,
            owner_id=owner_id,
            technical_complexity=0.52,
            initial_budget=120_000_000,
            performance=ProjectPerformanceState(planned_duration=10),
        )
    ]
