"""Locate actual action functions and remaining wiring work without claiming acceptance.

This read-only inventory separates source presence from branch semantics and
runtime evidence. Literal references are navigation aids, never proof that a
host installs an action or that a branch has a native execution endpoint.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import textwrap

from integration.action_macro_mapping import build_mapping
from integration.bootstrap import enable_gba_imports


ROOT = Path(__file__).resolve().parents[1]


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _location(function):
    path = Path(inspect.getsourcefile(function)).resolve()
    lines, line = inspect.getsourcelines(function)
    source = ''.join(lines)
    return {'symbol': function.__module__ + ':' + function.__qualname__,
        'path': path.relative_to(ROOT).as_posix(), 'line': line,
        'end_line': line + len(lines) - 1, 'file_sha256': _sha(path),
        'function_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest()}, source


def _business_functions(processor):
    """Follow actual calls of explicitly imported role functions, not filenames."""
    _, source = _location(processor)
    tree = ast.parse(textwrap.dedent(source))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    results = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module or not node.module.startswith('src.actions.roles.'):
            continue
        module = importlib.import_module(node.module)
        for alias in node.names:
            if (alias.asname or alias.name) not in called:
                continue
            function = getattr(module, alias.name)
            if inspect.isfunction(function):
                location, body = _location(function)
                body_tree = ast.parse(textwrap.dedent(body))
                location['literal_strings'] = sorted({n.value for n in ast.walk(body_tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) <= 100})
                # No claim that a string is an executable branch. Helpers,
                # parameterized decisions and conditional reads need review.
                results.append(location)
    return sorted(results, key=lambda row: row['symbol'])


def _delegated_business_functions(location):
    """Locate explicit thin-wrapper returns, without claiming runtime coverage.

    Complex dispatch and callbacks remain review tasks. Only a direct return
    of an imported/global role function is followed; local assignments, control
    flow, method dispatch and argument-shadowed function names are excluded.
    """
    module_name, qualified_name = location['symbol'].split(':', 1)
    function = importlib.import_module(module_name)
    for name in qualified_name.split('.'):
        function = getattr(function, name)
    seen, results = {location['symbol']}, []
    while inspect.isfunction(function):
        _, source = _location(function)
        definition = ast.parse(textwrap.dedent(source)).body[0]
        body = [node for node in definition.body if not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str))]
        if (not body or not isinstance(body[-1], ast.Return)
                or any(not isinstance(node, ast.ImportFrom) for node in body[:-1])
                or not isinstance(body[-1].value, ast.Call)
                or not isinstance(body[-1].value.func, ast.Name)):
            break
        called = body[-1].value.func.id
        arguments = definition.args
        parameters = {arg.arg for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]}
        parameters.update(arg.arg for arg in (arguments.vararg, arguments.kwarg) if arg is not None)
        if called in parameters:
            break
        target = function.__globals__.get(called)
        for node in body[:-1]:
            for alias in node.names:
                if (alias.asname or alias.name) == called:
                    target = (getattr(importlib.import_module(node.module), alias.name)
                        if node.level == 0 and node.module and node.module.startswith('src.actions.roles.') else None)
        if not inspect.isfunction(target) or not target.__module__.startswith('src.actions.roles.'):
            break
        entry, source = _location(target)
        if entry['symbol'] in seen:
            break
        seen.add(entry['symbol'])
        entry['delegated_from'] = function.__module__ + ':' + function.__qualname__
        entry['evidence_kind'] = 'direct_return_delegation_only'
        entry['literal_strings'] = sorted({node.value for node in ast.walk(ast.parse(textwrap.dedent(source)))
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) <= 100})
        results.append(entry)
        function = target
    return results


def _integration_references(action_ids):
    refs = defaultdict(list)
    hashes = {}
    for path in sorted((ROOT/'integration').rglob('*.py')):
        # Inventory/export code describes actions; it is not a business host.
        if path.name in {'action_macro_mapping.py', 'action_implementation_inventory.py'}:
            continue
        source = path.read_text(encoding='utf-8-sig')
        tree = ast.parse(source, filename=str(path))
        relative = path.relative_to(ROOT).as_posix()
        module = relative[:-3].replace('/', '.')
        lines = source.splitlines()
        found = []

        def visit(node, scope=()):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                scope = (*scope, node.name)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in action_ids:
                found.append((node.value, {'path': relative, 'line': node.lineno,
                    'symbol': module + (':' + '.'.join(scope) if scope else ''),
                    'source': lines[node.lineno-1].strip()[:240],
                    'evidence_kind': 'literal_source_reference_only',
                    'local_fixture_or_offline': any(part in path.stem for part in ('fixture', 'offline'))}))
            for child in ast.iter_child_nodes(node):
                visit(child, scope)

        visit(tree)
        if found:
            hashes[relative] = _sha(path)
            for action_id, location in found:
                refs[action_id].append(location)
    return refs, hashes


def build_inventory():
    enable_gba_imports()
    from src.actions.processors import register_representative_processors
    from src.actions.registry import ActionRegistry

    mapping = build_mapping()
    registry = register_representative_processors(ActionRegistry())
    identifiers = {row['action_id'] for row in mapping['actions']}
    references, reference_hashes = _integration_references(identifiers)
    rows = []
    counts = Counter()
    for action in mapping['actions']:
        registration = registry.get(action['action_id'])
        if registration.processor is None:
            processor, functions = None, []
        else:
            processor, _ = _location(registration.processor)
            functions = _business_functions(registration.processor)
        code_evidence = 'role_function_present_semantics_unverified' if functions else 'business_function_not_located'
        # Missing a directly imported role function is an inspection task, not
        # proof that no implementation exists (dynamic dispatch is possible).
        branches = []
        for branch in action['branches']:
            if registration.processor is None:
                work = 'missing_business_code'
            elif branch['use'] in {'existing_bridge', 'existing_internal_bridge'}:
                work = 'coded_pending_validation'
            else:
                work = 'needs_source_adaptation_or_assembly_review'
            counts[work] += 1
            branches.append({'choice': branch['choice'], 'work_category': work,
                'business_semantics': 'unverified',
                'mapping_use': branch['use'], 'mapping_status': branch['status'],
                'candidate_operation': branch['candidate_operation'],
                'closure': branch['closure'],
                **({'reviewed_source_requirements': branch['reviewed_source_requirements']}
                   if 'reviewed_source_requirements' in branch else {}),
                'next_code_step': (branch['reviewed_source_requirements']['next_code_step']
                    if 'reviewed_source_requirements' in branch else
                    'Implement and bind the original typed business processor.'
                    if work == 'missing_business_code' else
                    'Inspect the located role function and current-source producer; wire its authorized next consumer. '
                    'For formal effects, inspect the original native call chain before selecting a response mapping.'
                    if work == 'needs_source_adaptation_or_assembly_review' else
                    'Inspect existing bridge implementation and its source/authority configuration, then validate '
                    'this exact branch, native consequence if applicable, and later feedback consumer.')})
        input_model = registration.contract.input_model
        rows.append({'action_id': action['action_id'], 'role': action['role'], 'title': action['title'],
            'processor': processor, 'business_functions': functions, 'code_evidence': code_evidence,
            'delegated_business_functions': [entry for location in functions
                for entry in _delegated_business_functions(location)],
            'input_model': input_model.__module__ + ':' + input_model.__qualname__,
            'required_input_fields': [name for name, field in input_model.model_fields.items() if field.is_required()],
            'integration_source_references': references.get(action['action_id'], []),
            'mapping_sections': [key for key, value in action.items() if isinstance(value, dict)
                and key not in {'source', 'native_contract'}],
            'mapped_next_consumer': action['next_consumer'],
            'branches': branches})
    assert len(rows) == len(identifiers) == 106
    assert sum(len(row['branches']) for row in rows) == 438
    assert all(len({b['choice'] for b in row['branches']}) == len(row['branches'])
        and {b['choice'] for b in row['branches']} == set(registry.get(row['action_id']).contract.choices)
        for row in rows)
    return {'schema_version': 'gba-action-implementation-inventory.v1',
        'status': 'static_navigation_and_wiring_work_not_business_acceptance',
        'actions': rows,
        'counts': {'actions': len(rows), 'branches': sum(counts.values()),
            'branch_work_categories': dict(counts),
            'actions_with_located_role_functions': sum(bool(row['business_functions']) for row in rows)},
        'inputs': {'catalog_sha256': _sha(ROOT/'config/action_registry.json'),
            'mapping_generator_sha256': _sha(ROOT/'integration/action_macro_mapping.py'),
            'inventory_generator_sha256': _sha(Path(__file__)),
            'integration_reference_file_sha256': reference_hashes},
        'limits': [
            'Work categories are navigation priorities, not percentages or proof that remaining business code is complete.',
            'No processor means confirmed missing business registration. No located direct role call requires inspection.',
            'Existing bridge labels come from the reviewed mapping, not from runtime verification of every branch.',
            'Literal action references do not prove installed routes; dynamic references are not exhaustively indexed.',
            'Choice string occurrence/absence does not prove branch implementation/absence.',
            'Needs review is not a count of missing implementations; internal preparation may already run inside another bridge.',
            'No macro capability is declared missing by this inventory. Confirmed limits remain in the source-backed mapping.',
            'No business execution, feedback acceptance, coverage promotion or macro mutation is performed.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = build_inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), **result['counts']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
