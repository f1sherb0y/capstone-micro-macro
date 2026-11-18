"""Original GOV-A12 consumes current native monthly work and own earlier outcomes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from pydantic import Field,model_validator

from integration.bank_financing_private import checked_result
from integration.government_approval_native_feedback import prior_approval_decisions
from integration.government_approval_native_learning import GovernmentApprovalFeedbackPlan,feedback_sources
from integration.government_feedback_actions import GovernmentFeedbackActionAssembler
from integration.government_feedback_results import GovernmentFeedbackResultWorker
from integration.government_monthly_native_sources import monthly_scope,prior_monthly_feedback,project_monthly_feedback_event
from integration.government_monthly_native_recovery import original_monthly_work,validate_saved_monthly_stage,recover_saved_monthly_proposal
from integration.module_host import module_factory_descriptor
from integration.government_monthly_business import result_judgment,result_operation
from src.actions.contracts.common import StrictRecord,TextId
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest
from src.methods.models import Digest


class GovernmentMonthlyPlan(StrictRecord):
    organization_id:TextId
    tick:int=Field(ge=1)
    feedback:GovernmentApprovalFeedbackPlan

    @model_validator(mode='after')
    def exact_context(self):
        context=self.feedback.context
        if (context.scope.kind!='organization'
                or context.scope.ref.id!=self.organization_id or context.business_time.offset!=self.tick):
            raise ValueError('Monthly feedback must retain its original own organization and business time')
        return self


class GovernmentMonthlySettings(StrictRecord):
    version:TextId
    file_path:TextId
    file_sha256:Digest
    allow_saved_recovery:bool=False


class GovernmentMonthlyApplication:
    VERSION='gba-v1-government-monthly-feedback.v4'
    PREFIX='government_monthly_native_request:'

    def __init__(self,*,parent,settings):
        self.parent=parent;self.assembly=parent.assembly
        self.settings=GovernmentMonthlySettings.model_validate(settings).model_copy(deep=True)
        self._check_file();doc=json.loads(Path(self.settings.file_path).read_bytes())
        if (set(doc)!={'schema_version','run_id','plans'} or doc['schema_version']!='government-monthly-feedback-input.v1'
                or doc['run_id']!=self.assembly.client.run_id):raise TaskConflict('Monthly feedback needs its pinned independent sources')
        self.plans=[GovernmentMonthlyPlan.model_validate(p) for p in doc['plans']]
        if not self.plans or len({(p.organization_id,p.tick) for p in self.plans})!=len(self.plans):
            raise TaskConflict('Monthly feedback requires unique original organization/time plans')
        self._plans_sha=task_digest([p.model_dump(mode='json') for p in self.plans])
        self._settings_sha=task_digest(self.settings.model_dump(mode='json'));self._code=self._descriptors();self._bound={}
        self.recovery_guard=parent.read_guard
        routes=self.assembly.client.native_routes
        if routes.settings.query_saved_monthly_on_error and not self.settings.allow_saved_recovery:
            raise TaskConflict('Monthly query on error requires explicit saved-result recovery authorization')
        if (not routes.settings.micro_government_monthly_feedback_scope
                or ('Government','decide_monthly_operation') in routes._proposals
                or ('Government','monthly_enterprise_operation') in routes._decisions):
            raise TaskConflict('Monthly feedback needs exclusive explicit original proposal/final ownership')
        self.assembler=GovernmentFeedbackActionAssembler(registry=parent.registry,organizations=parent.organizations,
            provider=self,macro_version='gba-public-2026-08-21',source_mode='formal',
            policy_version=parent.settings.policy_version,model_version=self.assembly.client.versions['model'])
        self.worker=GovernmentFeedbackResultWorker(store=self.assembly.client.tasks,snapshots=parent.snapshots,
            registry=parent.registry,client_version=self.VERSION,model_version=self.assembly.client.versions['model'],
            validate_invocation=self.validate_invocation,validate_wait=self.validate_wait,validate_recovery=self.validate_recovery)

    @staticmethod
    def _descriptors():
        return {name:module_factory_descriptor(function,'government-monthly-sources.v1') for name,function in
            [('scope',monthly_scope),('monthly_history',prior_monthly_feedback),('approval_history',prior_approval_decisions),
             ('sources',feedback_sources),('event_projection',project_monthly_feedback_event),
             ('original_recovery',original_monthly_work),('validate_recovery',validate_saved_monthly_stage),
             ('recover_proposal',recover_saved_monthly_proposal)]}

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest()!=self.settings.file_sha256:
            raise TaskConflict('Monthly feedback independent source bytes changed')

    def check_components(self):
        self._check_file()
        if (task_digest(self.settings.model_dump(mode='json'))!=self._settings_sha
                or task_digest([p.model_dump(mode='json') for p in self.plans])!=self._plans_sha
                or self._descriptors()!=self._code or self.recovery_guard is not self.parent.read_guard
                or self.worker.store is not self.assembly.client.tasks
                or self.worker.registry is not self.parent.registry or self.worker.snapshots is not self.parent.snapshots
                or self.assembler.organizations is not self.parent.organizations or self.assembler.provider is not self):
            raise TaskConflict('Monthly feedback changes its original source, worker or shared runtime')

    def _current(self,request):
        self.parent._check();scope=monthly_scope(self.assembly,request,purpose='propose')
        plans=[p for p in self.plans if (p.organization_id,p.tick)==(scope['organization_id'],scope['tick'])]
        if len(plans)!=1:raise TaskConflict('Monthly feedback lacks its exact independently authorized original plan')
        return plans[0],scope

    def history(self,*,organization_id,tick):
        return prior_monthly_feedback(self.assembly,organization_id=organization_id,tick=tick,
            read_guard=self.parent.read_guard,worker=self.worker,organizations=self.parent.organizations)

    def _sources(self,plan,request):
        _,scope=self._current(request)
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'prior_approval_decisions':prior_approval_decisions(self.assembly,organization_id=plan.organization_id,
                tick=plan.tick,read_guard=self.parent.read_guard,organizations=self.parent.organizations),
            'prior_monthly_feedback':self.history(organization_id=plan.organization_id,tick=plan.tick)}
        profile,=[r['value'] for r in plan.feedback.objects if r['ref']==plan.feedback.action_input['observation_profile_ref']]
        if profile.get('monthly_policy_ref') is not None:
            observed['macro_environment']=deepcopy(request.inputs['macro_environment'])
        return feedback_sources(plan,observed=observed),observed

    def project(self,*,context,organization_id,grants):
        plan,request=self._bound[task_digest(context.model_dump(mode='json'))];objects,_=self._sources(plan,request)
        if context!=plan.feedback.context or organization_id!=plan.organization_id:
            raise TaskConflict('Monthly feedback reading substitutes its own original context')
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21','state_version':'native-monthly:'+task_digest(objects),
            'read_token':context.read_token,'business_time':context.business_time.model_dump(mode='json'),
            'organization_id':organization_id,'objects':objects}

    def validate_invocation(self,row,prepared):
        plan,request=self._bound[prepared.context_sha256];self._current(request)
        if (prepared.context!=plan.feedback.context or prepared.action_input.model_dump(mode='json')!=plan.feedback.action_input
                or row['identity']['organization_id']!=plan.organization_id or prepared.runner.registry is not self.parent.registry):
            raise TaskConflict('Monthly feedback worker changes the original request or sources')
        prepared.reading.recheck();return True

    def validate_wait(self,*args,**kwargs):
        raise TaskConflict('Unresolved monthly feedback requires original source diagnosis; no native fallback')

    def _records(self):return self.parent._records(prefix=self.PREFIX)

    def _result(self,plan,record):
        saved=checked_result(self.worker,TaskIdentity(**record['identity']));payload=saved['result']['payload']
        from integration.government_history_authority import authorize_government_history
        authorize_government_history(self.assembly,TaskIdentity(**record['identity']),
            organizations=self.parent.organizations,tick=self.assembly.engine.current_tick,saved=saved)
        if (payload['choice']!='record_feedback' or payload['scope']!=plan.feedback.action_input['scope']
                or payload['feedback_refs']!=plan.feedback.action_input['feedback_refs']):
            raise TaskConflict('Monthly operation requires its actual original private record_feedback result')
        return saved

    def validate_recovery(self,row,saved,snapshot):
        return validate_saved_monthly_stage(self,row,saved,snapshot)

    def recover_saved_proposal(self,request):
        return recover_saved_monthly_proposal(self,request)

    @staticmethod
    def _proposal_response(request,scope,identity,saved):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        judgment=result_judgment(saved)
        description=saved['result']['payload']['interpretation'] if judgment is None else judgment.guidance or judgment.interpretation
        return AgentProposalResponseV1(request_id=request.request_id,action_type=result_operation(saved),accepted=True,
            utility=0.5,probability=1,reason=saved['result']['payload']['note'],
            data={'label':'Reviewed own regulatory feedback' if judgment is None else judgment.operation,'description':description},
            factors={'micro_action_id':'GOV-A12','micro_task_key':identity.key,'micro_result_sha256':saved['result_sha256'],
                'native_monthly_feedback_scope':scope})

    def propose(self,request):
        with self.parent.read_guard():
            plan,scope=self._current(request);objects,observed=self._sources(plan,request)
            key=self.PREFIX+task_digest([self.assembly.client.simulation_id,scope,request.request_id])
            if any(r['key']==key for r in self._records()):raise TaskConflict('Monthly feedback already claimed; query original transport')
            record=self.parent._save(key,{'key':key,'state':'preparing','scope':scope,'native_request':request.model_dump(mode='json'),
                'source_sha256':task_digest(objects),'observed':observed,'context':plan.feedback.context.model_dump(mode='json'),
                'action_input':plan.feedback.action_input,'native_evidence_ref':plan.feedback.native_evidence_ref.model_dump(mode='json')})
            self._bound[task_digest(record['context'])]=(plan,request.model_copy(deep=True))
            prepared=self.assembler.build(plan.feedback.context,**deepcopy(plan.feedback.action_input))
            identity=self.worker.register(prepared,request_id=key+':GOV-A12');record['identity']=identity.as_dict()
            record=self.parent._save(key,record);self.worker.execute(identity,prepared);saved=self._result(plan,record)
            response=self._proposal_response(request,scope,identity,saved)
            record.update(state='formed',result_sha256=saved['result_sha256'],proposal_response_sha256=task_digest(response.model_dump(mode='json')))
            self.parent._save(key,record);return response

    def decide(self,request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1,AgentDecisionResponseV1
        from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
        with self.parent.read_guard():
            self.parent._check();scope=monthly_scope(self.assembly,request,purpose='decide')
            record,=[r for r in self._records() if r['state']=='formed' and r['scope']==scope]
            original=AgentProposalRequestV1.model_validate(record['native_request']);plan,_=self._current(original)
            objects,observed=self._sources(plan,original);saved=self._result(plan,record)
            proposals=[t['output'] for t in self.assembly.client.tasks.for_organization(run_id=self.assembly.client.run_id,
                organization_id=plan.organization_id) if t['identity']['purpose']=='propose'
                and t['identity']['action_id']=='decide_monthly_operation' and t['state']=='output_formed'
                and t['output'].get('factors',{}).get('native_monthly_feedback_scope')==scope]
            if len(proposals)!=1:raise TaskConflict('Monthly feedback lost its original unique formed proposal')
            proposal=proposals[0];support=request.decision_support
            if (task_digest(objects)!=record['source_sha256'] or observed!=record['observed']
                    or saved['result_sha256']!=record['result_sha256'] or task_digest(proposal)!=record['proposal_response_sha256']
                    or support.get('decision_factors')!=proposal['factors'] or support.get('accepted') is not True
                    or support.get('action_type')!=result_operation(saved) or proposal['accepted'] is not True
                    or result_operation(saved) not in request.constraints.allowed_actions):
                raise TaskConflict('Monthly feedback final changes its source, deciding result or original proposal')
            response=AgentDecisionResponseV1(request_id=request.request_id,agent_id=plan.organization_id,
                action_type=result_operation(saved),decision=True,reason=proposal['reason'],
                data={**proposal['factors'],'proposal_response_sha256':task_digest(proposal)})
            ExternalAgentDecisionProvider._validated_action(request,response);return response

    def evidence(self):
        self.check_components()
        return {'version':self.VERSION,'source_file_sha256':self.settings.file_sha256,'requests':self._records(),
            'saved_recovery':{'enabled':self.settings.allow_saved_recovery,
                'entry':'assembly.client.recover_proposal(original_request)',
                'boundary':'Queries the same current original request and durable completed result only; no processor replay, engine restart or resubmission.'},
            'limits':'Original GOV-A12 privately records authenticated own approval and strictly earlier monthly outcomes. '
                'Only the original native scheduler executes the background operation and any random capability update. '
                'No policy parameter, formal regulation, project, resource or financial ledger is changed by this micro action.'}
