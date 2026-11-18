"""Run a fresh complement and match disjoint evidence to the project collection."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree as ET

from integration.action_catalog import ROOT, write_new
from integration.verify_supplier import sha


def identity(node):
    components = node.split('::')
    return components[0][:-3].replace('/', '.') + ''.join('.'+v for v in components[1:-1]), components[-1]


def verify(selected: Path, output: Path):
    selected, output = selected.resolve(), output.resolve()
    if not selected.is_relative_to(ROOT) or not output.is_relative_to(ROOT) or output.exists():
        raise ValueError('Use repository paths and a new evidence directory')
    manifest = json.loads((selected / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['status'] != 'partial_local_verified': raise ValueError('Selected evidence is not verified')
    for name,digest in manifest['artifact_hashes'].items():
        if sha(selected / name) != digest: raise ValueError(f'Selected artifact changed: {name}')
    for name,digest in manifest['code_hashes'].items():
        if sha(ROOT / name) != digest: raise ValueError(f'Selected source changed: {name}')
    baseline = ROOT / manifest['protected']['baseline']
    protected = json.loads(baseline.read_text(encoding='utf-8'))['protected_hashes']
    output.mkdir(parents=True)
    paths = [p for directory in ('src','integration','tests','config','skills') for p in (ROOT / directory).rglob('*')
             if p.is_file() and p.suffix in {'.py','.json','.md','.yaml','.yml'}]
    paths.extend(ROOT / name for name in ('pyproject.toml','uv.lock'))
    code_hashes = {p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    freeze = {'code_hashes':code_hashes,'protected_hashes':protected,'selected_manifest_sha256':sha(selected / 'manifest.json')}
    write_new(output / 'freeze.json',freeze)
    collection = subprocess.run([sys.executable,'-m','pytest','tests','--collect-only','-q','--disable-warnings'],cwd=ROOT,capture_output=True,text=True)
    (output / 'collection.log').write_text(collection.stdout+collection.stderr,encoding='utf-8')
    if collection.returncode: raise ValueError('Project collection failed; see collection.log')
    nodes = [line for line in collection.stdout.splitlines() if line.startswith('tests/') and '::' in line]
    collected = {identity(node) for node in nodes}
    selected_root = ET.parse(selected / 'tests.xml').getroot()
    selected_tests = {(r.get('classname'),r.get('name')) for r in selected_root.findall('.//testcase')}
    if len(collected) != len(nodes) or not selected_tests <= collected: raise ValueError('Duplicate or stale test evidence')
    remaining = [node for node in nodes if identity(node) not in selected_tests]
    modules = list(dict.fromkeys(node.split('::')[0] for node in remaining))
    if any(identity(node) in selected_tests for node in nodes if node.split('::')[0] in modules):
        raise ValueError('Mixed selected/complement module; use explicit node selection')
    command = [sys.executable,'-m','pytest',*modules,'-q','--disable-warnings','-o','faulthandler_timeout=60',f'--junitxml={output / "complement.xml"}']
    print(f'Running fresh complement: {len(remaining)} tests in {len(modules)} modules',flush=True)
    with (output / 'complement.log').open('x',encoding='utf-8') as stream:
        status = subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    complement_root = ET.parse(output / 'complement.xml').getroot()
    combined = ET.Element('testsuites')
    seen = set()
    for root in (selected_root,complement_root):
        for row in root.findall('.//testcase'):
            key = row.get('classname'),row.get('name')
            if key in seen or any(row.find(k) is not None for k in ('failure','error','skipped')):
                raise ValueError(f'Duplicate or nonpassing test: {key}; see complement.log')
            seen.add(key)
        combined.extend(deepcopy(s) for s in root.findall('testsuite'))
    totals = {k:sum(int(s.get(k,'0')) for s in combined) for k in ('tests','failures','errors','skipped')}
    if status.returncode or collected != seen or len(seen) != totals['tests'] or any(totals[k] for k in ('failures','errors','skipped')):
        raise ValueError('Combined evidence does not exactly match current project test collection')
    for name,digest in {**code_hashes,**protected}.items():
        if sha(ROOT / name) != digest: raise ValueError(f'Frozen source changed: {name}')
    if sha(selected / 'manifest.json') != freeze['selected_manifest_sha256']: raise ValueError('Selected evidence changed')
    ET.ElementTree(combined).write(output / 'tests.xml',encoding='utf-8',xml_declaration=True)
    write_new(output / 'checks.json',{'collection_matches':True,'unique_tests':len(seen),'selected_tests':len(selected_tests),'complement_tests':len(remaining),
                                    'complement_command':command,'protected_files':len(protected)})
    write_new(output / 'manifest.json',{'schema_version':'plan-full-regression-composite.v2','status':'passed',
        'recorded_at':datetime.now(timezone.utc).isoformat(),'tests':totals,'unique_tests':len(seen),'code_hashes':code_hashes,
        'source_runs':{'selected':(selected / 'manifest.json').relative_to(ROOT).as_posix(),'fresh_complement':'complement.xml'},
        'protected':{'files':len(protected),'unchanged':True,'baseline':baseline.relative_to(ROOT).as_posix()},
        'artifact_hashes':{name:sha(output / name) for name in ('freeze.json','collection.log','complement.xml','complement.log','tests.xml','checks.json')},
        'limitations':['This proves the current tests pass; 106 actions, calibration, real models and formal bindings are not complete']})
    print(json.dumps({'output':str(output),'tests':totals,'unique_tests':len(seen)}),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selected',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args()
    verify(args.selected,args.output)
