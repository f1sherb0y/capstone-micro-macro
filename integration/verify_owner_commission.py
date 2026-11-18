"""Freeze and independently replay the local OWN-A04 appointment boundary."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree as ET

from integration.action_catalog import ROOT,write_new
from integration.coverage import coverage_report
from integration.owner_commission_oracle import source_oracle
from integration.verify_supplier import sha
from integration.verify_owner_investment import TEST_MODULES as INVESTMENT_MODULES
from src.actions.contracts.catalog import ContractCatalog
from src.actions.processors import register_representative_processors
from src.actions.registry import ActionRegistry
from src.methods.capacity import local_method_registry

TEST_MODULES=(*INVESTMENT_MODULES,'owner_commission','owner_commission_contracts','owner_commission_method')
CHECKS={
    'CHECK-OWN-010':'partial: own exact offer/terms decision creates no appointment or delivery reservation; formal independent acceptance and submit/query remain unbound',
    'CHECK-OWN-015':'partial: professional advice does not replace Owner commission or payer authority; formal scope/permission effects and payment binding remain unverified',
    'CHECK-OWN-058':'partial: existing shared-project commitments compete with all management/internal allocations; formal atomic allocation and subsequent rescheduling remain unbound',
    'CHECK-OWN-061':'partial: known invitation permission permits investigation without inferred local qualification; acceptance requires exact project-region qualification; actual producers/calibration remain unbound',
}
LIMITATIONS=[
    'All source facts, organizations, qualifications, fees, capability/method domains and physical pools are explicitly synthetic',
    'One declared clock/currency, fixed location and constant half-open capacity; no real qualification, cost or productivity calibration',
    'A local decision creates no appointment, contract, payment, invoice, task, resource commitment or receipt and does not accept for independent counterparties',
    'Actual input producers, appointment submit/query, formal independent acceptance, obligations, reservations, feedback and recovery remain unbound',
]


def run_tests(output,workers):
    commands=[[sys.executable,'-m','pytest',*[f'tests/test_{name}.py' for name in TEST_MODULES[i::workers]],'-q',
        '--disable-warnings','-o','faulthandler_timeout=60',f'--junitxml={output / f"tests-worker-{i}.xml"}'] for i in range(workers)]
    def worker(i):
        with (output / f'tests-worker-{i}.log').open('x',encoding='utf-8') as stream:
            status=subprocess.run(commands[i],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        print(f'Worker {i} finished: {status.returncode}',flush=True)
        return status.returncode
    with ThreadPoolExecutor(max_workers=workers) as executor:
        statuses=list(executor.map(worker,range(workers)))
    combined=ET.Element('testsuites')
    for i in range(workers):
        combined.extend(ET.parse(output / f'tests-worker-{i}.xml').getroot().findall('testsuite'))
    ET.ElementTree(combined).write(output / 'tests.xml',encoding='utf-8',xml_declaration=True)
    (output / 'tests.log').write_text('\n'.join((output / f'tests-worker-{i}.log').read_text() for i in range(workers)),encoding='utf-8')
    totals={key:sum(int(s.get(key,'0')) for s in combined) for key in ('tests','failures','errors','skipped')}
    keys={(row.get('classname'),row.get('name')) for row in combined.findall('.//testcase')}
    counts={name:sum(module==f'tests.test_{name}' for module,_ in keys) for name in ('owner_commission','owner_commission_contracts','owner_commission_method')}
    if any(statuses) or len(keys)!=totals['tests'] or any(totals[k] for k in ('failures','errors','skipped')) or counts['owner_commission']<107 or counts['owner_commission_method']<17:
        raise ValueError(f'Incomplete shared regression: {totals}, {counts}; preserve this evidence')
    return totals,len(keys),commands,counts


def verify(output,workers=4):
    output=output.resolve()
    if not output.is_relative_to(ROOT) or output.exists() or not 1<=workers<=8:
        raise ValueError('Use a new repository output directory and 1-8 workers')
    baseline=ROOT / 'output/integration/plan_20261002_implementation/baseline.json'
    protected=json.loads(baseline.read_text())['protected_hashes']
    paths={p for directory in ('src','integration','tests','skills','config') for p in (ROOT / directory).rglob('*')
        if p.is_file() and p.suffix in {'.py','.md','.json','.yaml','.yml'}}
    paths.update(ROOT / name for name in ('pyproject.toml','uv.lock'))
    code_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
    if any(sha(ROOT / name)!=digest for name,digest in protected.items()):
        raise ValueError('Protected source changed before verification')
    output.mkdir(parents=True)
    write_new(output / 'freeze.json',{'code_hashes':code_hashes,'protected_hashes':protected})
    print('Running frozen commission and shared regression',flush=True)
    totals,unique_tests,commands,counts=run_tests(output,workers)
    from tests.test_owner_commission import facts,build_run,named,known,ref,point
    catalogue=ContractCatalog()
    registry=register_representative_processors(ActionRegistry(catalog=catalogue))
    methods=local_method_registry()
    cases=[]
    for choice in ('invite','clarify','accept','reject_all','retender','internal'):
        data=facts()
        named(data,'ProcurementProfile')['policy']=known(choice)
        cases.append((choice,data,'completed',choice))
    specs=[
        ('first_invitation','completed','invite'),('zero_offers_reject','completed','reject_all'),
        ('zero_offers_retender','completed','retender'),('expired_offer','completed','accept'),
        ('withdrawn_terms','completed','accept'),('unknown_qualification_invite','completed','invite'),
        ('unknown_qualification_accept','needs_information',None),('wrong_region','completed','retender'),
        ('qualification_expired','completed','retender'),('future_qualification','needs_information',None),
        ('advisory_owner_authority','technical_error',None),('advisory_quote_action','completed','retender'),
        ('over_cap','completed','retender'),('exact_cap','completed','accept'),
        ('priority_tie','needs_information',None),('unknown_fee','needs_information',None),
        ('unknown_condition','needs_information',None),('unmet_condition','completed','retender'),
        ('management_conflict','completed','retender'),('internal_shared_conflict','completed','retender'),
        ('internal_released','completed','internal'),('existing_internal_task','completed','internal'),
        ('internal_qualification_unknown','needs_information',None),('internal_service_grant_missing','completed','retender'),
        ('partial_management','needs_information',None),('stale_management','needs_information',None),
        ('foreign_currency','unsupported',None),('resource_unit','unsupported',None),
        ('unrelated_issue_work','technical_error',None),('scope_version','technical_error',None),
        ('method_domain','completed','retender'),('advice_only_limits','completed','retender'),
        ('defer_policy','deferred',None),('infeasible_defer','deferred',None),
    ]
    for label,kind,choice in specs:
        data=facts()
        profile=named(data,'ProcurementProfile')
        if label=='first_invitation': profile['policy']=known('invite'); data['input']['candidates']=[]
        elif label.startswith('zero_offers_'):
            profile['policy']=known('reject_all' if label.endswith('reject') else 'retender')
            data['input'].update(candidates=[],candidate_provider_refs=[])
        elif label=='expired_offer': named(data,'ServiceOffer','primary')['effective_window']['end']['offset']=10
        elif label=='withdrawn_terms': named(data,'ContractTerms','primary-terms')['status']='withdrawn'
        elif label.startswith('unknown_qualification_'):
            named(data,'Capability','external-architect')['qualification_coverage']='unknown'
            profile['policy']=known('invite' if label.endswith('invite') else 'accept')
        elif label=='wrong_region': named(data,'Qualification','external-qualification')['region_ids']=['MO']
        elif label=='qualification_expired': named(data,'Qualification','external-qualification')['effective_window']['end']['offset']=10
        elif label=='future_qualification': named(data,'Qualification','external-qualification')['verified_at']['offset']=11
        elif label=='advisory_owner_authority': data['input']['authority_ref']=ref('Authorization','architect-authority')
        elif label=='advisory_quote_action':
            named(data,'Authorization','architect-authority')['action_ids']=['ARCHITECT-A01']
            for identity in ('primary','secondary'): named(data,'ServiceOffer',identity)['authority_action_id']='ARCHITECT-A01'
        elif label in {'over_cap','exact_cap'}: profile['fee_cap']['value']['value']='10' if label=='over_cap' else '30'
        elif label=='priority_tie': named(data,'ServiceOffer','secondary')['priority']=known(1)
        elif label=='unknown_fee': named(data,'ContractTerms','primary-terms')['fee']={'state':'unknown','reason_code':'missing','missing_refs':[]}
        elif label in {'unknown_condition','unmet_condition'}:
            named(data,'Requirement')['permitted']={'state':'unknown','reason_code':'missing','missing_refs':[]} if label=='unknown_condition' else known(False)
        elif label=='management_conflict': named(data,'ResourcePool')['commitments'][0]['quantity']['value']='2.75'
        elif label in {'internal_shared_conflict','internal_released'}:
            profile['policy']=known('internal')
            named(data,'InternalServicePlan')['allocations'][0]['quantity']['value']='2'
            if label=='internal_released':
                load=named(data,'ResourcePool')['commitments'][0]
                load['window']['start']['offset']=10; load['window']['end']['offset']=12
        elif label=='existing_internal_task':
            profile['policy']=known('internal')
            named(data,'InternalServicePlan')['allocations'][0]['task_target']={'kind':'existing','task_ref':ref('Task','existing-design')}
        elif label=='internal_qualification_unknown':
            profile['policy']=known('internal'); named(data,'Capability','internal-architect')['qualification_coverage']='unknown'
        elif label=='internal_service_grant_missing':
            profile['policy']=known('internal'); named(data,'Authorization','internal-service-authority')['action_ids']=['ARCHITECT-A01']
        elif label=='partial_management': named(data,'ManagementCapacity')['coverage']='partial'
        elif label=='stale_management': named(data,'ManagementCapacity')['as_of']['offset']=9
        elif label=='foreign_currency': named(data,'ContractTerms','primary-terms')['fee']['value']['currency']='USD'
        elif label=='resource_unit': profile['management_allocations'][0]['quantity']['unit']='hours'
        elif label=='unrelated_issue_work': profile['policy']=known('clarify'); named(data,'Issue')['scope_ref']['coverage_refs']=[ref('WorkScope','unrelated')]
        elif label=='scope_version': named(data,'ContractTerms','primary-terms')['service_scope_ref']['version']='2'
        elif label=='method_domain': named(data,'Method')['service_codes']=['unrelated']
        elif label=='advice_only_limits':
            for identity in ('primary-terms','secondary-terms'): named(data,'ContractTerms',identity)['authority_limits']=known(['payment_instruction'])
        elif label=='defer_policy': profile['policy']=known('defer')
        elif label=='infeasible_defer': profile['on_unavailable']=known('defer'); data['input']['candidates']=[]
        cases.append((label,data,kind,choice))
    print('Replaying commission branches and independent source oracles',flush=True)
    runtime,inputs,oracles=[],[],[]
    for label,data,expected_kind,expected_choice in cases:
        run=build_run(data,catalog=catalogue,run_id=f'{output.name}:{label}')
        before=deepcopy(run.objects)
        result=run.execute()
        if result.kind!=expected_kind or expected_choice is not None and result.payload.choice!=expected_choice:
            raise ValueError(f'Unexpected {label}: {result}')
        if run.objects!=before:
            raise ValueError(f'Formal source projection changed during {label}')
        audit=run.runner.audit_records[-1].as_dict()
        if audit['method_registry_digest']!=methods.content_digest or any(c['registry_digest']!=methods.content_digest for c in audit['method_calls']):
            raise ValueError('Method snapshot changed or was omitted from audit')
        oracles.append({'label':label,'oracle':source_oracle(data,result,audit,before)})
        inputs.append({'label':label,'origin':'synthetic','context':run.context.model_dump(mode='json'),'input':run.input,'projections':before})
        runtime.append({'label':label,'result':result.model_dump(mode='json'),'audit':audit,'formal_submission':None,'macro_receipt':None})
    inventory=json.loads((ROOT / 'config/action_registry.json').read_text())
    coverage=json.loads((ROOT / '宏微观衔接方案/新版方案/action_coverage.json').read_text())
    record=next(row for row in coverage['actions'] if row['action_id']=='OWN-A04')
    skill=registry.get('OWN-A04').skill.manifest
    branches={row['result']['payload']['choice'] for row in runtime if row['result']['kind']=='completed'}
    if branches!=set(catalogue.get('OWN-A04').choices): raise ValueError('Incomplete source branch replay')
    record.update(decision='partial_local_verified',method='partial_local_verified',validation='partial_local_verified',binding='unverified',feedback='pending',
        branches={choice:'partial_local_verified' for choice in sorted(branches)},
        local_processor={'processor_id':skill.processor_id,'code':'src/actions/roles/owner_commission.py','scope':'Authorized synthetic procurement and internal resource decisions only'},
        local_methods={'code':'src/methods/owner_commission.py','registry_status':'registered_host_method','registry_digest':methods.content_digest,
            'support':'Exact fee-cap/ordinal selection plus source-bound fixed-location shared capacity','calibration':'mathematical_only'},
        gaps=[{'kind':'formal_binding','detail':'Actual professional procurement, appointment and task input producers and submit/query remain unbound'},
            {'kind':'feedback_recovery','detail':'Independent acceptance, obligations, commitments, receipts and feedback recovery remain unbound'},
            {'kind':'real_method_calibration','detail':'Professional qualifications, prices, methods, productivity and pools are synthetic'}])
    record['evidence']=list(dict.fromkeys([*record['evidence'],(output / 'manifest.json').relative_to(ROOT).as_posix()]))
    artifacts={'runtime.json':runtime,'inputs.json':inputs,'source_oracle.json':oracles,'methods.json':{'registry_digest':methods.content_digest,'catalog':methods.catalog()},
        'coverage_record.json':record,'coverage.json':coverage_report(inventory,coverage),'skill_audit.json':registry.skill_audit(),
        'binding.json':{'action_id':'OWN-A04','status':'not_bound','macro_receipt':None,'limitations':LIMITATIONS},
        'checks.json':{'tests':totals,'unique_tests':unique_tests,'test_commands':commands,'source_checks':CHECKS,'formal_receipts':0,'model_calls':0,'runtime_cases':len(runtime)}}
    for name,value in artifacts.items(): write_new(output / name,value)
    check=subprocess.run([sys.executable,'-m','integration.action_catalog','--check'],cwd=ROOT,capture_output=True,text=True)
    if check.returncode: raise ValueError(check.stdout+check.stderr)
    whitespace_paths=[*['tests/test_'+name+'.py' for name in TEST_MODULES],
        'src/actions/contracts/owner_commission_objects.py','src/actions/roles/owner_commission.py','src/actions/processors.py',
        'src/actions/contracts/role_rules.py','src/methods/capacity.py','src/methods/owner_commission.py','src/methods/OWNER_COMMISSION.md',
        'skills/actions/owner/OWN-A04/SKILL.md','skills/actions/owner/OWN-A04/manifest.json','tests/fixtures/roles/owner_commission.v1.json',
        'integration/owner_commission_oracle.py','integration/verify_owner_commission.py']
    for name in whitespace_paths:
        checked=subprocess.run(['git','-c','core.whitespace=cr-at-eol','diff','--no-index','--check','/dev/null',name],cwd=ROOT,capture_output=True,text=True)
        if checked.stdout or checked.stderr or checked.returncode not in (0,1): raise ValueError(f'Whitespace: {name}: {checked.stdout}{checked.stderr}')
    if any(sha(ROOT / name)!=digest for name,digest in {**code_hashes,**protected}.items()):
        raise ValueError('Frozen source changed; preserve this run and use a fresh directory')
    write_new(output / 'manifest.json',{'schema_version':'plan-owner-commission-evidence.v1','action_id':'OWN-A04','evidence_id':output.name,
        'recorded_at':datetime.now(timezone.utc).isoformat(),'status':'partial_local_verified',
        'source_sha256':catalogue.get('OWN-A04').source_sha256,'processor_id':skill.processor_id,'skill_version':skill.skill_version,
        'method_registry_digest':methods.content_digest,'tests':totals,'unique_tests':unique_tests,'test_counts':counts,
        'code_hashes':code_hashes,'runtime_cases':len(runtime),'branches':sorted(branches),'checks':CHECKS,
        'protected':{'baseline':baseline.relative_to(ROOT).as_posix(),'files':len(protected),'unchanged':True},
        'artifact_hashes':{name:sha(output / name) for name in [*artifacts,'freeze.json','tests.xml','tests.log',
            *[f'tests-worker-{i}.{suffix}' for i in range(workers) for suffix in ('xml','log')]]},'limitations':LIMITATIONS,
        'environment':{'python':sys.version,'packages':{name:version(name) for name in ('pytest','pydantic','lark')}}})
    print(json.dumps({'output':str(output),'tests':totals,'unique_tests':unique_tests,'runtime_cases':len(runtime)}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    verify(args.output,args.workers)
