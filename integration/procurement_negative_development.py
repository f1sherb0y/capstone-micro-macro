"""Extend existing fixed procurement inputs with an unbound negative A05 view."""
from copy import deepcopy
from pathlib import Path
from integration.procurement_failure_development import build_bundle as foundation_bundle
from integration.contractor_supply_native_development import contractor_plans
from integration.contractor_tender_development import _write, _write_launch_files
from integration.verify_tender_closed_loop import read
from integration.contractor_planning_actions import ContractorPlanningActionAssembler
from src.actions.contracts.common import Reference
from src.actions.roles.qs_change import content_digest


def build_bundle(directory, *, run_id, decline_all_quotes):
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=False)
    foundation = directory/'foundation'
    foundation_bundle(foundation, run_id=run_id, decline_all_quotes=decline_all_quotes)
    settings = read(foundation/'assembly-host.json')['settings']
    snapshot = settings['supply']['authority']['organization_snapshot']
    sources = read(settings['supply']['file_path']); grants = []
    plans = contractor_plans(sources['plans'], organizations=snapshot['organizations'], grants=grants)
    for plan in plans:
        old = plan['context']['operation_id']; new = old+'-negative-selection'
        def rename(value):
            if isinstance(value, str): return value.replace(old, new)
            if isinstance(value, list): return [rename(v) for v in value]
            if isinstance(value, dict): return {k:rename(v) for k,v in value.items()}
            return value
        # Distinct current enterprise decisions and post-failure private inquiry
        # drafts keep separate original authorities, operations and read tokens.
        plan.update(rename(deepcopy(plan)))
        # These are independent initial commercial views. Renaming their
        # identities changes the typed terms digest; seal that derived checksum
        # before any engine exists, rather than altering an execution result.
        for row in plan['objects']:
            if row['ref']['kind']=='ProcurementAuthority':
                authority=row['value']
                terms,=[r for r in plan['objects'] if r['ref']==authority['terms_ref']]
                typed=ContractorPlanningActionAssembler.SOURCE_SCHEMAS().validate_projection(
                    Reference.model_validate(terms['ref']),terms['value'])
                authority['terms_sha256']=content_digest(typed)
        ref = {'kind':'NativeSupplySelectionObservation','id':new+'-actual-decisions','version':'1'}
        profile, = [r['value'] for r in plan['objects'] if r['ref']['kind']=='WorkPlanningProfile']
        template = {k:deepcopy(profile[k]) for k in ['scope','available_at','effective_window','evidence_refs']}
        template['available_at']=deepcopy(plan['context']['business_time'])
        plan['objects'].append({'ref':ref,'value':{'ref':ref,**template,
            'organization_id':plan['organization_id'],'project_id':plan['project_id'],'tick':plan['tick'],
            'supplier_decisions':None,'prior_failures':None}})
        plan['negative_selection_observation_ref']=ref
        visible=[r['ref'] for r in plan['objects']];plan['context']['visible_refs']=visible
        actual, = [r['value'] for r in plan['objects'] if r['ref']==profile['authority_ref']]
        actual['readable_refs']=visible
        for grant in grants:
            if grant['ref']['id'].startswith(old+'-'):
                renamed=rename(grant)
                if renamed['ref']==actual['ref']:renamed=deepcopy(actual)
                snapshot['authorizations'].append(renamed)
    settings['supply']['contractor']={'version':'1',**_write(directory,'contractor-negative-input.json',{
        'schema_version':'contractor-supply-input.v1','run_id':run_id,'plans':plans})}
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1',
        'host_id':run_id,'version':'1','settings':settings})
    native=read(foundation/'native-host.json'); routes=native['settings']
    routes['native_proposals']=[r for r in routes['native_proposals'] if (r['role'],r['operation'])!=('Contractor','select_supplier')]
    routes['native_decisions']=[r for r in routes['native_decisions'] if (r['role'],r['decision_type'])!=('Contractor','contractor_supplier_selection')]
    routes['micro_contractor_supply_scope']=True
    _write(directory,'native-host.json',native)
    _write(directory,'macro-request.json',read(foundation/'macro-request.json'))
    _write_launch_files(directory,assembly_hook='integration.procurement_failure_followup:configure_assembly',readme_override=__doc__)
