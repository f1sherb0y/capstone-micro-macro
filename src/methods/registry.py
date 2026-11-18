"""Explicit host binding of pure methods, exact versions and strict schemas."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import inspect
import json
from pathlib import Path
from typing import Callable

from pydantic import TypeAdapter, ValidationError

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, StrictRecord, walk_references
from src.actions.contracts.references import ActionReadView
from src.actions.implementation import callable_implementation
from src.methods.models import MethodDefinition, MethodResult, MethodTechnicalError, MethodUnsupported
from src.organization.registry import AccessDenied


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class MethodBinding:
    definition: MethodDefinition
    input_model: type[StrictRecord]
    output_model: type[StrictRecord]
    executor: Callable
    content_digest: str
    declaration: dict


def _binding_contents(definition, input_model, output_model, executor):
    return {"schema_version": "local-method-binding.v2",
            "definition": definition.model_dump(mode="json"),
            "input_schema": input_model.model_json_schema(), "output_schema": output_model.model_json_schema(),
            "implementation": inspect.getsource(executor),
            "implementation_module_sha256": hashlib.sha256(Path(inspect.getsourcefile(executor)).read_bytes()).hexdigest(),
            "executor_implementation": callable_implementation(executor),
            "boundary_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


class MethodRegistry:
    """No dynamic imports or fallback versions; methods are supplied by the host."""

    def __init__(self):
        self._bindings = {}
        self._sealed = False

    def register(self, definition, input_model, output_model, executor):
        if self._sealed:
            raise ValueError("Method registry is sealed")
        definition = MethodDefinition.model_validate(definition)
        key = definition.method_ref.key()
        if key in self._bindings:
            raise ValueError("Method version already registered")
        for model in (input_model, output_model):
            if not isinstance(model, type) or not issubclass(model, StrictRecord) or not model.model_fields:
                raise ValueError("Method schemas must be nonempty strict records")
        if not callable(executor):
            raise TypeError("Method executor must be host supplied")
        contents = _binding_contents(definition, input_model, output_model, executor)
        self._bindings[key] = MethodBinding(deepcopy(definition), input_model, output_model, executor,
            digest(contents), deepcopy(contents))

    @staticmethod
    def _check_binding(binding):
        """Never report an old digest for changed metadata, schemas or Python code.

        Captured state and transitive dependencies remain explicitly configured
        by the host; this check does not inspect or publish closure contents.
        """
        current = _binding_contents(binding.definition, binding.input_model, binding.output_model, binding.executor)
        if digest(current) != binding.content_digest or digest(binding.declaration) != binding.content_digest:
            raise ValueError('Registered method definition, schemas or executable implementation changed')

    def snapshot(self):
        for binding in self._bindings.values():
            self._check_binding(binding)
        registry = MethodRegistry()
        registry._bindings = deepcopy(self._bindings)
        registry._sealed = True
        for binding in registry._bindings.values():
            registry._check_binding(binding)
        return registry

    @property
    def content_digest(self):
        for binding in self._bindings.values():
            self._check_binding(binding)
        return digest([{"ref": list(key), "digest": value.content_digest}
                       for key, value in sorted(self._bindings.items(), key=lambda pair: repr(pair[0]))])

    def catalog(self):
        for binding in self._bindings.values():
            self._check_binding(binding)
        return [{"definition": binding.definition.model_dump(mode="json"), "content_digest": binding.content_digest,
                 "input_schema": binding.input_model.model_json_schema(), "output_schema": binding.output_model.model_json_schema()}
                for _, binding in sorted(self._bindings.items(), key=lambda pair: repr(pair[0]))]

    @staticmethod
    def unsupported(method_ref):
        return MethodUnsupported(kind="unsupported", capability_ref={
            "kind": "Capability", "id": f"local-method:{method_ref.id}:{method_ref.version}", "version": "1"})

    def invoke(self, method_ref, data, *, context: ActionContext, action_id: str, reading):
        if not isinstance(reading, ActionReadView):
            raise AccessDenied('Method invocation requires its original authorized action reading')
        permitted = reading.check_method_execution(context, action_id, self, method_ref)

        def finish(result):
            if binding is not None:
                self._check_binding(binding)
            return reading._record_method_result(method_ref, data, result)

        binding = self._bindings.get(method_ref.key())
        if binding is not None:
            self._check_binding(binding)
        if not permitted or binding is None or action_id not in binding.definition.action_ids:
            return finish(self.unsupported(method_ref))
        adapter = TypeAdapter(MethodResult[binding.output_model])
        try:
            value = binding.input_model.model_validate(data)
        except ValidationError as exc:
            return finish(adapter.validate_python({"kind": "invalid_input", "issues": [
                {"field_path": ".".join(str(part) for part in issue["loc"]) or "input",
                 "code": issue["type"], "expected": "Valid registered method input"}
                for issue in exc.errors(include_input=False)]}))
        sources = getattr(value, "source_refs", ())
        basis = {ref.key(): ref for ref in walk_references(value) if ref.kind == "Evidence"}
        if not sources or not basis:
            return finish(adapter.validate_python({"kind": "needs_information", "missing_fields": ["method_input_provenance"]}))
        # These reads and rechecks use the action's current run, token and grant.
        # A local MethodRef is host metadata, never a fabricated macro object.
        projections = [{"ref": ref.model_dump(mode="json"), "value": reading.resolve(ref).model_dump(mode="json")}
                       for ref in sources]
        for ref in basis.values():
            record = reading.resolve(ref)
            if not isinstance(record, EvidenceRecord):
                return finish(adapter.validate_python({"kind": "invalid_input", "issues": [{
                    "field_path": "basis_refs", "code": "evidence_schema", "expected": "Registered EvidenceRecord"}]}))
            if record.effective_window is not None and not record.effective_window.contains(context.business_time):
                return finish(adapter.validate_python({"kind": "needs_information", "missing_fields": ["current_method_evidence"]}))
        reading.recheck()
        input_digest = digest({"run_id": context.run_id, "actor_id": context.actor_id, "action_id": action_id,
            "operation_id": context.operation_id, "read_token": context.read_token,
            "function_ref": context.function_ref.model_dump(mode="json"),
            "authorization_refs": [ref.model_dump(mode="json") for ref in context.authorization_refs],
            "contract_ref": context.contract_ref.model_dump(mode="json"),
            "task_ref": context.task_ref.model_dump(mode="json"),
            "scope": context.scope.model_dump(mode="json"), "business_time": context.business_time.model_dump(mode="json"),
            "registry_digest": self.content_digest, "method_digest": binding.content_digest,
            "input": value.model_dump(mode="json"), "source_projections": projections})
        self._check_binding(binding)
        try:
            result = binding.output_model.model_validate(binding.executor(deepcopy(value)))
        except Exception:
            reading.recheck()
            self._check_binding(binding)
            return finish(MethodTechnicalError(kind="technical_error", error={"kind": "unrecorded",
                "correlation_id": context.operation_id, "code": "method_execution_failed"}, retryability="unknown"))
        reading.recheck()
        self._check_binding(binding)
        return finish(adapter.validate_python({"kind": "ok", "value": result, "method_ref": binding.definition.method_ref,
            "input_digest": input_digest, "input_refs": [{"data_space": {"kind": "run", "id": context.run_id}, "ref": ref}
                                                       for ref in sources],
            "basis_refs": [ref.model_dump(mode="python") for ref in basis.values()]}))
