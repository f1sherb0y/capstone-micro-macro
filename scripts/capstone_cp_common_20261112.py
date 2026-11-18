"""Shared paths and reversible isolation for the zero-provider CP preparation."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
PACK = ROOT / 'Capstone报告/验证体系/实验/2026-11-12_CP零调用准备'
PARENT = ROOT / 'Capstone报告/验证体系/实验/2026-11-09_24项目扩样验证'
CP00 = PACK / 'CP00'
CP01 = PACK / 'CP01'
CP02 = PACK / 'CP02'
CP03 = PACK / 'CP03'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    """Only create a new artifact or reproduce exactly the same preparation."""
    path = Path(path)
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists():
        if path.read_text(encoding='utf-8') != text:
            raise ValueError('Refuse to replace a changed prepared artifact: ' + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


@contextmanager
def no_provider():
    """Block socket connections and both actual environment client factories."""
    import src.llm_client as llm
    counts = {'network_attempts': 0, 'paid_client_constructions': 0}

    def block_network(*args, **kwargs):
        counts['network_attempts'] += 1
        raise AssertionError('No network in CP preparation')

    def block_client(*args, **kwargs):
        counts['paid_client_constructions'] += 1
        raise AssertionError('No paid client in CP preparation')

    with patch.object(socket.socket, 'connect', block_network), \
         patch.object(socket.socket, 'connect_ex', block_network), \
         patch.object(llm.OpenAICompatibleClient, 'from_env', side_effect=block_client):
        yield counts
    assert not any(counts.values()), counts


@contextmanager
def engine_binding(out, verify):
    import run_capstone_v2_5_20261109 as engine
    old = engine.OUT, engine.verify_frozen
    engine.OUT, engine.verify_frozen = Path(out), verify
    try:
        yield engine
    finally:
        engine.OUT, engine.verify_frozen = old


def verify_parent():
    from run_capstone_expansion_20261109 import verify_frozen
    return deepcopy(verify_frozen())


def verify_input_protocol(out):
    protocol = read(out / 'protocol.json')
    for file, key in [('windows.json', 'windows_sha256'), ('targets.json', 'targets_sha256'),
                      ('sample_manifest.json', 'manifest_sha256')]:
        if sha(out / file) != protocol[key]:
            raise ValueError('Frozen CP input changed: ' + file)
    for file, digest in protocol['code_sha256'].items():
        if sha(ROOT / file) != digest:
            raise ValueError('Frozen CP implementation changed: ' + file)
    for file, digest in protocol['source_sha256'].items():
        if sha(ROOT / file) != digest:
            raise ValueError('Frozen CP source changed: ' + file)
    return protocol
