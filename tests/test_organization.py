from copy import deepcopy
from pathlib import Path

import pytest

from src.actions.contracts.common import ActionContext, Reference, StrictRecord, ref_type
from src.actions.contracts.references import ReferenceResolver
from src.organization.models import Authorization, Organization
from src.organization.registry import AccessDenied, OrganizationRegistry, load_role_configurations


def ref(kind, identity="object-1", version="1"):
    return {"kind": kind, "id": identity, "version": version}


def scope():
    return {"kind": "organization", "ref": ref("Organization", "org-1"), "coverage_refs": []}


@pytest.fixture
def host():
    function = ref("FunctionAssignment", "contractor-function")
    evidence = ref("Evidence", "source")
    organization = Organization.model_validate({
        "organization_id": "org-1", "actor_id": "actor-1", "source_ids": ["synthetic:org-1"],
        "public_description": "Synthetic dual-role fixture", "public_location": {"state": "unknown", "reason_code": "not_supplied", "missing_refs": []},
        "members": [], "evidence_refs": [evidence],
        "assignments": [
            {"role": "Contractor", "function_ref": function, "configuration_version": "1", "basis_refs": [evidence]},
            {"role": "Supplier", "function_ref": ref("FunctionAssignment", "supplier-function"), "configuration_version": "1", "basis_refs": [evidence]},
        ],
    })
    registry = OrganizationRegistry("run-1")
    registry.register(organization)
    grant = Authorization.model_validate({
        "ref": ref("Authorization", "grant-1"), "organization_id": "org-1", "actor_id": "actor-1",
        "function_ref": function, "action_ids": ["CONTRACTOR-A01"], "scopes": [scope()],
        "readable_refs": [evidence], "tool_ids": ["screen", "write"], "basis_refs": [evidence],
        "validity": {"start": {"clock_ref": ref("ClockProfile"), "offset": 0},
                     "end": {"clock_ref": ref("ClockProfile"), "offset": 10}, "bounds": "closed_open"},
    })
    registry.authorize(grant)
    context = ActionContext.model_validate({
        "run_id": "run-1", "actor_id": "actor-1", "function_ref": function, "authorization_refs": [grant.ref.model_dump()],
        "operation_id": "operation-1", "contract_ref": ref("ActionContract"), "task_ref": ref("DecisionTask"),
        "scope": scope(), "business_time": {"clock_ref": ref("ClockProfile"), "offset": 1}, "read_token": "read-1",
        "visible_refs": [evidence], "candidate_set_ref": ref("CandidateSet"), "execution_mode": "offline_fixture",
    })
    return registry, organization, grant, context


def test_eight_role_configurations_are_domain_specific_and_do_not_grant_tools():
    configurations = load_role_configurations(Path("config/roles"))
    assert len(configurations) == 8
    assert len({tuple(m.member_id for m in c.members) for c in configurations.values()}) > 1
    assert all(not c.tool_ids for c in configurations.values())


def test_multi_role_identity_is_reused_and_does_not_clone_resources(host, tmp_path):
    registry, organization, _, _ = host
    assert registry.register(organization) == organization
    assert len(registry.get("org-1").assignments) == 2
    path = tmp_path / "organizations.json"
    registry.save(path)
    restored = OrganizationRegistry.load(path, "run-1")
    assert restored.get("org-1") == organization
    with pytest.raises(ValueError, match="run mismatch"):
        OrganizationRegistry.load(path, "run-2")
    changed = organization.model_dump()
    changed["organization_id"] = "org-2"
    with pytest.raises(ValueError, match="Actor"):
        registry.register(Organization.model_validate(changed))


@pytest.mark.parametrize("mutation", ["run", "role", "action", "actor", "scope", "time", "version"])
def test_action_authorization_is_bounded(host, mutation):
    registry, _, _, context = host
    assert registry.grants(context, "CONTRACTOR-A01", "Contractor")
    data = context.model_dump()
    role, action = "Contractor", "CONTRACTOR-A01"
    if mutation == "run":
        data["run_id"] = "run-2"
    elif mutation == "role":
        role = "Supplier"
    elif mutation == "action":
        action = "CONTRACTOR-A02"
    elif mutation == "actor":
        data["actor_id"] = "competitor"
    elif mutation == "scope":
        data["scope"]["ref"]["id"] = "org-2"
    elif mutation == "time":
        data["business_time"]["offset"] = 10
    else:
        data["authorization_refs"][0]["version"] = "2"
    with pytest.raises(AccessDenied):
        registry.grants(ActionContext.model_validate(data), action, role)


def test_tools_require_all_five_capability_sources(host):
    registry, _, _, context = host
    assert registry.permitted_tools(context, "CONTRACTOR-A01", "Contractor", {"screen", "write"},
                                    {"screen", "write"}, {"screen"}, {"screen", "write"}) == {"screen"}
    assert registry.permitted_tools(context, "CONTRACTOR-A01", "Contractor", {"screen"}, {"screen"}, {"screen"}, set()) == set()


class EvidenceProjection(StrictRecord):
    description: str


def test_reference_resolution_is_typed_scoped_private_and_versioned(host):
    registry, _, grant, context = host
    resolver = ReferenceResolver("run-1")
    resolver.register_kind("Evidence", EvidenceProjection, str)
    evidence = ref_type("Evidence").model_validate(ref("Evidence", "source"))
    private = ref_type("Evidence").model_validate(ref("Evidence", "competitor-finances"))
    resolver.register_projection(evidence, {"description": "Current authorized state"})
    resolver.register_projection(private, {"description": "Private quote"})
    resolver.freeze_read("read-1", [evidence, private])
    grants = registry.grants(context, "CONTRACTOR-A01", "Contractor")
    assert resolver.resolve(context, evidence, grants).description == "Current authorized state"
    forged = context.model_dump()
    forged["visible_refs"].append(private.model_dump())
    with pytest.raises(AccessDenied, match="not authorized"):
        resolver.resolve(ActionContext.model_validate(forged), private, grants)
    for mutation in [{"run_id": "run-2"}, {"read_token": "stale"}, {"visible_refs": []}]:
        forged = context.model_dump()
        forged.update(mutation)
        with pytest.raises(AccessDenied):
            resolver.resolve(ActionContext.model_validate(forged), evidence, grants)
    with pytest.raises(ValueError, match="version conflict"):
        resolver.register_projection(evidence, {"description": "Overwritten history"})
    with pytest.raises(ValueError, match="serialization"):
        resolver.register_projection(Reference.model_validate(ref("Evidence", "integer-version", 1)), {"description": "Bad version"})
    latest = ref_type("Evidence").model_validate(ref("Evidence", "source", "2"))
    resolver.register_projection(latest, {"description": "Updated authorized state"})
    resolver.freeze_read("read-2", [latest])
    grant_data = grant.model_dump()
    grant_data["ref"]["version"] = "2"
    grant_data["readable_refs"] = [latest.model_dump()]
    registry.authorize(Authorization.model_validate(grant_data))
    current = context.model_dump()
    current.update(read_token="read-2", visible_refs=[latest.model_dump()], authorization_refs=[grant_data["ref"]])
    current = ActionContext.model_validate(current)
    assert resolver.resolve(current, latest, registry.grants(current, "CONTRACTOR-A01", "Contractor")).description == "Updated authorized state"
    assert resolver.resolve(context, evidence, grants).description == "Current authorized state"


def test_returned_organizations_cannot_mutate_registered_identity(host):
    registry, _, _, _ = host
    organization = registry.get("org-1")
    organization.assignments.clear()
    assert len(registry.get("org-1").assignments) == 2


def test_revoked_authority_is_not_reactivated_by_retry_or_restart(host, tmp_path):
    registry, _, grant, context = host
    registry.revoke(grant.ref)
    registry.authorize(grant)
    with pytest.raises(AccessDenied, match="no longer active"):
        registry.grants(context, "CONTRACTOR-A01", "Contractor")
    path = tmp_path / "authority-state.json"
    registry.save(path)
    restored = OrganizationRegistry.load(path, "run-1")
    with pytest.raises(AccessDenied, match="no longer active"):
        restored.grants(context, "CONTRACTOR-A01", "Contractor")


def test_authorization_revision_requires_exact_supersession_and_keeps_history(host, tmp_path):
    registry, _, grant, context = host
    changed = grant.model_dump()
    changed["ref"]["version"] = "revision-B"
    changed["tool_ids"] = ["screen"]
    new = Authorization.model_validate(changed)
    registry.authorize(new, supersedes=grant.ref)
    with pytest.raises(AccessDenied, match="no longer active"):
        registry.grants(context, "CONTRACTOR-A01", "Contractor")
    current = context.model_copy(update={"authorization_refs": [new.ref]})
    assert registry.grants(current, "CONTRACTOR-A01", "Contractor") == [new]
    path = tmp_path / "authority-state.json"
    registry.save(path)
    restored = OrganizationRegistry.load(path, "run-1")
    assert restored.grants(current, "CONTRACTOR-A01", "Contractor") == [new]
    with pytest.raises(AccessDenied, match="reactivated"):
        restored.authorize(grant, supersedes=new.ref)


def test_current_reference_resolution_uses_host_authority_after_revocation(host):
    registry, _, grant, context = host
    resolver = ReferenceResolver("run-1")
    resolver.register_kind("Evidence", EvidenceProjection, str)
    evidence = context.visible_refs[0]
    resolver.register_projection(evidence, {"description": "Private current observation"})
    resolver.freeze_read(context.read_token, [evidence])
    assert resolver.resolve_action(context, evidence, registry, "CONTRACTOR-A01", "Contractor")
    registry.revoke(grant.ref)
    with pytest.raises(AccessDenied):
        resolver.resolve_action(context, evidence, registry, "CONTRACTOR-A01", "Contractor")


def test_reference_resolution_checks_exact_authorization_and_scope(host):
    registry, _, grant, context = host
    resolver = ReferenceResolver("run-1")
    resolver.register_kind("Evidence", EvidenceProjection, str)
    evidence = context.visible_refs[0]
    resolver.register_projection(evidence, {"description": "Observation"})
    resolver.freeze_read(context.read_token, [evidence])
    for changes in ({"authorization_refs": []}, {"scope": {**scope(), "ref": ref("Organization", "competitor")}}):
        data = {**context.model_dump(), **changes}
        with pytest.raises(AccessDenied):
            resolver.resolve(ActionContext.model_validate(data), evidence, [grant])


def test_reading_token_cannot_be_reused_by_another_run_or_resolver(host):
    registry, _, grant, context = host
    resolver = ReferenceResolver("run-1")
    resolver.register_kind("Evidence", EvidenceProjection, str)
    evidence = context.visible_refs[0]
    resolver.register_projection(evidence, {"description": "Run one observation"})
    resolver.freeze_read(context.read_token, [evidence])

    foreign_context = context.model_copy(update={"run_id": "run-2"})
    with pytest.raises(AccessDenied, match="another run"):
        resolver.resolve(foreign_context, evidence, [grant])

    other_resolver = ReferenceResolver("run-2")
    other_resolver.register_kind("Evidence", EvidenceProjection, str)
    other_resolver.register_projection(evidence, {"description": "Run two observation"})
    other_resolver.freeze_read(context.read_token, [evidence])
    with pytest.raises(AccessDenied, match="another run"):
        resolver.resolve(foreign_context, evidence, [grant])

    with pytest.raises(AccessDenied, match="another run"):
        other_resolver.resolve(context, evidence, [grant])


def test_projection_schema_checks_its_embedded_identity(host):
    from src.actions.contracts.common import EvidenceRecord

    _, _, _, context = host
    resolver = ReferenceResolver("run-1")
    resolver.register_kind("Evidence", EvidenceRecord, str)
    with pytest.raises(ValueError, match="identity"):
        resolver.register_projection(context.visible_refs[0], {
            "ref": ref("Evidence", "another-source"), "source_kind": "synthetic", "basis_kind": "assumed",
            "locator": "fixture", "content_hash": "0" * 64, "effective_window": None,
        })
