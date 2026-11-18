"""Offline continuity acceptance: A commits before procurement of B begins.

No API calls. The fixture chooses a consortium to exercise wiring, not to claim
that a model learned to cooperate. Construction still starts after all contracts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from integration.bootstrap import enable_gba_imports
from integration.decision_context import build_own_state
from integration.fixture_client import IntegrationFixtureClient
from integration.run import build_engine
from integration.sessions import atomic_json
from integration.shared_data import SharedDataset


ROOT = Path(__file__).resolve().parents[1]
A, B = "PRJ01/contractor_package_A", "PRJ01/contractor_package_B"


def run(directory):
    directory = Path(directory)
    if directory.exists():
        raise ValueError("Use a new output directory; saved runs must not be overwritten")
    enable_gba_imports()
    from gba_construction_sim.backend.decision.rule_based_provider import RuleBasedDecisionProvider

    payload = json.loads((ROOT / "integration/examples/shared_dbb.json").read_text(encoding="utf-8"))
    next(p for p in payload["packages"] if p["package_id"] == B)["depends_on"].append(A)
    payload["assumptions"]["source_note"] += "; Continuity fixture: B procurement starts after A contract commits, not after A construction completes."
    dataset = SharedDataset(payload)
    client = IntegrationFixtureClient()
    engine = build_engine(dataset, client, directory, native_provider=RuleBasedDecisionProvider())
    atomic_json(directory / "shared_input.json", payload)
    atomic_json(directory / "source_manifest.json", {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for pattern in ("integration/*.py", "src/**/*.py", "prompts/**/*.md") for p in ROOT.glob(pattern)
    })
    try:
        engine.run()
    finally:
        atomic_json(directory / "result.json", {"offline_fixture": True,
                    "simulation": engine.response().model_dump(),
                    "procurement": engine.procurement_executor.status()})
    ex = engine.procurement_executor
    first, second = ex.sessions[(A, 1)], ex.sessions[(B, 1)]
    entity = first.proposal.lead_id
    before = first.snapshot.for_entity(entity)["own_state"]
    later = second.snapshot.for_entity(entity)["own_state"]
    after = build_own_state(engine, dataset, ex.registry, entity, second.spec)
    project = engine.projects["PRJ01"]
    receipt = project.flags["package_contracts"][A]
    prompt_markers = set()
    for messages in client.requests:
        prompt = messages[-1]["content"]
        if "Authorized decision context:\n" not in prompt:
            continue
        ctx = json.loads(prompt.split("Authorized decision context:\n", 1)[1])
        if ctx["package_id"] == B and ctx["own_state"]["entity_id"] == entity:
            if ctx["own_state"] != later:
                raise AssertionError("Decision prompt differs from saved authorized snapshot")
            prompt_markers.add(prompt.splitlines()[0])
    checks = {
        "B_snapshot_after_A_commit": second.snapshot.tick > receipt["signed_tick"],
        "B_knows_A_contract": any(c["package_id"] == A for c in later["task_state"]["contracts"]),
        "B_resources_match_A_commitment": abs(before["available_resource"] - later["available_resource"]
                                                - receipt["resource_commitments"][entity]) < 1e-8,
        "B_remembers_A_commit": any(e["event_type"] == "package_contract_committed" and e.get("package_id") == A
                                   for e in later["memory"]),
        "member_and_final_decisions_receive_context": {"AGENT_MESSAGE", "MANAGEMENT_DECISION"}.issubset(prompt_markers),
        "closed": project.current_stage.value == "closed",
        "all_resources_released": all(a.occupied_resource == 0 for a in engine.agents.values()),
        "original_snapshot_preserved": before["occupied_resource"] == 0,
        "signed_promises_retained_after_release": len([c for c in after["task_state"]["contracts"]
                                                        if c["party_role"] == "member"]) == 2,
        "purchases_do_not_reserve_buyer_capacity": all(c["own_committed_resource"] == 0
            for c in after["task_state"]["contracts"] if c["party_role"] == "buyer"),
    }
    result = {"offline_fixture": True, "real_model": False, "passed": all(checks.values()),
              "checks": checks, "entity_id": entity, "tick": engine.current_tick,
              "A_session": first.path.relative_to(directory).as_posix(),
              "B_session": second.path.relative_to(directory).as_posix(),
              "A_signed_tick": receipt["signed_tick"], "B_snapshot_tick": second.snapshot.tick,
              "before_A": before, "before_B": later, "after_close": after,
              "B_decision_markers": sorted(prompt_markers)}
    atomic_json(directory / "continuity.json", result)
    report = ["# 连续采购与状态反馈：离线开发验收", "",
              "合成输入与固定离线回答，仅检查工程链路；没有调用真实模型，也不证明决策效果。",
              "A 签约后启动 B 的采购；所有合同齐备后才进入原有施工流程。", "",
              f"企业：`{entity}`。A 在 tick {receipt['signed_tick']} 签约，B 的快照为 tick {second.snapshot.tick}。", "",
              "| 时点 | 可用资源 | 已占资源 | 自身合同记录数 |", "| --- | ---: | ---: | ---: |"]
    for label, own in [("A 决策前", before), ("B 决策前", later), ("项目关闭后", after)]:
        report.append(f"| {label} | {own['available_resource']:.2f} | {own['occupied_resource']:.2f} | {len(own['task_state']['contracts'])} |")
    report += ["", "资源单位为标准化施工能力。历史合同承诺保留，但不能重复计为当前占用。", "",
               f"检查结果：**{'通过' if result['passed'] else '未通过'}**。", ""]
    report += [f"- {name}: {passed}" for name, passed in checks.items()]
    report += ["", "[完整检查与上下文](continuity.json) · [宏观结果](result.json)", "",
               f"[A 采购会话]({result['A_session']}) · [B 采购会话]({result['B_session']})", ""]
    (directory / "continuity.md").write_text("\n".join(report), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps({"passed": result["passed"], "offline_fixture": True,
                      "tick": result["tick"], "report": str(args.output / "continuity.md")}, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
