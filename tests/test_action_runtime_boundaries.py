import json
import pytest

from src.actions.registry import ActionRegistry
from src.actions.processors import register_representative_processors
from src.actions.runner import ActionRunError, ActionRunner, JsonlActionAuditSink
from src.skills.loader import SkillLoadError, SkillLoader
from tests.test_action_contracts import input_example
from tests.test_action_runner import _context


def test_registry_rejects_manifest_schema_role_and_source_mismatch(tmp_path):
    # The production registry already validates these fields against its
    # source catalog.  Exercise each failure through a small manifest bundle
    # so the loader's host binding remains independently testable.
    from tests.test_skill_runtime import _bundle

    path, manifest, _, _ = _bundle(tmp_path)
    manifest["input_schema_id"] = "wrong"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loader = SkillLoader(tmp_path, contract_metadata={
        "OWN-A01": ("Owner", "spec.md", "role-contract.v1:OWN-A01:input",
                     "role-contract.v1:OWN-A01:payload")
    })
    with pytest.raises(SkillLoadError, match="schema identifiers"):
        loader.load_manifest(path)

    path, manifest, _, _ = _bundle(tmp_path)
    manifest["role"] = "Bank"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SkillLoadError, match="Invalid Skill manifest"):
        SkillLoader(tmp_path, contract_metadata={
            "OWN-A01": ("Owner", "spec.md", "role-contract.v1:OWN-A01:input",
                         "role-contract.v1:OWN-A01:payload")
        }).load_manifest(path)

    path, manifest, _, _ = _bundle(tmp_path)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SkillLoadError, match="specification"):
        SkillLoader(tmp_path, contract_metadata={
            "OWN-A01": ("Owner", "other.md", "role-contract.v1:OWN-A01:input",
                         "role-contract.v1:OWN-A01:payload")
        }).load_manifest(path)


def test_registry_skill_audit_separates_skill_and_processor_evidence():
    registry = register_representative_processors(ActionRegistry())
    audit = registry.skill_audit()
    assert audit["schema_version"] == "action-skill-audit.v1"
    assert audit["counts"]["registered"] == 106
    assert audit["counts"]["with_skill"] == 106
    assert audit["counts"]["processor_bound"] == 106
    assert audit["counts"]["method_verified"] == 0
    assert audit["dimensions"]["processor"] == {"bound": 106, "unbound": 0}


def test_action_runner_writes_structured_audit_and_exposes_execution_paths(tmp_path):
    registry = register_representative_processors(ActionRegistry())
    runner = ActionRunner(registry, method_version="methods.v1", policy_version="policy.v1",
                          model_version="offline.deterministic.v1")
    contract = registry.get("CONTRACTOR-A01").contract
    data = input_example(contract.input_model.model_json_schema())
    result = runner.run_deterministic(_context(contract), data)
    assert result.kind == "needs_information"
    record = runner.audit_records[-1]
    assert record.run_id == "run-1"
    assert record.action_id == "CONTRACTOR-A01"
    assert record.input_sha256 and record.input_schema_id.endswith(":input")
    assert record.skill_id == "CONTRACTOR-A01.participation"
    assert record.skill_version == "3"
    assert record.processor_id == "contractor.participation.v2"
    assert record.result_kind == "needs_information"
    assert record.method_version == "methods.v1"
    assert record.as_dict()["stages"] == {
        "input_validation": "accepted", "authorization": "accepted", "processor": "bound"
    }

    sink = JsonlActionAuditSink(tmp_path / "run-1" / "action_audit.jsonl", run_id="run-1")
    sink(record)
    assert sink.read(run_id="run-1")[0]["run_id"] == "run-1"

    other = record.__class__(**{**record.__dict__, "run_id": "run-2"})
    with pytest.raises(ActionRunError, match="another run"):
        sink(other)
    with pytest.raises(ActionRunError, match="another run"):
        JsonlActionAuditSink(tmp_path / "run-1" / "action_audit.jsonl", run_id="run-2")

    with pytest.raises(ActionRunError, match="not configured"):
        runner.run_single_agent(_context(contract), data)


def test_action_runner_audit_records_input_rejection():
    registry = register_representative_processors(ActionRegistry())
    runner = ActionRunner(registry)
    contract = registry.get("CONTRACTOR-A01").contract
    with pytest.raises(Exception):
        runner.run_action(_context(contract), {"unexpected": True})
    assert runner.audit_records[-1].input_validation == "rejected"
    assert runner.audit_records[-1].processor_status == "not_run"


def test_processor_type_error_is_not_retried_or_reinterpreted_as_signature_failure():
    registry = ActionRegistry(load_skills=False)
    calls = []

    def processor(context, action_input):
        calls.append(1)
        raise TypeError("processor body failure")

    registry.register_processor("CONTRACTOR-A01", "test.processor.v1", processor)
    contract = registry.get("CONTRACTOR-A01").contract
    result = ActionRunner(registry).run_action(_context(contract), input_example(contract.input_model.model_json_schema()))
    assert result.kind == "technical_error"
    assert result.error.code == "processor_exception"
    assert calls == [1]


def test_action_runner_is_bound_to_one_run_identity():
    registry = register_representative_processors(ActionRegistry())
    runner = ActionRunner(registry)
    contract = registry.get("CONTRACTOR-A01").contract
    data = input_example(contract.input_model.model_json_schema())
    runner.run_deterministic(_context(contract), data)
    other = _context(contract).model_copy(update={"run_id": "run-2"})
    with pytest.raises(ActionRunError, match="another run"):
        runner.run_deterministic(other, data)
