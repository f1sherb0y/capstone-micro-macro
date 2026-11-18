"""Original OWN-A05 consumes disclosed actual bank proposals, without a loan ledger."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from pydantic import Field

from integration.bank_financing_private import checked_result, evidence_binding
from integration.module_host import module_factory_descriptor
from integration.owner_financing_actions import OwnerFinancingActionAssembler
from integration.owner_financing_results import OwnerFinancingResultWorker
from integration.project_financing_native import financing_scope
from src.actions.contracts.common import ActionContext, EvidenceRecord, Measured, StrictRecord, TextId, ref_type
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.registry import AccessDenied
from src.methods.models import Digest


class FinancingQuoteDisclosure(StrictRecord):
    bank_id: TextId
    offer_ref: ref_type('FinanceOffer')
    evidence_ref: ref_type('Evidence')
    priority: int
    readable_refs: list[dict]


class OwnerFinancingPlan(StrictRecord):
    organization_id: TextId
    project_id: TextId
    tick: int = Field(ge=1)
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    project_evidence_ref: ref_type('Evidence')
    disclosures: list[FinancingQuoteDisclosure]
    # An explicitly supplied Owner preference, never a Bank credit/cash fact.
    repeat_lender_priority_penalty: int = Field(default=0, ge=0, strict=True)
    prior_refusal_priority_penalty: int = Field(default=0, ge=0, strict=True)
    utility: Measured
    probability: Measured


class OwnerFinancingSettings(StrictRecord):
    version: TextId
    file_path: TextId
    file_sha256: Digest


class OwnerFinancingApplication:
    PREFIX = 'owner_financing_native_request:'

    def __init__(self, *, bank, settings):
        self.bank = bank
        self.settings = OwnerFinancingSettings.model_validate(settings).model_copy(deep=True)
        self._check_file()
        doc = json.loads(Path(self.settings.file_path).read_bytes())
        if (set(doc) != {'schema_version','run_id','plans'} or doc['schema_version'] != 'owner-financing-input.v1'
                or doc['run_id'] != bank.assembly.client.run_id):
            raise TaskConflict('Owner financing sources change their original schema or run')
        self.plans = [OwnerFinancingPlan.model_validate(p) for p in doc['plans']]
        self._plans_sha256=task_digest([p.model_dump(mode='json') for p in self.plans])
        self._settings_sha256=task_digest(self.settings.model_dump(mode='json'))
        self._source_implementations=self._source_descriptors()
        keys = [(p.organization_id,p.project_id,p.tick) for p in self.plans]
        if not keys or len(set(keys)) != len(keys):
            raise TaskConflict('Owner financing needs unique explicit current request selectors')
        for p in self.plans:
            c = p.context
            if (c.run_id != doc['run_id'] or c.actor_id != bank.organizations.get(p.organization_id).actor_id or c.contract_ref.id != 'OWN-A05'
                    or c.execution_mode == 'offline_fixture' or c.scope.kind != 'project' or c.scope.ref.id != p.project_id
                    or c.business_time.offset != p.tick or len({q.bank_id for q in p.disclosures}) != len(p.disclosures)):
                raise TaskConflict('Owner financing plan changes its original actor, project, time or disclosures')
        self._bound = {}
        self.assembler = OwnerFinancingActionAssembler(registry=bank.registry, organizations=bank.organizations,
            provider=self, macro_version='gba-public-2026-08-21', source_mode='formal',
            policy_version=bank.settings.policy_version, model_version=bank.assembly.client.versions['model'])
        self.worker = OwnerFinancingResultWorker(store=bank.assembly.client.tasks, snapshots=bank.snapshots,
            registry=bank.registry, client_version=bank.VERSION, model_version=bank.assembly.client.versions['model'],
            validate_invocation=self.validate_invocation, validate_wait=bank.validate_wait)

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest() != self.settings.file_sha256:
            raise TaskConflict('Owner financing independent inputs changed their pinned bytes')

    @staticmethod
    def _source_descriptors():
        from integration.project_financing_feedback import own_financing_history
        from integration.owner_financing_quote_views import quote_views
        from integration.project_financing_native import financing_requirement
        return {name:module_factory_descriptor(fn,'owner-financing-sources.v2')
            for name,fn in [('history',own_financing_history),('quotes',quote_views),('amount',financing_requirement)]}

    def check_components(self):
        self._check_file()
        if (task_digest(self.settings.model_dump(mode='json'))!=self._settings_sha256
                or task_digest([p.model_dump(mode='json') for p in self.plans])!=self._plans_sha256
                or self._source_descriptors()!=self._source_implementations):
            raise TaskConflict('Owner financing changes its original pinned plans or settings')
        if (self.worker.store is not self.bank.assembly.client.tasks or self.worker.registry is not self.bank.registry
                or self.assembler.organizations is not self.bank.organizations):
            raise TaskConflict('Owner financing replaced its original shared worker, journal or authority')

    def _current(self, request):
        self.bank._check()
        scope = financing_scope(self.bank.assembly, request, purpose='propose')
        if (request.agent.role, request.operation) != ('Owner','select_financing_offer'):
            raise TaskConflict('Owner financing requires its actual native selection request')
        plan, = [p for p in self.plans if (p.organization_id,p.project_id,p.tick)
                 == (request.agent.agent_id,scope['project_id'],scope['tick'])]
        if self.bank.organizations.grants(plan.context,'OWN-A05','Owner')[0].organization_id != plan.organization_id:
            raise TaskConflict('Owner financing lost its current original decision authority')
        return plan, scope

    def _sources(self, plan, request):
        """Disclose only declared quote dependencies, never the Bank risk review.

        FinanceOffer is a private view of the actual communicated proposal. We
        deliberately create no FinanceOfferReceipt: the existing receipt helper
        requires detailed formal registration, which the native summary is not.
        """
        from integration.owner_financing_quote_views import quote_views
        objects = deepcopy(plan.objects)
        scope = financing_scope(self.bank.assembly,request,purpose='propose')
        from integration.project_financing_native import financing_requirement
        requirement=financing_requirement(self.bank.assembly,scope)
        funding_profile,=[r['value'] for r in objects if r['ref']==plan.action_input['funding_profile_ref']]
        if (funding_profile['funding_lines']!=plan.action_input['funding_lines'] or len(funding_profile['funding_lines'])!=1
                or funding_profile['funding_lines'][0]['planned_use']!={'state':'unknown',
                    'reason_code':'await_current_native_financing_amount','missing_refs':[plan.native_evidence_ref.model_dump(mode='json')]}):
            raise TaskConflict('Owner financing requires its declared unbound native amount and independent timing')
        funding_profile['funding_lines'][0]['planned_use']={'state':'known','value':{
            'value':str(requirement['requested_amount']),'currency':requirement['currency'],
            'basis_ref':plan.native_evidence_ref.model_dump(mode='json')}}
        history = self._history(plan) if (plan.repeat_lender_priority_penalty or plan.prior_refusal_priority_penalty) else []
        prior_refusal_count=sum(h['financing_mode']=='unfinanced' for h in history)
        origins, offers = [], []
        priorities = []
        for profile, decision in request.inputs['offers']:
            if not decision['accepted']:
                continue
            disclosure, = [q for q in plan.disclosures if q.bank_id == profile['agent_id']]
            rows, origin = quote_views(self.bank, plan=plan, request=request, disclosure=disclosure, decision=decision)
            count = sum(h['selected_bank_id'] == disclosure.bank_id for h in history)
            priority = (disclosure.priority + plan.repeat_lender_priority_penalty * count
                + plan.prior_refusal_priority_penalty * prior_refusal_count)
            offer, = [r['value'] for r in rows if r['ref'] == disclosure.offer_ref.model_dump(mode='json')]
            # This field is the Owner's declared comparison preference. Preserve
            # every communicated Bank term and retain the actual quote evidence.
            offer['priority'] = {'state':'known', 'value':priority}
            if plan.repeat_lender_priority_penalty or plan.prior_refusal_priority_penalty:
                offer['evidence_refs'].append(plan.native_evidence_ref.model_dump(mode='json'))
            priorities.append({'bank_id':disclosure.bank_id,'base_priority':disclosure.priority,
                'earlier_selection_count':count,'priority':priority})
            objects.extend(rows)
            origins.append(origin)
            offers.append(disclosure.offer_ref.model_dump(mode='json'))
        # Shared borrower/purpose data are supplied even if no bank offers.
        region = self.bank.plans[0].native_region_ids[self.bank.assembly.engine.projects[plan.project_id].region]
        evidence_binding(objects,plan.project_evidence_ref.model_dump(mode='json'),{'scope':scope,'region_id':region})
        for row in objects:
            if row['ref']['kind'] == 'FundingPurpose' and row['value']['project_region_id'] == {'state':'known','value':None}:
                row['value']['project_region_id']['value'] = region
            if row['ref'] == plan.context.candidate_set_ref.model_dump(mode='json'):
                row['value']['candidates'] = [{'ref':ref,'permitted_choices':['accept_offer']} for ref in offers]
        observed = {'request_sha256':task_digest(request.model_dump(mode='json')),'scope':scope,'bank_origins':origins,
            'funding_requirement':requirement}
        if plan.repeat_lender_priority_penalty or plan.prior_refusal_priority_penalty:
            observed['feedback_preference'] = {'repeat_lender_priority_penalty':plan.repeat_lender_priority_penalty,
                'prior_refusal_priority_penalty':plan.prior_refusal_priority_penalty,
                'prior_refusal_count':prior_refusal_count,'history':history, 'priorities':priorities}
        evidence_binding(objects,plan.native_evidence_ref.model_dump(mode='json'),observed)
        # Same immutable object can be needed by multiple disclosed quotes.
        unique = {}
        for row in objects:
            key = task_digest(row['ref'])
            if key in unique and task_digest(unique[key]) != task_digest(row):
                raise TaskConflict('Owner quotes substitute a shared immutable source version')
            unique[key] = row
        inputs = deepcopy(plan.action_input)
        inputs['funding_lines']=deepcopy(funding_profile['funding_lines'])
        inputs['offers'] = offers
        return list(unique.values()), inputs, observed

    def _history(self, plan, *, include_current=False, decision_task_key=None):
        from integration.project_financing_feedback import own_financing_history
        history = own_financing_history(self.bank.assembly, organization_id=plan.organization_id,
            tick=plan.tick, read_guard=self.bank.read_guard,
            include_current=include_current, decision_task_key=decision_task_key)
        for origin in history:
            if origin['owner_id'] != plan.organization_id:
                raise TaskConflict('Owner preference reads another organization financing history')
            if 'micro_task_key' not in origin:
                continue  # Authenticated original native choices are also facts.
            previous = [r for r in self.bank._records(prefix=self.PREFIX) if r['state']=='formed'
                and r['scope']=={'owner_id':plan.organization_id,'project_id':origin['project_id'],'tick':origin['tick']}]
            if len(previous) != 1:
                raise TaskConflict('Owner feedback lost its original micro financing request')
            saved = previous[0]
            identity = TaskIdentity(**saved['identity'])
            record = checked_result(self.worker,identity)
            prior_plan, = [p for p in self.plans if (p.organization_id,p.project_id,p.tick)
                == (plan.organization_id,origin['project_id'],origin['tick'])]
            snapshot=self.bank.snapshots.get(identity)
            current_context = prior_plan.context.model_copy(update={
                'business_time': prior_plan.context.business_time.model_copy(update={'offset': plan.tick})}, deep=True)
            grants=self.bank.organizations.grants(current_context,'OWN-A05','Owner')
            readable={r.key() for grant in grants for r in grant.readable_refs} & {r.key() for r in prior_plan.context.visible_refs}
            if not grants or any(g.organization_id!=plan.organization_id for g in grants):
                raise AccessDenied('Owner financing history lost its current original decision authority')
            if (snapshot['identity']!=identity.as_dict()
                    or snapshot['context']!=prior_plan.context.model_dump(mode='json')
                    or identity.context_sha256!=task_digest(snapshot['context'])
                    or identity.input_sha256!=task_digest(snapshot['action_input'])
                    or record['result_sha256']!=task_digest(record['result'])
                    or record['source_reading_sha256']!=task_digest(record['source_reading'])):
                raise TaskConflict('Owner financing history changes its original snapshot, result or reading')
            from src.actions.contracts.common import Reference
            if any(Reference.model_validate(row['ref']).key() not in readable for row in record['source_reading']):
                raise AccessDenied('Owner financing history lost its current original source-reading authority')
            payload = record['result']['payload']
            selected = None
            if payload['choice']=='accept_offer':
                selected, = [q.bank_id for q in prior_plan.disclosures
                    if q.offer_ref.model_dump(mode='json')==payload['offer_ref']]
            elif payload['choice'] not in {'own_funds','no_finance'}:
                raise TaskConflict('Owner feedback is not an executed supported micro choice')
            if (identity.key != origin['micro_task_key'] or saved['result_sha256'] != record['result_sha256']
                    or origin['micro_result_sha256'] != record['result_sha256']
                    or origin['proposal_response_sha256'] != saved['proposal_response_sha256']
                    or selected != origin['selected_bank_id']
                    or origin['financing_mode']!={'own_funds':'owner_equity','no_finance':'unfinanced','accept_offer':'bank_finance'}[payload['choice']]):
                raise TaskConflict('Owner feedback substitutes its original completed micro result')
            origin['micro_choice']=payload['choice']
        return history

    def project(self, *, context, organization_id, grants):
        plan, request = self._bound[task_digest(context.model_dump(mode='json'))]
        self._current(request)
        if organization_id != plan.organization_id:
            raise TaskConflict('Owner financing source changes its original receiving organization')
        objects, _, _ = self._sources(plan,request)
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21','state_version':'native-owner-financing:'+task_digest(objects),
            'read_token':context.read_token,'business_time':context.business_time.model_dump(mode='json'),
            'organization_id':organization_id,'objects':objects}

    def validate_invocation(self, row, prepared):
        plan, request = self._bound[prepared.context_sha256]
        self._current(request)
        if (row['identity']['organization_id'] != plan.organization_id or prepared.context != plan.context
                or prepared.runner.registry is not self.bank.registry):
            raise TaskConflict('Owner worker substitutes its original financing invocation')
        prepared.reading.recheck()
        return True

    def _summary(self, record, plan, request):
        choice = record['result']['payload']['choice']
        if choice == 'own_funds':
            return 'self_finance_project', {'financing_mode':'owner_equity','selected_bank_id':None}
        if choice == 'no_finance':
            return 'select_project_finance', {'financing_mode':'unfinanced','selected_bank_id':None}
        if choice != 'accept_offer':
            raise TaskConflict('Owner financing outcome has no verified native selection mapping; no equity fallback')
        selected, = [q.bank_id for q in plan.disclosures if q.offer_ref.model_dump(mode='json') == record['result']['payload']['offer_ref']]
        from gba_construction_sim.backend.agents.base_agent import AgentDecision
        selected_decision, = [d for p,d in request.inputs['offers'] if p['agent_id']==selected and d['accepted']]
        return 'select_project_finance', {'financing_mode':'bank_finance','selected_bank_id':selected,
            'accepted_bank_ids':[p['agent_id'] for p,d in request.inputs['offers'] if d['accepted']],
            'selected_offer':AgentDecision(**deepcopy(selected_decision)).to_event_data()}

    def propose(self, request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        with self.bank.read_guard():
            plan, scope = self._current(request)
            key = self.PREFIX+task_digest([self.bank.assembly.client.simulation_id,scope,request.request_id])
            if any(r['key']==key for r in self.bank._records(prefix=self.PREFIX)):
                raise TaskConflict('Owner request already claimed; reuse its original transport or diagnose unresolved work')
            technical = self.bank._save(key,{'key':key,'state':'preparing','scope':scope,'native_request':request.model_dump(mode='json')})
            self._bound[task_digest(plan.context.model_dump(mode='json'))] = (plan,request.model_copy(deep=True))
            objects, inputs, observed = self._sources(plan,request)
            prepared = self.assembler.build(plan.context,**inputs)
            identity = self.worker.register(prepared,request_id=key+':OWN-A05')
            technical.update(identity=identity.as_dict(),source_sha256=task_digest(objects),observed=observed)
            technical=self.bank._save(key,technical)
            self.worker.execute(identity,prepared)
            record = checked_result(self.worker,identity)
            technical.update(result_sha256=record['result_sha256'])
            technical=self.bank._save(key,technical)
            action,data = self._summary(record,plan,request)
            for metric,unit in [(plan.utility,'score'),(plan.probability,'probability')]:
                if metric.unit != unit or not 0<=float(metric.value)<=1:
                    raise TaskConflict('Owner financing indicators need explicit sourced bounded units')
                if not isinstance(prepared.reading.resolve(metric.basis_ref),EvidenceRecord):
                    raise TaskConflict('Owner native indicators lack their exact authorized evidence')
            accepted=record['result']['payload']['choice']!='no_finance'
            response=AgentProposalResponseV1(request_id=request.request_id,action_type=action,accepted=accepted,
                utility=float(plan.utility.value),probability=float(plan.probability.value),reason=record['result']['payload']['note'],data=data,
                factors={'micro_action_id':'OWN-A05','micro_task_key':identity.key,'micro_result_sha256':record['result_sha256'],
                         'native_financing_scope':scope})
            technical.update(state='formed',identity=identity.as_dict(),result_sha256=record['result_sha256'],
                source_sha256=task_digest(objects),observed=observed,proposal_response_sha256=task_digest(response.model_dump(mode='json')))
            self.bank._save(key,technical)
            return response

    def decide(self, request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1, AgentDecisionResponseV1
        with self.bank.read_guard():
            scope=financing_scope(self.bank.assembly,request,purpose='decide')
            technical,=[r for r in self.bank._records(prefix=self.PREFIX) if r['state']=='formed' and r['scope']==scope]
            original=AgentProposalRequestV1.model_validate(technical['native_request']);plan,_=self._current(original)
            record=checked_result(self.worker,TaskIdentity(**technical['identity']))
            objects,_,observed=self._sources(plan,original);action,data=self._summary(record,plan,original)
            proposal,=[t['output'] for t in self.bank.assembly.client.tasks.for_organization(run_id=plan.context.run_id,organization_id=plan.organization_id)
                if t['state']=='output_formed' and t['identity']['purpose']=='propose' and t['identity']['action_id']=='select_financing_offer'
                and t['output'].get('factors',{}).get('native_financing_scope')==scope]
            support=request.decision_support
            accepted=record['result']['payload']['choice']!='no_finance'
            if (task_digest(proposal)!=technical['proposal_response_sha256'] or technical['source_sha256']!=task_digest(objects)
                    or observed!=technical['observed'] or record['result_sha256']!=technical['result_sha256']
                    or support.get('decision_factors')!=proposal['factors'] or support.get('action_type')!=action
                    or support.get('accepted') is not accepted or any(task_digest(support.get(k))!=task_digest(v) for k,v in data.items())
                    or action not in request.constraints.allowed_actions or request.choice_contract.output_field!='selected_bank_id'
                    or request.choice_contract.multiple or data['selected_bank_id'] is not None
                    and data['selected_bank_id'] not in {o['id'] for o in request.candidate_options}):
                raise TaskConflict('Owner final confirmation changes its exact original micro choice, candidates or disclosed sources')
            return AgentDecisionResponseV1(request_id=request.request_id,agent_id=plan.organization_id,action_type=action,decision=accepted,
                reason=record['result']['payload']['note'],data={**data,**proposal['factors'],
                    'proposal_response_sha256':technical['proposal_response_sha256']})

    def query_native_outcome(self, identity, *, organization_id, tick):
        from integration.financing_native_outcome_query import query_owner_financing_outcome
        return query_owner_financing_outcome(self, identity, organization_id=organization_id, tick=tick)

    def evidence(self):
        self.check_components()
        return {'source_file_sha256':self.settings.file_sha256,'requests':self.bank._records(prefix=self.PREFIX),
            'limits':'Only actual disclosed proposals feed original OWN-A05. Selection is not a signed arrangement, drawdown or cash.'}
