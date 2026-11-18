"""Advance one explicitly supplied synthetic procurement stage without replay."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.lifecycle_v2_offline import (
    _CONFIGURED_CASES, _check_configured_result, _check_durable_result, _prepare, run_v2_offline,
)
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.coordination.tasks import task_digest


_ORDER = (
    'v2-owner-tender-publication', 'v2-received-tender-bid', 'v2-received-bids-evaluation',
    'v2-selected-evaluation-award', 'v2-received-award-formation',
)
_CONTINUING_CHOICES = ('publish_package', 'submit_bid', 'evaluate', 'accept', 'accept')
_ROOT = Path(__file__).resolve().parents[1]
_LIMITATIONS = [
    'Synthetic local decisions and declared reception only; no formal submission or receipt is generated.',
    'Independent registration and current authorized history inputs are required for each continuation.',
    'Formal effectiveness, resource effects and complete V2/PLAN acceptance remain separate requirements.',
]


def _read_artifact(path, expected_sha, *, output_only=False):
    path = Path(path).resolve()
    allowed = ('output/integration',) if output_only else ('tests/fixtures/roles', 'output/integration')
    if not any(path.is_relative_to(_ROOT / directory) for directory in allowed):
        raise ValueError('V2 chain artifact escapes its repository source directories')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('V2 chain artifact changed its recorded raw SHA')
    _, value = parse_input_json(raw)
    return path, value


def _check_stage_result(result, case, step):
    request, configuration = step['request'], step['configuration']
    declared = case['steps'][0]
    observed = result.get('result', {})
    payload = observed.get('payload', {})
    if (result.get('request_sha256') != task_digest(request)
            or result.get('configuration') != {'host_id': configuration['host_id'],
                'version': configuration['version'], 'sha256': task_digest(configuration)}
            or result.get('macro_execution') != 'not_performed'
            or observed.get('kind') != declared['expected_kind']
            or payload.get('choice') != declared['expected_choice']
            or any(payload.get(key) != value for key, value in step['expected_refs'].items())):
        raise ValueError('V2 chain result differs from its original invocation, configuration or branch')
    route = _CONFIGURED_CASES.get(case['case_id'])
    if route is None:
        _check_durable_result(result, step, action_id='OWN-A09', role='Owner', result_table='owner_tender_results')
    else:
        _check_configured_result(result, step, route)


def _check_previous_link(step, previous):
    """Require a declared reception of this exact preceding durable output."""
    source = step['configuration']['settings']['source_settings']
    entries = source.get('received_bids')
    if entries is None:
        entries = [{'history': source['owner_history'], 'registration': source['registration']}]
    evidence = previous['execution_evidence']
    matches = [entry for entry in entries if entry['history']['identity'] == evidence['identity']]
    if len(matches) != 1:
        raise ValueError('V2 continuation must receive its preceding original task exactly once')
    entry = matches[0]
    registration = entry['registration']
    original = previous['execution_evidence']['saved_audit']
    current = step['request']['context']
    history = entry['history']['request']['context']
    if (registration['source_identity'] != evidence['identity']
            or registration['source_record_sha256'] != evidence['record_sha256']
            or registration['source_result_sha256'] != task_digest(previous['result'])
            or current['run_id'] != previous['run_id'] or history['run_id'] != previous['run_id']):
        raise ValueError('V2 continuation substitutes its preceding result or source history')
    if 'source_audit_reading_sha256' in registration:
        witness = evidence.get('bid_source_witness', {})
        if (witness.get('status') != 'captured'
                or registration['source_snapshot_sha256'] != witness['source_snapshot_sha256']
                or registration['source_audit_reading_sha256'] != task_digest(original['reading'])):
            raise ValueError('V2 bid continuation substitutes original snapshot or audit reading')
    elif registration['source_reading_sha256'] != evidence['source_reading_sha256']:
        raise ValueError('V2 continuation substitutes original source reading')


def _read_previous_state(path, expected_sha):
    _, state = _read_artifact(path, expected_sha, output_only=True)
    if (set(state) != {'schema_version', 'origin', 'run_id', 'status', 'stages', 'remaining_requirements'}
            or state['schema_version'] != 'lifecycle-v2-chain-state.v1' or state['origin'] != 'synthetic'
            or state['status'] != 'awaiting_next_stage_inputs'
            or not isinstance(state['stages'], list) or not 1 <= len(state['stages']) < len(_ORDER)):
        raise ValueError('V2 continuation requires an actual unfinished chain state, not a plan or failed attempt')
    last_result, last_step = None, None
    for index, stage in enumerate(state['stages']):
        if set(stage) != {'case_path', 'case_sha256', 'result_path', 'result_file_sha256', 'result_sha256'}:
            raise ValueError('V2 recorded stage changes its source bindings')
        case_path, _ = _read_artifact(stage['case_path'], stage['case_sha256'])
        _, sha, case, steps = _prepare(case_path)
        if sha != stage['case_sha256'] or case['case_id'] != _ORDER[index] or len(steps) != 1:
            raise ValueError('V2 recorded stages omit, repeat or reorder an original action')
        _, result = _read_artifact(stage['result_path'], stage['result_file_sha256'], output_only=True)
        _check_stage_result(result, case, steps[0])
        if (result['run_id'] != state['run_id'] or task_digest(result) != stage['result_sha256']
                or result['result']['payload']['choice'] != _CONTINUING_CHOICES[index]):
            raise ValueError('V2 preceding stage is not the original continuing branch')
        if last_result is not None:
            _check_previous_link(steps[0], last_result)
            _check_context_order(last_step, steps[0])
        last_result, last_step = result, steps[0]
    return state, last_result, last_step


def _check_context_order(previous, current):
    before, after = previous['request']['context'], current['request']['context']
    if (before['run_id'] != after['run_id'] or before['scope'] != after['scope']
            or before['business_time']['clock_ref'] != after['business_time']['clock_ref']
            or before['business_time']['offset'] > after['business_time']['offset']
            or before['operation_id'] == after['operation_id']):
        raise ValueError('V2 continuation changes run/scope, reverses time or repeats an operation')


def advance_v2_chain(*, case_path, output_directory, previous_state_path=None,
        previous_state_sha256=None, execute=False):
    """Advance one stage; caller supplies new receiver facts between stages."""
    if type(execute) is not bool or (previous_state_path is None) != (previous_state_sha256 is None):
        raise ValueError('V2 chain requires explicit execution mode and a pinned optional previous state')
    state, previous, previous_step = None, None, None
    if previous_state_path is not None:
        state, previous, previous_step = _read_previous_state(previous_state_path, previous_state_sha256)
    index = len(state['stages']) if state is not None else 0
    path, sha, case, steps = _prepare(case_path)
    if not any(path.is_relative_to(_ROOT / directory) for directory in ('tests/fixtures/roles', 'output/integration')):
        raise ValueError('V2 chain case must stay in repository fixture or integration output directories')
    if len(steps) != 1 or case.get('case_id') != _ORDER[index]:
        raise ValueError('V2 chain requires exactly its next configured stage')
    if previous is not None:
        _check_previous_link(steps[0], previous)
        _check_context_order(previous_step, steps[0])
    directory = Path(output_directory).resolve()
    if not directory.is_relative_to(_ROOT / 'output/integration'):
        raise ValueError('V2 chain output must stay in repository integration output')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v2-chain-plan.v1', 'origin': 'synthetic',
        'run_id': case['run_id'], 'stage_index': index, 'case_path': str(path), 'case_sha256': sha,
        'previous_state_path': str(Path(previous_state_path).resolve()) if state is not None else None,
        'previous_state_sha256': previous_state_sha256,
        'mode': 'execute_offline' if execute else 'plan_only', 'remaining_requirements': deepcopy(_LIMITATIONS)}
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v2-chain-attempt.v1', 'status': 'started', 'stage_index': index}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        run_v2_offline(case_path=path, output_directory=directory / 'stage', execute=True)
        result_path = directory / 'stage/step-1/result.json'
        raw = result_path.read_bytes()
        _, result = parse_input_json(raw)
        _check_stage_result(result, case, steps[0])
        # Verify the old evidence again after the new action, without executing it.
        if state is not None:
            _read_previous_state(previous_state_path, previous_state_sha256)
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError('V2 case changed while advancing its original stage')
        choice = result['result']['payload']['choice']
        status = ('branch_requires_new_decision' if choice != _CONTINUING_CHOICES[index]
            else 'local_procurement_decisions_completed' if index == len(_ORDER) - 1
            else 'awaiting_next_stage_inputs')
        next_state = {'schema_version': 'lifecycle-v2-chain-state.v1', 'origin': 'synthetic',
            'run_id': case['run_id'], 'status': status,
            'stages': deepcopy(state['stages']) if state is not None else [],
            'remaining_requirements': deepcopy(_LIMITATIONS)}
        next_state['stages'].append({'case_path': str(path), 'case_sha256': sha,
            'result_path': str(result_path), 'result_file_sha256': hashlib.sha256(raw).hexdigest(),
            'result_sha256': task_digest(result)})
        atomic_json(directory / 'state.json', next_state)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'state_saved'})
        return next_state
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed',
            'error_type': type(exc).__name__, 'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous-state', type=Path)
    parser.add_argument('--previous-state-sha256')
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    report = advance_v2_chain(case_path=args.case, output_directory=args.output,
        previous_state_path=args.previous_state, previous_state_sha256=args.previous_state_sha256,
        execute=args.execute_offline)
    print(json.dumps({'output': str(args.output), 'status': report.get('status', 'planned_not_executed')},
        ensure_ascii=False))


if __name__ == '__main__':
    main()
