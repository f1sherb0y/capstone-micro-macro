"""Explicit trusted-host decision components; no implicit model construction."""
from dataclasses import dataclass
from typing import Callable, Literal
import re


@dataclass(frozen=True)
class DecisionStrategyOutcome:
    result: object
    evidence: dict


@dataclass(frozen=True)
class DecisionStrategyBinding:
    """Bind a real executor to explicit action and strategy identities.

    execute receives context, action_input, registration, reading and processor
    as named arguments. Like a registered processor, it is trusted application
    code and must retain the action's business checks. A prompt/model response
    cannot register an executor or change its supported actions. Model adapters
    must independently validate proposals before returning them to the runner.
    Optional prepare_invocation receives the original context/input/registration
    and a reading that cannot calculate, before a durable worker starts.
    """
    strategy: Literal['single_agent','organization_discussion']
    component_id: str
    version: str
    action_ids: frozenset[str]
    execute: Callable
    model_version: str | None = None
    configuration_sha256: str | None = None
    prepare_invocation: Callable | None = None

    def __post_init__(self):
        if self.strategy not in {'single_agent','organization_discussion'}:
            raise ValueError('Only declared action decision strategies may be bound')
        if any(not isinstance(value,str) or not value.strip() for value in (self.component_id,self.version)):
            raise ValueError('Actual component and strategy version identities are required')
        if (not isinstance(self.action_ids,frozenset) or not self.action_ids
                or any(not isinstance(action,str) or not action.strip() for action in self.action_ids)
                or not callable(self.execute)):
            raise ValueError('Explicit supported actions and an actual callable executor are required')
        if self.prepare_invocation is not None and not callable(self.prepare_invocation):
            raise ValueError('Optional invocation preparation must be actual trusted host code')
        if self.model_version is not None and (not isinstance(self.model_version,str) or not self.model_version.strip()):
            raise ValueError('Model version must be explicit when supplied')
        if self.configuration_sha256 is not None and (
                not isinstance(self.configuration_sha256,str) or re.fullmatch(r'[0-9a-f]{64}',self.configuration_sha256) is None):
            raise ValueError('Strategy configuration digest must be an exact SHA256')

    def evidence(self, *, status):
        result={'strategy':self.strategy,'component_id':self.component_id,'version':self.version,
                'model_version':self.model_version,'status':status}
        if self.configuration_sha256 is not None: result['configuration_sha256']=self.configuration_sha256
        if self.prepare_invocation is not None: result['invocation_preparation']='configured'
        return result
