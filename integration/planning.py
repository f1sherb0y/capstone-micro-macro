"""The owner organization proposes bounded DBB packages from the whole project."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from src.agent_runtime import AgentRuntime
from src.models import SimulationState, dump
from src.run_audit import LLMCallAuditLogger
from src.stages.rosters import generate_member_agents
from integration.contracts import DecisionSnapshot, IntegrationError, positive
from integration.sessions import SAFE_RECOVERY, atomic_json
from integration.shared_data import SharedDataset


async def plan_dataset(dataset, client, directory, profile="smoke"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    project = next(iter(dataset.projects.values()))
    owner = dataset.companies[project["owner_id"]]
    snapshot = DecisionSnapshot(directory.name, project["project_id"], "procurement-planning", 1, 0,
        {"currency": project["currency"], "project": project, "environment": dataset.payload["environment"],
         "policy": dataset.payload["policy"], "scenario_assumptions": {k: dataset.payload["assumptions"].get(k) for k in ("version", "source_note", "eligibility", "units")}},
        {owner.company_id: {"company_profile": asdict(owner), "enterprise_parameters": dataset.payload["assumptions"]["enterprise_parameters"][owner.company_id]}}, dataset.version)
    audit = LLMCallAuditLogger(directory, project["project_id"] + "/planning", client)
    runtime = AgentRuntime(client, profile=profile, audit_logger=audit)
    runtime.context_resolver = snapshot.for_entity
    state = SimulationState(project_idea=dataset.project_idea(project["project_id"]), companies=[owner])
    state.company_agent_rosters = await generate_member_agents([owner], runtime)
    context = ("根据完整项目范围提出可分别采购、无重复计价的施工分包方案。采用 DBB，设计和造价服务在先，"
               "至少两个、最多四个并行施工包，各施工包后续自行采购材料。设计预算为总预算 3%，造价 1.5%，"
               "施工总预算 85%，其余为业主预备金。不得使用历史中标结果；预算、工期、角色资格均为公开标注的情景假设。")
    await runtime.discuss_async(state, "procurement_planning", owner, "procurement-planning",
        state.company_agent_rosters[owner.company_id], [(1, "scope_and_dependencies"), (2, "package_approval")], context)
    def validate(data):
        items = data.get("construction_packages")
        if not isinstance(items, list) or not 2 <= len(items) <= 4:
            raise ValueError("Provide 2 to 4 parallel construction packages")
        for item in items:
            if not isinstance(item.get("name"), str) or not item["name"].strip() or not isinstance(item.get("scope"), str) or not item["scope"].strip():
                raise ValueError("Every package needs a name and scope")
            positive(item.get("share"), "construction budget share")
        if abs(sum(p["share"] for p in items) - 1) > 1e-6:
            raise ValueError("Construction budget shares must sum to 1")
    import json
    decision = await runtime.for_entity(owner.company_id).ask_json_async(
        "Act as the owner organization. Return JSON with construction_packages: [{name, scope, share}], and reason. "
        "Use your members' discussion. Two parallel packages are suitable for the first trial; propose more only if justified. "
        "Each share is its fraction of the construction budget, not of the total project budget. Avoid overlapping scopes.",
        "PROCUREMENT_PLAN", context + "\nOwn discussion:\n" + json.dumps(dump(state.agent_discussion_history), ensure_ascii=False), validator=validate)
    if any(e["kind"] not in SAFE_RECOVERY for e in runtime.recovery_events):
        raise IntegrationError("Procurement planning degraded; no plan was approved")
    payload = deepcopy(dataset.payload)
    templates = {p.kind: asdict(p) for p in dataset.packages}
    payload["packages"] = [asdict(p) for p in dataset.packages if p.kind in {"design", "cost_consulting"}]
    total, assigned = round(project["budget"] * .85, 2), 0
    items = decision["construction_packages"]
    for index, item in enumerate(items):
        construction = deepcopy(templates["construction"])
        construction.update(package_id=f"{project['project_id']}/construction-{index+1}", name=item["name"], scope=item["scope"],
                            budget=round(total * item["share"], 2) if index < len(items) - 1 else round(total - assigned, 2))
        assigned += construction["budget"]
        supply = deepcopy(templates["supply"])
        # The supply scope must read as a supply contract. Appending a short suffix to the
        # full construction scope made suppliers read it as a second construction package
        # (and its "sole pricing package" wording as theirs), so every supplier declined.
        supply_scope = (f"仅为施工包「{item['name']}」供应其施工所需的材料与构配件：供货、运输到场、质量证明文件和质保期内的更换。"
                        "不含任何施工、安装、临时工程或措施费，也不承担施工界面责任。"
                        "材料费用已包含在该施工包的合同价内，由该施工包的承包商作为买方支付。"
                        f"该施工包的工作内容（仅用于判断所需材料，不属于本包工作）：{item['scope']}")
        supply.update(package_id=f"{project['project_id']}/supply-{index+1}", name=item["name"] + "材料采购",
                      scope=supply_scope, budget=round(construction["budget"] * .28, 2),
                      depends_on=[construction["package_id"]], parent_package_id=construction["package_id"])
        payload["packages"] += [construction, supply]
    payload["assumptions"]["procurement_plan"] = {"source": "owner_organization_model_proposal", "reason": decision.get("reason", ""),
                                                  "base_data_version": dataset.version, "numeric_approval": "DBB structure and budget/dependency validation"}
    planned = SharedDataset(payload)
    atomic_json(directory / "plan.json", {"snapshot": asdict(snapshot), "state": dump(state), "proposal": decision,
                                         "approved_data_version": planned.version, "numeric_checks_passed": True})
    return planned, state.company_agent_rosters
