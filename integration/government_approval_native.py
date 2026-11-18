"""Original GOV-A04/A07 drive native design and completion approval requests."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from typing import Literal
from pathlib import Path

from pydantic import Field, model_validator

from integration.bank_financing_private import checked_result, evidence_binding
from integration.government_approval_native_sources import current_review_assignment, decision_sources, ref_digest
from integration.government_review_actions import GovernmentReviewActionAssembler
from integration.government_review_results import GovernmentReviewResultWorker
from integration.government_decision_actions import GovernmentDecisionActionAssembler
from integration.government_decision_results import GovernmentDecisionResultWorker
from integration.government_intake_scope import government_scope
from integration.government_approval_native_feedback import prior_approval_decisions
from integration.government_approval_native_learning import GovernmentApprovalFeedbackPlan, feedback_sources, feedback_origin
from integration.government_feedback_actions import GovernmentFeedbackActionAssembler
from integration.government_feedback_results import GovernmentFeedbackResultWorker
from integration.government_approval_native_recovery import recover_saved_proposal,validate_saved_stage
from integration.government_native_wait import validate_pending_result, completed_result_or_wait
from integration.unstarted_action_continuation import execute_original_stage
from integration.government_native_outcome_query import query_native_approval_outcome
from integration.government_completion_native_feedback import own_completion_outcomes
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import ActionContext, EvidenceRecord, Measured, StrictRecord, TextId, ref_type
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.methods.models import Digest


class GovernmentApprovalCheckLink(StrictRecord):
    review_rule_ref: ref_type('Rule')
    decision_check_ref: ref_type('DecisionCheck')
    decision_finding_ref: ref_type('MethodResult')


class GovernmentApprovalOutcomePolicy(StrictRecord):
    approve_rule_ref: ref_type('Rule')
    approve_effect_ref: ref_type('EffectRule')
    revision_rule_ref: ref_type('Rule')
    revision_effect_ref: ref_type('EffectRule')
    approve_reason: TextId
    revision_reason: TextId


class GovernmentApprovalPlan(StrictRecord):
    organization_id: TextId
    project_id: TextId
    tick: int=Field(ge=1)
    review_phase: Literal['design','completion']='design'
    assignment_tick: int | None=Field(default=None,ge=1)
    review_context: ActionContext
    decision_context: ActionContext
    review_input: dict
    decision_input: dict
    review_objects: list[dict]
    decision_objects: list[dict]
    review_native_evidence_ref: ref_type('Evidence')
    decision_native_evidence_ref: ref_type('Evidence')
    handoff_evidence_ref: ref_type('Evidence')
    assessment_ref: ref_type('Assessment')
    submission_content: dict
    submission_evidence_ref: ref_type('Evidence')
    check_links: list[GovernmentApprovalCheckLink]=Field(min_length=1)
    outcome_policy: GovernmentApprovalOutcomePolicy
    utility: Measured
    probability: Measured
    feedback: GovernmentApprovalFeedbackPlan | None=None

    @model_validator(mode='after')
    def original_contexts(self):
        if self.assignment_tick is not None and self.assignment_tick>self.tick:
            raise ValueError('Approval cannot consume a future regulatory assignment')
        if self.feedback is not None:
            current=self.feedback.context
            if (current.actor_id!=self.review_context.actor_id or current.run_id!=self.review_context.run_id
                    or current.scope!=self.review_context.scope or current.business_time!=self.review_context.business_time
                    or current.function_ref!=self.review_context.function_ref):
                raise ValueError('Approval feedback changes its original organization, project, time or function')
        for action,context,inputs,objects in [('GOV-A04',self.review_context,self.review_input,self.review_objects),
                ('GOV-A07',self.decision_context,self.decision_input,self.decision_objects)]:
            if (context.actor_id!=self.review_context.actor_id or context.contract_ref.id!=action
                    or context.scope.kind!='project' or context.scope.ref.id!=self.project_id
                    or context.business_time.offset!=self.tick or context.execution_mode=='offline_fixture'
                    or context.scope.model_dump(mode='json')!=inputs.get('scope')
                    or len({task_digest(r['ref']) for r in objects})!=len(objects)):
                raise ValueError('Approval changes its original actor, action, project, time or source identities')
        if (self.review_context.function_ref!=self.decision_context.function_ref
                or self.review_context.run_id!=self.decision_context.run_id
                or self.review_context.business_time!=self.decision_context.business_time
                or self.review_input['case_ref']!=self.decision_input['case_ref']
                or self.review_input['submission_ref']!=self.decision_input['current_submission_ref']
                or self.decision_input['assessment_refs']!=[self.assessment_ref.model_dump(mode='json')]
                or any(len({ref_digest(getattr(l,f)) for l in self.check_links})!=len(self.check_links)
                    for f in ('review_rule_ref','decision_check_ref','decision_finding_ref'))):
            raise ValueError('Approval changes its original review/decision scope or exact handoff identities')
        return self


class GovernmentApprovalSettings(StrictRecord):
    version: TextId
    file_path: TextId
    file_sha256: Digest
    allow_saved_recovery: bool=False
    continue_unstarted_actions_on_error: bool=False


class GovernmentApprovalApplication:
    PREFIX='government_approval_native_request:'

    def __init__(self,*,parent,settings,install=True):
        self.parent=parent;self.assembly=parent.assembly
        self.settings=GovernmentApprovalSettings.model_validate(settings).model_copy(deep=True)
        self._check_file();doc=json.loads(Path(self.settings.file_path).read_bytes())
        if (set(doc)!={'schema_version','run_id','plans'} or doc['schema_version']!='government-approval-input.v1'
                or doc['run_id']!=self.assembly.client.run_id):
            raise TaskConflict('Approval sources change their original schema or run')
        self.plans=[GovernmentApprovalPlan.model_validate(p) for p in doc['plans']]
        keys=[(p.organization_id,p.project_id,p.tick,p.review_phase) for p in self.plans]
        if not keys or len(keys)!=len(set(keys)) or any(p.review_context.run_id!=doc['run_id'] for p in self.plans):
            raise TaskConflict('Approval needs unique explicit current source plans')
        self._plans_sha=task_digest([p.model_dump(mode='json') for p in self.plans])
        self._settings_sha=task_digest(self.settings.model_dump(mode='json'));self._bound={}
        self.recovery_guard=parent.read_guard
        self._recovery_code=self._recovery_descriptor()
        routes=self.assembly.client.native_routes
        if routes.settings.query_saved_approval_on_error and not self.settings.allow_saved_recovery:
            raise TaskConflict('Approval query on error requires explicit saved-result recovery authorization')
        if (not routes.settings.micro_government_approval_scope or routes.settings.native_government_approval_transport
                or ('Government','decide_approval') in routes._proposals
                or any(('Government',decision) in routes._decisions for decision in
                    ('government_design_approval','government_completion_approval'))):
            raise TaskConflict('Micro approval needs exclusive declared original proposal/final ownership')
        args=dict(registry=parent.registry,organizations=parent.organizations,provider=self,
            macro_version='gba-public-2026-08-21',source_mode='formal',policy_version=parent.settings.policy_version,
            model_version=self.assembly.client.versions['model'])
        self.review_assembler=GovernmentReviewActionAssembler(**args)
        self.decision_assembler=GovernmentDecisionActionAssembler(**args)
        self.feedback_assembler=GovernmentFeedbackActionAssembler(**args) if any(p.feedback is not None for p in self.plans) else None
        args=dict(store=self.assembly.client.tasks,snapshots=parent.snapshots,registry=parent.registry,
            client_version=parent.VERSION,model_version=self.assembly.client.versions['model'],
            validate_invocation=self.validate_invocation,validate_wait=self.validate_wait,
            validate_recovery=self.validate_recovery)
        self.review_worker=GovernmentReviewResultWorker(**args);self.decision_worker=GovernmentDecisionResultWorker(**args)
        self.feedback_worker=GovernmentFeedbackResultWorker(**args) if self.feedback_assembler is not None else None
        if install:
            self.assembly.client.bind_proposal_handler(role='Government',operation='decide_approval',handler=self.propose,
                client_version=parent.VERSION+'.approval.v1')

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest()!=self.settings.file_sha256:
            raise TaskConflict('Approval independent input bytes changed')

    @staticmethod
    def _recovery_descriptor():
        return {name:module_factory_descriptor(function,'government-approval-saved-recovery.v1')
            for name,function in [('reconcile',recover_saved_proposal),('validate',validate_saved_stage),
                ('unstarted',execute_original_stage),('outcome_query',query_native_approval_outcome),
                ('outcome_history',prior_approval_decisions),('completion_history',own_completion_outcomes)]}

    def check_components(self):
        self._check_file()
        if (task_digest(self.settings.model_dump(mode='json'))!=self._settings_sha
                or self.recovery_guard is not self.parent.read_guard
                or self._recovery_descriptor()!=self._recovery_code
                or task_digest([p.model_dump(mode='json') for p in self.plans])!=self._plans_sha
                or any(w.store is not self.assembly.client.tasks or w.registry is not self.parent.registry
                    or w.snapshots is not self.parent.snapshots
                    or w.validate_wait!=self.validate_wait
                    or w.validate_recovery!=self.validate_recovery
                    for w in (self.review_worker,self.decision_worker,self.feedback_worker) if w is not None)
                or any(a.organizations is not self.parent.organizations or a.provider is not self
                    for a in (self.review_assembler,self.decision_assembler,self.feedback_assembler) if a is not None)
                or (self.feedback_assembler is None)!=(self.feedback_worker is None)
                or (self.feedback_worker is not None)!=any(p.feedback is not None for p in self.plans)):
            raise TaskConflict('Approval changes its original plans or shared workers')

    def _records(self):return self.parent._records(prefix=self.PREFIX)

    @staticmethod
    def _stage_context(plan,stage):
        return plan.feedback.context if stage=='feedback' else getattr(plan,stage+'_context')

    @staticmethod
    def _stage_input(plan,stage):
        return plan.feedback.action_input if stage=='feedback' else getattr(plan,stage+'_input')

    def _stages(self,plan):
        return ([('feedback',self.feedback_assembler,self.feedback_worker)] if plan.feedback is not None else [])+[
            ('review',self.review_assembler,self.review_worker),('decision',self.decision_assembler,self.decision_worker)]

    def _current(self,request):
        self.parent._check();scope=government_scope(self.assembly,request,purpose='propose')
        if request.operation!='decide_approval':raise TaskConflict('Approval needs its original native approval request')
        plans=[p for p in self.plans if (p.organization_id,p.project_id,p.tick)==
            (request.agent.agent_id,scope['project_id'],scope['tick']) and p.review_phase==
                ('completion' if scope['purpose']=='completion_approval' else 'design')]
        if len(plans)!=1:raise TaskConflict('Approval lacks one exact independent current source plan')
        plan=plans[0];assignment=current_review_assignment(self.parent,plan,scope)
        project=self.assembly.engine.projects[plan.project_id]
        for inputs,objects in [(plan.review_input,plan.review_objects),(plan.decision_input,plan.decision_objects)]:
            case,=[r['value'] for r in objects if r['ref']==inputs['case_ref']]
            submission_ref=inputs.get('submission_ref',inputs.get('current_submission_ref'))
            submission,=[r['value'] for r in objects if r['ref']==submission_ref]
            if (case['organization_id']!=plan.organization_id or case['applicant_id']!=project.owner_id
                    or submission['applicant_id']!=project.owner_id or submission['recipient_organization_id']!=plan.organization_id
                    or case['region_id']!={'state':'known','value':project.region}):
                raise TaskConflict('Approval sources change actual native agency, applicant or project region')
            evidence,=[r['value'] for r in objects if r['ref']==plan.submission_evidence_ref.model_dump(mode='json')]
            if (submission['content_sha256']!=task_digest(plan.submission_content)
                    or evidence['content_hash']!=submission['content_sha256']):
                raise TaskConflict('Approval received submission content differs from its original independent evidence')
        return plan,scope,assignment

    def _sources(self,plan,request,stage,record):
        _,scope,assignment=self._current(request)
        observed={'scope':scope,'native_request_sha256':task_digest(request.model_dump(mode='json')),
            'assignment':assignment,'prior_approval_decisions':prior_approval_decisions(self.assembly,
                organization_id=plan.organization_id,tick=plan.tick,read_guard=self.parent.read_guard,
                organizations=self.parent.organizations)}
        if self.parent.monthly is not None:
            observed['prior_monthly_feedback']=self.parent.monthly.history(organization_id=plan.organization_id,tick=plan.tick)
        if stage=='feedback':return feedback_sources(plan,observed=observed),observed
        if plan.feedback is not None:observed['private_feedback']=feedback_origin(self,plan,record)
        objects=deepcopy(getattr(plan,stage+'_objects'))
        evidence_binding(objects,assignment['intake_evidence']['ref'],assignment['intake_evidence']['observed'])
        if stage=='decision':objects,observed['review_handoff']=decision_sources(self,plan,record,objects)
        evidence_binding(objects,getattr(plan,stage+'_native_evidence_ref').model_dump(mode='json'),observed)
        return objects,observed

    def project(self,*,context,organization_id,grants):
        plan,request,stage,key=self._bound[task_digest(context.model_dump(mode='json'))]
        if organization_id!=plan.organization_id:raise TaskConflict('Approval view changes its original private recipient')
        record,=[r for r in self._records() if r['key']==key]
        objects,_=self._sources(plan,request,stage,record)
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21',
            'state_version':'native-government-approval:'+task_digest(objects),'read_token':context.read_token,
            'business_time':context.business_time.model_dump(mode='json'),'organization_id':organization_id,'objects':objects}

    def validate_invocation(self,row,prepared):
        plan,request,stage,key=self._bound[prepared.context_sha256];self._current(request)
        if (prepared.context!=self._stage_context(plan,stage) or row['identity']['organization_id']!=plan.organization_id
                or prepared.runner.registry is not self.parent.registry):
            raise TaskConflict('Approval worker substitutes its original invocation')
        prepared.reading.recheck();return True

    def validate_wait(self,row,result,conditions):
        identity=TaskIdentity(**row['identity'])
        bound=self._bound.get(identity.context_sha256)
        if bound is None:raise TaskConflict('Regulatory wait lost its original approval binding')
        plan,request,stage,key=bound
        self._current(request)
        record,=[r for r in self._records() if r['key']==key]
        worker=next((worker for name,_,worker in self._stages(plan) if name==stage),None)
        objects,observed=self._sources(plan,request,stage,record)
        if (worker is None or record.get(stage+'_identity')!=identity.as_dict()
                or record['native_request']!=request.model_dump(mode='json')
                or record[stage+'_observed']!=observed):
            raise TaskConflict('Regulatory wait changes its original approval stage or observations')
        return validate_pending_result(parent=self.parent,worker=worker,context=self._stage_context(plan,stage),
            objects=objects,source_sha256=record[stage+'_source_sha256'],row=row,result=result,conditions=conditions)

    @staticmethod
    def _summary(saved):
        result=saved['result'];payload=result.get('payload',{})
        # A formal refusal/conditional permit is not the native request-revision action.
        choice=payload.get('choice')
        if (result.get('kind')!='completed' or choice not in {'approve','defer_by_procedure'}
                or payload['draft']['outcome']!=choice or payload['draft']['conditions']):
            raise TaskConflict('Unresolved, conditional or adverse approval needs its separately verified native mapping')
        return (True,'approve') if choice=='approve' else (False,'request_revision')

    def validate_recovery(self,row,saved,snapshot):
        return validate_saved_stage(self,row,saved,snapshot)

    def recover_saved_proposal(self,request):
        return recover_saved_proposal(self,request)

    def query_native_outcome(self,identity,*,organization_id,tick):
        return query_native_approval_outcome(self,identity,organization_id=organization_id,tick=tick)

    def _proposal_response(self,plan,request,scope,record,saved,prepared):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        accepted,action=self._summary(saved)
        for metric,unit in [(plan.utility,'score'),(plan.probability,'probability')]:
            if metric.unit!=unit or not 0<=Decimal(metric.value)<=1 or not isinstance(prepared.reading.resolve(metric.basis_ref),EvidenceRecord):
                raise TaskConflict('Approval native indicators require original bounded units and evidence')
        prepared.reading.recheck()
        factors={'micro_action_id':'GOV-A07','micro_task_key':TaskIdentity(**record['decision_identity']).key,
            'micro_result_sha256':saved['result_sha256'],'review_micro_task_key':TaskIdentity(**record['review_identity']).key,
            'review_micro_result_sha256':record['review_result_sha256'],'native_government_scope':scope}
        return AgentProposalResponseV1(request_id=request.request_id,action_type=action,accepted=accepted,
            utility=float(plan.utility.value),probability=float(plan.probability.value),reason=saved['result']['payload']['draft']['reason'],
            data={},factors=factors)

    def propose(self,request):
        with self.parent.read_guard():
            plan,scope,_=self._current(request)
            key=self.PREFIX+task_digest([self.assembly.client.simulation_id,plan.organization_id,scope,request.request_id])
            if any(r['key']==key for r in self._records()):raise TaskConflict('Approval already claimed; recover original transport')
            record=self.parent._save(key,{'key':key,'scope':scope,'state':'preparing','native_request':request.model_dump(mode='json')})
            saved_by_stage={}
            for stage,assembler,worker in self._stages(plan):
                context=self._stage_context(plan,stage)
                self._bound[task_digest(context.model_dump(mode='json'))]=(plan,request.model_copy(deep=True),stage,key)
                objects,observed=self._sources(plan,request,stage,record)
                prepared=assembler.build(context,**deepcopy(self._stage_input(plan,stage)))
                identity=worker.register(prepared,request_id=key+':'+context.contract_ref.id)
                record.update({stage+'_identity':identity.as_dict(),stage+'_source_sha256':task_digest(objects),stage+'_observed':observed})
                record=self.parent._save(key,record)
                execute_original_stage(worker=worker,identity=identity,prepared=prepared,
                    enabled=self.settings.continue_unstarted_actions_on_error,record=record,stage=stage,
                    save_record=lambda value:self.parent._save(key,value))
                saved=completed_result_or_wait(parent=self.parent,worker=worker,identity=identity,
                    key=key,record=record,stage=stage)
                record[stage+'_result_sha256']=saved['result_sha256'];record=self.parent._save(key,record)
                saved_by_stage[stage]=saved
            saved=saved_by_stage['decision']
            response=self._proposal_response(plan,request,scope,record,saved,prepared)
            record.update(state='formed',proposal_response_sha256=task_digest(response.model_dump(mode='json')))
            self.parent._save(key,record);return response

    def decide(self,request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1,AgentDecisionResponseV1
        from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
        with self.parent.read_guard():
            self.parent._check();scope=government_scope(self.assembly,request,purpose='decide')
            record,=[r for r in self._records() if r['state']=='formed' and r['scope']==scope
                and r['native_request']['agent']['agent_id']==request.agent.agent_id]
            original=AgentProposalRequestV1.model_validate(record['native_request']);plan,_,_=self._current(original)
            for stage,_,worker in self._stages(plan):
                objects,observed=self._sources(plan,original,stage,record)
                saved=checked_result(worker,TaskIdentity(**record[stage+'_identity']))
                if (task_digest(objects)!=record[stage+'_source_sha256'] or observed!=record[stage+'_observed']
                        or saved['result_sha256']!=record[stage+'_result_sha256']):
                    raise TaskConflict('Approval confirmation changes its original source or micro result')
            accepted,action=self._summary(saved);support=request.decision_support
            proposal,=[t['output'] for t in self.assembly.client.tasks.for_organization(run_id=self.assembly.client.run_id,
                organization_id=plan.organization_id) if t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_approval'
                and t['state']=='output_formed' and t['output'].get('factors',{}).get('native_government_scope')==scope]
            if (task_digest(proposal)!=record['proposal_response_sha256'] or support.get('decision_factors')!=proposal['factors']
                    or support.get('accepted')!=accepted or support.get('action_type')!=action
                    or proposal['accepted']!=accepted or proposal['action_type']!=action or proposal['data']
                    or action not in request.constraints.allowed_actions):
                raise TaskConflict('Approval final transport substitutes its original bounded proposal')
            response=AgentDecisionResponseV1(request_id=request.request_id,agent_id=plan.organization_id,action_type=action,
                decision=accepted,reason=proposal['reason'],data={**proposal['factors'],'proposal_response_sha256':task_digest(proposal)})
            ExternalAgentDecisionProvider._validated_action(request,response);return response

    def evidence(self):
        self.check_components()
        return {'source_file_sha256':self.settings.file_sha256,'requests':self._records(),
            'native_outcome_query':{'entry':'approval.query_native_outcome(original_decision_identity, organization_id=own_id, tick=current_tick)',
                'implementation':'integration.government_native_outcome_query:query_native_approval_outcome',
                'limits':'Read original authenticated native design/completion outcomes, including the current tick. Missing native confirmation remains unknown. Requires current original-source read authority at query time. No execution, reconciliation, engine restart, resubmission or detailed permit receipt.'},
            'unstarted_continuation':{'enabled':self.settings.continue_unstarted_actions_on_error,
                'implementation':'integration.unstarted_action_continuation:execute_original_stage',
                'limits':'One original registered stage whose immutable claim proves preparation has not started, within the still-open native call only. Rechecks current sources, authority and versions. No waiting-input replay, saved-result recovery, engine restart or new business request.'},
            'saved_result_recovery':{'enabled':self.settings.allow_saved_recovery,'code':self._recovery_code,
                'entry':'assembly.client.recover_proposal(original_request)',
                'limits':'Queries durable completed original stages in the same current native scope only; no processor replay, macro delivery, engine restoration or formal resubmission.'},
            'limits':'Actual A04 document review and A07 authorized draft drive native design/completion approval. Optional original A12 private reflection is read by the same request A04/A07. Micro approval and actual native completion remain distinct. No policy application, physical A10 inspection, formal case filing, signed decision ID, delivery or permit ledger is created.'}
