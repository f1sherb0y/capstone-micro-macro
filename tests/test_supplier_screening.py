"""Synthetic Supplier-A01 business branches through authorized projections."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json

import pytest

from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.catalog import ContractCatalog
from src.actions.contracts.common import ActionContext
from src.actions.contracts.supplier_objects import SupplierCapacityView, SupplyInquiryView, supplier_screening_schemas
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.actions.runner import ActionRunner, ActionRunError
from src.organization.models import Authorization, Organization
from src.organization.registry import OrganizationRegistry


def ref(kind, identity, version="1"):
    return {"kind": kind, "id": identity, "version": version}


def known(value):
    return {"state": "known", "value": value}


def unknown():
    return {"state": "unknown", "reason_code": "synthetic_unsupplied", "missing_refs": []}


def point(offset):
    return {"clock_ref": ref("ClockProfile", "synthetic-clock"), "offset": offset}


def window(start=0, end=100):
    return {"start": point(start), "end": point(end), "bounds": "closed_open"}


def measured(value, unit="line"):
    return {"value": value, "unit": unit, "basis_ref": ref("Evidence", "synthetic-basis")}


def view(data, kind):
    return next(row["value"] for row in data["objects"] if row["ref"]["kind"] == kind)


def facts():
    basis = [ref("Evidence", "synthetic-basis")]
    scope = {"kind": "project", "ref": ref("Project", "buyer-project"),
             "coverage_refs": [ref("WorkScope", "line-1")]}
    inquiry = {"ref": ref("SupplyInquiry", "inquiry"), "scope": scope,
        "buyer_id": "synthetic-buyer", "recipient_id": "supplier-actor", "recipient_organization_id": "supplier-org",
        "received_at": point(1), "response_window": window(0, 5), "status": "active", "allow_partial_scope": True,
        "lines": [{"requirement_ref": ref("Requirement", "line-1"), "scope": deepcopy(scope),
            "product_code": known("panel"), "quantity": known(measured("10", "panel")),
            "production_region_id": known("HK"), "delivery_region_id": known("HK"),
            "work_window": known(window(10, 20)), "required_function_codes": known(["supply"]),
            "allowed_fulfillment_modes": known(["manufacture"])}],
        "clarification_requirement_refs": [], "evidence_refs": basis}
    capability = {"ref": ref("SupplierCapability", "capability"), "organization_id": "supplier-org",
        "registration_region_id": known("HK"), "operating_region_ids": known(["HK"]), "effective_window": window(),
        "product_coverage": "complete", "products": [{"product_code": "panel", "function_codes": known(["supply"]),
            "production_region_ids": known(["HK"]), "delivery_region_ids": known(["HK"]),
            "method_ref": ref("WorkMethod", "panel-method")}], "function_authority_refs": [], "evidence_refs": basis}
    capacity = {"ref": ref("SupplierCapacity", "capacity"), "organization_id": "supplier-org", "as_of": point(1),
        "resource_coverage": "complete", "commitment_coverage": "complete",
        "resources": [{"resource_ref": ref("Resource", "shared-line"), "resource_kind": "production_line",
            "region_id": known("HK"), "total": known(measured("2")), "effective_window": window()}],
        "commitments": [{"commitment_ref": ref("ResourceCommitment", "other-project"),
            "resource_ref": ref("Resource", "shared-line"), "quantity": measured("1"), "window": window(10, 20)}],
        "evidence_refs": basis}
    profile = {"ref": ref("SupplyScreeningProfile", "profile"), "organization_id": "supplier-org",
        "effective_window": window(), "policy": "evaluate", "allow_limited_scope": True,
        "inquiry_priorities": [], "evidence_refs": basis}
    method = {"ref": ref("WorkMethod", "panel-method"), "organization_id": "supplier-org", "product_code": "panel",
        "fulfillment_mode": "manufacture", "production_region_id": "HK", "delivery_region_ids": ["HK"],
        "function_codes": ["supply"], "effective_window": window(), "quantity_unit": "panel",
        "resource_kind": "production_line", "capacity_unit": "line", "units_per_capacity_tick": "1",
        "method": "constant_capacity_over_half_open_window_v1", "evidence_refs": basis}
    requirement = {"ref": ref("Requirement", "line-1"), "inquiry_ref": deepcopy(inquiry["ref"]), "scope": deepcopy(scope),
                   "description": "Synthetic requested panel supply", "evidence_refs": basis}
    market = {"ref": ref("MarketObservation", "market"), "scope": scope, "region_id": known("HK"),
        "product_codes": known(["panel"]), "forecast_quantity": unknown(), "forecast_window": unknown(),
        "observed_at": point(0), "available_at": point(1), "evidence_refs": basis}
    return deepcopy({"origin": "synthetic", "schema_version": "supplier-screening-fixture.v1",
        "assumptions": "Invented organizations, inquiry, product, method, capacity and policy; no real production or macro effect.",
        "business_time": point(1), "scope": deepcopy(scope),
        "input": {"inquiry_refs": [inquiry["ref"]], "market_refs": [], "capability_ref": capability["ref"],
                  "capacity_ref": capacity["ref"], "screening_profile_ref": profile["ref"]},
        "objects": [{"ref": item["ref"], "value": item} for item in
                    (inquiry, capability, capacity, profile, method, requirement, market)]})


@dataclass
class ScreeningRun:
    context: ActionContext
    input: dict
    objects: list
    runner: ActionRunner

    def execute(self):
        return self.runner.run_action(self.context, self.input)


def build_run(data, *, catalog=None, run_id="synthetic-supplier-screening", hidden_kinds=(), permitted_choices=None):
    data = deepcopy(data)
    now, scope, objects = data["business_time"], data["scope"], data["objects"]
    source = ref("Evidence", "synthetic-basis")
    objects.append({"ref": source, "value": {"ref": source, "source_kind": "synthetic", "basis_kind": "assumed",
        "locator": "tests/test_supplier_screening.py:facts", "content_hash": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
        "effective_window": data.get("evidence_window")}})
    objects.append({"ref": scope["ref"], "value": {"ref": scope["ref"], "evidence_refs": [source]}})
    for coverage in scope["coverage_refs"]:
        objects.append({"ref": coverage, "value": {"ref": coverage, "parent_ref": scope["ref"], "evidence_refs": [source]}})
    candidate = ref("CandidateSet", "screening-candidates")
    objects.append({"ref": candidate, "value": {"operation_id": "screening-1", "scope": scope, "as_of": now,
        "candidates": [{"ref": item, "permitted_choices": permitted_choices if permitted_choices is not None else
                       (["track_market"] if item["kind"] == "MarketObservation" else ["respond", "limited_scope", "clarify", "decline"])}
                       for item in [*data["input"]["inquiry_refs"], *data["input"]["market_refs"]]],
        "search_profile_ref": ref("Profile", "synthetic-exposure")}})
    visible = [row["ref"] for row in objects]
    function = ref("FunctionAssignment", "supplier-screening")
    context = ActionContext.model_validate({"run_id": run_id, "actor_id": "supplier-actor", "function_ref": function,
        "authorization_refs": [ref("Authorization", "supplier-grant")], "operation_id": "screening-1",
        "contract_ref": ref("ActionContract", "SUPPLIER-A01"), "task_ref": ref("DecisionTask", "screening-task"),
        "scope": scope, "business_time": now, "read_token": f"{run_id}:read", "visible_refs": visible,
        "candidate_set_ref": candidate, "execution_mode": "offline_fixture"})
    organizations = OrganizationRegistry(run_id)
    organizations.register(Organization.model_validate({"organization_id": "supplier-org", "actor_id": context.actor_id,
        "source_ids": ["synthetic:supplier-screening"], "public_description": data["assumptions"], "public_location": unknown(),
        "members": [], "evidence_refs": [source], "assignments": [{"role": "Supplier", "function_ref": function,
        "configuration_version": "1", "basis_refs": [source]}]}))
    organizations.authorize(Authorization.model_validate({"ref": context.authorization_refs[0], "organization_id": "supplier-org",
        "actor_id": context.actor_id, "function_ref": function, "action_ids": ["SUPPLIER-A01"], "scopes": [scope],
        "readable_refs": [row for row in visible if row["kind"] not in hidden_kinds], "tool_ids": [], "basis_refs": [source],
        "validity": window()}))

    class Provider:
        def project(self, **request):
            return {"run_id": run_id, "macro_version": "synthetic-supplier.v1", "state_version": "fixture-1",
                    "read_token": context.read_token, "business_time": now, "organization_id": "supplier-org", "objects": objects}

    resolver = AuthorizedMacroViewAssembler(organizations, Provider(), supplier_screening_schemas(),
        macro_version="synthetic-supplier.v1", source_mode="fixture").build_resolver(context, "SUPPLIER-A01", "Supplier")
    return ScreeningRun(context, data["input"], objects,
        ActionRunner(register_representative_processors(ActionRegistry(catalog=catalog)), organizations=organizations, references=resolver))


def add_line(data, *, product="panel", quantity="10"):
    inquiry = view(data, "SupplyInquiry")
    parent = inquiry["scope"]
    coverage = ref("WorkScope", f"line-{len(inquiry['lines']) + 1}")
    parent["coverage_refs"].append(coverage)
    data["scope"] = deepcopy(parent)
    first = inquiry["lines"][0]
    first["scope"]["coverage_refs"] = [ref("WorkScope", "line-1")]
    view(data, "Requirement")["scope"] = deepcopy(first["scope"])
    line = deepcopy(first)
    line["scope"]["coverage_refs"] = [coverage]
    line["requirement_ref"] = ref("Requirement", coverage["id"])
    line["product_code"] = known(product)
    line["quantity"] = known(measured(quantity, "panel"))
    inquiry["lines"].append(line)
    req = deepcopy(view(data, "Requirement"))
    req.update(ref=line["requirement_ref"], scope=line["scope"])
    data["objects"].append({"ref": req["ref"], "value": req})


def add_inquiry(data):
    inquiry = deepcopy(view(data, "SupplyInquiry"))
    inquiry["ref"] = ref("SupplyInquiry", "second-inquiry")
    requirement = deepcopy(view(data, "Requirement"))
    requirement["ref"] = ref("Requirement", "second-requirement")
    requirement["inquiry_ref"] = inquiry["ref"]
    inquiry["lines"][0]["requirement_ref"] = requirement["ref"]
    for item in (inquiry, requirement):
        data["objects"].append({"ref": item["ref"], "value": item})
    data["input"]["inquiry_refs"].append(inquiry["ref"])


@pytest.fixture(scope="module")
def catalog():
    return ContractCatalog()


def test_exact_response_does_not_mutate_formal_facts(catalog):
    data = facts()
    before = deepcopy(data)
    run = build_run(data, catalog=catalog)
    projections = deepcopy(run.objects)
    result = run.execute()
    assert result.kind == "completed" and result.payload.choice == "respond", result
    assert result.payload.inquiry_ref.model_dump() == data["input"]["inquiry_refs"][0]
    assert result.payload.offered_scope_refs[0].model_dump() == data["scope"]
    assert result.payload.basis_refs and run.objects == projections and data == before
    assert set(result.payload.model_dump()) == {"choice", "inquiry_ref", "offered_scope_refs", "basis_refs", "note"}
    assert run.runner.audit_records[-1].skill_version == "3"


def test_partial_scope_excludes_known_unsupported_product(catalog):
    data = facts()
    add_line(data, product="unsupported")
    result = build_run(data, catalog=catalog).execute()
    assert result.kind == "completed" and result.payload.choice == "limited_scope", result
    assert [ref.id for ref in result.payload.offered_scope_refs[0].coverage_refs] == ["line-1"]


def test_all_feasible_partial_lines_are_offered_together(catalog):
    data = facts()
    add_line(data, product="unsupported")
    add_line(data, quantity="5")
    view(data, "SupplyInquiry")["lines"][0]["quantity"] = known(measured("5", "panel"))
    result = build_run(data, catalog=catalog).execute()
    assert result.kind == "completed" and result.payload.choice == "limited_scope", result
    assert len(result.payload.offered_scope_refs) == 2


def test_competing_partial_subsets_need_explicit_selection(catalog):
    data = facts()
    add_line(data)
    assert build_run(data, catalog=catalog).execute().kind == "needs_information"


def test_only_feasible_capacity_subset_is_offered(catalog):
    data = facts()
    add_line(data, quantity="20")
    result = build_run(data, catalog=catalog).execute()
    assert result.kind == "completed" and result.payload.choice == "limited_scope", result
    assert len(result.payload.offered_scope_refs) == 1


def test_clarify_registered_requirement_and_exact_inquiry(catalog):
    data = facts()
    view(data, "SupplyInquiry")["clarification_requirement_refs"] = [view(data, "Requirement")["ref"]]
    result = build_run(data, catalog=catalog).execute()
    assert result.kind == "completed" and result.payload.choice == "clarify", result
    assert [item.model_dump() for item in result.payload.requirement_refs] == [view(data, "Requirement")["ref"]]


def test_market_tracking_requires_no_order_or_known_forecast(catalog):
    data = facts()
    data["input"]["inquiry_refs"] = []
    data["input"]["market_refs"] = [view(data, "MarketObservation")["ref"]]
    result = build_run(data, catalog=catalog).execute()
    assert result.kind == "completed" and result.payload.choice == "track_market", result
    assert not hasattr(result.payload, "inquiry_ref")


@pytest.mark.parametrize("mutation", ["product", "production", "delivery", "operating", "function", "mode", "method_region", "capacity", "partial_forbidden", "policy"])
def test_known_infeasibility_is_commercial_decline(catalog, mutation):
    data = facts()
    line = view(data, "SupplyInquiry")["lines"][0]
    if mutation == "product":
        line["product_code"] = known("unavailable")
    elif mutation in {"production", "delivery"}:
        line[f"{mutation}_region_id"] = known("GZ")
    elif mutation == "operating":
        view(data, "SupplierCapability")["operating_region_ids"] = known(["GZ"])
    elif mutation == "function":
        line["required_function_codes"] = known(["installation"])
    elif mutation == "mode":
        line["allowed_fulfillment_modes"] = known(["purchase"])
    elif mutation == "method_region":
        view(data, "WorkMethod")["production_region_id"] = "GZ"
    elif mutation == "capacity":
        view(data, "SupplierCapacity")["commitments"][0]["quantity"]["value"] = "2"
    elif mutation == "partial_forbidden":
        add_line(data, product="unsupported")
        view(data, "SupplyInquiry")["allow_partial_scope"] = False
    else:
        view(data, "SupplyScreeningProfile")["policy"] = "decline_new_work"
    result = build_run(data, catalog=catalog).execute()
    assert result.kind == "completed" and result.payload.choice == "decline", result


@pytest.mark.parametrize("mutation", ["quantity", "product", "production_region_id", "delivery_region_id", "work_window", "required_function_codes", "allowed_fulfillment_modes", "registration", "operating", "support", "product_coverage", "resource", "resources_partial", "commitments_partial", "snapshot", "future_inquiry", "expired_response", "future_response", "expired_method", "short_method", "expired_evidence", "future_evidence"])
def test_unknown_or_stale_facts_remain_waiting(catalog, mutation):
    data = facts()
    line = view(data, "SupplyInquiry")["lines"][0]
    field = {"quantity": "quantity", "product": "product_code"}.get(mutation, mutation)
    if field in line and field != "scope":
        line[field] = unknown()
    elif mutation in {"registration", "operating"}:
        key = "registration_region_id" if mutation == "registration" else "operating_region_ids"
        view(data, "SupplierCapability")[key] = unknown()
    elif mutation == "support":
        view(data, "SupplierCapability")["products"][0]["function_codes"] = unknown()
    elif mutation == "product_coverage":
        view(data, "SupplierCapability").update(products=[], product_coverage="partial")
    elif mutation == "resource":
        view(data, "SupplierCapacity")["resources"][0]["total"] = unknown()
    elif mutation in {"resources_partial", "commitments_partial"}:
        key = "resource_coverage" if mutation == "resources_partial" else "commitment_coverage"
        view(data, "SupplierCapacity")[key] = "partial"
    elif mutation == "snapshot":
        view(data, "SupplierCapacity")["as_of"] = point(0)
    elif mutation == "future_inquiry":
        view(data, "SupplyInquiry")["received_at"] = point(2)
    elif mutation == "expired_response":
        view(data, "SupplyInquiry")["response_window"] = window(0, 1)
    elif mutation == "future_response":
        view(data, "SupplyInquiry")["response_window"] = window(2, 5)
    elif mutation == "expired_method":
        view(data, "WorkMethod")["effective_window"] = window(0, 1)
    elif mutation == "short_method":
        view(data, "WorkMethod")["effective_window"] = window(0, 15)
    else:
        data["evidence_window"] = window(0, 1) if mutation == "expired_evidence" else window(2, 10)
    assert build_run(data, catalog=catalog).execute().kind == "needs_information"


@pytest.mark.parametrize("mutation", ["quantity_unit", "capacity_unit", "commitment_unit", "clock", "bounds"])
def test_unsupported_domain_stays_distinct(catalog, mutation):
    data = facts()
    line = view(data, "SupplyInquiry")["lines"][0]
    if mutation == "quantity_unit":
        line["quantity"]["value"]["unit"] = "kg"
    elif mutation == "capacity_unit":
        view(data, "SupplierCapacity")["resources"][0]["total"]["value"]["unit"] = "crew"
    elif mutation == "commitment_unit":
        view(data, "SupplierCapacity")["commitments"][0]["quantity"]["unit"] = "crew"
    elif mutation == "clock":
        for edge in ("start", "end"):
            line["work_window"]["value"][edge]["clock_ref"]["version"] = "2"
    else:
        line["work_window"]["value"]["bounds"] = "closed_closed"
    assert build_run(data, catalog=catalog).execute().kind == "unsupported"


@pytest.mark.parametrize("mutation", ["recipient", "organization", "capability", "capacity", "profile", "method", "requirement_version", "requirement_scope"])
def test_identity_mismatch_is_technical_failure(catalog, mutation):
    data = facts()
    if mutation in {"recipient", "organization"}:
        key = "recipient_id" if mutation == "recipient" else "recipient_organization_id"
        view(data, "SupplyInquiry")[key] = "other-supplier"
    elif mutation in {"capability", "capacity", "profile", "method"}:
        kind = {"capability": "SupplierCapability", "capacity": "SupplierCapacity", "profile": "SupplyScreeningProfile", "method": "WorkMethod"}[mutation]
        view(data, kind)["organization_id"] = "competitor"
    elif mutation == "requirement_version":
        view(data, "Requirement")["inquiry_ref"]["version"] = "old"
    else:
        view(data, "Requirement")["scope"]["coverage_refs"] = []
    assert build_run(data, catalog=catalog).execute().kind == "technical_error"


def test_explicit_deferral_has_resume_condition(catalog):
    data = facts()
    view(data, "SupplyScreeningProfile")["policy"] = "defer_new_work"
    result = build_run(data, catalog=catalog).execute()
    assert result.kind == "deferred" and result.resume_condition.condition_code == "supplier_policy_revision"


@pytest.mark.parametrize("policy", ["decline_new_work", "defer_new_work"])
def test_policy_cannot_bypass_recipient_validation(catalog, policy):
    data = facts()
    view(data, "SupplyInquiry")["recipient_id"] = "competitor"
    view(data, "SupplyScreeningProfile")["policy"] = policy
    assert build_run(data, catalog=catalog).execute().kind == "technical_error"


@pytest.mark.parametrize("priority", ["missing", "tied", "unknown", "unique", "old_version"])
def test_multiple_inquiries_need_exact_unique_priority(catalog, priority):
    data = facts()
    add_inquiry(data)
    if priority != "missing":
        view(data, "SupplyScreeningProfile")["inquiry_priorities"] = [
            {"inquiry_ref": deepcopy(item), "priority": unknown() if priority == "unknown" else known(index if priority == "unique" else 0)}
            for index, item in enumerate(data["input"]["inquiry_refs"])]
        if priority == "old_version":
            view(data, "SupplyScreeningProfile")["inquiry_priorities"][0]["inquiry_ref"]["version"] = "old"
    result = build_run(data, catalog=catalog).execute()
    assert result.kind == ("completed" if priority == "unique" else "needs_information"), result
    if priority == "unique":
        assert result.payload.inquiry_ref.model_dump() == data["input"]["inquiry_refs"][0]


@pytest.mark.parametrize("field", ["resources", "commitments"])
def test_same_capacity_identity_cannot_be_reused_across_versions(field):
    data = view(facts(), "SupplierCapacity")
    duplicate = deepcopy(data[field][0])
    duplicate["resource_ref" if field == "resources" else "commitment_ref"]["version"] = "2"
    data[field].append(duplicate)
    with pytest.raises(ValueError, match="identity repeated"):
        SupplierCapacityView.model_validate(data)


def test_private_projection_cannot_enter_authorized_read(catalog):
    with pytest.raises(ValueError, match="authorized"):
        build_run(facts(), catalog=catalog, hidden_kinds=("SupplierCapacity",))


def test_revoked_grant_prevents_execution(catalog):
    run = build_run(facts(), catalog=catalog)
    run.runner.organizations.revoke(run.context.authorization_refs[0])
    with pytest.raises(ActionRunError, match="no longer active"):
        run.execute()


def test_candidate_permission_is_rechecked(catalog):
    run = build_run(facts(), catalog=catalog, permitted_choices=["clarify"])
    assert run.execute().kind == "technical_error"


def test_decimal_capacity_does_not_round_into_acceptance(catalog):
    data = facts()
    view(data, "SupplyInquiry")["lines"][0]["quantity"]["value"]["value"] = "10.000000000000000000000000000000001"
    result = build_run(data, catalog=catalog).execute()
    assert result.kind == "completed" and result.payload.choice == "decline", result


def test_shared_capacity_is_checked_on_each_time_segment(catalog):
    data = facts()
    view(data, "SupplierCapacity")["commitments"][0].update(quantity=measured("2"), window=window(19, 21))
    assert build_run(data, catalog=catalog).execute().payload.choice == "decline"


def test_adjacent_commitment_does_not_overlap_half_open_window(catalog):
    data = facts()
    view(data, "SupplierCapacity")["commitments"][0].update(quantity=measured("2"), window=window(20, 30))
    assert build_run(data, catalog=catalog).execute().payload.choice == "respond"


def test_unknown_line_cannot_be_removed_to_form_partial_response(catalog):
    data = facts()
    add_line(data)
    view(data, "SupplyInquiry")["lines"][1]["quantity"] = unknown()
    assert build_run(data, catalog=catalog).execute().kind == "needs_information"


@pytest.mark.parametrize("mutation", ["overlap", "duplicate_requirement", "missing_coverage"])
def test_inquiry_line_coverage_is_closed_and_disjoint(mutation):
    data = facts()
    add_line(data)
    inquiry = view(data, "SupplyInquiry")
    if mutation == "overlap":
        inquiry["lines"][1]["scope"] = deepcopy(inquiry["lines"][0]["scope"])
    elif mutation == "duplicate_requirement":
        inquiry["lines"][1]["requirement_ref"] = deepcopy(inquiry["lines"][0]["requirement_ref"])
        inquiry["lines"][1]["requirement_ref"]["version"] = "2"
    else:
        inquiry["lines"][1]["scope"]["coverage_refs"] = []
    with pytest.raises(ValueError):
        SupplyInquiryView.model_validate(inquiry)


def add_function_authority(data):
    view(data, "SupplyInquiry")["lines"][0]["required_function_codes"] = known(["supply", "installation"])
    capability = view(data, "SupplierCapability")
    capability["products"][0]["function_codes"] = known(["supply", "installation"])
    view(data, "WorkMethod")["function_codes"] = ["supply", "installation"]
    authority = {"ref": ref("Authority", "installation"), "organization_id": "supplier-org",
        "actor_id": "supplier-actor", "scope": deepcopy(data["scope"]), "function_codes": ["installation"],
        "effective_window": window(), "evidence_refs": [ref("Evidence", "synthetic-basis")]}
    capability["function_authority_refs"] = [authority["ref"]]
    data["objects"].append({"ref": authority["ref"], "value": authority})


@pytest.mark.parametrize("mutation,kind", [("valid", "completed"), ("missing", "needs_information"),
    ("expired", "needs_information"), ("short_window", "needs_information"), ("scope", "needs_information"),
    ("actor", "technical_error"), ("organization", "technical_error")])
def test_extended_supply_function_has_bounded_authority(catalog, mutation, kind):
    data = facts()
    add_function_authority(data)
    authority = view(data, "Authority")
    if mutation == "missing":
        view(data, "SupplierCapability")["function_authority_refs"] = []
    elif mutation == "expired":
        authority["effective_window"] = window(0, 1)
    elif mutation == "short_window":
        authority["effective_window"] = window(0, 15)
    elif mutation == "scope":
        authority["scope"]["coverage_refs"] = []
    elif mutation in {"actor", "organization"}:
        authority[f"{mutation}_id"] = "competitor"
    result = build_run(data, catalog=catalog).execute()
    assert result.kind == kind, result
    if mutation == "valid":
        assert result.payload.choice == "respond"


def test_registration_does_not_substitute_for_production_or_delivery(catalog):
    data = facts()
    view(data, "SupplierCapability")["registration_region_id"] = known("GZ")
    view(data, "SupplyInquiry")["lines"][0]["delivery_region_id"] = known("MO")
    view(data, "SupplierCapability")["products"][0]["delivery_region_ids"] = known(["MO"])
    view(data, "WorkMethod")["delivery_region_ids"] = ["MO"]
    assert build_run(data, catalog=catalog).execute().payload.choice == "respond"


@pytest.mark.parametrize("field", ["observed_at", "available_at"])
def test_future_market_facts_cannot_form_current_tracking(catalog, field):
    data = facts()
    data["input"].update(inquiry_refs=[], market_refs=[view(data, "MarketObservation")["ref"]])
    view(data, "MarketObservation")[field] = point(2)
    assert build_run(data, catalog=catalog).execute().kind == "needs_information"


def test_missing_inquiry_and_market_data_never_becomes_decline(catalog):
    data = facts()
    data["input"]["inquiry_refs"] = []
    assert build_run(data, catalog=catalog).execute().kind == "needs_information"


def test_missing_commitment_resource_version_is_not_free_capacity(catalog):
    data = facts()
    view(data, "SupplierCapacity")["commitments"][0]["resource_ref"]["version"] = "old"
    assert build_run(data, catalog=catalog).execute().kind == "needs_information"


def test_full_response_checks_concurrent_inquiry_lines_together(catalog):
    data = facts()
    add_line(data, quantity="5")
    view(data, "SupplyInquiry")["lines"][0]["quantity"] = known(measured("5", "panel"))
    result = build_run(data, catalog=catalog).execute()
    assert result.kind == "completed" and result.payload.choice == "respond", result
    assert len(result.payload.offered_scope_refs) == 2


@pytest.mark.parametrize("choice", ["track_market", "decline"])
def test_output_cannot_invent_market_target_or_commercial_inquiry(catalog, choice):
    contract = catalog.get("SUPPLIER-A01")
    data = facts()
    data["input"]["inquiry_refs"] = []
    payload = {"choice": choice, "note": "Synthetic invalid output", "basis_refs": []}
    if choice == "track_market":
        payload["market_refs"] = [ref("MarketObservation", "hidden-market")]
    with pytest.raises(ValueError):
        contract.validate_decision(data["input"], payload)
