"""Read-only assembly of schema-registered macro object projections."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Literal, Protocol

from src.actions.contracts.common import ActionContext, Reference, StrictRecord
from src.actions.contracts.references import ReferenceResolver, ReferenceSchemaRegistry
from src.organization.models import Authorization
from src.organization.registry import AccessDenied, OrganizationRegistry


class MacroViewProvider(Protocol):
    def project(self, *, context: ActionContext, organization_id: str,
                grants: list[Authorization]) -> dict:
        """Query a fixed macro read point without advancing the engine."""
        ...


@dataclass(frozen=True)
class ObjectProjection:
    ref: Reference
    value: StrictRecord

@dataclass(frozen=True)
class MacroProjection:
    run_id: str
    macro_version: str
    state_version: str
    read_token: str
    organization_id: str
    source_mode: Literal["formal", "fixture"]
    objects: tuple[ObjectProjection, ...]
    digest: str


class AuthorizedMacroViewAssembler:
    """Host boundary; models cannot supply the provider, schemas or registry.

    Each returned object must use a registered closed projection schema and be
    readable in this action. This creates no formal ledger or macro writes.
    """

    def __init__(self, organizations: OrganizationRegistry, provider: MacroViewProvider,
                 schemas: ReferenceSchemaRegistry, *, macro_version: str,
                 source_mode: Literal["formal", "fixture"]):
        if not isinstance(macro_version, str) or not macro_version.strip():
            raise ValueError("Macro version is required")
        if source_mode not in {"formal", "fixture"}:
            raise ValueError("Explicit formal or fixture source mode is required")
        self.organizations = organizations
        self.provider = provider
        self.schemas = schemas
        self.macro_version = macro_version
        self.source_mode = source_mode
        self._boundaries: dict[tuple, str] = {}
        self._read_points: dict[str, tuple] = {}
        self._object_hashes: dict[tuple, str] = {}

    def assemble(self, context: ActionContext, action_id: str, role: str) -> MacroProjection:
        grants = self.organizations.grants(context, action_id, role)
        organization_id = grants[0].organization_id
        raw = self.provider.project(context=deepcopy(context), organization_id=organization_id,
                                    grants=deepcopy(grants))
        required = {"run_id", "macro_version", "state_version", "read_token", "business_time",
                    "organization_id", "objects"}
        if not isinstance(raw, dict) or set(raw) != required:
            raise ValueError("Macro projection envelope has missing or extra fields")
        if (raw["run_id"] != context.run_id or raw["organization_id"] != organization_id
                or raw["macro_version"] != self.macro_version):
            raise AccessDenied("Macro projection run, organization or version mismatch")
        if raw["read_token"] != context.read_token or raw["business_time"] != context.business_time.model_dump():
            raise AccessDenied("Macro projection does not match the invocation read point")
        if not isinstance(raw["state_version"], str) or not raw["state_version"].strip():
            raise ValueError("Macro state version is required")
        if not isinstance(raw["objects"], list):
            raise ValueError("Macro objects must be a list of registered projections")
        permitted = {ref.key() for grant in grants for ref in grant.readable_refs}
        permitted &= {ref.key() for ref in context.visible_refs}
        objects, seen, object_hashes = [], set(), {}
        for item in raw["objects"]:
            if not isinstance(item, dict) or set(item) != {"ref", "value"}:
                raise ValueError("Object projection must contain ref and value")
            ref = Reference.model_validate(item["ref"])
            if ref.key() not in permitted:
                raise AccessDenied("Macro object is outside the authorized action view")
            if ref.key() in seen:
                raise ValueError("Duplicate macro object projection")
            seen.add(ref.key())
            value = self.schemas.validate_projection(ref, item["value"])
            if getattr(value, 'run_id', context.run_id) != context.run_id:
                raise AccessDenied('Macro object content belongs to another run')
            value_hash = _digest(value.model_dump(mode="json"))
            prior_hash = self._object_hashes.get(ref.key())
            if prior_hash is not None and prior_hash != value_hash:
                raise ValueError("Immutable macro object version changed")
            object_hashes[ref.key()] = value_hash
            objects.append(ObjectProjection(ref=ref, value=value))
        # A grant can change while the adapter is querying the engine.
        if self.organizations.grants(context, action_id, role) != grants:
            raise AccessDenied("Authorization changed during macro projection")
        normalized = {**raw, "source_mode": self.source_mode,
                      "objects": [{"ref": item.ref.model_dump(mode="json"),
                                           "value": item.value.model_dump(mode="json")} for item in objects]}
        digest = _digest(normalized)
        read_point = (raw["state_version"], _digest(raw["business_time"]))
        prior_point = self._read_points.get(context.read_token)
        if prior_point is not None and prior_point != read_point:
            raise ValueError("Immutable macro read point changed")
        key = (context.read_token, organization_id, context.function_ref.key(), action_id,
               tuple(ref.key() for ref in context.authorization_refs),
               tuple(ref.key() for ref in context.visible_refs))
        old = self._boundaries.get(key)
        if old is not None and old != digest:
            raise ValueError("Immutable macro read point changed; request a new read token")
        self._boundaries[key] = digest
        self._read_points[context.read_token] = read_point
        self._object_hashes.update(object_hashes)
        return MacroProjection(context.run_id, self.macro_version, raw["state_version"],
                               context.read_token, organization_id, self.source_mode,
                               tuple(objects), digest)

    def build_resolver(self, context: ActionContext, action_id: str, role: str) -> ReferenceResolver:
        """Freeze the actual authorized projection for the action runtime."""
        projection = self.assemble(context, action_id, role)
        resolver = ReferenceResolver(projection.run_id, source_mode=projection.source_mode, schemas=self.schemas)
        for item in projection.objects:
            resolver.register_projection(item.ref, item.value)
        resolver.freeze_read(projection.read_token, [item.ref for item in projection.objects])
        return resolver


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()
