"""Explicit experimental lifecycle input adapter and batch-metered transport.

Builds sources only unless the formal run factory is explicitly invoked with
the CP03 batch authorization. Reuses native authority, sources and processors.
"""
import atexit
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.coordination.tasks import task_digest

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def allowed_model_options(config):
    from integration.tender_model_development import TenderModelDevelopmentSettings
    model = TenderModelDevelopmentSettings.model_validate(config['model_options'])
    cap = config.get('api_total_attempt_cap', 4)
    if type(cap) is not int or not 1 <= cap <= 32 or model.max_calls > cap:
        raise ValueError('Explicit experimental case cap1..32 required')
    return model


def build_bundle(directory, config):
    """Prepare a new input bundle, without executing the macro engine."""
    import integration.case_library_lifecycle as library
    import integration.origin_model_lifecycle as origin
    from integration.contractor_tender_development import _write_launch_files
    arm = config['research_arm']
    if arm not in {'R', 'S', 'D3', 'S4'}:
        raise ValueError('Unknown CP03 arm')
    expected_strategy = 'organization_discussion' if arm == 'D3' else 'single_agent'
    if config['model_options']['strategy'] != expected_strategy:
        raise ValueError('CP03 arm differs from its native dispatch')
    old_read, old_configure = library.read, origin.configure_model_inputs

    def base_read(path):
        value = old_read(path)
        if Path(path).resolve() == (ROOT / config['base_config']).resolve():
            value = deepcopy(value)
            value['api_total_attempt_cap'] = config['api_total_attempt_cap']
            value['contract_duration'] = config['contract_duration']
        return value

    def configure(directory, host, native, base):
        host, native = old_configure(directory, host, native, base)
        app = host['settings']['tender']['settings']['source_settings']['application_settings']['owner_contractor']['contractor']
        if arm in {'R', 'S4'}:
            app['model_host_factory'] = 'integration.capstone_mechanism_controls:build_model_host'
            app['model_host_settings']['research_control_arm'] = arm
        native['settings']['cp03_control'] = deepcopy(config['cp03_control'])
        return host, native

    def write_launch(directory, **kwargs):
        kwargs.update(offline=False, assembly_hook='integration.origin_model_lifecycle:configure_assembly',
            agent_client_factory='integration.capstone_mechanism_native:build_agent_client',
            allow_native_project_generation=True, allow_native_initial_projects_with_generation=True,
            source_note='CP03 controlled mechanism comparison. Public case background plus explicit synthetic HKD initial assumptions. No outcomes prefilled.',
            readme_override='CP03 input only. Formal run requires its sealed batch authorization and shared call budget; do not use an unmetered factory.')
        return _write_launch_files(directory, **kwargs)

    with patch.object(library, 'read', base_read), patch.object(origin, 'model_options', allowed_model_options), \
         patch.object(origin, 'configure_model_inputs', configure), patch.object(library, '_write_launch_files', write_launch):
        return library.build_bundle(directory, config)


class DisabledRuleTransport:
    """An explicit zero-request backend, used only for rule arm R."""
    def __init__(self, provider, model):
        self.provider, self.model = provider, model
        async def close_async():
            return None
        self._chat_model = SimpleNamespace(root_client=SimpleNamespace(close=lambda: None),
                                           root_async_client=SimpleNamespace(close=close_async))

    def request_policy(self):
        return {'schema_version': 'model-request-policy.v1', 'max_requests_per_call': 1,
                'internal_retries': 0, 'provider': self.provider, 'model': self.model,
                'backend': 'disabled_rule_control_no_provider'}

    def chat_with_metadata(self, *args, **kwargs):
        raise AssertionError('Rule arm must never request a model')


class MeteredCP03Transport:
    def __init__(self, client, *, directory, chain_id, protocol_sha256, cap, max_chain_calls):
        from src.coordination.tasks import TaskStore
        from src.coordination.model_budget import ModelCallBudget
        self.client, self.directory, self.chain_id = client, Path(directory), chain_id
        self.protocol_sha256, self.count = protocol_sha256, 0
        self.max_chain_calls = max_chain_calls
        self.store = TaskStore(run_id='capstone-CP03-20261112', organization_ids=['experiment-host'],
                               path=self.directory / 'run/budget.sqlite')
        self.budget = ModelCallBudget(store=self.store, budget_id='CP03-independent-firsts', max_calls=cap)
        atexit.register(self.store.close)

    def __getattr__(self, name):
        return getattr(self.client, name)

    def request_policy(self):
        return {**self.client.request_policy(), 'cp03_protocol_sha256': self.protocol_sha256,
                'cp03_chain_id': self.chain_id, 'batch_cap': self.budget.max_calls}

    def chat_with_metadata(self, messages, *, temperature):
        import hashlib
        directory = self.directory
        if (directory / 'run/HALT.json').exists():
            raise RuntimeError('CP03 batch halted; no further calls')
        if hashlib.sha256((directory / 'protocol.json').read_bytes()).hexdigest() != self.protocol_sha256:
            raise ValueError('CP03 protocol changed during request')
        if self.count >= self.max_chain_calls:
            halt = directory / 'run/HALT.json'
            halt.parent.mkdir(parents=True, exist_ok=True)
            with halt.open('x', encoding='utf-8') as stream:
                json.dump({'reason': 'unexpected_extra_decision_window', 'chain_id': self.chain_id}, stream)
            raise ValueError('Unexpected additional model window; stop before paying')
        self.count += 1
        slot = self.chain_id + f':request-{self.count:02d}'
        if not self.budget.reserve(slot, 1):
            raise ValueError('CP03 batch request cap exhausted')
        path = directory / 'run/provider_attempts' / self.chain_id / f'{self.count:02d}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {'call_id': slot, 'status': 'reserved', 'messages': messages,
                  'temperature': temperature, 'request_sha256': task_digest(messages)}
        try:
            with path.open('x', encoding='utf-8') as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
            self.budget.begin_attempt(slot)
            record['status'] = 'started'
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            response = self.client.chat_with_metadata(messages, temperature=temperature)
            record.update(status='returned', raw_content=response.content, metadata=response.metadata)
            return response
        except Exception as exc:
            record.update(status='provider_unknown_attempt' if getattr(exc, 'status_code', None) is None else 'provider_failed',
                          error_type=type(exc).__name__, http_status=getattr(exc, 'status_code', None))
            halt = directory / 'run/HALT.json'
            if not halt.exists():
                with halt.open('x', encoding='utf-8') as stream:
                    json.dump({'call_id': slot, 'reason': record['status'], 'automatic_resume': False}, stream)
            raise
        finally:
            self.budget.finish(slot)
            # Original request and every returned/error response remain saved.
            if path.exists():
                path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')


def build_agent_client(*, configuration, **kwargs):
    """Only formal entry: authorization validated BEFORE constructing a client."""
    from integration.module_host import GbaModuleHostConfiguration
    import integration.model_tender_native as original
    import hashlib
    config = GbaModuleHostConfiguration.model_validate(configuration).model_dump(mode='json')
    control = config['settings'].pop('cp03_control')
    directory = Path(control['batch_directory'])
    if not (directory / 'authorization.json').is_file():
        raise ValueError('CP03 authorization file required before any client construction')
    protocol = read(directory / 'protocol.json')
    auth = read(directory / 'authorization.json')
    digest = hashlib.sha256((directory / 'protocol.json').read_bytes()).hexdigest()
    if auth['protocol_sha256'] != digest or auth['max_calls'] != protocol['max_calls']:
        raise ValueError('CP03 explicit batch authorization mismatch')
    if (directory / 'run/HALT.json').exists():
        raise ValueError('CP03 stopped; no automatic resume')
    chain = next(j for j in protocol['jobs'] if j['chain_id'] == control['chain_id'])
    if chain['arm'] != control['arm']:
        raise ValueError('CP03 chain arm mismatch')
    expected_output = directory / 'chains' / control['chain_id'] / 'runtime'
    if Path(kwargs['output_directory']).resolve() != expected_output.resolve():
        raise ValueError('CP03 formal factory requires its assigned isolated chain output')
    factory = original.OpenAICompatibleClient.from_env

    def bounded_factory(*, model):
        if control['arm'] == 'R':
            return DisabledRuleTransport(config['settings']['expected_provider'], model)
        client = factory(model=model)
        policy = client.request_policy()
        if policy['internal_retries'] != 0:
            raise ValueError('No hidden retries in CP03')
        client._chat_model.max_tokens = 4096
        return MeteredCP03Transport(client, directory=directory, chain_id=control['chain_id'],
                                    protocol_sha256=digest, cap=protocol['max_calls'],
                                    max_chain_calls=chain['expected_max_provider_calls'])
    with patch.object(original.OpenAICompatibleClient, 'from_env', side_effect=bounded_factory):
        return original.build_agent_client(configuration=config, **kwargs)
