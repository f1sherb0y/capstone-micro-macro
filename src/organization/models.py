from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from src.actions.contracts.common import StrictRecord, TextId, Reference, ScopeRef, TimeWindow, ValueState, ref_type


Role = Literal["Owner", "Bank", "Architect", "Engineer", "QS", "Government", "Contractor", "Supplier"]
Strategy = Literal["single_agent", "organization_discussion"]


class MemberConfiguration(StrictRecord):
    member_id: TextId
    name: TextId
    functions: list[TextId]
    responsibilities: list[TextId]


class RoleConfiguration(StrictRecord):
    role: Role
    version: TextId
    strategy: Strategy
    members: list[MemberConfiguration] = Field(min_length=1)
    tool_ids: list[TextId]
    source: TextId

    @model_validator(mode="after")
    def unique_members(self):
        if len({m.member_id for m in self.members}) != len(self.members):
            raise ValueError("Repeated member identity")
        return self


class RoleAssignment(StrictRecord):
    role: Role
    function_ref: ref_type("FunctionAssignment")
    configuration_version: TextId
    basis_refs: list[Reference] = Field(min_length=1)


class Authorization(StrictRecord):
    ref: ref_type("Authorization")
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type("FunctionAssignment")
    action_ids: list[TextId] = Field(min_length=1)
    scopes: list[ScopeRef] = Field(min_length=1)
    readable_refs: list[Reference]
    tool_ids: list[TextId]
    validity: TimeWindow
    basis_refs: list[Reference] = Field(min_length=1)


class Organization(StrictRecord):
    organization_id: TextId
    actor_id: TextId
    source_ids: list[TextId] = Field(min_length=1)
    public_description: str
    public_location: ValueState[str]
    assignments: list[RoleAssignment] = Field(min_length=1)
    members: list[MemberConfiguration]
    evidence_refs: list[ref_type("Evidence")] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_identities(self):
        functions = [assignment.function_ref.key() for assignment in self.assignments]
        if len(functions) != len(set(functions)):
            raise ValueError("Function assignment repeated")
        members = [member.member_id for member in self.members]
        if len(members) != len(set(members)):
            raise ValueError("Organization member repeated")
        return self
