"""Resolve typed, immutable host projections at a run-local reading boundary."""
from __future__ import annotations

from copy import deepcopy
import json

from pydantic import BaseModel

from src.actions.contracts.common import Reference, ActionContext, StrictRecord, ref_type
from src.organization.models import Authorization
from src.organization.registry import AccessDenied, OrganizationRegistry, scope_covers


def _projection_json(value: BaseModel) -> str:
    """Preserve exact transport types while ignoring JSON object key order."""
    return json.dumps(value.model_dump(mode="json"), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class ReferenceSchemaRegistry:
    """Run-local registry for the concrete schema behind each business Ref.

    Action contracts only carry typed references.  A host must explicitly
    register the projection schema before an object can enter a reading
    boundary; this keeps a well-shaped reference from becoming an untyped
    business fact.
    """

    def __init__(self):
        self._schemas: dict[str, tuple[type[BaseModel], type]] = {}
        self._identity_fields: dict[str, str | None] = {}

    def register_kind(self, kind: str, schema: type[BaseModel], version_type: type,
                      *, identity_field: str | None = None) -> None:
        ref_type(kind)
        if (not isinstance(schema, type) or not issubclass(schema, StrictRecord)
                or not schema.model_fields or schema.model_config.get("extra") != "forbid"):
            raise ValueError("Object kinds require a non-empty strict schema")
        if version_type not in (str, int):
            raise ValueError("Object kind versions must serialize as str or int")
        if identity_field is None and "ref" in schema.model_fields:
            identity_field = "ref"
        if identity_field is not None and identity_field not in schema.model_fields:
            raise ValueError("Projection identity field is absent from its schema")
        previous = self._schemas.get(kind)
        if previous is not None and (previous != (schema, version_type)
                                     or self._identity_fields[kind] != identity_field):
            raise ValueError("Object kind schema conflict")
        self._schemas[kind] = schema, version_type
        self._identity_fields[kind] = identity_field

    def validate_projection(self, ref: Reference, data: BaseModel | dict) -> StrictRecord:
        schema, version_type = self.schema_for(ref.kind)
        if type(ref.version) is not version_type:
            raise ValueError("Object kind version serialization mismatch")
        data = data.model_dump(mode="python") if isinstance(data, BaseModel) else data
        value = schema.model_validate(data)
        identity_field = self._identity_fields[ref.kind]
        if identity_field is not None:
            identity = getattr(value, identity_field)
            if not isinstance(identity, Reference) or identity.key() != ref.key():
                raise ValueError("Projection identity differs from its reference")
        return deepcopy(value)

    def schema_for(self, kind: str) -> tuple[type[BaseModel], type]:
        try:
            return self._schemas[kind]
        except KeyError as exc:
            raise ValueError(f"Unregistered object kind: {kind}") from exc

    @property
    def registered_kinds(self) -> frozenset[str]:
        return frozenset(self._schemas)


class ReferenceResolver:
    def __init__(self, run_id: str, *, source_mode: str = "fixture",
                 schemas: ReferenceSchemaRegistry | None = None):
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("Run identity is required")
        if source_mode not in {"formal", "fixture"}:
            raise ValueError("Explicit formal or fixture source mode is required")
        self.run_id = run_id
        self.source_mode = source_mode
        self.registry = deepcopy(schemas) if schemas is not None else ReferenceSchemaRegistry()
        self._objects: dict[tuple, BaseModel] = {}
        self._snapshots: dict[str, tuple[str, frozenset[tuple]]] = {}

    def register_kind(self, kind: str, schema: type[StrictRecord], version_type: type) -> None:
        self.registry.register_kind(kind, schema, version_type)

    def register_projection(self, ref: Reference, data: BaseModel | dict) -> None:
        value = self.registry.validate_projection(ref, data)
        if getattr(value, 'run_id', self.run_id) != self.run_id:
            raise AccessDenied('Projection content belongs to another run')
        value_json = _projection_json(value)
        old = self._objects.get(ref.key())
        if old is not None and (old != value or _projection_json(old) != value_json):
            raise ValueError("Immutable object version conflict")
        self._objects[ref.key()] = deepcopy(value)

    def freeze_read(self, token: str, refs: list[Reference]) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Reading token is required")
        keys = frozenset(ref.key() for ref in refs)
        if not keys <= self._objects.keys():
            raise ValueError("Cannot freeze unresolved references")
        old = self._snapshots.get(token)
        if old is not None and old != (self.run_id, keys):
            raise ValueError("Reading token conflict")
        self._snapshots[token] = (self.run_id, keys)

    def resolve(self, context: ActionContext, ref: Reference, grants: list[Authorization]) -> BaseModel:
        """Resolve with host-verified grants; use resolve_action for current authority."""
        if context.run_id != self.run_id:
            raise AccessDenied("Reference context belongs to another run")
        snapshot = self._snapshots.get(context.read_token)
        if snapshot is None or snapshot[0] != context.run_id:
            raise AccessDenied("Reading token belongs to another run or is unknown")
        if ref.key() not in snapshot[1]:
            raise AccessDenied("Reference is not available at this reading boundary")
        if ref.key() not in {visible.key() for visible in context.visible_refs}:
            raise AccessDenied("Reference is absent from the authorized invocation view")
        authorization_keys = {grant_ref.key() for grant_ref in context.authorization_refs}
        if not any(grant.ref.key() in authorization_keys
                   and grant.actor_id == context.actor_id and grant.function_ref == context.function_ref
                   and grant.validity.contains(context.business_time)
                   and any(scope_covers(scope, context.scope) for scope in grant.scopes)
                   and ref.key() in {readable.key() for readable in grant.readable_refs} for grant in grants):
            raise AccessDenied("Reference is not authorized")
        return deepcopy(self._objects[ref.key()])

    def resolve_action(self, context: ActionContext, ref: Reference, organizations: OrganizationRegistry,
                       action_id: str, role: str) -> BaseModel:
        if organizations.run_id != self.run_id:
            raise AccessDenied("Organization registry belongs to another run")
        grants = organizations.grants(context, action_id, role)
        return self.resolve(context, ref, grants)


class ActionReadView:
    """A processor reads exact host projections with current action authority.

    Only resolved objects enter the read evidence. Returned objects are copies,
    so a processor cannot change the frozen snapshot by mutating a list field.
    Inspection may retain the original method registry and references with
    allow_methods=False; calculate then fails before invoking any method.
    """

    def __init__(self, context: ActionContext, resolver: ReferenceResolver,
                 organizations: OrganizationRegistry, action_id: str, role: str, *, methods=None, method_refs=(),
                 allow_methods: bool = True):
        if type(allow_methods) is not bool:
            raise ValueError('Method execution mode must be an explicit boolean')
        if context.run_id != resolver.run_id or context.run_id != organizations.run_id:
            raise AccessDenied("Action reading belongs to another run")
        self._context = deepcopy(context)
        self._resolver = resolver
        self._organizations = organizations
        self._action_id = action_id
        self._role = role
        self.organization_id = organizations.grants(context, action_id, role)[0].organization_id
        self._reads: dict[tuple, BaseModel] = {}
        self._methods = methods
        self._allow_methods = allow_methods
        self._method_refs = frozenset(ref.key() for ref in method_refs)
        self._method_records = []

    def check_method_context(self, context, action_id):
        if context != self._context or action_id != self._action_id:
            raise AccessDenied("Method invocation differs from its action reading context")
        self._organizations.grants(self._context, self._action_id, self._role)

    def check_method_execution(self, context, action_id, registry, method_ref):
        """Apply the same read-only and Skill boundary to direct registry calls."""
        self.check_method_context(context, action_id)
        if not self._allow_methods:
            raise AccessDenied('This reading retains method declarations for inspection only; calculation is disabled')
        if registry is not self._methods:
            raise AccessDenied('Method registry differs from the original action reading')
        return method_ref.key() in self._method_refs

    def _record_method_result(self, method_ref, data, result):
        self._method_records.append({"method_ref": method_ref.model_dump(mode="json"),
            "registry_digest": self._methods.content_digest if self._methods is not None else None,
            "input": data.model_dump(mode="json") if isinstance(data, BaseModel) else deepcopy(data),
            "result": result.model_dump(mode="json")})
        return result

    def calculate(self, method_ref, data):
        from src.methods.registry import MethodRegistry
        self.check_method_context(self._context, self._action_id)
        if not self._allow_methods:
            raise AccessDenied('This reading retains method declarations for inspection only; calculation is disabled')
        if self._methods is None or method_ref.key() not in self._method_refs:
            result = MethodRegistry.unsupported(method_ref)
            return self._record_method_result(method_ref, data, result)
        return self._methods.invoke(method_ref, data, context=self._context, action_id=self._action_id, reading=self)

    def method_evidence(self):
        return deepcopy(self._method_records)

    def resolve(self, ref: Reference) -> BaseModel:
        value = self._resolver.resolve_action(self._context, ref, self._organizations,
                                              self._action_id, self._role)
        value_json = _projection_json(value)
        prior = self._reads.get(ref.key())
        if prior is not None and (value != prior or value_json != _projection_json(prior)):
            raise ValueError("Action reading changed during execution")
        if prior is None:
            self._reads[ref.key()] = deepcopy(value)
        return value

    def recheck(self) -> None:
        self._organizations.grants(self._context, self._action_id, self._role)
        for key, prior in tuple(self._reads.items()):
            # Rechecking must not replace the retained original before the
            # comparison succeeds. A failed check preserves its evidence.
            value = self._resolver.resolve_action(self._context,
                Reference(kind=key[0], id=key[1], version=key[2]), self._organizations,
                self._action_id, self._role)
            if value != prior or _projection_json(value) != _projection_json(prior):
                raise ValueError("Action reading changed during execution")

    def evidence(self) -> list[dict]:
        return [{"ref": {"kind": key[0], "id": key[1], "version": key[2]},
                 "projection": value.model_dump(mode="json")}
                for key, value in sorted(self._reads.items(), key=lambda row: repr(row[0]))]
