"""Shared SQLite catalog imported from input-only CSVs; never reads benchmark files."""
from __future__ import annotations

import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3

from src.models import Company
from integration.contracts import digest
from integration.shared_data import SharedDataset

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data/test_sources/casebank_enterprise_matched"
DEFAULT_DATABASE = ROOT / "output/integration/shared_catalog.sqlite3"
PROJECT_FIELDS = ("case_id", "project_name", "project_type", "location", "delivery_mode", "owner_name", "scale")
COMPANY_FIELDS = ("company_id", "company_name", "office_location", "business_scope", "industry", "certifications")
ROLE_WORDS = {
    "designer": ("建筑设计", "建築設計", "建筑师", "建築師", "工程设计", "工程設計", "交通规划", "交通規劃", "設計研究", "设计研究"),
    "supervisor": ("造价", "造價", "工料", "测量师", "測量師", "工程咨询", "工程諮詢", "工程顾问", "工程顧問", "监理", "監理"),
    "contractor": ("工程施工", "建築工程", "建筑工程", "建设工程", "建設工程", "土木", "承建", "建设集团", "建設集團", "建筑集团", "建築集團", "路桥", "路橋", "市政工程"),
    "supplier": ("建材", "混凝土", "水泥", "钢材", "鋼材", "建筑材料", "建築材料", "工程材料", "沥青", "瀝青", "预制", "預製"),
}


def _read(path, fields):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return [{key: str(row.get(key) or "").strip() for key in fields} for row in csv.DictReader(stream)]


def stable_id(prefix, name):
    return prefix + hashlib.sha256(name.strip().encode()).hexdigest()[:14]


def region(value):
    for local, normalized in (("澳门", "Macau"), ("澳門", "Macau"), ("香港", "Hong Kong"), ("深圳", "Shenzhen"), ("广州", "Guangzhou"), ("廣州", "Guangzhou"), ("珠海", "Zhuhai")):
        if local in value:
            return normalized
    return "Macau"  # Explicit scenario location for unresolved/outside-GBA entities.


class SharedCatalog:
    def __init__(self, path=DEFAULT_DATABASE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS companies (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scenarios (version TEXT PRIMARY KEY, case_id TEXT NOT NULL, payload TEXT NOT NULL);
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def import_inputs(self, source=DEFAULT_SOURCE):
        source = Path(source)
        projects = _read(source / "simulation_input_projects.csv", PROJECT_FIELDS)
        companies = _read(source / "simulation_input_enterprises.csv", COMPANY_FIELDS)
        if len({p["case_id"] for p in projects}) != len(projects) or len({c["company_id"] for c in companies}) != len(companies):
            raise ValueError("Duplicate source IDs")
        evidence = {"source": str(source.resolve()), "project_count": len(projects), "company_count": len(companies),
                    "project_fields": PROJECT_FIELDS, "company_fields": COMPANY_FIELDS,
                    "excluded": ["hidden_benchmark", "candidate_assignments", "past_project_experience", "partners_or_clients", "investment_amount", "reserve_price_hint", "evaluation_criteria_hint"],
                    "input_version": digest({"projects": projects, "companies": companies}),
                    "source_sha256": {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                                      for name in ("simulation_input_projects.csv", "simulation_input_enterprises.csv")}}
        with self.connect() as db:
            # Replace only catalog input tables atomically; stored run scenarios are immutable.
            db.execute("DELETE FROM projects")
            db.execute("DELETE FROM companies")
            db.executemany("INSERT INTO projects VALUES (?, ?)", [(p["case_id"], json.dumps(p, ensure_ascii=False)) for p in projects])
            db.executemany("INSERT INTO companies VALUES (?, ?)", [(c["company_id"], json.dumps(c, ensure_ascii=False)) for c in companies])
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('import', ?)", (json.dumps(evidence, ensure_ascii=False),))
        return evidence

    def list_projects(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM projects ORDER BY id")]

    def metadata(self):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM metadata WHERE key='import'").fetchone()
        return json.loads(row[0]) if row else {}

    def save_scenario(self, dataset):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO scenarios VALUES (?, ?, ?)",
                       (dataset.version, next(iter(dataset.projects)), json.dumps(dataset.payload, ensure_ascii=False)))

    def scenario(self, case_id="CASE-0005", budget=150_000_000, duration=24, seed=42,
                 candidate_policy=None):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM projects WHERE id=?", (case_id,)).fetchone()
            if not row:
                raise ValueError("Unknown project ID")
            project = json.loads(row[0])
            enterprises = [json.loads(x[0]) for x in db.execute("SELECT payload FROM companies ORDER BY id")]
        if project["delivery_mode"].strip().upper() != "DBB":
            raise ValueError("Select a DBB project for the currently supported procurement lifecycle")
        owner_name = project["owner_name"] or f"Scenario owner for {case_id}"
        owner_id = stable_id("OWNER-", owner_name)
        owner = Company(owner_id, owner_name, "owner", "项目输入中的业主；具体采购行为由组织成员讨论。", [], [], [], [], "见情景参数", [], [])
        companies, selected, evidence = [asdict(owner)], set(), {}
        candidate_audit = None
        for role, count in (("designer", 2), ("supervisor", 2), ("contractor", 3), ("supplier", 2)):
            if role == 'contractor' and candidate_policy is not None:
                from integration.candidate_policy import retrieve
                if set(candidate_policy) != {'version', 'contractor_count'} or candidate_policy['version'] not in {'public-project-fit.v2', 'public-project-fit.v3'}:
                    raise ValueError('Unknown candidate policy')
                if candidate_policy['version'] == 'public-project-fit.v3':
                    from integration.candidate_policy_v3 import retrieve
                picked, candidate_audit = retrieve(project, enterprises,
                    count=candidate_policy['contractor_count'], seed=seed, excluded=selected)
                for enterprise in picked:
                    key = enterprise['company_id']; selected.add(key)
                    basis = next(row for row in candidate_audit if row['company_id'] == key)
                    evidence[key] = {**basis, 'scenario_role': role, 'selection': 'input_fields_only_no_benchmark'}
                    companies.append(asdict(Company(key, enterprise['company_name'], role,
                        '企业公开资料：' + (enterprise['business_scope'] or '经营范围未知') + '；评分仅为文本匹配代理，资质未核实。',
                        [], [], [enterprise['certifications']] if enterprise['certifications'] else [], [], '以授权情景资源为准', [], [])))
                continue
            eligible = []
            for enterprise in enterprises:
                text = " ".join(enterprise[key] for key in ("company_name", "business_scope", "industry"))
                matches = [w for w in ROLE_WORDS[role] if w in text]
                if not matches or enterprise["company_id"] in selected or enterprise["company_name"] == owner_name:
                    continue
                domain = sum(w in text for w in ("市政", "交通", "道路", "路桥", "路橋", "土木"))
                score = len(matches) + domain * 3 + (3 if region(enterprise["office_location"]) == region(project["location"]) else 0)
                tie = stable_id("", f"{seed}/{case_id}/{role}/{enterprise['company_id']}")
                eligible.append((-score, tie, enterprise, matches))
            eligible.sort(key=lambda item: (item[0], item[1]))
            if len(eligible) < count:
                raise ValueError(f"Not enough input-only candidates for {role}")
            for _, _, enterprise, matches in eligible[:count]:
                key = enterprise["company_id"]
                selected.add(key)
                evidence[key] = {"source_id": key, "scenario_role": role, "role_evidence": matches,
                                 "source_region": enterprise["office_location"], "selection": "input_fields_only_no_benchmark"}
                companies.append(asdict(Company(key, enterprise["company_name"], role,
                    f"本地企业资料：{enterprise['business_scope'] or enterprise['company_name']}。本次为情景试运行，不复现历史中标结果。",
                    [], [], [enterprise["certifications"]] if enterprise["certifications"] else [], [], "以授权情景资源为准", [], [])))
        location = region(project["location"])
        currency = "MOP" if location == "Macau" else "HKD" if location == "Hong Kong" else "CNY"
        payload = {"schema_version": "1.0", "companies": companies,
            "projects": [{"project_id": case_id, "name": project["project_name"], "owner_id": owner_id,
                "region": location, "project_type": "infrastructure", "scope": f"{project['project_type']}；{project['scale']}；{project['project_name']}",
                "budget": budget, "currency": currency, "duration_months": duration, "delivery_mode": "DBB"}],
            "packages": [], "environment": {}, "policy": {},
            "assumptions": {"version": "shared-dbb-scenario-20260920-v2", "source_note": "真实项目/企业基本描述 + 明示情景预算、工期、角色资格和数值能力；不代表真实企业能力估计，也不是历史采购回放。",
                "catalog": self.metadata(), "candidate_selection": evidence,
                "eligibility": "本次机制情景允许列出的候选以所分配角色独立投标或联合投标；不以缺失历史资质字段推断实际资格。企业仍可基于商业判断拒绝。",
                "units": {"resource": "normalized_enterprise_capacity", "time": "months", "currency": currency},
                "enterprise_parameters": {}, "enterprise_regions": {},
                "support_agents": [{"agent_id": f"REGULATOR-{location}", "name": "Scenario regulator", "role": "Government", "enterprise_type": "scenario_support", "region": location,
                                    "total_resource_capacity": 3, "policy_adaptability": .9}],
                "budget_origin": "scenario_assumption_not_observed_cost", "duration_origin": "scenario_assumption_not_observed_duration"}}
        for c in companies:
            payload["assumptions"]["enterprise_parameters"][c["company_id"]] = {
                "total_resource_capacity": 2.0, "qualification_level": .85, "financial_capacity": .8,
                "technical_capability": .8, "management_capability": .8, "design_capability": .8,
                "cost_estimation_capability": .8, "construction_capability": .8, "safety_management_capability": .8,
                "quality_management_capability": .8, "supply_reliability": .8, "material_quality": .8, "policy_adaptability": .8}
            payload["assumptions"]["enterprise_regions"][c["company_id"]] = location
        def package(suffix, kind, fraction, scope, dependencies=(), parent=None):
            role = {"design": "designer", "cost_consulting": "supervisor", "construction": "contractor", "supply": "supplier"}[kind]
            return {"package_id": f"{case_id}/{suffix}", "project_id": case_id, "kind": kind,
                "buyer_id": "$construction_lead" if parent else owner_id, "name": scope, "scope": scope,
                "budget": round(budget * fraction, 2), "currency": currency, "resource_required": .7 if kind == "construction" else .25,
                "depends_on": list(dependencies), "cost_inclusion": "included_in_parent" if parent else "owner_additional",
                "parent_package_id": parent, "candidate_ids": [c["company_id"] for c in companies if c["company_role"] == role]}
        payload["packages"] = [package("design", "design", .03, "总体及施工图设计与现场设计配合"), package("cost", "cost_consulting", .015, "造价咨询与合同成本管理")]
        for suffix, scope in (("A", "道路及场地土建施工"), ("B", "排水、交通附属及配套设施施工")):
            parent = f"{case_id}/construction-{suffix}"
            payload["packages"] += [package(f"construction-{suffix}", "construction", .425, scope, [f"{case_id}/design", f"{case_id}/cost"]),
                package(f"supply-{suffix}", "supply", .12, f"{scope}所需材料采购（包含在所属施工合同价内）", [parent], parent)]
        dataset = SharedDataset(payload)
        if candidate_audit is not None:
            payload['assumptions']['candidate_audit'] = candidate_audit
            payload['assumptions']['candidate_policy'] = candidate_policy
            dataset = SharedDataset(payload)
        self.save_scenario(dataset)
        return dataset


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--case", default="CASE-0005")
    parser.add_argument("--output", type=Path, default=ROOT / "output/integration/CASE-0005-shared.json")
    args = parser.parse_args()
    catalog = SharedCatalog(args.database)
    metadata = catalog.import_inputs(args.source)
    data = catalog.scenario(args.case)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data.payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"projects": metadata["project_count"], "companies": metadata["company_count"], "case": args.case, "version": data.version, "output": str(args.output)}, ensure_ascii=False))
