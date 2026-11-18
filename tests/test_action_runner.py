from copy import deepcopy

import pytest

from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.actions.runner import ActionRunError, ActionRunner
from src.actions.contracts.common import ActionContext
from src.actions.contracts.common import walk_references
from tests.test_action_contracts import input_example
from tests.test_organization import host


def _ref(kind, identity="fixture", version="1"):
    return {"kind": kind, "id": identity, "version": version}


def _context(contract, *, visible_refs=None, execution_mode="offline_fixture"):
    data = {
        "run_id": "run-1", "actor_id": "actor-1", "function_ref": _ref("FunctionAssignment"),
        "authorization_refs": [], "operation_id": "operation-1",
        "contract_ref": _ref("ActionContract", contract.action_id), "task_ref": _ref("DecisionTask"),
        "scope": {"kind": "organization", "ref": _ref("Organization"), "coverage_refs": []},
        "business_time": {"clock_ref": _ref("ClockProfile"), "offset": 1}, "read_token": "read-1",
        "visible_refs": visible_refs or [], "candidate_set_ref": _ref("CandidateSet"),
        "execution_mode": execution_mode,
    }
    return ActionContext.model_validate(data)


def test_runner_binds_representatives_and_keeps_unimplemented_unsupported():
    registry = register_representative_processors(ActionRegistry())
    runner = ActionRunner(registry)
    contractor = registry.get("CONTRACTOR-A01").contract
    data = input_example(contractor.input_model.model_json_schema())
    result = runner.run_action(_context(contractor), data)
    assert result.kind == "needs_information"
    unsupported = registry.get("CONTRACTOR-A02").contract
    # The representative registry now binds A02 too; exercise an actually
    # unbound registration to retain the unsupported-processor boundary.
    unbound_runner = ActionRunner(ActionRegistry())
    assert unbound_runner.run_action(_context(unsupported), input_example(unsupported.input_model.model_json_schema())).kind == "unsupported"


def test_runner_requires_authorization_outside_fixture_and_rechecks_revocation(host):
    organizations, _, grant, base_context = host
    registry = register_representative_processors(ActionRegistry())
    contract = registry.get("CONTRACTOR-A01").contract
    data = input_example(contract.input_model.model_json_schema())
    data["qualification_refs"] = [_ref("Qualification")]
    context_data = base_context.model_dump()
    context_data["contract_ref"] = _ref("ActionContract", contract.action_id)
    context_data["authorization_refs"] = []
    context_data["visible_refs"] = [
        data["package_ref"], data["capability_ref"], data["commitments_ref"], data["screening_profile_ref"],
        *data["qualification_refs"],
    ]
    context = ActionContext.model_validate(context_data)
    runner = ActionRunner(registry, organizations=organizations)
    with pytest.raises(ActionRunError, match="authorization"):
        runner.run_action(context, data)
    context_data["authorization_refs"] = [grant.ref.model_dump()]
    context = ActionContext.model_validate(context_data)
    result = runner.run_action(context, data)
    assert result.kind == "needs_information"
    assert "business_projections" in result.missing_fields
    organizations.revoke(grant.ref)
    with pytest.raises(ActionRunError, match="no longer active"):
        runner.run_action(context, data)


def _all_refs(value):
    return list(walk_references(value))


def _key(reference):
    return reference.kind, reference.id, reference.version


@pytest.mark.parametrize(
    "action_id,setup,forbidden",
    [
        (
            "OWN-A01",
            lambda data: data.update({"opportunity_refs": [_ref("Opportunity")]}),
            "opportunity_refs",
        ),
        (
            "BANK-A02",
            lambda data: data.update({
                "product_candidates": [_ref("FinanceProductProfile")],
                "disclosure_refs": [_ref("Evidence", "disclosure")],
            }),
            "product_candidates",
        ),
        (
            "CONTRACTOR-A01",
            lambda data: data.update({"qualification_refs": [_ref("Qualification")]}),
            "screening_profile_ref",
        ),
        ("ARCHITECT-A02", lambda data: None, "price_basis_ref"),
        ("ENGINEER-A02", lambda data: None, "capacity_ref"),
        ("QS-A02", lambda data: None, "capacity_ref"),
        ("GOV-A02", lambda data: None, "procedure_ref"),
        (
            "SUPPLIER-A01",
            lambda data: data.update({"inquiry_refs": [_ref("SupplyInquiry")]}),
            "inquiry_refs",
        ),
    ],
)
def test_representative_processors_require_visible_business_facts(action_id, setup, forbidden):
    registry = register_representative_processors(ActionRegistry())
    contract = registry.get(action_id).contract
    data = input_example(contract.input_model.model_json_schema())
    setup(data)
    validated = contract.validate_input(data)
    all_visible = _all_refs(validated)
    context = _context(contract, visible_refs=all_visible)
    result = ActionRunner(registry).run_action(context, data)
    assert result.kind == "needs_information"
    assert "business_projections" in result.missing_fields

    value = getattr(validated, forbidden)
    hidden = [reference for reference in all_visible if reference in _all_refs(value)]
    if not hidden:
        # For list fields, hide the first member; for scalar references, hide
        # the exact reference while retaining unrelated visible facts.
        target = value[0] if isinstance(value, list) and value else value
        hidden = [target]
    visible_without = [reference for reference in all_visible if _key(reference) != _key(hidden[0])]
    missing = ActionRunner(registry).run_action(_context(contract, visible_refs=visible_without), data)
    assert missing.kind == "needs_information"
    assert forbidden in missing.missing_fields
    assert any(_key(reference) == _key(hidden[0]) for reference in missing.requested_refs)
