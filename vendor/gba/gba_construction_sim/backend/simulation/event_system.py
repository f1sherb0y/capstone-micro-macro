from typing import Callable, Dict, Iterable, List, Optional

from gba_construction_sim.backend.core.enums import ProjectStage
from gba_construction_sim.backend.models.event import SimulationEvent
from gba_construction_sim.backend.models.project import ConstructionProject


class EventSystem:
    def __init__(
        self,
        observers: Optional[
            Iterable[Callable[[SimulationEvent, Optional[ConstructionProject]], None]]
        ] = None,
    ) -> None:
        self.events: List[SimulationEvent] = []
        self._counter = 0
        self._observers = list(observers or [])

    def add_observer(
        self,
        observer: Callable[[SimulationEvent, Optional[ConstructionProject]], None],
    ) -> None:
        if observer not in self._observers:
            self._observers.append(observer)

    def record(
        self,
        tick: int,
        event_type: str,
        description: str,
        project: Optional[ConstructionProject] = None,
        agent_id: Optional[str] = None,
        stage: Optional[ProjectStage] = None,
        data: Optional[Dict] = None,
    ) -> SimulationEvent:
        self._counter += 1
        event = SimulationEvent(
            event_id=f"EVT{self._counter:06d}",
            tick=tick,
            project_id=project.project_id if project else None,
            agent_id=agent_id,
            event_type=event_type,
            stage=stage or (project.current_stage if project else None),
            description=description,
            data=data or {},
        )
        self.events.append(event)
        try:
            from gba_construction_sim.backend.services.agent_cognitive_service import agent_cognitive_service

            agent_cognitive_service.record_simulation_event(event, project=project)
        except Exception as exc:
            event.data["cognition_error"] = str(exc)
        if project:
            project.event_log.append(event.dict())
        for observer in self._observers:
            try:
                observer(event, project)
            except Exception as exc:
                event.data.setdefault("agent_observer_errors", []).append(str(exc))
        return event

    def by_project(self, project_id: str) -> List[SimulationEvent]:
        return [event for event in self.events if event.project_id == project_id]

    def by_agent(self, agent_id: str) -> List[SimulationEvent]:
        return [event for event in self.events if event.agent_id == agent_id]
