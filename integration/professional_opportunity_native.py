"""Original private A01 interest precedes, but never replaces, professional A02."""
from copy import deepcopy
import json
from typing import Literal

from pydantic import model_validator

from integration.architect_opportunity_actions import ArchitectOpportunityActionAssembler
from integration.architect_opportunity_results import ArchitectOpportunityResultWorker
from integration.engineer_opportunity_actions import EngineerOpportunityActionAssembler
from integration.engineer_opportunity_results import EngineerOpportunityResultWorker
from integration.qs_market_actions import QSMarketActionAssembler
from integration.qs_market_results import QSMarketResultWorker
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, StrictRecord, ref_type
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


COMPONENTS = {
    'Architect': (ArchitectOpportunityActionAssembler, ArchitectOpportunityResultWorker),
    'Engineer': (EngineerOpportunityActionAssembler, EngineerOpportunityResultWorker),
    'QS': (QSMarketActionAssembler, QSMarketResultWorker),
}


class ProfessionalOpportunityPlan(StrictRecord):
    context: ActionContext
    action_input: dict
    objects: list[dict]
    opportunity_ref: ref_type('Opportunity')
    native_evidence_ref: ref_type('Evidence')
    handoff_evidence_ref: ref_type('Evidence')
    non_interest_policy: Literal['require_resolution', 'decline_new_work'] = 'require_resolution'

    @model_validator(mode='after')
    def original_sources(self):
        if (len({task_digest(row['ref']) for row in self.objects}) != len(self.objects)
                or self.native_evidence_ref == self.handoff_evidence_ref):
            raise ValueError('Professional opportunity needs distinct original sources and evidence points')
        return self


class ProfessionalOpportunityStep:
    VERSION = 'gba-v1-professional-opportunity.v3'

    def __init__(self, application):
        self.application = application
        self.assemblers, self.workers = {}, {}
        for role, (assembler, worker) in COMPONENTS.items():
            self.assemblers[role] = assembler(registry=application.registry, organizations=application.organizations,
                provider=application, macro_version='gba-public-2026-08-21', source_mode='formal',
                policy_version=application.settings.policy_version, model_version=application.assembly.client.versions['model'])
            self.workers[role] = worker(store=application.assembly.client.tasks, snapshots=application.snapshots,
                registry=application.registry, client_version=self.VERSION+':'+role,
                model_version=application.assembly.client.versions['model'],
                validate_invocation=application.validate_invocation, validate_wait=application.validate_wait)
        self._descriptors = self._implementations()

    def _implementations(self):
        return {name:module_factory_descriptor(getattr(self, name), self.VERSION)
            for name in ('sources','execute','handoff','_record')}

    def check(self):
        app = self.application
        if self._implementations() != self._descriptors:
            raise TaskConflict('Professional opportunity substituted its original source or continuation implementation')
        for role in COMPONENTS:
            if (self.workers[role].store is not app.assembly.client.tasks
                    or self.workers[role].snapshots is not app.snapshots
                    or self.workers[role].registry is not app.registry
                    or self.assemblers[role].organizations is not app.organizations
                    or self.assemblers[role].provider is not app):
                raise TaskConflict('Professional opportunity changed its shared source, authority or worker')

    def sources(self, plan, request):
        """Bind the current received request; independently declared permissions remain original."""
        original = plan.opportunity
        selected = (original.action_input['opportunity_refs'] if plan.role=='QS'
            else [original.action_input['opportunity_ref']])
        if selected != [original.opportunity_ref.model_dump(mode='json')]:
            raise TaskConflict('Professional discovery must assess the exact original received opportunity')
        project = self.application.assembly.engine.projects[plan.project_id]
        observed = {'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'organization_id':plan.organization_id, 'role':plan.role, 'project_id':project.project_id,
            'owner_id':project.owner_id, 'owner_actor_id':self.application.organizations.get(project.owner_id).actor_id,
            'region':project.region, 'object_type':project.project_type,
            'tick':plan.tick}
        objects = deepcopy(original.objects)
        opportunity, = [row['value'] for row in objects
            if row['ref']==original.opportunity_ref.model_dump(mode='json')]
        recipients = opportunity['recipient_ids'] if plan.role=='QS' else opportunity['recipient_actor_ids']
        if (opportunity['scope'] != plan.context.scope.model_dump(mode='json')
                or opportunity['inviting_actor_id'] != observed['owner_actor_id']
                or recipients != [plan.context.actor_id]
                or original.native_evidence_ref.model_dump(mode='json') not in opportunity['evidence_refs']):
            raise TaskConflict('Professional opportunity changes its actual received project, inviter or recipient')
        if plan.role != 'QS':
            terms, = [row['value'] for row in plan.objects if row['ref']==plan.action_input['terms_ref']]
            if (opportunity['recipient_organization_ids'] != [plan.organization_id]
                    or any(opportunity[field]!=terms[field] for field in ('region_id','object_type','service_code'))):
                raise TaskConflict('Professional opportunity changes original project or offered service scope')
        rows = [row['value'] for row in objects
            if row['ref']==original.native_evidence_ref.model_dump(mode='json')]
        if len(rows)!=1 or rows[0].get('content_hash') is not None:
            raise TaskConflict('Professional opportunity needs one declared unbound observation evidence')
        rows[0]['content_hash'] = task_digest(observed)
        evidence = EvidenceRecord.model_validate(rows[0])
        if evidence.source_kind!='synthetic' or evidence.basis_kind!='observed':
            raise TaskConflict('Professional simulator opportunity must preserve its observed synthetic provenance')
        schemas = self.assemblers[plan.role].SOURCE_SCHEMAS()
        objects = [{'ref':row['ref'], 'value':schemas.validate_projection(
            Reference.model_validate(row['ref']),row['value']).model_dump(mode='json')} for row in objects]
        return objects, observed

    def execute(self, plan, request, record):
        """Execute once inside the original native request; persist identity before processing."""
        app = self.application
        source = plan.opportunity
        app._bound[task_digest(source.context.model_dump(mode='json'))] = (plan, request.model_copy(deep=True))
        objects, observed = self.sources(plan, request)
        prepared = self.assemblers[plan.role].build(source.context, **deepcopy(source.action_input))
        worker = self.workers[plan.role]
        identity = worker.register(prepared, request_id='professional-opportunity:'+app._key(request))
        record.update(opportunity_identity=identity.as_dict(), opportunity_source_sha256=task_digest(objects),
            opportunity_observed=observed)
        app._save(request, record)
        outcome = worker.execute(identity, prepared)
        record['opportunity_result_sha256'] = task_digest(outcome['result'])
        app._save(request, record)
        # This exact saved result is also read when the later A02 source is
        # projected and when its native final decision is returned.
        self.handoff(plan, request)

    def handoff(self, plan, request):
        """Authenticate saved own interest; no message, appointment or acceptance is implied."""
        app = self.application
        app._check()
        source = plan.opportunity
        key, record = self._record(plan, request)
        if record is None or 'opportunity_identity' not in record:
            raise TaskConflict('Professional A02 requires its original completed opportunity result')
        identity = TaskIdentity(**record['opportunity_identity'])
        worker = self.workers[plan.role]
        saved = worker.get_record(identity)
        if saved is None:
            raise TaskConflict('Professional opportunity handoff has no saved original result')
        task = app.assembly.client.tasks.get(identity)
        snapshot = app.snapshots.get(identity)
        objects, observed = self.sources(plan, request)
        grants = app.organizations.grants(source.context, plan.role.upper()+'-A01', plan.role)
        permitted = {ref.key() for grant in grants for ref in grant.readable_refs} & {
            ref.key() for ref in source.context.visible_refs}
        if any(Reference.model_validate(row['ref']).key() not in permitted for row in saved['source_reading']):
            raise TaskConflict('Professional opportunity handoff lost current source-reading permission')
        if (identity.organization_id != plan.organization_id or identity.run_id!=plan.context.run_id
                or identity.purpose!='action' or identity.request_id!='professional-opportunity:'+key
                or snapshot['context']!=source.context.model_dump(mode='json')
                or snapshot['action_input']!=source.action_input
                or saved is None or task['state']!='output_formed' or task['output']!=saved['result']
                or saved['result_sha256']!=record.get('opportunity_result_sha256')
                or record['opportunity_source_sha256']!=task_digest(objects) or record['opportunity_observed']!=observed):
            raise TaskConflict('Professional opportunity handoff lost its original request, source or formed result')
        expected = {task_digest(row['ref']):row['value'] for row in objects}
        if {task_digest(row['ref']):row['projection'] for row in saved['source_reading']} != expected:
            raise TaskConflict('Professional opportunity handoff changed its original consumed sources')
        if saved['result']['kind']!='completed':
            raise TaskConflict('Professional opportunity has no original interest permitting later A02 review')
        payload = saved['result']['payload']
        choice = payload['choice']
        if choice == 'express_interest':
            if payload.get('recipient_id') != observed['owner_actor_id']:
                raise TaskConflict('Professional interest changes its original actual Owner recipient')
        elif (choice != ('decline' if plan.role == 'Engineer' else 'ignore')
                or source.non_interest_policy != 'decline_new_work'):
            raise TaskConflict('Professional opportunity has no original interest permitting later A02 review')
        handoff = {'identity':identity.as_dict(), 'result_sha256':saved['result_sha256'],
            'record_sha256':saved['record_sha256'], 'source_reading_sha256':saved['source_reading_sha256'],
            'native_request_sha256':observed['native_request_sha256'],
            'choice':choice}
        if choice == 'express_interest':
            handoff['recipient_id'] = observed['owner_actor_id']
        else:
            # This is a private instruction for the original A02 evaluation,
            # not an A01 message or a formal native rejection by itself.
            handoff['non_interest_policy'] = source.non_interest_policy
        return handoff

    def _record(self, plan, request):
        """Read the original point after legitimate native event-log appends.

        The incoming propose path still requires the full current snapshot.
        An Owner or later feedback consumer reads an already completed private
        source; it never creates a replacement invocation at the newer point.
        """
        app = self.application
        scope = {'project_id':plan.project_id,'tick':plan.tick,'role':plan.role}
        key = app.PREFIX+task_digest([app.assembly.client.simulation_id,plan.organization_id,request.request_id,scope])
        original = request.inputs.get('project',{})
        current = app.assembly.engine.projects[plan.project_id].model_dump(mode='json')
        if (request.agent.agent_id!=plan.organization_id or request.agent.role!=plan.role
                or request.operation!='consider_appointment'
                or any(original.get(field)!=current[field] for field in
                    ('project_id','owner_id','region','project_type','initial_budget'))
                or current['event_log'][:len(original.get('event_log',[]))]!=original.get('event_log')):
            raise TaskConflict('Professional opportunity source lost its original native project or event prefix')
        with app.assembly.client.tasks._lock:
            row = app.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()
        record = None if row is None else json.loads(row[0])
        if record is not None and (
                record['record_sha256']!=task_digest({k:v for k,v in record.items() if k!='record_sha256'})
                or record['source_file_sha256']!=app.settings.file_sha256
                or record['native_request']!=request.model_dump(mode='json')
                or record['request_sha256']!=task_digest(request.model_dump(mode='json'))):
            raise TaskConflict('Professional opportunity changed its saved original request or source file')
        return key, record
