"""Compose original native operations and validated external micro operations.

Native operations are declared before engine creation and invoke the original
AgentBehaviorRegistry interface with its original typed inputs and decisions.
Every external operation still uses the unchanged macro external validator.
No micro result is relabelled native, and no failure changes route ownership.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.bootstrap import enable_gba_imports
from src.coordination.tasks import task_digest

enable_gba_imports()
from gba_construction_sim.backend.agents.agent_registry import AgentBehaviorRegistry
from gba_construction_sim.backend.agents.contracts import to_jsonable
from gba_construction_sim.backend.agents.external_adapter import ExternalAgentModuleAdapter


class DeclaredNativeComposition(ExternalAgentModuleAdapter):
    VERSION = 'gba-v1-declared-native-module-composition.v1'

    def __init__(self, client, profiles, *, random_seed):
        super().__init__(client, profiles, random_seed=random_seed)
        self._native_routes = client.native_routes
        self._declared_settings_sha256 = task_digest(self._native_routes.settings.model_dump(mode='json'))
        self._declared_keys = frozenset((r.role,r.operation) for r in self._native_routes.settings.direct_native_proposals)
        self._source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self._native_calls = []
        self._validate_native_composition()

    def _validate_native_composition(self):
        from integration.agent_client import AgentClientError
        routes = self._native_routes
        if (self.client.native_routes is not routes
                or task_digest(routes.settings.model_dump(mode='json')) != self._declared_settings_sha256
                or self._declared_keys != frozenset((r.role,r.operation) for r in routes.settings.direct_native_proposals)
                or not self._declared_keys or not self._declared_keys <= routes._proposals
                or routes._sources() != routes._source_sha256
                or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != self._source_sha256):
            raise AgentClientError('Native module composition changed its original declared routes or source implementation')
        for key in self._declared_keys:
            if self.client.proposal_handlers.get(key) != routes.propose:
                raise AgentClientError('A direct native module operation cannot own an installed micro proposal handler')

    def propose(self, profile, operation, **inputs):
        from integration.agent_client import AgentClientError
        self.client._assert_runtime_ready()
        self._validate_native_composition()
        key = (profile.role,operation)
        if key not in self._declared_keys:
            return super().propose(profile,operation,**inputs)
        routes = self._native_routes
        if (routes.assembly is None or routes.assembly.engine.agent_module is not self
                or routes.assembly.engine.agents.get(profile.agent_id) is not profile
                or routes.roles.get(profile.agent_id) != profile.role):
            raise AgentClientError('Native module proposal requires its actual original engine and enterprise')
        observed = {'role':profile.role,'agent_id':profile.agent_id,'operation':operation,
            'tick':routes.assembly.engine.current_tick,'inputs_sha256':task_digest(to_jsonable(inputs)),
            'decision_source':'native_macro','micro_coverage':False}
        # This is the original module interface, not a client response and not
        # a reconstruction of selected fields. Its errors remain errors.
        result = AgentBehaviorRegistry.propose(self,profile,operation,**inputs)
        observed['result_sha256'] = task_digest(to_jsonable(result.to_event_data()))
        self._native_calls.append(observed)
        return result

    def native_composition_evidence(self):
        self._validate_native_composition()
        return {'version':self.VERSION,'source_sha256':self._source_sha256,
            'declared_settings_sha256':self._declared_settings_sha256,
            'native_proposals':[{'role':r,'operation':o} for r,o in sorted(self._declared_keys)],
            'calls':deepcopy(self._native_calls),'fallback_on_micro_failure':False,'micro_coverage':False,
            'external_validation':'All other proposals and every external final decision use the original macro validators.',
            'boundary':'Only declared original native behavior; no external response or micro result enters this route.'}
