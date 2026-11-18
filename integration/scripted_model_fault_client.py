"""Explicit single-call synthetic faults for deferred offline V7 verification."""
from copy import deepcopy
from dataclasses import dataclass
import json
from threading import RLock
from typing import Literal

from src.actions.contracts.common import StrictRecord, TextId
from src.coordination.tasks import TaskConflict, task_digest


class ScriptedModelFaultSettings(StrictRecord):
    schema_version: Literal['scripted-model-fault-settings.v1']
    origin: Literal['synthetic']
    case_id: TextId
    fault: Literal['timeout', 'invalid_json']
    response: str | None


@dataclass(frozen=True)
class ScriptedModelFaultResponse:
    content: str
    metadata: dict


class ScriptedModelFaultClient:
    """Inject one declared local exception/response; never connect to a model.

    Supply this client to the existing action strategy in an explicitly
    synthetic verification run with authorized host-authored alternatives.
    It does not assemble options, change business processors or return a fake
    success. A single alternative bypasses model selection in the normal
    strategy, so the fixture must independently supply at least two valid
    alternatives before asserting that either fault path was exercised.
    """

    def __init__(self, settings):
        self.settings = ScriptedModelFaultSettings.model_validate(settings).model_copy(deep=True)
        if self.settings.fault == 'timeout':
            if self.settings.response is not None:
                raise ValueError('Synthetic timeout has no response content')
        else:
            if not self.settings.response or len(self.settings.response) > 2048:
                raise ValueError('Synthetic invalid JSON requires explicit bounded response content')
            try:
                json.loads(self.settings.response)
            except (ValueError, TypeError):
                pass
            else:
                raise ValueError('Synthetic invalid_json content must actually be malformed JSON')
        self._settings_sha256 = task_digest(self.settings.model_dump(mode='json'))
        self._calls = 0
        self._prompt_sha256 = None
        self._lock = RLock()

    def request_policy(self):
        return {'schema_version': 'model-request-policy.v1', 'max_requests_per_call': 1,
            'internal_retries': 0, 'origin': 'synthetic', 'transport': 'local_script',
            'network_enabled': False, 'fault_settings_sha256': self._settings_sha256}

    def chat_with_metadata(self, messages, temperature=0):
        if (not isinstance(messages, list) or not messages or temperature != 0
                or any(not isinstance(message, dict) or set(message) != {'role', 'content'}
                    or message['role'] not in {'system', 'user', 'assistant'}
                    or not isinstance(message['content'], str) for message in messages)):
            raise ValueError('Synthetic model fault requires explicit original deterministic strategy messages')
        with self._lock:
            if task_digest(self.settings.model_dump(mode='json')) != self._settings_sha256:
                raise TaskConflict('Synthetic model fault settings changed')
            if self._calls:
                raise TaskConflict('Synthetic model fault was already consumed; no automatic retry')
            self._calls = 1
            self._prompt_sha256 = task_digest(messages)
        if self.settings.fault == 'timeout':
            raise TimeoutError('Explicit synthetic model-selection timeout')
        return ScriptedModelFaultResponse(self.settings.response, {'origin': 'synthetic',
            'case_id': self.settings.case_id, 'fault': self.settings.fault, 'network_requests': 0,
            'usage_metadata': {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}})

    def evidence(self):
        with self._lock:
            return {'schema_version': 'scripted-model-fault-evidence.v1', 'origin': 'synthetic',
                'settings': deepcopy(self.settings.model_dump(mode='json')),
                'settings_sha256': self._settings_sha256, 'script_calls': self._calls,
                'prompt_sha256': self._prompt_sha256, 'network_requests': 0, 'real_model_calls': 0,
                'limitations': ['Local fault injection only; it does not demonstrate real endpoint timeout or model behavior.']}


def build_scripted_model_fault_client(settings):
    """Construct only the explicitly supplied local script, without loading credentials."""
    return ScriptedModelFaultClient(settings)
