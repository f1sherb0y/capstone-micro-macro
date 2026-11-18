"""Declare initial refusal policies and private failure-contingent inquiry sources."""
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.contractor_supply_native_development import contractor_plans
from integration.contractor_tender_development import _write,_write_launch_files
from integration.supplier_order_native_development import build_bundle as build_supply,known
from integration.verify_tender_closed_loop import read
from integration.contractor_planning_actions import ContractorPlanningActionAssembler
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def build_bundle(directory,*,run_id,decline_all_quotes=True):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    foundation=directory/'foundation'
    build_supply(foundation,run_id=run_id,with_quote=True,with_product=True,with_screening=True,decline_all_quotes=decline_all_quotes)
    original=read(foundation/'assembly-host.json');settings=deepcopy(original['settings'])
    supply_doc=read(Path(settings['file_path']));snapshot=settings['authority']['organization_snapshot']
    plans=contractor_plans(supply_doc['plans'],organizations=snapshot['organizations'],grants=snapshot['authorizations'])
    followups=[]
    for plan in plans:
        objects=plan['objects'];profile,=[r['value'] for r in objects if r['ref']['kind']=='WorkPlanningProfile']
        disclosure=plan['disclosures'][0];requirement=disclosure['requirement_links'][0]['supply_requirement_ref']
        recipient={'kind':'SupplySupplier','id':profile['ref']['id']+'-inquiry-recipient','version':'1'}
        basis=next(r['value'] for r in objects if r['ref']['kind']=='Evidence' and r['value']['basis_kind']=='assumed' and r['value']['locator']=='independent-contractor-procurement-mandate-and-received-commercial-views')
        basis['content_hash']=task_digest({'original_declared_basis_sha256':basis['content_hash'],'authorized_trigger':'own_committed_supplier_selection_failed',
            'private_inquiry_recipient':disclosure['supplier_id'],'requirement_ref':requirement,'inquiry_channel_independently_declared':True,
            'effect':'private_request_quote_proposal_only'})
        profile.update(choice='request_quote',requirement_refs=[requirement],supplier_refs=[recipient],selected_offer_ref=None,procurement_authority_ref=None,
            note='Following the actually received own failed selection, propose an independently authorized new private inquiry. No inquiry has been sent and no Supplier accepted or was appointed.')
        objects.append({'ref':recipient,'value':{'ref':recipient,'scope':profile['scope'],'available_at':profile['available_at'],
            'effective_window':profile['effective_window'],'evidence_refs':[basis['ref']],'organization_id':disclosure['supplier_id'],
            'accepts_inquiries':known(True),'requirement_refs':[requirement]}})
        candidate,=[r['value'] for r in objects if r['ref']==plan['context']['candidate_set_ref']]
        candidate['candidates']=[{'ref':requirement,'permitted_choices':['request_quote']}]
        visible=[r['ref'] for r in objects];plan['context']['visible_refs']=visible
        grant,=[r['value'] for r in objects if r['ref']==profile['authority_ref']];grant['readable_refs']=visible
        for i,g in enumerate(snapshot['authorizations']):
            if g['ref']==grant['ref']:snapshot['authorizations'][i]=deepcopy(grant)
        for row in objects:
            value=deepcopy(row['value'])
            if row['ref']['kind']=='Evidence' and value['content_hash'] is None:value['content_hash']='0'*64
            ContractorPlanningActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
        followups.append({k:deepcopy(plan[k]) for k in ['organization_id','project_id','tick','context','action_input','objects','native_evidence_ref']}
            | {'trigger':'own_committed_supplier_selection_failed'})
    file=directory/'failure-followup-input.json';_write(directory,file.name,{'schema_version':'procurement-failure-followup.v1','run_id':run_id,'plans':followups})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1',
        'settings':{'supply':settings,'followup':{'file_path':str(file.resolve()),'file_sha256':hashlib.sha256(file.read_bytes()).hexdigest()}}})
    for name in ['native-host.json','macro-request.json']:_write(directory,name,read(foundation/name))
    _write(directory,'source-policy.json',{'decline_all_quotes':decline_all_quotes,'run_id':run_id,
        'boundary':'Original supported initial scenarios and independent initial commercial policies only. Native negative selection stays native. A current actual committed failure is required before any private follow-up worker starts.'})
    _write_launch_files(directory,assembly_hook='integration.procurement_failure_followup:configure_assembly',readme_override=__doc__)
