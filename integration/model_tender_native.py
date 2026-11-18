"""Explicit model-backed tender composition with original native background routes.

Only the configured Contractor actions use the model host. Other routes remain
the declared native behavior; their presence is not micro/model coverage. The
existing offline factory and its guard are unchanged.
"""
import asyncio
from pathlib import Path

from integration.agent_client import GbaV1AgentClient
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension
from integration.native_routes import NativeRoutes, NativeRouteAgentClient, NativeRouteSettings
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.model_strategy import model_client_request_policy
from src.coordination.tasks import TaskConflict, task_digest
from src.llm_client import OpenAICompatibleClient


class ModelTenderNativeSettings(StrictRecord):
    native: NativeRouteSettings
    expected_provider: TextId
    expected_model: TextId
    response_cache_directory: str | None = None
    max_paid_attempts: int = 4


def _close_transport(client):
    """Release both SDK transports owned by the existing synchronous wrapper."""
    from integration.model_client import CachedModelClient
    if isinstance(client, CachedModelClient):
        client = client.client
    try:
        client._chat_model.root_client.close()
    finally:
        asyncio.run(client._chat_model.root_async_client.close())


class ModelTenderAgentClient(NativeRouteAgentClient):
    VERSION = 'model-tender-native-composition.v1'

    def __init__(self, *, model_client, **kwargs):
        self.tender_model_client = model_client
        self._model_policy = model_client_request_policy(model_client)
        if kwargs['versions']['model'] != 'tender-model:' + task_digest(self._model_policy):
            raise ValueError('Model tender client requires its actual bounded transport version')
        self._model_closed = False
        super().__init__(**kwargs)

    def close(self):
        try:
            super().close()
        finally:
            if not self._model_closed:
                self._model_closed = True
                _close_transport(self.tender_model_client)


def build_agent_client(*, request, output_directory, offline, configuration):
    """CLI factory for explicit LLM mode; construction makes no paid request.

    Credentials are loaded only on this explicitly selected path, through the
    existing client. Its actual provider/model must match the declared values.
    The journal, model transport and budgets belong to this one run.
    """
    if offline is not False:
        raise ValueError('Model tender composition requires explicit LLM mode')
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise ValueError('Use the synchronous module entrypoint for this model transport owner')
    config = GbaModuleHostConfiguration.model_validate(configuration)
    settings = ModelTenderNativeSettings.model_validate(config.settings)
    routes = NativeRoutes(request=request, settings=settings.native)
    directory = Path(output_directory)
    model = OpenAICompatibleClient.from_env(model=settings.expected_model)
    try:
        if settings.response_cache_directory is not None:
            from integration.lifecycle_model_cache import LifecycleModelCache
            if not 1 <= settings.max_paid_attempts <= 32:
                raise ValueError('Lifecycle case allows one to 32 explicitly configured retained API attempts')
            model = LifecycleModelCache(model, settings.response_cache_directory, settings.max_paid_attempts)
        policy = model_client_request_policy(model)
        if policy.get('provider') != settings.expected_provider or policy.get('model') != settings.expected_model:
            raise TaskConflict('Actual model provider/name differs from the explicit tender configuration')
        from gba_construction_sim.backend.agents.contracts import AGENT_MODULE_CONTRACT_VERSION
        versions = {'client': ModelTenderAgentClient.VERSION + ':' + NativeRoutes.VERSION,
            'skill': 'native-role-behaviors.v1', 'prompt': 'host-bound-tender-options.v1',
            'contract': AGENT_MODULE_CONTRACT_VERSION, 'method': 'native-rule-based.v1',
            'model': 'tender-model:' + task_digest(policy), 'strategy': 'explicit-model-tender-native-background.v1'}
        client = ModelTenderAgentClient(model_client=model,
            run_id=settings.native.run_id or directory.resolve().name, organization_roles=routes.roles,
            proposal_handlers={key: routes.propose for key in routes._proposals
                if not (settings.native.mixed_owner_invitation_scope and key == ('Owner', 'select_tender_invitees'))
                and not (settings.native.mixed_qs_learning_scope and key == ('QS', 'decide_monthly_operation'))},
            decision_handler=routes.decide, versions=versions,
            inbox_path=directory / 'observations.json', task_path=directory / 'tasks.sqlite')
        client.native_routes = routes
        if not isinstance(client, GbaV1AgentClient):
            raise TypeError('Original module client required')
        return client
    except Exception:
        _close_transport(model)
        raise


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    """Attach the original native routes, then the configured model tender host."""
    from integration.contractor_tender_module_host import configure_assembly as configure_tender
    if offline is not False or not isinstance(assembly.client, ModelTenderAgentClient):
        raise ValueError('Model tender assembly requires its original explicit LLM client')
    routes = assembly.client.native_routes
    routes.attach(assembly)
    extension = configure_tender(assembly=assembly, request=request, output_directory=output_directory,
        offline=offline, configuration=configuration)

    def evidence():
        return {'schema_version': ModelTenderAgentClient.VERSION,
            'native_routes': routes.evidence(), 'tender': extension.evidence()}

    return GbaModuleHostExtension(version=ModelTenderAgentClient.VERSION, evidence=evidence,
        close=extension.close, writer_guard=extension.writer_guard)
