"""Run-local identity and authorization registry, with no formal resource ledger."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from pydantic import Field

from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId, ScopeRef, ref_type
from src.organization.models import Authorization, Organization, RoleConfiguration
from src.json_input import read_json_object


class AccessDenied(ValueError):
    pass


def scope_covers(granted: ScopeRef, requested: ScopeRef) -> bool:
    if granted.kind != requested.kind or granted.ref != requested.ref:
        return False
    return {ref.key() for ref in requested.coverage_refs} <= {ref.key() for ref in granted.coverage_refs}


class OrganizationSnapshot(StrictRecord):
    schema_version: str
    run_id: TextId
    organizations: list[Organization]
    authorizations: list[Authorization]
    inactive_authorization_refs: list[ref_type("Authorization")] = Field(default_factory=list)


class OrganizationRegistry:
    def __init__(self, run_id: str):
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("Run identity is required")
        self.run_id = run_id
        self._organizations: dict[str, Organization] = {}
        self._actors: dict[str, str] = {}
        self._authorizations: dict[tuple, Authorization] = {}
        self._inactive_authorizations: set[tuple] = set()

    def register(self, organization: Organization) -> Organization:
        old = self._organizations.get(organization.organization_id)
        if old is not None:
            if old != organization:
                raise ValueError("Organization identity conflict; explicit revision required")
            return deepcopy(old)
        if organization.actor_id in self._actors:
            raise ValueError("Actor already belongs to a different organization")
        existing_sources = {s for org in self._organizations.values() for s in org.source_ids}
        if existing_sources.intersection(organization.source_ids):
            raise ValueError("Source identity duplicated across organizations")
        self._organizations[organization.organization_id] = deepcopy(organization)
        self._actors[organization.actor_id] = organization.organization_id
        return deepcopy(organization)

    def get(self, organization_id: str) -> Organization:
        return deepcopy(self._organizations[organization_id])

    def authorize(self, authorization: Authorization, *, supersedes: Reference | None = None) -> None:
        organization = self._organizations.get(authorization.organization_id)
        if organization is None or authorization.actor_id != organization.actor_id:
            raise AccessDenied("Authorization does not belong to this organization")
        if authorization.function_ref not in [assignment.function_ref for assignment in organization.assignments]:
            raise AccessDenied("Function is not assigned to this organization")
        previous = self._authorizations.get(authorization.ref.key())
        if previous is not None and previous != authorization:
            raise ValueError("Authorization version conflict")
        if supersedes is not None:
            if supersedes.kind != "Authorization" or supersedes.id != authorization.ref.id or supersedes == authorization.ref:
                raise ValueError("Superseded grant must be another exact version of the same authorization")
            if supersedes.key() not in self._authorizations:
                raise ValueError("Superseded authorization is unknown")
            old = self._authorizations[supersedes.key()]
            if old.organization_id != authorization.organization_id or old.actor_id != authorization.actor_id:
                raise AccessDenied("Authorization revision cannot change its organization or actor")
            if authorization.ref.key() in self._inactive_authorizations:
                raise AccessDenied("An inactive authorization version cannot be reactivated")
        self._authorizations[authorization.ref.key()] = deepcopy(authorization)
        if supersedes is not None:
            self._inactive_authorizations.add(supersedes.key())

    def revoke(self, ref: Reference) -> None:
        """Apply a trusted host authorization update, retaining historical grants."""
        if ref.kind != "Authorization" or ref.key() not in self._authorizations:
            raise ValueError("Cannot revoke an unknown authorization")
        self._inactive_authorizations.add(ref.key())

    def grants(self, context: ActionContext, action_id: str, role: str) -> list[Authorization]:
        if context.run_id != self.run_id:
            raise AccessDenied("Invocation belongs to another run")
        organization_id = self._actors.get(context.actor_id)
        if organization_id is None:
            raise AccessDenied("Unknown actor")
        organization = self._organizations[organization_id]
        if not any(a.role == role and a.function_ref == context.function_ref for a in organization.assignments):
            raise AccessDenied("Role and function assignment mismatch")
        grants = []
        if len({ref.key() for ref in context.authorization_refs}) != len(context.authorization_refs):
            raise AccessDenied("Authorization reference repeated")
        for ref in context.authorization_refs:
            if ref.key() in self._inactive_authorizations:
                raise AccessDenied("Authorization version is no longer active")
            grant = self._authorizations.get(ref.key())
            if grant is None or grant.actor_id != context.actor_id or grant.organization_id != organization_id:
                raise AccessDenied("Invalid authorization reference")
            if (grant.function_ref == context.function_ref and action_id in grant.action_ids
                    and grant.validity.contains(context.business_time)
                    and any(scope_covers(scope, context.scope) for scope in grant.scopes)):
                grants.append(deepcopy(grant))
        if not grants:
            raise AccessDenied("Action, time or scope exceeds authorization")
        return grants

    def permitted_tools(self, context: ActionContext, action_id: str, role: str,
                        declared: set[str], registered: set[str], run_scope: set[str], macro_supported: set[str]) -> set[str]:
        authorized = {tool for grant in self.grants(context, action_id, role) for tool in grant.tool_ids}
        return declared & registered & authorized & run_scope & macro_supported

    def save(self, path: Path) -> None:
        snapshot = OrganizationSnapshot(schema_version="organization.v2", run_id=self.run_id,
                                        organizations=list(self._organizations.values()),
                                        authorizations=list(self._authorizations.values()),
                                        inactive_authorization_refs=[self._authorizations[key].ref
                                                                     for key in sorted(self._inactive_authorizations, key=repr)])
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path, run_id: str) -> OrganizationRegistry:
        text, _ = read_json_object(path)
        snapshot = OrganizationSnapshot.model_validate_json(text)
        if snapshot.schema_version not in {"organization.v1", "organization.v2"} or snapshot.run_id != run_id:
            raise ValueError("Organization store version or run mismatch")
        if snapshot.schema_version == "organization.v1" and snapshot.inactive_authorization_refs:
            raise ValueError("Legacy organization snapshots cannot contain inactive authorization state")
        registry = cls(run_id)
        for organization in snapshot.organizations:
            registry.register(organization)
        for authorization in snapshot.authorizations:
            registry.authorize(authorization)
        for ref in snapshot.inactive_authorization_refs:
            registry.revoke(ref)
        return registry


def load_role_configurations(directory: Path) -> dict[str, RoleConfiguration]:
    configurations = {}
    for path in sorted(Path(directory).glob("*.json")):
        text, _ = read_json_object(path)
        configuration = RoleConfiguration.model_validate_json(text)
        if configuration.role in configurations:
            raise ValueError("Duplicate role configuration")
        configurations[configuration.role] = configuration
    if set(configurations) != {"Owner", "Bank", "Architect", "Engineer", "QS", "Government", "Contractor", "Supplier"}:
        raise ValueError("Exactly eight role configurations are required")
    return configurations
