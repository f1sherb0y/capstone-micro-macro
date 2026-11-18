"""Compile the registered source inventory into concrete Input/Payload schemas."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from pydantic import TypeAdapter

from src.actions.contracts import owner, bank, contractor, supplier, architect, engineer, qs, government
from src.actions.contracts.common import ActionResult, Reference, ScopeRef
from src.actions.contracts.type_language import TypeCompiler
from src.json_input import read_json_object


ROOT = Path(__file__).resolve().parents[3]
EXPLICIT_BRANCHES = {**owner.BRANCH_FIELDS, **bank.BRANCH_FIELDS, **contractor.BRANCH_FIELDS, **supplier.BRANCH_FIELDS}
PROFESSIONAL_ROLES = {"Architect", "Engineer", "QS", "Government"}


def _code_segments(text: str) -> list[str]:
    return re.findall(r"`([^`]+)`", text)


def _reference_kinds(inventory: dict) -> set[str]:
    kinds = set()
    for action in inventory["actions"]:
        text = " ".join((action.get(key) or "") for key in
                         ("input_definition", "payload_definition", "local_type_definitions"))
        kinds.update(re.findall(r"Ref<([A-Za-z][A-Za-z0-9]*)>", text))
    return kinds


def local_definitions(section: str) -> dict[str, str]:
    definitions = {}
    for line in section.splitlines():
        match = re.match(r"\| `([A-Za-z][A-Za-z0-9]+)` \| (.+) \|$", line)
        if match:
            code = _code_segments(match.group(2))
            if not code:
                raise ValueError(f"Missing local definition: {match.group(1)}")
            definitions[match.group(1)] = code[0]
    return definitions


def _input_reference_data(value):
    """Validate assembler reference values against each concrete input type.

    Keep every supplied field, including unvalidated model_copy additions, so
    the closed target schema still rejects unknown fields and wrong kinds.
    Other model instances retain their normal strict validation behavior.
    """
    if isinstance(value, Reference):
        return {key: _input_reference_data(item) for key, item in vars(value).items()}
    if isinstance(value, dict):
        return {key: _input_reference_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_input_reference_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_input_reference_data(item) for item in value)
    return value


@dataclass(frozen=True)
class ActionContract:
    action_id: str
    role: str
    source_sha256: str
    input_model: type
    payload_type: object
    choices: tuple[str, ...]

    @property
    def payload_adapter(self):
        return TypeAdapter(self.payload_type)

    @property
    def result_adapter(self):
        return TypeAdapter(ActionResult[self.payload_type])

    def validate_input(self, data):
        return self.input_model.model_validate(_input_reference_data(data))

    def validate_payload(self, data):
        return self.payload_adapter.validate_python(data)

    @property
    def decision_validator(self):
        """Expose the actual rule callable for the original role and code identity."""
        rules = {"Architect": architect, "Engineer": engineer, "QS": qs, "Government": government}
        if self.role in rules:
            return rules[self.role].validate_decision
        from src.actions.contracts.role_rules import validate_decision
        return validate_decision

    def validate_decision(self, action_input, data):
        action_input = self.validate_input(action_input)
        payload = self.validate_payload(data)
        self.decision_validator(self.action_id, action_input, payload)
        return payload


class ContractCatalog:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        _, inventory = read_json_object(self.root / "config/action_registry.json")
        for relative, digest in inventory["source_hashes"].items():
            path = (self.root / relative).resolve()
            if not path.is_relative_to(self.root.resolve() / "zwtnew"):
                raise ValueError("Contract source path is outside the registered specification tree")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Stale source declaration: {relative}")
        self.contracts = {}
        self.compilers = {}
        reference_kinds = _reference_kinds(inventory)
        # This shared draft belongs to the system interface, not to a role.
        system_source = self.root / "zwtnew/gba_simulation_developer_guide/gba_simulation_developer_guide/06_engineering/system_interfaces.md"
        system_text = system_source.read_text(encoding="utf-8-sig")
        finance_row = next(line for line in system_text.splitlines() if line.startswith("| `FinanceApplicationDraft` |"))
        finance_definition = _code_segments(finance_row)[1]
        for action in inventory["actions"]:
            source_text = (self.root / action["source"]).read_text(encoding="utf-8-sig")
            if (action["source_card"] not in source_text
                    or hashlib.sha256(action["source_card"].encode("utf-8")).hexdigest() != action["card_sha256"]
                    or action["local_type_definitions"] not in source_text):
                raise ValueError(f"Declaration is detached from source: {action['action_id']}")
            for label, field in (("输入记录", "input_definition"), ("输出分支", "payload_definition")):
                match = re.search(rf"^- \*\*{label}\*\*[：:]\s*(.+)$", action["source_card"], re.M)
                if match is None or action[field] != match.group(1):
                    raise ValueError(f"Source field mismatch: {action['action_id']} {field}")
            role = action["role"]
            if role not in self.compilers:
                definitions = local_definitions(action["local_type_definitions"])
                definitions["FinanceApplicationDraft"] = finance_definition
                self.compilers[role] = TypeCompiler(definitions, reference_kinds)
            compiler = self.compilers[role]
            input_code = _code_segments(action["input_definition"])[0]
            input_declaration = input_code.split("=", 1)[1].strip()
            input_model = compiler.record(action["input_type"], input_declaration)
            if role in PROFESSIONAL_ROLES:
                declaration = next(code for code in _code_segments(action["payload_definition"])
                                   if re.match(r"[a-z_]+\{", code))
                payload_type = compiler.branches(action["payload_type"], declaration,
                                                {"scope": (ScopeRef, ...), "note": (str | None, ...)})
            else:
                base = next(code for code in _code_segments(action["payload_definition"])
                            if code.startswith("{choice:"))
                model = compiler.record(action["payload_type"] + "Base", base)
                common_fields = {name: (field.annotation, ...) for name, field in model.model_fields.items() if name != "choice"}
                variants = {choice: [] for choice in action["choices"]}
                for choices, fields in EXPLICIT_BRANCHES[action["action_id"]]:
                    for choice in choices.split("/"):
                        if choice not in variants:
                            raise ValueError(f"Unknown explicit branch: {action['action_id']} {choice}")
                        variants[choice].append(fields)
                declaration = ";".join(f"{choice}{{{','.join(fields)}}}" for choice, fields in variants.items())
                payload_type = compiler.branches(action["payload_type"], declaration, common_fields)
            payload_schema = TypeAdapter(payload_type).json_schema()
            choices = tuple(payload_schema["discriminator"]["mapping"])
            if set(choices) != set(action["choices"]):
                raise ValueError(f"Compiled choice mismatch: {action['action_id']}")
            if action["action_id"] in self.contracts:
                raise ValueError("Duplicate action schema")
            self.contracts[action["action_id"]] = ActionContract(action["action_id"], role, action["source_sha256"],
                                                                input_model, payload_type, choices)
        if len(self.contracts) != 106:
            raise ValueError("Exactly 106 action contracts required")

    def get(self, action_id: str) -> ActionContract:
        return self.contracts[action_id]
