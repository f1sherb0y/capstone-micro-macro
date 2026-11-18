"""Independent private JV review options; actual observations remain unbound."""
from copy import deepcopy
from pathlib import Path
from integration.contractor_region_development import build_bundle as foundation
from integration.contractor_jv_review import JVReviewPlan
from integration.professional_monthly_native import ProfessionalMonthlySettings
from integration.bindings.gba_v1_contractor_screening import gba_contractor_screening_source_schemas
from integration.contractor_tender_development import _write,_write_launch_files,ref
from integration.verify_tender_closed_loop import read
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def build_bundle(directory,*,run_id,regional_friction):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    base=directory/'regional-foundation';foundation(base,run_id=run_id,regional_friction=regional_friction)
    authority=read(base/'assembly-host.json')['settings']['authority'];plans=[]
    for seed in read(base/'region-review-input.json')['plans']:
        org,tick=seed['organization_id'],seed['tick'];tag=org+'-jv-review-'+str(tick);rr=lambda kind:ref(kind,tag)
        context=deepcopy(seed['context']);context.update(operation_id=tag,task_ref=rr('DecisionTask'),candidate_set_ref=rr('CandidateSet'),read_token=tag+'-read')
        scope=context['scope'];now=context['business_time'];native=seed['native_evidence_ref']
        objects=[deepcopy(r) for r in seed['objects'] if r['ref']['kind'] not in {'RegionEntryReviewPolicy','RegionEntryReviewObservation','CandidateSet'}]
        profile,=[r['value'] for r in objects if r['ref']['kind']=='OpportunityScreeningProfile']
        profile.update(monthly_region_policy_ref=None,monthly_region_observation_ref=None)
        grant=next(g for g in authority['organization_snapshot']['authorizations'] if g['ref']==context['authorization_refs'][0]);window=grant['validity']
        basis,policy,observation=map(rr,['Evidence','JVPartnerReviewPolicy','JVPartnerReviewObservation'])
        def add(identity,value):objects.append({'ref':identity,'value':{'ref':identity,**deepcopy(value)}})
        first,=[r for r in objects if r['ref']['kind']=='RegionalPartnerDisclosure']
        first['value']['partner_organization_id']='declared-public-macao-partner-a'
        second=deepcopy(first);second['ref']=ref('RegionalPartnerDisclosure',tag+'-b');second['value']['ref']=second['ref'];second['value']['partner_organization_id']='declared-public-macao-partner-b';objects.append(second)
        measure=lambda v:{'value':v,'unit':'ratio','basis_ref':basis}
        options=[{'disclosure_ref':row['ref'],'regional_review_weight':measure(weight),'own_review_effort_ratio':measure(effort)}
            for row,weight,effort in [(first,'0.6','0.1'),(second,'0.2','0.05')]]
        assumed={'purpose':'independent private preliminary JV risk-sharing review priorities',
            'candidate_ids':['declared-public-macao-partner-a','declared-public-macao-partner-b'],'options':options,
            'interpretation':'Private review weights and own effort ratios only; no counterparty risk-sharing promise or quoted cost.',
            'counterparty_consent':'unknown','committed_partner_capacity':'unknown'}
        add(basis,{'source_kind':'synthetic','basis_kind':'assumed','locator':'independent-initial-private-JV-review-policy-and-public-candidate-listing',
            'content_hash':task_digest(assumed),'effective_window':window})
        first['value']['evidence_refs']=[basis];second['value']['evidence_refs']=[basis]
        add(policy,{'organization_id':org,'scope':scope,'authority_ref':grant['ref'],'effective_window':window,
            'home_region':'Hong Kong','target_region':'Macao','minimum_free_ratio':measure('0.2'),'options':options,
            'purpose':'private_cross_region_risk_sharing_candidate_review','evidence_refs':[basis]})
        add(observation,{'organization_id':org,'scope':scope,'as_of':now,'native_home_region':None,'native_friction':None,
            'native_free_ratio':None,'prior_own_outcomes':None,'evidence_refs':[native]})
        profile.update(monthly_jv_policy_ref=policy,monthly_jv_observation_ref=observation)
        for r in objects:
            if r['ref']==native:r['value'].update(locator='actual-current-native-regional-friction-free-ratio-and-prior-confirmed-JV-reviews',content_hash=None)
        objects.append({'ref':context['candidate_set_ref'],'value':{'operation_id':tag,'scope':scope,'as_of':now,
            'candidates':[{'ref':seed['action_input']['package_ref'],'permitted_choices':['participate','decline','clarify']}],'search_profile_ref':rr('Profile')}})
        grant['readable_refs']=[r['ref'] for r in objects];context['visible_refs']=deepcopy(grant['readable_refs'])
        for r in objects:
            v=deepcopy(r['value'])
            if r['ref']==native:v['content_hash']='0'*64
            if r['ref']==observation:v.update(native_home_region='Hong Kong',native_friction=measure('0'),native_free_ratio=measure('1'),prior_own_outcomes=[])
            gba_contractor_screening_source_schemas().validate_projection(Reference.model_validate(r['ref']),v)
        plans.append(JVReviewPlan.model_validate({'organization_id':org,'role':'Contractor','tick':tick,'context':context,'action_input':seed['action_input'],
            'objects':objects,'native_evidence_ref':native,'observation_ref':observation}).model_dump(mode='json'))
    sources=_write(directory,'jv-review-input.json',{'schema_version':'contractor-jv-review-input.v1','run_id':run_id,'plans':plans})
    settings=ProfessionalMonthlySettings.model_validate({'authority':authority,**sources})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1','settings':settings.model_dump(mode='json')})
    _write(directory,'native-host.json',read(base/'native-host.json'));_write(directory,'macro-request.json',read(base/'macro-request.json'))
    _write_launch_files(directory,assembly_hook='integration.contractor_jv_review:configure_assembly',readme_override=__doc__)
