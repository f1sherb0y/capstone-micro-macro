"""Explicit, non-destructive conversion of input-only CSV and legacy scenarios."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path

from pydantic import Field, model_validator

from integration.scenario_v2 import ScenarioV2, VersionManifest, domain_leaf_paths, domain_field_values, read_input_json, parse_input_json
from src.actions.contracts.common import StrictRecord, TextId
from src.organization.models import Role


PROJECT_FIELDS = ("case_id", "project_name", "project_type", "location", "owner_name", "scale", "delivery_mode")
COMPANY_FIELDS = ("company_id", "company_name", "office_location", "business_scope", "industry")
_UNSET = object()


class IdentitySelection(StrictRecord):
    source_id: TextId
    organization_id: TextId
    actor_id: TextId
    roles: list[Role] = Field(min_length=1)
    assignment_note: TextId


class MigrationSelection(StrictRecord):
    run_id: TextId
    project_ids: list[TextId]
    identities: list[IdentitySelection] = Field(min_length=1)
    project_owner_ids: dict[TextId, TextId]
    manifest: VersionManifest

    @model_validator(mode="after")
    def unique_selection(self):
        for field in ("source_id", "organization_id", "actor_id"):
            values = [getattr(identity, field) for identity in self.identities]
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate selected {field}; assign multiple roles to one identity")
        if len(self.project_ids) != len(set(self.project_ids)):
            raise ValueError("Duplicate selected project")
        if set(self.project_owner_ids) != set(self.project_ids):
            raise ValueError("Owner mappings must cover exactly the selected projects")
        owners = {identity.organization_id for identity in self.identities if "Owner" in identity.roles}
        if not set(self.project_owner_ids.values()) <= owners:
            raise ValueError("Selected project owner must have the Owner role")
        return self


def _ref(kind, identity, version="1"):
    return {"kind": kind, "id": identity, "version": version}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _decimal_transport(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("Legacy numeric parameter requires a finite number")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite legacy parameter")
    return str(result)


def _read_csv(path: Path, fields: tuple[str, ...], *, source_bytes=None):
    raw = Path(path).read_bytes() if source_bytes is None else source_bytes
    with io.StringIO(raw.decode("utf-8-sig"), newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        if len(columns) != len(set(columns)):
            raise ValueError('Input CSV contains duplicate column names')
        missing = set(fields) - set(columns)
        if missing:
            raise ValueError(f"Input CSV lacks required columns: {sorted(missing)}")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f'Input CSV row has missing or extra cells near line {reader.line_num}')
            rows.append({field: row[field].strip() for field in fields})
    identity = fields[0]
    ids = [row[identity] for row in rows]
    if any(not key for key in ids) or len(ids) != len(set(ids)):
        raise ValueError("Missing or duplicate source identity")
    return rows, [column for column in columns if column not in fields]


class MigrationBuilder:
    def __init__(self, selection: MigrationSelection, sources: dict, *, fixture=False):
        self.selection = selection
        self.sources = sources
        self.evidence = []
        self.fields = []
        self.entries = []
        self.warnings = []
        self.fixture = fixture
        self.source_values = []

    def provenance(self, source_path, target_path, value, status="preserved", reason="Source input field", synthetic=False,
                   basis_kind=None, source_value=_UNSET):
        source_value = value if source_value is _UNSET else source_value
        identity = "evidence-" + _digest({"source": source_path, "target": target_path, "value": source_value})[:24]
        ref = _ref("Evidence", identity)
        self.evidence.append({"ref": ref, "source_kind": "synthetic" if synthetic or self.fixture else "real_user",
                              "basis_kind": basis_kind or ("assumed" if synthetic or self.fixture or status == "missing" else
                                                            "inferred" if status == "transformed" else "observed"),
                              "locator": source_path or f"migration:{target_path}",
                              "content_hash": _digest(source_value), "effective_window": None})
        self.source_values.append({"evidence_ref": ref, "value": source_value})
        transformation = {"preserved": "identity", "transformed": "explicit_mapping", "missing": "missing", "assumed": "assumption"}[status]
        self.fields.append({"field_path": target_path, "evidence_ref": ref, "transformation": transformation, "source_path": source_path})
        self.entries.append({"source_path": source_path, "target_path": target_path, "status": status, "reason": reason, "evidence_ref": ref})
        return ref

    def organization(self, selected: IdentitySelection, name: str, description: str, source_prefix: str, location="",
                     *, name_source=None, description_source=None, location_source=None):
        key = selected.organization_id
        selection_index = self.selection.identities.index(selected)
        selection_path = f"selection/identities/{selection_index}"
        name_basis = self.provenance(source_prefix, f"organizations/{key}/public_description",
                                     {"name": name, "description": description}, "transformed",
                                     "Compose public description from explicitly supplied fields")
        self.entries[-1]["source_paths"] = [name_source or f"{source_prefix}/company_name",
                                            description_source or f"{source_prefix}/business_scope"]
        role_basis = self.provenance(selection_path, f"organizations/{key}/assignments",
                                     {"roles": selected.roles, "note": selected.assignment_note}, "assumed",
                                     "Explicit scenario role assignment; no real qualification inferred", synthetic=True)
        location_basis = self.provenance(location_source, f"organizations/{key}/public_location", location,
                                         "transformed" if location else "missing", "Wrap supplied location without a default region")
        if "QS" in selected.roles:
            self.warnings.append(f"{key}: QS is an explicit scenario assignment, not proof that a supervisor has independent QS functions")
        for field, value in (("organization_id", key), ("actor_id", selected.actor_id), ("source_ids", [selected.source_id])):
            self.provenance(f"{selection_path}/{'source_id' if field == 'source_ids' else field}",
                            f"organizations/{key}/{field}", value,
                            "transformed" if field == "source_ids" else "preserved",
                            source_value=selected.source_id if field == "source_ids" else value)
        self.provenance(None, f"organizations/{key}/members", [], "assumed",
                        "No micro members attached during data import; host config supplies members", synthetic=True)
        return {"organization_id": key, "actor_id": selected.actor_id, "source_ids": [selected.source_id],
                "public_description": f"{name}: {description}",
                "public_location": {"state": "known", "value": location} if location else {"state": "unknown", "reason_code": "source_location_not_supplied", "missing_refs": []},
                "members": [], "evidence_refs": [name_basis, role_basis, location_basis],
                "assignments": [{"role": role, "function_ref": _ref("FunctionAssignment", f"{key}/{role}"),
                                 "configuration_version": "1", "basis_refs": [role_basis]} for role in selected.roles]}

    def assessment(self, project: dict, owner_id: str, prefix: str, *, source_fields=None):
        source_fields = source_fields or {"case_id": "case_id", "project_name": "project_name",
                                          "location": "location", "project_type": "project_type", "scale": "scale"}
        key = project["case_id"]
        source_ref = self.provenance(prefix, f"assessments/{key}/scope_description", project, "transformed",
                                     "Combine supplied project type and scale as assessment scope")
        self.entries[-1]["source_paths"] = [f"{prefix}/{source_fields[field]}" for field in ("project_type", "scale")]
        location = project["location"]
        location_source = source_fields.get("location")
        location_ref = self.provenance(f"{prefix}/{location_source}" if location_source else None,
                                       f"assessments/{key}/location", location,
                                       "transformed" if location else "missing", "Wrap supplied location; no default region is inferred")
        name = project["project_name"]
        self.provenance(f"{prefix}/{source_fields['case_id']}", f"assessments/{key}/case_id", key)
        self.provenance(f"{prefix}/{source_fields['project_name']}", f"assessments/{key}/name", name)
        self.provenance(f"selection/project_owner_ids/{key}", f"assessments/{key}/owner_id", owner_id, "transformed")
        self.provenance(None, f"assessments/{key}/purpose", None, "missing", "No project objective is supplied")
        return {"case_id": key, "owner_id": owner_id, "name": name,
                "purpose": {"state": "unknown", "reason_code": "objective_not_supplied", "missing_refs": []},
                "location": {"state": "known", "value": location} if location else {"state": "unknown", "reason_code": "location_not_supplied", "missing_refs": []},
                "scope_description": project["project_type"] + "; " + project["scale"], "source_refs": [source_ref, location_ref]}

    def missing_parameters(self, identities):
        parameters = []
        for organization_id in identities:
            for kind in ("initial_cash", "resource", "inventory"):
                key = f"{organization_id}/{kind}"
                basis = self.provenance(None, f"initial_parameters/{key}", None, "missing", "No observed initial value supplied")
                data = {"parameter_id": key, "owner_id": organization_id, "kind": kind, "version": "1", "evidence_ref": basis,
                        "effective_window": None, "value": {"state": "unknown", "reason_code": "initial_value_not_supplied", "missing_refs": []}}
                if kind in {"resource", "inventory"}:
                    data["resource_type_ref"] = None
                parameters.append(data)
        return parameters

    def finish(self, organizations, assessments, parameters, numeric_profile=None):
        mapping = {identity.source_id: identity.organization_id for identity in self.selection.identities}
        manifest = self.selection.manifest.model_dump(mode="json")
        if manifest["identity_mapping"] != mapping:
            raise ValueError("Manifest and migration identity mappings differ")
        if manifest["source_hashes"] != self.sources:
            raise ValueError("Manifest and source file hashes differ")
        # Record host-assigned metadata separately from the unknown/observed
        # parameter value. A whole-parameter source must not confer observed
        # provenance on its generated ID, owner, clock or resource kind.
        for parameter in parameters:
            prefix = f"initial_parameters/{parameter['parameter_id']}"
            parent = next(row for row in self.fields if row["field_path"] == prefix)
            parent["field_path"] = prefix + "/value"
            entry = next(row for row in reversed(self.entries)
                         if row["target_path"] == prefix and row["evidence_ref"] == parent["evidence_ref"])
            entry["target_path"] = parent["field_path"]
            for field in ("parameter_id", "owner_id", "kind", "version", "effective_window", "resource_type_ref"):
                if field not in parameter:
                    continue
                self.provenance(None, prefix + "/" + field, parameter[field],
                                "missing" if field in {"effective_window", "resource_type_ref"} else "assumed",
                                "Explicit migration metadata; no observed type/time/authorization inferred", synthetic=True)
        target = {"organizations": organizations, "assessments": assessments, "initial_parameters": parameters,
                  "proposals": [], "projects": [], "numeric_profile": numeric_profile or {"currencies": [], "units": []}}
        self.provenance(None, "numeric_profile", target["numeric_profile"], "assumed",
                        "Explicit supported currencies/units of the migrated scenario parameters; no conversions", synthetic=True)
        for group, items in target.items():
            if not items:
                self.provenance("selection/project_ids" if group == "assessments" else None, group, [],
                                "transformed" if group == "assessments" else "assumed",
                                "Explicitly empty selected initial collection", synthetic=group != "assessments")
        prefixes = {f"{group}/{item[id_field]}": f"{group}/{index}"
                    for group, id_field in (("organizations", "organization_id"), ("assessments", "case_id"),
                                           ("initial_parameters", "parameter_id"))
                    for index, item in enumerate(target[group])}
        rows, entries = [], []
        for row in self.fields:
            old_path = row["field_path"]
            prefix = next((prefix for prefix in sorted(prefixes, key=len, reverse=True)
                           if old_path == prefix or old_path.startswith(prefix + "/")), None)
            if prefix is None and old_path not in target:
                raise ValueError(f"Provenance target cannot resolve: {old_path}")
            path = prefixes[prefix] + old_path[len(prefix):] if prefix else old_path
            value = _lookup_path(target, path)
            source_entry = next(entry for entry in reversed(self.entries)
                                if entry["target_path"] == old_path and entry["evidence_ref"] == row["evidence_ref"])
            for leaf, leaf_value in domain_leaf_paths(value, path):
                rows.append({**row, "field_path": leaf})
                entries.append({**source_entry, "target_path": leaf, "target_value_hash": _digest(leaf_value)})
        self.fields = rows
        self.entries = [entry for entry in self.entries if entry["evidence_ref"] is None] + entries
        required = set(domain_field_values(target))
        actual = {row["field_path"] for row in self.fields}
        if required != actual or len(actual) != len(self.fields):
            raise ValueError(f"Migration field provenance is incomplete: {sorted(required - actual)}")
        snapshot = ScenarioV2.model_validate({"schema_version": "scenario.v2", "run_id": self.selection.run_id, "fixture": self.fixture,
            "manifest": manifest, "organizations": organizations, "assessments": assessments, "proposals": [], "projects": [],
            "initial_parameters": parameters, "numeric_profile": numeric_profile or {"currencies": [], "units": []},
            "evidence": self.evidence, "field_sources": self.fields, "field_source_format": "domain_leaves.v1"})
        missing_field_sources = [entry["field_path"] for entry in self.fields
                                 if entry["transformation"] == "missing"]
        report = {"schema_version": "migration-report.v2", "run_id": snapshot.run_id, "snapshot_digest": snapshot.digest,
                  "source_hashes": self.sources, "identity_mapping": mapping, "entries": self.entries, "warnings": self.warnings,
                  "source_values": self.source_values,
                  "selection": self.selection.model_dump(mode="json"),
                  "selection_hash": _digest(self.selection.model_dump(mode="json")),
                  "field_provenance": {"total": len(self.fields), "missing": len(missing_field_sources),
                                       "missing_paths": missing_field_sources, "complete": True,
                                       "paths": sorted(actual), "path_format": "zero_based_output_field_path"},
                  "unconverted_sources": [entry["source_path"] for entry in self.entries if entry["status"] == "unconverted"],
                  "formal_projects_created": 0, "assumptions": "Supplied input describes records; role assignments and legacy numeric parameters are scenario assumptions"}
        validate_migration_report(snapshot, report)
        return snapshot, report


def validate_migration_report(snapshot: ScenarioV2, report: dict) -> None:
    if (report.get("schema_version") != "migration-report.v2" or report.get("run_id") != snapshot.run_id
            or report.get("snapshot_digest") != snapshot.digest):
        raise ValueError("Migration report does not belong to this snapshot/version")
    if snapshot.field_source_format != "domain_leaves.v1":
        raise ValueError("Legacy partial provenance cannot be treated as complete migration")
    if report.get("source_hashes") != snapshot.manifest.source_hashes or report.get("identity_mapping") != snapshot.manifest.identity_mapping:
        raise ValueError("Migration report source or identity manifest differs")
    selection = MigrationSelection.model_validate(report["selection"])
    if _digest(report["selection"]) != report["selection_hash"] or selection.run_id != snapshot.run_id or selection.manifest != snapshot.manifest:
        raise ValueError("Migration selection differs from the frozen snapshot")
    entries = report.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Migration report entries are required")
    allowed_statuses = {"preserved", "transformed", "missing", "assumed", "excluded", "unconverted"}
    fingerprints = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Migration report entry must be an object")
        if entry.get("status") not in allowed_statuses:
            raise ValueError("Migration report contains an unknown entry status")
        source_path = entry.get("source_path")
        status = entry["status"]
        # A missing/assumed value may be generated without an observed source
        # locator. Excluded and unconverted records, however, must identify the
        # legacy field that was deliberately left out.
        if source_path is not None and (not isinstance(source_path, str) or not source_path.strip()):
            raise ValueError("Migration report source path is malformed")
        if source_path is None and status not in {"missing", "assumed"}:
            raise ValueError("Migration report source path is required")
        target = entry.get("target_path")
        evidence_ref = entry.get("evidence_ref")
        if status in {"excluded", "unconverted"}:
            if target is not None or evidence_ref is not None:
                raise ValueError("Excluded or unconverted source cannot have a target or evidence")
        elif evidence_ref is not None:
            if not isinstance(target, str) or not target.strip() or not isinstance(evidence_ref, dict):
                raise ValueError("Converted migration entry requires a target and evidence")
        elif target is not None and (not isinstance(target, str) or not target.strip()):
            raise ValueError("Migration report target path is malformed")
        fingerprint = _digest({key: entry.get(key) for key in ("source_path", "target_path", "status", "evidence_ref")})
        if fingerprint in fingerprints:
            raise ValueError("Duplicate migration report entry")
        fingerprints.add(fingerprint)
    unconverted = [entry["source_path"] for entry in entries if entry["status"] == "unconverted"]
    if report.get("unconverted_sources") != unconverted or len(unconverted) != len(set(unconverted)):
        raise ValueError("Migration unconverted source summary differs from entries")
    source_values = report.get("source_values")
    if not isinstance(source_values, list):
        raise ValueError("Migration source evidence values are required")
    if any(not isinstance(entry, dict) or not isinstance(entry.get("evidence_ref"), dict) for entry in source_values):
        raise ValueError("Migration source evidence reference is malformed")
    if any("value" not in entry for entry in source_values):
        raise ValueError("Migration source evidence value is missing")
    bases = {_digest(entry["evidence_ref"]): entry["value"] for entry in source_values}
    if len(bases) != len(source_values) or len(bases) != len(snapshot.evidence):
        raise ValueError("Migration source evidence values are missing or duplicate")
    for evidence in snapshot.evidence:
        key = _digest(evidence.ref.model_dump())
        if key not in bases or _digest(bases[key]) != evidence.content_hash:
            raise ValueError("Migration source evidence hash differs")
    values = domain_field_values(snapshot.model_dump(mode="json"))
    rows = [entry for entry in entries if entry["evidence_ref"] is not None]
    mapped = {entry["target_path"]: entry for entry in rows}
    if set(mapped) != set(values) or len(mapped) != len(rows):
        raise ValueError("Migration report field set is missing, duplicate or stale")
    for field in snapshot.field_sources:
        entry = mapped[field.field_path]
        if entry["evidence_ref"] != field.evidence_ref.model_dump() or entry["source_path"] != field.source_path:
            raise ValueError("Migration report provenance differs from the snapshot")
        if entry["target_value_hash"] != _digest(values[field.field_path]):
            raise ValueError("Migration report field value hash differs from the snapshot")
        transformations = {"preserved": "identity", "transformed": "explicit_mapping", "missing": "missing", "assumed": "assumption"}
        if transformations.get(entry["status"]) != field.transformation:
            raise ValueError("Migration report transformation differs from the snapshot")
    missing = [field.field_path for field in snapshot.field_sources if field.transformation == "missing"]
    summary = report["field_provenance"]
    if (summary["total"] != len(values) or summary["missing"] != len(missing) or summary["missing_paths"] != missing
            or summary["paths"] != sorted(values) or summary["complete"] is not True):
        raise ValueError("Migration report provenance totals differ")


def _lookup_path(target, path):
    value = target
    for segment in path.split("/"):
        value = value[int(segment)] if isinstance(value, list) else value[segment]
    return value


def migrate_csv(source_directory: Path, selection: MigrationSelection):
    source_directory = Path(source_directory)
    paths = [source_directory / "simulation_input_projects.csv", source_directory / "simulation_input_enterprises.csv"]
    captured = {path.name: path.read_bytes() for path in paths}
    sources = {name: hashlib.sha256(raw).hexdigest() for name, raw in captured.items()}
    projects, project_excluded = _read_csv(paths[0], PROJECT_FIELDS, source_bytes=captured[paths[0].name])
    companies, company_excluded = _read_csv(paths[1], COMPANY_FIELDS, source_bytes=captured[paths[1].name])
    by_project = {project["case_id"]: project for project in projects}
    by_company = {company["company_id"]: company for company in companies}
    builder = MigrationBuilder(selection, sources)
    for path, columns in zip(paths, (project_excluded, company_excluded)):
        builder.entries.extend({"source_path": f"{path.name}/{column}", "target_path": None, "status": "excluded",
                                "reason": "Not in the input-only field allowlist", "evidence_ref": None} for column in columns)
    # These fields are part of the accepted CSV shape, but no registered v2
    # assessment/organization field currently carries their semantics. Keep
    # them visible as explicit conversion gaps instead of silently discarding
    # them or mislabelling them as excluded input.
    builder.entries.extend(
        {"source_path": f"{paths[0].name}/{project['case_id']}/delivery_mode", "target_path": None,
         "status": "unconverted", "reason": "No registered v2 assessment delivery-mode schema",
         "evidence_ref": None}
        for project in projects
    )
    builder.entries.extend(
        {"source_path": f"{paths[1].name}/{company['company_id']}/industry", "target_path": None,
         "status": "unconverted", "reason": "No registered v2 organization industry schema",
         "evidence_ref": None}
        for company in companies
    )
    organizations = []
    for identity in selection.identities:
        if identity.source_id.startswith("owner:"):
            case_id = identity.source_id.split(":", 1)[1]
            if case_id not in by_project or not by_project[case_id]["owner_name"] or identity.roles != ["Owner"]:
                raise ValueError("Project-owner source requires a supplied owner name and the explicit Owner role")
            organizations.append(builder.organization(identity, by_project[case_id]["owner_name"], "Owner named by the supplied project record",
                                                      f"{paths[0].name}/{case_id}",
                                                      name_source=f"{paths[0].name}/{case_id}/owner_name",
                                                      description_source="migration_rule:project_owner_description"))
            continue
        if identity.source_id not in by_company:
            raise ValueError(f"Unknown enterprise source identity: {identity.source_id}")
        company = by_company[identity.source_id]
        organizations.append(builder.organization(identity, company["company_name"], company["business_scope"],
                                                  f"{paths[1].name}/{identity.source_id}", company["office_location"],
                                                  location_source=f"{paths[1].name}/{identity.source_id}/office_location"))
    assessments = []
    for key in selection.project_ids:
        if key not in by_project or key not in selection.project_owner_ids:
            raise ValueError(f"Missing selected project or explicit owner mapping: {key}")
        assessments.append(builder.assessment(by_project[key], selection.project_owner_ids[key], f"{paths[0].name}/{key}"))
    parameters = builder.missing_parameters([organization["organization_id"] for organization in organizations])
    return builder.finish(organizations, assessments, parameters)


def migrate_legacy(path: Path, selection: MigrationSelection):
    path = Path(path)
    source_bytes = path.read_bytes()
    _, payload = parse_input_json(source_bytes)
    # Preserve numeric tokens for decimal transport. Other provenance/report
    # data retains its existing JSON shape; both parses use the captured bytes
    # and the same strict duplicate/non-finite/overflow rejection boundary.
    _, exact_payload = parse_input_json(source_bytes, exact_decimal_numbers=True)
    if payload.get("schema_version") != "1.0":
        raise ValueError("Only explicit legacy shared-input v1 is accepted")
    companies = {company["company_id"]: company for company in payload["companies"]}
    if len(companies) != len(payload["companies"]):
        raise ValueError("Duplicate legacy enterprise identity")
    selected_ids = [identity.source_id for identity in selection.identities]
    if len(selected_ids) != len(set(selected_ids)) or set(selected_ids) != set(companies):
        raise ValueError("Legacy conversion requires an explicit one-to-one source identity selection")
    mapping = {identity.source_id: identity.organization_id for identity in selection.identities}
    builder = MigrationBuilder(selection, {path.name: hashlib.sha256(source_bytes).hexdigest()})
    organizations = [builder.organization(identity, companies[identity.source_id]["company_name"],
                                         companies[identity.source_id]["profile"], f"{path.name}/companies/{identity.source_id}",
                                         description_source=f"{path.name}/companies/{identity.source_id}/profile")
                     for identity in selection.identities]
    for identity in selection.identities:
        old_role = companies[identity.source_id]["company_role"]
        builder.entries.append({"source_path": f"companies/{identity.source_id}/company_role", "target_path": f"organizations/{identity.organization_id}/assignments",
                                "status": "transformed", "reason": f"Explicit compatibility mapping {old_role} -> {','.join(identity.roles)}; not evidence of real qualification", "evidence_ref": None})
        for field in ("past_project_experience", "qualifications", "weaknesses", "risk_signals"):
            builder.entries.append({"source_path": f"companies/{identity.source_id}/{field}", "target_path": None, "status": "excluded",
                                    "reason": "Historical/private or unverified role metadata is not decision input", "evidence_ref": None})
    parameters = builder.missing_parameters(mapping.values())
    by_parameter = {parameter["parameter_id"]: parameter for parameter in parameters}
    units, currencies = set(), set()
    assumptions = payload.get("assumptions", {})
    for source_id, values in assumptions.get("enterprise_parameters", {}).items():
        if source_id not in mapping:
            raise ValueError("Legacy parameter belongs to an unmapped identity")
        builder.entries.extend({"source_path": f"{path.name}/assumptions/enterprise_parameters/{source_id}/{field}",
                                "target_path": None, "status": "unconverted", "evidence_ref": None,
                                "reason": "Legacy scalar profile has no registered v2 professional parameter schema"}
                               for field in values if field != "total_resource_capacity")
        scalar = values.get("total_resource_capacity")
        if scalar is not None:
            exact_scalar = exact_payload['assumptions']['enterprise_parameters'][source_id]['total_resource_capacity']
            quantity = _decimal_transport(exact_scalar)
            if Decimal(quantity) < 0:
                raise ValueError("Legacy capacity is negative")
            parameter = by_parameter[f"{mapping[source_id]}/resource"]
            # Replace the missing-field provenance entry for this one supplied value.
            target_path = f"initial_parameters/{parameter['parameter_id']}"
            builder.fields = [field for field in builder.fields if field["field_path"] != target_path]
            basis = builder.provenance(f"{path.name}/assumptions/enterprise_parameters/{source_id}/total_resource_capacity", target_path,
                                       {"value": quantity, "unit": "normalized_enterprise_capacity"}, "assumed",
                                       "Legacy scalar is retained as a synthetic parameter; no typed resource equivalence claimed", synthetic=True)
            parameter.update(evidence_ref=basis, value={"state": "known", "value": {"value": quantity, "unit": "normalized_enterprise_capacity", "basis_ref": basis}})
            units.add("normalized_enterprise_capacity")
            builder.warnings.append(f"{source_id}: legacy scalar capacity is not decomposed into professional resources")
    assessments = []
    projects = {project["project_id"]: project for project in payload["projects"]}
    exact_projects = {project['project_id']: project for project in exact_payload['projects']}
    if len(projects) != len(payload["projects"]):
        raise ValueError("Duplicate legacy project identity")
    for project_id in selection.project_ids:
        if project_id not in projects:
            raise ValueError("Unknown selected legacy project")
        project = projects[project_id]
        owner_id = mapping.get(project["owner_id"])
        if owner_id is None or selection.project_owner_ids.get(project_id) != owner_id:
            raise ValueError("Legacy owner and explicit project owner mapping differ")
        converted = {"case_id": project_id, "project_name": project["name"], "project_type": project["project_type"],
                     "location": "", "scale": project["scope"]}
        assessment = builder.assessment(converted, owner_id, f"{path.name}/projects/{project_id}",
                                        source_fields={"case_id": "project_id", "project_name": "name", "location": None,
                                                       "project_type": "project_type", "scale": "scope"})
        assessments.append(assessment)
        builder.warnings.append(f"{project_id}: legacy region {project['region']} may be a default/assumption; real location remains unknown without source evidence")
        builder.entries.append({"source_path": f"projects/{project_id}", "target_path": f"assessments/{project_id}", "status": "transformed",
                                "reason": "Legacy initial project has no verified formal registration receipt; converted to assessment data", "evidence_ref": None})
        for kind, field, label in (("budget", "budget", "currency"), ("duration", "duration_months", "unit")):
            quantity = _decimal_transport(exact_projects[project_id][field])
            parameter_id = f"{project_id}/{kind}"
            unit = project["currency"] if kind == "budget" else "month"
            basis = builder.provenance(f"{path.name}/projects/{project_id}/{field}", f"initial_parameters/{parameter_id}",
                                       {"value": quantity, label: unit}, "assumed", "Explicit legacy scenario assumption; not observed project cost or actual duration", synthetic=True)
            parameter = {"parameter_id": parameter_id, "owner_id": owner_id, "version": "1", "evidence_ref": basis,
                         "effective_window": None, "kind": kind, "value": {"state": "known", "value": {"value": quantity, label: unit, "basis_ref": basis}}}
            if kind == "duration":
                parameter["resource_type_ref"] = None
                units.add(unit)
            else:
                currencies.add(unit)
            parameters.append(parameter)
    for field in ("packages", "support_agents", "environment", "policy"):
        if field not in payload:
            continue
        builder.entries.append({"source_path": field, "target_path": None, "status": "excluded",
                                "reason": "Requires explicit v2 object/profile conversion; no silent compatibility cast", "evidence_ref": None})
        builder.entries[-1]["status"] = "unconverted"
    for field in assumptions:
        if field != "enterprise_parameters":
            builder.entries.append({"source_path": f"{path.name}/assumptions/{field}", "target_path": None,
                                    "status": "unconverted", "evidence_ref": None,
                                    "reason": "No v2 mapping for this legacy assumption section"})
    return builder.finish(organizations, assessments, parameters, {"currencies": sorted(currencies), "units": sorted(units)})


def write_migration(snapshot: ScenarioV2, report: dict, directory: Path):
    validate_migration_report(snapshot, report)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    snapshot.save_new(directory / "scenario.v2.json")
    with (directory / "migration_report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-kind", choices=["csv", "legacy"], default="csv")
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    selection_text, _ = read_input_json(args.selection)
    selection = MigrationSelection.model_validate_json(selection_text)
    snapshot, report = (migrate_csv if args.source_kind == "csv" else migrate_legacy)(args.source, selection)
    write_migration(snapshot, report, args.output)
    print(json.dumps({"output": str(args.output), "snapshot_digest": snapshot.digest}))


if __name__ == "__main__":
    main()
