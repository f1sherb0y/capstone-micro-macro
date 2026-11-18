from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from src.models import Company, ProjectIdea


DEFAULT_CONFIG = Path("config/test_source_config.json")

ROLE_PACKAGES = {
    "designer": ["design_package"],
    "supplier": ["supplier_package"],
    "contractor": ["contractor_package"],
    "supervisor": ["supervision_package"],
}


def load_case_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    config_path = Path(path)
    return json.loads(config_path.read_text(encoding="utf-8"))


def list_case_ids(config: dict[str, Any]) -> list[str]:
    base = Path(config["test_source_dir"])
    projects = _read_csv(base / "simulation_input_projects.csv")
    return [row["case_id"] for row in projects if row.get("case_id")]


def load_case_inputs(config: dict[str, Any], case_id: str) -> tuple[ProjectIdea, list[Company], dict[str, Any]]:
    base = Path(config["test_source_dir"])
    projects = _read_csv(base / "simulation_input_projects.csv")
    enterprises = _read_csv(base / "simulation_input_enterprises.csv")
    benchmark = _read_csv(base / "hidden_benchmark_project_enterprises.csv")

    project_row = next((row for row in projects if row.get("case_id") == case_id), None)
    if not project_row:
        raise ValueError(f"Case id not found in simulation_input_projects.csv: {case_id}")

    benchmark_rows = [row for row in benchmark if row.get("case_id") == case_id]
    if not benchmark_rows:
        raise ValueError(f"Case id has no hidden benchmark rows: {case_id}")

    candidate_pool_config = config.get("candidate_pool", {})
    assignment_file = candidate_pool_config.get("assignment_file", "")
    assignment_rows: list[dict[str, str]] = []
    if assignment_file:
        assignment_rows = [
            row
            for row in _read_csv(base / assignment_file)
            if row.get("case_id") == case_id
        ]
        companies = companies_from_candidate_assignments(project_row, enterprises, assignment_rows)
        _validate_assigned_pool(case_id, companies, benchmark_rows, candidate_pool_config)
    else:
        companies = build_candidate_company_pool(project_row, enterprises, benchmark_rows, candidate_pool_config)
    project = _project_idea(project_row)
    validation_context = {
        "case_id": case_id,
        "project": project_row,
        "benchmark": benchmark_rows,
        "candidate_pool_summary": _candidate_pool_summary(companies),
        "candidate_pool_config": candidate_pool_config,
        "candidate_pool_details": (
            _assigned_candidate_pool_details(assignment_rows, enterprises)
            if assignment_rows
            else _candidate_pool_details(project_row, companies, enterprises, benchmark_rows)
        ),
        "source_dir": str(base),
    }
    return project, companies, validation_context


def build_diversified_candidate_assignments(
    project_rows: list[dict[str, str]],
    enterprise_rows: list[dict[str, str]],
    benchmark_rows: list[dict[str, str]],
    config: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Build reproducible candidate pools while limiting distractor reuse across cases."""
    case_ids = [row["case_id"] for row in project_rows if row.get("case_id")]
    project_by_case = {row["case_id"]: row for row in project_rows if row.get("case_id")}
    benchmark_by_case: dict[str, list[dict[str, str]]] = {case_id: [] for case_id in case_ids}
    for row in benchmark_rows:
        if row.get("case_id") in benchmark_by_case:
            benchmark_by_case[row["case_id"]].append(row)

    by_id = {row.get("company_id", ""): row for row in enterprise_rows if row.get("company_id")}
    by_name = {_norm(row.get("company_name", "")): row for row in enterprise_rows if row.get("company_name")}
    assignments: dict[str, list[dict[str, Any]]] = {case_id: [] for case_id in case_ids}
    selected_ids: dict[str, set[str]] = {case_id: set() for case_id in case_ids}
    role_counts: dict[str, dict[str, int]] = {case_id: {} for case_id in case_ids}

    if bool(config.get("include_benchmark_companies", True)):
        for case_id in case_ids:
            for row in benchmark_by_case[case_id]:
                source = by_id.get(row.get("company_id", "")) or by_name.get(
                    _norm(row.get("matched_enterprise_name", ""))
                )
                if not source or source.get("company_id") in selected_ids[case_id]:
                    continue
                role = role_from_case_role(row.get("company_role_original", ""))
                assignments[case_id].append(
                    _assignment(case_id, source, role, "benchmark_included", "", len(assignments[case_id]) + 1)
                )
                selected_ids[case_id].add(source["company_id"])
                role_counts[case_id][role] = role_counts[case_id].get(role, 0) + 1

    role_targets = config.get("role_targets", {})
    roles = ["designer", "supplier", "contractor", "supervisor"]
    min_role_keyword_matches = max(1, int(config.get("min_role_keyword_matches", 1)))
    eligible_by_role = {
        role: [
            row
            for row in enterprise_rows
            if row.get("company_id")
            and _is_role_eligible(row, role, min_role_keyword_matches)
        ]
        for role in roles
    }
    required_by_role = {
        role: sum(
            max(0, int(role_targets.get(role, 5)) - role_counts[case_id].get(role, 0)
            )
            for case_id in case_ids
        )
        for role in roles
    }
    roles.sort(
        key=lambda role: (
            -(required_by_role[role] / max(1, len(eligible_by_role[role]))),
            role,
        )
    )

    max_share = float(config.get("max_distractor_case_share", 1.0))
    exposure_cap = max(1, math.floor(len(case_ids) * max_share))
    top_n = max(1, int(config.get("distractor_top_n", 20)))
    exposure_penalty = float(config.get("distractor_exposure_penalty", 8.0))
    seed = str(config.get("selection_seed", "codedemo-v2-candidate-pool-v1"))
    exposure: dict[str, int] = {}

    for role in roles:
        target = int(role_targets.get(role, 5))
        max_slots = max(max(0, target - role_counts[case_id].get(role, 0)) for case_id in case_ids)
        for slot in range(max_slots):
            active_cases = [case_id for case_id in case_ids if role_counts[case_id].get(role, 0) < target]
            active_cases.sort(key=lambda case_id: _stable_hash(seed, role, str(slot), case_id))
            for case_id in active_cases:
                project = project_by_case[case_id]
                ranked = []
                for row in eligible_by_role[role]:
                    company_id = row["company_id"]
                    if company_id in selected_ids[case_id] or exposure.get(company_id, 0) >= exposure_cap:
                        continue
                    score = _score_enterprise(project, row, role)
                    ranked.append((score, _stable_hash(seed, case_id, role, company_id), row))
                ranked.sort(key=lambda item: (-item[0], item[1], item[2]["company_id"]))
                band = ranked[:top_n]
                if not band:
                    raise ValueError(
                        f"Cannot fill diversified candidate pool for {case_id}/{role}; "
                        f"exposure_cap={exposure_cap}, eligible={len(eligible_by_role[role])}"
                    )
                chosen_score, _hash, chosen = max(
                    band,
                    key=lambda item: (
                        item[0] - exposure_penalty * exposure.get(item[2]["company_id"], 0),
                        -exposure.get(item[2]["company_id"], 0),
                        -item[1],
                    ),
                )
                company_id = chosen["company_id"]
                assignments[case_id].append(
                    _assignment(
                        case_id,
                        chosen,
                        role,
                        "diversified_distractor",
                        chosen_score,
                        role_counts[case_id].get(role, 0) + 1,
                    )
                )
                selected_ids[case_id].add(company_id)
                role_counts[case_id][role] = role_counts[case_id].get(role, 0) + 1
                exposure[company_id] = exposure.get(company_id, 0) + 1

    max_companies = int(config.get("max_companies", 30))
    for case_id in case_ids:
        if len(assignments[case_id]) + 1 > max_companies:
            raise ValueError(
                f"Diversified candidate pool exceeds max_companies for {case_id}: "
                f"{len(assignments[case_id]) + 1} > {max_companies}"
            )
    return assignments


def companies_from_candidate_assignments(
    project_row: dict[str, str],
    enterprise_rows: list[dict[str, str]],
    assignment_rows: list[dict[str, Any]],
) -> list[Company]:
    by_id = {row.get("company_id", ""): row for row in enterprise_rows if row.get("company_id")}
    companies = []
    for assignment in assignment_rows:
        company_id = str(assignment.get("company_id", ""))
        if company_id not in by_id:
            raise ValueError(f"Candidate assignment references unknown company_id: {company_id}")
        companies.append(_company(by_id[company_id], str(assignment.get("role", ""))))
    return [_owner_company(project_row), *companies]


def _assignment(
    case_id: str,
    row: dict[str, str],
    role: str,
    source: str,
    score: int | str,
    selection_rank: int,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "company_id": row.get("company_id", ""),
        "company_name": row.get("company_name", ""),
        "role": role,
        "source": source,
        "score": score,
        "selection_rank": selection_rank,
    }


def _stable_hash(*parts: str) -> int:
    text = "\x1f".join(parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(text).digest()[:8], "big")


def _role_match_score(row: dict[str, str], role: str) -> int:
    text = " ".join(
        [
            row.get("company_name", ""),
            row.get("business_scope", ""),
            row.get("industry", ""),
            row.get("past_project_experience", ""),
            row.get("certifications", ""),
        ]
    )
    return sum(1 for token in _role_keywords(role) if token in text)


def _is_role_eligible(row: dict[str, str], role: str, minimum_matches: int) -> bool:
    scores = {
        candidate_role: _role_match_score(row, candidate_role)
        for candidate_role in ["designer", "supplier", "contractor", "supervisor"]
    }
    primary_roles = _primary_role_hints(row)
    if primary_roles:
        return (
            role in primary_roles
            and scores[role] >= minimum_matches
            and scores[role] == max(scores.values())
        )
    if any(
        token in row.get("company_name", "")
        for token in ["投资", "投資", "控股", "置业", "置業", "资源经营", "資源經營"]
    ):
        return False
    return scores[role] >= minimum_matches and scores[role] == max(scores.values())


def _primary_role_hints(row: dict[str, str]) -> set[str]:
    name = row.get("company_name", "")
    industry = row.get("industry", "")
    roles: set[str] = set()
    if any(token in name for token in ["设计", "設計", "勘察", "測繪", "测绘", "規劃", "规划", "建筑师", "建築師"]):
        roles.add("designer")
    if any(token in name for token in ["监理", "監理", "检测", "檢測", "造价", "工料", "咨询", "諮詢", "顾问", "顧問", "项目管理"]):
        roles.add("supervisor")
    if any(token in name for token in ["工程局", "建築", "建筑", "建設", "建设", "建工", "裝飾", "装饰", "隧道工程", "路桥工程", "水利水电"]):
        roles.add("contractor")
    if any(token in name for token in ["设备", "設備", "材料", "科技", "动力", "動力", "机电", "機電", "电气", "電氣", "制造", "製造", "供应", "供應", "系统", "系統"]):
        roles.add("supplier")
    if roles:
        return roles
    if any(token in name for token in ["投资", "投資", "控股", "置业", "置業", "资源经营", "資源經營"]):
        return set()
    if any(token in industry for token in ["土木工程建筑", "房屋建筑", "建筑安装", "建筑装饰", "建築", "建筑业"]):
        return {"contractor"}
    if any(token in industry for token in ["制造业", "批发业", "零售业"]):
        return {"supplier"}
    return set()


def _validate_assigned_pool(
    case_id: str,
    companies: list[Company],
    benchmark_rows: list[dict[str, str]],
    config: dict[str, Any],
) -> None:
    company_ids = {company.company_id for company in companies}
    benchmark_ids = {row.get("company_id", "") for row in benchmark_rows if row.get("company_id")}
    if bool(config.get("include_benchmark_companies", True)) and not benchmark_ids <= company_ids:
        raise ValueError(f"Candidate assignments omit benchmark companies for {case_id}: {sorted(benchmark_ids - company_ids)}")
    role_targets = config.get("role_targets", {})
    for role, target in role_targets.items():
        count = sum(company.company_role == role for company in companies)
        if count < int(target):
            raise ValueError(f"Candidate assignments underfill {case_id}/{role}: {count} < {target}")


def _assigned_candidate_pool_details(
    assignment_rows: list[dict[str, str]], enterprise_rows: list[dict[str, str]]
) -> list[dict[str, Any]]:
    by_id = {row.get("company_id", ""): row for row in enterprise_rows if row.get("company_id")}
    details = []
    for assignment in assignment_rows:
        company_id = assignment.get("company_id", "")
        enterprise = by_id.get(company_id, {})
        details.append(
            {
                "company_id": company_id,
                "company_name": assignment.get("company_name") or enterprise.get("company_name", ""),
                "role": assignment.get("role", ""),
                "source": assignment.get("source", ""),
                "distractor_rank": assignment.get("selection_rank", "")
                if assignment.get("source") == "diversified_distractor"
                else "",
                "score": assignment.get("score", ""),
                "benchmark_role_original": "",
            }
        )
    return details


def build_candidate_company_pool(
    project_row: dict[str, str],
    enterprise_rows: list[dict[str, str]],
    benchmark_rows: list[dict[str, str]],
    config: dict[str, Any],
) -> list[Company]:
    max_companies = int(config.get("max_companies", 30))
    role_targets = config.get("role_targets", {})
    include_benchmark = bool(config.get("include_benchmark_companies", True))

    by_id = {row.get("company_id", ""): row for row in enterprise_rows if row.get("company_id")}
    by_name = {_norm(row.get("company_name", "")): row for row in enterprise_rows if row.get("company_name")}

    selected: list[tuple[dict[str, str], str, bool]] = []
    selected_ids: set[str] = set()

    if include_benchmark:
        for row in benchmark_rows:
            role = role_from_case_role(row.get("company_role_original", ""))
            source = by_id.get(row.get("company_id", "")) or by_name.get(_norm(row.get("matched_enterprise_name", "")))
            if source and source.get("company_id") not in selected_ids:
                selected.append((source, role, True))
                selected_ids.add(source["company_id"])

    for role in ["designer", "supplier", "contractor", "supervisor"]:
        target = int(role_targets.get(role, 5))
        current = sum(1 for _row, item_role, _benchmark in selected if item_role == role)
        if current >= target:
            continue
        for row in _rank_distractors(project_row, enterprise_rows, role):
            cid = row.get("company_id", "")
            if not cid or cid in selected_ids:
                continue
            selected.append((row, role, False))
            selected_ids.add(cid)
            current += 1
            if current >= target or len(selected) >= max_companies:
                break
        if len(selected) >= max_companies:
            break

    selected = selected[:max_companies]
    owner = _owner_company(project_row)
    return [owner, *[_company(row, role) for row, role, _is_benchmark in selected]]


def role_from_case_role(value: str) -> str:
    text = value.lower()
    if any(token in value for token in ["施工", "承建", "总承包", "總承包", "专业分包", "清拆", "建造"]):
        return "contractor"
    if any(token in value for token in ["供应", "供應", "制造", "製造", "材料", "设备", "設備"]):
        return "supplier"
    if any(token in value for token in ["设计", "設計", "勘察", "测绘", "測繪", "规划", "規劃"]):
        return "designer"
    if any(token in value for token in ["监理", "監理", "监察", "監察", "检测", "檢測", "质量", "質量", "工料", "造价", "顧問", "顾问", "咨询", "代建", "项目管理"]):
        return "supervisor"
    if any(token in text for token in ["design", "architect"]):
        return "designer"
    if any(token in text for token in ["build", "construction", "contractor"]):
        return "contractor"
    return "supervisor"


def _project_idea(row: dict[str, str]) -> ProjectIdea:
    constraints = [
        f"项目类型：{row.get('project_type', '')}",
        f"合作方向：{row.get('cooperation_direction', '')}",
        f"交付模式：{row.get('delivery_mode', '')}",
        f"业主：{row.get('owner_name', '')}",
        f"业主性质：{row.get('owner_type', '')}",
        f"评标标准提示：{row.get('evaluation_criteria_hint', '')}",
        f"底价提示：{row.get('reserve_price_hint', '')}",
    ]
    return ProjectIdea(
        row["case_id"],
        row.get("project_name", ""),
        row.get("project_type", ""),
        row.get("location", ""),
        _owner_intent(row),
        row.get("scale", "") or "由项目基础数据提供",
        row.get("investment_amount", "") or "原始数据未提供",
        "由业主方 agent 进一步细化",
        [item for item in constraints if item and not item.endswith("：")],
        "case_input",
    )


def _owner_intent(row: dict[str, str]) -> str:
    parts = [
        f"围绕「{row.get('project_name', '')}」开展招投标仿真。",
        f"项目属地为{row.get('location', '')}。",
        f"项目类型为{row.get('project_type', '')}。",
        f"交付模式为{row.get('delivery_mode', '')}。",
        "仿真输入不得包含真实合作企业和真实判给结果。",
    ]
    return "".join(part for part in parts if part)


def _owner_company(row: dict[str, str]) -> Company:
    owner_name = row.get("owner_name") or "案例业主单位"
    return Company(
        "owner_001",
        owner_name,
        "owner",
        f"{owner_name} 是本案例的业主方，负责项目招标策略、评标组织和模拟判给决策。",
        ["掌握项目目标", "熟悉澳门公共工程管理要求"],
        ["需要在有限基础信息下细化招标包和评标重点"],
        ["业主管理", "招标组织", "项目约束控制", "评标决策"],
        [row.get("project_name", "")],
        "项目业主组织",
        ["公共项目透明度要求高", "跨区域协作和接口协调要求高"],
        ["design_package", "supplier_package", "contractor_package", "supervision_package"],
    )


def _company(row: dict[str, str], role: str) -> Company:
    name = row.get("company_name", "")
    profile_parts = [
        f"{name} 是候选企业池中的{_role_name(role)}企业。",
        f"企业类型：{row.get('enterprise_type', '')}。",
        f"办公地点：{row.get('office_location', '')}。",
        f"经营范围：{row.get('business_scope', '')}。",
    ]
    qualifications = [
        row.get("business_scope", ""),
        row.get("certifications", ""),
        row.get("industry", ""),
        _role_capability(role),
    ]
    strengths = [
        item
        for item in [
            _nonempty("代表项目经验", row.get("past_project_experience", "")),
            _nonempty("合作伙伴或客户基础", row.get("partners_or_clients", "")),
            _role_capability(role),
        ]
        if item
    ][:4]
    weaknesses = [
        item
        for item in [
            _nonempty("公开数据缺口", _missing_fields(row)),
            _nonempty("风险信号", row.get("risk_signals", "")),
        ]
        if item
    ] or ["需要进一步核实项目资源投入和具体报价能力"]
    return Company(
        row.get("company_id", ""),
        name,
        role,
        " ".join(part for part in profile_parts if part and not part.endswith("：。")),
        strengths,
        weaknesses,
        [item for item in qualifications if item],
        [row.get("past_project_experience", "") or "企业信息表未提供明确代表项目"],
        row.get("staff_scale", "") or row.get("insured_staff_count", "") or "企业信息表未提供明确规模",
        [item for item in [row.get("risk_signals", ""), row.get("compliance", "")] if item],
        ROLE_PACKAGES[role],
    )


def _rank_distractors(project_row: dict[str, str], rows: list[dict[str, str]], role: str) -> list[dict[str, str]]:
    scored = [(_score_enterprise(project_row, row, role), row) for row in rows if row.get("company_id")]
    scored.sort(key=lambda item: (-item[0], item[1].get("company_id", "")))
    return [row for score, row in scored if score > 0]


def _score_enterprise(project_row: dict[str, str], row: dict[str, str], role: str) -> int:
    text = " ".join(
        [
            row.get("company_name", ""),
            row.get("business_scope", ""),
            row.get("industry", ""),
            row.get("past_project_experience", ""),
            row.get("partners_or_clients", ""),
            row.get("office_location", ""),
        ]
    )
    score = 0
    for token in _role_keywords(role):
        if token in text:
            score += 6
    for token in [project_row.get("location", ""), "澳门", "澳門", "大湾区", "灣區", "珠海", "广州", "深圳"]:
        if token and token in text:
            score += 2
    for token in ["交通", "桥", "橋", "道路", "口岸", "市政", "基础设施", "基礎設施", "公共工程"]:
        if token in text:
            score += 3
    return score


def _role_keywords(role: str) -> list[str]:
    return {
        "designer": ["设计", "設計", "规划", "規劃", "建筑师", "建築師", "工程顾问", "工程顧問", "勘察", "测绘", "測繪"],
        "supplier": ["供应", "供應", "设备", "設備", "材料", "制造", "製造", "系统", "系統"],
        "contractor": ["施工", "承建", "建造", "建筑", "建築", "总承包", "總承包"],
        "supervisor": ["监理", "監理", "监察", "監察", "检测", "檢測", "质量", "質量", "咨询", "諮詢", "顾问", "顧問", "造价", "工料", "项目管理"],
    }[role]


def _role_capability(role: str) -> str:
    return {
        "designer": "设计协调和业主审查提交能力",
        "supplier": "供应协调、质量文件和售后支持能力",
        "contractor": "施工组织、安全管理和进度控制能力",
        "supervisor": "第三方监察、质量记录和业主报告能力",
    }[role]


def _role_name(role: str) -> str:
    return {
        "designer": "设计",
        "supplier": "供应",
        "contractor": "施工",
        "supervisor": "监管/顾问",
    }[role]


def _candidate_pool_summary(companies: list[Company]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for company in companies:
        counts[company.company_role] = counts.get(company.company_role, 0) + 1
    return {"company_count": len(companies), "role_counts": counts}


def _candidate_pool_details(
    project_row: dict[str, str],
    companies: list[Company],
    enterprise_rows: list[dict[str, str]],
    benchmark_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    enterprise_by_id = {row.get("company_id", ""): row for row in enterprise_rows if row.get("company_id")}
    benchmark_by_id = {row.get("company_id", ""): row for row in benchmark_rows if row.get("company_id")}
    distractor_rank_by_role: dict[str, int] = {}
    details = []
    for company in companies:
        if company.company_role == "owner":
            continue
        benchmark_row = benchmark_by_id.get(company.company_id)
        source = "benchmark_included" if benchmark_row else "top_scored_distractor"
        rank = ""
        if not benchmark_row:
            distractor_rank_by_role[company.company_role] = distractor_rank_by_role.get(company.company_role, 0) + 1
            rank = distractor_rank_by_role[company.company_role]
        enterprise_row = enterprise_by_id.get(company.company_id, {})
        details.append(
            {
                "company_id": company.company_id,
                "company_name": company.company_name,
                "role": company.company_role,
                "source": source,
                "distractor_rank": rank,
                "score": _score_enterprise(project_row, enterprise_row, company.company_role) if enterprise_row else "",
                "benchmark_role_original": benchmark_row.get("company_role_original", "") if benchmark_row else "",
            }
        )
    return details


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _norm(value: str) -> str:
    value = value.lower()
    value = value.replace("（", "(").replace("）", ")")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[·•．.、,，/\\-]", "", value)
    return value


def _nonempty(label: str, value: str) -> str:
    return f"{label}：{value}" if value else ""


def _missing_fields(row: dict[str, str]) -> str:
    missing = [field for field in ["staff_scale", "certifications", "revenue", "profit"] if not row.get(field)]
    return "、".join(missing)
