"""Scoped CP03E/CP03X transport and launch wiring over native mechanisms.

Original CP03 source/transport files remain frozen. No calls occur at import
or input compilation; the formal client factory requires a signed batch.
"""
import atexit
from pathlib import Path
from unittest.mock import patch

from integration.capstone_mechanism_native import MeteredCP03Transport

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'Capstone报告/验证体系'
MASTER = BASE / '实验/2026-11-13_总实验收尾'
DIRECTORIES = {'CP03E': BASE / '实验/2026-11-13_CP03E另三组宏观',
               'CP03X': BASE / '实验/2026-11-13_CP03X宏观扩样'}


def read(path):
    import json
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_master(directory):
    directory = Path(directory).resolve()
    matches = [batch for batch, path in DIRECTORIES.items() if path.resolve() == directory]
    if len(matches) != 1:
        raise ValueError('Unregistered macro batch directory')
    batch, = matches
    if (MASTER / 'PAID_HALT.json').exists():
        raise ValueError('Global paid stop is active; no macro client or request')
    auth = read(MASTER / 'authorization.json')
    if (sha(BASE / '2026-11-13_GOAL_Capstone剩余实验与结果收尾.md') != auth['goal_sha256']
            or auth['new_attempt_cap'] != 3488):
        raise ValueError('Master authorization differs from activated scope')
    p = read(directory / 'protocol.json')
    allocation = next(b for b in auth['budgets'] if b['batch'] == batch)
    if p['batch'] != batch or not 0 < p['max_calls'] <= allocation['remaining_max']:
        raise ValueError('Macro batch exceeds its independent allocation')
    for key in ['code_sha256', 'source_sha256']:
        for name, digest in p[key].items():
            if sha(ROOT / name) != digest:
                raise ValueError('Frozen macro dependency changed: ' + name)
    return p


def paid_stop(directory, reason):
    import json
    if not (MASTER / 'PAID_HALT.json').exists():
        MASTER.mkdir(parents=True, exist_ok=True)
        with (MASTER / 'PAID_HALT.json').open('x', encoding='utf-8') as stream:
            json.dump({'batch_directory': str(directory), 'reason': reason,
                       'automatic_resume': False}, stream, ensure_ascii=False, indent=2)


def assert_transport_open(client):
    for root in [client._chat_model.root_client, client._chat_model.root_async_client]:
        closed = getattr(root, 'is_closed', None)
        closed = closed() if callable(closed) else closed
        if closed is not False:
            raise RuntimeError('Cannot prove macro transport open; do not reserve a call')


class FinishMeteredTransport(MeteredCP03Transport):
    """Same attempt semantics, with an independent correctly named ledger."""
    def __init__(self, client, *, directory, chain_id, protocol_sha256, cap, max_chain_calls):
        from src.coordination.tasks import TaskStore
        from src.coordination.model_budget import ModelCallBudget
        p = check_master(directory)
        assert p['max_calls'] == cap
        assert_transport_open(client)
        self.client, self.directory, self.chain_id = client, Path(directory), chain_id
        self.protocol_sha256, self.count = protocol_sha256, 0
        self.max_chain_calls = max_chain_calls
        self.store = TaskStore(run_id=p['run_id'], organization_ids=['experiment-host'],
                               path=self.directory / 'run/budget.sqlite')
        self.budget = ModelCallBudget(store=self.store, budget_id=p['budget_id'], max_calls=cap)
        atexit.register(self.store.close)

    def chat_with_metadata(self, messages, *, temperature):
        check_master(self.directory)
        try:
            assert_transport_open(self.client)
            return super().chat_with_metadata(messages, temperature=temperature)
        except Exception as exc:
            paid_stop(self.directory, 'macro_request_or_transport_stop:' + type(exc).__name__)
            raise


def build_bundle(directory, config):
    """Compile the already supported Macau infrastructure extension only."""
    import integration.capstone_mechanism_native as native
    import integration.contractor_tender_development as development
    original = development._write_launch_files
    def launch_files(path, **kwargs):
        kwargs['agent_client_factory'] = 'integration.capstone_finish_native:build_agent_client'
        kwargs['readme_override'] = ('Prepared input only. CP03E/CP03X requires its independently sealed authorization, '
            'unhalted master scope and named batch ledger. Do not bypass the scoped runner.')
        return original(path, **kwargs)
    with patch.object(development, '_write_launch_files', side_effect=launch_files):
        return native.build_bundle(directory, config)


def build_agent_client(*, configuration, **kwargs):
    from integration.module_host import GbaModuleHostConfiguration
    import integration.capstone_mechanism_native as native
    config = GbaModuleHostConfiguration.model_validate(configuration).model_dump(mode='json')
    control = config['settings']['cp03_control']
    directory = Path(control['batch_directory'])
    p = check_master(directory)
    auth = read(directory / 'authorization.json')
    if auth['batch'] != p['batch'] or auth['master_authorization_sha256'] != sha(MASTER / 'authorization.json'):
        raise ValueError('Explicit macro batch/master receipt is missing or changed')
    # The native factory still verifies chain/arm, assigned output directory,
    # per-chain limit and protocol before constructing any actual transport.
    with patch.object(native, 'MeteredCP03Transport', FinishMeteredTransport):
        return native.build_agent_client(configuration=config, **kwargs)
