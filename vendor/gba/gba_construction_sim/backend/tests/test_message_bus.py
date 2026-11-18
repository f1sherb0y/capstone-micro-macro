from gba_construction_sim.backend.simulation.message_bus import BusEnvelope, SimulationMessageBus
from gba_construction_sim.backend.simulation.interaction_session import InteractionSessionManager


def test_message_bus_drains_only_matching_project_session_messages():
    bus = SimulationMessageBus()
    bus.publish(
        BusEnvelope(
            message_type="DecisionRequest",
            topic="project/P001/tender",
            payload={"request_id": "R1"},
            tick=4,
            project_id="P001",
            session_id="S1",
        )
    )
    bus.publish(
        BusEnvelope(
            message_type="InteractionMessage",
            topic="project/P001/tender",
            payload={"message_id": "M1"},
            tick=4,
            project_id="P001",
            session_id="S2",
        )
    )

    drained = bus.drain(
        "project/P001/tender",
        message_type="DecisionRequest",
        project_id="P001",
        session_id="S1",
    )

    assert [envelope.payload["request_id"] for envelope in drained] == ["R1"]
    assert len(bus.peek("project/P001/tender")) == 1
    assert bus.peek("project/P001/tender")[0].payload["message_id"] == "M1"


def test_interaction_session_manager_publishes_bounded_messages_to_bus():
    bus = SimulationMessageBus()
    manager = InteractionSessionManager(bus)
    session = manager.get_or_create("P001", "contract_negotiation", ["OWNER", "CONTRACTOR", "QS"])

    manager.append_message(
        session,
        tick=10,
        sender_id="OWNER",
        recipient_ids=["CONTRACTOR", "QS"],
        topic="contract_terms",
        content="Confirm price, payment terms, programme, and risk allocation before signing.",
    )

    envelopes = bus.peek("project:P001")

    assert len(envelopes) == 1
    assert envelopes[0].message_type == "InteractionMessage"
    assert envelopes[0].session_id == "P001:contract_negotiation"
    assert envelopes[0].payload.content.startswith("Confirm price")
    assert "OWNER to CONTRACTOR,QS" in session.summary
