"""Compile the closed MD type notation using a grammar, never eval/import.

Only trusted, hash-checked source declarations reach this compiler. Business
data is validated by the resulting Pydantic schemas, not parsed as declarations.
"""
from __future__ import annotations

from itertools import count
from typing import Annotated, Literal, Union

from lark import Lark, Tree
from pydantic import Field, create_model, model_validator

from src.actions.contracts import common
from src.actions.contracts.semantic import validate_local


GRAMMAR = r"""
?start: expression
?expression: primary (("/" | "或") primary)+ -> alternatives
           | primary
?primary: NAME "<" expression ">" -> generic
        | "{" [fields] "}" -> record
        | NAME -> name
fields: field (("," | ";") field)* ["," | ";"]
field: NAME ":" expression
branches: branch (";" branch)* [";"]
branch: NAME "{" [fields] "}"
NAME: /[A-Za-z_][A-Za-z_0-9]*/
%import common.WS
%ignore WS
"""
PARSER = Lark(GRAMMAR, parser="lalr", start=["start", "branches"], maybe_placeholders=False)


class TypeCompiler:
    def __init__(self, definitions: dict[str, str], reference_kinds: set[str] | None = None):
        self.definitions = dict(definitions)
        # A reference kind is a host-registered business object, not an
        # arbitrary string supplied by a declaration.  The catalog passes the
        # complete frozen inventory; standalone compilers retain the small
        # transport set needed by unit tests and shared system types.
        self.reference_kinds = set({
            "Evidence", "Method", "Profile", "ClockProfile", "Rule",
            "Capability", "Organization", "WorkScope", "OwnerCase",
            "Project", "FunctionAssignment", "Authorization",
            "ActionContract", "DecisionTask", "CandidateSet",
        } if reference_kinds is None else reference_kinds) | set(definitions)
        self.types = {"string": str, "bool": bool, "int": int, "decimal": common.DecimalString,
                      "ScopeRef": common.ScopeRef, "Money": common.Money, "Measured": common.Measured,
                      "TimePoint": common.TimePoint, "TimeWindow": common.TimeWindow,
                      "Explanation": common.Explanation}
        self._building = set()
        self._anonymous = count(1)

    def parse(self, declaration: str) -> Tree:
        return PARSER.parse(declaration, start="start")

    def named(self, name: str):
        if name in self.types:
            return self.types[name]
        if name not in self.definitions:
            raise ValueError(f"Unregistered contract type: {name}")
        if name in self._building:
            raise ValueError(f"Cyclic inline schema: {name}; use registered references")
        self._building.add(name)
        try:
            declaration = self.definitions[name]
            # Local table rows also permit an unbraced field list.
            if not declaration.lstrip().startswith("{") and ":" in declaration:
                declaration = "{" + declaration + "}"
            result = self.compile(self.parse(declaration), name)
            self.types[name] = result
            return result
        finally:
            self._building.remove(name)

    def fields(self, tree: Tree) -> dict:
        result = {}
        for field in tree.children:
            name, expression = field.children
            if str(name) in result:
                raise ValueError(f"Duplicate field: {name}")
            result[str(name)] = (self.compile(expression), ...)
        return result

    def compile(self, tree: Tree, name: str | None = None):
        if tree.data == "name":
            value = str(tree.children[0])
            if value in self.types or value in self.definitions:
                return self.named(value)
            if value[0].islower():
                return Literal[value]
            raise ValueError(f"Unregistered contract type: {value}")
        if tree.data == "generic":
            constructor, argument = tree.children
            constructor = str(constructor)
            if constructor in {"Ref", "EntityId"}:
                if argument.data != "name":
                    raise ValueError("Reference kind must be a registered name")
                kind = str(argument.children[0])
                if constructor == "EntityId":
                    return common.TextId
                if kind not in self.reference_kinds:
                    raise ValueError(f"Unregistered reference kind: {kind}")
                return common.Reference if kind == "BusinessObject" else common.ref_type(kind)
            annotation = self.compile(argument)
            if constructor == "List":
                return list[annotation]
            if constructor == "Option":
                return annotation | None
            if constructor == "ValueState":
                return common.ValueState[annotation]
            raise ValueError(f"Unsupported type constructor: {constructor}")
        if tree.data == "record":
            fields = self.fields(tree.children[0]) if tree.children else {}
            return create_model(name or f"InlineRecord{next(self._anonymous)}", __base__=common.StrictRecord,
                                __validators__={"source_invariants": model_validator(mode="after")(validate_local)}, **fields)
        if tree.data == "alternatives":
            alternatives = tuple(self.compile(child, f"{name}_{index}" if name else None)
                                 for index, child in enumerate(tree.children))
            literals = [getattr(annotation, "__args__", ()) for annotation in alternatives]
            if all(getattr(annotation, "__origin__", None) is Literal for annotation in alternatives):
                return Literal[tuple(item for values in literals for item in values)]
            union = Union[alternatives]
            if all(isinstance(annotation, type) and issubclass(annotation, common.StrictRecord)
                   and "kind" in annotation.model_fields for annotation in alternatives):
                return Annotated[union, Field(discriminator="kind")]
            return union
        raise ValueError(f"Unsupported grammar node: {tree.data}")

    def record(self, name: str, declaration: str):
        tree = self.parse(declaration)
        if tree.data != "record":
            raise ValueError(f"Expected closed record: {name}")
        return self.compile(tree, name)

    def branches(self, name: str, declaration: str, common_fields: dict | None = None):
        tree = PARSER.parse(declaration, start="branches")
        variants = []
        choices = set()
        for branch in tree.children:
            choice = str(branch.children[0])
            if choice in choices:
                raise ValueError(f"Duplicate branch: {choice}")
            choices.add(choice)
            fields = dict(common_fields or {})
            fields.update(self.fields(branch.children[1]) if len(branch.children) > 1 else {})
            fields["choice"] = (Literal[choice], ...)
            variants.append(create_model(f"{name}_{choice}", __base__=common.StrictRecord, **fields))
        return Annotated[Union[tuple(variants)], Field(discriminator="choice")]
