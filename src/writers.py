from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models import SimulationState, dump
from src.report_sections import render_package_details
from src.verification import conditions


REQUIRED_OUTPUTS = [
    "companies.json",
    "company_agent_rosters.json",
    "tender_process_log.json",
    "agent_discussion_history.json",
    "agent_discussion_history.md",
    "consortiums.json",
    "bid_documents.json",
    "opening_record.json",
    "evaluation_report.json",
    "simulated_award_result.json",
    "project_execution_log.json",
    "final_report.md",
    "case_status.json",
    "llm_calls.jsonl",
    "recovery_events.jsonl",
    "workflow_checkpoint.json",
    "workflow_checkpoint_events.jsonl",
    "progress.log",
]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dump(data), ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_outputs(state: SimulationState, run_dir: Path) -> dict[str, str]:
    files = {
        "companies": run_dir / "companies.json",
        "company_agent_rosters": run_dir / "company_agent_rosters.json",
        "participation_decisions": run_dir / "participation_decisions.json",
        "verification_conditions": run_dir / "verification_conditions.json",
        "tender_process_log": run_dir / "tender_process_log.json",
        "agent_discussion_history": run_dir / "agent_discussion_history.json",
        "agent_discussion_history_md": run_dir / "agent_discussion_history.md",
        "consortiums": run_dir / "consortiums.json",
        "bid_documents": run_dir / "bid_documents.json",
        "opening_record": run_dir / "opening_record.json",
        "evaluation_report": run_dir / "evaluation_report.json",
        "simulated_award_result": run_dir / "simulated_award_result.json",
        "project_execution_log": run_dir / "project_execution_log.json",
        "final_report": run_dir / "final_report.md",
    }
    write_json(files["companies"], state.companies)
    write_json(files["company_agent_rosters"], state.company_agent_rosters)
    write_json(files["participation_decisions"], state.participation_decisions)
    scopes = sorted({(m.company_id, m.package_id) for m in state.agent_discussion_history if m.package_id})
    write_json(files["verification_conditions"], [r for company_id, package_id in scopes
                                                for r in conditions(state, company_id, package_id)])
    write_json(files["tender_process_log"], state.tender_process_log)
    write_json(files["agent_discussion_history"], state.agent_discussion_history)
    write_text(files["agent_discussion_history_md"], render_discussion_history(state))
    write_json(files["consortiums"], state.consortiums)
    write_json(files["bid_documents"], state.bid_documents)
    write_json(files["opening_record"], state.opening_record)
    write_json(files["evaluation_report"], state.evaluation_report)
    write_json(files["simulated_award_result"], state.simulated_award_result)
    write_json(files["project_execution_log"], state.project_execution_log)
    write_text(files["final_report"], render_final_report(state))
    return {key: str(path) for key, path in files.items()}


def render_discussion_history(state: SimulationState) -> str:
    lines = ["# Agent 讨论记录", ""]
    current_key = None
    for message in state.agent_discussion_history:
        key = (message.stage, message.package_id, message.company_id)
        if key != current_key:
            lines.extend(
                [
                    "",
                    f"## {message.stage} / {message.package_id or 'project'} / {message.company_id}",
                    "",
                ]
            )
            current_key = key
        lines.extend(
            [
                f"### {message.message_id} - 第 {message.round} 轮：{message.round_type}",
                "",
                f"- Agent：{message.agent_name}（{message.department}，{message.position}）",
                f"- 消息类型：{message.message_type}",
                f"- 建议：{message.recommendation}",
                f"- 决策影响：{message.decision_impact}",
                f"- 最终决策：{message.final_decision}",
                "",
                "**内部思考**",
                "",
                _text(message.thoughts) or "（该消息类型未记录）",
                "",
                "**发言内容**",
                "",
                _text(message.content),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _text(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def render_final_report(state: SimulationState) -> str:
    lines = [
        "# codedemo_v2 最终报告",
        "",
        "## 项目初步想法",
        "",
        f"- 项目：{state.project_idea.project_name}",
        f"- 类型：{state.project_idea.project_type}",
        f"- 地点：{state.project_idea.location}",
        f"- 业主意图：{state.project_idea.owner_intent}",
        "",
        "## 流程汇总",
        "",
        f"- 企业数量：{len(state.companies)}",
        f"- 招标包数量：{len(state.tender_packages)}",
        f"- 讨论记录数量：{len(state.agent_discussion_history)}",
        f"- 组合体数量：{len(state.consortiums)}",
        f"- 投标文件数量：{len(state.bid_documents)}",
        f"- 开标记录数量：{len(state.opening_record)}",
        f"- 评标报告数量：{len(state.evaluation_report)}",
        f"- 执行衔接包数量：{len(state.project_execution_log.get('package_handoffs', []))}",
        "",
        "## 招标包模拟判给结果",
        "",
    ]
    for award in state.simulated_award_result.get("package_awards", []):
        lines.extend(
            [
                f"### {award['package_id']}",
                "",
                f"- 选定投标主体：{award['selected_bidder_name']}",
                f"- 投标主体类型：{award['bidder_type']}",
                f"- 判给理由：{award['decision_reason']}",
                f"- 保留的待核实条件：{award.get('unresolved_condition_ids', [])}",
                f"- 投标假设：{award.get('bid_assumptions', [])}",
                f"- 业主待澄清事项：{award.get('pending_clarifications', [])}",
                "",
            ]
        )
    lines.extend(render_package_details(state))
    lines.extend(render_validation_comparison(state))
    lines.extend(
        [
            "## MVP 边界",
            "",
            "当前 MVP 尚未实现项目实施阶段仿真；招投标结果到实施阶段的衔接记录在 `project_execution_log.json` 中。",
            "",
        ]
    )
    return "\n".join(lines)


def render_validation_comparison(state: SimulationState) -> list[str]:
    context = state.validation_context or {}
    benchmark = context.get("benchmark") or []
    project = context.get("project") or {}
    if not benchmark:
        return []

    lines = [
        "## 与真实 benchmark 对照",
        "",
        f"本次用于对照的真实案例是 `{context.get('case_id', state.project_idea.project_id)}`：`{project.get('project_name', state.project_idea.project_name)}`。",
        "",
        "### 真实 benchmark 记录",
        "",
        f"隐藏 benchmark 中该案例共有 {len(benchmark)} 条真实项目-企业关系：",
        "",
    ]
    for row in benchmark:
        lines.append(f"- {row.get('company_role_original', '')}：`{row.get('matched_enterprise_name') or row.get('company_name', '')}`")

    lines.extend(
        [
            "",
            "### 判定规则",
            "",
            "- 先把真实角色归并为 MVP 当前支持的角色组：设计、供应、施工、监管/顾问。",
            "- 企业命中：同一个角色组内，模拟选中的企业名称与至少一家真实 benchmark 企业名称完全一致。",
            "- 角色匹配，企业未命中：该角色组有模拟选中企业，但企业名称没有命中真实 benchmark。",
            "- 未覆盖：该真实角色组在本次模拟结果中没有对应选中企业。",
            "- 逐企业命中会逐家检查真实 benchmark 企业；角色组命中只检查该角色组是否至少命中一家。",
            "",
            "### 项目基础字段判断过程",
            "",
        ]
    )
    lines.extend(_render_project_judgment_process(state, project))
    lines.extend(
        [
            "",
            "### 候选企业池构建规则",
            "",
        ]
    )
    lines.extend(_render_candidate_pool_rules(context))
    lines.extend(
        [
            "",
            "### 从候选池到最终入选企业",
            "",
        ]
    )
    lines.extend(_render_final_selection_process(state, benchmark, context))
    lines.extend(
        [
            "",
            "### 模拟结果对照",
            "",
        ]
    )
    rows = _validation_rows(state, benchmark, project)
    lines.extend(
        [
            "| 对照层级 | 真实情况 | 本次模拟结果 | 判断 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |")

    role_details = _role_validation_details(state, benchmark)
    lines.extend(
        [
            "",
            "### 企业命中明细",
            "",
            "| 真实角色组 | 对应模拟招标包 | 真实企业数 | 模拟选中企业 | 命中的真实企业 | 未命中的真实企业 | 判断 |",
            "| --- | --- | ---: | --- | --- | --- | --- |",
        ]
    )
    for detail in role_details:
        lines.append(
            "| {role} | {package} | {benchmark_count} | {simulated} | {hits} | {misses} | {verdict} |".format(
                role=detail["role"],
                package=detail["package"],
                benchmark_count=detail["benchmark_count"],
                simulated=detail["simulated"] or "当前未单独拆分",
                hits=detail["hits"] or "无",
                misses=detail["misses"] or "无",
                verdict=detail["verdict"],
            )
        )

    role_group_total = len(role_details)
    role_group_hits = sum(1 for detail in role_details if detail["verdict"] == "企业命中")
    role_group_covered = sum(1 for detail in role_details if detail["verdict"] in {"企业命中", "角色匹配，企业未命中"})
    benchmark_company_names = _unique(
        row.get("matched_enterprise_name") or row.get("company_name") or row.get("casebank_company_name", "")
        for row in benchmark
    )
    individual_hit_names = _unique(name for detail in role_details for name in detail["hit_names"])
    lines.extend(
        [
            "",
            "### 对照结论",
            "",
            f"- 角色组企业命中：{role_group_hits}/{role_group_total}",
            f"- 逐企业命中：{len(individual_hit_names)}/{len(benchmark_company_names)}",
            f"- 角色覆盖：{role_group_covered}/{role_group_total}",
            "- 角色组命中的意思是：不要求选中该角色下所有真实企业，只要同一个角色组内，仿真最终结果至少命中一家真实 benchmark 企业，就记为该角色组命中。",
            "- 本次统计的“企业命中”默认指角色组命中，不等于真实企业逐家全部命中。",
            "- 如果一个真实角色组有多家企业，模拟结果只命中其中一家，该角色组仍记为企业命中，但逐企业命中只增加 1 家。",
            "- 当前 MVP 每个模拟包通常只判给一个主体，因此监管/顾问等多企业角色更适合同时看逐企业命中。",
            "- 真实 benchmark 企业已经进入候选池，但 agent 不知道哪些企业是真实结果。",
            "- 该对照用于 validation，不作为仿真输入。",
            "",
        ]
    )
    return lines


def _render_project_judgment_process(state: SimulationState, project: dict[str, str]) -> list[str]:
    project_idea = state.project_idea
    source_name = "`simulation_input_projects.csv`"
    rows = [
        _field_judgment(
            "项目名称",
            f"{source_name}.project_name",
            project.get("project_name", ""),
            "ProjectIdea.project_name",
            project_idea.project_name,
            "去除首尾空格后完全相同",
        ),
        _field_judgment(
            "项目类型",
            f"{source_name}.project_type",
            project.get("project_type", ""),
            "ProjectIdea.project_type",
            project_idea.project_type,
            "去除首尾空格后完全相同",
        ),
        _field_judgment(
            "项目地点",
            f"{source_name}.location",
            project.get("location", ""),
            "ProjectIdea.location",
            project_idea.location,
            "去除首尾空格后完全相同",
        ),
    ]
    package_ids = [package.package_id for package in state.tender_packages]
    package_names = [package.package_name for package in state.tender_packages]
    has_dbb_structure = {"design_package", "contractor_package", "supervision_package"}.issubset(set(package_ids))
    delivery_result = "结构性符合" if project.get("delivery_mode") == "DBB" and has_dbb_structure else "需要人工复核"
    rows.append(
        {
            "item": "交付模式/包拆分",
            "source_field": f"{source_name}.delivery_mode",
            "source_value": project.get("delivery_mode", ""),
            "simulation_field": "TenderPackage.package_id/package_name",
            "simulation_value": "、".join(package_names),
            "method": "DBB 不要求单一总包；检查是否拆出设计、施工、监管/顾问等独立包",
            "result": delivery_result,
            "reason": f"当前包 ID 为：{'、'.join(package_ids)}",
        }
    )

    lines = [
        "- 项目名称、项目类型、项目地点不是从 benchmark 企业结果推断出来的，而是由 case 输入表生成仿真项目后再核对。",
        "- 如果源字段值和仿真字段值去除首尾空格后完全相同，报告写为“一致”。",
        "- 交付模式不做简单文字相等判断，而是检查模拟招标包结构是否符合该交付模式。",
        "",
        "| 判断项 | 数据来源字段 | 源字段值 | 仿真字段 | 仿真值 | 比较方法 | 结论 | 判断依据 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {item} | {source_field} | {source_value} | {simulation_field} | {simulation_value} | {method} | {result} | {reason} |".format(
                **row
            )
        )
    return lines


def _field_judgment(
    item: str,
    source_field: str,
    source_value: str,
    simulation_field: str,
    simulation_value: str,
    method: str,
) -> dict[str, str]:
    source_norm = (source_value or "").strip()
    simulation_norm = (simulation_value or "").strip()
    matched = bool(source_norm) and source_norm == simulation_norm
    return {
        "item": item,
        "source_field": source_field,
        "source_value": source_value,
        "simulation_field": simulation_field,
        "simulation_value": simulation_value,
        "method": method,
        "result": "一致" if matched else "不一致",
        "reason": f"`{source_norm}` == `{simulation_norm}`" if matched else f"`{source_norm}` != `{simulation_norm}`",
    }


def _render_candidate_pool_rules(context: dict[str, Any]) -> list[str]:
    config = context.get("candidate_pool_config") or {}
    details = context.get("candidate_pool_details") or []
    if not config or not details:
        return ["本次报告未记录候选企业池构建明细。"]

    role_targets = config.get("role_targets", {})
    lines = [
        f"- 数据来源目录：`{context.get('source_dir', '')}`。",
        "- 项目基础信息来自 `simulation_input_projects.csv`，只使用项目名称、类型、地点、交付模式、业主等输入字段。",
        "- 企业画像来自 `simulation_input_enterprises.csv`，用于生成候选企业的 profile、能力、经验和风险信息。",
        "- 真实合作企业来自 `hidden_benchmark_project_enterprises.csv`，只用于候选池保底纳入和最终 validation 对照。",
        f"- 候选企业池上限：{config.get('max_companies', 30)} 家候选企业，不含自动生成的业主方。",
        f"- 是否强制纳入真实 benchmark 企业：{config.get('include_benchmark_companies', True)}。",
        "- 干扰企业排序分数：角色关键词命中 +6，地点/区域关键词命中 +2，项目场景关键词命中 +3。",
        "- 排序只用于补足干扰企业；真实 benchmark 企业会先放入候选池，不靠分数决定是否进入。",
        "",
        "| 角色 | 目标候选数 | benchmark 纳入数 | 补充 Top 干扰企业数 | 实际候选数 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for role in ["designer", "supplier", "contractor", "supervisor"]:
        role_details = [item for item in details if item.get("role") == role]
        benchmark_count = sum(1 for item in role_details if item.get("source") == "benchmark_included")
        distractor_count = sum(1 for item in role_details if item.get("source") == "top_scored_distractor")
        lines.append(
            f"| {_role_name_cn(role)} | {role_targets.get(role, 5)} | {benchmark_count} | Top {distractor_count} | {len(role_details)} |"
        )

    lines.extend(
        [
            "",
            "候选企业池明细：",
            "",
            "| 角色 | 来源 | Top 排名 | 企业 | 匹配分数 | benchmark 原始角色 |",
            "| --- | --- | ---: | --- | ---: | --- |",
        ]
    )
    for item in details:
        source = "benchmark 保底纳入" if item.get("source") == "benchmark_included" else "相似干扰企业"
        rank = item.get("distractor_rank") or "-"
        lines.append(
            f"| {_role_name_cn(item.get('role', ''))} | {source} | {rank} | {item.get('company_name', '')} | {item.get('score', '')} | {item.get('benchmark_role_original', '') or '-'} |"
        )
    return lines


def _render_final_selection_process(state: SimulationState, benchmark: list[dict[str, str]], context: dict[str, Any]) -> list[str]:
    details = context.get("candidate_pool_details") or []
    detail_by_id = {item.get("company_id"): item for item in details}
    benchmark_names_by_role = _benchmark_by_role(benchmark)
    run_mode = context.get("run_mode", "")
    lines = [
        "- `Top 排名` 只表示相似干扰企业进入候选池时的排序，不是最终中标排序。",
        "- `benchmark 保底纳入` 企业没有 Top 排名，因为它们是根据真实案例关系先放入候选池，不参与干扰企业 Top K 排序。",
        "- 最终入选企业来自 `simulated_award_result.json` 的 `package_awards.selected_bidder_id` 和 `selected_bidder_name`。",
        "- `evaluation_report.json` 的 `recommended_winner` 是评标推荐结果，`simulated_award_result.json` 是业主最终判给结果。",
        "- 当前 MVP 的最终判给是每个模拟招标包选出一个最终入选主体；如果真实案例中同一角色有多家企业，报告只能检查该包是否命中其中一家。",
    ]
    if run_mode == "case":
        lines.extend(
            [
                "- 本次使用 case 仿真模式：输入使用真实 case 项目信息和真实企业候选池，中间讨论、投标文件、评标和判给均由 LLM 生成。",
                "- case 仿真结果仍是模拟结果，不等同于真实采购预测；benchmark 只用于事后 validation 对照。",
            ]
        )
    lines.extend(
        [
            "",
            "本次最终入选企业如下：",
            "",
            "| 模拟招标包 | 最终入选企业 ID | 最终入选企业 | 候选池来源 | 候选池 Top 排名 | 是否属于真实 benchmark | 对 benchmark 的处理 |",
            "| --- | --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for award in state.simulated_award_result.get("package_awards", []):
        bidder_id = award.get("selected_bidder_id", "")
        bidder_name = award.get("selected_bidder_name", "")
        role_label = _role_for_package(award.get("package_id", ""))
        detail = detail_by_id.get(bidder_id, {})
        source = detail.get("source", "")
        source_label = "benchmark 保底纳入" if source == "benchmark_included" else "相似干扰企业" if source == "top_scored_distractor" else "-"
        rank = detail.get("distractor_rank") or "-"
        benchmark_names = benchmark_names_by_role.get(role_label, [])
        is_benchmark = bidder_name in benchmark_names
        lines.append(
            "| {package_id} | {bidder_id} | {bidder_name} | {source} | {rank} | {is_benchmark} | {judgment} |".format(
                package_id=award.get("package_id", ""),
                bidder_id=bidder_id or "-",
                bidder_name=bidder_name or "-",
                source=source_label,
                rank=rank,
                is_benchmark="是" if is_benchmark else "否",
                judgment=_selected_benchmark_judgment(role_label, bidder_name, benchmark_names),
            )
        )
    lines.extend(
        [
            "",
            "本报告判断“哪个公司入选”的顺序：",
            "",
            "1. 先读取 `simulated_award_result.json` 中每个包的 `selected_bidder_name`。",
            "2. 再把每个模拟包映射到 benchmark 角色组：`design_package -> 设计`，`supplier_package -> 供应`，`contractor_package -> 施工`，`supervision_package -> 监管/顾问`。",
            "3. 在同一个角色组内比较企业名称是否和 `hidden_benchmark_project_enterprises.csv` 的 `matched_enterprise_name` 完全一致。",
            "4. 名称一致则记为企业命中；同角色有入选企业但名称不一致则记为角色匹配、企业未命中；该角色没有入选企业则记为未覆盖。",
        ]
    )
    return lines


def _validation_rows(state: SimulationState, benchmark: list[dict[str, str]], project: dict[str, str]) -> list[tuple[str, str, str, str]]:
    rows = [
        (
            "项目类型",
            project.get("project_type", ""),
            state.project_idea.project_type,
            "一致" if project.get("project_type") == state.project_idea.project_type else "基本接近",
        ),
        (
            "项目地点",
            project.get("location", ""),
            state.project_idea.location,
            "一致" if project.get("location") == state.project_idea.location else "不一致",
        ),
        (
            "交付模式",
            project.get("delivery_mode", ""),
            "、".join(package.package_name for package in state.tender_packages),
            "结构性对照",
        ),
    ]

    for role, names in _benchmark_by_role(benchmark).items():
        simulated = _selected_names_for_role(state, role)
        if not simulated:
            verdict = "未覆盖"
        elif any(name in simulated for name in names):
            verdict = "企业命中"
        else:
            verdict = "角色匹配，企业未命中"
        rows.append((role, "、".join(names), "、".join(simulated) or "当前未单独拆分", verdict))
    return rows


def _benchmark_by_role(benchmark: list[dict[str, str]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for row in benchmark:
        role = _role_label(row.get("company_role_original", ""))
        name = row.get("matched_enterprise_name") or row.get("company_name") or row.get("casebank_company_name", "")
        grouped.setdefault(role, [])
        if name and name not in grouped[role]:
            grouped[role].append(name)
    return grouped


def _selected_names_for_role(state: SimulationState, role_label: str) -> list[str]:
    package_roles = {
        "设计": "design_package",
        "供应": "supplier_package",
        "施工": "contractor_package",
        "监管/顾问": "supervision_package",
    }
    package_id = package_roles.get(role_label)
    if not package_id:
        return []
    award = next((item for item in state.simulated_award_result.get("package_awards", []) if item.get("package_id") == package_id), None)
    if not award:
        return []
    if award.get("bidder_type") != "consortium":
        return [award.get("selected_bidder_name", "")]
    consortium = next((item for item in state.consortiums if item.consortium_id == award.get("selected_bidder_id")), None)
    if not consortium:
        return [award.get("selected_bidder_name", "")]
    company_names = []
    for company_id in consortium.member_company_ids:
        company = next((item for item in state.companies if item.company_id == company_id), None)
        if company:
            company_names.append(company.company_name)
    return company_names or [award.get("selected_bidder_name", "")]


def _role_validation_details(state: SimulationState, benchmark: list[dict[str, str]]) -> list[dict[str, Any]]:
    details = []
    for role, names in _benchmark_by_role(benchmark).items():
        simulated = _selected_names_for_role(state, role)
        hits = [name for name in names if name in simulated]
        misses = [name for name in names if name not in simulated]
        if not simulated:
            verdict = "未覆盖"
        elif hits:
            verdict = "企业命中"
        else:
            verdict = "角色匹配，企业未命中"
        details.append(
            {
                "role": role,
                "package": _package_label_for_role(role),
                "benchmark_count": len(names),
                "simulated": "、".join(simulated),
                "hits": "、".join(hits),
                "misses": "、".join(misses),
                "hit_names": hits,
                "verdict": verdict,
            }
        )
    return details


def _package_label_for_role(role_label: str) -> str:
    return {
        "设计": "design_package",
        "供应": "supplier_package",
        "施工": "contractor_package",
        "监管/顾问": "supervision_package",
    }.get(role_label, "当前未映射")


def _role_for_package(package_id: str) -> str:
    return {
        "design_package": "设计",
        "supplier_package": "供应",
        "contractor_package": "施工",
        "supervision_package": "监管/顾问",
    }.get(package_id, "")


def _selected_benchmark_judgment(role_label: str, bidder_name: str, benchmark_names: list[str]) -> str:
    if not benchmark_names:
        return f"该案例没有{role_label or '该角色'}类 benchmark 记录，不计入命中分母"
    if bidder_name in benchmark_names:
        return f"命中{role_label}角色组中的真实企业"
    return f"{role_label}角色有入选企业，但未命中真实 benchmark 企业"


def _unique(values) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _role_name_cn(role: str) -> str:
    return {
        "designer": "设计",
        "supplier": "供应",
        "contractor": "施工",
        "supervisor": "监管/顾问",
    }.get(role, role)


def _role_label(value: str) -> str:
    if any(token in value for token in ["施工", "承建", "总承包", "總承包", "专业分包", "建造"]):
        return "施工"
    if any(token in value for token in ["供应", "供應", "制造", "製造", "材料", "设备", "設備"]):
        return "供应"
    if any(token in value for token in ["设计", "設計", "勘察", "测绘", "測繪", "规划", "規劃"]):
        return "设计"
    return "监管/顾问"


def missing_required_outputs(run_dir: Path) -> list[str]:
    return [name for name in REQUIRED_OUTPUTS if not (run_dir / name).exists()]
