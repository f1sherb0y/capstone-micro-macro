import time
from datetime import date, datetime, timedelta
from threading import RLock
from typing import Dict, Optional

from gba_construction_sim.backend.core.enums import EngagementStatus, ProjectStage
from gba_construction_sim.backend.decision.camel_provider import CamelDecisionError
from gba_construction_sim.backend.models.frontend_dto import SimulationRuntimeStateDTO
from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
from gba_construction_sim.backend.services.camel_queue_metrics_service import camel_queue_metrics_service
from gba_construction_sim.backend.services.mock_catalog import CITY_COORDS
from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine
from gba_construction_sim.backend.storage.repositories import simulation_repository


ROLE_MAP = {
    "Owner": "developer",
    "Architect": "consultant",
    "Engineer": "consultant",
    "QS": "consultant",
    "Contractor": "contractor",
    "Supplier": "supplier",
    "Government": "government",
}

VISIBLE_ENTERPRISE_LIMIT = 550
ROLE_CLASS_ORDER = ["developer", "contractor", "supplier", "consultant", "government"]
DEFAULT_CITY_ROLE_MIX = {
    "developer": 0.08,
    "contractor": 0.48,
    "supplier": 0.18,
    "consultant": 0.22,
    "government": 0.04,
}
CITY_ROLE_MIX = {
    "Guangzhou": {"developer": 0.10, "contractor": 0.38, "supplier": 0.15, "consultant": 0.33, "government": 0.04},
    "Shenzhen": {"developer": 0.16, "contractor": 0.34, "supplier": 0.14, "consultant": 0.32, "government": 0.04},
    "Hong Kong": {"developer": 0.12, "contractor": 0.26, "supplier": 0.10, "consultant": 0.48, "government": 0.04},
    "Macau": {"developer": 0.12, "contractor": 0.30, "supplier": 0.18, "consultant": 0.36, "government": 0.04},
    "Foshan": {"developer": 0.06, "contractor": 0.46, "supplier": 0.28, "consultant": 0.17, "government": 0.03},
    "Dongguan": {"developer": 0.06, "contractor": 0.44, "supplier": 0.30, "consultant": 0.17, "government": 0.03},
    "Zhongshan": {"developer": 0.06, "contractor": 0.46, "supplier": 0.24, "consultant": 0.21, "government": 0.03},
    "Jiangmen": {"developer": 0.06, "contractor": 0.48, "supplier": 0.22, "consultant": 0.21, "government": 0.03},
    "Zhaoqing": {"developer": 0.06, "contractor": 0.50, "supplier": 0.20, "consultant": 0.21, "government": 0.03},
    "Huizhou": {"developer": 0.06, "contractor": 0.44, "supplier": 0.24, "consultant": 0.26, "government": 0.04},
    "Zhuhai": {"developer": 0.10, "contractor": 0.36, "supplier": 0.20, "consultant": 0.30, "government": 0.04},
}


class SimulationRuntimeService:
    def __init__(self) -> None:
        self._engine_locks: dict[str, RLock] = {}
        self._engine_locks_guard = RLock()

    def _lock_for(self, simulation_id: str) -> RLock:
        with self._engine_locks_guard:
            lock = self._engine_locks.get(simulation_id)
            if lock is None:
                lock = RLock()
                self._engine_locks[simulation_id] = lock
            return lock

    def get_engine(self, simulation_id: str) -> SimulationEngine:
        return simulation_repository.get(simulation_id)

    def ensure_demo_simulation(self) -> SimulationEngine:
        existing = simulation_repository.all()
        if existing:
            return existing[-1]
        engine = SimulationEngine.from_request(
            SimulationCreateRequest(
                name="GBA demo runtime simulation",
                ticks=60,
                random_seed=42,
                enable_project_generation=False,
            )
        )
        simulation_repository.add(engine)
        engine.run()
        return engine

    def runtime_state(self, simulation_id: str, tick: Optional[int] = None) -> Dict:
        engine = self.get_engine(simulation_id)
        requested_tick = int(tick) if tick is not None else engine.current_tick
        target_tick = min(max(requested_tick, 0), engine.ticks)
        started_from_tick = engine.current_tick
        started_at = time.perf_counter()
        performance_profile: Dict = {
            "requested_tick": target_tick,
            "started_from_tick": started_from_tick,
            "ticks_generated": 0,
            "generation_loop_ms": 0.0,
        }
        warnings: list[str] = []
        error: Optional[str] = None
        generation_loop_started_at = time.perf_counter()
        if tick is not None:
            if target_tick > engine.current_tick:
                with self._lock_for(simulation_id):
                    engine = self.get_engine(simulation_id)
                    while engine.current_tick < target_tick:
                        before_tick = engine.current_tick
                        try:
                            engine.current_operation = "generating_requested_tick"
                            engine.step(return_snapshot=False)
                            engine.last_progress_at = datetime.utcnow().isoformat() + "Z"
                        except Exception as exc:
                            error = str(exc)
                            engine.last_generation_error = error
                            engine.last_progress_at = datetime.utcnow().isoformat() + "Z"
                            if self._is_recoverable_generation_error(exc):
                                warnings.append(
                                    f"Generation paused at tick {engine.current_tick} while requesting tick {target_tick}: {error}"
                                )
                                break
                            raise
                        if engine.current_tick <= before_tick:
                            warnings.append(
                                f"Simulation did not advance while requesting tick {target_tick}."
                            )
                            break
                        performance_profile["ticks_generated"] += max(0, engine.current_tick - before_tick)
        performance_profile["generation_loop_ms"] = round((time.perf_counter() - generation_loop_started_at) * 1000, 2)
        effective_tick = self._effective_tick(engine, tick)
        section_started_at = time.perf_counter()
        snapshot = self._snapshot_for_tick(engine, effective_tick)
        performance_profile["snapshot_lookup_ms"] = round((time.perf_counter() - section_started_at) * 1000, 2)
        section_started_at = time.perf_counter()
        map_data = self.map_data(simulation_id, effective_tick, snapshot_override=snapshot)
        performance_profile["map_build_ms"] = round((time.perf_counter() - section_started_at) * 1000, 2)
        section_started_at = time.perf_counter()
        collaboration_links = map_data["collaboration_links"]
        resource_flows = map_data["resource_flows"]
        cross_city_links = len([link for link in collaboration_links if link["cross_city"]])
        runtime_links = len(collaboration_links) + len(resource_flows)
        project_rows = self._snapshot_project_rows(snapshot) if snapshot else list(engine.projects.values())
        total_project_count = len(engine.projects)
        active_projects = len(
            [
                project
                for project in project_rows
                if self._project_stage_value(project) not in {ProjectStage.CLOSED.value, ProjectStage.FAILED.value, ProjectStage.SUSPENDED.value}
            ]
        )
        visible_projects = len(project_rows)
        # Runtime dashboards need a stable "projects in view" count even when the
        # selected playback tick is after final account and the lifecycle stage is
        # already closed. Keep the lifecycle-completed count separate below.
        active_project_kpi = active_projects or visible_projects
        completed_projects = len([project for project in project_rows if self._project_stage_value(project) == ProjectStage.CLOSED.value])
        firms, all_engaged_firms = self._engaged_agent_sets(project_rows)
        engaged_count = len(firms) or len(all_engaged_firms)
        resource_flow_score = self._resource_flow_score(resource_flows, project_rows)
        performance_profile["kpi_build_ms"] = round((time.perf_counter() - section_started_at) * 1000, 2)
        runtime_status = self._runtime_status(engine.status)
        if error:
            runtime_status = "blocked"
        if runtime_status == "completed" and engine.current_tick < engine.ticks:
            runtime_status = "running"
        if effective_tick < engine.current_tick:
            runtime_status = "running"
        if error is None:
            engine.last_generation_error = None
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        performance_profile["request_total_ms"] = elapsed_ms
        performance_profile["generated_until_tick"] = engine.current_tick
        performance_profile["effective_tick"] = effective_tick
        performance_profile["last_step_profile"] = getattr(engine, "last_step_profile", {})
        performance_profile["recent_step_profiles"] = list(getattr(engine, "step_profile_history", [])[-5:])
        generation_state = self.generation_status(
            simulation_id,
            requested_tick=target_tick,
            elapsed_ms=elapsed_ms,
            started_from_tick=started_from_tick,
            warnings=warnings,
            error=error,
            performance_profile=performance_profile,
        )
        camel_queue = camel_queue_metrics_service.snapshot()
        section_started_at = time.perf_counter()
        interaction_session_summary = self._runtime_interaction_session_summary(map_data.get("projects", []))
        performance_profile["interaction_summary_ms"] = round((time.perf_counter() - section_started_at) * 1000, 2)
        workflow_runtime = (
            snapshot.get("workflow_runtime", {})
            if snapshot
            else engine.workflow_runtime.state()
        )
        generation_state["performance"] = performance_profile
        generation_state["workflow_runtime"] = workflow_runtime
        state = {
            "simulation_id": simulation_id,
            "current_tick": effective_tick,
            "total_ticks": engine.ticks,
            "generated_until_tick": engine.current_tick,
            "requested_tick": target_tick,
            "progress_percent": generation_state["progress_percent"],
            "elapsed_ms": elapsed_ms,
            "last_progress_at": generation_state["last_progress_at"],
            "current_phase": generation_state["current_phase"],
            "current_operation": generation_state["current_operation"],
            "warnings": warnings,
            "error": error,
            "is_stalled": generation_state["is_stalled"],
            "generation_state": generation_state,
            "camel_queue": camel_queue,
            "interaction_session_summary": interaction_session_summary,
            "workflow_runtime": workflow_runtime,
            "current_date": (date(2025, 5, 1) + timedelta(days=30 * effective_tick)).isoformat(),
            "status": runtime_status,
            "kpis": {
                "active_projects": active_project_kpi,
                "active_projects_change_pct": 12,
                "project_count": len(project_rows),
                "snapshot_project_count": len(project_rows),
                "total_projects": total_project_count,
                "completed_projects": completed_projects,
                "runtime_links": runtime_links,
                "collaboration_links": len(collaboration_links),
                "resource_flows": len(resource_flows),
                "cross_city_links": cross_city_links,
                "cross_city_links_change_pct": 18,
                "firms_engaged": engaged_count,
                "firms_engaged_change_pct": 15,
                "resource_flow_index": resource_flow_score["index"],
                "resource_flow_components": resource_flow_score["components"],
                "resource_flow_volume": resource_flow_score["flow_volume"],
                "resource_flow_index_change_pct": 9,
            },
            "map": map_data,
        }
        return SimulationRuntimeStateDTO(**state).dict()

    def generation_status(
        self,
        simulation_id: str,
        requested_tick: Optional[int] = None,
        elapsed_ms: int = 0,
        started_from_tick: Optional[int] = None,
        warnings: Optional[list[str]] = None,
        error: Optional[str] = None,
        performance_profile: Optional[Dict] = None,
    ) -> Dict:
        engine = self.get_engine(simulation_id)
        target_tick = engine.current_tick if requested_tick is None else min(max(int(requested_tick), 0), engine.ticks)
        generated_until_tick = engine.current_tick
        request_span = max(1, target_tick - (started_from_tick if started_from_tick is not None else 0))
        request_progress = 100.0 if generated_until_tick >= target_tick else max(
            0.0,
            min(100.0, ((generated_until_tick - (started_from_tick or 0)) / request_span) * 100.0),
        )
        total_progress = 100.0 if engine.ticks <= 0 else min(100.0, (generated_until_tick / engine.ticks) * 100.0)
        last_progress_at = getattr(engine, "last_progress_at", None)
        is_stalled = bool(target_tick > generated_until_tick and elapsed_ms >= 30000)
        last_error = error or getattr(engine, "last_generation_error", None)
        camel_queue = camel_queue_metrics_service.snapshot()
        return {
            "status": "blocked" if last_error else self._runtime_status(engine.status),
            "requested_tick": target_tick,
            "generated_until_tick": generated_until_tick,
            "current_tick": engine.current_tick,
            "current_phase": getattr(engine, "current_phase", ""),
            "current_operation": getattr(engine, "current_operation", ""),
            "progress_percent": round(total_progress, 1),
            "request_progress_percent": round(request_progress, 1),
            "elapsed_ms": elapsed_ms,
            "last_progress_at": last_progress_at,
            "warnings": warnings or [],
            "error": last_error,
            "is_stalled": is_stalled,
            "camel_queue": camel_queue,
            "performance": performance_profile or {},
            "workflow_runtime": engine.workflow_runtime.state(),
        }

    def map_data(self, simulation_id: str, tick: Optional[int] = None, snapshot_override: Optional[Dict] = None) -> Dict:
        engine = self.get_engine(simulation_id)
        effective_tick = self._effective_tick(engine, tick)
        snapshot = snapshot_override if snapshot_override is not None else self._snapshot_for_tick(engine, effective_tick)
        if snapshot:
            snapshot_projects = snapshot.get("projects", {})
            snapshot_agents = snapshot.get("agents", {})
            visible_agents = self._visible_snapshot_agents(snapshot_agents, snapshot_projects, engine)
            projects = [self._project_node_from_dict(project, snapshot_agents) for project in snapshot_projects.values()]
            enterprises = [
                self._enterprise_node_from_dict(agent, snapshot_projects)
                for agent in visible_agents
            ]
            network = snapshot.get("network", {})
            collaboration_links = [
                self._edge_link_from_dict(edge, snapshot_agents, snapshot_projects, "collaboration_link")
                for edge in network.get("edges", [])
            ]
            resource_flows = [
                self._resource_link_from_dict(project, snapshot_agents)
                for project in snapshot_projects.values()
                if project.get("selected_supplier_ids") and project.get("selected_contractor_id")
            ]
        else:
            projects = [self._project_node(project, engine.agents) for project in engine.projects.values()]
            enterprises = [self._enterprise_node(agent, engine) for agent in self._visible_enterprise_agents(engine)]
            collaboration_links = [self._edge_link(edge, engine, "collaboration_link") for edge in engine.network.edges]
            resource_flows = [
                self._resource_link(project, engine)
                for project in engine.projects.values()
                if project.selected_supplier_ids and project.selected_contractor_id
            ]
        if not collaboration_links and not snapshot:
            collaboration_links = self._fallback_links(engine)
        if not resource_flows and not snapshot and engine.projects:
            resource_flows = [self._resource_link(next(iter(engine.projects.values())), engine)]
        return {
            "projects": projects,
            "enterprises": enterprises,
            "resource_flows": [link for link in resource_flows if link],
            "collaboration_links": [link for link in collaboration_links if link],
        }

    def _visible_enterprise_agents(self, engine: SimulationEngine) -> list:
        if len(engine.agents) <= VISIBLE_ENTERPRISE_LIMIT:
            return list(engine.agents.values())
        engaged_ids = {
            engagement.agent_id
            for project in engine.projects.values()
            for engagement in project.engagements
        }
        engaged_agents = [agent for agent in engine.agents.values() if agent.agent_id in engaged_ids]
        free_agents = [agent for agent in engine.agents.values() if agent.agent_id not in engaged_ids]
        engaged_agents = sorted(
            engaged_agents,
            key=lambda agent: (
                agent.region,
                self._role_class(agent.role),
                agent.agent_id,
            ),
        )
        free_agents = sorted(
            free_agents,
            key=lambda agent: (
                agent.region,
                self._role_class(agent.role),
                -agent.cross_region_experience,
                agent.agent_id,
            ),
        )
        selected_free = self._balanced_enterprise_agents(
            free_agents,
            max(0, VISIBLE_ENTERPRISE_LIMIT - len(engaged_agents)),
        )
        return engaged_agents + selected_free

    def _balanced_enterprise_agents(self, agents: list, limit: int) -> list:
        if limit <= 0 or not agents:
            return []
        city_buckets: dict[str, dict[str, list]] = {}
        for agent in agents:
            city = str(getattr(agent, "region", "") or "Shenzhen")
            role_class = self._role_class(getattr(agent, "role", ""))
            city_buckets.setdefault(city, {}).setdefault(role_class, []).append(agent)

        for role_buckets in city_buckets.values():
            for bucket in role_buckets.values():
                bucket.sort(key=lambda agent: (-agent.cross_region_experience, agent.agent_id))

        city_order = [
            city
            for city in CITY_COORDS
            if any(city_buckets.get(city, {}).values())
        ] + sorted(city for city in city_buckets if city not in CITY_COORDS)
        city_role_counts: dict[str, dict[str, int]] = {city: {} for city in city_order}
        selected = []
        while len(selected) < limit and any(self._city_has_agents(city_buckets.get(city, {})) for city in city_order):
            for city in city_order:
                if len(selected) >= limit:
                    break
                role_class = self._next_city_role(city, city_buckets.get(city, {}), city_role_counts[city])
                if not role_class:
                    continue
                selected.append(city_buckets[city][role_class].pop(0))
                city_role_counts[city][role_class] = city_role_counts[city].get(role_class, 0) + 1
        return selected

    @staticmethod
    def _city_has_agents(role_buckets: dict[str, list]) -> bool:
        return any(role_buckets.get(role_class) for role_class in ROLE_CLASS_ORDER)

    def _next_city_role(
        self,
        city: str,
        role_buckets: dict[str, list],
        role_counts: dict[str, int],
    ) -> Optional[str]:
        available_roles = [
            role_class
            for role_class in ROLE_CLASS_ORDER
            if role_buckets.get(role_class)
        ]
        if not available_roles:
            return None
        unused_roles = [role_class for role_class in available_roles if role_counts.get(role_class, 0) == 0]
        if unused_roles and sum(role_counts.values()) < min(3, len(available_roles)):
            return max(unused_roles, key=lambda role_class: self._city_role_weight(city, role_class))
        return min(
            available_roles,
            key=lambda role_class: (
                role_counts.get(role_class, 0) / max(self._city_role_weight(city, role_class), 0.01),
                -self._city_role_weight(city, role_class),
            ),
        )

    @staticmethod
    def _city_role_weight(city: str, role_class: str) -> float:
        return CITY_ROLE_MIX.get(city, DEFAULT_CITY_ROLE_MIX).get(role_class, 0.01)

    @staticmethod
    def _role_class(role: str) -> str:
        return ROLE_MAP.get(str(role or ""), "consultant")

    def projects(self, simulation_id: str, tick: Optional[int] = None) -> list[Dict]:
        return self.map_data(simulation_id, tick)["projects"]

    def insights(self, simulation_id: str, tick: Optional[int] = None) -> list[Dict]:
        engine = self.get_engine(simulation_id)
        metrics = engine.metrics.dict()
        project_metrics = metrics.get("project_metrics", {})
        return [
            {
                "insight_id": "INS001",
                "severity": "medium",
                "title": "Approval and tender sequence preserved",
                "description": "The active project follows the stage-gated lifecycle before entering construction.",
            },
            {
                "insight_id": "INS002",
                "severity": "high" if project_metrics.get("average_delay_days", 0) > 20 else "low",
                "title": "Delay and claim risk are traceable",
                "description": "Delay days, cost overrun, defect rate, and claim risk are saved at each simulation tick.",
            },
        ]

    def timeline(self, simulation_id: str) -> Dict:
        engine = self.get_engine(simulation_id)
        events_by_tick: Dict[int, list[Dict]] = {}
        for event in engine.events.events:
            events_by_tick.setdefault(event.tick, []).append(self._event_dict(event))
        rows = []
        for snapshot in self._ordered_tick_snapshots(engine):
            projects = self._snapshot_project_rows(snapshot)
            stage_counts: Dict[str, int] = {}
            for project in projects:
                stage = self._project_stage_value(project)
                stage_counts[stage] = stage_counts.get(stage, 0) + 1
            active_count = len(
                [
                    project
                    for project in projects
                    if self._project_stage_value(project) not in {ProjectStage.CLOSED.value, ProjectStage.FAILED.value, ProjectStage.SUSPENDED.value}
                ]
            )
            completed_count = len([project for project in projects if self._project_stage_value(project) == ProjectStage.CLOSED.value])
            progress_values = [self._project_lifecycle_progress(project) for project in projects]
            quality_values = [
                self._performance_dict(project).get("overall_quality", 0.0)
                for project in projects
            ]
            delay_days = sum(int(self._performance_dict(project).get("delay_days", 0)) for project in projects)
            edge_count = len(snapshot.get("network", {}).get("edges", []))
            tick_value = int(snapshot.get("tick", 0))
            active_firms, all_engaged_firms = self._engaged_agent_sets(projects)
            tick_events = events_by_tick.get(tick_value, [])
            important_events = [
                event
                for event in tick_events
                if event.get("event_type")
                in {
                    "stage_transition",
                    "approval_approved",
                    "approval_rejected",
                    "project_completed",
                    "project_suspended",
                    "project_failed",
                    "agent_engaged",
                    "agent_released",
                    "agent_recalled",
                    "bid_submitted",
                    "bid_declined",
                    "bid_failed",
                    "contract_awarded",
                    "construction_progress_updated",
                    "variation_requested",
                    "quality_issue",
                    "safety_issue",
                    "supply_delay",
                }
            ][:8]
            rows.append(
                {
                    "tick": tick_value,
                    "date": (date(2025, 5, 1) + timedelta(days=30 * tick_value)).isoformat(),
                    "active_projects": active_count,
                    "completed_projects": completed_count,
                    "project_count": len(projects),
                    "average_progress": round(sum(progress_values) / max(len(progress_values), 1), 4),
                    "average_construction_progress": round(
                        sum(self._safe_float(self._performance_dict(project).get("actual_progress"), 0.0) for project in projects)
                        / max(len(projects), 1),
                        4,
                    ),
                    "average_quality": round(sum(quality_values) / max(len(quality_values), 1), 4),
                    "delay_days": delay_days,
                    "stage_counts": stage_counts,
                    "metrics": snapshot.get("metrics", {}),
                    "collaboration_edges": edge_count,
                    "resource_flows": len(
                        [
                            project
                            for project in projects
                            if project.get("selected_supplier_ids") and project.get("selected_contractor_id")
                        ]
                    ),
                    "engaged_agents": len(active_firms) or len(all_engaged_firms),
                    "stage": self._project_stage_value(projects[0]) if projects else "",
                    "event_count": len(tick_events),
                    "important_events": important_events,
                }
            )
        return {
            "simulation_id": simulation_id,
            "start_date": (date(2025, 5, 1) + timedelta(days=30)).isoformat(),
            "end_date": (date(2025, 5, 1) + timedelta(days=30 * (rows[-1]["tick"] if rows else engine.current_tick))).isoformat(),
            "ticks": rows,
        }

    def agent_history(self, simulation_id: str, agent_id: str, tick: Optional[int] = None) -> Dict:
        engine = self.get_engine(simulation_id)
        effective_tick = self._effective_tick(engine, tick)
        agent = engine.agents.get(agent_id)
        if not agent:
            # The agent may only exist inside compact historical snapshots.
            for snapshot in self._ordered_tick_snapshots(engine):
                snapshot_tick = int(snapshot.get("tick", 0))
                if tick is not None and snapshot_tick > effective_tick:
                    break
                snapshot_agent = snapshot.get("agents", {}).get(agent_id)
                if snapshot_agent:
                    agent = snapshot_agent
                    break
        events = [
            self._event_dict(event)
            for event in engine.events.by_agent(agent_id)
            if tick is None or int(getattr(event, "tick", 0) or 0) <= effective_tick
        ]
        engagements = [
            self._engagement_dict(engagement)
            for project in engine.projects.values()
            for engagement in project.engagements
            if engagement.agent_id == agent_id
            and (tick is None or int(getattr(engagement, "joined_at_tick", 0) or 0) <= effective_tick)
        ]
        status_timeline = []
        for snapshot in self._ordered_tick_snapshots(engine):
            tick_value = int(snapshot.get("tick", 0))
            if tick is not None and tick_value > effective_tick:
                break
            statuses = []
            project_ids = []
            for project in snapshot.get("projects", {}).values():
                for engagement in project.get("engagements", []):
                    if engagement.get("agent_id") == agent_id:
                        status = str(engagement.get("status") or "free")
                        joined_at = int(engagement.get("joined_at_tick") or 0)
                        released_at = int(engagement.get("released_at_tick") or 0)
                        if joined_at and tick_value < joined_at:
                            continue
                        if status in {"released", "terminated"}:
                            # Released/terminated engagements remain on the project as
                            # history, but after the release month the enterprise is
                            # free for its own operations again.
                            if released_at and tick_value > released_at:
                                continue
                            if released_at and tick_value < released_at:
                                continue
                        statuses.append(status)
                        project_ids.append(project.get("project_id"))
            status_timeline.append(
                {
                    "tick": tick_value,
                    "date": (date(2025, 5, 1) + timedelta(days=30 * tick_value)).isoformat(),
                    "status": self._dominant_status(statuses),
                    "project_ids": sorted({pid for pid in project_ids if pid}),
                }
            )
        active_like = {"active", "standby", "invited", "bidding"}
        active_rows = [row for row in status_timeline if row["status"] in active_like]
        joined_project_ids = sorted(
            {
                engagement.get("project_id")
                for engagement in engagements
                if engagement.get("project_id")
            }
            | {
                project_id
                for row in status_timeline
                for project_id in row.get("project_ids", [])
            }
        )
        event_counts: Dict[str, int] = {}
        for event in events:
            event_type = event.get("event_type", "")
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
        agent_data = agent.dict() if hasattr(agent, "dict") else agent
        activity_timeline = self._build_agent_activity_timeline(engine, agent_data or {"agent_id": agent_id}, events, status_timeline)
        return {
            "simulation_id": simulation_id,
            "current_tick": effective_tick,
            "agent": agent_data,
            "events": events,
            "engagements": engagements,
            "status_timeline": status_timeline,
            "activity_timeline": activity_timeline,
            "summary": {
                "joined_projects": len(joined_project_ids),
                "joined_project_ids": joined_project_ids,
                "event_count": len(events),
                "bid_events": sum(1 for event in events if "bid" in event.get("event_type", "")),
                "release_events": sum(1 for event in events if "released" in event.get("event_type", "")),
                "active_ticks": len(active_rows),
                "first_active_tick": active_rows[0]["tick"] if active_rows else None,
                "last_active_tick": active_rows[-1]["tick"] if active_rows else None,
                "event_counts": event_counts,
            },
        }

    def _build_agent_activity_timeline(
        self,
        engine: SimulationEngine,
        agent: Dict,
        events: list[Dict],
        status_timeline: list[Dict],
    ) -> list[Dict]:
        events_by_tick: Dict[int, list[Dict]] = {}
        for event in events:
            events_by_tick.setdefault(int(event.get("tick") or 0), []).append(event)

        rows: list[Dict] = []
        for status_row in status_timeline:
            tick_value = int(status_row.get("tick") or 0)
            tick_events = events_by_tick.get(tick_value, [])
            meaningful_events = [
                event
                for event in tick_events
                if event.get("event_type") not in {"agent_operation"}
            ]
            if meaningful_events:
                for event in meaningful_events:
                    event_row = dict(event)
                    event_row["date"] = status_row.get("date")
                    event_row["data"] = {
                        **(event_row.get("data") or {}),
                        "activity_source": "simulation_event",
                    }
                    rows.append(event_row)
                continue

            generated = self._generated_agent_monthly_activity(engine, agent, status_row)
            if generated:
                rows.append(generated)
        return rows

    def _generated_agent_monthly_activity(self, engine: SimulationEngine, agent: Dict, status_row: Dict) -> Optional[Dict]:
        tick_value = int(status_row.get("tick") or 0)
        if tick_value <= 0:
            return None

        agent_id = str(agent.get("agent_id") or "")
        role = str(agent.get("role") or "Enterprise")
        region = str(agent.get("region") or "Greater Bay Area")
        status = str(status_row.get("status") or "free")
        snapshot = self._snapshot_for_tick(engine, tick_value)
        project_context = self._agent_project_context(engine, snapshot, status_row)
        operation = self._agent_operation_for_context(agent, role, region, status, tick_value, project_context)
        project_id = project_context.get("project_id") if project_context and status not in {"free", "released", "terminated"} else None
        return {
            "event_id": f"ACT-{agent_id or 'agent'}-{tick_value:04d}",
            "tick": tick_value,
            "date": status_row.get("date"),
            "project_id": project_id,
            "agent_id": agent_id,
            "event_type": operation["event_type"],
            "stage": project_context.get("stage") if project_context else None,
            "description": operation["description"],
            "data": {
                "activity_source": "generated_monthly_operation",
                "operation": operation["operation"],
                "operation_label": operation["label"],
                "role": role,
                "status": status,
                "region": region,
                "project_id": project_context.get("project_id") if project_context else None,
                "project_name": project_context.get("project_name") if project_context else None,
                "project_stage": project_context.get("stage") if project_context else None,
                "available_resource": self._safe_float(agent.get("total_resource_capacity"), 1.0) - self._safe_float(agent.get("occupied_resource"), 0.0),
            },
        }

    def _agent_project_context(self, engine: SimulationEngine, snapshot: Optional[Dict], status_row: Dict) -> Dict:
        project_ids = status_row.get("project_ids") or []
        if not project_ids:
            return {}
        project_id = project_ids[0]
        project = None
        if snapshot:
            project = snapshot.get("projects", {}).get(project_id)
        if not project:
            project = engine.projects.get(project_id)
        if not project:
            return {"project_id": project_id, "project_name": project_id, "stage": None}
        return {
            "project_id": project_id,
            "project_name": project.get("name") if isinstance(project, dict) else project.name,
            "stage": self._project_stage_value(project),
            "region": project.get("region") if isinstance(project, dict) else project.region,
            "progress": self._performance_dict(project).get("actual_progress"),
            "quality": self._performance_dict(project).get("overall_quality"),
        }

    def _agent_operation_for_context(self, agent: Dict, role: str, region: str, status: str, tick: int, project: Dict) -> Dict:
        role_key = role.lower()
        stage = str(project.get("stage") or "").lower()
        project_name = project.get("project_name") or "the project"

        if status in {"free", "released", "terminated"}:
            catalog = self._out_of_project_operations(role_key, region, project_name, status)
            event_type = "out_of_project_operation"
        elif status == "invited":
            catalog = [
                ("review_tender_invitation", "Reviewed tender invitation", f"Reviewed the tender invitation and checked qualification, region fit, and available resources for {project_name}."),
                ("screen_project_risk", "Screened project risk", f"Screened {project_name} for policy friction, contract risk, expected margin, and partner needs."),
                ("prepare_go_no_go_decision", "Prepared bid decision", f"Prepared a bid/no-bid decision for {project_name} based on workload and strategic fit."),
            ]
            event_type = "enterprise_operation"
        elif status == "bidding":
            catalog = [
                ("price_bid", "Prepared bid price", f"Prepared bid pricing and risk allowance for {project_name}."),
                ("review_boq", "Reviewed bill of quantities", f"Reviewed bill of quantities, scope clarity, and likely variation risk for {project_name}."),
                ("seek_partner", "Checked partner needs", f"Checked whether a local partner or specialist supplier was needed before submitting the bid for {project_name}."),
            ]
            event_type = "enterprise_operation"
        elif status == "standby":
            catalog = [
                ("maintain_standby_support", "Maintained standby support", f"Kept a standby team available for design clarification, cost queries, or variation support on {project_name}."),
                ("review_project_updates", "Reviewed project updates", f"Reviewed monthly project updates for {project_name} while not actively consuming resources."),
                ("prepare_recall_response", "Prepared recall response", f"Maintained documents and staff readiness in case {project_name} required recall support."),
            ]
            event_type = "enterprise_operation"
        else:
            catalog = self._in_project_operations(role_key, stage, project_name)
            event_type = "enterprise_operation"

        operation, label, description = catalog[self._stable_index(agent.get("agent_id"), tick, len(catalog))]
        return {
            "event_type": event_type,
            "operation": operation,
            "label": label,
            "description": description,
        }

    def _out_of_project_operations(self, role_key: str, region: str, last_project_name: str, status: str) -> list[tuple[str, str, str]]:
        release_prefix = f"After release from {last_project_name}, " if status == "released" and last_project_name else ""
        if "owner" in role_key or "developer" in role_key:
            return [
                ("evaluate_market_demand", "Evaluated market demand", f"{release_prefix}reviewed market demand and financing conditions for potential new projects in {region}."),
                ("screen_investment_pipeline", "Screened investment pipeline", f"{release_prefix}screened candidate sites, budget capacity, and policy timing before initiating another project."),
                ("review_financing_capacity", "Reviewed financing capacity", f"{release_prefix}checked payment reliability, capital availability, and risk appetite for future developments."),
                ("prepare_project_scope", "Prepared project scope", f"{release_prefix}prepared an early scope, region choice, and budget envelope for a possible new project."),
            ]
        if "contractor" in role_key:
            return [
                ("scan_tender_opportunities", "Scanned tender opportunities", f"{release_prefix}scanned public and private tender opportunities and ranked them by margin, region fit, and risk."),
                ("adjust_bid_strategy", "Adjusted bid strategy", f"{release_prefix}updated bid strategy using recent tender outcomes, resource availability, and competitor signals."),
                ("evaluate_region_entry", "Evaluated regional entry", f"{release_prefix}evaluated whether to enter nearby GBA markets based on qualification recognition and local partner needs."),
                ("maintain_supplier_relationship", "Maintained supplier network", f"{release_prefix}maintained supplier relationships and checked material availability for upcoming bids."),
            ]
        if "supplier" in role_key:
            return [
                ("adjust_inventory", "Adjusted inventory", f"{release_prefix}adjusted inventory against material-price changes and expected construction demand in {region}."),
                ("seek_supply_contract", "Searched supply contracts", f"{release_prefix}looked for supply contract opportunities and checked delivery capacity."),
                ("monitor_material_prices", "Monitored material prices", f"{release_prefix}monitored material price trends and updated quotation assumptions."),
                ("improve_supply_reliability", "Improved supply reliability", f"{release_prefix}reviewed logistics reliability and backup sourcing options."),
            ]
        if "architect" in role_key or "design" in role_key:
            return [
                ("seek_design_commission", "Searched design commissions", f"{release_prefix}searched for design commissions and reviewed fit with the firm's design capability."),
                ("build_cross_region_reputation", "Built cross-region reputation", f"{release_prefix}updated portfolio material and cross-region collaboration references."),
                ("improve_design_capability", "Improved design capability", f"{release_prefix}allocated free capacity to design-process improvement and policy-aligned design methods."),
                ("maintain_client_relationship", "Maintained client relationships", f"{release_prefix}maintained owner and consultant relationships for future design work."),
            ]
        if "qs" in role_key or "consultant" in role_key:
            return [
                ("update_cost_database", "Updated cost database", f"{release_prefix}updated cost benchmarks, tender-price assumptions, and regional material indices."),
                ("seek_consulting_work", "Searched consulting work", f"{release_prefix}screened upcoming consulting commissions and tender-preparation opportunities."),
                ("review_cost_market", "Reviewed cost market", f"{release_prefix}reviewed market rates, claim trends, and procurement risk signals."),
                ("improve_cost_estimation", "Improved cost estimation", f"{release_prefix}refined cost-estimation parameters using recent project and bid data."),
            ]
        if "government" in role_key:
            return [
                ("publish_guidelines", "Published guidance", f"Reviewed market feedback and prepared policy or compliance guidance for enterprises in {region}."),
                ("monitor_compliance", "Monitored compliance signals", f"Monitored approval, safety, and procurement compliance signals across active regional projects."),
                ("adjust_regulatory_focus", "Adjusted regulatory focus", f"Adjusted inspection and procedural focus based on market risk and policy objectives."),
                ("review_policy_feedback", "Reviewed policy feedback", f"Reviewed enterprise feedback on cross-region qualification, transparency, and compliance burden."),
            ]
        return [
            ("maintain_operations", "Maintained operations", f"{release_prefix}maintained enterprise operations and watched for suitable GBA collaboration opportunities."),
            ("review_partner_pipeline", "Reviewed partner pipeline", f"{release_prefix}reviewed partner options and cross-region collaboration fit."),
        ]

    def _in_project_operations(self, role_key: str, stage: str, project_name: str) -> list[tuple[str, str, str]]:
        if "owner" in role_key or "developer" in role_key:
            if stage in {"tender_preparation", "tendering", "bid_evaluation"}:
                return [
                    ("define_procurement_strategy", "Defined procurement strategy", f"Reviewed procurement strategy, tender attractiveness, and evaluation criteria for {project_name}."),
                    ("answer_owner_queries", "Managed tender decisions", f"Resolved owner-side tender decisions and clarified project priorities for {project_name}."),
                ]
            if stage == "construction":
                return [
                    ("monitor_progress", "Monitored project progress", f"Reviewed monthly progress, payment readiness, delay exposure, and variation risk for {project_name}."),
                    ("approve_payment", "Reviewed payment request", f"Reviewed payment reliability and certified progress before approving payment on {project_name}."),
                    ("resolve_variation", "Reviewed variation request", f"Reviewed possible design variation impacts on cost, time, and claim risk for {project_name}."),
                ]
            return [
                ("review_project_scope", "Reviewed project scope", f"Reviewed scope, budget, consultant outputs, and approval readiness for {project_name}."),
                ("coordinate_owner_decision", "Coordinated owner decision", f"Coordinated owner decisions required to keep {project_name} moving through the lifecycle gate."),
            ]
        if "contractor" in role_key:
            return [
                ("execute_work", "Executed site work", f"Coordinated labour, plant, and subcontractors to progress construction work on {project_name}."),
                ("manage_safety_quality", "Managed safety and quality", f"Checked safety controls, method statements, and quality records for {project_name}."),
                ("coordinate_supplier", "Coordinated supplier delivery", f"Coordinated supplier delivery dates, material availability, and site demand for {project_name}."),
                ("prepare_payment_request", "Prepared payment request", f"Prepared a monthly payment request and progress evidence for {project_name}."),
            ]
        if "supplier" in role_key:
            return [
                ("deliver_materials", "Delivered materials", f"Checked material availability and delivered scheduled supplies for {project_name}."),
                ("manage_supply_risk", "Managed supply risk", f"Reviewed logistics, price movement, and delay risk for supplies to {project_name}."),
                ("coordinate_contractor", "Coordinated with contractor", f"Coordinated quantities, delivery windows, and replacement materials with the contractor on {project_name}."),
            ]
        if "architect" in role_key or "design" in role_key:
            return [
                ("prepare_design_information", "Prepared design information", f"Prepared or clarified design information needed for {project_name}."),
                ("coordinate_design", "Coordinated design inputs", f"Coordinated owner, QS, and technical design inputs for {project_name}."),
                ("support_approval", "Supported approval", f"Supported approval or construction clarification with updated design documents for {project_name}."),
            ]
        if "qs" in role_key or "consultant" in role_key:
            return [
                ("update_cost_estimate", "Updated cost estimate", f"Updated cost estimates, BOQ assumptions, and financial risk for {project_name}."),
                ("evaluate_payment", "Evaluated payment", f"Checked payment application, completed quantities, and cost exposure for {project_name}."),
                ("assess_claim_variation", "Assessed claim or variation", f"Assessed variation cost, claim exposure, and contract implications for {project_name}."),
            ]
        if "government" in role_key:
            return [
                ("review_submission", "Reviewed submission", f"Reviewed approval or inspection submission materials for {project_name}."),
                ("conduct_compliance_check", "Conducted compliance check", f"Checked safety, approval, and procedural compliance evidence for {project_name}."),
            ]
        return [
            ("coordinate_project_task", "Coordinated project task", f"Performed the assigned project responsibility for {project_name}."),
        ]

    @staticmethod
    def _stable_index(agent_id, tick: int, size: int) -> int:
        seed = sum(ord(char) for char in str(agent_id or "")) + tick * 17
        return seed % max(size, 1)

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
        return max(lower, min(upper, value))

    def _resource_flow_score(self, resource_flows: list[Dict], projects: list) -> Dict:
        project_rows = [project for project in projects or [] if self._project_id(project)]
        if not project_rows:
            return {
                "index": 0.0,
                "flow_volume": 0.0,
                "components": {
                    "coverage": 0.0,
                    "throughput": 0.0,
                    "reliability": 0.0,
                    "corridor_balance": 0.0,
                    "cross_region_integration": 0.0,
                },
            }

        projects_by_id = {self._project_id(project): project for project in project_rows}
        project_budgets = {
            project_id: self._project_budget(project)
            for project_id, project in projects_by_id.items()
        }
        positive_budgets = [budget for budget in project_budgets.values() if budget > 0]
        average_budget = sum(positive_budgets) / max(len(positive_budgets), 1)
        total_demand = sum(positive_budgets) or max(average_budget, 1.0)

        flowed_projects: set[str] = set()
        total_flow_volume = 0.0
        cross_region_volume = 0.0
        corridor_volumes: dict[str, float] = {}
        reliability_scores = []

        for flow in resource_flows or []:
            project_id = str(flow.get("project_id") or self._project_id_from_resource_link(flow, projects_by_id) or "")
            project = projects_by_id.get(project_id)
            budget = self._project_budget(project) if project else average_budget
            if budget <= 0:
                budget = average_budget or 1.0
            strength = self._clamp(self._safe_float(flow.get("strength"), 0.0))
            flow_volume = self._safe_float(flow.get("flow_volume"), 0.0)
            if flow_volume <= 0:
                flow_volume = self._project_resource_flow_volume(project, strength, budget) if project else budget * strength
            if flow_volume <= 0:
                continue

            if project_id:
                flowed_projects.add(project_id)
            total_flow_volume += flow_volume
            if bool(flow.get("cross_city")):
                cross_region_volume += flow_volume
            corridor = f"{flow.get('source_city') or 'Unknown'}->{flow.get('target_city') or 'Unknown'}"
            corridor_volumes[corridor] = corridor_volumes.get(corridor, 0.0) + flow_volume
            reliability_scores.append(self._resource_reliability_score(project, strength))

        coverage = len(flowed_projects) / max(len(project_rows), 1)
        throughput = self._clamp(total_flow_volume / max(total_demand, 1.0))
        reliability = sum(reliability_scores) / max(len(reliability_scores), 1) if reliability_scores else 0.0
        corridor_balance = self._corridor_balance_score(corridor_volumes)
        cross_region_integration = self._clamp((cross_region_volume / max(total_flow_volume, 1.0)) / 0.35) if total_flow_volume else 0.0
        index = 10 * (
            0.26 * coverage
            + 0.24 * throughput
            + 0.22 * reliability
            + 0.16 * corridor_balance
            + 0.12 * cross_region_integration
        )

        return {
            "index": round(index, 1),
            "flow_volume": round(total_flow_volume, 2),
            "components": {
                "coverage": round(coverage, 3),
                "throughput": round(throughput, 3),
                "reliability": round(reliability, 3),
                "corridor_balance": round(corridor_balance, 3),
                "cross_region_integration": round(cross_region_integration, 3),
            },
        }

    def _resource_reliability_score(self, project, strength: float) -> float:
        performance = self._performance_dict(project) if project else {}
        cost_overrun = max(0.0, self._safe_float(performance.get("cost_overrun_ratio"), 0.0))
        delay_days = max(0.0, self._safe_float(performance.get("delay_days"), 0.0))
        planned_duration = max(1.0, self._safe_float(performance.get("planned_duration"), 12.0))
        cost_score = self._clamp(1.0 - cost_overrun * 1.8)
        delay_score = self._clamp(1.0 - delay_days / max(planned_duration * 30 * 0.35, 1.0))
        return self._clamp(0.62 * self._clamp(strength) + 0.22 * cost_score + 0.16 * delay_score)

    @staticmethod
    def _corridor_balance_score(corridor_volumes: dict[str, float]) -> float:
        values = [value for value in corridor_volumes.values() if value > 0]
        if not values:
            return 0.0
        if len(values) == 1:
            return 0.35
        total = sum(values)
        shares = [value / total for value in values]
        hhi = sum(share * share for share in shares)
        return max(0.0, min(1.0, (1.0 - hhi) / (1.0 - 1.0 / len(values))))

    def _project_resource_flow_volume(self, project, strength: float, budget: Optional[float] = None) -> float:
        if not project:
            return 0.0
        project_budget = budget if budget is not None else self._project_budget(project)
        performance = self._performance_dict(project)
        progress = self._clamp(self._safe_float(performance.get("actual_progress"), 0.0))
        return max(project_budget, 0.0) * max(progress, 0.05) * max(self._clamp(strength), 0.15)

    def _project_budget(self, project) -> float:
        if not project:
            return 0.0
        if isinstance(project, dict):
            return max(
                self._safe_float(project.get("contract_sum"), 0.0),
                self._safe_float(project.get("estimated_cost"), 0.0),
                self._safe_float(project.get("initial_budget"), 0.0),
            )
        return max(
            self._safe_float(getattr(project, "contract_sum", None), 0.0),
            self._safe_float(getattr(project, "estimated_cost", None), 0.0),
            self._safe_float(getattr(project, "initial_budget", None), 0.0),
        )

    @staticmethod
    def _project_id(project) -> str:
        if not project:
            return ""
        if isinstance(project, dict):
            return str(project.get("project_id") or "")
        return str(getattr(project, "project_id", "") or "")

    @staticmethod
    def _project_id_from_resource_link(flow: Dict, projects_by_id: dict[str, object]) -> str:
        link_id = str(flow.get("link_id") or "")
        for project_id in projects_by_id:
            if link_id.endswith(f"_{project_id}") or project_id in link_id:
                return project_id
        return ""

    def step(self, simulation_id: str) -> Dict:
        with self._lock_for(simulation_id):
            engine = self.get_engine(simulation_id)
            engine.step()
        return self.runtime_state(simulation_id)

    def play(self, simulation_id: str) -> Dict:
        with self._lock_for(simulation_id):
            engine = self.get_engine(simulation_id)
            engine.status = "running"
        return self.runtime_state(simulation_id)

    def pause(self, simulation_id: str) -> Dict:
        with self._lock_for(simulation_id):
            engine = self.get_engine(simulation_id)
            engine.status = "paused"
        return self.runtime_state(simulation_id)

    def seek(self, simulation_id: str, target_tick: int) -> Dict:
        with self._lock_for(simulation_id):
            engine = self.get_engine(simulation_id)
            while engine.current_tick < min(target_tick, engine.ticks):
                engine.step()
        return self.runtime_state(simulation_id, min(target_tick, engine.current_tick))

    def _project_node(self, project, agents: Optional[Dict] = None) -> Dict:
        coords = CITY_COORDS.get(project.region, CITY_COORDS["Shenzhen"])
        lifecycle_progress = self._project_lifecycle_progress(project)
        physical_progress = self._safe_float(project.performance.actual_progress, 0.0)
        return {
            "project_id": project.project_id,
            "name": project.name,
            "city": project.region,
            "latitude": coords["latitude"],
            "longitude": coords["longitude"],
            "project_type": project.project_type,
            "status": self._project_status(project.current_stage),
            "progress": round(lifecycle_progress * 100, 1),
            "lifecycle_progress": round(lifecycle_progress, 4),
            "physical_progress": round(physical_progress, 4),
            "quality_score": round(project.performance.overall_quality * 100, 1),
            "delay_days": project.performance.delay_days,
            "cost_overrun_ratio": round(project.performance.cost_overrun_ratio, 4),
            "stage": project.current_stage.value if hasattr(project.current_stage, "value") else str(project.current_stage),
            "owner_id": project.owner_id,
            "selected_architect_id": project.selected_architect_id,
            "selected_engineer_id": project.selected_engineer_id,
            "selected_qs_id": project.selected_qs_id,
            "selected_contractor_id": project.selected_contractor_id,
            "selected_supplier_ids": project.selected_supplier_ids,
            "selected_bank_id": project.selected_bank_id,
            "participants": self._project_participants(project, agents or {}),
            "initial_budget": project.initial_budget,
            "estimated_cost": project.estimated_cost,
            "contract_sum": project.contract_sum,
            "planned_duration": project.performance.planned_duration,
            "bids": project.bids[:12],
            "contracts": project.contracts[:6],
            "created_tick": self._project_created_tick(project),
            "interaction_sessions": self._project_interaction_sessions(project),
        }

    def _project_node_from_dict(self, project: Dict, agents: Optional[Dict] = None) -> Dict:
        coords = CITY_COORDS.get(project.get("region"), CITY_COORDS["Shenzhen"])
        performance = project.get("performance", {})
        stage = self._project_stage_value(project)
        lifecycle_progress = self._project_lifecycle_progress(project)
        physical_progress = self._safe_float(performance.get("actual_progress"), 0.0)
        return {
            "project_id": project.get("project_id", ""),
            "name": project.get("name", "Project"),
            "city": project.get("region", "Shenzhen"),
            "latitude": coords["latitude"],
            "longitude": coords["longitude"],
            "project_type": project.get("project_type", "building"),
            "status": self._project_status(stage),
            "progress": round(lifecycle_progress * 100, 1),
            "lifecycle_progress": round(lifecycle_progress, 4),
            "physical_progress": round(physical_progress, 4),
            "quality_score": round(float(performance.get("overall_quality", 0.0)) * 100, 1),
            "delay_days": performance.get("delay_days", 0),
            "cost_overrun_ratio": round(float(performance.get("cost_overrun_ratio", 0.0)), 4),
            "stage": stage,
            "owner_id": project.get("owner_id"),
            "selected_architect_id": project.get("selected_architect_id"),
            "selected_engineer_id": project.get("selected_engineer_id"),
            "selected_qs_id": project.get("selected_qs_id"),
            "selected_contractor_id": project.get("selected_contractor_id"),
            "selected_supplier_ids": project.get("selected_supplier_ids") or [],
            "selected_bank_id": project.get("selected_bank_id"),
            "participants": self._project_participants_from_dict(project, agents or {}),
            "initial_budget": project.get("initial_budget"),
            "estimated_cost": project.get("estimated_cost"),
            "contract_sum": project.get("contract_sum"),
            "planned_duration": performance.get("planned_duration", project.get("planned_duration", 0)),
            "bids": (project.get("bids") or [])[:12],
            "contracts": (project.get("contracts") or [])[:6],
            "created_tick": self._project_created_tick(project),
            "interaction_sessions": self._project_interaction_sessions(project),
        }

    @staticmethod
    def _project_interaction_sessions(project) -> list[Dict]:
        event_log = project.get("event_log", []) if isinstance(project, dict) else getattr(project, "event_log", [])
        sessions: dict[str, Dict] = {}
        for event in event_log or []:
            event_type = str(event.get("event_type") or "")
            data = event.get("data") or {}
            session_id = data.get("session_id")
            if not session_id:
                continue
            session_key = str(session_id)
            session = sessions.setdefault(
                session_key,
                {
                    "session_id": session_id,
                    "session_type": data.get("session_type") or event_type.replace("_session_started", ""),
                    "tick": event.get("tick"),
                    "stage": event.get("stage"),
                    "participants": data.get("session_participants") or data.get("participants") or [],
                    "summary": data.get("summary") or event.get("description") or "",
                    "recent_messages": data.get("recent_messages") or [],
                    "latest_event_type": event_type,
                    "latest_tick": event.get("tick"),
                },
            )
            if event_type.endswith("_session_started"):
                session.update(
                    {
                        "session_type": data.get("session_type") or event_type.replace("_session_started", ""),
                        "tick": event.get("tick"),
                        "stage": event.get("stage"),
                        "participants": data.get("session_participants") or data.get("participants") or [],
                        "summary": data.get("summary") or event.get("description") or "",
                        "recent_messages": data.get("recent_messages") or [],
                    }
                )
            else:
                session["latest_event_type"] = event_type
                session["latest_tick"] = event.get("tick")
                session["latest_action"] = data.get("selected_action")
                session["latest_reason"] = data.get("decision_reason")
                if data.get("decision_reason"):
                    session["summary"] = data["decision_reason"]
        return sorted(sessions.values(), key=lambda item: int(item.get("tick") or 0))[-6:]

    @staticmethod
    def _runtime_interaction_session_summary(project_nodes: list[Dict]) -> Dict:
        sessions: list[Dict] = []
        for project in project_nodes or []:
            project_id = project.get("project_id")
            project_name = project.get("name")
            for session in project.get("interaction_sessions") or []:
                sessions.append(
                    {
                        **session,
                        "project_id": project_id,
                        "project_name": project_name,
                    }
                )
        by_type: Dict[str, int] = {}
        for session in sessions:
            session_type = str(session.get("session_type") or "interaction")
            by_type[session_type] = by_type.get(session_type, 0) + 1
        latest = None
        if sessions:
            latest = max(
                sessions,
                key=lambda item: int(item.get("latest_tick") or item.get("tick") or 0),
            )
        return {
            "total": len(sessions),
            "by_type": by_type,
            "latest": latest,
        }

    def _project_lifecycle_progress(self, project) -> float:
        stage = self._project_stage_value(project)
        performance = self._performance_dict(project)
        actual_progress = self._safe_float(performance.get("actual_progress"), 0.0)
        design_quality = self._safe_float(performance.get("design_quality"), 0.0)
        information_quality = self._safe_float(performance.get("information_quality"), 0.0)
        elapsed_time = self._safe_float(performance.get("elapsed_time"), 0.0)
        planned_duration = max(1.0, self._safe_float(performance.get("planned_duration"), 1.0))

        stage_bounds = {
            ProjectStage.INITIATION.value: (0.00, 0.05),
            ProjectStage.FEASIBILITY.value: (0.03, 0.08),
            ProjectStage.CONSULTANT_SELECTION.value: (0.05, 0.10),
            ProjectStage.CONCEPT_DESIGN.value: (0.10, 0.16),
            ProjectStage.DETAILED_DESIGN.value: (0.16, 0.24),
            ProjectStage.DESIGN.value: (0.08, 0.25),
            ProjectStage.STATUTORY_APPROVAL.value: (0.25, 0.34),
            ProjectStage.APPROVAL.value: (0.25, 0.34),
            ProjectStage.TENDER_PREPARATION.value: (0.34, 0.43),
            ProjectStage.TENDERING.value: (0.43, 0.54),
            ProjectStage.BID_EVALUATION.value: (0.54, 0.63),
            ProjectStage.CONTRACT_AWARD.value: (0.63, 0.70),
            ProjectStage.MOBILIZATION.value: (0.70, 0.74),
            ProjectStage.CONSTRUCTION.value: (0.74, 0.92),
            ProjectStage.COMPLETION.value: (0.92, 0.96),
            ProjectStage.HANDOVER.value: (0.96, 0.98),
            ProjectStage.FINAL_ACCOUNT.value: (0.98, 0.995),
            ProjectStage.CLOSED.value: (1.00, 1.00),
            ProjectStage.SUSPENDED.value: (0.0, 0.0),
            ProjectStage.FAILED.value: (0.0, 0.0),
        }
        start, end = stage_bounds.get(stage, (0.0, 0.0))
        if stage == ProjectStage.DESIGN.value:
            stage_fraction = max(design_quality / 0.70, information_quality / 0.65)
        elif stage in {ProjectStage.CONSTRUCTION.value, ProjectStage.COMPLETION.value, ProjectStage.HANDOVER.value}:
            stage_fraction = actual_progress
        elif stage == ProjectStage.CLOSED.value:
            stage_fraction = 1.0
        elif stage in {ProjectStage.SUSPENDED.value, ProjectStage.FAILED.value}:
            return max(actual_progress, start)
        else:
            stage_fraction = min(1.0, elapsed_time / planned_duration)
            if stage_fraction <= 0:
                stage_fraction = 0.5
        return max(0.0, min(1.0, start + (end - start) * max(0.0, min(1.0, stage_fraction))))

    @staticmethod
    def _project_created_tick(project) -> int:
        flags = project.get("flags", {}) if isinstance(project, dict) else getattr(project, "flags", {})
        created_tick = flags.get("created_tick") if isinstance(flags, dict) else None
        try:
            if created_tick is not None:
                return max(1, int(created_tick))
        except (TypeError, ValueError):
            pass

        event_log = project.get("event_log", []) if isinstance(project, dict) else getattr(project, "event_log", [])
        project_events = [
            int(event.get("tick") or 0)
            for event in event_log
            if event.get("event_type")
            in {
                "project_opportunity_initiated",
                "project_initiated",
                "consultant_team_appointed",
                "stage_transition",
            }
            and int(event.get("tick") or 0) > 0
        ]
        if project_events:
            return min(project_events)
        return 1

    def _project_participants(self, project, agents: Dict) -> list[Dict]:
        participants: dict[str, Dict] = {}

        def add(agent_id: Optional[str], role: str, status: str = "selected") -> None:
            if not agent_id:
                return
            agent = agents.get(agent_id)
            if not agent:
                return
            participants[agent_id] = {
                "agent_id": agent_id,
                "name": agent.name,
                "role": role,
                "city": agent.region,
                "status": status,
            }

        add(project.owner_id, "Owner", "active")
        add(project.selected_architect_id, "Architect", "active")
        add(project.selected_engineer_id, "Engineer", "active")
        add(project.selected_qs_id, "QS", "active")
        add(project.selected_bank_id, "Bank", "active")
        contract_signed = bool(project.flags.get("contract_signed") or project.contracts)
        if contract_signed:
            add(project.selected_contractor_id, "Contractor", "active")
        for supplier_id in project.selected_supplier_ids:
            add(supplier_id, "Supplier", "active")

        for engagement in project.engagements:
            status = engagement.status.value if hasattr(engagement.status, "value") else str(engagement.status)
            if status not in {"active", "standby"}:
                continue
            if engagement.role == "Contractor" and not contract_signed:
                continue
            add(engagement.agent_id, engagement.role, status)

        return sorted(participants.values(), key=self._participant_sort_key)

    def _project_participants_from_dict(self, project: Dict, agents: Dict) -> list[Dict]:
        participants: dict[str, Dict] = {}

        def agent_value(agent: Dict, key: str, default: str = "") -> str:
            return str(agent.get(key) or default)

        def add(agent_id: Optional[str], role: str, status: str = "selected") -> None:
            if not agent_id:
                return
            agent = agents.get(agent_id)
            if not agent:
                return
            participants[agent_id] = {
                "agent_id": agent_id,
                "name": agent_value(agent, "name", agent_id),
                "role": role,
                "city": agent_value(agent, "region", project.get("region", "")),
                "status": status,
            }

        add(project.get("owner_id"), "Owner", "active")
        add(project.get("selected_architect_id"), "Architect", "active")
        add(project.get("selected_engineer_id"), "Engineer", "active")
        add(project.get("selected_qs_id"), "QS", "active")
        add(project.get("selected_bank_id"), "Bank", "active")
        contract_signed = bool((project.get("flags") or {}).get("contract_signed") or project.get("contracts"))
        if contract_signed:
            add(project.get("selected_contractor_id"), "Contractor", "active")
        for supplier_id in project.get("selected_supplier_ids") or []:
            add(supplier_id, "Supplier", "active")

        for engagement in project.get("engagements", []):
            status = str(engagement.get("status") or "active")
            if status not in {"active", "standby"}:
                continue
            if str(engagement.get("role") or "") == "Contractor" and not contract_signed:
                continue
            add(engagement.get("agent_id"), engagement.get("role") or "Participant", status)

        return sorted(participants.values(), key=self._participant_sort_key)

    @staticmethod
    def _participant_sort_key(participant: Dict) -> tuple[int, str]:
        role_order = {
            "Owner": 0,
            "Developer": 0,
            "Architect": 1,
            "Engineer": 2,
            "QS": 3,
            "Bank": 4,
            "Consultant": 5,
            "Contractor": 6,
            "Supplier": 7,
            "Government": 8,
        }
        return (role_order.get(str(participant.get("role")), 99), str(participant.get("name", "")))

    def _enterprise_node(self, agent, engine: SimulationEngine) -> Dict:
        coords = CITY_COORDS.get(agent.region, CITY_COORDS["Shenzhen"])
        engaged_project_ids = [
            project.project_id
            for project in engine.projects.values()
            for engagement in project.engagements
            if engagement.agent_id == agent.agent_id and engagement.status in {EngagementStatus.ACTIVE, EngagementStatus.STANDBY}
        ]
        status = "free"
        if engaged_project_ids:
            status = "active"
        elif agent.occupied_resource > 0:
            status = "standby"
        return {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "role": ROLE_MAP.get(agent.role, "consultant"),
            "city": agent.region,
            "latitude": coords["latitude"],
            "longitude": coords["longitude"],
            "status": status,
            "engaged_project_ids": engaged_project_ids,
        }

    def _enterprise_node_from_dict(self, agent: Dict, projects: Dict) -> Dict:
        coords = CITY_COORDS.get(agent.get("region"), CITY_COORDS["Shenzhen"])
        active_statuses = []
        engaged_project_ids = []
        for project in projects.values():
            for engagement in project.get("engagements", []):
                if engagement.get("agent_id") == agent.get("agent_id"):
                    status = engagement.get("status", "free")
                    if status in {"active", "standby", "invited", "bidding"}:
                        active_statuses.append(status)
                        engaged_project_ids.append(project.get("project_id"))
        status = self._dominant_status(active_statuses)
        if status in {"invited", "bidding"}:
            status = "active"
        return {
            "agent_id": agent.get("agent_id", ""),
            "name": agent.get("name", ""),
            "role": ROLE_MAP.get(agent.get("role"), "consultant"),
            "city": agent.get("region", "Shenzhen"),
            "latitude": coords["latitude"],
            "longitude": coords["longitude"],
            "status": status,
            "engaged_project_ids": sorted({pid for pid in engaged_project_ids if pid}),
        }

    def _edge_link(self, edge, engine: SimulationEngine, link_type: str) -> Dict:
        source = engine.agents.get(edge.source_agent_id) or engine.projects.get(edge.source_agent_id)
        target = engine.agents.get(edge.target_agent_id) or engine.projects.get(edge.target_agent_id)
        if not source or not target:
            return {}
        source_region = getattr(source, "region", "Shenzhen")
        target_region = getattr(target, "region", "Shenzhen")
        source_coords = CITY_COORDS.get(source_region, CITY_COORDS["Shenzhen"])
        target_coords = CITY_COORDS.get(target_region, CITY_COORDS["Shenzhen"])
        return {
            "link_id": f"{link_type}_{edge.source_agent_id}_{edge.target_agent_id}_{edge.project_id}",
            "source_id": edge.source_agent_id,
            "target_id": edge.target_agent_id,
            "source_latitude": source_coords["latitude"],
            "source_longitude": source_coords["longitude"],
            "target_latitude": target_coords["latitude"],
            "target_longitude": target_coords["longitude"],
            "link_type": link_type,
            "strength": round(edge.strength, 3),
            "cross_city": edge.cross_region,
            "status": "active",
        }

    def _edge_link_from_dict(self, edge: Dict, agents: Dict, projects: Dict, link_type: str) -> Dict:
        source_id = edge.get("source_agent_id") or edge.get("source_id")
        target_id = edge.get("target_agent_id") or edge.get("target_id")
        source = agents.get(source_id) or projects.get(source_id)
        target = agents.get(target_id) or projects.get(target_id)
        if not source or not target:
            return {}
        source_region = source.get("region", "Shenzhen")
        target_region = target.get("region", "Shenzhen")
        source_coords = CITY_COORDS.get(source_region, CITY_COORDS["Shenzhen"])
        target_coords = CITY_COORDS.get(target_region, CITY_COORDS["Shenzhen"])
        project_id = edge.get("project_id", "")
        return {
            "link_id": f"{link_type}_{source_id}_{target_id}_{project_id}",
            "source_id": source_id,
            "target_id": target_id,
            "source_latitude": source_coords["latitude"],
            "source_longitude": source_coords["longitude"],
            "target_latitude": target_coords["latitude"],
            "target_longitude": target_coords["longitude"],
            "link_type": link_type,
            "strength": round(float(edge.get("strength", 0.5)), 3),
            "cross_city": bool(edge.get("cross_region", source_region != target_region)),
            "status": "active",
        }

    def _resource_link(self, project, engine: SimulationEngine) -> Dict:
        supplier_id = project.selected_supplier_ids[0] if project.selected_supplier_ids else "S001"
        target_id = project.selected_contractor_id or project.project_id
        supplier = engine.agents.get(supplier_id)
        target = engine.agents.get(target_id) or project
        if not supplier:
            return {}
        source_region = supplier.region
        target_region = getattr(target, "region", project.region)
        source_coords = CITY_COORDS.get(source_region, CITY_COORDS["Foshan"])
        target_coords = CITY_COORDS.get(target_region, CITY_COORDS["Shenzhen"])
        strength = self._clamp(project.performance.material_availability)
        return {
            "link_id": f"resource_{supplier_id}_{target_id}_{project.project_id}",
            "project_id": project.project_id,
            "source_id": supplier_id,
            "target_id": target_id,
            "source_city": source_region,
            "target_city": target_region,
            "source_latitude": source_coords["latitude"],
            "source_longitude": source_coords["longitude"],
            "target_latitude": target_coords["latitude"],
            "target_longitude": target_coords["longitude"],
            "link_type": "resource_flow",
            "strength": round(strength, 3),
            "flow_volume": round(self._project_resource_flow_volume(project, strength), 2),
            "cross_city": source_region != target_region,
            "status": "active",
        }

    def _resource_link_from_dict(self, project: Dict, agents: Dict) -> Dict:
        supplier_ids = project.get("selected_supplier_ids") or []
        supplier_id = supplier_ids[0] if supplier_ids else ""
        target_id = project.get("selected_contractor_id") or project.get("project_id")
        supplier = agents.get(supplier_id)
        target = agents.get(target_id) or project
        if not supplier:
            return {}
        source_region = supplier.get("region")
        target_region = target.get("region", project.get("region", "Shenzhen"))
        source_coords = CITY_COORDS.get(source_region, CITY_COORDS["Foshan"])
        target_coords = CITY_COORDS.get(target_region, CITY_COORDS["Shenzhen"])
        performance = project.get("performance", {})
        strength = self._clamp(self._safe_float(performance.get("material_availability"), 1.0))
        return {
            "link_id": f"resource_{supplier_id}_{target_id}_{project.get('project_id', '')}",
            "project_id": project.get("project_id", ""),
            "source_id": supplier_id,
            "target_id": target_id,
            "source_city": source_region,
            "target_city": target_region,
            "source_latitude": source_coords["latitude"],
            "source_longitude": source_coords["longitude"],
            "target_latitude": target_coords["latitude"],
            "target_longitude": target_coords["longitude"],
            "link_type": "resource_flow",
            "strength": round(strength, 3),
            "flow_volume": round(self._project_resource_flow_volume(project, strength), 2),
            "cross_city": source_region != target_region,
            "status": "active",
        }

    def _fallback_links(self, engine: SimulationEngine) -> list[Dict]:
        project = next(iter(engine.projects.values()), None)
        if not project:
            return []
        fallback_edges = [
            ("O001", "A001"),
            ("O001", "Q001"),
            ("O001", "C003"),
            ("C003", "S001"),
        ]
        links = []
        for source_id, target_id in fallback_edges:
            source = engine.agents.get(source_id)
            target = engine.agents.get(target_id)
            if not source or not target:
                continue
            source_coords = CITY_COORDS.get(source.region, CITY_COORDS["Shenzhen"])
            target_coords = CITY_COORDS.get(target.region, CITY_COORDS["Shenzhen"])
            links.append(
                {
                    "link_id": f"fallback_{source_id}_{target_id}",
                    "source_id": source_id,
                    "target_id": target_id,
                    "source_latitude": source_coords["latitude"],
                    "source_longitude": source_coords["longitude"],
                    "target_latitude": target_coords["latitude"],
                    "target_longitude": target_coords["longitude"],
                    "link_type": "collaboration_link",
                    "strength": 0.7,
                    "cross_city": source.region != target.region,
                    "status": "active",
                }
            )
        return links

    def _project_status(self, stage) -> str:
        if isinstance(stage, str):
            if stage == ProjectStage.CLOSED.value:
                return "completed"
            if stage == ProjectStage.SUSPENDED.value:
                return "suspended"
            if stage == ProjectStage.FAILED.value:
                return "failed"
            if stage in {ProjectStage.CONSTRUCTION.value, ProjectStage.COMPLETION.value, ProjectStage.FINAL_ACCOUNT.value}:
                return "ongoing"
            return "building"
        if stage == ProjectStage.CLOSED:
            return "completed"
        if stage == ProjectStage.SUSPENDED:
            return "suspended"
        if stage == ProjectStage.FAILED:
            return "failed"
        if stage in {ProjectStage.CONSTRUCTION, ProjectStage.COMPLETION, ProjectStage.FINAL_ACCOUNT}:
            return "ongoing"
        return "building"

    def _runtime_status(self, status: str) -> str:
        return {
            "created": "not_started",
            "running": "running",
            "paused": "paused",
            "completed": "completed",
            "failed": "failed",
        }.get(status, "running")

    @staticmethod
    def _is_recoverable_generation_error(exc: Exception) -> bool:
        if isinstance(exc, CamelDecisionError):
            return True
        message = str(exc).lower()
        return "camel" in message or "model" in message or "zhipu" in message or "openai" in message

    def _effective_tick(self, engine: SimulationEngine, tick: Optional[int]) -> int:
        if tick is None:
            return engine.current_tick
        return max(1, min(int(tick), max(engine.current_tick, 1)))

    def _snapshot_for_tick(self, engine: SimulationEngine, tick: Optional[int]) -> Optional[Dict]:
        snapshots = self._ordered_tick_snapshots(engine)
        if not snapshots:
            return None
        effective_tick = self._effective_tick(engine, tick)
        selected = snapshots[0]
        for snapshot in snapshots:
            if int(snapshot.get("tick", 0)) <= effective_tick:
                selected = snapshot
            else:
                break
        return selected

    @staticmethod
    def _ordered_tick_snapshots(engine: SimulationEngine) -> list[Dict]:
        snapshots_by_tick: Dict[int, Dict] = {}
        for snapshot in engine.result_store.tick_snapshots:
            tick_value = int(snapshot.get("tick", 0) or 0)
            if tick_value > 0:
                snapshots_by_tick[tick_value] = snapshot
        return [snapshots_by_tick[tick] for tick in sorted(snapshots_by_tick)]

    def _snapshot_project_rows(self, snapshot: Optional[Dict]) -> list:
        if not snapshot:
            return []
        return list(snapshot.get("projects", {}).values())

    def _performance_dict(self, project) -> Dict:
        if isinstance(project, dict):
            return project.get("performance", {})
        return project.performance.dict()

    def _project_stage_value(self, project) -> str:
        if isinstance(project, dict):
            stage = project.get("current_stage", "")
            return stage.value if hasattr(stage, "value") else str(stage)
        return project.current_stage.value if hasattr(project.current_stage, "value") else str(project.current_stage)

    def _engaged_agent_sets(self, projects: list) -> tuple[set, set]:
        active_statuses = {"active", "standby", "invited", "bidding"}
        active = set()
        all_engaged = set()
        for project in projects:
            engagements = project.get("engagements", []) if isinstance(project, dict) else project.engagements
            for engagement in engagements:
                agent_id = engagement.get("agent_id") if isinstance(engagement, dict) else engagement.agent_id
                status = engagement.get("status") if isinstance(engagement, dict) else engagement.status.value
                if agent_id:
                    all_engaged.add(agent_id)
                if agent_id and status in active_statuses:
                    active.add(agent_id)
        return active, all_engaged

    def _visible_snapshot_agents(self, agents: Dict, projects: Dict, engine: Optional[SimulationEngine] = None) -> list:
        compact_total = 0
        if engine:
            compact_total = len(engine.agents)
        if len(agents) <= VISIBLE_ENTERPRISE_LIMIT and compact_total <= VISIBLE_ENTERPRISE_LIMIT:
            return list(agents.values())
        linked_ids = {
            engagement.get("agent_id")
            for project in projects.values()
            for engagement in project.get("engagements", [])
            if engagement.get("agent_id")
        }
        if engine and compact_total > len(agents):
            engine_agent_rows = {
                agent_id: agent.dict()
                for agent_id, agent in engine.agents.items()
            }
            source_agents = {**engine_agent_rows, **agents}
        else:
            source_agents = agents
        linked = [agent for agent in source_agents.values() if agent.get("agent_id") in linked_ids]
        free = [agent for agent in source_agents.values() if agent.get("agent_id") not in linked_ids]
        return linked + self._balanced_visible_agents(
            free,
            max_count=max(0, VISIBLE_ENTERPRISE_LIMIT - len(linked)),
        )

    def _balanced_visible_agents(self, agents: list[Dict], max_count: int) -> list[Dict]:
        if len(agents) <= max_count:
            return agents

        city_order = list(CITY_COORDS.keys())
        role_order = ["Owner", "Contractor", "Supplier", "Architect", "QS", "Government"]
        city_rank = {city: index for index, city in enumerate(city_order)}
        role_rank = {role: index for index, role in enumerate(role_order)}
        buckets: Dict[str, list[Dict]] = {city: [] for city in city_order}
        overflow: list[Dict] = []
        for agent in agents:
            region = agent.get("region", "")
            if region in buckets:
                buckets[region].append(agent)
            else:
                overflow.append(agent)

        def rank(agent: Dict) -> tuple:
            return (
                role_rank.get(agent.get("role", ""), 99),
                -float(agent.get("cross_region_experience", 0.0) or 0.0),
                -float(agent.get("collaboration_preference", 0.0) or 0.0),
                agent.get("agent_id", ""),
            )

        for bucket in buckets.values():
            bucket.sort(key=rank)
        overflow.sort(key=lambda agent: (city_rank.get(agent.get("region", ""), 99), *rank(agent)))

        selected: list[Dict] = []
        while len(selected) < max_count and any(buckets.values()):
            for city in city_order:
                if len(selected) >= max_count:
                    break
                bucket = buckets[city]
                if bucket:
                    selected.append(bucket.pop(0))

        if len(selected) < max_count:
            selected.extend(overflow[: max_count - len(selected)])
        return selected

    def _dominant_status(self, statuses: list[str]) -> str:
        for status in ["active", "bidding", "invited", "standby", "candidate", "released", "terminated"]:
            if status in statuses:
                return status
        return "free"

    def _event_dict(self, event) -> Dict:
        data = event.dict() if hasattr(event, "dict") else dict(event)
        data["stage"] = self._value(data.get("stage"))
        return data

    def _engagement_dict(self, engagement) -> Dict:
        data = engagement.dict() if hasattr(engagement, "dict") else dict(engagement)
        for key in ["status", "start_stage", "expected_end_stage", "actual_end_stage"]:
            data[key] = self._value(data.get(key))
        return data

    def _value(self, value):
        if value is None:
            return None
        return value.value if hasattr(value, "value") else value


simulation_runtime_service = SimulationRuntimeService()
