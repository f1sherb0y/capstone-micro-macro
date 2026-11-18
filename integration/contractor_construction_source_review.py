"""Reviewed C3 input boundaries, without inferring execution or API absence.

These records guide source assembly. They neither supply missing business
objects nor change branch acceptance, authorization or native state.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
from pathlib import Path


_MICRO = {
    'CONTRACTOR-A06': ('src/actions/roles/contractor_readiness.py', 'check_task_readiness'),
    'CONTRACTOR-A07': ('src/actions/roles/contractor_execution.py', 'execute_or_report'),
    'CONTRACTOR-A08': ('src/actions/roles/contractor_quality.py', 'inspect_and_remedy'),
}

# Keep the obligations of each private branch distinct from its formal effect.
_BRANCHES = {
    'CONTRACTOR-A06': {
        'request_release': (
            'Effective own mandate; exact current task, complete necessary gates and predecessor coverage; '
            'actual exclusive input allocations and independent professional verification.',
            'Private readiness request, not a core TaskRelease.',
            'Find the authentic detailed task/gate/allocation producers and equivalent native release issuer; '
            'submit the exact request only after those sources and current grants are available.'),
        'rectify_dependency': (
            'The original current task and necessary requirements, with actual unresolved readiness gaps.',
            'Scoped issues for the original requirements; no dependency is repaired by this output.',
            'Bind each issue to its authorized responsible consumer and independently received remedy evidence; '
            'then recheck the original task under an explicit new invocation.'),
        'resequence': (
            'Original task and effective mandate plus explicitly authorized independent replacement tasks; '
            'preserve predecessor identities, execution windows and cycle checks.',
            'Private replacement-task proposal; it does not alter a native programme or release work.',
            'Locate the equivalent original programme-change consumer and its actual outcome; '
            'do not turn a private replacement list into a core schedule update.'),
    },
    'CONTRACTOR-A07': {
        'execute': (
            'Current released task, authentic core TaskRelease and satisfied ExecutionGateSnapshot; '
            'supported WorkMethod/ProductionRule, actual crew/equipment, inventory and site conditions.',
            'Work-input intention only; the engineering core must calculate and atomically record actual work, '
            'consumption, cost and quality.',
            'Find the equivalent native detailed execution issuer and original result query before binding '
            'submission callbacks; aggregate progress is insufficient.'),
        'rebalance': (
            'The same original released task, release, gates and actual input ledgers as execute, '
            'with authorized replacement allocations and supported production rules.',
            'Revised work-input intention; no resource movement or work is executed by the micro result.',
            'Bind the original input-change issuer and query its actual allocation/work records; '
            'preserve unknown outcomes without a replacement command.'),
        'report': (
            'Original own execution task and report profile; independently authored original A07 observations '
            'with actual observed evidence, original-time read authority and matching task requirements.',
            'Private status/issues from observations. This branch does not require a new TaskRelease '
            'and does not measure work or assign a cause to an aggregate suspension.',
            'Locate the authentic detailed task/observation producer and authorized report recipient. '
            'Do not construct those objects from an owner-side completed stage task or suspension event.'),
        'reconcile': (
            'Nonempty original WorkExecution references and their command hashes, actual core-event/work '
            'records, observation evidence and query statuses.',
            'Reconciliation of original history; submitted_unknown or unknown/not_queried outcomes wait.',
            'Connect the existing execution reader to the original native command/receipt query; '
            'never retry physical work to resolve missing history.'),
    },
    'CONTRACTOR-A08': {
        'self_check': (
            'Original work records and requirements, actual authored observation evidence and supported '
            'inspection method whose executor is this Contractor/A08.',
            'Scoped self-check request; no external acceptance or defect closure.',
            'Bind authentic work/observation producers and the original inspection executor/result reader; '
            'aggregate quality is not a work-specific inspection record.'),
        'request_external_check': (
            'Original work records, requirements and actual inspection evidence, with a supported method '
            'and an independently authorized external executor.',
            'Request to an independent inspection party; no accepted inspection result.',
            'Locate the actual external inspection recipient, submission endpoint and independently '
            'received result; do not substitute the Contractor as verifier.'),
        'isolate': (
            'Visible defects linked to actual observations and original work, plus independent isolation '
            'authority for the same actor, function, scope and exact defect set.',
            'Scoped isolation issues only; no native stock return, liability assignment or physical isolation.',
            'Bind the equivalent native isolation consumer and original outcome; do not infer detailed '
            'defects or isolation authority from project_suspended.'),
        'rectify': (
            'Original visible defects and authored remedy plan; actual saved capacity calculation, '
            'current resource/qualification snapshots, supported productivity and acyclic task dependencies.',
            'Private remedy-task proposal; no executed repair, resource reservation or defect closure.',
            'Deliver the exact plan to the authorized task/release consumer, then use independently '
            'observed remedy evidence for any later recheck.'),
        'request_recheck': (
            'Original inspection and open defects, actual remedy evidence covering the original work '
            'and a supported recheck method with independent executor where external acceptance is required.',
            'Recheck request; the original defect remains open until an authentic accepted outcome.',
            'Bind the original inspection/recheck issuer and receipt reader without fabricating a repair '
            'from aggregate quality improvement or a completion event.'),
    },
}


def _source(root: Path, relative: str, symbol: str) -> dict:
    path = root / relative
    raw = path.read_bytes()
    source = raw.decode('utf-8-sig')
    tree = ast.parse(source)
    parts = symbol.split('.')
    nodes = tree.body
    for part in parts:
        matches = [n for n in nodes if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == part]
        if len(matches) != 1:
            raise ValueError(f'Reviewed construction source lost its exact symbol: {relative}:{symbol}')
        node = matches[0]
        nodes = node.body
    text = ast.get_source_segment(source, node)
    return {'path': relative, 'symbol': symbol, 'line': node.lineno,
            'file_sha256': hashlib.sha256(raw).hexdigest(),
            'function_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}


def construction_source_reviews(root: Path, macro_backend: Path) -> dict:
    """Return scoped review records; source presence never promotes acceptance."""
    macro = [
        _source(macro_backend, 'simulation/project_lifecycle_engine.py',
                'ProjectLifecycleEngine.' + name)
        for name in ('_record_lifecycle_task', '_handle_construction')]
    macro.extend(_source(macro_backend, 'simulation/project_state_update_engine.py',
                         'ProjectStateUpdateEngine.' + name)
                 for name in ('update_construction_state', 'update_supply_state', 'update_construction_progress'))
    # Stored paths must resolve from the same repository root as micro sources.
    for row in macro:
        row['path'] = (macro_backend / row['path']).relative_to(root).as_posix()
    result = {}
    for action_id, branches in _BRANCHES.items():
        path, symbol = _MICRO[action_id]
        source = _source(root, path, symbol)
        result[action_id] = {
            choice: {
                'status': 'source_requirements_reviewed_runtime_unverified',
                'micro_source': deepcopy(source), 'reviewed_native_sources': deepcopy(macro),
                'required_producer_outputs': required, 'micro_result_semantics': effect,
                'next_code_step': step,
                'native_source_boundary': (
                    '_record_lifecycle_task records an owner-side done simulation task with a stage/name '
                    'result; it does not issue the detailed Contractor task, mandate, gate or observation. '
                    'The reviewed state updates calculate aggregate supply/quality/progress. '
                    '_handle_construction emits suspension/variation and assigns completion review. '
                    'These findings are limited to these functions; other original producers and equivalent '
                    'execution endpoints remain to be located. No global macro capability absence is inferred.'),
                'acceptance_effect': 'none',
            } for choice, (required, effect, step) in branches.items()}
    return result
