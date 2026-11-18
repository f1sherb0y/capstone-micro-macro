from __future__ import annotations

import datetime as dt
from copy import deepcopy

from src.models import Company, MemberAgent, SimulationState, TenderPackage


def log_event(state: SimulationState, event_type: str, payload: dict) -> None:
    state.tender_process_log.append(
        {
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "event_type": event_type,
            "payload": deepcopy(payload),
        }
    )


def final_agent(agents: list[MemberAgent]) -> MemberAgent:
    return next((agent for agent in agents if agent.decision_authority == "final"), agents[-1])


def company_by_role(state: SimulationState, role: str) -> list[Company]:
    return [company for company in state.companies if company.company_role == role]


def company_by_id(state: SimulationState, company_id: str) -> Company:
    return next(company for company in state.companies if company.company_id == company_id)


def package_by_id(state: SimulationState, package_id: str) -> TenderPackage:
    return next(package for package in state.tender_packages if package.package_id == package_id)
