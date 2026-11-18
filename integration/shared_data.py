"""One explicit, versioned input, two views. This module never imports case_sources."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path

from src.models import Company, ProjectIdea
from integration.contracts import PackageSpec, digest, positive


@dataclass
class SharedDataset:
    payload: dict

    @classmethod
    def load(cls, path: str | Path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8-sig")))

    def __post_init__(self):
        self.payload = deepcopy(self.payload)
        if set(self.payload) - {"schema_version", "companies", "projects", "packages", "assumptions", "environment", "policy"}:
            raise ValueError("Unknown shared-input fields (historical outcomes are not accepted)")
        if self.payload.get("schema_version") != "1.0":
            raise ValueError("Unsupported shared input version")
        self.companies = {c["company_id"]: Company(**c) for c in self.payload["companies"]}
        self.projects = {p["project_id"]: p for p in self.payload["projects"]}
        if not self.companies or not self.projects:
            raise ValueError("Explicit companies and projects must not be empty")
        for company in self.companies.values():
            if not isinstance(company.company_id, str) or not company.company_id.strip() or company.company_role not in {"owner", "designer", "supervisor", "contractor", "supplier"}:
                raise ValueError("Unsupported company identity/role")
        self.packages = [PackageSpec(**{**p, "depends_on": tuple(p.get("depends_on", [])),
                                      "candidate_ids": tuple(p.get("candidate_ids", []))}) for p in self.payload["packages"]]
        if len(self.companies) != len(self.payload["companies"]) or len(self.projects) != len(self.payload["projects"]):
            raise ValueError("Duplicate entity/project IDs")
        by_id = {p.package_id: p for p in self.packages}
        if len(by_id) != len(self.packages):
            raise ValueError("Package IDs must be unique across projects")
        assumptions = self.payload["assumptions"]
        if not assumptions.get("version") or not assumptions.get("source_note"):
            raise ValueError("Explicit assumptions need a version and source note")
        if set(assumptions.get("enterprise_parameters", {})) != set(self.companies) or set(assumptions.get("enterprise_regions", {})) != set(self.companies):
            raise ValueError("Every enterprise requires explicit parameters and a region")
        support_ids = [a["agent_id"] for a in assumptions.get("support_agents", [])]
        if len(support_ids) != len(set(support_ids)) or set(support_ids) & set(self.companies):
            raise ValueError("Support agent IDs must be unique and separate from enterprises")
        for project in self.projects.values():
            if set(project) - {"project_id", "name", "owner_id", "region", "project_type", "scope", "budget", "currency", "duration_months", "delivery_mode"}:
                raise ValueError("Unexpected project fact/label")
            positive(project["budget"], "project budget")
            positive(project["duration_months"], "planned duration")
            if project["delivery_mode"] != "DBB":
                raise ValueError("This version supports explicitly declared DBB procurement only")
            if project["owner_id"] not in self.companies or self.companies[project["owner_id"]].company_role != "owner":
                raise ValueError("Project requires an explicit owner entity")
            packs = [p for p in self.packages if p.project_id == project["project_id"]]
            if not all(any(p.kind == kind for p in packs) for kind in ("design", "cost_consulting", "construction", "supply")):
                raise ValueError("DBB requires design, cost consulting, construction and supply procurement")
            if sum(p.budget for p in packs if p.cost_inclusion == "owner_additional") > project["budget"] + 1e-8:
                raise ValueError("Owner package budgets exceed project budget")
        for package in self.packages:
            if package.project_id not in self.projects or package.currency != self.projects[package.project_id]["currency"]:
                raise ValueError("Invalid project reference or currency mismatch")
            if package.buyer_id not in self.companies and package.buyer_id != "$construction_lead":
                raise ValueError("Unknown buyer")
            if not package.candidate_ids or len(set(package.candidate_ids)) != len(package.candidate_ids):
                raise ValueError("Specify unique eligible candidates")
            for candidate in package.candidate_ids:
                if candidate not in self.companies or self.companies[candidate].company_role != package.micro_role or candidate == package.buyer_id:
                    raise ValueError("Candidate role/identity mismatch")
            for dependency in package.depends_on:
                if dependency not in by_id or by_id[dependency].project_id != package.project_id:
                    raise ValueError("Unknown/cross-project package dependency")
            if package.parent_package_id:
                parent = by_id.get(package.parent_package_id)
                if not parent or parent.project_id != package.project_id or package.parent_package_id not in package.depends_on:
                    raise ValueError("Parent contract must be a same-project dependency")
        pending = set(by_id)
        while pending:
            ready = {key for key in pending if not set(by_id[key].depends_on) & pending}
            if not ready:
                raise ValueError("Cyclic procurement dependencies")
            pending -= ready
        # These are the supported DBB phase boundaries. Reject plans that would
        # wait forever or silently lose a second design/QS execution profile.
        for project_id, project in self.projects.items():
            packs = [p for p in self.packages if p.project_id == project_id]
            for kind in ("design", "cost_consulting"):
                if sum(p.kind == kind for p in packs) != 1:
                    raise ValueError("Current DBB execution requires one design and one cost-consulting package")
            for package in packs:
                if package.kind in {"design", "cost_consulting"} and package.depends_on:
                    raise ValueError("Initial service packages cannot depend on other packages")
                if package.kind == "construction" and any(by_id[d].kind not in {"design", "cost_consulting", "construction"} for d in package.depends_on):
                    raise ValueError("Construction dependencies may only reference initial services or predecessor construction contracts")
                if package.kind == "supply":
                    parent = by_id.get(package.parent_package_id)
                    if not parent or parent.kind != "construction" or package.buyer_id != "$construction_lead" or package.cost_inclusion != "included_in_parent":
                        raise ValueError("Supply must be included in a construction parent and purchased by its lead")
                    if any(by_id[d].kind == "supply" for d in package.depends_on):
                        raise ValueError("Supply packages cannot depend on other supply packages")
                elif package.parent_package_id or package.cost_inclusion != "owner_additional" or package.buyer_id != project["owner_id"]:
                    raise ValueError("Initial services and construction require an owner-funded contract")
            for construction in (p for p in packs if p.kind == "construction"):
                supplies = [p for p in packs if p.parent_package_id == construction.package_id]
                if not supplies or sum(p.budget for p in supplies) > construction.budget:
                    raise ValueError("Each construction package requires included supply within its budget")
        self.version = digest(self.payload)

    def project_idea(self, project_id):
        p = self.projects[project_id]
        return ProjectIdea(project_id, p["name"], p["project_type"], p["region"], p["scope"], "scenario-defined",
                           f"{p['currency']} {p['budget']}", f"{p['duration_months']} months",
                           ["DBB; scope and budget changes require macro approval"], "shared_input")

    def macro_request(self, ticks=120, seed=42):
        from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
        role_map = {"owner": "Owner", "designer": "Architect", "supervisor": "QS", "contractor": "Contractor", "supplier": "Supplier"}
        assumptions = self.payload["assumptions"]
        profiles = []
        for company in self.companies.values():
            params = assumptions["enterprise_parameters"][company.company_id]
            positive(params["total_resource_capacity"], "enterprise capacity")
            profiles.append({**params, "agent_id": company.company_id, "name": company.company_name,
                             "role": role_map[company.company_role], "enterprise_type": "scenario_entity",
                             "region": assumptions["enterprise_regions"][company.company_id],
                             "semantic_memory": {"shared_data_version": self.version, "parameter_source": "scenario_assumption"}})
        profiles.extend(deepcopy(assumptions.get("support_agents", [])))
        return SimulationCreateRequest(
            name="Shared DBB organizational procurement", agent_source="explicit", agents=profiles,
            initial_projects=[{"project_id": p["project_id"], "name": p["name"], "region": p["region"],
                               "owner_id": p["owner_id"], "project_type": p["project_type"], "initial_budget": p["budget"],
                               "performance": {"planned_duration": p["duration_months"]}}
                              for p in self.projects.values()], ticks=ticks, random_seed=seed,
            enable_project_generation=False, use_prior_network_edges=False,
            macro_environment=self.payload.get("environment", {}), policy=self.payload.get("policy", {}))
