"""Business-condition variations exercise the actual A01 runtime and Skill."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import pytest

from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.catalog import ContractCatalog
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.contractor_objects import contractor_screening_schemas
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.actions.runner import ActionRunner
from src.organization.models import Authorization, Organization
from src.organization.registry import OrganizationRegistry


FIXTURE = Path(__file__).parent / "fixtures/roles/contractor_screening.v1.json"


def facts():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def view(data, kind):
    return next(row["value"] for row in data["objects"] if row["ref"]["kind"] == kind)


def ref(kind, identity, version="1"):
    return {"kind": kind, "id": identity, "version": version}


@dataclass
class ScreeningRun:
    runner: ActionRunner
    context: ActionContext
    input: dict

    def execute(self):
        return self.runner.run_action(self.context, self.input)


def build_screening_run(data, *, catalog=None, run_id="synthetic-screening"):
    data = deepcopy(data)
    objects = data["objects"]
    clock = view(data, "CommitmentSnapshot")["as_of"]["clock_ref"]
    now = {"clock_ref": clock, "offset": 1}
    source = ref("Evidence", "synthetic-basis")
    scope = view(data, "ProcurementPackage")["scope"]
    function = ref("FunctionAssignment", "contractor-function")
    candidate_ref = ref("CandidateSet", "candidate-set")
    objects.extend([
        {"ref": source, "value": {"ref": source, "source_kind": "synthetic", "basis_kind": "assumed",
                                  "locator": str(FIXTURE), "content_hash": hashlib.sha256(
                                      json.dumps(data, sort_keys=True).encode()).hexdigest(), "effective_window": None}},
        {"ref": candidate_ref, "value": {"operation_id": "screening-1", "scope": scope, "as_of": now,
                                         "candidates": [{"ref": data["input"]["package_ref"],
                                                         "permitted_choices": ["participate", "decline", "clarify"]}],
                                         "search_profile_ref": ref("Profile", "fixture-exposure")}},
    ])
    visible = [row["ref"] for row in objects]
    context = ActionContext.model_validate({
        "run_id": run_id, "actor_id": data["actor_id"], "function_ref": function,
        "authorization_refs": [ref("Authorization", "screening-grant")], "operation_id": "screening-1",
        "contract_ref": ref("ActionContract", "CONTRACTOR-A01"), "task_ref": ref("DecisionTask", "screening-task"),
        "scope": scope, "business_time": now, "read_token": "screening-read", "visible_refs": visible,
        "candidate_set_ref": candidate_ref, "execution_mode": "offline_fixture",
    })
    organizations = OrganizationRegistry(run_id)
    organizations.register(Organization.model_validate({
        "organization_id": data["organization_id"], "actor_id": data["actor_id"],
        "source_ids": ["synthetic:contractor-screening"], "public_description": data["assumptions"],
        "public_location": {"state": "unknown", "reason_code": "fixture", "missing_refs": []},
        "members": [], "evidence_refs": [source],
        "assignments": [{"role": "Contractor", "function_ref": function,
                         "configuration_version": "1", "basis_refs": [source]}],
    }))
    organizations.authorize(Authorization.model_validate({
        "ref": context.authorization_refs[0], "organization_id": data["organization_id"], "actor_id": data["actor_id"],
        "function_ref": function, "action_ids": ["CONTRACTOR-A01"], "scopes": [scope],
        "readable_refs": visible, "tool_ids": [], "basis_refs": [source],
        "validity": {"start": {"clock_ref": clock, "offset": 0}, "end": {"clock_ref": clock, "offset": 100}, "bounds": "closed_open"},
    }))

    class FixtureProvider:
        def project(self, **request):
            return {"run_id": run_id, "macro_version": "synthetic-screening.v1", "state_version": "fixture-1",
                    "read_token": context.read_token, "business_time": now,
                    "organization_id": data["organization_id"], "objects": objects}

    host = AuthorizedMacroViewAssembler(organizations, FixtureProvider(), contractor_screening_schemas(),
                                       macro_version="synthetic-screening.v1", source_mode="fixture")
    resolver = host.build_resolver(context, "CONTRACTOR-A01", "Contractor")
    registry = register_representative_processors(ActionRegistry(catalog=catalog))
    return ScreeningRun(ActionRunner(registry, organizations=organizations, references=resolver), context, data["input"])


@pytest.fixture(scope="module")
def catalog():
    return ContractCatalog()


def test_public_package_with_applicable_facts_forms_intent_without_macro_effect(catalog):
    data = facts()
    original = deepcopy(data)
    run = build_screening_run(data, catalog=catalog)
    result = run.execute()
    assert result.kind == "completed" and result.payload.choice == "participate"
    assert result.payload.package_ref.model_dump() == data["input"]["package_ref"]
    assert result.payload.basis_refs and data == original
    assert set(result.payload.model_dump()) == {"choice", "package_ref", "basis_refs", "note"}
    assert run.runner.audit_records[-1].reference_status == "accepted"
    assert run.runner.audit_records[-1].skill_version == "3"


@pytest.mark.parametrize("mutation", ["standing", "region", "work", "expiry", "method", "capacity", "deadline", "policy"])
def test_known_business_conditions_change_participation_to_decline(catalog, mutation):
    data = facts()
    if mutation == "standing":
        view(data, "Qualification")["standing"]["value"] = False
    elif mutation == "region":
        view(data, "Qualification")["region_ids"] = ["FS"]
    elif mutation == "work":
        view(data, "ProcurementPackage")["work_types"]["value"] = ["bridge"]
    elif mutation == "expiry":
        view(data, "Qualification")["effective_window"]["end"]["offset"] = 15
    elif mutation == "method":
        view(data, "WorkMethod")["work_types"] = ["tunnel"]
    elif mutation == "capacity":
        view(data, "CommitmentSnapshot")["allocations"][0]["quantity"]["value"] = "2"
    elif mutation == "deadline":
        view(data, "ProcurementPackage")["participation_window"]["value"]["end"]["offset"] = 1
    else:
        view(data, "OpportunityScreeningProfile")["policy"] = "decline_new_work"
    result = build_screening_run(data, catalog=catalog).execute()
    assert result.kind == "completed" and result.payload.choice == "decline"


@pytest.mark.parametrize("mutation", ["qualification", "qualification_coverage", "resources", "commitment_coverage", "snapshot", "funding", "invitation"])
def test_missing_or_unknown_facts_never_become_commercial_refusal(catalog, mutation):
    data = facts()
    unknown = {"state": "unknown", "reason_code": "not_supplied", "missing_refs": []}
    if mutation == "qualification":
        view(data, "Qualification")["standing"] = unknown
    elif mutation == "qualification_coverage":
        data["input"]["qualification_refs"] = []
        view(data, "ContractorCapability")["qualification_coverage"] = "partial"
    elif mutation == "resources":
        view(data, "ContractorCapability")["resources"][0]["total"] = unknown
    elif mutation == "commitment_coverage":
        view(data, "CommitmentSnapshot")["coverage"] = "partial"
    elif mutation == "snapshot":
        view(data, "CommitmentSnapshot")["as_of"]["offset"] = 0
    elif mutation == "funding":
        view(data, "OpportunityScreeningProfile")["require_known_funding_signal"] = True
    else:
        view(data, "ProcurementPackage")["access_mode"] = "invitation_only"
    result = build_screening_run(data, catalog=catalog).execute()
    assert result.kind == "needs_information"


def test_clarification_uses_a_bounded_requirement_on_the_exact_package(catalog):
    data = facts()
    target = view(data, "Requirement")["ref"]
    view(data, "ProcurementPackage")["clarification_requirement_refs"] = [target]
    result = build_screening_run(data, catalog=catalog).execute()
    assert result.kind == "completed" and result.payload.choice == "clarify"
    assert [item.model_dump() for item in result.payload.requirement_refs] == [target]


@pytest.mark.parametrize("mutation", ["actor", "issuer", "version", "expired"])
def test_invitation_cannot_authorize_another_actor_employer_or_version(catalog, mutation):
    data = facts()
    view(data, "ProcurementPackage")["access_mode"] = "invitation_only"
    invitation = view(data, "Invitation")
    data["input"]["invitation_refs"] = [invitation["ref"]]
    if mutation == "actor":
        invitation["recipient_actor_id"] = "competitor"
    elif mutation == "issuer":
        invitation["issuer_ref"]["id"] = "other-owner"
    elif mutation == "version":
        invitation["package_ref"]["version"] = "old"
    else:
        invitation["effective_window"]["end"]["offset"] = 1
    assert build_screening_run(data, catalog=catalog).execute().kind == "needs_information"


def test_applicable_invitation_supports_invited_participation(catalog):
    data = facts()
    view(data, "ProcurementPackage")["access_mode"] = "invitation_only"
    data["input"]["invitation_refs"] = [view(data, "Invitation")["ref"]]
    assert build_screening_run(data, catalog=catalog).execute().payload.choice == "participate"


@pytest.mark.parametrize("mutation", ["unit", "bounds", "clock", "multiregion"])
def test_unsupported_comparison_domains_do_not_default_to_capacity(catalog, mutation):
    data = facts()
    demand = view(data, "ProcurementPackage")["resource_demands"]["value"][0]
    if mutation == "unit":
        demand["quantity"]["unit"] = "person"
    elif mutation == "bounds":
        demand["window"]["bounds"] = "closed_closed"
    elif mutation == "clock":
        window = view(data, "ProcurementPackage")["work_window"]["value"]
        window["start"]["clock_ref"]["id"] = window["end"]["clock_ref"]["id"] = "other-clock"
    else:
        demand["region_id"] = "FS"
    assert build_screening_run(data, catalog=catalog).execute().kind == "unsupported"


def test_resource_capacity_is_compared_exactly_beyond_default_decimal_precision(catalog):
    data = facts()
    capacity = view(data, "ContractorCapability")["resources"][0]["total"]["value"]
    demand = view(data, "ProcurementPackage")["resource_demands"]["value"][0]
    capacity["value"] = "2.0000000000000000000000000001"
    demand["quantity"]["value"] = "1.0000000000000000000000000002"
    assert build_screening_run(data, catalog=catalog).execute().payload.choice == "decline"
    demand["quantity"]["value"] = "1.0000000000000000000000000001"
    assert build_screening_run(data, catalog=catalog).execute().payload.choice == "participate"


def test_nonoverlapping_demands_do_not_sum_as_simultaneous_capacity(catalog):
    data = facts()
    demands = view(data, "ProcurementPackage")["resource_demands"]["value"]
    demands[0]["window"]["end"]["offset"] = 15
    second = deepcopy(demands[0])
    second["requirement_ref"]["id"] = "second-demand"
    second["window"]["start"]["offset"] = 15
    second["window"]["end"]["offset"] = 20
    demands.append(second)
    assert build_screening_run(data, catalog=catalog).execute().payload.choice == "participate"
    second["window"]["start"]["offset"] = 14
    assert build_screening_run(data, catalog=catalog).execute().payload.choice == "decline"


def test_resources_at_another_location_are_not_instantly_relocated(catalog):
    data = facts()
    view(data, "ContractorCapability")["resources"][0]["region_id"]["value"] = "FS"
    assert build_screening_run(data, catalog=catalog).execute().payload.choice == "decline"


def test_another_organizations_records_cannot_be_used_as_own_capacity(catalog):
    data = facts()
    for kind in ("ContractorCapability", "OpportunityScreeningProfile", "CommitmentSnapshot"):
        view(data, kind)["organization_ref"]["id"] = "competitor"
    result = build_screening_run(data, catalog=catalog).execute()
    assert result.kind == "technical_error"


@pytest.mark.parametrize("other_version", [False, True])
@pytest.mark.parametrize("kind,field,identity", [("ContractorCapability", "resources", "resource_ref"),
                                               ("CommitmentSnapshot", "allocations", "commitment_ref")])
def test_duplicate_resource_or_commitment_id_is_rejected_before_processing(catalog, kind, field, identity, other_version):
    data = facts()
    items = view(data, kind)[field]
    items.append(deepcopy(items[0]))
    if other_version:
        items[-1][identity]["version"] = "2"
    with pytest.raises(ValueError, match="twice"):
        build_screening_run(data, catalog=catalog)


@pytest.mark.parametrize("mutation", ["resource_coverage", "resource_location", "capability_expiry", "profile_expiry",
                                      "unknown_work", "unknown_demand", "unknown_method", "empty_work"])
def test_required_unknown_or_outdated_facts_remain_information_gaps(catalog, mutation):
    data = facts()
    unknown = {"state": "unknown", "reason_code": "not_supplied", "missing_refs": []}
    if mutation == "resource_coverage":
        view(data, "ContractorCapability")["resource_coverage"] = "partial"
    elif mutation == "resource_location":
        view(data, "ContractorCapability")["resources"][0]["region_id"] = unknown
    elif mutation.endswith("expiry"):
        kind = "ContractorCapability" if mutation == "capability_expiry" else "OpportunityScreeningProfile"
        view(data, kind)["effective_window"]["end"]["offset"] = 1
    else:
        field = {"unknown_work": "work_types", "unknown_demand": "resource_demands",
                 "unknown_method": "required_method_refs", "empty_work": "work_types"}[mutation]
        view(data, "ProcurementPackage")[field] = {"state": "known", "value": []} if mutation == "empty_work" else unknown
    assert build_screening_run(data, catalog=catalog).execute().kind == "needs_information"


def test_qualified_organization_with_no_work_methods_cannot_gain_support_from_title(catalog):
    data = facts()
    view(data, "ContractorCapability")["method_refs"]["value"] = []
    result = build_screening_run(data, catalog=catalog).execute()
    assert result.kind == "completed" and result.payload.choice == "decline"


def test_clarification_requirement_from_another_version_is_a_technical_error(catalog):
    data = facts()
    requirement = view(data, "Requirement")
    view(data, "ProcurementPackage")["clarification_requirement_refs"] = [requirement["ref"]]
    requirement["package_ref"]["version"] = "other-version"
    assert build_screening_run(data, catalog=catalog).execute().kind == "technical_error"


def test_declared_negative_funding_policy_changes_participation(catalog):
    data = facts()
    view(data, "ProcurementPackage")["funding_signal"] = {"state": "known", "value": False}
    view(data, "OpportunityScreeningProfile")["decline_on_negative_funding_signal"] = True
    result = build_screening_run(data, catalog=catalog).execute()
    assert result.kind == "completed" and result.payload.choice == "decline"
