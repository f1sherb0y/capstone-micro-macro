"""Read-only, entity-scoped facts and bounded event recall for procurement.

Contract commitments are historical promises; engagements and enterprise totals
are the current resource ledger. Never infer current allocation from old promises.
"""
from copy import deepcopy
from dataclasses import asdict


CONTEXT_VERSION = "enterprise-task-context.v1"
MEMORY_LIMIT = 12


def select_memory(events, project_id, package_id, limit=MEMORY_LIMIT):
    """Keep significant events before progress, then return chronological copies.

Only the latest progress observation per project competes for the bounded view.
The caller supplies this enterprise's authorized history, never a shared log.
Full events remain in OrganizationRegistry for audit and recovery.
"""
    if limit < 1:
        raise ValueError("Memory limit must be positive")
    latest_progress = {}
    candidates = []
    for index, event in enumerate(events):
        if event.get("event_type") == "project_state_updated":
            latest_progress[event.get("project_id")] = (index, event)
        else:
            candidates.append((index, event))
    candidates.extend(latest_progress.values())

    def priority(item):
        index, event = item
        return (event.get("event_type") != "project_state_updated",
                event.get("package_id") == package_id,
                event.get("project_id") == project_id, index)

    selected = sorted(candidates, key=priority, reverse=True)[:limit]
    selected.sort(key=lambda item: item[0])
    return deepcopy([event for _, event in selected])


def build_own_state(engine, dataset, registry, entity_id, spec):
    """Project only this party's contracts and engagements across explicit projects.

Engagement allocation is at project/role level in GBA, not per package. Expose
that granularity rather than attributing one combined reservation to every lot.
"""
    agent = engine.agents[entity_id]
    engagements, contracts = [], []
    for project in sorted(engine.projects.values(), key=lambda p: p.project_id):
        own_engagements = [e for e in project.engagements if e.agent_id == entity_id]
        for engagement in own_engagements:
            engagements.append({
                "engagement_id": engagement.engagement_id,
                "project_id": project.project_id,
                "project_stage": project.current_stage.value,
                "role": engagement.role,
                "status": engagement.status.value,
                "resource_allocation": engagement.resource_allocation,
                "contractual_obligation": engagement.contractual_obligation,
                "can_be_recalled": engagement.can_be_recalled,
                "joined_at_tick": engagement.joined_at_tick,
                "released_at_tick": engagement.released_at_tick,
            })
        for package_id, contract in sorted(project.flags.get("package_contracts", {}).items()):
            is_member = entity_id in contract["members"]
            if not is_member and entity_id != contract["buyer_id"]:
                continue
            execution = project.flags.get("package_execution", {}).get(package_id, {})
            contracts.append({
                "contract_id": contract["contract_id"], "project_id": project.project_id,
                "package_id": package_id, "kind": contract["kind"],
                "party_role": "member" if is_member else "buyer",
                "signed_tick": contract["signed_tick"], "status": contract["status"],
                "project_stage": project.current_stage.value,
                "price": contract["price"], "currency": contract["currency"],
                "own_committed_resource": contract["resource_commitments"].get(entity_id, 0),
                "own_work_share": contract["work_shares"].get(entity_id, 0),
                "package_progress": execution.get("performance", {}).get("actual_progress"),
            })
    events = registry.memories.get(entity_id, [])
    memory = select_memory(events, spec.project_id, spec.package_id)
    return {
        "entity_id": entity_id, "available_resource": agent.available_resource(),
        "occupied_resource": agent.occupied_resource,
        "total_resource_capacity": agent.total_resource_capacity,
        "company_profile": asdict(dataset.companies[entity_id]),
        "enterprise_parameters": {key: value for key, value in agent.model_dump().items()
                                  if key not in {"episodic_memory", "semantic_memory"}},
        "resource_unit": "normalized_enterprise_capacity",
        "task_state": {
            "schema_version": CONTEXT_VERSION,
            "observed_tick": engine.current_tick,
            "source": "committed_macro_state",
            "resource_accounting": "enterprise totals and project-role engagements are current; "
                                   "contract commitments are signed promises, not extra reservations; "
                                   "a buyer's purchase does not itself reserve the buyer's resources",
            "engagements": engagements, "contracts": contracts,
        },
        "memory": memory,
        "memory_selection": {"policy": "significant_then_relevant_then_recent.v1",
                             "limit": MEMORY_LIMIT, "total_events": len(events),
                             "selected_events": len(memory),
                             "omitted_events": len(events) - len(memory),
                             "note": "Historical events explain changes; task_state and current resource "
                                     "totals are authoritative. Full history is retained in the audit."},
    }
