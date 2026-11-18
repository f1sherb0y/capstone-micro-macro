"""Read actual selected-client provenance; never invent a client contact or relation."""
from copy import deepcopy
import hashlib
import json
import sqlite3
from integration.verify_tender_closed_loop import ROOT,read,require,one,digest_valid,macro_hashes
from integration.verify_tender_basic import verify_history
from integration.verify_professional_chain import verify_scenario
from integration.contractor_construction_source_review import _source
from src.coordination.tasks import TaskIdentity,task_digest

BOUNDARY='Historical own selected-client identity and original native-only monthly feedback only. These are not current private relationship coverage, a contact task, delivered message, client receipt, satisfaction, reputation, active detailed service relationship or a micro-origin monthly decision. Original native selection remains real; no historical task is replayed.'


def prior_selected_clients(selections,*,organization_id,tick):
    """Strictly prior own selection; a later selection cannot justify earlier contact."""
    require(isinstance(tick,int) and not isinstance(tick,bool) and tick>0,'Positive original observation tick required')
    require(len({(s['organization_id'],s['team_event_id']) for s in selections})==len(selections),'Repeated own selection identity')
    return deepcopy(sorted((s for s in selections if s['organization_id']==organization_id and 0<s['tick']<tick),
        key=lambda s:(s['tick'],s['team_event_id'])))


def inspect_sources(config):
    require(config['schema_version']=='architect-client-sources-config.v1','Unsupported selected-client source configuration')
    source=(ROOT/config['source_directory']).resolve()
    require(source.is_relative_to((ROOT/'output/integration').resolve()),'Source must be a preserved workspace integration artifact')
    require(hashlib.sha256((source/'artifact-manifest.json').read_bytes()).hexdigest()==config['source_manifest_sha256'],'Pinned historical source manifest changed')
    historical=verify_history(source)
    original=verify_scenario(source,read(source/'source-config.json'))
    output=read(source/'runtime/result.json');simulation=output['simulation'];host=output['module_host_extension']['host']
    events=[e for p in simulation['project_results'] for e in p['event_log']]
    database=source/'runtime/tasks.sqlite';before=hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        tasks=[json.loads(v) for v, in db.execute('SELECT record FROM tasks')]
        workers=[json.loads(v) for v, in db.execute('SELECT record FROM architect_appointment_results')]
    require(all(t['state']=='output_formed' and t['output_sha256']==task_digest(t['output']) for t in tasks),'Historical task changed or unresolved')
    selections=[]
    for row in host['appointment']['receipts']:
        if row['role']!='Architect':continue
        digest_valid(row)
        worker=one(workers,lambda w:w['identity']==row['identity'],'Original own A03 result missing');digest_valid(worker)
        identity=TaskIdentity(**worker['identity'])
        require(identity.role=='Architect' and identity.action_id=='ARCHITECT-A03' and row['result_sha256']==worker['result_sha256']
            and worker['result_sha256']==task_digest(worker['result']) and worker['source_reading_sha256']==task_digest(worker['source_reading']), 'Original selection confirmation changed')
        task=one(tasks,lambda t:t['identity']==identity.as_dict(),'Original A03 task missing')
        require(task['output']==worker['result'],'Original A03 task differs from saved confirmation')
        event=one(events,lambda e:e['event_id']==row['event_id'],'Actual team selection missing')
        project=one(simulation['project_results'],lambda p:p['project_id']==event['project_id'],'Actual selected project missing')
        appointment=one(worker['source_reading'],lambda s:s['ref']['kind']=='Appointment','Original appointment source missing')['projection']
        request=one(worker['source_reading'],lambda s:s['ref']['kind']=='ServiceRequest','Original appointment client request missing')['projection']
        require(event['event_type']=='consultant_team_appointed' and event['data']['architect_id']==identity.organization_id
            and event['agent_id']==project['owner_id']==appointment['client_organization_id']==request['client_organization_id']
            and appointment['client_id']==request['client_id'] and row['observed']['event_sha256']==task_digest(event),
            'Selected client identity differs from original Owner/project/request/A03')
        require(appointment['status']=='selected' and appointment['service_relationship_ref'] is None and appointment['reservation_ref'] is None,
            'This inspector requires the original selected-only boundary; review an actual activation separately')
        selections.append({'source_run_id':identity.run_id,'organization_id':identity.organization_id,'client_organization_id':appointment['client_organization_id'],
            'client_actor_id':appointment['client_id'],'project_id':event['project_id'],'tick':event['tick'],'team_event_id':event['event_id'],
            'team_event_sha256':task_digest(event),'micro_identity':identity.as_dict(),'micro_result_sha256':worker['result_sha256'],
            'appointment_ref':appointment['ref'],'appointment_status':appointment['status'],'service_relationship_ref':None,'reservation_ref':None,
            'claim':'Actual selection and private compatibility confirmation only; no contact delivery or activated detailed relationship'})
    observations=read(source/'runtime/observations.json')['records'];native_only=[]
    for feedback in observations:
        payload=feedback['payload']
        if payload['event_type']!='agent_operation' or payload['data'].get('operation')!='maintain_client_relationship':continue
        org=feedback['organization_id'];tick=payload['tick']
        require(payload['committed'] is True and payload['agent_id']==org,'Original own feedback is not committed')
        proposals=[t for t in tasks if t['identity']['organization_id']==org and t['identity']['purpose']=='propose'
            and t['identity']['request_id']==f'proposal-tick{tick}-none-{org}-decide_monthly_operation']
        proposal=one(proposals,lambda t:t['output']['action_type']=='maintain_client_relationship','Original native monthly proposal missing')
        require(proposal['output']['factors']['decision_source']=='native_macro' and not proposal['output']['factors'].get('micro_task_key'),
            'This source is no longer a native-only monthly decision; inspect the actual micro route')
        final=one(tasks,lambda t:t['identity']['organization_id']==org and t['identity']['purpose']=='decide'
            and t['identity']['request_id']==f'tick{tick}-no_project-{org}-monthly_enterprise_operation','Original native final decision missing')
        require(final['output']['decision'] is True and final['output']['action_type']=='maintain_client_relationship'
            and final['output']['data']['decision_source']=='native_macro','Original native final is not the same accepted monthly operation')
        agent=one(simulation['agent_results'],lambda a:a['agent_id']==org and a['role']=='Architect','Actual own Architect profile missing')
        memory=one(agent['episodic_memory'],lambda m:m.get('tick')==tick and m.get('operation')=='maintain_client_relationship','Original native monthly memory missing')
        require(memory['label']==payload['data']['label'],'Native monthly memory differs from actual feedback')
        native_only.append({'organization_id':org,'tick':tick,'event_id':feedback['event_id'],'committed_feedback':feedback,'feedback_sha256':task_digest(feedback),
            'native_proposal_identity':proposal['identity'],'native_proposal_sha256':proposal['output_sha256'],
            'native_final_identity':final['identity'],'native_final_sha256':final['output_sha256'],'original_native_memory':memory,
            'strictly_prior_own_client_selections':prior_selected_clients(selections,organization_id=org,tick=tick),
            'counts_as_micro_coverage':False,'claim':'Original native monthly action occurred; no micro decision or client contact receipt is proved'})
    macro=macro_hashes()
    native_agent=one(list((ROOT/macro['root']).rglob('architect_agent.py')),lambda p:p.parent.name=='agents','Frozen original Architect agent missing')
    backend=native_agent.parent.parent
    anchors=[_source(ROOT,(backend/'agents/architect_agent.py').relative_to(ROOT).as_posix(),'ArchitectAgent.decide_monthly_operation'),
        _source(ROOT,(backend/'simulation/interaction_session.py').relative_to(ROOT).as_posix(),'InteractionSessionManager.get_or_create'),
        _source(ROOT,(backend/'simulation/interaction_session.py').relative_to(ROOT).as_posix(),'InteractionSessionManager.append_message'),
        _source(ROOT,'src/actions/roles/architect_opportunity.py','discover_opportunity'),
        _source(ROOT,'src/actions/roles/architect_appointment.py','confirm_appointment'),
        _source(ROOT,'integration/bindings/gba_v1_tender_clarification.py','_channel')]
    require(hashlib.sha256(database.read_bytes()).hexdigest()==before,'Source inspection changed the original database')
    return {'schema_version':'architect-client-source-inspection.v1','status':'waiting_authorized_client_followup_sources',
        'source_directory':source.relative_to(ROOT).as_posix(),'source_manifest_sha256':historical['manifest_sha256'],
        'source_database_sha256':before,'historical_professional_verification':original['status'],'macro':macro,'client_selections':selections,
        'native_only_monthly_observations':native_only,'source_anchors':anchors,
        'available':'Authenticated historical own selected client identity, project, exact original A03 compatibility result and actual native-only monthly feedback',
        'missing':['current_authorized_client_followup_scope_purpose_and_recipient_consent','appropriate_original_micro_followup_decision_binding',
            'supported_client_contact_delivery_or_internal_relationship_update_with_authentic_feedback','later_original_micro_consumer_of_that_same_feedback'],
        'next_action':'Bind a current authorized follow-up task to an appropriate original processor and supported original delivery/update interface. Reuse prior_selected_clients for own historical identity only. An independently authorized contact history can suffice; a detailed service relationship is not imposed as a prerequisite for every informal follow-up.',
        'interface_boundary':'Generic interaction-session creation/message methods exist. Reviewed native lifecycle sessions are project-specific tender clarification, negotiation and final-account dispute; an arbitrary new session does not establish authorized client follow-up or client receipt.',
        'counts_as_micro_coverage':False,'overall_goal3_complete':False,'boundary':BOUNDARY}
