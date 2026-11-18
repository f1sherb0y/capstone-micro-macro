"""Optional procurement plugin, assembled outside the GBA source tree."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import random

from gba_construction_sim.backend.core.enums import EngagementStatus, ProjectStage
from gba_construction_sim.backend.simulation.macro_environment import MacroEnvironmentUpdater
from integration.contracts import CommitRejected, DecisionSnapshot, IntegrationError, digest
from integration.decision_context import CONTEXT_VERSION, build_own_state
from integration.gba_commit import ContractCommitter
from integration.gba_execution import ContractStateUpdater
from integration.sessions import OrganizationRegistry, ProcurementSession, atomic_json


class CodedemoProcurementExecutor:
    def __init__(self, dataset, llm, directory, profile="smoke", max_rounds=3, seed_rosters=None, restore_initial=False):
        self.dataset, self.llm, self.directory = dataset, llm, Path(directory)
        self.profile, self.max_rounds = profile, max_rounds
        self.sessions = {}
        self.rounds = {}
        self.engine = None
        self.seed_rosters = seed_rosters or {}
        self.restore_initial = restore_initial

    def supports(self, execution):
        return execution.mode == "codedemo_micro" and execution.scope == "full_procurement" and execution.adapter_profile_id == "codedemo-local"

    def attach(self, engine):
        if self.engine is not None:
            raise IntegrationError("An executor cannot be shared between simulations")
        if not self.supports(engine.procurement_execution):
            raise IntegrationError("Executor requires explicit codedemo-local micro procurement mode")
        if set(engine.projects) != set(self.dataset.projects):
            raise IntegrationError("Macro projects differ from the shared input")
        for key, company in self.dataset.companies.items():
            agent = engine.agents.get(key)
            if agent is None or agent.semantic_memory.get("shared_data_version") != self.dataset.version:
                raise IntegrationError("Macro enterprises differ from the shared input/version")
        if engine.enable_project_generation:
            raise IntegrationError("Shared procurement requires explicit projects")
        self.engine = engine
        provider = getattr(engine, "decision_provider", None)
        if provider is None:
            provider = getattr(getattr(engine, "lifecycle_engine", None), "decision_provider", None)
        self.macro_binding = getattr(provider, "macro_binding", None)
        self.directory.mkdir(parents=True, exist_ok=True)
        manifest = self.directory / "run.json"
        if manifest.exists():
            if not self.restore_initial:
                raise IntegrationError("Run directory already exists; use a new directory (full engine restart restore is not supported)")
            previous = json.loads(manifest.read_text(encoding="utf-8"))
            if previous.get("decision_context_version") != CONTEXT_VERSION:
                raise IntegrationError("Decision context version changed; use a new run directory instead of old checkpoints")
            result = json.loads((self.directory / "result.json").read_text(encoding="utf-8"))
            if result["simulation"]["current_tick"] != 0 or previous["data_version"] != self.dataset.version:
                raise IntegrationError("Initial-window recovery requires tick zero and identical shared input")
            engine.simulation_id = previous["simulation_id"]
        self.registry = OrganizationRegistry(engine.simulation_id, self.directory)
        self.registry.rosters.update(deepcopy(self.seed_rosters))
        self.registry.save()
        self.committer = ContractCommitter(engine, self.dataset)
        engine.lifecycle_engine = ProcurementLifecycle(engine.lifecycle_engine, self)
        engine.state_update_engine = ContractStateUpdater(engine.state_update_engine, self.dataset)
        engine.events.add_observer(self.observe)
        if self.macro_binding is not None:
            self.macro_binding.bind_observer(engine.simulation_id,
                "integration.gba_adapter.CodedemoProcurementExecutor.observe")
        atomic_json(manifest, {"schema_version": "1.0", "simulation_id": engine.simulation_id,
                               "data_version": self.dataset.version, "procurement": engine.procurement_execution.dict(),
                               "supported_delivery_mode": "DBB", "non_procurement": "gba_native",
                               "assumptions": self.dataset.payload["assumptions"],
                               "decision_context_version": CONTEXT_VERSION})

    def contracts(self, project):
        return project.flags.get("package_contracts", {})

    def specs(self, project, kinds=None):
        return [p for p in self.dataset.packages if p.project_id == project.project_id and (kinds is None or p.kind in kinds)]

    def ready(self, project, spec):
        return spec.package_id not in self.contracts(project) and set(spec.depends_on).issubset(self.contracts(project))

    def stage_target(self, project, spec):
        stage = project.current_stage
        if stage == ProjectStage.INITIATION and spec.kind in {"design", "cost_consulting"}:
            return "signatures"
        if spec.kind == "construction":
            return {ProjectStage.TENDER_PREPARATION: "requirements", ProjectStage.TENDERING: "bids",
                    ProjectStage.BID_EVALUATION: "award", ProjectStage.CONTRACT_AWARD: "signatures"}.get(stage)
        if stage == ProjectStage.CONTRACT_AWARD and spec.kind == "supply":
            return "signatures"
        return None

    def prepare_tick(self, engine):
        # Native tick updates the external environment first. Preview using an
        # independent RNG copy so failed LLM work cannot consume a tick/random draw.
        future_environment = engine.macro_environment.model_copy(deep=True)
        future_rng = random.Random()
        future_rng.setstate(engine.rng.getstate())
        MacroEnvironmentUpdater(future_rng).update(future_environment, engine.current_tick + 1)
        # Preview scheduled policy/environment changes without publishing events
        # or mutating the real controller's once-only event IDs.
        from gba_construction_sim.backend.simulation.event_system import EventSystem
        from copy import copy
        future_policy = engine.policy.model_copy(deep=True)
        preview = copy(engine.workflow_runtime)
        preview.__dict__ = {key: deepcopy(value) for key, value in engine.workflow_runtime.__dict__.items()
                            if key not in {"events", "policy", "macro_environment"}}
        preview.policy, preview.macro_environment, preview.events = future_policy, future_environment, EventSystem()
        preview.apply_tick(engine.current_tick + 1)
        self.prepared_environment = future_environment.dict()
        self.prepared_policy = future_policy.model_dump()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise IntegrationError("Call the synchronous GBA step from a worker thread, not an active asyncio loop")
        asyncio.run(self._prepare(future_environment))

    async def _prepare(self, future_environment):
        for project in self.engine.projects.values():
            for spec in self.specs(project):
                target = self.stage_target(project, spec)
                if target is None or not self.ready(project, spec):
                    continue
                round_id = self.rounds.get(spec.package_id, 1)
                if round_id > self.max_rounds:
                    continue
                key = (spec.package_id, round_id)
                session = self.sessions.get(key)
                if session is None:
                    buyer = spec.buyer_id
                    if buyer == "$construction_lead":
                        buyer = self.contracts(project)[spec.parent_package_id]["lead_id"]
                    entities = [buyer, *spec.candidate_ids]
                    private = {entity: build_own_state(self.engine, self.dataset, self.registry, entity, spec)
                               for entity in entities}
                    snapshot = DecisionSnapshot(self.engine.simulation_id, project.project_id, spec.package_id, round_id,
                                                self.engine.current_tick + 1,
                                                {"environment": future_environment.dict(), "policy": self.prepared_policy,
                                                 "scenario_assumptions": {k: self.dataset.payload["assumptions"].get(k)
                                                                          for k in ("version", "source_note", "eligibility", "units", "contract_framework")
                                                                          if k != "contract_framework" or k in self.dataset.payload["assumptions"]},
                                                 "currency": spec.currency, "package_budget": spec.budget,
                                                 "project": self.dataset.projects[project.project_id],
                                                 "package": asdict(spec)}, private, self.dataset.version)
                    session = ProcurementSession(self.dataset, spec, snapshot, buyer, self.registry,
                                                 self.llm, self.directory / "sessions", self.profile)
                    self.sessions[key] = session
                await session.advance_to(target)

    def session(self, spec):
        return self.sessions.get((spec.package_id, self.rounds.get(spec.package_id, 1)))

    def finish(self, project, spec, tick):
        session = self.session(spec)
        if session is None or session.next_stage < 9:
            return
        if spec.package_id in self.contracts(project):
            return
        try:
            receipt = self.committer.commit(session, tick)
        except CommitRejected as exc:
            session.status = "rejected" if session.proposal else "no_contract"
            session.error = str(exc)
            session.save()
            # A rejected signature is a business outcome. Keep its feedback in
            # the participating organizations' memory for the next round.
            authorizations = next((row for row in reversed(session.state.tender_process_log)
                                   if row.get("event_type") == "contract_authorizations"), None)
            if authorizations:
                decisions = authorizations["decisions"]
                self.registry.observe(session.session_id + "/contract-feedback", list(decisions),
                    {"event_type": "contract_revision_requested", "tick": tick,
                     "project_id": project.project_id, "package_id": spec.package_id,
                     "round": session.snapshot.round_id, "decisions": decisions,
                     "committed": False})
            recipients = [session.buyer_id, *(session.proposal.members if session.proposal else [])]
            self.registry.observe(session.session_id + "/commit-rejected", recipients,
                {"event_type": "procurement_commit_rejected", "tick": tick,
                 "project_id": project.project_id, "package_id": spec.package_id,
                 "round": session.snapshot.round_id, "reason": str(exc), "committed": False})
            self.rounds[spec.package_id] = self.rounds.get(spec.package_id, 1) + 1
            project.performance.delay_days += 7
            self.engine.events.record(tick, "procurement_round_rejected", str(exc), project=project,
                                      data={"package_id": spec.package_id, "round": session.snapshot.round_id,
                                            "buyer_id": session.buyer_id, "members": [], "decision_source": "micro"})
            if self.rounds[spec.package_id] > self.max_rounds:
                project.current_stage = ProjectStage.SUSPENDED
            elif spec.kind == "construction":
                self.engine.lifecycle_engine.native._transition(project, ProjectStage.TENDER_PREPARATION, tick, "New procurement round after business rejection")
            return
        session.status = "committed"
        session.save()
        return receipt

    def observe(self, event, project=None):
        if project is None:
            return
        if event.event_type == "package_contract_committed":
            data = event.data
            recipients = [data["buyer_id"], *data["members"]]
            payload = {"event_type": event.event_type, "tick": event.tick, "project_id": project.project_id, **data, "committed": True}
        elif event.event_type == "project_state_updated":
            recipients = sorted({project.owner_id, *(m for c in self.contracts(project).values() for m in c["members"])})
            payload = {"event_type": event.event_type, "tick": event.tick, "project_id": project.project_id,
                       "stage": project.current_stage.value, "actual_progress": project.performance.actual_progress,
                       "delay_days": project.performance.delay_days, "committed": True}
        elif event.event_type in {"agent_engaged", "agent_recalled", "agent_standby",
                                  "agent_released", "agent_terminated"}:
            # Allocation details belong to the affected enterprise, not every bidder.
            if event.agent_id not in self.dataset.companies:
                return
            recipients = [event.agent_id]
            agent = self.engine.agents[event.agent_id]
            payload = {"event_type": event.event_type, "tick": event.tick,
                       "project_id": project.project_id, "role": event.data.get("role"),
                       "available_resource": agent.available_resource(),
                       "occupied_resource": agent.occupied_resource, "committed": True}
        else:
            return
        event_id = f"{self.engine.simulation_id}/{event.event_id}"
        self.registry.observe(event_id, recipients, payload)
        if self.macro_binding is not None:
            self.macro_binding.observe(event_id, recipients, payload)

    def status(self):
        return {"mode": "codedemo_micro", "data_version": self.dataset.version,
                "sessions": [{"session_id": s.session_id, "package_id": s.spec.package_id, "status": s.status,
                              "next_stage": s.next_stage, "error": s.error} for s in self.sessions.values()]}


class ProcurementLifecycle:
    def __init__(self, native, executor):
        self.native, self.executor = native, executor

    def __getattr__(self, name):
        return getattr(self.native, name)

    def step(self, project, agents, policy, macro_environment, tick):
        stage = project.current_stage
        procurement_stages = {ProjectStage.INITIATION, ProjectStage.TENDER_PREPARATION, ProjectStage.TENDERING,
                              ProjectStage.BID_EVALUATION, ProjectStage.CONTRACT_AWARD}
        if stage not in procurement_stages:
            self.native.step(project, agents, policy, macro_environment, tick)
            return
        if macro_environment.dict() != self.executor.prepared_environment:
            raise IntegrationError("Environment changed after procurement preparation")
        if policy.model_dump() != self.executor.prepared_policy:
            raise IntegrationError("Policy changed after procurement preparation")
        project.stage_tick += 1
        ex = self.executor
        minimum = {ProjectStage.INITIATION: self.native.MIN_INITIATION_TICKS,
                   ProjectStage.TENDER_PREPARATION: self.native.MIN_TENDER_PREPARATION_TICKS,
                   ProjectStage.BID_EVALUATION: self.native.MIN_BID_EVALUATION_TICKS}.get(stage, 1)
        if project.stage_tick < minimum:
            return
        if stage == ProjectStage.INITIATION:
            for spec in ex.specs(project, {"design", "cost_consulting"}):
                if ex.ready(project, spec):
                    ex.finish(project, spec, tick)
            if project.current_stage == ProjectStage.SUSPENDED:
                return
            if all(s.package_id in ex.contracts(project) for s in ex.specs(project, {"design", "cost_consulting"})):
                self.native._ensure_engagement(project, agents[project.owner_id], "Owner", EngagementStatus.ACTIVE, tick, 0.25)
                project.performance.planned_cost = project.initial_budget
                self.native._transition(project, ProjectStage.DESIGN, tick, "Micro consultant procurement committed")
        elif stage == ProjectStage.TENDER_PREPARATION:
            specs = [s for s in ex.specs(project, {"construction"}) if ex.ready(project, s)]
            if specs and all(ex.session(s) and ex.session(s).next_stage >= 1 for s in specs):
                self.native._transition(project, ProjectStage.TENDERING, tick, "Micro package requirements approved")
        elif stage == ProjectStage.TENDERING:
            specs = [s for s in ex.specs(project, {"construction"}) if ex.ready(project, s)]
            if specs and all(ex.session(s) and ex.session(s).next_stage >= 5 for s in specs):
                project.bids = [{**asdict(b), "contractor_id": b.bidder_id, "bid_price": b.quotation,
                                 "decision_source": "codedemo_micro"}
                                for spec in ex.specs(project, {"construction"}) if ex.session(spec)
                                for b in ex.session(spec).state.bid_documents]
                self.native._transition(project, ProjectStage.BID_EVALUATION, tick, "Micro sealed bids registered")
        elif stage == ProjectStage.BID_EVALUATION:
            specs = [s for s in ex.specs(project, {"construction"}) if ex.ready(project, s)]
            if specs and all(ex.session(s) and ex.session(s).next_stage >= 8 for s in specs):
                self.native._transition(project, ProjectStage.CONTRACT_AWARD, tick, "Micro evaluation and award intentions recorded")
        elif stage == ProjectStage.CONTRACT_AWARD:
            for spec in ex.specs(project, {"construction", "supply"}):
                if ex.ready(project, spec):
                    ex.finish(project, spec, tick)
                if project.current_stage != stage:
                    return
            if all(s.package_id in ex.contracts(project) for s in ex.specs(project)):
                project.flags["contract_signed"] = True
                project.flags["supplier_selected"] = True
                self.native._complete_mobilization(project, agents, tick)
                self.native._transition(project, ProjectStage.CONSTRUCTION, tick, "All micro package contracts committed and supplies mobilized")
            elif any(ex.ready(project, s) and ex.session(s) is None
                     for s in ex.specs(project, {"construction"})):
                # A committed predecessor can unlock another procurement batch.
                # Create its session next tick, with the updated resource ledger.
                self.native._transition(project, ProjectStage.TENDER_PREPARATION, tick,
                                        "Predecessor contract committed; prepare newly ready construction packages")
