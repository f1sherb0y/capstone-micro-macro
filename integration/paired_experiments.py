"""Declare comparable, isolated action experiments without starting a run."""
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from integration.action_model_host import ActionModelHostConfiguration
from src.actions.contracts.common import StrictRecord, TextId
from src.coordination.tasks import task_digest


Digest = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]
ExperimentId = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]*$')]


class PairedActionBasis(StrictRecord):
    """Declared frozen hashes; actual source/endpoint checks remain required."""
    action_id: TextId
    input_sha256: Digest
    authorized_facts_sha256: Digest
    authorizations_sha256: Digest
    candidate_options_sha256: Digest
    tools_sha256: Digest
    methods_sha256: Digest
    skill_sha256: Digest
    binding_version: TextId
    supported_choices: Annotated[list[TextId], Field(min_length=1)]

    @model_validator(mode='after')
    def unique_choices(self):
        if len(set(self.supported_choices)) != len(self.supported_choices):
            raise ValueError('Paired action basis repeats a supported branch')
        return self


class PairedExperimentArm(StrictRecord):
    run_id: TextId
    strategy: Literal['single_agent', 'organization_discussion']
    model_host: ActionModelHostConfiguration


class PairedExperimentConfiguration(StrictRecord):
    """Both arms use one declared comparison basis and equal adapter-call limits.

    Separate run IDs scope task, session, budget, cache and private cognition.
    The later explicit run assembler must verify these declarations against
    actual authorized sources, supported bindings and independent stores.
    A prepared configuration is not execution or evidence of an advantage.
    """
    schema_version: Literal['paired-action-experiment.v1'] = 'paired-action-experiment.v1'
    experiment_id: ExperimentId
    version: TextId
    seed: int
    scenario_sha256: Digest
    macro_version: TextId
    model_version: TextId
    model_configuration_sha256: Digest
    policy_sha256: Digest
    action_basis: Annotated[list[PairedActionBasis], Field(min_length=1)]
    arms: Annotated[list[PairedExperimentArm], Field(min_length=2, max_length=2)]

    @model_validator(mode='after')
    def comparable_arms(self):
        actions = [basis.action_id for basis in self.action_basis]
        if len(set(actions)) != len(actions):
            raise ValueError('Paired experiment repeats an action basis')
        left, right = self.arms
        if (left.run_id == right.run_id
                or {left.strategy, right.strategy} != {'single_agent', 'organization_discussion'}):
            raise ValueError('Paired experiment requires independent runs and both original strategies')
        limits = []
        for arm in self.arms:
            host = arm.model_host
            if (len(set(host.action_ids)) != len(host.action_ids)
                    or set(host.action_ids) != set(actions)):
                raise ValueError('Each model host must cover exactly the declared supported actions')
            value = host.model_dump(mode='json', exclude={'host_id', 'budget_id', 'action_ids'})
            limits.append(value)
        if limits[0] != limits[1]:
            raise ValueError('Paired model hosts require equal call, option, prompt, response and member limits')
        return self


def prepare_paired_experiment(configuration, *, output_root: Path) -> dict:
    """Return an immutable-by-hash plan; create no files, stores, hosts or clients.

    Artifact paths reserve separate namespaces only. Runtime isolation and
    measured comparability remain unverified until explicit assembly/run gates.
    Call limits count adapter attempts, not monetary cost or provider tokens.
    """
    config = PairedExperimentConfiguration.model_validate(configuration).model_copy(deep=True)
    # Revalidate even a supplied model instance after its mutable lists change.
    config = PairedExperimentConfiguration.model_validate(config.model_dump(mode='python'))
    root = Path(output_root).resolve() / config.experiment_id
    basis = config.model_dump(mode='json', exclude={'arms'})
    basis_sha256 = task_digest(basis)
    plans = []
    for arm in config.arms:
        plans.append({'run_id': arm.run_id, 'strategy': arm.strategy,
            'output_directory': (root / arm.strategy).as_posix(),
            'model_host': arm.model_host.model_dump(mode='json'),
            'comparison_basis_sha256': basis_sha256,
            'required_store_run_id': arm.run_id})
    prepared = {'schema_version': config.schema_version, 'status': 'configured_unverified',
        'configuration': config.model_dump(mode='json'),
        'configuration_sha256': task_digest(config.model_dump(mode='json')),
        'comparison_basis_sha256': basis_sha256, 'run_plans': plans,
        'limitations': ['Input, facts, permission, candidate, tool and binding hashes are declarations awaiting actual verification.',
            'Distinct namespaces do not prove independent task/session/cache/cognition stores.',
            'Equal adapter-call limits do not imply equal token usage or monetary cost.',
            'No model calls, macro execution, measured outcome or mechanism advantage.']}
    prepared['plan_sha256'] = task_digest(prepared)
    return prepared
