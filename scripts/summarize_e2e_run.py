"""Summarize one end-to-end run: per-package procurement outcome and macro result (read-only).

Run:  python -m scripts.summarize_e2e_run runs/<run-id>   -> prints and writes <run>/SUMMARY.md
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path


def main() -> None:
    run = Path(sys.argv[1])
    status = json.loads((run / "status.json").read_text(encoding="utf-8"))
    shared = json.loads((run / "shared_input.json").read_text(encoding="utf-8"))
    result = json.loads((run / "result.json").read_text(encoding="utf-8"))
    names = {c["company_id"]: c["company_name"] for c in shared["companies"].values()} if isinstance(shared["companies"], dict) \
        else {c["company_id"]: c["company_name"] for c in shared["companies"]}
    sessions = {}
    for path in (run / "sessions").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        sessions[data["session_id"]] = data
    project = status["projects"][0]
    budget = status["settings"]["budget"]
    out = [f"# 端到端运行摘要：{run.name}", "",
           f"项目 {project['id']} {project['name']}；模型 `{status['usage']['model']}`；"
           f"状态 **{status['status']}**（{status['phase']}），共 {status['current_tick']} 个宏观时间步。", "",
           f"模型调用 {status['usage']['requests']} 次，输入 {status['usage']['input_tokens']:,} tokens，"
           f"输出 {status['usage']['output_tokens']:,} tokens。", "",
           "## 各采购包", "",
           "| 包 | 类型 | 预算 | 轮次 | 投标/放弃 | 递交投标 | 中标人 | 合同价 | 合同价/预算 | 签约修订稿 | 结果 |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    by_package = collections.defaultdict(list)
    for data in sessions.values():
        by_package[data["spec"]["package_id"]].append(data)
    total_contract = 0.0
    for spec in shared["packages"]:
        rounds = sorted(by_package.get(spec["package_id"], []), key=lambda d: d["session_id"])
        if not rounds:
            out.append(f"| {spec['package_id']} | {spec['kind']} | {spec['budget']:,.0f} | 0 | | | | | | | 未开始 |")
            continue
        last = rounds[-1]
        state = last["state"]
        decisions = collections.Counter(p["decision"] for p in state["participation_decisions"])
        proposal = last["proposal"]
        revisions = [e for e in state["tender_process_log"] if e.get("event_type") == "contract_authorizations"]
        price = proposal["price"] if proposal and last["status"] == "committed" else None
        if price and spec.get("cost_inclusion") != "included_in_parent":
            total_contract += price
        winner = proposal["bidder_id"] if proposal else "—"
        out.append(f"| {spec['package_id'].split('/')[-1]} | {spec['kind']} | {spec['budget']:,.0f} | {len(rounds)} | "
                   f"{decisions.get('bid', 0) + decisions.get('bid_with_consortium', 0)}/{decisions.get('no_bid', 0)} | "
                   f"{len(state['bid_documents'])} | {winner} {names.get(winner, '')} | "
                   f"{f'{price:,.0f}' if price else '—'} | {f'{price / spec['budget']:.1%}' if price else '—'} | "
                   f"{len(revisions)} | {last['status']} |")
    simulation = result["simulation"]
    macro = simulation["project_results"][0]
    metrics = simulation["metrics"]["project_metrics"]
    performance = macro["performance"]
    out += ["", "## 宏观结果（GBA 规则引擎）", "",
            f"- 项目阶段：{macro['current_stage']}；进度 {project['progress']:.0%}；延误 {project['delay_days']} 天。",
            f"- 业主直接签约合同价合计 {total_contract:,.0f}（材料包已含在施工包内，不重复计入）；情景总预算 {budget:,.0f}；"
            f"宏观登记的施工合同额 {macro['contract_sum']:,.0f}。",
            f"- 宏观记录的实际成本 {project['cost']:,.0f}，为总预算的 {project['cost'] / budget:.1%}。",
            f"- 选定单位：设计 {macro['selected_architect_id']}，造价 {macro['selected_qs_id']}，"
            f"施工 {macro['selected_contractor_id']}，供应 {', '.join(macro['selected_supplier_ids'])}。", "",
            "| 指标 | 数值 |", "|---|---|"]
    out += [f"| {key} | {round(value, 4) if isinstance(value, float) else value} |" for key, value in metrics.items()]
    out += [f"| performance.{key} | {round(value, 4) if isinstance(value, float) else value} |"
            for key, value in performance.items() if isinstance(value, (int, float)) and not isinstance(value, bool)]
    events = collections.Counter(e.get("event_type") for e in macro.get("event_log", []))
    out += ["", f"宏观事件共 {len(macro.get('event_log', []))} 条：", "", "| 事件类型 | 次数 |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in events.most_common(20)]
    text = "\n".join(out) + "\n"
    (run / "SUMMARY.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
