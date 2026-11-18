"""Closed common object projections defined in the frozen interface contract.

Role-specific business objects need their own schemas before they can be read;
this registry is deliberately limited to the common types defined here.
"""
from __future__ import annotations

from pydantic import model_validator

from src.actions.contracts.common import (
    ActionContext, EvidenceRecord, Reference, ScopeRef, StrictRecord,
    TextId, TimePoint, TimeWindow, ref_type,
)
from src.actions.contracts.references import ReferenceSchemaRegistry
from src.organization.models import Authorization, RoleAssignment


class Candidate(StrictRecord):
    ref: Reference
    permitted_choices: list[str]


class CandidateSet(StrictRecord):
    operation_id: TextId
    scope: ScopeRef
    as_of: TimePoint
    candidates: list[Candidate]
    search_profile_ref: ref_type("Profile")

    @model_validator(mode="after")
    def unique_candidates(self):
        keys = [candidate.ref.key() for candidate in self.candidates]
        if len(keys) != len(set(keys)):
            raise ValueError("Candidate reference repeated")
        for candidate in self.candidates:
            if len(set(candidate.permitted_choices)) != len(candidate.permitted_choices):
                raise ValueError("Candidate permitted choice repeated")
        return self

    def check_context(self, context: ActionContext, choices: tuple[str, ...]) -> None:
        if (self.operation_id != context.operation_id or self.scope != context.scope
                or self.as_of != context.business_time):
            raise ValueError("Candidate set differs from its invocation operation, scope or time")
        visible = {ref.key() for ref in context.visible_refs}
        if any(candidate.ref.key() not in visible for candidate in self.candidates):
            raise ValueError("Candidate set contains a reference outside the invocation view")
        if any(not set(candidate.permitted_choices) <= set(choices) for candidate in self.candidates):
            raise ValueError("Candidate set permits a choice outside this action contract")

    def check_referenced_choices(self, choice: str, references: list[Reference]) -> None:
        candidates = {candidate.ref.key(): candidate for candidate in self.candidates}
        for ref in references:
            candidate = candidates.get(ref.key())
            if candidate is not None and choice not in candidate.permitted_choices:
                raise ValueError("Selected choice is not permitted for the referenced candidate")

    def check_selected(self, choice: str, references: list[Reference]) -> None:
        if not references:
            raise ValueError("Candidate selection has no target reference")
        exposed = {candidate.ref.key() for candidate in self.candidates}
        if any(ref.key() not in exposed for ref in references):
            raise ValueError("Selected reference is outside the exposed candidate set")
        self.check_referenced_choices(choice, references)


def common_projection_schemas() -> ReferenceSchemaRegistry:
    registry = ReferenceSchemaRegistry()
    for kind, schema in (("Evidence", EvidenceRecord), ("Authorization", Authorization),
                         ("FunctionAssignment", RoleAssignment), ("CandidateSet", CandidateSet),
                         ("TimeWindow", TimeWindow)):
        registry.register_kind(kind, schema, str,
                               identity_field="function_ref" if kind == "FunctionAssignment" else None)
    return registry
