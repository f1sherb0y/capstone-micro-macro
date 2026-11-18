"""Run-local action registration and processor binding.

The contract catalog is the source of truth for the 106 action identifiers.
This registry adds the executable boundary without treating declaration as
implementation: an action may be registered while still returning
``unsupported`` until a trusted processor is explicitly bound.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from collections import Counter

from src.actions.contracts.catalog import ActionContract, ContractCatalog, ROOT
from src.actions.contracts.common import Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.organization.models import Role, RoleConfiguration
from src.organization.registry import load_role_configurations
from src.skills.loader import SkillBundle, SkillLoader, SkillLoadError
from src.json_input import read_json_object


Processor = Callable[..., Any]


def _candidate_declaration(fields, choices):
    if not isinstance(fields, dict) or set(fields) - set(choices):
        raise ValueError('Candidate selection requires a mapping of registered action choices')
    for paths in fields.values():
        if (not isinstance(paths, (tuple, list)) or not paths
                or any(not isinstance(path, str) or not path
                    or not all(part.isidentifier() for part in path.split('.')) for path in paths)
                or len(set(paths)) != len(paths)):
            raise ValueError('Candidate selection requires distinct explicit payload field paths')
    return tuple((choice, tuple(paths)) for choice, paths in sorted(fields.items()))


def _candidate_values(payload, path):
    selections = [payload]
    for name in path.split('.'):
        selections = [getattr(item, name) for value in selections
            for item in (value if isinstance(value, (list, tuple)) else [value])]
    return selections


@dataclass(frozen=True)
class ActionRegistration:
    action_id: str
    role: Role
    contract: ActionContract
    strategy: str
    processor_id: str | None = None
    processor: Processor | None = None
    skill: SkillBundle | None = None
    candidate_fields: tuple[tuple[str, tuple[str, ...]], ...] = ()
    candidate_collection_fields: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def check_candidate_permissions(self, payload, candidates):
        """Check required targets and explicitly declared possibly empty lists.

        Collection paths end at lists of actual references. Only their empty
        membership is optional; every present reference still requires exact
        current candidate membership and the selected branch's permission.
        Existing required fields keep their nonempty selection requirement.
        """
        if not isinstance(candidates, CandidateSet):
            raise ValueError('Candidate permissions require the actual typed candidate set')
        choice = payload.choice
        candidates.check_referenced_choices(choice, list(walk_references(payload)))
        for path in dict(self.candidate_fields).get(choice, ()):
            refs = [ref for value in _candidate_values(payload, path) for ref in walk_references(value)]
            candidates.check_selected(choice, refs)
        for path in dict(self.candidate_collection_fields).get(choice, ()):
            for refs in _candidate_values(payload, path):
                if (not isinstance(refs, (list, tuple))
                        or any(not isinstance(ref, Reference) for ref in refs)):
                    raise ValueError('Candidate collections require explicit lists of typed target references')
                if refs:
                    candidates.check_selected(choice, list(refs))

    @property
    def implemented(self) -> bool:
        return self.processor is not None

    @property
    def skill_declared(self) -> bool:
        return self.skill is not None

    @property
    def skill_status(self) -> str:
        return self.skill.manifest.status if self.skill is not None else "missing"


class ActionRegistry:
    """Register every declared action and bind only explicitly supplied code."""

    def __init__(self, root: Path = ROOT, *, catalog: ContractCatalog | None = None,
                 role_configurations: dict[str, RoleConfiguration] | None = None,
                 skill_loader: SkillLoader | None = None, load_skills: bool = True):
        self.root = Path(root).resolve()
        self.catalog = catalog or ContractCatalog(self.root)
        self.role_configurations = role_configurations or load_role_configurations(self.root / "config/roles")
        self._skills: dict[str, SkillBundle] = {}
        _, inventory = read_json_object(self.root / "config/action_registry.json")
        source_paths = {item["action_id"]: item["source"] for item in inventory["actions"]}
        contract_metadata = {
            action_id: (contract.role, source_paths[action_id],
                        f"role-contract.v1:{action_id}:input",
                        f"role-contract.v1:{action_id}:payload")
            for action_id, contract in self.catalog.contracts.items()
        }
        if load_skills:
            try:
                loader = skill_loader or SkillLoader(self.root, contract_metadata=contract_metadata)
                self._skills = {bundle.manifest.action_id: bundle for bundle in loader.discover()}
            except SkillLoadError:
                raise
        unknown_skills = set(self._skills) - set(self.catalog.contracts)
        if unknown_skills:
            raise ValueError(f"Skill manifests are not registered actions: {sorted(unknown_skills)}")
        for action_id, skill in self._skills.items():
            self._validate_skill_binding(action_id, self.catalog.get(action_id), skill)
        self._registrations: dict[str, ActionRegistration] = {}
        for action_id, contract in self.catalog.contracts.items():
            config = self.role_configurations.get(contract.role)
            if config is None:
                raise ValueError(f"Missing role configuration for {contract.role}")
            skill = self._skills.get(action_id)
            self._registrations[action_id] = ActionRegistration(
                action_id=action_id, role=contract.role, contract=contract,
                strategy=config.strategy, skill=skill,
            )
        if len(self._registrations) != 106:
            raise ValueError("Exactly 106 actions must be registered")

    def _validate_skill_binding(self, action_id: str, contract: ActionContract, skill: SkillBundle) -> None:
        manifest = skill.manifest
        if manifest.action_id != action_id or manifest.role != contract.role:
            raise ValueError(f"Skill role/action mismatch for {action_id}")
        if manifest.spec_source_sha256 != contract.source_sha256:
            raise ValueError(f"Skill source digest differs from the contract for {action_id}")
        if manifest.input_schema_id != f"role-contract.v1:{action_id}:input":
            raise ValueError(f"Skill input schema differs from the contract for {action_id}")
        if manifest.output_schema_id != f"role-contract.v1:{action_id}:payload":
            raise ValueError(f"Skill output schema differs from the contract for {action_id}")
        role_config = self.role_configurations[contract.role]
        declared_tools = set(manifest.tool_ids)
        configured_tools = set(role_config.tool_ids)
        if not declared_tools <= configured_tools:
            raise ValueError(f"Skill declares tools outside the role configuration for {action_id}")

    def get(self, action_id: str) -> ActionRegistration:
        try:
            return self._registrations[action_id]
        except KeyError as exc:
            raise KeyError(f"Unknown action: {action_id}") from exc

    def register_processor(self, action_id: str, processor_id: str, processor: Processor,
                           *, strategy: str | None = None,
                           candidate_fields: dict[str, tuple[str, ...]] | None = None,
                           candidate_collection_fields: dict[str, tuple[str, ...]] | None = None) -> ActionRegistration:
        registration = self.get(action_id)
        if not isinstance(processor_id, str) or not processor_id.strip():
            raise ValueError("Processor identifier is required")
        if not callable(processor):
            raise TypeError("Action processor must be callable")
        declarations = {}
        for name, fields in (('candidate_fields', candidate_fields),
                ('candidate_collection_fields', candidate_collection_fields)):
            if fields is not None:
                declarations[name] = _candidate_declaration(fields, registration.contract.choices)
        if declarations:
            registration = ActionRegistration(**{**registration.__dict__, **declarations})
        required = dict(registration.candidate_fields)
        if any(set(paths) & set(required.get(choice, ()))
                for choice, paths in registration.candidate_collection_fields):
            raise ValueError('Candidate path cannot declare both required and possibly empty selection')
        if registration.skill is not None and registration.skill.manifest.processor_id != processor_id:
            raise ValueError("Processor identifier differs from the Skill manifest")
        if registration.skill is not None and registration.skill.manifest.status != "implemented":
            raise ValueError("A declared-only Skill cannot bind an executable processor")
        if strategy is not None and strategy != registration.strategy:
            if strategy not in {"single_agent", "organization_discussion"}:
                raise ValueError("Unknown action decision strategy")
            registration = ActionRegistration(**{**registration.__dict__, "strategy": strategy})
        updated = ActionRegistration(**{**registration.__dict__, "processor_id": processor_id,
                                        "processor": processor})
        self._registrations[action_id] = updated
        return updated

    def bind_skill_processors(self, processors: dict[str, Processor]) -> None:
        """Bind processors by manifest id, rejecting unknown or duplicate ids."""
        for action_id, skill in self._skills.items():
            processor = processors.get(skill.manifest.processor_id)
            if processor is not None:
                self.register_processor(action_id, skill.manifest.processor_id, processor)
        unknown = set(processors) - {skill.manifest.processor_id for skill in self._skills.values()}
        if unknown:
            raise ValueError(f"Processors have no declared Skill: {sorted(unknown)}")

    def all(self) -> tuple[ActionRegistration, ...]:
        return tuple(self._registrations[key] for key in sorted(self._registrations))

    @property
    def action_ids(self) -> frozenset[str]:
        return frozenset(self._registrations)

    @property
    def implemented_action_ids(self) -> frozenset[str]:
        return frozenset(key for key, value in self._registrations.items() if value.implemented)

    def coverage(self) -> dict[str, int]:
        return {"declared": len(self._registrations), "implemented": len(self.implemented_action_ids),
                "unsupported": len(self._registrations) - len(self.implemented_action_ids)}

    def skill_audit(self) -> dict[str, object]:
        """Return an explicit per-action implementation/Skill evidence matrix.

        A manifest, a bound processor, and a validated decision are separate
        facts.  The latter is only true after a processor has been bound; the
        method, macro binding, and feedback dimensions remain unverified until
        their dedicated evidence is supplied.
        """
        actions = []
        for registration in self.all():
            manifest = registration.skill.manifest if registration.skill else None
            actions.append({
                "action_id": registration.action_id,
                "registered": True,
                "skill": "missing" if manifest is None else manifest.status,
                "processor": "bound" if registration.processor is not None else "unbound",
                "decision": "implemented" if registration.processor is not None else "pending",
                "method": "unassessed",
                "binding": "unverified",
                "feedback": "pending",
                "processor_id": registration.processor_id or (manifest.processor_id if manifest else None),
                "skill_version": manifest.skill_version if manifest else None,
                "skill_sha256": manifest.skill_sha256 if manifest else None,
            })
        counts = {
            "registered": len(actions),
            "with_skill": sum(item["skill"] != "missing" for item in actions),
            "skill_implemented": sum(item["skill"] == "implemented" for item in actions),
            "processor_bound": sum(item["processor"] == "bound" for item in actions),
            "decision_implemented": sum(item["decision"] == "implemented" for item in actions),
            "method_verified": 0,
            "binding_verified": 0,
            "feedback_verified": 0,
        }
        dimensions = {key: dict(Counter(item[key] for item in actions))
                      for key in ("skill", "processor", "decision", "method", "binding", "feedback")}
        # Processor consumers need both states even when every action is bound.
        dimensions["processor"] = {state: dimensions["processor"].get(state, 0)
                                   for state in ("bound", "unbound")}
        return {"schema_version": "action-skill-audit.v1", "actions": actions, "counts": counts,
                "dimensions": dimensions}
