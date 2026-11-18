"""Explicit frozen initial data. Formal dynamic state belongs to the macro engine."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, PrivateAttr, model_validator

from src.actions.contracts.common import (
    StrictRecord, TextId, ScopeRef, Money, Measured, DecimalString, ValueState,
    TimeWindow, EvidenceRecord, NumericProfile, ref_type, walk_references,
)
from src.organization.models import Organization


def parse_input_json(source_bytes: bytes, *, exact_decimal_numbers: bool = False) -> tuple[str, dict]:
    """Parse one captured byte sequence without normalizing its source text.

    Migration can hash these same bytes. Model loaders retain JSON-mode
    validation and the existing ambiguous/non-finite input rejection rules.
    Legacy numeric conversion can separately retain exact decimal tokens from
    these same bytes without rounding amounts through binary floating point.
    """
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate input JSON field: {key}')
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError('Non-finite input JSON number')

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Input JSON number exceeds finite numeric transport')
        return Decimal(value) if exact_decimal_numbers else number

    text = source_bytes.decode('utf-8-sig')
    data = json.loads(text, object_pairs_hook=unique_object,
        parse_constant=reject_constant, parse_float=finite_float)
    if not isinstance(data, dict):
        raise ValueError('Scenario and migration input must be a JSON object')
    return text, data


def read_input_json(path: Path) -> tuple[str, dict]:
    """Read one source snapshot while preserving its exact UTF-8 text."""
    return parse_input_json(Path(path).read_bytes())


class VersionManifest(StrictRecord):
    data_version: TextId
    schema_version: Literal["scenario.v2"]
    macro_version: TextId
    method_versions: dict[TextId, TextId]
    skill_versions: dict[TextId, TextId]
    prompt_versions: dict[TextId, TextId]
    model_provider: TextId
    model_name: TextId
    model_configuration_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    seed: int
    mode: Literal["legacy_procurement", "role_contract", "gba_v1_module"]
    identity_mapping: dict[TextId, TextId]
    source_hashes: dict[TextId, Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]]


class FieldSource(StrictRecord):
    field_path: TextId
    evidence_ref: ref_type("Evidence")
    transformation: Literal["identity", "explicit_mapping", "assumption", "missing"]
    source_path: TextId | None


class AssessmentSeed(StrictRecord):
    case_id: TextId
    owner_id: TextId
    name: str
    purpose: ValueState[str]
    location: ValueState[str]
    scope_description: str
    source_refs: list[ref_type("Evidence")] = Field(min_length=1)


class ProposalSeed(StrictRecord):
    proposal_id: TextId
    case_id: TextId
    brief_ref: ref_type("OwnerBrief")
    evidence_refs: list[ref_type("Evidence")] = Field(min_length=1)


class ProjectSeed(StrictRecord):
    project_id: TextId
    owner_id: TextId
    name: str
    scope_description: str
    registration_basis_ref: ref_type("RegistrationEvidence")
    evidence_refs: list[ref_type("Evidence")] = Field(min_length=1)


class ParameterBase(StrictRecord):
    parameter_id: TextId
    owner_id: TextId | None
    version: TextId
    evidence_ref: ref_type("Evidence")
    effective_window: TimeWindow | None


class MoneyParameter(ParameterBase):
    kind: Literal["initial_cash", "budget", "price"]
    value: ValueState[Money]


class QuantityParameter(ParameterBase):
    kind: Literal["resource", "inventory", "duration"]
    resource_type_ref: ref_type("ResourceType") | None
    value: ValueState[Measured]


class PolicyParameter(ParameterBase):
    kind: Literal["policy", "environment"]
    profile_ref: ref_type("Profile")
    value: ValueState[DecimalString]


InitialParameter = Annotated[MoneyParameter | QuantityParameter | PolicyParameter, Field(discriminator="kind")]


class ScenarioV2(StrictRecord):
    _sealed_digest: str = PrivateAttr()
    schema_version: Literal["scenario.v2"]
    run_id: TextId
    fixture: bool
    manifest: VersionManifest
    organizations: list[Organization] = Field(min_length=1)
    assessments: list[AssessmentSeed]
    proposals: list[ProposalSeed]
    projects: list[ProjectSeed]
    initial_parameters: list[InitialParameter]
    numeric_profile: NumericProfile
    evidence: list[EvidenceRecord] = Field(min_length=1)
    field_sources: list[FieldSource]
    field_source_format: Literal["legacy_partial", "domain_leaves.v1"] = "legacy_partial"

    @model_validator(mode="after")
    def consistent_snapshot(self):
        if self.manifest.schema_version != self.schema_version:
            raise ValueError("Manifest schema mismatch")
        orgs = {org.organization_id: org for org in self.organizations}
        if len(orgs) != len(self.organizations) or len({org.actor_id for org in self.organizations}) != len(orgs):
            raise ValueError("Duplicate organization or actor identity")
        source_ids = [source for org in self.organizations for source in org.source_ids]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Source identity duplicated; multi-role organizations must be shared")
        expected_mapping = {source: org.organization_id for org in self.organizations for source in org.source_ids}
        if self.manifest.identity_mapping != expected_mapping:
            raise ValueError("Identity mapping must exactly match the selected organization sources")
        for group, field in ((self.assessments, "case_id"), (self.proposals, "proposal_id"),
                             (self.projects, "project_id"), (self.initial_parameters, "parameter_id")):
            ids = [getattr(item, field) for item in group]
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate {field}")
        for item in self.assessments + self.projects:
            if item.owner_id not in orgs or not any(a.role == "Owner" for a in orgs[item.owner_id].assignments):
                raise ValueError("Assessment/project requires a registered Owner")
        case_ids = {case.case_id for case in self.assessments}
        if any(proposal.case_id not in case_ids for proposal in self.proposals):
            raise ValueError("Proposal has no assessment case")
        for parameter in self.initial_parameters:
            if parameter.owner_id is not None and parameter.owner_id not in orgs:
                raise ValueError("Initial parameter owner is unknown")
            self.numeric_profile.check(parameter)
        evidence_keys = {record.ref.key() for record in self.evidence}
        if len(evidence_keys) != len(self.evidence):
            raise ValueError("Duplicate evidence identity")
        for ref in walk_references(self):
            if ref.kind == "Evidence" and ref.key() not in evidence_keys:
                raise ValueError("Field provenance references missing evidence")
        paths = [field.field_path for field in self.field_sources]
        if len(paths) != len(set(paths)):
            raise ValueError("Field provenance path repeated")
        if self.field_source_format == "domain_leaves.v1":
            expected = set(domain_field_values(self.model_dump(mode="json")))
            if set(paths) != expected:
                raise ValueError("Field provenance does not cover the complete domain leaf set")
        return self

    def model_post_init(self, context):
        self._sealed_digest = self._content_digest()

    @classmethod
    def load(cls, path: Path) -> ScenarioV2:
        text, _ = read_input_json(path)
        return cls.model_validate_json(text)

    @property
    def digest(self) -> str:
        digest = self._content_digest()
        if digest != self._sealed_digest:
            raise ValueError("Frozen initial snapshot was mutated; create an explicit new version")
        return digest

    def _content_digest(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), ensure_ascii=False,
                                         sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def bootstrap_input(self) -> dict:
        """Frozen seeds for an explicit macro binding, not a submitted state ledger."""
        return {"run_id": self.run_id, "snapshot_digest": self.digest,
                "organizations": [org.model_dump(mode="json") for org in self.organizations],
                "assessments": [item.model_dump(mode="json") for item in self.assessments],
                "proposals": [item.model_dump(mode="json") for item in self.proposals],
                "projects": [item.model_dump(mode="json") for item in self.projects],
                "initial_parameters": [item.model_dump(mode="json") for item in self.initial_parameters],
                "evidence": [record.model_dump(mode="json") for record in self.evidence]}

    def initial_inputs(self, organization_ids) -> dict:
        """Freeze one explicit snapshot for macro seeds and selected own views.

        This prepares input only. Actual bindings must validate the manifest
        and accept supported seeds; it creates no registries, formal ledgers,
        grants, model clients or runtime business state.
        """
        if (not isinstance(organization_ids, (list, tuple)) or not organization_ids
                or any(not isinstance(identity, str) or not identity.strip() for identity in organization_ids)
                or len(set(organization_ids)) != len(organization_ids)):
            raise ValueError("Initial inputs require distinct explicitly selected organizations")
        selected = tuple(organization_ids)
        snapshot_digest = self.digest
        # Isolate mutable nested models/lists before deriving either side.
        frozen = self.model_copy(deep=True)
        if frozen.digest != snapshot_digest:
            raise ValueError("Initial snapshot changed while freezing macro and micro inputs")
        known = {organization.organization_id for organization in frozen.organizations}
        if not set(selected) <= known:
            raise ValueError("Initial inputs select an organization outside the original snapshot")
        macro = frozen.bootstrap_input()
        micro = {identity: frozen.authorized_initial_view(identity) for identity in selected}
        if (self.digest != snapshot_digest or frozen.digest != snapshot_digest
                or any(view['run_id'] != frozen.run_id or view['snapshot_digest'] != snapshot_digest
                    for view in [macro, *micro.values()])):
            raise ValueError("Macro and micro initial inputs must retain the same frozen run and snapshot")
        return {"schema_version": "scenario-v2-initial-inputs.v1", "run_id": frozen.run_id,
                "snapshot_digest": snapshot_digest, "fixture": frozen.fixture,
                "manifest": frozen.manifest.model_dump(mode="json"),
                "numeric_profile": frozen.numeric_profile.model_dump(mode="json"),
                "macro_input": macro, "organization_inputs": micro}

    def authorized_initial_view(self, organization_id: str) -> dict:
        """Return own frozen seeds and public organizations; dynamic sharing requires host grants."""
        organization = next((org for org in self.organizations if org.organization_id == organization_id), None)
        if organization is None:
            raise ValueError("Unknown organization")
        own_cases = [case for case in self.assessments if case.owner_id == organization_id]
        own_case_ids = {case.case_id for case in own_cases}
        own_proposals = [proposal for proposal in self.proposals if proposal.case_id in own_case_ids]
        own_projects = [project for project in self.projects if project.owner_id == organization_id]
        parameters = [parameter for parameter in self.initial_parameters if parameter.owner_id in (None, organization_id)]
        # Walk original typed records: serialized reference dictionaries do not
        # carry type identity. Only sources linked from visible facts are shared.
        visible_facts = [organization, *own_cases, *own_proposals, *own_projects, *parameters,
                         *(org.public_location for org in self.organizations)]
        evidence_keys = {ref.key() for ref in walk_references(visible_facts) if ref.kind == 'Evidence'}
        return {"run_id": self.run_id, "snapshot_digest": self.digest,
                "source": "frozen_initial_input", "organization": organization.model_dump(mode="json"),
                "public_organizations": [{"organization_id": org.organization_id, "public_description": org.public_description,
                                          "public_location": org.public_location.model_dump(mode="json"),
                                          "roles": [assignment.role for assignment in org.assignments]} for org in self.organizations],
                "assessments": [case.model_dump(mode="json") for case in own_cases],
                "proposals": [proposal.model_dump(mode="json") for proposal in own_proposals],
                "projects": [project.model_dump(mode="json") for project in own_projects],
                "initial_parameters": [parameter.model_dump(mode="json") for parameter in parameters],
                "evidence": [record.model_dump(mode="json") for record in self.evidence
                             if record.ref.key() in evidence_keys]}

    def save_new(self, path: Path) -> None:
        self.digest
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(self.model_dump_json(indent=2) + "\n")


PROVENANCE_LINKS = {"evidence_ref", "evidence_refs", "basis_ref", "basis_refs", "source_refs"}
DOMAIN_COLLECTIONS = ("organizations", "assessments", "proposals", "projects", "initial_parameters", "numeric_profile")


def domain_leaf_paths(value, prefix=""):
    """Field paths address actual output indices; proof links use reference closure."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in PROVENANCE_LINKS:
                yield from domain_leaf_paths(item, f"{prefix}/{key}" if prefix else key)
    elif isinstance(value, list):
        if not value:
            yield prefix, value
        for index, item in enumerate(value):
            yield from domain_leaf_paths(item, f"{prefix}/{index}")
    else:
        yield prefix, value


def domain_field_values(data: dict) -> dict:
    return dict(domain_leaf_paths({name: data[name] for name in DOMAIN_COLLECTIONS}))
