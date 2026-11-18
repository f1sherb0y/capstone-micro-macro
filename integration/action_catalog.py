"""Source-grounded action inventory. Registration is not implementation evidence."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ROLE_SPECS = {
    "owner": ("Owner", "OWN", 16), "bank": ("Bank", "BANK", 13),
    "architect": ("Architect", "ARCHITECT", 13), "engineer": ("Engineer", "ENGINEER", 13),
    "qs": ("QS", "QS", 13), "government": ("Government", "GOV", 12),
    "contractor": ("Contractor", "CONTRACTOR", 13), "supplier": ("Supplier", "SUPPLIER", 13),
}
# Each action has one principal implementation batch; these are not world phases.
BATCHES = {
    "owner": {"P4": (1, 2, 3, 4, 5, 9, 10, 16), "P5": (6, 7, 8, 11), "P6": (12, 13, 14, 15)},
    "bank": {"P4": (1, 2, 3, 4, 5, 13), "P5": (6, 7, 8, 9), "P6": (10, 11, 12)},
    "architect": {"P4": (1, 2, 3, 13), "P5": (4, 5, 6, 7, 8, 9, 10), "P6": (11, 12)},
    "engineer": {"P4": (1, 2, 3, 13), "P5": (4, 5, 6, 7, 8, 9, 10), "P6": (11, 12)},
    "qs": {"P4": (1, 2, 3, 4, 5, 6, 13), "P5": (7, 8, 10), "P6": (9, 11, 12)},
    "government": {"P4": (1,), "P5": (2, 3, 4, 5, 6, 7, 8, 9, 10), "P6": (11, 12)},
    "contractor": {"P4": (1, 2, 3, 4, 13), "P5": (5, 6, 7, 8, 9, 10), "P6": (11, 12)},
    "supplier": {"P4": (1, 2, 3, 4, 13), "P5": (5, 6, 7, 8, 9, 10, 11), "P6": (12,)},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line(card: str, label: str) -> str:
    match = re.search(rf"^- \*\*{re.escape(label)}\*\*[：:]\s*(.+)$", card, re.M)
    if not match:
        raise ValueError(f"Missing source section: {label}")
    return match.group(1)


def _section(content: str, heading: str) -> str:
    match = re.search(rf"^{heading}[^\n]*\n", content, re.M)
    if not match:
        raise ValueError(f"Missing source section: {heading}")
    following = re.search(r"^##?\s", content[match.end():], re.M)
    end = match.end() + following.start() if following else len(content)
    return content[match.start():end]


def check_ids(content: str) -> list[str]:
    tokens = re.findall(r"CHECK-([A-Z]+)-(\d{3}(?:/\d{3})*)", content)
    return sorted({f"CHECK-{prefix}-{number}" for prefix, numbers in tokens
                   for number in numbers.split("/")})


def build_catalog(root: Path = ROOT) -> dict:
    root = Path(root)
    source_dir = root / "zwtnew/04_roles/04_roles"
    actions, sources = [], {}
    for filename, (role, prefix, count) in ROLE_SPECS.items():
        source = source_dir / f"{filename}.md"
        relative = source.relative_to(root).as_posix()
        content = source.read_text(encoding="utf-8-sig")
        sources[relative] = sha256(source)
        local_types = _section(content, r"### 3\.2\b")
        method_dependencies = _section(content, r"## 7\.")
        role_checks = check_ids(_section(content, r"## 6\."))
        pattern = rf"^###\s+({prefix}-A\d{{2}})\s*[｜·]\s*(.+)$"
        headings = list(re.finditer(pattern, content, re.M))
        expected = {f"{prefix}-A{n:02d}" for n in range(1, count + 1)}
        actual = [match.group(1) for match in headings]
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError(f"Source action set mismatch: {role}: {actual}")
        assignment = {}
        for batch, numbers in BATCHES[filename].items():
            for number in numbers:
                if number in assignment:
                    raise ValueError(f"Repeated batch assignment: {role} A{number:02d}")
                assignment[number] = batch
        if set(assignment) != set(range(1, count + 1)):
            raise ValueError(f"Incomplete batch assignment: {role}")
        for index, match in enumerate(headings):
            # Stop at any next heading, so trailing matrices do not contaminate a card.
            following = re.search(r"^#{1,3}\s", content[match.end():], re.M)
            end = match.end() + following.start() if following else len(content)
            card = content[match.start():end]
            action_id = match.group(1)
            signature = _line(card, "函数")
            function_match = re.search(r"`(roles\.\w+\.a\d+)\(ctx: ActionContext, input: (\w+)\) -> ActionResult<(\w+)>`", signature)
            if not function_match:
                raise ValueError(f"Cannot parse function contract: {action_id}")
            function, input_type, payload_type = function_match.groups()
            if function != f"roles.{filename}.a{action_id[-2:]}":
                raise ValueError(f"Function identity mismatch: {action_id}")
            input_text = _line(card, "输入记录")
            payload_text = _line(card, "输出分支")
            choice_match = re.search(r"choice:\s*([^,}]+)", payload_text)
            choices = ([value.strip() for value in choice_match.group(1).split("/")]
                       if choice_match else re.findall(r"(?:`|;\s*)([a-z_]+)\{", payload_text))
            if not choices:
                raise ValueError(f"Cannot index payload choices: {action_id}")
            checks = check_ids(card)
            if not checks:
                raise ValueError(f"No source checks: {action_id}")
            try:
                constraints = _line(card, "分支前置与约束")
            except ValueError:
                # Professional-role cards define constraints in their narrative
                # and section 3.2 instead of this optional named subsection.
                constraints = None
            actions.append({
                "action_id": action_id, "role": role, "role_key": filename,
                "title": match.group(2).strip(), "function": function,
                "input_type": input_type, "payload_type": payload_type,
                "input_definition": input_text, "payload_definition": payload_text,
                "choices": choices, "checks": checks,
                "role_checks": role_checks,
                "local_type_definitions": local_types,
                "role_method_dependencies": method_dependencies,
                "method_profile_kinds": sorted({kind for kind in re.findall(
                    r"Ref<(\w+)>", input_text + payload_text + local_types)
                    if re.search(r"Method|Profile|Calculation|Rule$", kind)}),
                "binding_gaps": {choice: {
                    "status": "unverified", "macro_version": "gba-public-2026-08-21",
                    "missing": ["equivalence", "input_producer", "authorized_projection",
                                "execution_entry", "receipt", "feedback"],
                    "closure": "Trace actual source symbols and run the branch through the formal endpoint",
                } for choice in choices},
                "constraints": constraints,
                "business_effect": (_line(card, "来源、接收与核心效果")
                                    if "**来源、接收与核心效果**" in card else _line(card, "接收与核心效果")),
                "business_exits": _line(card, "业务出口与验收"),
                "source": relative, "source_sha256": sources[relative],
                "source_line": content[:match.start()].count("\n") + 1,
                "card_sha256": hashlib.sha256(card.encode("utf-8")).hexdigest(),
                "source_card": card,
                "implementation_batch": assignment[int(action_id[-2:])],
            })
    common = root / "zwtnew/gba_simulation_developer_guide/gba_simulation_developer_guide/06_engineering/interface_contracts.md"
    sources[common.relative_to(root).as_posix()] = sha256(common)
    system = common.with_name("system_interfaces.md")
    sources[system.relative_to(root).as_posix()] = sha256(system)
    if len(actions) != 106 or len({a["action_id"] for a in actions}) != 106:
        raise ValueError("Expected exactly 106 unique actions")
    return {"schema_version": "action-catalog.v1", "source_hashes": sources,
            "counts": dict(Counter(a["role"] for a in actions)), "actions": actions}


def initial_coverage(catalog: dict) -> dict:
    return {"schema_version": "action-coverage.v1", "actions": [{
        "action_id": a["action_id"], "source_sha256": a["source_sha256"],
        "implementation_batch": a["implementation_batch"],
        "contract": "source_indexed", "decision": "pending", "method": "unassessed",
        "binding": "unverified", "feedback": "pending", "validation": "pending",
        "branches": {choice: "pending" for choice in a["choices"]},
        "evidence": [], "gaps": [{"kind": "binding_unverified", "detail": "Source specification is not an executable endpoint"}],
    } for a in catalog["actions"]]}


def validate_coverage(catalog: dict, coverage: dict) -> None:
    records = coverage["actions"]
    expected = {a["action_id"]: a for a in catalog["actions"]}
    ids = [record["action_id"] for record in records]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise ValueError("Coverage inventory mismatch or duplicate action")
    for record in records:
        action = expected[record["action_id"]]
        if record["source_sha256"] != action["source_sha256"]:
            raise ValueError(f"Stale coverage source: {record['action_id']}")
        if record["implementation_batch"] != action["implementation_batch"]:
            raise ValueError(f"Coverage batch mismatch: {record['action_id']}")
        if set(record["branches"]) != set(action["choices"]):
            raise ValueError(f"Coverage branch mismatch: {record['action_id']}")


def write_new(path: Path, payload: dict) -> None:
    """Never overwrite an existing evidence file or silently clear progress."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--enrich", action="store_true", help="Enrich an unchanged source inventory; preserve coverage")
    args = parser.parse_args()
    catalog = build_catalog()
    path = ROOT / "config/action_registry.json"
    coverage = ROOT / "宏微观衔接方案/新版方案/action_coverage.json"
    if args.enrich:
        previous = json.loads(path.read_text(encoding="utf-8"))
        if any(catalog["source_hashes"].get(path) != value for path, value in previous["source_hashes"].items()):
            raise ValueError("Source changed; explicit migration required")
        for old, new in zip(previous["actions"], catalog["actions"], strict=True):
            if any(new.get(key) != value for key, value in old.items()):
                raise ValueError(f"Existing declaration changed: {old['action_id']}")
        validate_coverage(catalog, json.loads(coverage.read_text(encoding="utf-8")))
        path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.write:
        write_new(path, catalog)
        if not coverage.exists():
            write_new(coverage, initial_coverage(catalog))
    if args.check:
        if json.loads(path.read_text(encoding="utf-8")) != catalog:
            raise ValueError("Registered action source changed; review and migrate explicitly")
        validate_coverage(catalog, json.loads(coverage.read_text(encoding="utf-8")))
    print(json.dumps({"action_count": len(catalog["actions"]), "counts": catalog["counts"],
                      "batches": dict(Counter(a["implementation_batch"] for a in catalog["actions"]))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
