"""Received original candidates -> bounded monthly screen -> later original A03."""
from copy import deepcopy
import json

from integration.bank_financing_private import checked_result
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension
from integration.owner_opportunity_native import OwnerOpportunityApplication, OwnerOpportunitySettings
from integration.owner_opportunity_native_feedback import authorize_owner_history
from integration.owner_pipeline_sources import received_candidates, one, valid
from src.actions.contracts.common import StrictRecord
from src.actions.contracts.owner_monthly_pipeline import OwnerPipelinePolicy
from src.actions.roles.owner_monthly_pipeline import decide_pipeline_review
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest

BOUNDARY = ('Actual original generated and received candidates, original A03 private calculations, bounded native monthly '
    'screen_investment_pipeline execution and subsequent original A03 private appetite gate. A positive individual '
    'candidate decision is not project creation: only its exact original native initiation event proves that effect. '
    'The screen is an internal review activity; it does not issue a formal investment authorization or reserve cash. '
    'Current own read authority is checked for the original private candidate sources. Independent forecast, cash, '
    'old debt, capacity and scoped grant assumptions remain explicit scenario inputs. A declared prior-screen limit '
    'pauses new investment for portfolio review; no screen result creates cash, clears debt or proves investment return.')


class OwnerPipelineSettings(StrictRecord):
    opportunity: OwnerOpportunitySettings
    pipeline: OwnerPipelinePolicy


def attach_pipeline_feedback(source, *, policy, history):
    """Extend a freshly assembled projection before its original A03 invocation.

    This follows the existing observation/proposal handoff pattern: check the
    old binding first, then hash the combined observation. No saved source or
    formal business object is edited.
    """
    source=deepcopy(source)
    native=one(source['objects'],lambda r:r['ref']==source['native_evidence_ref'],
        'Original candidate observation evidence missing')['value']
    if native['content_hash']!=task_digest(source['observed']):
        raise TaskConflict('Original opportunity observation changed before pipeline handoff')
    scope=source['observed']['scope'];ids=[h['event_id'] for h in history]
    if (scope['owner_id']!=policy.organization_id or scope['tick'] not in policy.authorized_ticks
            or 'prior_own_pipeline_screens' in source['observed'] or len(ids)!=len(set(ids))
            or any(h['organization_id']!=policy.organization_id or not 0<h['tick']<scope['tick']
                or h['operation']!='screen_investment_pipeline' for h in history)):
        raise TaskConflict('Pipeline handoff changes current own scope or uses foreign, duplicate or future feedback')
    pause=len(history)>=policy.maximum_prior_screens_before_portfolio_review
    source['observed'].update(prior_own_pipeline_screens=deepcopy(history),pipeline_policy_sha256=task_digest(policy.model_dump(mode='json')),
        maximum_prior_screens_before_portfolio_review=policy.maximum_prior_screens_before_portfolio_review,
        pipeline_review_preference_pauses_initiation=pause)
    native['content_hash']=task_digest(source['observed'])
    if pause:
        for row in source['objects']:
            if row['ref']['kind']=='ProjectRegistrationProfile':row['value']['policy']={'state':'known','value':'reject'}
    return source


class OwnerMonthlyPipelineApplication(OwnerOpportunityApplication):
    VERSION = 'owner-monthly-native-pipeline.v1'
    PIPELINE_PREFIX = 'owner_monthly_pipeline_request:'

    def __init__(self, *, assembly, settings):
        settings=OwnerPipelineSettings.model_validate(settings)
        self.pipeline=settings.pipeline.model_copy(deep=True)
        self._pipeline_sha=task_digest(self.pipeline.model_dump(mode='json'))
        super().__init__(assembly=assembly,settings=settings.opportunity)
        if (len(self.policies)!=1 or self.policies[0].organization_id!=self.pipeline.organization_id
                or any([self.policies[0].with_observation,self.policies[0].with_proposal,self.policies[0].study_question_code])):
            raise TaskConflict('Fixed pipeline composition requires one original Owner and investment-only candidate evaluations')

    def _check(self):
        super()._check()
        if task_digest(self.pipeline.model_dump(mode='json'))!=self._pipeline_sha:
            raise TaskConflict('Independent pipeline authority or review limit changed')

    def proposal_bindings(self):
        return {**super().proposal_bindings(),('Owner','decide_monthly_operation'):self.monthly_propose}

    def install(self):
        client=self.assembly.client
        with client._lock:
            if self._implementation is not None or client._calls or client._request_hashes:
                raise TaskConflict('Install pipeline routes once before any original request')
            for (role,operation),handler in self.proposal_bindings().items():
                client.bind_proposal_handler(role=role,operation=operation,handler=handler,
                    client_version=self.VERSION+':'+operation)
            client.decision_handler=self.decide
            self.seal_client_binding()

    def pipeline_records(self):
        with self.assembly.client.tasks._lock:
            rows=[json.loads(v) for v, in self.assembly.client.tasks._db.execute(
                'SELECT value FROM metadata WHERE key LIKE ?',(self.PIPELINE_PREFIX+'%',))]
        for row in rows:valid(row)
        return rows

    def candidates(self, tick):
        client=self.assembly.client;org=self.pipeline.organization_id
        tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=org)
        records=self._records()
        identities=[TaskIdentity(**r['identity']) for r in records if r['scope']['owner_id']==org
            and r['scope']['tick']==tick and r.get('state')=='formed']
        return received_candidates(records=records,tasks=tasks,saved_results=[checked_result(self.worker,i) for i in identities],
            snapshots={i.key:self.snapshots.get(i) for i in identities},events=[e.model_dump(mode='json') for e in self.assembly.engine.events.events],
            organization_id=org,tick=tick,run_id=client.run_id,simulation_id=self.assembly.engine.simulation_id,
            authorize=lambda saved,snapshot,**kw:authorize_owner_history(saved,snapshot,organizations=self.organizations,
                tick=self.assembly.engine.current_tick))

    def pipeline_history(self, organization_id, tick):
        if organization_id!=self.pipeline.organization_id:
            raise TaskConflict('Pipeline feedback is private to its originally authorized Owner')
        history=[];client=self.assembly.client
        tasks=client.tasks.for_organization(run_id=client.run_id,organization_id=organization_id)
        records=sorted(self.pipeline_records(),key=lambda r:r['scope']['tick'])
        if len({task_digest(r['scope']) for r in records})!=len(records):
            raise TaskConflict('Pipeline journal repeats an original monthly scope')
        for record in records:
            if record['scope']['tick']>=tick:continue
            scope=record['scope'];j=record['judgment']
            recomputed=decide_pipeline_review(self.pipeline,organization_id=organization_id,tick=scope['tick'],
                market_demand=record['native_request']['inputs']['macro_environment']['market_demand_index'],
                candidates=record['candidates'],history=history).model_dump(mode='json')
            if (record['state']!='formed' or scope['organization_id']!=organization_id or record['history']!=history
                    or record['policy']!=self.pipeline.model_dump(mode='json') or j!=recomputed
                    or record['judgment_sha256']!=task_digest(j) or record['candidates']!=self.candidates(scope['tick'])):
                raise TaskConflict('Pipeline feedback changes its exact original candidate review')
            proposal=one(tasks,lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
                and (t.get('output') or {}).get('factors',{}).get('pipeline_record_key')==record['key'],'Original pipeline proposal missing')['output']
            final=one(tasks,lambda t:t['identity']['purpose']=='decide' and t['identity']['action_id']=='monthly_enterprise_operation'
                and (t.get('output') or {}).get('data',{}).get('pipeline_record_key')==record['key'],'Original pipeline final missing')['output']
            event=one([e.model_dump(mode='json') for e in self.assembly.engine.events.events],
                lambda e:e['event_type']=='agent_operation' and e['agent_id']==organization_id and e['tick']==scope['tick'],
                'Original actual pipeline activity missing')
            expected='screen_investment_pipeline' if j['participate'] else 'maintain_operations'
            memory=one(self.assembly.engine.agents[organization_id].episodic_memory,
                lambda m:m.get('tick')==scope['tick'] and m.get('operation')==expected,'Original pipeline memory missing')
            if (record['proposal_response_sha256']!=task_digest(proposal) or final['data']['proposal_response_sha256']!=task_digest(proposal)
                    or proposal['accepted'] is not True or final['decision']!=j['participate']
                    or not (proposal['action_type']==final['action_type']=='screen_investment_pipeline')
                    or proposal['factors']['pipeline_judgment_sha256']!=record['judgment_sha256']
                    or proposal['factors']['micro_candidate_task_keys']!=j['candidate_task_keys']
                    or final['data']['pipeline_judgment_sha256']!=record['judgment_sha256']
                    or event['data']['operation']!=expected or event['description']!=proposal['data']['description']
                    or memory['label']!=event['data']['label'] or memory.get('capability_update')!=event['data'].get('capability_update')):
                raise TaskConflict('Pipeline feedback lacks its same actual original execution and memory')
            if not j['participate']:continue
            history.append({'organization_id':organization_id,'tick':scope['tick'],'operation':expected,'event_id':event['event_id'],
                'event_sha256':task_digest(event),'candidate_source_sha256':task_digest(record['candidates']),
                'candidate_task_keys':j['candidate_task_keys'],'judgment_sha256':record['judgment_sha256'],
                'proposal_response_sha256':task_digest(proposal),'final_response_sha256':task_digest(final)})
        return sorted(history,key=lambda h:(h['tick'],h['event_id']))

    def _sources(self,policy,request,scope,*,stage='investment'):
        source=super()._sources(policy,request,scope,stage=stage)
        history=self.pipeline_history(policy.organization_id,scope['tick'])
        return attach_pipeline_feedback(source,policy=self.pipeline,history=history)

    def monthly_scope(self,request,*,purpose):
        self._check();engine=self.assembly.engine
        scope={'organization_id':self.pipeline.organization_id,'role':'Owner','tick':engine.current_tick}
        environment=engine.macro_environment.model_dump(mode='json')
        if request.agent.agent_id!=scope['organization_id'] or request.agent.role!='Owner' or scope['tick'] not in self.pipeline.authorized_ticks:
            raise TaskConflict('Monthly pipeline request leaves current own authorized review scope')
        if purpose=='propose':
            if request.operation!='decide_monthly_operation' or request.inputs!={'macro_environment':environment}:
                raise TaskConflict('Monthly pipeline substitutes current original macro inputs')
        elif (request.decision_type!='monthly_enterprise_operation' or request.tick!=scope['tick'] or request.project_id is not None
                or request.environment!=environment or request.decision_support.get('decision_factors',{}).get('native_owner_pipeline_scope')!=scope):
            raise TaskConflict('Monthly pipeline final changes its original request scope')
        return scope

    def monthly_propose(self,request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        with self.read_guard():
            scope=self.monthly_scope(request,purpose='propose');key=self.PIPELINE_PREFIX+task_digest([self.assembly.client.run_id,scope,request.request_id])
            if any(r['key']==key for r in self.pipeline_records()):raise TaskConflict('Original pipeline review already claimed; never replay it')
            candidates=self.candidates(scope['tick']);history=self.pipeline_history(scope['organization_id'],scope['tick'])
            judgment=decide_pipeline_review(self.pipeline,organization_id=scope['organization_id'],tick=scope['tick'],
                market_demand=request.inputs['macro_environment']['market_demand_index'],candidates=candidates,history=history)
            data=judgment.model_dump(mode='json')
            response=AgentProposalResponseV1(request_id=request.request_id,action_type='screen_investment_pipeline',accepted=True,
                utility=.7 if judgment.participate else 0.,probability=1.,reason=judgment.model_dump_json(),
                data={'label':'Original received candidate pipeline review','description':judgment.model_dump_json()},
                factors={'pipeline_record_key':key,'pipeline_judgment_sha256':task_digest(data),
                    'micro_candidate_task_keys':judgment.candidate_task_keys,'micro_participation':judgment.participate,'native_owner_pipeline_scope':scope})
            self._save(key,{'key':key,'scope':scope,'state':'formed','native_request':request.model_dump(mode='json'),
                'policy':self.pipeline.model_dump(mode='json'),'candidates':candidates,'history':history,'judgment':data,
                'judgment_sha256':task_digest(data),'proposal_response_sha256':task_digest(response.model_dump(mode='json'))})
            return response

    def decide(self,request):
        if (request.agent.role,request.decision_type)!=('Owner','monthly_enterprise_operation'):return super().decide(request)
        from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1
        from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
        with self.read_guard():
            scope=self.monthly_scope(request,purpose='decide');record=one(self.pipeline_records(),lambda r:r['scope']==scope,'Original pipeline review missing')
            current=self.candidates(scope['tick']);history=self.pipeline_history(scope['organization_id'],scope['tick'])
            judgment=decide_pipeline_review(self.pipeline,organization_id=scope['organization_id'],tick=scope['tick'],
                market_demand=request.environment['market_demand_index'],candidates=current,history=history).model_dump(mode='json')
            proposal=one(self.assembly.client.tasks.for_organization(run_id=self.assembly.client.run_id,organization_id=scope['organization_id']),
                lambda t:t['identity']['purpose']=='propose' and t['identity']['action_id']=='decide_monthly_operation'
                    and (t.get('output') or {}).get('factors',{}).get('pipeline_record_key')==record['key'],'Original pipeline proposal missing')['output']
            if (record['candidates']!=current or record['history']!=history or record['judgment']!=judgment
                    or record['proposal_response_sha256']!=task_digest(proposal)
                    or request.decision_support.get('decision_factors')!=proposal['factors']
                    or request.decision_support.get('accepted') is not True
                    or request.decision_support.get('action_type')!=proposal['action_type']):
                raise TaskConflict('Monthly pipeline final changes original received candidates or actual micro judgment')
            response=AgentDecisionResponseV1(request_id=request.request_id,agent_id=scope['organization_id'],action_type='screen_investment_pipeline',
                decision=judgment['participate'],reason=proposal['reason'],data={**proposal['factors'],'proposal_response_sha256':task_digest(proposal)})
            ExternalAgentDecisionProvider._validated_action(request,response);return response

    def evidence(self):
        return {**super().evidence(),'pipeline_requests':self.pipeline_records(),'pipeline_policy':self.pipeline.model_dump(mode='json'),
            'original_global_events':[e.model_dump(mode='json') for e in self.assembly.engine.events.events],'boundary':BOUNDARY}


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Explicit private pipeline development requires offline mode')
    assembly.client.native_routes.attach(assembly)
    app=OwnerMonthlyPipelineApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
