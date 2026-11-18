"""Render config/micro_org_rubric.json as a readable table: docs/micro_org_rubric_levels.md.

Run:  python -m scripts.render_micro_org_rubric
The JSON file is the single source; rerun this after editing it.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    rubric = json.loads((ROOT / "config/micro_org_rubric.json").read_text(encoding="utf-8"))
    out = [f"# 评分规则逐档标准（{rubric['rubric_id']}）", "",
           "本页由 `scripts/render_micro_org_rubric.py` 从 [config/micro_org_rubric.json](../config/micro_org_rubric.json) 生成，"
           "请改 JSON 后重新生成，不要直接改本页。设计说明见 [micro_org_rubric.md](micro_org_rubric.md)。", "",
           "## 判档规则", ""]
    out += [f"{index}. {rule}" for index, rule in enumerate(rubric["scoring_rules"], start=1)]
    out += ["", "## 六个结果维度", "", "| 编号 | 维度 | 判什么 |", "|---|---|---|"]
    out += [f"| {c['id']} | {c['name_zh']} | {c['question']} |" for c in rubric["criteria"]]
    for index, spec in enumerate(rubric["unit_types"].values(), start=1):
        out += ["", f"## 输出类型 {index}：{spec['name_zh']}", "", spec["product"], "",
                "R2 的事项清单：" + "；".join(f"({i}) {item}" for i, item in enumerate(spec["coverage_checklist"], start=1)) + "。",
                "", f"R5 的说明：{spec['grounding_note']}", ""]
        for criterion in rubric["criteria"]:
            levels = spec["levels"][criterion["id"]]
            out += [f"### {criterion['id']} {criterion['name_zh']}", "", "| 档位 | 判档条件 |", "|---|---|"]
            out += [f"| {level} | {levels[level]} |" for level in ("5", "4", "3", "2", "1")]
            out.append("")
    out += ["## 讨论过程维度（只评有讨论记录的臂）", ""]
    for criterion in rubric["process_criteria"]:
        out += [f"### {criterion['id']} {criterion['name_zh']}", "", criterion["question"], "",
                "| 档位 | 判档条件 |", "|---|---|"]
        out += [f"| {level} | {criterion['levels'][level]} |" for level in ("5", "4", "3", "2", "1")]
        out.append("")
    out += ["## 过程失败标记（是/否）", "", "| 标记 | 含义 |", "|---|---|"]
    out += [f"| {flag['name_zh']} | {flag['meaning']} |" for flag in rubric["process_failure_flags"]]
    path = ROOT / "docs/micro_org_rubric_levels.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
