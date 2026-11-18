from threading import Event, Thread
import time

from gba_construction_sim.backend.models.action import AgentAction
from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
from gba_construction_sim.backend.simulation.action_applier import ActionApplier
from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine


def test_action_applier_serializes_same_project_and_agent_mutations():
    applier = ActionApplier()
    first_entered = Event()
    release_first = Event()
    order = []

    def first_mutation():
        order.append("first_start")
        first_entered.set()
        release_first.wait(timeout=2)
        order.append("first_end")

    def second_mutation():
        order.append("second_start")

    first = Thread(target=lambda: applier.apply_project_mutation("P-LOCK", ["A-LOCK"], first_mutation))
    second = Thread(target=lambda: applier.apply_project_mutation("P-LOCK", ["A-LOCK"], second_mutation))

    first.start()
    assert first_entered.wait(timeout=1)
    second.start()
    time.sleep(0.05)
    assert order == ["first_start"]
    release_first.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert order == ["first_start", "first_end", "second_start"]


def test_simulation_step_routes_project_state_changes_through_action_applier():
    engine = SimulationEngine.from_request(SimulationCreateRequest(ticks=1, random_seed=42))
    calls = []

    class CapturingActionApplier:
        def apply_project_update(self, project, agents, apply_one):
            calls.append(project.project_id)
            apply_one()

    engine.action_applier = CapturingActionApplier()

    engine.step(return_snapshot=False)

    assert "P001" in calls
    assert calls.count("P001") >= 2


def test_owner_project_generation_routes_creation_through_action_applier():
    engine = SimulationEngine.from_request(
        SimulationCreateRequest(
            ticks=1,
            random_seed=42,
            enable_project_generation=True,
            target_project_count=1,
            max_active_projects=1,
        )
    )
    owner = next(agent for agent in engine.agents.values() if agent.role == "Owner")
    calls = []

    class CapturingActionApplier:
        def apply_project_mutation(self, project_id, agent_ids, apply_one):
            calls.append(("mutation", project_id, tuple(agent_ids)))
            apply_one()

        def apply_project_update(self, project, agents, apply_one):
            calls.append(("update", project.project_id, ()))
            apply_one()

    def accept_owner_initiation(owner_agent, project_id, *_args, **_kwargs):
        return AgentAction(
            action_type="initiate_project",
            project_id=project_id,
            agent_id=owner_agent.agent_id,
            decision=True,
            reason="Owner has enough capital and resource to initiate the project.",
        )

    engine.action_applier = CapturingActionApplier()
    engine._rank_owner_project_decisions = lambda _opportunity, _target_by_tick: [(owner, 0.95, 1.0, {"test": True})]
    engine._owner_initiation_advisor = accept_owner_initiation

    engine.step(return_snapshot=False)

    assert ("mutation", "PGEN0001", (owner.agent_id,)) in calls
    assert "PGEN0001" in engine.projects
