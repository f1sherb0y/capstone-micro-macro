"""Closed metadata models for project action Skills.

Skill files are instructions and references, not executable code.  The loader
checks every path and digest before returning a bundle to an action runner.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import MethodRef, StrictRecord, TextId
from src.organization.models import Role


_ID = r"[A-Za-z][A-Za-z0-9_.:/-]*"
Digest = Field(pattern=r"^[0-9a-f]{64}$")


class SkillManifest(StrictRecord):
    skill_id: TextId
    skill_version: TextId
    action_id: Annotated[str, Field(pattern=r"^(OWN|BANK|ARCHITECT|ENGINEER|QS|GOV|CONTRACTOR|SUPPLIER)-A\d{2}$")]
    role: Role
    status: Literal["declared", "implemented"] = "declared"
    spec_source: TextId
    spec_source_sha256: Annotated[str, Digest]
    skill_path: TextId
    skill_sha256: Annotated[str, Digest]
    input_schema_id: TextId
    output_schema_id: TextId
    processor_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.:-]*$")]
    tool_ids: list[TextId]
    shared_refs: list[TextId]
    shared_sha256s: dict[TextId, Annotated[str, Digest]] = Field(default_factory=dict)
    prompt_sha256: Annotated[str, Digest]
    method_refs: list[MethodRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def identity_matches_action(self):
        action_role = self.action_id.split("-", 1)[0]
        expected = {"OWN": "Owner", "BANK": "Bank", "ARCHITECT": "Architect", "ENGINEER": "Engineer",
                    "QS": "QS", "GOV": "Government", "CONTRACTOR": "Contractor", "SUPPLIER": "Supplier"}[action_role]
        if self.role != expected:
            raise ValueError("Skill role does not match action identifier")
        if not self.skill_id.startswith(self.action_id + "."):
            raise ValueError("Skill identity must be namespaced by action")
        if any(path.startswith("/") for path in [self.skill_path, self.spec_source, *self.shared_refs]):
            raise ValueError("Skill paths must be repository-relative")
        if len({ref.key() for ref in self.method_refs}) != len(self.method_refs):
            raise ValueError("Skill method reference repeated")
        return self


class SkillReference(StrictRecord):
    ref_id: TextId
    path: TextId
    sha256: Annotated[str, Digest]


class LoadedSkill(StrictRecord):
    manifest: SkillManifest
    content: str
    shared_content: dict[str, str]
