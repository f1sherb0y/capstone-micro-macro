"""Validate explicit acceptance claims against captured, correlated JSON evidence."""
from pathlib import Path
from typing import Annotated, Literal
import hashlib
import re

from pydantic import Field, model_validator

from integration.scenario_v2 import parse_input_json
from src.actions.contracts.common import StrictRecord, TextId
from src.methods.models import Digest


class DimensionTarget(StrictRecord):
    kind: Literal['dimension']
    dimension: Literal['C', 'D', 'M', 'B', 'F', 'V']


class BranchTarget(StrictRecord):
    kind: Literal['branch']
    choice: TextId


class CheckTarget(StrictRecord):
    kind: Literal['check']
    check_id: TextId


class ScenarioTarget(StrictRecord):
    kind: Literal['scenario']
    scenario_id: Literal['V1', 'V2', 'V3', 'V4', 'V5', 'V6', 'V7']


EvidenceTarget = Annotated[DimensionTarget | BranchTarget | CheckTarget | ScenarioTarget,
    Field(discriminator='kind')]


class EvidenceClaim(StrictRecord):
    action_id: TextId
    source_sha256: Digest
    target: EvidenceTarget
    outcome: Literal['passed', 'failed', 'unknown', 'not_applicable']
    origin: Literal['synthetic', 'actual']
    artifact_path: TextId
    artifact_sha256: Digest
    json_pointer: str


class ActionEvidenceMap(StrictRecord):
    schema_version: Literal['action-evidence-map.v1']
    claims: list[EvidenceClaim]

    @model_validator(mode='after')
    def unique_claims(self):
        keys = [(row.action_id, tuple(row.target.model_dump().items()), row.artifact_path, row.json_pointer)
            for row in self.claims]
        if len(keys) != len(set(keys)):
            raise ValueError('Acceptance mapping repeats an original claim locator')
        return self


def _pointer(value, pointer):
    """Resolve RFC 6901 pointers without coercing invalid indices or escapes."""
    if pointer == '':
        return value
    if not pointer.startswith('/'):
        raise ValueError('Evidence locator must be a JSON pointer')
    for token in pointer[1:].split('/'):
        if re.search(r'~(?![01])', token):
            raise ValueError('Invalid evidence JSON pointer escape')
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict):
            if token not in value:
                raise ValueError('Evidence JSON pointer object key is absent')
            value = value[token]
        elif isinstance(value, list):
            if not re.fullmatch(r'0|[1-9][0-9]*', token) or int(token) >= len(value):
                raise ValueError('Evidence JSON pointer array index is invalid')
            value = value[int(token)]
        else:
            raise ValueError('Evidence JSON pointer traverses a scalar')
    return value


def validate_evidence_map(registry, mapping, *, root):
    """Check links once per artifact, retaining all conflicting/failing claims.

    Locator integrity and explicit correlation prove only a recorded claim;
    they do not certify test quality, current implementation or business effects.
    No action statuses or applicability exemptions are promoted here.
    """
    mapping = ActionEvidenceMap.model_validate(mapping)
    root = Path(root).resolve()
    actions = {row['action_id']: row for row in registry['actions']}
    artifacts, claims = {}, []
    for claim in mapping.claims:
        action = actions.get(claim.action_id)
        if action is None or claim.source_sha256 != action['source_sha256']:
            raise ValueError('Evidence mapping names an unknown action or stale frozen source')
        target = claim.target
        if isinstance(target, BranchTarget) and target.choice not in action['choices']:
            raise ValueError('Evidence mapping names an illegal action branch')
        if isinstance(target, CheckTarget) and target.check_id not in {*action['checks'], *action['role_checks']}:
            raise ValueError('Evidence mapping names a CHECK outside this action role')
        relative = Path(claim.artifact_path)
        path = (root / relative).resolve()
        if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(root):
            raise ValueError('Evidence artifact must remain inside the repository')
        if path not in artifacts:
            raw = path.read_bytes()
            _, document = parse_input_json(raw)
            artifacts[path] = (hashlib.sha256(raw).hexdigest(), document)
        digest, document = artifacts[path]
        if digest != claim.artifact_sha256:
            raise ValueError('Evidence artifact differs from its declared raw SHA')
        node = _pointer(document, claim.json_pointer)
        expected = {'action_id': claim.action_id, 'source_sha256': claim.source_sha256,
            'target': target.model_dump(mode='json'), 'outcome': claim.outcome, 'origin': claim.origin}
        if not isinstance(node, dict) or any(node.get(key) != value for key, value in expected.items()):
            raise ValueError('Located evidence lacks exact action/source/target/outcome/origin correlation')
        claims.append({**claim.model_dump(mode='json'), 'link_status': 'sha_and_locator_correlated'})
    return {'schema_version': 'validated-action-evidence-map.v1', 'claims': claims,
        'distinct_artifact_count': len(artifacts), 'completion_proven': False,
        'limitations': 'Correlated original claims only; failed/unknown/not-applicable claims are retained. No independent completion or business-effect proof is inferred.'}
