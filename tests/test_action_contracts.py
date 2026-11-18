"""Contract examples are synthetic transport inputs, not execution evidence."""
from copy import deepcopy
import json

import pytest
from pydantic import TypeAdapter, ValidationError

from src.actions.contracts.catalog import ContractCatalog, ROOT
from src.actions.contracts.common import Reference


@pytest.fixture(scope="module")
def catalog():
    return ContractCatalog()


def ref(kind, identity="fixture-1", version="1"):
    return {"kind": kind, "id": identity, "version": version}


def scope():
    return {"kind": "organization", "ref": ref("Organization"), "coverage_refs": []}


def input_example(schema, definitions=None):
    """Build only transport data. Business scenarios use independent fixed facts."""
    definitions = definitions or schema.get("$defs", {})
    if "$ref" in schema:
        return input_example(definitions[schema["$ref"].rsplit("/", 1)[1]], definitions)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "oneOf" in schema:
        discriminator = schema.get("discriminator", {})
        mapping = discriminator.get("mapping", {})
        choice = "organization" if "organization" in mapping else "unknown" if "unknown" in mapping else next(iter(mapping), None)
        return input_example({"$ref": mapping[choice]} if choice else schema["oneOf"][0], definitions)
    if "anyOf" in schema:
        if any(branch.get("type") == "null" for branch in schema["anyOf"]):
            return None
        return input_example(schema["anyOf"][0], definitions)
    if schema.get("type") == "object":
        return {field: input_example(schema["properties"][field], definitions) for field in schema["required"]}
    if schema.get("type") == "array":
        return []
    if schema.get("type") == "boolean":
        return False
    if schema.get("type") == "integer":
        return 1
    return "1"


def test_all_106_inputs_are_closed_required_and_reference_typed(catalog):
    inventory = json.loads((ROOT / "config/action_registry.json").read_text(encoding="utf-8"))
    assert {action["action_id"] for action in inventory["actions"]} == set(catalog.contracts)
    for action in inventory["actions"]:
        contract = catalog.get(action["action_id"])
        schema = contract.input_model.model_json_schema()
        data = input_example(schema)
        assert contract.validate_input(data).model_dump() == data
        with pytest.raises(ValidationError):
            contract.validate_input({**data, "formal_balance": "100000"})
        for field in schema["required"]:
            incomplete = deepcopy(data)
            del incomplete[field]
            with pytest.raises(ValidationError):
                contract.validate_input(incomplete)
        assert set(contract.choices) == set(action["choices"])
        payload = contract.payload_adapter.json_schema()
        for schema_ref in payload["discriminator"]["mapping"].values():
            branch = payload["$defs"][schema_ref.rsplit("/", 1)[1]]
            assert branch["additionalProperties"] is False
            assert set(branch["required"]) == set(branch["properties"])


def test_assembler_references_keep_identity_and_concrete_input_validation(catalog):
    contract = catalog.get('SUPPLIER-A05')
    case = json.loads((ROOT / 'tests/fixtures/roles/lifecycle_v4_supplier_purchase_planning.v1.json').read_text())
    original = case['steps'][0]['request']['action_input']
    supplied = deepcopy(original)
    reference = Reference.model_validate(supplied['work_authority_ref'])
    supplied['work_authority_ref'] = reference
    supplied['requirement_refs'] = [Reference.model_validate(value) for value in supplied['requirement_refs']]
    supplied['scope_ref']['ref'] = Reference.model_validate(supplied['scope_ref']['ref'])
    validated = contract.validate_input(supplied)
    assert validated.model_dump(mode='json') == original
    assert type(validated.work_authority_ref) is not Reference
    assert supplied['work_authority_ref'] is reference
    for invalid in (reference.model_copy(update={'kind': 'InventoryView'}),
            reference.model_copy(update={'version': True}),
            reference.model_copy(update={'undeclared_field': 'must not disappear'})):
        with pytest.raises(ValidationError):
            contract.validate_input({**supplied, 'work_authority_ref': invalid})


def test_contractor_first_public_invitation_is_optional_but_package_version_is_bound(catalog):
    contract = catalog.get("CONTRACTOR-A01")
    data = input_example(contract.input_model.model_json_schema())
    payload = {"choice": "participate", "package_ref": data["package_ref"], "basis_refs": [], "note": "Synthetic intent"}
    assert contract.validate_decision(data, payload).choice == "participate"
    payload = deepcopy(payload)
    payload["package_ref"]["version"] = "2"
    with pytest.raises(ValueError, match="package version"):
        contract.validate_decision(data, payload)


@pytest.mark.parametrize("action_id,terms_field", [("ARCHITECT-A02", "accepted_terms_ref"), ("ENGINEER-A02", "terms_ref"), ("QS-A02", "terms_ref")])
def test_service_acceptance_cannot_switch_terms_or_represent_client(catalog, action_id, terms_field):
    contract = catalog.get(action_id)
    data = input_example(contract.input_model.model_json_schema())
    payload = {"choice": "accept", "scope": data["scope"], "note": None, terms_field: data["terms_ref"]}
    assert contract.validate_decision(data, payload).choice == "accept"
    changed = deepcopy(payload)
    changed[terms_field]["version"] = "2"
    with pytest.raises(ValueError, match="terms version"):
        contract.validate_decision(data, changed)
    with pytest.raises(ValidationError):
        contract.validate_payload({**payload, "client_accepted": True})
    decline = {"choice": "decline", "scope": data["scope"], "note": None, "reason": "Commercial refusal"}
    assert contract.validate_decision(data, decline).choice == "decline"
    with pytest.raises(ValidationError):
        contract.validate_payload({**decline, terms_field: data["terms_ref"]})


def test_bank_intake_uses_application_and_product_candidates_without_generating_loan(catalog):
    contract = catalog.get("BANK-A02")
    data = input_example(contract.input_model.model_json_schema())
    data["product_candidates"] = [ref("FinanceProductProfile")]
    payload = {"choice": "accept_for_review", "application_ref": data["application_ref"], "finding_refs": [],
               "note": "Synthetic intake", "product_ref": data["product_candidates"][0], "required_condition_refs": []}
    assert contract.validate_decision(data, payload).choice == "accept_for_review"
    with pytest.raises(ValidationError):
        contract.validate_payload({**payload, "loan_created": True})
    payload["product_ref"] = ref("FinanceProductProfile", "other")
    with pytest.raises(ValueError, match="candidates"):
        contract.validate_decision(data, payload)


def test_owner_proposal_needs_sources_but_does_not_need_a_project(catalog):
    contract = catalog.get("OWN-A01")
    data = input_example(contract.input_model.model_json_schema())
    payload = {"choice": "propose", "basis_refs": [], "note": "Synthetic proposal", "source_refs": [ref("Observation")]}
    assert contract.validate_decision(data, payload).choice == "propose"
    with pytest.raises(ValueError, match="source_refs"):
        contract.validate_decision(data, {**payload, "source_refs": []})
    with pytest.raises(ValidationError):
        contract.validate_payload({**payload, "project_id": "invented"})


def test_supplier_market_tracking_without_inquiry_and_response_with_bound_inquiry(catalog):
    contract = catalog.get("SUPPLIER-A01")
    data = input_example(contract.input_model.model_json_schema())
    payload = {"choice": "track_market", "basis_refs": [], "note": "Synthetic watch", "market_refs": []}
    assert contract.validate_decision(data, payload).choice == "track_market"
    data["inquiry_refs"] = [ref("SupplyInquiry")]
    response = {"choice": "respond", "basis_refs": [], "note": "Synthetic response", "inquiry_ref": data["inquiry_refs"][0], "offered_scope_refs": [scope()]}
    assert contract.validate_decision(data, response).choice == "respond"
    response["inquiry_ref"] = ref("SupplyInquiry", "unreceived")
    with pytest.raises(ValueError, match="received inquiry"):
        contract.validate_decision(data, response)


def test_government_receipt_is_not_substantive_approval(catalog):
    contract = catalog.get("GOV-A02")
    data = input_example(contract.input_model.model_json_schema())
    check = {"submission_ref": data["submission_ref"], "procedure_ref": data["procedure_ref"],
             "checked_requirement_refs": [ref("InformationRequirement")], "missing_requirement_refs": [],
             "unresolved_questions": [], "scope": data["scope"]}
    payload = {"choice": "accept_for_processing", "scope": data["scope"], "note": None, "check": check}
    assert contract.validate_decision(data, payload).choice == "accept_for_processing"
    check["missing_requirement_refs"] = [ref("InformationRequirement")]
    with pytest.raises(ValueError, match="Incomplete submission"):
        contract.validate_decision(data, payload)
    with pytest.raises(ValidationError):
        contract.validate_payload({"choice": "approve", "scope": data["scope"], "note": None, "permit_ref": ref("Permit")})


def test_known_range_currency_order_and_missing_result_rules(catalog):
    compiler = catalog.compilers["Bank"]
    model = compiler.named("BankIndicativeRange")
    data = {"lower": {"state": "known", "value": {"value": "10", "currency": "HKD", "basis_ref": ref("Evidence")}},
            "upper": {"state": "known", "value": {"value": "20", "currency": "HKD", "basis_ref": ref("Evidence")}},
            "method_ref": ref("FinanceFeasibilityMethod"), "assumptions": []}
    assert model.model_validate(data).lower.value.value == "10"
    for lower, currency in [("21", "HKD"), ("10", "CNY")]:
        changed = deepcopy(data)
        changed["lower"]["value"].update(value=lower, currency=currency)
        with pytest.raises(ValidationError):
            model.model_validate(changed)
    check_model = catalog.compilers["Engineer"].named("EngineerCheckItem")
    check = {"check_spec_ref": ref("CheckSpec"), "evidence_refs": [], "evidence_status": "missing",
             "method_result_ref": None, "result": None, "missing_field_paths": ["loads"], "issue_refs": []}
    assert check_model.model_validate(check).result is None
    with pytest.raises(ValidationError):
        check_model.model_validate({**check, "result": "satisfied"})


def test_unknown_type_and_code_injection_are_rejected():
    from src.actions.contracts.type_language import TypeCompiler
    compiler = TypeCompiler({})
    with pytest.raises(ValueError, match="Unregistered"):
        compiler.record("Bad", "{field:UndefinedDomainType}")
    with pytest.raises(Exception):
        compiler.record("Bad", "{field:__import__('os')}")
    with pytest.raises(ValueError, match="Unregistered reference kind"):
        compiler.record("BadRef", "{field:Ref<InventedBusinessObject>}")


def test_decision_validation_rejects_an_input_model_from_another_action(catalog):
    other = catalog.get("BANK-A02")
    data = other.validate_input(input_example(other.input_model.model_json_schema()))
    with pytest.raises(ValidationError):
        catalog.get("CONTRACTOR-A01").validate_decision(data, {
            "choice": "participate", "package_ref": ref("ProcurementPackage"), "basis_refs": [], "note": "Fixture",
        })
