from copy import deepcopy
import os
from typing import Dict, Optional

from gba_construction_sim.backend.decision.camel_provider import CamelDecisionProvider
from gba_construction_sim.backend.decision.rule_based_provider import RuleBasedDecisionProvider
from gba_construction_sim.backend.models.frontend_dto import SimulationWorkflowDTO
from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
from gba_construction_sim.backend.models.procurement import require_available
from gba_construction_sim.backend.services.cluster_service import cluster_service
from gba_construction_sim.backend.services.mock_catalog import WORKFLOW
from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine
from gba_construction_sim.backend.simulation.workflow_runtime import normalize_workflow_configuration
from gba_construction_sim.backend.storage.repositories import simulation_repository


class WorkflowService:
    def __init__(self) -> None:
        self._items: Dict[str, Dict] = {
            WORKFLOW["workflow_id"]: normalize_workflow_configuration(WORKFLOW)
        }
        self._saved_template = deepcopy(self._items[WORKFLOW["workflow_id"]])
        # Optional external procurement composition; native deployments need none.
        self.procurement_run_handler = None

    def list_workflows(self) -> list[Dict]:
        return [SimulationWorkflowDTO(**workflow).dict() for workflow in self._items.values()]

    def get_workflow(self, workflow_id: str) -> Dict:
        workflow = self._items.get(workflow_id, self._items[WORKFLOW["workflow_id"]])
        return SimulationWorkflowDTO(**normalize_workflow_configuration(workflow)).dict()

    def create_workflow(self, payload: Dict) -> Dict:
        workflow = deepcopy(WORKFLOW)
        workflow.update(payload)
        workflow.setdefault("workflow_id", f"WF{len(self._items) + 1:03d}")
        workflow = normalize_workflow_configuration(workflow)
        self._items[workflow["workflow_id"]] = workflow
        return SimulationWorkflowDTO(**workflow).dict()

    def update_workflow(self, workflow_id: str, payload: Dict) -> Dict:
        workflow = deepcopy(self._items.get(workflow_id, WORKFLOW))
        if isinstance(payload.get("configuration"), dict):
            payload = {
                **payload,
                "configuration": {
                    **(workflow.get("configuration") or {}),
                    **payload["configuration"],
                },
            }
        workflow.update(payload)
        workflow["workflow_id"] = workflow_id
        workflow = normalize_workflow_configuration(workflow)
        self._items[workflow_id] = workflow
        return SimulationWorkflowDTO(**workflow).dict()

    def validate_workflow(self, workflow_id: str) -> Dict:
        workflow = self.get_workflow(workflow_id)
        errors = []
        warnings = []
        if not workflow["selected_cluster_id"]:
            errors.append("selected_cluster_id is required")
        if not workflow["interventions"]:
            warnings.append("No policy intervention is configured.")
        if workflow["horizon_years"] <= 0:
            errors.append("horizon_years must be positive")
        return {"valid": not errors, "warnings": warnings, "errors": errors}

    def save_template(self, workflow_id: str) -> Dict:
        # This service, like simulations, is in-memory. Do not imply disk persistence.
        self._saved_template = deepcopy(self.get_workflow(workflow_id))
        return {"workflow_id": workflow_id, "template_saved": True}

    def load_template(self) -> Dict:
        return deepcopy(self._saved_template)

    def run_workflow(self, workflow_id: str, payload: Optional[Dict] = None) -> Dict:
        workflow = self.get_workflow(workflow_id)
        payload = payload or {}
        runtime_workflow = deepcopy(workflow)
        if isinstance(payload.get("workflow_configuration"), dict):
            runtime_workflow.update(payload["workflow_configuration"])
        runtime_configuration = deepcopy(runtime_workflow.get("configuration") or {})
        for key, configuration_key in (
            ("phases", "periods"),
            ("interventions", "policies"),
            ("events", "events"),
        ):
            if key not in payload:
                continue
            schedule_rows = deepcopy(payload.get(key) or [])
            runtime_workflow[key] = schedule_rows
            # The explicit run payload is the final user-confirmed schedule.
            # Keep the nested representation in sync so normalization cannot
            # revive an older saved schedule.
            runtime_configuration[configuration_key] = deepcopy(schedule_rows)
        runtime_workflow["configuration"] = runtime_configuration
        timeline_items = payload.get("timeline_items")
        if timeline_items is not None:
            runtime_workflow.setdefault("execution_logic", {})
            runtime_workflow["execution_logic"] = {
                **(runtime_workflow.get("execution_logic") or {}),
                "timeline_items": timeline_items,
                "item_count": len(timeline_items),
            }
        runtime_workflow = normalize_workflow_configuration(runtime_workflow)
        ticks = int(payload.get("ticks") or max(1, int(workflow["horizon_years"]) * 12))
        runtime_workflow["horizon_years"] = max(1, round(ticks / 12))
        runtime_workflow.setdefault("execution_logic", {})
        runtime_workflow["execution_logic"] = {
            **(runtime_workflow.get("execution_logic") or {}),
            "total_ticks": ticks,
        }
        configuration = runtime_workflow.get("configuration") or {}
        # Resolve and validate before cluster/database loading or provider setup.
        procurement = SimulationCreateRequest(**{
            "workflow_configuration": runtime_workflow,
            **({"shared_input": payload["shared_input"]} if "shared_input" in payload else {}),
            **({"procurement_execution": payload["procurement_execution"]}
               if "procurement_execution" in payload else {}),
        }).procurement_execution
        if procurement.mode == "codedemo_micro" and self.procurement_run_handler is not None:
            return self.procurement_run_handler(workflow_id, payload, runtime_workflow, ticks)
        require_available(procurement)
        runtime_workflow.setdefault("configuration", {})["procurement_execution"] = procurement.dict()
        selected_cluster_id = str(
            payload.get("selected_cluster_id")
            or runtime_workflow.get("selected_cluster_id")
            or ""
        )
        cluster_runtime: Dict = {}
        if selected_cluster_id:
            try:
                cluster_runtime = cluster_service.use_in_simulation(selected_cluster_id)
            except (KeyError, IndexError, ValueError):
                cluster_runtime = {}
        recommended_run = cluster_runtime.get("recommended_run") or {}
        agent_source = str(
            payload.get("agent_source")
            or configuration.get("agent_source")
            or cluster_runtime.get("agent_source")
            or "database"
        )
        enable_generation = payload.get("enable_project_generation")
        if enable_generation is None:
            enable_generation = configuration.get("enable_project_generation")
        if enable_generation is None:
            enable_generation = recommended_run.get("enable_project_generation")
        if enable_generation is None:
            enable_generation = agent_source.lower() == "database"
        agent_count_value = (
            payload.get("agent_count")
            or configuration.get("agent_count")
            or cluster_runtime.get("agent_count")
            or 6000
        )
        agent_regions = (
            payload.get("agent_regions")
            or configuration.get("agent_regions")
            or cluster_runtime.get("region_scope")
            or []
        )
        agent_source_types = (
            payload.get("agent_source_types")
            or configuration.get("agent_source_types")
            or cluster_runtime.get("agent_source_types")
            or []
        )
        max_tender_invites = int(
            payload.get("max_tender_invites")
            or configuration.get("max_tender_invites")
            or recommended_run.get("max_tender_invites")
            or 40
        )
        use_prior_network_edges = payload.get("use_prior_network_edges")
        if use_prior_network_edges is None:
            use_prior_network_edges = configuration.get("use_prior_network_edges")
        if use_prior_network_edges is None:
            use_prior_network_edges = recommended_run.get("use_prior_network_edges", True)
        request = SimulationCreateRequest(
            procurement_execution=procurement,
            agents=payload.get("agents", configuration.get("agents", [])),
            initial_projects=payload.get("initial_projects", configuration.get("initial_projects", [])),
            name=f"{workflow['name']} run",
            ticks=ticks,
            random_seed=int(payload.get("random_seed", 42)),
            policy=payload.get("policy") or configuration.get("policy") or {},
            macro_environment=payload.get("macro_environment") or configuration.get("macro_environment") or {},
            enable_project_generation=bool(enable_generation),
            agent_source=agent_source,
            agent_count=int(agent_count_value) if agent_count_value else None,
            agent_roles=payload.get("agent_roles") or configuration.get("agent_roles") or [],
            agent_regions=agent_regions,
            agent_source_types=agent_source_types,
            max_tender_invites=max_tender_invites,
            use_prior_network_edges=bool(use_prior_network_edges),
            target_project_count=int(payload["target_project_count"]) if payload.get("target_project_count") else None,
            max_active_projects=int(payload["max_active_projects"]) if payload.get("max_active_projects") else None,
            workflow_configuration=runtime_workflow,
        )
        engine = SimulationEngine.from_request(request)
        self._configure_runtime_decision_provider(engine, payload)
        simulation_repository.add(engine)
        regulator_count = sum(1 for agent in engine.agents.values() if agent.role == "Government")
        enterprise_agent_count = len(engine.agents) - regulator_count
        return {
            "simulation_id": engine.simulation_id,
            "procurement": engine.procurement_state(),
            "workflow_id": workflow_id,
            "status": "created",
            "agent_count": enterprise_agent_count,
            "enterprise_agent_count": enterprise_agent_count,
            "support_regulator_count": regulator_count,
            "total_agent_count": len(engine.agents),
            "project_count": len(engine.projects),
            "prior_edge_count": engine.collaboration_prior.edge_count,
            "current_tick": engine.current_tick,
            "total_ticks": engine.ticks,
            "live_mode": True,
            "configuration_summary": {
                "selected_cluster_id": selected_cluster_id,
                "agent_source": agent_source,
                "agent_regions": list(agent_regions),
                "agent_source_types": list(agent_source_types),
                "requested_agent_count": int(agent_count_value) if agent_count_value else None,
                "max_tender_invites": max_tender_invites,
                "use_prior_network_edges": bool(use_prior_network_edges),
                "period_count": len(runtime_workflow.get("phases") or []),
                "policy_count": len(runtime_workflow.get("interventions") or []),
                "event_count": len(runtime_workflow.get("events") or []),
            },
            "workflow_runtime": engine.workflow_runtime.state(),
            "message": "Simulation created. Use runtime step, seek, or play endpoints to run it live.",
        }

    def _configure_runtime_decision_provider(self, engine: SimulationEngine, payload: Dict) -> None:
        if self._strict_camel_requested(payload):
            return
        engine.lifecycle_engine.decision_provider = CamelDecisionProvider(
            strict=False,
            fallback=RuleBasedDecisionProvider(),
        )

    @staticmethod
    def _strict_camel_requested(payload: Dict) -> bool:
        for key in ("camel_strict", "decision_strict", "strict_camel"):
            if key in payload:
                value = payload.get(key)
                if isinstance(value, bool):
                    return value
                return str(value).lower() in {"1", "true", "yes", "on"}
        configured = os.getenv("CAMEL_DECISION_STRICT")
        if configured is not None:
            return configured.lower() not in {"0", "false", "no", "off"}
        return False


workflow_service = WorkflowService()
