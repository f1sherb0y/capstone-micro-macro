from copy import deepcopy

import pytest
from pydantic import ValidationError

from src.actions.contracts.common import ActionContext, Reference, StrictRecord, ref_type
from src.actions.contracts.references import ReferenceSchemaRegistry
from src.actions.contracts.domain import CandidateSet, common_projection_schemas


def ref(kind, identity="object-1"):
    return {"kind": kind, "id": identity, "version": "1"}


def fixture():
    scope = {"kind": "organization", "ref": ref("Organization"), "coverage_refs": []}
    time = {"clock_ref": ref("ClockProfile"), "offset": 1}
    package = ref("ProcurementPackage")
    context = ActionContext.model_validate({
        "run_id": "fixture-run", "actor_id": "fixture-actor", "function_ref": ref("FunctionAssignment"),
        "authorization_refs": [ref("Authorization")], "operation_id": "fixture-operation",
        "contract_ref": ref("ActionContract"), "task_ref": ref("DecisionTask"), "scope": scope,
        "business_time": time, "read_token": "fixture-read", "visible_refs": [package],
        "candidate_set_ref": ref("CandidateSet"), "execution_mode": "offline_fixture",
    })
    candidates = {"operation_id": context.operation_id, "scope": scope, "as_of": time,
                  "candidates": [{"ref": package, "permitted_choices": ["participate", "decline"]}],
                  "search_profile_ref": ref("Profile")}
    return context, candidates


def test_candidate_exposure_preserves_task_scope_time_and_legal_choices():
    context, candidates = fixture()
    registry = common_projection_schemas()
    projected = registry.validate_projection(context.candidate_set_ref, candidates)
    assert isinstance(projected, CandidateSet)
    projected.check_context(context, ("participate", "clarify", "decline"))
    CandidateSet.model_validate({**candidates, "candidates": []}).check_context(context, ("decline",))


@pytest.mark.parametrize("mutation", ["operation", "scope", "time", "hidden", "choice", "duplicate"])
def test_candidate_exposure_cannot_invent_visibility_or_action_permission(mutation):
    context, candidates = fixture()
    bad = deepcopy(candidates)
    if mutation == "operation":
        bad["operation_id"] = "other-operation"
    elif mutation == "scope":
        bad["scope"]["ref"]["id"] = "other-organization"
    elif mutation == "time":
        bad["as_of"]["offset"] = 2
    elif mutation == "hidden":
        bad["candidates"][0]["ref"]["id"] = "unexposed-package"
    elif mutation == "choice":
        bad["candidates"][0]["permitted_choices"] = ["approve_payment"]
    else:
        bad["candidates"].append(deepcopy(bad["candidates"][0]))
    with pytest.raises(ValueError):
        CandidateSet.model_validate(bad).check_context(context, ("participate", "clarify", "decline"))


def test_common_schema_registry_does_not_claim_unimplemented_professional_objects():
    registry = common_projection_schemas()
    with pytest.raises(ValueError, match="Unregistered"):
        registry.schema_for("EngineerAnalysis")
    context, candidates = fixture()
    with pytest.raises(ValidationError):
        registry.validate_projection(context.candidate_set_ref, {**candidates, "private_truth": True})


def test_projection_identity_uses_the_canonical_ref_not_its_python_subclass():
    class IdentityView(StrictRecord):
        ref: Reference
        description: str

    registry = ReferenceSchemaRegistry()
    registry.register_kind("Evidence", IdentityView, str)
    typed = ref_type("Evidence").model_validate(ref("Evidence"))
    view = registry.validate_projection(typed, {"ref": typed, "description": "Synthetic identity test"})
    assert view.ref.key() == typed.key()
    with pytest.raises(ValueError, match="identity"):
        registry.validate_projection(typed, {"ref": ref("Evidence", "foreign"), "description": "Different ID"})


def test_empty_or_open_object_schemas_cannot_enter_the_reading_registry():
    class Empty(StrictRecord):
        pass

    class Open(StrictRecord):
        model_config = {"extra": "allow"}
        description: str

    registry = ReferenceSchemaRegistry()
    for schema in (Empty, Open):
        with pytest.raises(ValueError, match="strict schema"):
            registry.register_kind("Evidence", schema, str)
