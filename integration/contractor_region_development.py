"""Independent initial regional dossier and public candidates; no contact or JV."""
from copy import deepcopy
from pathlib import Path
from integration.contractor_monthly_development import build_bundle as foundation
from integration.contractor_region_review import RegionReviewPlan
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.bindings.gba_v1_contractor_screening import gba_contractor_screening_source_schemas
from integration.contractor_tender_development import _write,_write_launch_files,ref
from integration.verify_tender_closed_loop import read
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def build_bundle(directory,*,run_id,regional_friction):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    base=directory/'screening-foundation';foundation(base,run_id=run_id)
    authority=read(base/'assembly-host.json')['settings']['authority'];plans=[]
    for seed in read(base/'contractor-monthly-input.json')['plans']:
        org,tick=seed['organization_id'],seed['tick'];tag=org+'-region-review-'+str(tick);rr=lambda kind:ref(kind,tag)
        context=deepcopy(seed['context']);context.update(operation_id=tag,task_ref=rr('DecisionTask'),candidate_set_ref=rr('CandidateSet'),read_token=tag+'-read')
        scope=context['scope'];now=context['business_time'];native=seed['native_evidence_ref']
        # Author a fresh synthetic target-region dossier before publication.
        # This never edits a source or formal state of an already running case.
        def target(value):
            if isinstance(value,list):return [target(v) for v in value]
            if isinstance(value,dict):return {k:target(v) for k,v in value.items()}
            return 'Macao' if value=='HK' else value
        objects=target([deepcopy(r) for r in seed['objects'] if r['ref']['kind'] not in {'CandidateSet','OutreachObservation'}])
        profile,=[r['value'] for r in objects if r['ref']['kind']=='OpportunityScreeningProfile'];profile['outreach_limits']=None
        basis=profile['evidence_refs'][0];grant=next(g for g in authority['organization_snapshot']['authorizations'] if g['ref']==context['authorization_refs'][0]);window=grant['validity']
        policy,observation,partner=map(rr,['RegionEntryReviewPolicy','RegionEntryReviewObservation','RegionalPartnerDisclosure'])
        def add(identity,value):objects.append({'ref':identity,'value':{'ref':identity,**deepcopy(value)}})
        measure=lambda v:{'value':v,'unit':'ratio','basis_ref':basis}
        add(policy,{'organization_id':org,'scope':scope,'authority_ref':grant['ref'],'effective_window':window,
            'home_region':'Hong Kong','target_region':'Macao','maximum_friction':measure('0.35'),'minimum_free_ratio':measure('0.2'),
            'partner_disclosure_refs':[partner],'purpose':'preliminary_qualification_and_local_partner_review','evidence_refs':[basis]})
        add(partner,{'reviewing_organization_id':org,'partner_organization_id':'declared-public-macao-builder',
            'scope':scope,'available_at':now,'effective_window':window,'region_ids':['Macao'],'work_types':['building'],
            'disclosure_use':'public_preliminary_candidate_review','evidence_refs':[basis]})
        add(observation,{'organization_id':org,'scope':scope,'as_of':now,'native_home_region':None,'native_friction':None,
            'native_free_ratio':None,'prior_own_outcomes':None,'evidence_refs':[native]})
        profile.update(monthly_region_policy_ref=policy,monthly_region_observation_ref=observation)
        assumptions={'target_region':'Macao','source':'independently rebound initial synthetic screening dossier',
            'original_dossier_sha256':next(r['value']['content_hash'] for r in objects if r['ref']==basis),
            'crew_capacity':2,'existing_crew_commitment':1,'candidate_demand':1,'qualification':'initial synthetic qualification only',
            'public_partner':'declared-public-macao-builder','consent':'unknown','entry_clearance':'unknown'}
        for r in objects:
            if r['ref']==basis:r['value'].update(content_hash=task_digest(assumptions),locator='independent-initial-target-region-synthetic-dossier-and-public-partner-disclosure')
            if r['ref']==native:r['value'].update(locator='actual-current-native-regional-friction-free-ratio-and-prior-confirmed-regional-reviews',content_hash=None)
        objects.append({'ref':context['candidate_set_ref'],'value':{'operation_id':tag,'scope':scope,'as_of':now,
            'candidates':[{'ref':seed['action_input']['package_ref'],'permitted_choices':['participate','decline','clarify']}],'search_profile_ref':rr('Profile')}})
        grant['readable_refs']=[r['ref'] for r in objects];context['visible_refs']=deepcopy(grant['readable_refs'])
        for r in objects:
            value=deepcopy(r['value'])
            if r['ref']==native:value['content_hash']='0'*64
            if r['ref']==observation:value.update(native_home_region='Hong Kong',native_friction=measure('0'),native_free_ratio=measure('1'),prior_own_outcomes=[])
            gba_contractor_screening_source_schemas().validate_projection(Reference.model_validate(r['ref']),value)
        plans.append(RegionReviewPlan.model_validate({'organization_id':org,'role':'Contractor','tick':tick,'context':context,
            'action_input':seed['action_input'],'objects':objects,'native_evidence_ref':native,'observation_ref':observation}).model_dump(mode='json'))
    sources=_write(directory,'region-review-input.json',{'schema_version':'contractor-region-review-input.v1','run_id':run_id,'plans':plans})
    settings=ProfessionalMonthlySettings.model_validate({'authority':authority,**sources})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    _write(directory,'native-host.json',read(base/'native-host.json'))
    macro=read(base/'macro-request.json');macro['macro_environment']['regional_friction_matrix']={'Hong Kong':{'Macao':regional_friction}}
    _write(directory,'macro-request.json',macro)
    _write_launch_files(directory,assembly_hook='integration.contractor_region_review:configure_assembly',readme_override=__doc__)
