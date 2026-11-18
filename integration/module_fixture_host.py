"""Explicit offline monthly-operation host for the original GBA module contracts."""
from pathlib import Path

from integration.module_host import GbaModuleHostConfiguration
from src.actions.contracts.common import StrictRecord, TextId


class OfflineModuleSettings(StrictRecord):
    run_id: TextId | None = None


class OfflineMonthlyHandlers:
    """Synthetic wiring answers with explicit proposal and final-decision boundaries."""
    def propose(self, request):
        from integration.agent_client import AgentClientError
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        from gba_construction_sim.backend.agents.operation_specs import get_operation_contract

        if request.operation != 'decide_monthly_operation':
            raise AgentClientError('Offline monthly fixture does not support this proposal operation')
        contract = get_operation_contract(request.operation, request.agent.role)
        if request.operation_contract != contract or not contract.actions:
            raise AgentClientError('Offline monthly fixture requires the original role operation contract')
        return AgentProposalResponseV1(request_id=request.request_id,
            action_type=contract.actions[0].action_type, accepted=True, utility=0.5, probability=0.5,
            reason='Explicit synthetic offline monthly proposal',
            data={'label': 'Offline fixture proposal', 'description': 'Synthetic monthly operation for wiring verification'})

    def decide(self, request):
        from integration.agent_client import AgentClientError
        from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1

        if (request.decision_type != 'monthly_enterprise_operation'
                or 'maintain_operations' not in request.constraints.allowed_actions):
            raise AgentClientError('Offline monthly fixture requires an explicit bounded monthly maintenance decision')
        return AgentDecisionResponseV1(request_id=request.request_id, agent_id=request.agent.agent_id,
            action_type='maintain_operations', decision=True, reason='Explicit synthetic offline final maintenance choice')


def build_agent_client(*, request, output_directory, offline, configuration=None):
    """Construct only explicitly supported offline handlers and original persistent stores."""
    if offline is not True:
        raise ValueError('Offline GBA fixture host requires --offline')
    from integration.agent_client import GbaV1AgentClient
    from gba_construction_sim.backend.agents.contracts import AGENT_MODULE_CONTRACT_VERSION
    from gba_construction_sim.backend.agents.operation_specs import get_operation_contract
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest

    request = SimulationCreateRequest.model_validate(request).model_copy(deep=True)
    if request.agent_source != 'explicit' or not request.agents:
        raise ValueError('Offline GBA fixture requires explicit original agent identities')
    settings = {} if configuration is None else GbaModuleHostConfiguration.model_validate(configuration).settings
    settings = OfflineModuleSettings.model_validate(settings)
    roles = {agent.agent_id: agent.role for agent in request.agents}
    if len(roles) != len(request.agents):
        raise ValueError('Offline GBA fixture cannot alias agent identities')
    for role in set(roles.values()):
        get_operation_contract('decide_monthly_operation', role)
    directory = Path(output_directory)
    run_id = settings.run_id if settings.run_id is not None else directory.resolve().name
    handlers = OfflineMonthlyHandlers()
    versions = {'client': 'gba-offline-monthly-host.v1', 'skill': 'offline-monthly-operation.v1',
        'prompt': 'unused-offline.v1', 'contract': AGENT_MODULE_CONTRACT_VERSION,
        'method': 'unused-offline.v1', 'model': 'offline-fixture-no-model.v1',
        'strategy': 'deterministic-monthly-maintenance.v1'}
    return GbaV1AgentClient(run_id=run_id, organization_roles=roles,
        proposal_handlers={(role, 'decide_monthly_operation'): handlers.propose for role in set(roles.values())},
        decision_handler=handlers.decide, versions=versions,
        inbox_path=directory / 'observations.json', task_path=directory / 'tasks.sqlite')
