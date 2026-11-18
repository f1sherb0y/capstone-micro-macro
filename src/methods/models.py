"""Strict local method metadata and the frozen public MethodResult shape."""
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import Field, model_validator

from src.actions.contracts.common import (
    EvidenceRef, MethodRef, Reference, StrictRecord, TechnicalFailure, TextId, ref_type,
)


Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
T = TypeVar("T")


class MethodDefinition(StrictRecord):
    method_ref: MethodRef
    namespace: Literal["micro_local"]
    effect_kind: Literal["pure_calculation"]
    invocation: Literal["trusted_processor"]
    input_schema_id: TextId
    output_schema_id: TextId
    action_ids: Annotated[list[TextId], Field(min_length=1)]
    support_domain: Annotated[list[TextId], Field(min_length=1)]
    unit_rule: Literal["exact_declared_units_no_conversion", "exact_sourced_monetary_conversion"]
    basis_locator: TextId
    basis_sha256: Digest
    calibration: Literal["mathematical_only", "synthetic_only", "real_calibrated"]
    limitations: Annotated[list[TextId], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_actions(self):
        if type(self.method_ref.version) is not str:
            raise ValueError("Local method versions serialize as strings")
        if len(set(self.action_ids)) != len(self.action_ids):
            raise ValueError("Method action identity repeated")
        return self


class RunSpace(StrictRecord):
    kind: Literal["run"]
    id: TextId


class ScopedInputRef(StrictRecord):
    data_space: RunSpace
    ref: Reference


class MethodOk(StrictRecord, Generic[T]):
    kind: Literal["ok"]
    value: T
    method_ref: MethodRef
    input_digest: Digest
    input_refs: list[ScopedInputRef]
    basis_refs: list[EvidenceRef]


class MethodNeedsInformation(StrictRecord):
    kind: Literal["needs_information"]
    missing_fields: Annotated[list[TextId], Field(min_length=1)]


class FieldIssue(StrictRecord):
    field_path: TextId
    code: TextId
    expected: TextId


class MethodInvalidInput(StrictRecord):
    kind: Literal["invalid_input"]
    issues: Annotated[list[FieldIssue], Field(min_length=1)]


class MethodUnsupported(StrictRecord):
    kind: Literal["unsupported"]
    capability_ref: ref_type("Capability")


class MethodTechnicalError(StrictRecord):
    kind: Literal["technical_error"]
    error: TechnicalFailure
    retryability: Literal["retryable", "non_retryable", "unknown"]


type MethodResult[V] = Annotated[
    MethodOk[V] | MethodNeedsInformation | MethodInvalidInput | MethodUnsupported | MethodTechnicalError,
    Field(discriminator="kind"),
]
