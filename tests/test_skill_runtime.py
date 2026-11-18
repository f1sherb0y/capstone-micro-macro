import hashlib
import json
from pathlib import Path

import pytest

from src.skills.loader import SkillLoadError, SkillLoader


def _bundle(root: Path, *, action_id="OWN-A01", processor_id="owner.test.v1", shared_ref="skills/shared/shared.md"):
    source = root / "spec.md"
    skill = root / "skills/actions/owner/OWN-A01/SKILL.md"
    shared = root / "skills/shared/shared.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    shared.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("source", encoding="utf-8")
    skill.write_text("skill", encoding="utf-8")
    shared.write_text("shared", encoding="utf-8")
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    manifest = {
        "skill_id": "OWN-A01.test", "skill_version": "1", "action_id": action_id,
        "role": "Owner", "status": "implemented", "spec_source": "spec.md",
        "spec_source_sha256": digest(source), "skill_path": "skills/actions/owner/OWN-A01/SKILL.md",
        "skill_sha256": digest(skill), "input_schema_id": "input", "output_schema_id": "output",
        "processor_id": processor_id, "tool_ids": [], "shared_refs": [shared_ref],
        "shared_sha256s": {shared_ref: digest(shared)},
        "prompt_sha256": digest(skill),
    }
    path = skill.parent / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest, source, skill


def test_loader_accepts_valid_bundle_and_rejects_stale_source(tmp_path):
    path, manifest, source, _ = _bundle(tmp_path)
    bundle = SkillLoader(tmp_path, processor_ids={"owner.test.v1"}).load_manifest(path)
    assert bundle.manifest.action_id == "OWN-A01"
    source.write_text("changed", encoding="utf-8")
    with pytest.raises(SkillLoadError, match="digest"):
        SkillLoader(tmp_path).load_manifest(path)


def test_loader_rejects_skill_and_shared_path_escape(tmp_path):
    path, manifest, _, skill = _bundle(tmp_path)
    manifest["skill_path"] = "skills/../spec.md"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SkillLoadError, match="beside its manifest"):
        SkillLoader(tmp_path).load_manifest(path)
    path, manifest, _, _ = _bundle(tmp_path)
    manifest["shared_refs"] = ["spec.md"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SkillLoadError, match="existing repository file"):
        SkillLoader(tmp_path).load_manifest(path)


def test_loader_rejects_unregistered_processor_and_duplicate_action(tmp_path):
    path, manifest, _, _ = _bundle(tmp_path)
    with pytest.raises(SkillLoadError, match="Unregistered"):
        SkillLoader(tmp_path, processor_ids={"different.v1"}).load_manifest(path)
    duplicate = tmp_path / "skills/actions/owner/duplicate"
    duplicate.mkdir(parents=True)
    duplicate_manifest = json.loads(path.read_text(encoding="utf-8"))
    duplicate_manifest["skill_path"] = "skills/actions/owner/duplicate/SKILL.md"
    duplicate_manifest["skill_sha256"] = duplicate_manifest["prompt_sha256"] = hashlib.sha256(b"skill").hexdigest()
    (duplicate / "SKILL.md").write_text("skill", encoding="utf-8")
    (duplicate / "manifest.json").write_text(json.dumps(duplicate_manifest), encoding="utf-8")
    with pytest.raises(SkillLoadError, match="Multiple Skill manifests"):
        SkillLoader(tmp_path).discover()
