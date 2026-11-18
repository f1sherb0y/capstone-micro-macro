"""Load repository-owned Skill bundles without dynamic code execution."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Mapping

from src.skills.models import LoadedSkill, SkillManifest
from src.json_input import read_json_object


class SkillLoadError(ValueError):
    """Raised when a Skill declaration is missing, stale, or escapes its root."""


class SkillBundle:
    def __init__(self, loaded: LoadedSkill):
        self.manifest = loaded.manifest
        self.content = loaded.content
        self.shared_content = loaded.shared_content


class SkillLoader:
    """Resolve only paths declared under the repository's ``skills`` root.

    The loader intentionally returns text and metadata.  ``processor_id`` is
    later matched against a host supplied registry; it is never imported from
    manifest data.
    """

    def __init__(self, root: Path, *, processor_ids: set[str] | frozenset[str] = frozenset(),
                 contract_metadata: Mapping[str, tuple[str, str, str, str]] | None = None):
        self.root = Path(root).resolve()
        self.skills_root = (self.root / "skills").resolve()
        self.processor_ids = frozenset(processor_ids)
        # ``(role, source_path, input_schema_id, output_schema_id)`` is an
        # optional host-supplied view of the action contract.  Keeping this
        # dependency injectable lets the loader remain usable for isolated
        # Skill bundle tests while allowing the runtime registry to enforce
        # the real catalog binding.
        self.contract_metadata = dict(contract_metadata or {})
        if not self.skills_root.is_relative_to(self.root) or not self.skills_root.exists():
            raise SkillLoadError("Skill root does not exist inside repository")

    def _path(self, relative: str, *, shared: bool = False) -> Path:
        path = (self.root / relative).resolve()
        allowed = (self.skills_root / "shared").resolve() if shared else self.skills_root
        if not allowed.is_relative_to(self.skills_root) or not path.is_relative_to(allowed) or not path.is_file():
            raise SkillLoadError(f"Skill path is not an existing repository file: {relative}")
        return path

    def _spec_path(self, relative: str) -> Path:
        """Resolve a declared repository specification without allowing escape."""
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise SkillLoadError(f"Skill specification is not a repository file: {relative}")
        return path

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _validate_manifest_path(self, manifest_path: Path) -> LoadedSkill:
        try:
            _, data = read_json_object(manifest_path)
            manifest = SkillManifest.model_validate(data)
        except (OSError, ValueError) as exc:
            raise SkillLoadError(f"Invalid Skill manifest: {manifest_path}") from exc
        if manifest_path.parent.resolve() != (self.root / manifest.skill_path).resolve().parent:
            raise SkillLoadError("Manifest skill path must be beside its manifest")
        expected = self.contract_metadata.get(manifest.action_id)
        if expected is not None:
            expected_role, expected_source, expected_input, expected_output = expected
            if manifest.role != expected_role:
                raise SkillLoadError(f"Skill role differs from the registered contract for {manifest.action_id}")
            if manifest.spec_source != expected_source:
                raise SkillLoadError(f"Skill specification differs from the registered contract for {manifest.action_id}")
            if manifest.input_schema_id != expected_input or manifest.output_schema_id != expected_output:
                raise SkillLoadError(f"Skill schema identifiers differ from the registered contract for {manifest.action_id}")
        spec = self._spec_path(manifest.spec_source)
        skill = self._path(manifest.skill_path)
        if self._sha(spec) != manifest.spec_source_sha256:
            raise SkillLoadError(f"Stale specification digest for {manifest.action_id}")
        skill_bytes = skill.read_bytes()
        skill_sha256 = hashlib.sha256(skill_bytes).hexdigest()
        if skill_sha256 != manifest.skill_sha256 or skill_sha256 != manifest.prompt_sha256:
            raise SkillLoadError(f"Stale Skill content digest for {manifest.action_id}")
        if self.processor_ids and manifest.processor_id not in self.processor_ids:
            raise SkillLoadError(f"Unregistered Skill processor: {manifest.processor_id}")
        shared_bytes = {reference: self._path(reference, shared=True).read_bytes()
                        for reference in manifest.shared_refs}
        if (len(shared_bytes) != len(manifest.shared_refs)
                or set(manifest.shared_sha256s) != set(shared_bytes)):
            raise SkillLoadError('Shared fragment digests must exactly cover the declared references')
        for reference, raw in shared_bytes.items():
            if hashlib.sha256(raw).hexdigest() != manifest.shared_sha256s[reference]:
                raise SkillLoadError(f'Stale shared fragment digest for {manifest.action_id}: {reference}')
        return LoadedSkill(manifest=manifest, content=skill_bytes.decode('utf-8'),
            shared_content={reference: raw.decode('utf-8') for reference, raw in shared_bytes.items()})

    def load_manifest(self, path: Path) -> SkillBundle:
        path = Path(path)
        if path.is_absolute():
            path = path.resolve()
        else:
            path = (self.root / path).resolve()
        if not path.is_relative_to(self.skills_root) or path.name != "manifest.json":
            raise SkillLoadError("Manifest must be under the repository Skill root")
        try:
            return SkillBundle(self._validate_manifest_path(path))
        except (OSError, UnicodeError) as exc:
            raise SkillLoadError(f'Cannot read Skill bundle: {path}') from exc

    def discover(self) -> list[SkillBundle]:
        bundles = [self.load_manifest(path) for path in sorted(self.skills_root.glob("actions/*/*/manifest.json"))]
        ids = [bundle.manifest.action_id for bundle in bundles]
        if len(ids) != len(set(ids)):
            raise SkillLoadError("Multiple Skill manifests claim one action")
        return bundles

    def load_action(self, action_id: str) -> SkillBundle:
        if not re.fullmatch(r"(?:OWN|BANK|ARCHITECT|ENGINEER|QS|GOV|CONTRACTOR|SUPPLIER)-A\d{2}", action_id):
            raise SkillLoadError("Invalid action identifier")
        matches = [path for path in self.skills_root.glob(f"actions/*/{action_id}/manifest.json")]
        if len(matches) != 1:
            raise SkillLoadError(f"Expected exactly one Skill for {action_id}")
        return self.load_manifest(matches[0])
