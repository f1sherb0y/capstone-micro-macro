"""Explicit CP03 serial runner, with one batch ledger and no replay/retries."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from capstone_cp_common_20261112 import CP03, ROOT, read, sha


def verify_frozen():
    p = read(CP03 / 'protocol.json')
    for key in ['code_sha256', 'source_sha256']:
        for name, expected in p[key].items():
            if sha(ROOT / name) != expected:
                raise ValueError('CP03 frozen dependency changed: ' + name)
    for job in p['jobs']:
        if sha(ROOT / job['config_path']) != job['config_sha256']:
            raise ValueError('CP03 chain configuration changed')
    return p


def run(authorized_cap=None):
    if type(authorized_cap) is not int or authorized_cap != 324:
        raise ValueError('CP03 requires its explicitly frozen324 first-attempt scope; old hypothetical retry caps are invalid')
    p = verify_frozen()
    preflight = read(CP03 / 'preflight.json')
    if not preflight['passed']:
        raise ValueError('CP03 zero-call source/interface preflight required')
    if (CP03 / 'run').exists() or (CP03 / 'authorization.json').exists():
        raise ValueError('Existing/unknown CP03 run; no automatic resume/replay')
    from integration.capstone_mechanism_native import build_bundle
    from integration.contractor_tender_development import verify_bundle
    from integration.capstone_mechanism_results import verify as verify_chain
    # Compile ALL requested sources before any request is authorized/constructed.
    prepared = []
    for job in p['jobs']:
        directory = CP03 / 'chains' / job['chain_id']
        inputs = directory / 'input'
        if not inputs.exists():
            build_bundle(inputs, read(ROOT / job['config_path']))
        verify_bundle(inputs)
        prepared.append((job, directory, inputs))
    (CP03 / 'run').mkdir()
    (CP03 / 'authorization.json').write_text(json.dumps({'max_calls': 324,
        'protocol_sha256': sha(CP03 / 'protocol.json'), 'first_priority': True,
        'automatic_resume': False, 'macro_final_retries': 0}, indent=2), encoding='utf-8')
    outcomes = []
    for job, directory, inputs in prepared:
        command = [sys.executable, '-m', 'integration.run', '--input', str(inputs / 'macro-request.json'),
                   '--output', str(directory / 'runtime'), '--llm', '--input-format', 'gba_request',
                   '--macro-mode', 'gba_v1_module', '--allow-native-project-generation',
                   '--allow-native-initial-projects-with-generation',
                   '--agent-client-factory', 'integration.capstone_mechanism_native:build_agent_client',
                   '--agent-client-config', str(inputs / 'native-host.json'),
                   '--module-assembly-hook', 'integration.origin_model_lifecycle:configure_assembly',
                   '--module-assembly-config', str(inputs / 'assembly-host.json')]
        (directory / 'command.json').write_text(json.dumps(command, indent=2), encoding='utf-8')
        with (directory / 'stdout.log').open('xb') as out, (directory / 'stderr.log').open('xb') as err:
            result = subprocess.run(command, cwd=ROOT, stdout=out, stderr=err)
        (directory / 'exit.json').write_text(json.dumps({'exit_code': result.returncode}), encoding='utf-8')
        outcome = {'chain_id': job['chain_id'], 'exit_code': result.returncode, 'verification': None}
        try:
            if result.returncode != 0 or (CP03 / 'run/HALT.json').exists():
                raise ValueError('Actual chain/provider stopped')
            outcome['verification'] = verify_chain(directory)
        except Exception as exc:
            outcome['verification_error'] = type(exc).__name__ + ': ' + str(exc)
            halt = CP03 / 'run/HALT.json'
            if not halt.exists():
                halt.write_text(json.dumps({'chain_id': job['chain_id'], 'reason': outcome['verification_error'], 'automatic_resume': False}), encoding='utf-8')
            outcomes.append(outcome)
            (CP03 / 'run/outcomes.json').write_text(json.dumps(outcomes, ensure_ascii=False, indent=2), encoding='utf-8')
            raise RuntimeError('CP03 stopped; preserve failed chain, do not replay') from exc
        outcomes.append(outcome)
        (CP03 / 'run/outcomes.json').write_text(json.dumps(outcomes, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorize-max-calls', type=int)
    run(parser.parse_args().authorize_max_calls)
