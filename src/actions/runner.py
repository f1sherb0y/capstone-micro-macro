"""Uniform, authorization-aware execution of registered role actions."""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.registry import ActionRegistry, ActionRegistration
from src.actions.decision_strategies import DecisionStrategyBinding, DecisionStrategyOutcome
from src.json_input import parse_json_object
from src.organization.registry import AccessDenied, OrganizationRegistry


class ActionRunError(ValueError):
    """Raised when an invocation cannot pass its transport or identity checks."""


@dataclass(frozen=True)
class ActionExecution:
    action_id: str
    run_id: str
    operation_id: str
    strategy: str
    processor_id: str | None
    skill_id: str | None
    authorization_refs: tuple[tuple[str, str, str | int], ...]
    result: Any
    execution_path: str = "deterministic"


@dataclass(frozen=True)
class ActionAuditRecord:
    """Append-only run-local evidence for one action attempt."""

    schema_version: str
    run_id: str
    action_id: str
    operation_id: str
    input_schema_id: str
    input_version: str | int
    input_sha256: str
    execution_path: str
    strategy: str
    skill_id: str | None
    skill_version: str | None
    skill_sha256: str | None
    processor_id: str | None
    method_version: str | None
    policy_version: str | None
    model_version: str | None
    authorization_refs: tuple[tuple[str, str, str | int], ...]
    granted_authorization_refs: tuple[tuple[str, str, str | int], ...]
    input_validation: str
    authorization_status: str
    processor_status: str
    result_kind: str | None
    result_sha256: str | None
    error_code: str | None
    reference_status: str = "not_checked"
    reading_sha256: str | None = None
    read_token: str | None = None
    reading_source_mode: str | None = None
    method_registry_digest: str | None = None
    method_calls: tuple = ()
    decision_evidence: dict | None = None
    # Optional run-local witness; audit serialization keeps the original schema.
    source_reading_evidence: list[dict] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "action_id": self.action_id,
            "operation_id": self.operation_id,
            "input_schema_id": self.input_schema_id,
            "input_version": self.input_version,
            "input_sha256": self.input_sha256,
            "execution_path": self.execution_path,
            "strategy": self.strategy,
            "skill": {"id": self.skill_id, "version": self.skill_version, "sha256": self.skill_sha256},
            "processor_id": self.processor_id,
            "method_version": self.method_version,
            "method_registry_digest": self.method_registry_digest,
            "method_calls": deepcopy(list(self.method_calls)),
            "decision": deepcopy(self.decision_evidence),
            "policy_version": self.policy_version,
            "model_version": self.model_version,
            "authorization_refs": [list(ref) for ref in self.authorization_refs],
            "granted_authorization_refs": [list(ref) for ref in self.granted_authorization_refs],
            "stages": {"input_validation": self.input_validation, "authorization": self.authorization_status,
                       "processor": self.processor_status},
            "result_kind": self.result_kind,
            "result_sha256": self.result_sha256,
            "error_code": self.error_code,
            "reading": {"status": self.reference_status, "sha256": self.reading_sha256,
                        "read_token": self.read_token, "source_mode": self.reading_source_mode},
        }


class JsonlActionAuditSink:
    """Append action audit records to a run-local JSONL file.

    The sink is deliberately small and synchronous: a completed action must
    have durable evidence before its result is handed back to a caller.  The
    file is created under the caller-provided run directory, so independent
    runs cannot share an implicit cache or audit stream.
    """

    def __init__(self, path: str | Path, *, run_id: str | None = None):
        if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
            raise ActionRunError("Run identity is required")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self._seen_run_id: str | None = None
        if self.path.exists():
            records = self.read()
            run_ids = {record.get("run_id") for record in records}
            if len(run_ids) > 1 or (run_ids and None in run_ids):
                raise ActionRunError("Run-local audit file contains mixed or invalid run identities")
            self._seen_run_id = next(iter(run_ids), None)
            if self.run_id is not None and self._seen_run_id not in {None, self.run_id}:
                raise ActionRunError("Audit file belongs to another run")

    def __call__(self, record: ActionAuditRecord) -> None:
        if not isinstance(record.run_id, str) or not record.run_id.strip():
            raise ActionRunError("Run identity is required")
        if self.run_id is not None and record.run_id != self.run_id:
            raise ActionRunError("Audit record belongs to another run")
        if self._seen_run_id is not None and record.run_id != self._seen_run_id:
            raise ActionRunError("A run-local audit sink cannot mix run identities")
        # Serialize before opening the file: invalid nested numeric evidence
        # must not leave a partial line or establish a new run identity.
        encoded = json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False) + "\n"
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
        self._seen_run_id = record.run_id

    def read(self, *, run_id: str | None = None) -> list[dict[str, Any]]:
        if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
            raise ActionRunError("Run identity is required")
        expected = {value for value in (run_id, self.run_id, self._seen_run_id) if value is not None}
        if len(expected) > 1:
            raise ActionRunError("Audit record belongs to another run")
        if not self.path.exists():
            return []
        records = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = parse_json_object(line)
            except ValueError as exc:
                raise ActionRunError(f"Invalid action audit JSON at line {line_number}") from exc
            identity = record.get("run_id")
            if not isinstance(identity, str) or not identity.strip():
                raise ActionRunError(f"Invalid action audit run identity at line {line_number}")
            if expected and identity not in expected:
                raise ActionRunError("Audit record belongs to another run")
            expected.add(identity)
            records.append(record)
        return records


class ActionRunner:
    def __init__(self, registry: ActionRegistry, *, organizations: OrganizationRegistry | None = None,
                 audit_sink=None, method_version: str | None = None,
                 policy_version: str | None = None, model_version: str | None = None,
                 run_id: str | None = None, references: ReferenceResolver | None = None, methods=None,
                 decision_strategies=(), retain_reading_evidence: bool = False):
        self.registry = registry
        self.organizations = organizations
        self.references = references
        if methods is None:
            from src.methods.capacity import local_method_registry
            methods = local_method_registry()
        self.methods = methods.snapshot()
        configured_run_id = organizations.run_id if organizations is not None else run_id
        if configured_run_id is not None and (not isinstance(configured_run_id, str) or not configured_run_id.strip()):
            raise ValueError("Run identity is required")
        self.run_id = configured_run_id
        if references is not None and configured_run_id is not None and references.run_id != configured_run_id:
            raise ValueError("Reference resolver belongs to another run")
        self.last_execution: ActionExecution | None = None
        self.audit_sink = audit_sink
        self.method_version = method_version
        self.policy_version = policy_version
        self.model_version = model_version
        self.audit_records: list[ActionAuditRecord] = []
        self.retain_reading_evidence = retain_reading_evidence
        self.decision_strategies = {}
        for binding in decision_strategies:
            if not isinstance(binding,DecisionStrategyBinding) or binding.strategy in self.decision_strategies:
                raise ValueError('Distinct explicitly typed decision strategy bindings are required')
            for action_id in binding.action_ids:
                registration = registry.get(action_id)
                if registration.strategy != binding.strategy:
                    raise ValueError('Bound strategy differs from the action role configuration')
            if binding.model_version is not None and binding.model_version != self.model_version:
                raise ValueError('Bound strategy model version differs from the configured runner')
            self.decision_strategies[binding.strategy] = binding

    @staticmethod
    def _digest(value: Any) -> str:
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _record_audit(self, *, context: ActionContext, registration: ActionRegistration,
                      action_input: Any, execution_path: str, input_validation: str,
                      authorization_status: str, processor_status: str,
                      granted_authorization_refs=(), result=None, error_code=None,
                      reference_status="not_checked", reading=None, decision_evidence=None) -> None:
        manifest = registration.skill.manifest if registration.skill else None
        result_kind = getattr(result, "kind", None)
        if result_kind is None and isinstance(result, dict):
            result_kind = result.get("kind")
        reading_evidence = reading.evidence() if reading is not None else None
        record = ActionAuditRecord(
            schema_version="action-audit.v1", run_id=context.run_id, action_id=registration.action_id,
            operation_id=context.operation_id,
            input_schema_id=f"role-contract.v1:{registration.action_id}:input",
            input_version=context.contract_ref.version, input_sha256=self._digest(action_input),
            execution_path=execution_path, strategy=registration.strategy,
            skill_id=manifest.skill_id if manifest else None,
            skill_version=manifest.skill_version if manifest else None,
            skill_sha256=manifest.skill_sha256 if manifest else None,
            processor_id=registration.processor_id or (manifest.processor_id if manifest else None),
            method_version=self.method_version, policy_version=self.policy_version,
            model_version=self.model_version,
            authorization_refs=tuple(ref.key() for ref in context.authorization_refs),
            granted_authorization_refs=tuple(ref.ref.key() for ref in granted_authorization_refs),
            input_validation=input_validation, authorization_status=authorization_status,
            processor_status=processor_status, result_kind=result_kind,
            result_sha256=self._digest(result) if result is not None else None, error_code=error_code,
            reference_status=reference_status, read_token=context.read_token,
            reading_source_mode=self.references.source_mode if self.references is not None else None,
            reading_sha256=self._digest(reading_evidence) if reading_evidence is not None else None,
            method_registry_digest=self.methods.content_digest,
            method_calls=tuple(reading.method_evidence()) if reading is not None else (),
            decision_evidence=deepcopy(decision_evidence),
            source_reading_evidence=(deepcopy(reading_evidence) if self.retain_reading_evidence else None),
        )
        self.audit_records.append(record)
        if self.audit_sink is not None:
            self.audit_sink(record)

    @staticmethod
    def _technical_result(contract, context: ActionContext, code: str, *, retryability: str = "unknown"):
        value = {"kind": "technical_error",
                 "error": {"kind": "unrecorded", "correlation_id": context.operation_id, "code": code},
                 "retryability": retryability}
        return contract.result_adapter.validate_python(value)

    def _authorize(self, registration: ActionRegistration, context: ActionContext):
        if self.organizations is None:
            if context.execution_mode != "offline_fixture":
                raise ActionRunError("An organization registry is required for non-fixture execution")
            return ()
        try:
            return tuple(self.organizations.grants(context, registration.action_id, registration.role))
        except AccessDenied as exc:
            raise ActionRunError(str(exc)) from exc

    @staticmethod
    def _call_processor(processor, context, action_input, registration, reading=None):
        # Processors are intentionally ordinary callables; optional parameters
        # let a local processor consume the loaded Skill bundle without making
        # every action handler depend on the runtime implementation.
        try:
            signature = inspect.signature(processor)
        except (TypeError, ValueError):
            signature = None
        if signature is None:
            return processor(context, action_input)
        positional = [p for p in signature.parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        if len(positional) >= 4:
            return processor(context, action_input, registration, reading)
        if any(p.kind == p.VAR_POSITIONAL for p in signature.parameters.values()) or len(positional) >= 3:
            return processor(context, action_input, registration)
        return processor(context, action_input)

    def _execute(self, registration: ActionRegistration, context: ActionContext, action_input, execution_path,
                 reading=None):
        if execution_path not in {"single_agent", "organization_discussion", "deterministic"}:
            raise ActionRunError("Unknown action decision strategy")
        processor = registration.processor
        decision = {'strategy':execution_path,'component_id':registration.processor_id if execution_path=='deterministic' else None,
                    'version':None,'model_version':None,'status':'not_run'}
        if processor is None:
            return {"kind": "unsupported",
                    "capability_ref": {"kind": "Capability",
                                        "id": f"action-processor:{registration.action_id}", "version": "1"}}, decision
        binding = self.decision_strategies.get(execution_path) if execution_path!='deterministic' else None
        if execution_path!='deterministic':
            if binding is None or registration.action_id not in binding.action_ids:
                decision['status']='unbound'
                return {'kind':'unsupported','capability_ref':{'kind':'Capability',
                    'id':f'action-strategy:{execution_path}:{registration.action_id}','version':'1'}},decision
            decision=binding.evidence(status='started')
            if context.execution_mode=='llm' and binding.model_version is None:
                decision['status']='model_unconfigured'
                return {'kind':'unsupported','capability_ref':{'kind':'Capability',
                    'id':f'action-model:{execution_path}:{registration.action_id}','version':'1'}},decision
        try:
            if binding is None:
                result=self._call_processor(processor,deepcopy(context),deepcopy(action_input),registration,reading)
            else:
                result=binding.execute(context=deepcopy(context),action_input=deepcopy(action_input),
                    registration=registration,reading=reading,processor=processor)
                if isinstance(result,DecisionStrategyOutcome):
                    decision['execution']=deepcopy(result.evidence)
                    result=result.result
            decision['status']='returned'
            return result,decision
        except Exception:
            # A processor exception is a technical failure, never a business
            # rejection or a fabricated completed payload.
            decision['status']='failed'
            code='processor_exception' if binding is None else 'decision_strategy_exception'
            return self._technical_result(registration.contract,context,code),decision

    def _read_input(self, registration, context, action_input):
        if self.references is None:
            if context.execution_mode != "offline_fixture":
                raise ActionRunError("A reference resolver is required for non-fixture execution")
            return None, None
        if self.organizations is None:
            raise ActionRunError("An organization registry is required for resolved action reading")
        if self.references.source_mode == "fixture" and context.execution_mode != "offline_fixture":
            raise ActionRunError("Fixture projections require explicit offline_fixture execution")
        reading = ActionReadView(context, self.references, self.organizations,
                                 registration.action_id, registration.role, methods=self.methods,
                                 method_refs=registration.skill.manifest.method_refs if registration.skill else ())
        for ref in walk_references(action_input):
            reading.resolve(ref)
        candidates = reading.resolve(context.candidate_set_ref)
        if not isinstance(candidates, CandidateSet):
            raise ValueError("Candidate set requires its registered domain projection")
        candidates.check_context(context, registration.contract.choices)
        for candidate in candidates.candidates:
            reading.resolve(candidate.ref)
        return reading, candidates

    def prepare_decision(self, *, context, action_input, reading):
        """Prepare actual local option sources before a durable worker starts.

        The application holds its actual source/authority guard. Preparation
        uses a separate reading with the same method declarations and source
        boundary, while calculation is explicitly disabled. Existing direct
        strategy bindings without a preparation hook retain their behavior.
        """
        registration = self.registry.get(context.contract_ref.id)
        binding = self.decision_strategies.get(registration.strategy)
        if (context.execution_mode != 'llm' or binding is None
                or registration.action_id not in binding.action_ids or binding.prepare_invocation is None):
            return None
        if (context.run_id != self.run_id or not isinstance(reading, ActionReadView)
                or reading._resolver is not self.references or reading._organizations is not self.organizations
                or reading._role != registration.role or registration.skill is None):
            raise ActionRunError('Decision preparation changes its original runner, action or authorized reading')
        reading.check_method_context(context, registration.action_id)
        original = registration.contract.validate_input(action_input)
        def unchanged():
            return (self._digest(context), self._digest(original), reading.evidence(), reading.method_evidence())
        expected = unchanged()
        reading.recheck()
        inspection = ActionReadView(context, self.references, self.organizations,
            registration.action_id, registration.role, methods=reading._methods,
            method_refs=registration.skill.manifest.method_refs, allow_methods=False)
        try:
            for row in expected[2]:
                if inspection.resolve(Reference.model_validate(row['ref'])).model_dump(mode='json') != row['projection']:
                    raise ActionRunError('Decision preparation changes an original source projection')
            evidence = binding.prepare_invocation(context=deepcopy(context), action_input=deepcopy(original),
                registration=registration, reading=inspection)
            if evidence is not None and not isinstance(evidence, dict):
                raise ActionRunError('Decision preparation requires actual structured local evidence')
            if (self.registry.get(registration.action_id) is not registration
                    or self.decision_strategies.get(registration.strategy) is not binding):
                raise ActionRunError('Decision preparation changed the original registry or strategy binding')
            return deepcopy(evidence)
        finally:
            inspection.recheck()
            reading.recheck()
            if inspection.method_evidence() or unchanged() != expected:
                raise ActionRunError('Decision preparation changed original input, sources or professional method evidence')

    def run_action(self, context: ActionContext | dict, action_input: Any, *, execution_path: str | None = None):
        if not isinstance(context, ActionContext):
            context = ActionContext.model_validate(context)
        if self.run_id is None:
            self.run_id = context.run_id
        elif context.run_id != self.run_id:
            raise ActionRunError("Action runner belongs to another run")
        action_id = context.contract_ref.id
        registration = self.registry.get(action_id)
        contract = registration.contract
        if context.contract_ref.kind != "ActionContract":
            raise ActionRunError("Context contract reference must be an ActionContract")
        if context.run_id.strip() == "":
            raise ActionRunError("Run identity is required")
        path = execution_path or ("deterministic" if context.execution_mode in {"rule", "routine", "offline_fixture"}
                                  else registration.strategy)
        if path not in {"deterministic", registration.strategy}:
            raise ActionRunError(f"Execution path {path!r} is not configured for {action_id}")
        try:
            validated_input = contract.validate_input(action_input)
        except ValidationError:
            self._record_audit(context=context, registration=registration, action_input=action_input,
                               execution_path=path, input_validation="rejected", authorization_status="not_run",
                               processor_status="not_run", error_code="input_validation")
            raise
        try:
            auth = self._authorize(registration, context)
        except ActionRunError:
            self._record_audit(context=context, registration=registration, action_input=validated_input,
                               execution_path=path, input_validation="accepted", authorization_status="rejected",
                               processor_status="not_run", error_code="authorization")
            raise
        reading = None
        try:
            reading, candidates = self._read_input(registration, context, validated_input)
        except (ValueError, KeyError) as exc:
            self._record_audit(context=context, registration=registration, action_input=validated_input,
                               execution_path=path, input_validation="accepted", authorization_status="accepted",
                               processor_status="not_run", granted_authorization_refs=auth,
                               reference_status="rejected", error_code="reference_validation")
            raise ActionRunError(str(exc)) from exc
        raw_result,decision_evidence = self._execute(registration, context, validated_input, path, reading)
        reference_status = "accepted" if reading is not None else "fixture_unresolved"

        def recheck_access():
            # Both local work and output validation may consume live sources.
            # Preserve the original reading when its final recheck fails.
            try:
                self._authorize(registration, context)
                if reading is not None:
                    reading.recheck()
            except (ValueError, KeyError) as exc:
                denied = isinstance(exc, (ActionRunError, AccessDenied))
                self._record_audit(context=context, registration=registration, action_input=validated_input,
                                   execution_path=path, input_validation="accepted",
                                   authorization_status="revoked" if denied else "accepted",
                                   processor_status="executed", granted_authorization_refs=auth,
                                   reference_status="rejected", reading=reading,
                                   error_code="authorization" if denied else "reference_validation",
                                   decision_evidence=decision_evidence)
                raise ActionRunError(str(exc)) from exc

        recheck_access()
        try:
            result = contract.result_adapter.validate_python(raw_result)
            if result.kind == "completed":
                payload = contract.validate_decision(validated_input, result.payload)
                if reading is not None:
                    output_refs = list(walk_references(payload))
                    for ref in output_refs:
                        reading.resolve(ref)
                    registration.check_candidate_permissions(payload, candidates)
                result = contract.result_adapter.validate_python({"kind": "completed", "payload": payload})
        except Exception:
            if reading is not None:
                reference_status = "output_rejected"
            result = self._technical_result(contract, context, "processor_output_invalid", retryability="non_retryable")
        # Include output-only reads and changes made during decision/result
        # validation before publishing any accepted result or execution.
        recheck_access()
        execution = ActionExecution(
            action_id=action_id, run_id=context.run_id, operation_id=context.operation_id,
            strategy=registration.strategy, processor_id=registration.processor_id,
            skill_id=registration.skill.manifest.skill_id if registration.skill else None,
            authorization_refs=tuple(ref.key() for ref in context.authorization_refs), result=result,
            execution_path=path,
        )
        self._record_audit(context=context, registration=registration, action_input=validated_input,
                           execution_path=path, input_validation="accepted", authorization_status="accepted",
                           processor_status="bound" if registration.processor is not None else "unbound",
                           granted_authorization_refs=auth, result=result, reading=reading,
                           reference_status=reference_status,
                           decision_evidence=decision_evidence,
                           error_code=(getattr(getattr(result, "error", None), "code", None)
                                       if getattr(result, "kind", None) == "technical_error" else None))
        self.last_execution = execution
        return result

    def run_deterministic(self, context: ActionContext | dict, action_input: Any):
        return self.run_action(context, action_input, execution_path="deterministic")

    def run_single_agent(self, context: ActionContext | dict, action_input: Any):
        return self.run_action(context, action_input, execution_path="single_agent")

    def run_organization_discussion(self, context: ActionContext | dict, action_input: Any):
        return self.run_action(context, action_input, execution_path="organization_discussion")


def run_action(context: ActionContext | dict, action_input: Any, *, registry: ActionRegistry,
               organizations: OrganizationRegistry | None = None, execution_path: str | None = None,
               references: ReferenceResolver | None = None, methods=None):
    """Run one action through the common contract, authorization and result path."""
    return ActionRunner(registry, organizations=organizations, references=references, methods=methods).run_action(
        context, action_input, execution_path=execution_path)
