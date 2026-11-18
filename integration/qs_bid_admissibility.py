"""Execute an independently delegated original QS-A06 admissibility decision."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from pydantic import Field, model_validator

from integration.bank_financing_private import checked_result, evidence_binding
from integration.qs_bid_actions import QSBidActionAssembler
from integration.qs_bid_results import QSBidResultWorker
from integration.qs_evaluation_outcome_query import original_authorized_round
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId, ref_type
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.models import Digest
from src.organization.registry import AccessDenied


class QSBidAdmissibilitySettings(StrictRecord):
    version: TextId
    file_path: TextId
    file_sha256: Digest


class QSBidAdmissibilityPlan(StrictRecord):
    organization_id: TextId
    project_id: TextId
    tick: int = Field(ge=1, strict=True)
    contractor_id: TextId
    context: ActionContext
    action_input: dict
    objects: list[dict]
    original_round_evidence_ref: ref_type('Evidence')

    @model_validator(mode='after')
    def original_context(self):
        if (self.context.contract_ref.id!='QS-A06' or self.context.scope.kind!='project'
                or self.context.scope.ref.id!=self.project_id or self.context.business_time.offset!=self.tick
                or self.context.execution_mode=='offline_fixture'):
            raise ValueError('Admissibility requires its original formal project/time/action context')
        return self


class QSBidAdmissibility:
    VERSION = 'gba-v1-qs-bid-admissibility.v2'
    PREFIX = 'qs_bid_admissibility:'

    def __init__(self, *, parent, settings):
        self.parent = parent
        self.settings = QSBidAdmissibilitySettings.model_validate(settings).model_copy(deep=True)
        data = json.loads(Path(self.settings.file_path).read_bytes())
        if (set(data)!={'schema_version','run_id','plans'} or data['schema_version']!='qs-bid-admissibility-input.v1'
                or data['run_id']!=parent.assembly.client.run_id):
            raise TaskConflict('Admissibility changes its declared schema or original run')
        self.plans = [QSBidAdmissibilityPlan.model_validate(p) for p in data['plans']]
        selectors = [(p.organization_id,p.project_id,p.tick,p.contractor_id) for p in self.plans]
        if not selectors or len(set(selectors))!=len(selectors):
            raise TaskConflict('Admissibility needs distinct original per-bid selectors')
        tokens = [p.context.read_token for p in [*self.plans,*parent.plans]]
        if len(tokens)!=len(set(tokens)):
            raise TaskConflict('Admissibility cannot reuse the original comparison read token')
        self._bound = {}
        self.assembler = QSBidActionAssembler(registry=parent.bindings.registry,
            organizations=parent.bindings.organizations,provider=self,macro_version=parent.assembler.macro_version,
            source_mode='formal',methods=parent.bindings.methods,policy_version=parent.assembler.policy_version,
            model_version=parent.assembly.client.versions['model'],model_host=parent.bindings.model_host)
        self.worker = QSBidResultWorker(store=parent.worker.store,snapshots=parent.worker.snapshots,
            registry=parent.bindings.registry,client_version=self.VERSION,
            model_version=parent.assembly.client.versions['model'],
            validate_invocation=self.validate_invocation,validate_wait=self.validate_wait)
        self._components = (parent,self.assembler,self.worker,self.worker.store,parent.bindings.organizations)
        self._fingerprint = self._sources_fingerprint()
        self.check()

    def _sources_fingerprint(self):
        return (task_digest(self.settings.model_dump(mode='json')),
            task_digest([p.model_dump(mode='json') for p in self.plans]),
            hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest(),
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest())

    def check(self):
        p = self.parent
        if (self._sources_fingerprint()!=self._fingerprint or self._fingerprint[2]!=self.settings.file_sha256
                or self._components!=(p,self.assembler,self.worker,p.worker.store,p.bindings.organizations)
                or self.worker.registry is not p.bindings.registry
                or self.assembler.organizations is not p.bindings.organizations):
            raise TaskConflict('Admissibility changes its original sources, worker or authority')

    def plan(self, parent_plan, scope):
        self.check()
        rows = [p for p in self.plans if (p.organization_id,p.project_id,p.tick,p.contractor_id)==
            (parent_plan.organization_id,parent_plan.project_id,parent_plan.tick,scope['contractor_id'])]
        return rows[0] if rows else None

    def _sources(self, plan, request):
        parent = self.parent
        parent_plan,project,scope = parent._current(request)
        if (self.plan(parent_plan,scope)!=plan or request.agent.agent_id!=plan.organization_id
                or plan.context.actor_id!=parent_plan.context.actor_id
                or plan.context.function_ref!=parent_plan.context.function_ref
                or plan.context.authorization_refs!=parent_plan.context.authorization_refs):
            raise TaskConflict('Admissibility changes the original current request or executing authority')
        record = parent._record(parent_plan)
        if record is None:
            raise TaskConflict('Admissibility lacks the original same-round comparison')
        identity = TaskIdentity(**record['identity'])
        _,_,saved = original_authorized_round(parent,identity,organization_id=plan.organization_id,tick=plan.tick)
        binding, = [b for b in parent_plan.bids if b.contractor_id==plan.contractor_id]
        rows = [r for r in saved['result']['payload']['evaluations'] if r['bid_ref']==binding.bid_ref.model_dump(mode='json')]
        if len(rows)!=1 or rows[0]['status']!='exclusion_recommended' or rows[0]['unresolved_questions']:
            raise TaskConflict('Admissibility requires an original known rule failure, not missing or ambiguous evidence')
        source_plan = parent_plan.model_copy(update={'context':plan.context,
            'action_input':deepcopy(plan.action_input),'objects':deepcopy(plan.objects)},deep=True)
        objects,origins = parent._source_objects(source_plan,project)
        # Only separately declared profile/candidate/grant/evidence rows differ.
        original_objects,_ = parent._source_objects(parent_plan,project)
        by_ref = {task_digest(r['ref']):r['value'] for r in objects}
        for row in original_objects:
            if by_ref.get(task_digest(row['ref']))!=row['value']:
                raise TaskConflict('Admissibility substitutes an original comparison source or rule failure')
        origin = {'identity':identity.as_dict(),'result_sha256':saved['result_sha256'],
            'source_reading_sha256':saved['source_reading_sha256'],'source_origins':origins}
        evidence_binding(objects,plan.original_round_evidence_ref.model_dump(mode='json'),origin)
        return objects,origin,binding

    def project(self, *, context, organization_id, grants):
        plan,request = self._bound[task_digest(context.model_dump(mode='json'))]
        if context!=plan.context or organization_id!=plan.organization_id:
            raise TaskConflict('Admissibility projects another original private source')
        objects,origin,_ = self._sources(plan,request)
        return {'run_id':context.run_id,'macro_version':self.assembler.macro_version,
            'state_version':'original-qs-admissibility:'+task_digest(origin),'read_token':context.read_token,
            'business_time':context.business_time.model_dump(mode='json'),'organization_id':organization_id,'objects':objects}

    def validate_invocation(self, row, prepared):
        plan,request = self._bound[prepared.context_sha256]
        self._sources(plan,request)
        if (prepared.context!=plan.context or row['identity']['organization_id']!=plan.organization_id
                or prepared.runner.registry is not self.parent.bindings.registry):
            raise TaskConflict('Admissibility substitutes its original invocation')
        prepared.reading.recheck()
        return True

    def validate_wait(self, *args, **kwargs):
        raise TaskConflict('Admissibility remains pending; no automatic source repair or replay')

    def _key(self, plan):
        return self.PREFIX+task_digest([self.parent.assembly.client.simulation_id,
            plan.organization_id,plan.project_id,plan.tick,plan.contractor_id])

    def _record(self, plan):
        with self.worker.store._lock:
            row = self.worker.store._db.execute('SELECT value FROM metadata WHERE key=?',(self._key(plan),)).fetchone()
        if row is None:return None
        record = json.loads(row[0])
        if record['record_sha256']!=task_digest({k:v for k,v in record.items() if k!='record_sha256'}):
            raise TaskConflict('Admissibility changes its original technical record')
        return record

    def _save(self, plan, record):
        record = deepcopy(record)
        record['record_sha256'] = task_digest({k:v for k,v in record.items() if k!='record_sha256'})
        with self.worker.store._transaction():
            self.worker.store._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',
                (self._key(plan),canonical(record)))
        return record

    def remember_request(self, parent_plan, request, scope):
        plan = self.plan(parent_plan,scope)
        if plan is None:
            raise TaskConflict('Admissibility has no explicitly declared per-bid source plan')
        objects,origin,_ = self._sources(plan,request)
        record = self._record(plan)
        if record is None:
            return self._save(plan,{'state':'not_started','native_request':request.model_dump(mode='json'),
                'origin':origin,'source_sha256':task_digest(objects)})
        if (record['native_request']!=request.model_dump(mode='json') or record['origin']!=origin
                or record['source_sha256']!=task_digest(objects)):
            raise TaskConflict('Admissibility changes its original per-bid request or private sources')
        return record

    def decide(self, request, *, parent_plan, proposal):
        from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1,AgentProposalRequestV1
        scope = proposal['factors']['native_evaluation_scope']
        plan = self.plan(parent_plan,scope)
        if plan is None or 'exclude_bid' not in request.constraints.allowed_actions:
            raise TaskConflict('Admissibility lacks an original delegated plan or native final action')
        record = self._record(plan)
        if record is None or record['native_request']['request_id']!=proposal['request_id']:
            raise TaskConflict('Admissibility requires the exact original per-bid native request')
        native = AgentProposalRequestV1.model_validate(record['native_request'])
        objects,origin,binding = self._sources(plan,native)
        if record['state']=='not_started':
            self._bound[task_digest(plan.context.model_dump(mode='json'))]=(plan,native.model_copy(deep=True))
            record = self._save(plan,{'state':'preparing','native_request':native.model_dump(mode='json'),
                'origin':origin,'source_sha256':task_digest(objects)})
            prepared = self.assembler.build(plan.context,**deepcopy(plan.action_input))
            identity = self.worker.register(prepared,request_id=self._key(plan))
            outcome = self.worker.execute(identity,prepared)
            record.update(state='formed' if outcome['result']['kind']=='completed' else 'unresolved',
                identity=identity.as_dict(),result_sha256=task_digest(outcome['result']))
            record = self._save(plan,record)
        if record['state']!='formed' or record['source_sha256']!=task_digest(objects) or record['origin']!=origin:
            raise TaskConflict('Admissibility has changed sources or an unresolved original invocation')
        identity = TaskIdentity(**record['identity'])
        saved = checked_result(self.worker,identity)
        payload = saved['result']['payload']
        if (saved['result_sha256']!=record['result_sha256'] or payload['choice']!='exclude_authorized'
                or payload['bid_ref']!=binding.bid_ref.model_dump(mode='json')):
            raise TaskConflict('Only the exact original authorized exclusion can veto this bid')
        return AgentDecisionResponseV1(request_id=request.request_id,agent_id=request.agent.agent_id,
            action_type='exclude_bid',decision=False,reason='Original delegated QS exclusion; no award or cash effect.',
            data={'micro_action_id':'QS-A06','micro_task_key':identity.key,'micro_result_sha256':saved['result_sha256'],
                'parent_micro_task_key':TaskIdentity(**origin['identity']).key,
                'parent_micro_result_sha256':origin['result_sha256'],'native_evaluation_scope':scope,
                'evaluation_score':proposal['data']['evaluation_score'],'bid_ref':payload['bid_ref'],
                'rule_ref':payload['rule_ref'],'proposal_response_sha256':task_digest(proposal)})

    def read_original_final_exclusions(self, parent_plan, *, tick):
        """Own finalized originals at current authority, without inferring a native event."""
        p = self.parent
        p._check()
        if type(tick) is not int or tick!=p.assembly.engine.current_tick or parent_plan.tick>tick:
            raise TaskConflict('Exclusion originals change the actual current read time')
        outcomes = []
        for plan in self.plans:
            if (plan.organization_id,plan.project_id,plan.tick)!=(parent_plan.organization_id,parent_plan.project_id,parent_plan.tick):
                continue
            record = self._record(plan)
            if record is None or record['state']!='formed':
                raise TaskConflict('Exclusion history has an unresolved original decision')
            identity = TaskIdentity(**record['identity'])
            snapshot = self.worker.snapshots.get(identity)
            if (identity.organization_id!=plan.organization_id or identity.run_id!=p.assembly.client.run_id
                    or identity.role!='QS' or identity.action_id!='QS-A06' or identity.purpose!='action'
                    or identity.request_id!=self._key(plan) or snapshot['identity']!=identity.as_dict()
                    or snapshot['context']!=plan.context.model_dump(mode='json')
                    or identity.input_sha256!=task_digest(snapshot['action_input'])
                    or identity.context_sha256!=task_digest(snapshot['context'])
                    or any(snapshot['action_input'].get(k)!=v for k,v in plan.action_input.items())):
                raise TaskConflict('Exclusion history changes its original snapshot or invocation')
            current = plan.context.model_copy(update={'business_time':
                plan.context.business_time.model_copy(update={'offset':tick})},deep=True)
            grants = p.bindings.organizations.grants(current,'QS-A06','QS')
            saved = checked_result(self.worker,identity)
            readable = {r.key() for g in grants for r in g.readable_refs} & {r.key() for r in plan.context.visible_refs}
            if (not grants or any(g.organization_id!=plan.organization_id for g in grants)
                    or any(Reference.model_validate(r['ref']).key() not in readable for r in saved['source_reading'])):
                raise AccessDenied('Exclusion history lost current access to original private sources')
            scope = {'project_id':plan.project_id,'tick':plan.tick,'contractor_id':plan.contractor_id}
            tasks = p.assembly.client.tasks.for_organization(run_id=identity.run_id,organization_id=identity.organization_id)
            proposals = [t for t in tasks if t['identity']['purpose']=='propose'
                and t['identity']['action_id']=='evaluate_bid' and t['state']=='output_formed'
                and t['output'].get('factors',{}).get('native_evaluation_scope')==scope]
            finals = [t for t in tasks if t['identity']['purpose']=='decide'
                and t['identity']['action_id']=='qs_bid_evaluation' and t['state']=='output_formed'
                and t['output'].get('data',{}).get('native_evaluation_scope')==scope]
            if len(proposals)!=1 or len(finals)!=1:
                raise TaskConflict('Exclusion history lacks original per-bid transport decisions')
            proposal,final = proposals[0]['output'],finals[0]['output']
            payload = saved['result']['payload']
            parent_record = p._record(parent_plan)
            if (saved['result_sha256']!=record['result_sha256'] or payload['choice']!='exclude_authorized'
                    or proposal['accepted'] is not True or proposal['action_type']!='evaluate_bid'
                    or final['decision'] is not False or final['action_type']!='exclude_bid'
                    or final['data'].get('micro_task_key')!=identity.key
                    or final['data'].get('micro_result_sha256')!=saved['result_sha256']
                    or final['data'].get('proposal_response_sha256')!=task_digest(proposal)
                    or final['data'].get('bid_ref')!=payload['bid_ref']
                    or final['data'].get('rule_ref')!=payload['rule_ref']
                    or parent_record is None or record['origin']['identity']!=parent_record['identity']
                    or final['data'].get('parent_micro_task_key')!=TaskIdentity(**parent_record['identity']).key):
                raise TaskConflict('Exclusion history changes its original decision or actual published result')
            outcomes.append({'contractor_id':plan.contractor_id,'bid_ref':deepcopy(payload['bid_ref']),
                'rule_ref':deepcopy(payload['rule_ref']),'original_identity':identity.as_dict(),
                'result_sha256':saved['result_sha256'],'proposal_identity':proposals[0]['identity'],
                'final_identity':finals[0]['identity'],
                'limits':'Own QS exclusion evidence, not delivery of a private receipt or bidder resource release.'})
        return outcomes

    def read_outcomes(self, parent_plan, event, *, tick):
        """Add only an authenticated actual native result to the original decisions."""
        from integration.qs_evaluation_outcome_query import matching_native_events
        p = self.parent
        p._check()
        if type(tick) is not int or tick!=p.assembly.engine.current_tick or event.tick>tick:
            raise TaskConflict('Exclusion history changes its actual current read time')
        matched = matching_native_events(p,parent_plan)
        if len(matched)!=1 or matched[0]!=event.model_dump(mode='json'):
            raise TaskConflict('Exclusion history lacks matching original native event logs')
        is_deferred = event.event_type=='bid_evaluation_deferred'
        if is_deferred:
            from integration.qs_no_valid_outcome import validate_no_valid_deferral
            validate_no_valid_deferral(p,parent_plan,event)
        elif event.data.get('evaluation_committee',{}).get('qs_id')!=parent_plan.organization_id:
            raise TaskConflict('Exclusion history changes the actual receiving QS committee')
        outcomes = self.read_original_final_exclusions(parent_plan,tick=tick)
        if is_deferred and (len(outcomes)!=len(parent_plan.bids)
                or {r['contractor_id'] for r in outcomes}!={b.contractor_id for b in parent_plan.bids}):
            raise TaskConflict('No-valid-bid deferral needs every original finalized per-bid exclusion')
        for outcome in outcomes:
            if any(b.get('contractor_id')==outcome['contractor_id'] for b in event.data.get('ranked_bids',[])):
                raise TaskConflict('Excluded bid cannot appear in the actual published ranking')
            outcome.update(event_id=event.event_id,event_sha256=task_digest(event.model_dump(mode='json')))
        return outcomes

    def evidence(self):
        self.check()
        return {'version':self.VERSION,'records':[r for p in self.plans if (r:=self._record(p)) is not None],
            'limits':'Technical original micro decisions only; native ranked results and missing recipient receipts retain their own meanings.'}
