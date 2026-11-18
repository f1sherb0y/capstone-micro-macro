"""Common transport types from the frozen interface contract.

Structural validation does not confer access or prove a formal business effect.
Reference resolution and profile checks are separate trusted host operations.
"""
from __future__ import annotations

from decimal import Decimal
from functools import cache
import re
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, AfterValidator, create_model, model_validator


TextId = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
VersionToken = TextId | int
T = TypeVar("T")


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class Reference(StrictRecord):
    kind: TextId
    id: TextId
    version: VersionToken

    def key(self) -> tuple[str, str, str | int]:
        return self.kind, self.id, self.version

    def __eq__(self, other):
        # Typed refs narrow the allowed kind during validation; they do not
        # introduce another identity for the same immutable domain reference.
        if not isinstance(other, Reference):
            return NotImplemented
        return self.key() == other.key()

    def __hash__(self):
        return hash(self.key())


@cache
def ref_type(kind: str) -> type[Reference]:
    if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", kind):
        raise ValueError(f"Invalid registered object kind: {kind}")
    return create_model(f"{kind}Ref", __base__=Reference, kind=(Literal[kind], ...))


EvidenceRef = ref_type("Evidence")
MethodRef = ref_type("Method")
ProfileRef = ref_type("Profile")
ClockRef = ref_type("ClockProfile")


class OrganizationScope(StrictRecord):
    kind: Literal["organization"]
    ref: ref_type("Organization")
    coverage_refs: list[ref_type("WorkScope")]


class AssessmentScope(StrictRecord):
    kind: Literal["assessment_case"]
    ref: ref_type("OwnerCase")
    coverage_refs: list[ref_type("WorkScope")]


class ProjectScope(StrictRecord):
    kind: Literal["project"]
    ref: ref_type("Project")
    coverage_refs: list[ref_type("WorkScope")]


ScopeRef = Annotated[OrganizationScope | AssessmentScope | ProjectScope, Field(discriminator="kind")]


def _decimal_string(value: str) -> str:
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value):
        raise ValueError("Expected finite decimal transport string")
    if not Decimal(value).is_finite():
        raise ValueError("Non-finite decimal is forbidden")
    return value


DecimalString = Annotated[str, AfterValidator(_decimal_string)]


class Money(StrictRecord):
    value: DecimalString
    currency: TextId
    basis_ref: EvidenceRef


class Measured(StrictRecord):
    value: DecimalString
    unit: TextId
    basis_ref: EvidenceRef


class TimePoint(StrictRecord):
    clock_ref: ClockRef
    offset: int


class TimeWindow(StrictRecord):
    start: TimePoint
    end: TimePoint
    bounds: Literal["closed_open", "closed_closed", "open_closed", "open_open"]

    @model_validator(mode="after")
    def check_order(self):
        if self.start.clock_ref != self.end.clock_ref:
            raise ValueError("Time window must use one exact clock version")
        if self.start.offset > self.end.offset:
            raise ValueError("Time window start exceeds end")
        return self

    def contains(self, point: TimePoint) -> bool:
        if point.clock_ref != self.start.clock_ref:
            return False
        left = point.offset >= self.start.offset if self.bounds.startswith("closed") else point.offset > self.start.offset
        right = point.offset <= self.end.offset if self.bounds.endswith("closed") else point.offset < self.end.offset
        return left and right


class Known(StrictRecord, Generic[T]):
    state: Literal["known"]
    value: T


class Unknown(StrictRecord):
    state: Literal["unknown"]
    reason_code: TextId
    missing_refs: list[EvidenceRef]


class NotApplicable(StrictRecord):
    state: Literal["not_applicable"]
    rule_ref: ref_type("Rule")


class NotSupported(StrictRecord):
    state: Literal["not_supported"]
    capability_ref: ref_type("Capability")


type ValueState[V] = Annotated[Known[V] | Unknown | NotApplicable | NotSupported, Field(discriminator="state")]


class EvidenceRecord(StrictRecord):
    ref: EvidenceRef
    source_kind: Literal["real_user", "real_public", "synthetic"]
    basis_kind: Literal["observed", "inferred", "assumed"]
    locator: TextId
    content_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    effective_window: TimeWindow | None


class Explanation(StrictRecord):
    summary: str
    evidence_refs: list[EvidenceRef]
    assumptions: list[str]


class ActionContext(StrictRecord):
    run_id: TextId
    actor_id: TextId
    function_ref: ref_type("FunctionAssignment")
    authorization_refs: list[ref_type("Authorization")]
    operation_id: TextId
    contract_ref: ref_type("ActionContract")
    task_ref: ref_type("DecisionTask")
    scope: ScopeRef
    business_time: TimePoint
    read_token: TextId
    visible_refs: list[Reference]
    candidate_set_ref: ref_type("CandidateSet")
    execution_mode: Literal["llm", "rule", "routine", "offline_fixture"]


class ResumeCondition(StrictRecord):
    trigger: Literal["event", "time", "dependency_change"]
    object_refs: list[Reference]
    earliest_time: TimePoint | None
    condition_code: TextId


class RecordedFailure(StrictRecord):
    kind: Literal["recorded"]
    error_ref: ref_type("TechnicalError")


class UnrecordedFailure(StrictRecord):
    kind: Literal["unrecorded"]
    correlation_id: TextId
    code: TextId


TechnicalFailure = Annotated[RecordedFailure | UnrecordedFailure, Field(discriminator="kind")]


class Completed(StrictRecord, Generic[T]):
    kind: Literal["completed"]
    payload: T


class NeedsInformation(StrictRecord):
    kind: Literal["needs_information"]
    missing_fields: Annotated[list[TextId], Field(min_length=1)]
    requested_refs: list[Reference]


class Deferred(StrictRecord):
    kind: Literal["deferred"]
    reason_code: TextId
    resume_condition: ResumeCondition


class Unsupported(StrictRecord):
    kind: Literal["unsupported"]
    capability_ref: ref_type("Capability")


class TechnicalError(StrictRecord):
    kind: Literal["technical_error"]
    error: TechnicalFailure
    retryability: Literal["retryable", "non_retryable", "unknown"]


type ActionResult[P] = Annotated[Completed[P] | NeedsInformation | Deferred | Unsupported | TechnicalError,
                                 Field(discriminator="kind")]


def walk_references(value):
    """Traverse validated records, preserving each reference's exact version."""
    if isinstance(value, Reference):
        yield value
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from walk_references(getattr(value, name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from walk_references(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from walk_references(item)


class NumericProfile(StrictRecord):
    currencies: list[TextId]
    units: list[TextId]

    def check(self, value) -> None:
        if isinstance(value, Money) and value.currency not in self.currencies:
            raise ValueError("Currency is absent from the selected profile")
        if isinstance(value, Measured) and value.unit not in self.units:
            raise ValueError("Unit is absent from the selected profile")
        if isinstance(value, BaseModel):
            for name in type(value).model_fields:
                self.check(getattr(value, name))
        elif isinstance(value, dict):
            for item in value.values():
                self.check(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self.check(item)
