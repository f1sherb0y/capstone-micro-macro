"""Original GOV-A02 drives native regulatory review willingness, not case filing."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from typing import Literal
from pathlib import Path

from pydantic import Field, model_validator

from integration.bank_financing_private import checked_result, evidence_binding
from integration.contractor_tender_authority_runtime import TenderAuthorityRuntimeSettings, build_authority_runtime
from integration.government_intake_actions import GovernmentIntakeActionAssembler
from integration.government_intake_results import GovernmentIntakeResultWorker
from integration.government_intake_scope import government_scope
from integration.government_intake_feedback import prior_review_decisions
from integration.government_native_wait import validate_pending_result, completed_result_or_wait
from integration.government_intake_native_recovery import (
    original_intake_work, validate_saved_intake_stage, recover_saved_intake_proposal)
from integration.government_approval_native import GovernmentApprovalApplication, GovernmentApprovalSettings
from integration.government_monthly_native import GovernmentMonthlyApplication,GovernmentMonthlySettings
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension, module_client_implementation, module_factory_descriptor
from src.actions.contracts.common import ActionContext, EvidenceRecord, Measured, StrictRecord, TextId, ref_type
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.models import Digest


class GovernmentIntakePlan(StrictRecord):
    organization_id: TextId
    project_id: TextId
    tick: int=Field(ge=1)
    review_phase: Literal['design','completion']='design'
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    utility: Measured
    probability: Measured

    @model_validator(mode='after')
    def original_context(self):
        c=self.context
        if (c.contract_ref.id!='GOV-A02' or c.scope.kind!='project'
                or c.scope.ref.id!=self.project_id or c.business_time.offset!=self.tick or c.execution_mode=='offline_fixture'
                or self.action_input.get('scope')!=c.scope.model_dump(mode='json')
                or len({task_digest(r['ref']) for r in self.objects})!=len(self.objects)):
            raise ValueError('Regulatory intake changes its original actor, action, project, time or source identities')
        return self


class GovernmentIntakeSettings(StrictRecord):
    version: TextId
    policy_version: TextId
    authority: TenderAuthorityRuntimeSettings
    file_path: TextId
    file_sha256: Digest
    approval: GovernmentApprovalSettings | None = None
    monthly: GovernmentMonthlySettings | None = None
    allow_saved_recovery: bool = False


class GovernmentIntakeApplication:
    VERSION='gba-v1-government-intake.v16'
    PREFIX='government_intake_native_request:'

    def __init__(self,*,assembly,settings,authority=None,install=True):
        self.assembly=assembly;self.settings=GovernmentIntakeSettings.model_validate(settings).model_copy(deep=True)
        self._check_file();doc=json.loads(Path(self.settings.file_path).read_bytes())
        if (set(doc)!={'schema_version','run_id','plans'} or doc['schema_version']!='government-intake-input.v1'
                or doc['run_id']!=assembly.client.run_id):
            raise TaskConflict('Regulatory inputs change their declared original schema or run')
        self.plans=[GovernmentIntakePlan.model_validate(p) for p in doc['plans']]
        keys=[(p.organization_id,p.project_id,p.tick,p.review_phase) for p in self.plans]
        if not keys or len(keys)!=len(set(keys)) or any(p.context.run_id!=doc['run_id'] for p in self.plans):
            raise TaskConflict('Regulatory intake requires unique explicit current source selectors')
        self._plans_sha=task_digest([p.model_dump(mode='json') for p in self.plans])
        self._settings_sha=task_digest(self.settings.model_dump(mode='json'))
        self._owns_authority=authority is None
        self.authority=authority or build_authority_runtime(assembly=assembly,settings=self.settings.authority)
        if self.authority.assembly is not assembly or self.authority.settings!=self.settings.authority:
            raise TaskConflict('Regulatory shared authority must match its exact declared assembly and snapshot')
        self.registry,self.organizations=self.authority.registry,self.authority.organizations
        self.read_guard=self.authority.read_guard;self.snapshots=InvocationSnapshotStore(assembly.client.tasks)
        self._bound={};self._implementation=None
        self._wait_code=self._wait_descriptor()
        self.recovery_guard=self.read_guard
        self._recovery_code=self._recovery_descriptor()
        client=assembly.client;routes=client.native_routes
        self._other_decision=client.decision_handler
        self._native_settings=task_digest(routes.settings.model_dump(mode='json'))
        try:
            if routes.settings.query_saved_intake_on_error and not self.settings.allow_saved_recovery:
                raise TaskConflict('Intake query on error requires explicit saved-result recovery authorization')
            if (not routes.settings.micro_government_intake_scope
                    or ('Government','consider_review_assignment') in routes._proposals
                    or ('Government','government_review_assignment') in routes._decisions):
                raise TaskConflict('Regulatory micro intake needs exclusive declared proposal/final ownership')
            self.assembler=GovernmentIntakeActionAssembler(registry=self.registry,organizations=self.organizations,
                provider=self,macro_version='gba-public-2026-08-21',source_mode='formal',
                policy_version=self.settings.policy_version,model_version=client.versions['model'])
            self.worker=GovernmentIntakeResultWorker(store=client.tasks,snapshots=self.snapshots,registry=self.registry,
                client_version=self.VERSION,model_version=client.versions['model'],
                validate_invocation=self.validate_invocation,validate_wait=self.validate_wait,
                validate_recovery=self.validate_recovery)
            if routes.settings.micro_government_approval_scope!=(self.settings.approval is not None):
                raise TaskConflict('Micro approval scope requires its explicit independent source configuration')
            self.approval=(None if self.settings.approval is None else
                GovernmentApprovalApplication(parent=self,settings=self.settings.approval,install=False))
            if routes.settings.micro_government_monthly_feedback_scope!=(self.settings.monthly is not None):
                raise TaskConflict('Monthly feedback requires its explicit source configuration')
            self.monthly=None if self.settings.monthly is None else GovernmentMonthlyApplication(parent=self,settings=self.settings.monthly)
            if install:self.install()
        except Exception:
            if self._owns_authority:self.authority.close()
            raise

    def proposal_bindings(self):
        result={('Government','consider_review_assignment'):self.propose}
        if self.approval is not None:
            result[('Government','decide_approval')]=self.approval.propose
        if self.monthly is not None:result[('Government','decide_monthly_operation')]=self.monthly.propose
        return result

    def seal_client_binding(self):
        client=self.assembly.client
        with client._lock:
            if (self._implementation is not None or client._calls or client._request_hashes
                    or client.binding_installation_blocked()
                    or any(client.proposal_handlers.get(key)!=handler for key,handler in self.proposal_bindings().items())):
                raise TaskConflict('Regulatory client binding must be sealed once before requests, preserving every owned handler')
            self._implementation=module_client_implementation(client)

    def install(self):
        client=self.assembly.client
        with client._lock:
            for (role,operation),handler in self.proposal_bindings().items():
                client.bind_proposal_handler(role=role,operation=operation,handler=handler,
                    client_version=self.VERSION+':'+operation)
            client.decision_handler=self.decide
            self.seal_client_binding()

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest()!=self.settings.file_sha256:
            raise TaskConflict('Regulatory independent sources changed their pinned bytes')

    def _check(self):
        self.assembly._validate_components();self._check_file()
        if (task_digest(self.settings.model_dump(mode='json'))!=self._settings_sha
                or task_digest([p.model_dump(mode='json') for p in self.plans])!=self._plans_sha
                or task_digest(self.assembly.client.native_routes.settings.model_dump(mode='json'))!=self._native_settings
                or self._implementation is None or module_client_implementation(self.assembly.client)!=self._implementation
                or self._wait_descriptor()!=self._wait_code
                or self._recovery_descriptor()!=self._recovery_code or self.recovery_guard is not self.read_guard
                or self.worker.validate_recovery!=self.validate_recovery
                or self.worker.validate_wait!=self.validate_wait
                or self.worker.store is not self.assembly.client.tasks or self.worker.registry is not self.registry
                or self.assembler.organizations is not self.organizations):
            raise TaskConflict('Regulatory host changes its original plans, sources, handlers or shared runtime')
        if self.approval is not None:self.approval.check_components()
        if self.monthly is not None:self.monthly.check_components()

    def _current(self,request):
        self._check();scope=government_scope(self.assembly,request,purpose='propose')
        if request.operation!='consider_review_assignment':raise TaskConflict('Regulatory micro intake needs its original assignment request')
        plans=[p for p in self.plans if (p.organization_id,p.project_id,p.tick)==
            (request.agent.agent_id,scope['project_id'],scope['tick']) and p.review_phase==
                ('completion' if scope['purpose']=='completion_review_assignment' else 'design')]
        if len(plans)!=1:raise TaskConflict('Regulatory request has no exact independent current source plan')
        plan=plans[0];project=self.assembly.engine.projects[plan.project_id]
        grants=self.organizations.grants(plan.context,'GOV-A02','Government')
        submission,=[r['value'] for r in plan.objects if r['ref']==plan.action_input['submission_ref']]
        if (not grants or grants[0].organization_id!=plan.organization_id or submission['applicant_id']!=project.owner_id
                or submission['recipient_organization_id']!=plan.organization_id
                or submission['project_region_id']!={'state':'known','value':project.region}):
            raise TaskConflict('Regulatory sources change their actual native applicant, region, recipient or authority')
        return plan,scope

    def _sources(self,plan,request):
        objects=deepcopy(plan.objects)
        observed={'scope':government_scope(self.assembly,request,purpose='propose'),
            'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'prior_review_decisions':prior_review_decisions(self.assembly,organization_id=plan.organization_id,
                tick=plan.tick,read_guard=self.read_guard,organizations=self.organizations)}
        evidence_binding(objects,plan.native_evidence_ref.model_dump(mode='json'),observed)
        return objects,observed

    def project(self,*,context,organization_id,grants):
        plan,request=self._bound[task_digest(context.model_dump(mode='json'))]
        self._current(request)
        if organization_id!=plan.organization_id:raise TaskConflict('Regulatory view changes its original private recipient')
        objects,_=self._sources(plan,request)
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21','state_version':'native-government-intake:'+task_digest(objects),
            'read_token':context.read_token,'business_time':context.business_time.model_dump(mode='json'),
            'organization_id':organization_id,'objects':objects}

    def validate_invocation(self,row,prepared):
        plan,request=self._bound[prepared.context_sha256];self._current(request)
        if (row['identity']['organization_id']!=plan.organization_id or prepared.context!=plan.context
                or prepared.runner.registry is not self.registry):raise TaskConflict('Regulatory worker substitutes its original invocation')
        prepared.reading.recheck();return True

    @staticmethod
    def _wait_descriptor():
        return [module_factory_descriptor(fn,'government-native-wait.v1')
            for fn in (validate_pending_result,completed_result_or_wait)]

    def validate_wait(self,row,result,conditions):
        identity=TaskIdentity(**row['identity'])
        bound=self._bound.get(identity.context_sha256)
        if bound is None:raise TaskConflict('Regulatory wait lost its original intake binding')
        plan,request=bound
        self._current(request)
        records=[r for r in self._records() if r.get('identity')==identity.as_dict()]
        if len(records)!=1:raise TaskConflict('Regulatory wait lost its original intake workflow')
        record=records[0];objects,observed=self._sources(plan,request)
        if record['native_request']!=request.model_dump(mode='json') or record['observed']!=observed:
            raise TaskConflict('Regulatory wait changes its original intake request or observations')
        return validate_pending_result(parent=self,worker=self.worker,context=plan.context,
            objects=objects,source_sha256=record['source_sha256'],row=row,result=result,conditions=conditions)

    def _records(self,*,prefix=None):
        with self.assembly.client.tasks._lock:
            rows=[json.loads(v) for v, in self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key LIKE ?',((prefix or self.PREFIX)+'%',))]
        if any(r['record_sha256']!=task_digest({k:v for k,v in r.items() if k!='record_sha256'}) for r in rows):
            raise TaskConflict('Regulatory original technical request record changed')
        return rows

    def _save(self,key,value):
        value=deepcopy(value);value['record_sha256']=task_digest({k:v for k,v in value.items() if k!='record_sha256'})
        with self.assembly.client.tasks._transaction():
            self.assembly.client.tasks._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',(key,canonical(value)))
        return value

    def _summary(self,result):
        choice=result['payload']['choice']
        if choice not in {'accept_for_processing','decline_processing'}:
            raise TaskConflict('Correction, referral, acknowledgment and unresolved intake cannot become native regulatory acceptance')
        accepted=choice=='accept_for_processing'
        return accepted,'accept_regulatory_review' if accepted else 'defer_regulatory_review'

    @staticmethod
    def _recovery_descriptor():
        return [module_factory_descriptor(fn,'government-intake-saved-recovery.v1')
            for fn in (original_intake_work,validate_saved_intake_stage,recover_saved_intake_proposal)]

    def validate_recovery(self,row,saved,snapshot):
        return validate_saved_intake_stage(self,row,saved,snapshot)

    def recover_saved_proposal(self,request):
        return recover_saved_intake_proposal(self,request)

    def _proposal_response(self,plan,request,scope,identity,saved,prepared):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        accepted,action=self._summary(saved['result'])
        for metric,unit in [(plan.utility,'score'),(plan.probability,'probability')]:
            if (metric.unit!=unit or not 0<=Decimal(metric.value)<=1
                    or not isinstance(prepared.reading.resolve(metric.basis_ref),EvidenceRecord)):
                raise TaskConflict('Regulatory native indicators require original evidence and bounded units')
        prepared.reading.recheck()
        return AgentProposalResponseV1(request_id=request.request_id,action_type=action,accepted=accepted,
            utility=float(plan.utility.value),probability=float(plan.probability.value),reason=saved['result']['payload']['note'],
            data={},factors={'micro_action_id':'GOV-A02','micro_task_key':identity.key,'micro_result_sha256':saved['result_sha256'],
                'native_government_scope':scope})

    def propose(self,request):
        with self.read_guard():
            plan,scope=self._current(request)
            key=self.PREFIX+task_digest([self.assembly.client.simulation_id,plan.organization_id,scope,request.request_id])
            if any(r['key']==key for r in self._records()):raise TaskConflict('Regulatory request already claimed; recover its original transport')
            record=self._save(key,{'key':key,'scope':scope,'state':'preparing','native_request':request.model_dump(mode='json')})
            self._bound[task_digest(plan.context.model_dump(mode='json'))]=(plan,request.model_copy(deep=True))
            objects,observed=self._sources(plan,request)
            prepared=self.assembler.build(plan.context,**deepcopy(plan.action_input))
            identity=self.worker.register(prepared,request_id=key+':GOV-A02')
            record.update(identity=identity.as_dict(),source_sha256=task_digest(objects),observed=observed)
            record=self._save(key,record);self.worker.execute(identity,prepared)
            saved=completed_result_or_wait(parent=self,worker=self.worker,identity=identity,
                key=key,record=record,stage='intake')
            record.update(result_sha256=saved['result_sha256']);record=self._save(key,record)
            response=self._proposal_response(plan,request,scope,identity,saved,prepared)
            record.update(state='formed',proposal_response_sha256=task_digest(response.model_dump(mode='json')))
            self._save(key,record);return response

    def decide(self,request):
        if self.monthly is not None and (request.agent.role,request.decision_type)==('Government','monthly_enterprise_operation'):
            return self.monthly.decide(request)
        if self.approval is not None and request.agent.role=='Government' and request.decision_type in {
                'government_design_approval','government_completion_approval'}:
            return self.approval.decide(request)
        if (request.agent.role,request.decision_type)!=('Government','government_review_assignment'):return self._other_decision(request)
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1,AgentDecisionResponseV1
        with self.read_guard():
            self._check();scope=government_scope(self.assembly,request,purpose='decide')
            record,=[r for r in self._records() if r['state']=='formed' and r['scope']==scope
                and r['native_request']['agent']['agent_id']==request.agent.agent_id]
            original=AgentProposalRequestV1.model_validate(record['native_request']);plan,_=self._current(original)
            saved=checked_result(self.worker,TaskIdentity(**record['identity']));objects,observed=self._sources(plan,original)
            accepted,action=self._summary(saved['result']);support=request.decision_support
            proposal,=[t['output'] for t in self.assembly.client.tasks.for_organization(run_id=plan.context.run_id,organization_id=plan.organization_id)
                if t['identity']['purpose']=='propose' and t['identity']['action_id']=='consider_review_assignment' and t['state']=='output_formed'
                and t['output'].get('factors',{}).get('native_government_scope')==scope]
            if (task_digest(objects)!=record['source_sha256'] or observed!=record['observed'] or saved['result_sha256']!=record['result_sha256']
                    or task_digest(proposal)!=record['proposal_response_sha256'] or support.get('decision_factors')!=proposal['factors']
                    or support.get('accepted')!=accepted or support.get('action_type')!=action or action not in request.constraints.allowed_actions):
                raise TaskConflict('Regulatory final confirmation changes its original micro result, proposal or sources')
            return AgentDecisionResponseV1(request_id=request.request_id,agent_id=plan.organization_id,action_type=action,decision=accepted,
                reason=saved['result']['payload']['note'],data={**proposal['factors'],'proposal_response_sha256':record['proposal_response_sha256']})

    def evidence(self):
        with self.read_guard():
            self._check()
            return {'version':self.VERSION,'source_file_sha256':self.settings.file_sha256,'requests':self._records(),
                'saved_result_recovery':{'enabled':self.settings.allow_saved_recovery,'code':self._recovery_code,
                    'entry':'assembly.client.recover_proposal(original_request)',
                    'limits':'Only original completed intake in the same current native call; no supplement receipt, processor replay or failed-tick restart.'},
                **({'approval':self.approval.evidence()} if self.approval is not None else {}),
                **({'monthly':self.monthly.evidence()} if self.monthly is not None else {}),
                'native_routes':self.assembly.client.native_routes.evidence(),
                'limits':'GOV-A02 preparation maps only to native review willingness. Optional approval coverage is reported separately. No formal case filing or detailed permit ledger is created.'}


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Explicit regulatory development composition requires offline mode')
    assembly.client.native_routes.attach(assembly)
    app=GovernmentIntakeApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
