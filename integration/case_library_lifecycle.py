"""Apply input-only case-library facts to the existing bounded lifecycle host.

The native initial-project entry is used: a random generated opportunity is
never renamed into a real project. Contract, price and outcome fields stay empty.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from integration.catalog import SharedCatalog, DEFAULT_SOURCE
from integration.shared_data import SharedDataset
from integration.contractor_tender_development import _write, _write_launch_files
from integration.origin_lifecycle_case import build_bundle as build_origin, run
from integration.origin_lifecycle_sources import InitialLateSources, read
from src.coordination.tasks import task_digest


class LibraryInitialSources(InitialLateSources):
    """Recompile initial declarations, including their exact projection hashes."""
    def __init__(self,directory,*,config,public_project,companies,identities):
        super().__init__(directory,config={**config,'late_money_scale':'1'})
        self.names={**identities,'PGEN0001':public_project['project_id'],
            'Hong Kong':'Macau','industrial':'infrastructure'}
        self.pattern=re.compile('|'.join(re.escape(k) for k in sorted(self.names,key=len,reverse=True)))
        self.public_project=public_project
        self.companies={c['company_id']:c for c in companies}
        self.declaration=task_digest({'config':config,'public_project':public_project,
            'public_companies':companies,'identity_mapping':identities})

    def string(self,value):
        return self.pattern.sub(lambda m:self.names[m.group()],value)

    def transform(self,value):
        if isinstance(value,str):return self.string(value)
        if isinstance(value,list):
            result=[self.transform(v) for v in value]
            return list(dict.fromkeys(result)) if result and all(isinstance(v,str) for v in result) else result
        if not isinstance(value,dict):return value
        result={self.string(k):self.transform(v) for k,v in value.items()}
        if 'allowed_regions' in value and 'project_use_codes' in value:
            # This is the original generator's supported domain, not a single
            # project's identity. Keep Hong Kong and industrial alongside the
            # already supported Macau and infrastructure for later candidates.
            result['allowed_regions']=deepcopy(value['allowed_regions'])
            result['project_use_codes']=deepcopy(value['project_use_codes'])
        if result.get('ref',{}).get('kind')=='Project':
            for field in ['name','title']:
                if field in result:result[field]=self.public_project['name']
        if result.get('basis_kind')=='assumed' and result.get('content_hash'):
            result['content_hash']=task_digest({'original':value['content_hash'],
                'initial_case_declaration':self.declaration})
            own=[c for key,c in self.companies.items() if key in result.get('ref',{}).get('id','')]
            # Add public context only to the existing own initial-assumptions
            # evidence. File-backed quantity/cost/indicator locators are exact
            # source identities and must retain their original configured form.
            if own and result.get('ref',{}).get('id','').endswith('-assumptions'):
                background={'project':self.public_project,'public_companies':own}
                result['locator']=result.get('locator','')+'; CASE_LIBRARY_PUBLIC_BACKGROUND='+json.dumps(
                    background,ensure_ascii=False,sort_keys=True)
        return result

    def finalize_document(self, document):
        document=super().finalize_document(document)
        # These embedded documents and pure-method inputs are authored before
        # execution. Renaming their references changes their canonical hashes;
        # it must not weaken the runtime evidence or saved-method validators.
        from src.actions.contracts.common import Reference
        from src.actions.contracts.government_decision_objects import GovDecisionDraft
        from src.actions.roles.qs_change import content_digest
        from src.methods.government_rules import GovRuleInput
        for plan in document.get('plans',[]):
            for bid in plan.get('bids', []):
                company = self.companies.get(bid.get('contractor_id'), {})
                if company.get('public_fit_evidence') is not None:
                    bid['evaluation_score']['value'] = str(company['public_fit_evidence']['score'])
            if 'submission_content' not in plan:continue
            digest=task_digest(plan['submission_content'])
            for stage in ['review','decision']:
                objects=plan[stage+'_objects']
                by_ref={task_digest(r['ref']):r['value'] for r in objects}
                def get(reference):return by_ref[task_digest(reference)]
                source=get(plan['submission_evidence_ref'])
                old_digest=source['content_hash']
                source['content_hash']=digest
                source['locator']=source['locator'].replace(old_digest,digest)
                for row in objects:
                    value=row['value']
                    if value.get('content_sha256')==old_digest:value['content_sha256']=digest
                if stage=='review':
                    inputs=plan['review_input'];task=get(inputs['task_ref'])
                    for rule_ref in inputs['rule_refs']:
                        rule=get(rule_ref);fact=get(rule['fact_ref'])
                        if rule['criterion']!='code_equals' or rule['required_professions']:
                            raise ValueError('Case compiler supports the original declared document-code check only')
                        method=GovRuleInput(criterion=rule['criterion'],
                            applicable=get(rule['applicability_ref'])['applicable'],
                            measured_value=None,code_value=fact['code_value'],unit=rule['unit'],
                            minimum=rule['minimum'],maximum=rule['maximum'],expected_code=rule['expected_code'],
                            professional_findings=[],professional_complete=True,
                            source_refs=[Reference.model_validate(r) for r in [rule_ref,
                                rule['applicability_ref'],inputs['submission_ref'],task['ref'],
                                fact['ref'],*fact['verification_evidence_refs']]])
                        get(rule['result_ref'])['input_sha256']=content_digest(method)
                else:
                    for row in objects:
                        if row['ref']['kind']=='DecisionBasis' and 'draft' in row['value']:
                            basis=row['value']
                            get(basis['command_ref'])['draft_sha256']=content_digest(
                                GovDecisionDraft.model_validate(basis['draft']))
        return document


def build_bundle(directory,config):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    catalog=SharedCatalog(directory/'case-catalog.sqlite3')
    imported=catalog.import_inputs(DEFAULT_SOURCE)
    dataset=catalog.scenario(config['case_id'],budget=config['scenario_budget'],
        duration=config['contract_duration'],seed=config['random_seed'],
        candidate_policy=config.get('candidate_policy'))
    # The case CSV has no observed budget or currency. The current formal
    # lifecycle bindings explicitly support HKD; declare a fresh HKD scenario
    # rather than weaken those guards or claim an unimplemented MOP conversion.
    payload=deepcopy(dataset.payload)
    if config['scenario_currency']!='HKD':
        raise ValueError('Current formal lifecycle supports an explicitly declared HKD scenario only')
    for p in payload['projects']:p['currency']=config['scenario_currency']
    for package in payload['packages']:package['currency']=config['scenario_currency']
    payload['assumptions']['units']['currency']=config['scenario_currency']
    payload['assumptions']['source_note']+='; Currency is an explicit HKD mechanism scenario, not an observed historical denomination or an FX conversion.'
    dataset=SharedDataset(payload)
    project,=dataset.payload['projects']
    if project['region']!='Macau' or project['currency']!='HKD' or project['project_type']!='infrastructure':
        raise ValueError('This adapter explicitly declares the Macau infrastructure case only')
    companies=dataset.payload['companies']
    role=lambda role:[c for c in companies if c['company_role']==role]
    owner,=role('owner');designers=role('designer');supervisors=role('supervisor')
    contractors=role('contractor');suppliers=role('supplier')
    expanded=config.get('candidate_policy') is not None
    if expanded:
        if config.get('active_contractor_count') != len(contractors):
            raise ValueError('Active contractor count must match the declared retrieval policy')
        if config['model_options']['max_calls'] < len(contractors):
            raise ValueError('Model budget cannot cover every active Contractor')
        companies=deepcopy(companies)
        for company in companies:
            if company['company_role']=='contractor':
                company['public_fit_evidence']=dataset.payload['assumptions']['candidate_selection'][company['company_id']]
    identities={'finance-owner-a':owner['company_id'],
        'finance-architect':designers[0]['company_id'],'finance-architect-b':designers[1]['company_id'],
        'finance-qs':supervisors[0]['company_id'],'finance-engineer':supervisors[1]['company_id'],
        'finance-contractor':contractors[0]['company_id'],'origin-contractor-b':contractors[1]['company_id'],
        'finance-supplier':suppliers[0]['company_id'],'origin-supplier-b':suppliers[1]['company_id']}
    if expanded:
        identities.update({f'dev-contractor-{i+1:03d}':c['company_id'] for i,c in enumerate(contractors) if i>=2})
    base_config=read(Path(config['base_config']))
    base_config.update(run_id=config['run_id'],model_options=deepcopy(config['model_options']))
    if expanded:
        base_config.update(initial_contractor_ids=['dev-contractor-a','dev-contractor-b']+
            [f'dev-contractor-{i+1:03d}' for i in range(2,len(contractors))],
            api_total_attempt_cap=config['api_total_attempt_cap'])
    foundation=directory/'origin-foundation'
    build_origin(foundation,base_config)
    transform=LibraryInitialSources(directory/'case-declarations',config=config,
        public_project=project,companies=companies,identities=identities)
    host=transform.settings(read(foundation/'assembly-host.json'))
    host=transform.bind_initial_digests(host)
    request=transform.transform(read(foundation/'macro-request.json'))
    by_company={c['company_id']:c for c in companies}
    for agent in request['agents']:
        if agent['agent_id'] in by_company:agent['name']=by_company[agent['agent_id']]['company_name']
    authority=host['settings']['bank']['authority']
    for organization in authority['organization_snapshot']['organizations']:
        company=by_company.get(organization['organization_id'])
        if company:
            organization['public_description']=company['company_name']+'; '+company['profile']
    for name in ['bank','professional','opportunity','formation','supplier','government']:
        host['settings'][name]['authority']=deepcopy(authority)
    host['settings']['tender']['settings']['source_settings']['application_settings']['owner_contractor']['contractor']['authority']=deepcopy(authority)
    request.update(ticks=config['ticks'],random_seed=config['random_seed'],
        initial_projects=[{'project_id':project['project_id'],'name':project['name'],
            'project_type':project['project_type'],'region':project['region'],
            'owner_id':project['owner_id'],'current_stage':'initiation',
            'initial_budget':project['budget'],'technical_complexity':config['technical_complexity'],
            'performance':{'planned_duration':config['contract_duration']},
            'flags':{'case_library_public_background':deepcopy(project)}}])
    native=transform.transform(read(foundation/'native-host.json'))
    if config.get('response_cache_directory'):
        native['settings'].update(response_cache_directory=config['response_cache_directory'],
            max_paid_attempts=config.get('api_total_attempt_cap',4))
    _write(directory,'macro-request.json',request)
    _write(directory,'assembly-host.json',host)
    _write(directory,'native-host.json',native)
    _write(directory,'case-config.json',config)
    _write(directory,'macro-before.json',read(foundation/'macro-before.json'))
    _write(directory,'case-library-input.json',dataset.payload)
    _write(directory,'source-declaration.json',{
        'source_kind':'case_library_public_background_with_explicit_scenario_assumptions',
        'project':project,'catalog_inputs':imported,'actor_identity_mapping':identities,
        'excluded':'Historical winners, partners, contract amounts, benchmark rows and evaluation hints are not imported.',
        'assumptions':{'budget':config['scenario_budget'],'currency':config['scenario_currency'],
            'duration':config['contract_duration'],'technical_complexity':config['technical_complexity'],
            'enterprise_role_and_numeric_capabilities':'Scenario eligibility and normalized values, not observed real qualifications or ability estimates.',
            'unused_catalog_contractor':None if expanded else contractors[2]['company_id'],
            'active_contractor_count':len(contractors) if expanded else 2,
            'evaluation_score_basis':'public_text_fit_proxy_not_observed_qualification' if expanded else 'uniform_synthetic_score',
            'support_roles':'Banks and regulator retain synthetic scenario identities.',
            'currency_reauthoring':'Private initial amounts are explicitly declared in HKD because current formal bindings require it. MOP remains unsupported here; no FX conversion or observed historical costs.'},
        'entry_boundary':'Native initial project at initiation. First investment choice and initial bank selection are not executed in this imported-project entry. Later opportunity judgments may read actual own settlement.',
        'outcomes_prefilled':False})
    _write_launch_files(directory,offline=False,
        assembly_hook='integration.origin_model_lifecycle:configure_assembly',
        agent_client_factory='integration.model_tender_native:build_agent_client',
        allow_native_project_generation=True,allow_native_initial_projects_with_generation=True,
        source_note='Input-only case-library public project and enterprise facts with explicitly declared HKD scenario budget, duration and capabilities. No historical outcomes or FX conversion.',
        readme_override='Native initiation entry for '+config['case_id']+'. Only A02 pricing uses the bounded model host. No automatic retries, fallback or prefilled decisions.')
    return {'status':'authored-not-executed','case_id':config['case_id'],'directory':str(directory)}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--build',type=Path);action.add_argument('--run',action='store_true')
    args=parser.parse_args(argv)
    result=build_bundle(args.directory/'input',read(args.build)) if args.build else run(args.directory)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
