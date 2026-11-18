"""Original OWN-A03 evaluates real native opportunities; the core creates projects."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from integration.bank_financing_private import checked_result
from integration.contractor_tender_authority_runtime import TenderAuthorityRuntimeSettings,build_authority_runtime
from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension,module_client_implementation,module_factory_descriptor
from integration.owner_investment_actions import OwnerInvestmentActionAssembler
from integration.owner_investment_results import OwnerInvestmentResultWorker
from integration.owner_opportunity_native_sources import prepare_opportunity_sources
from integration.owner_opportunity_native_feedback import prior_owner_initiations, authorize_owner_history
from integration.owner_opportunity_decline_feedback import prior_owner_declines
from integration.owner_opportunity_observation import prepare_observation_sources,attach_observation,observation_origin
from integration.owner_observation_actions import OwnerObservationActionAssembler
from integration.owner_observation_results import OwnerObservationResultWorker
from integration.owner_proposal_actions import OwnerProposalActionAssembler
from integration.owner_proposal_results import OwnerProposalResultWorker
from integration.owner_opportunity_proposal import prepare_proposal_sources, proposal_origin, attach_proposal
from integration.owner_study_actions import OwnerStudyActionAssembler
from integration.owner_study_results import OwnerStudyResultWorker
from integration.owner_opportunity_study import declare_study_followup, declared_study_scope, prepare_study_sources, study_origin
from integration.owner_study_service_offer import OwnerStudyServiceOfferPolicy, prepare_study_service_offer, validate_service_offer_policy
from integration.owner_study_professional_intake import (OwnerStudyProfessionalIntakePolicy,
    OwnerStudyProfessionalIntakeStep, prepare_intake_sources, validate_study_intake_policy)
from integration.owner_opportunity_preparation import preparation_origin
from integration.owner_opportunity_native_recovery import recover_saved_opportunity_proposal, validate_saved_opportunity_stage
from integration.owner_opportunity_scope import owner_opportunity_scope,original_candidate_snapshot
from src.actions.contracts.common import StrictRecord,TextId,DecimalString
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict,TaskIdentity,canonical,task_digest
from src.methods.models import Digest


class OwnerOpportunityPolicy(StrictRecord):
    organization_id: TextId
    cost_organization_id: TextId
    schedule_organization_id: TextId
    allow_scoped_template_authorizations: bool=False
    allowed_regions: list[TextId]=Field(min_length=1)
    initiation_region_ids: list[TextId] | None=Field(default=None,min_length=1)
    project_use_codes: dict[str,TextId]
    money_scale: DecimalString
    max_prior_initiations: int | None=Field(default=None,ge=0)
    max_prior_payment_requests: int | None=Field(default=None,ge=1)
    max_prior_final_accounts: int | None=Field(default=None,ge=1,strict=True)
    max_prior_declines: int | None=Field(default=None,ge=1)
    initial_investment_policy: Literal['evaluate','prepare_only','reject'] | None=None
    native_budget_currency: TextId
    utility: DecimalString
    probability: DecimalString
    with_observation: bool=False
    with_proposal: bool=False
    proposal_review_cost: DecimalString='1000000'
    proposal_review_effort: DecimalString='0.5'
    observation_minimum_demand: DecimalString='0'
    observation_management_requirement: DecimalString='1'
    study_question_code: TextId | None=None
    study_target_interventions: list[Literal['new_build','alter','extend','non_build']]=Field(default_factory=list,max_length=4)
    study_budget: DecimalString='1000000'
    study_estimated_cost: DecimalString='500000'
    study_resource_requirement: DecimalString='0.5'
    study_duration: int=Field(default=1,ge=1)
    study_qualified: bool=True
    study_service_offer: OwnerStudyServiceOfferPolicy | None=None
    study_professional_intake: OwnerStudyProfessionalIntakePolicy | None=None

    @model_validator(mode='after')
    def bounded_study_targets(self):
        if self.study_target_interventions and self.study_question_code is None:
            raise ValueError('Targeted study requires an explicit unresolved question code')
        if len(set(self.study_target_interventions))!=len(self.study_target_interventions):
            raise ValueError('Targeted study interventions cannot repeat')
        validate_service_offer_policy(self)
        validate_study_intake_policy(self)
        return self


class OwnerOpportunitySettings(StrictRecord):
    version: TextId
    policy_version: TextId
    authority: TenderAuthorityRuntimeSettings
    file_path: TextId
    file_sha256: Digest
    allow_saved_recovery: bool=False


class OwnerOpportunityApplication:
    VERSION='gba-v1-owner-opportunity.v15'
    PREFIX='owner_opportunity_native_request:'

    def __init__(self,*,assembly,settings,authority=None,install=True):
        self.assembly=assembly;self.settings=OwnerOpportunitySettings.model_validate(settings).model_copy(deep=True)
        self._check_file();self.document=json.loads(Path(self.settings.file_path).read_bytes())
        doc=self.document
        if (set(doc)!={'schema_version','run_id','template','policies'} or doc['schema_version']!='owner-opportunity-input.v1'
                or doc['run_id']!=assembly.client.run_id or doc['template'].get('origin')!='synthetic'):
            raise TaskConflict('Owner opportunity requires its explicit original independent synthetic source composition')
        self.policies=[OwnerOpportunityPolicy.model_validate(p) for p in doc['policies']]
        if not self.policies or len({p.organization_id for p in self.policies})!=len(self.policies):
            raise TaskConflict('Owner opportunity policies must name unique original Owners')
        self._document_sha=task_digest(self.document);self._settings_sha=task_digest(self.settings.model_dump(mode='json'))
        self._policies_sha=task_digest([p.model_dump(mode='json') for p in self.policies])
        self._source_pins=self._source_descriptors()
        self._owns_authority=authority is None
        self.authority=authority or build_authority_runtime(assembly=assembly,settings=self.settings.authority)
        if self.authority.assembly is not assembly or self.authority.settings!=self.settings.authority:
            raise TaskConflict('Owner opportunity shared authority must match its exact declared assembly and snapshot')
        self.registry,self.organizations=self.authority.registry,self.authority.organizations
        self.read_guard=self.authority.read_guard;self.snapshots=InvocationSnapshotStore(assembly.client.tasks)
        self._bound={};self._implementation=None
        client=assembly.client;routes=client.native_routes;self._other_decision=client.decision_handler
        self._native_settings=task_digest(routes.settings.model_dump(mode='json'))
        try:
            if routes.settings.query_saved_opportunity_on_error and not self.settings.allow_saved_recovery:
                raise TaskConflict('Owner saved query on error requires explicit saved recovery authorization')
            if (not routes.settings.micro_owner_opportunity_scope
                    or ('Owner','evaluate_project_opportunity') in routes._proposals
                    or ('Owner','owner_project_opportunity') in routes._decisions):
                raise TaskConflict('Owner opportunity needs exclusive declared micro proposal/final ownership')
            for p in self.policies:
                for org,role in [(p.organization_id,'Owner'),(p.cost_organization_id,'QS'),(p.schedule_organization_id,'Architect')]:
                    if (client.organization_roles.get(org)!=role or self.organizations.get(org).assignments[0].role!=role):
                        raise TaskConflict('Owner opportunity sources change original Owner or professional organizations')
                if (not p.allow_scoped_template_authorizations or Decimal(p.money_scale)<=0
                        or not 0<=Decimal(p.utility)<=1 or not 0<=Decimal(p.probability)<=1
                        or p.native_budget_currency!='HKD' or not p.project_use_codes):
                    raise TaskConflict('Owner opportunity needs explicit assessment mandate, units and bounded indicators')
                if (not Decimal(p.observation_minimum_demand).is_finite() or Decimal(p.observation_minimum_demand)<0
                        or not Decimal(p.observation_management_requirement).is_finite()
                        or Decimal(p.observation_management_requirement)<=0):
                    raise TaskConflict('Owner observation requires explicit finite threshold and positive private management effort')
                if p.initiation_region_ids is not None and (
                        len(set(p.initiation_region_ids))!=len(p.initiation_region_ids)
                        or not set(p.initiation_region_ids)<=set(p.allowed_regions)):
                    raise TaskConflict('Owner initiation preference must name distinct supported source regions')
                if (p.with_proposal and not p.with_observation
                        or not Decimal(p.proposal_review_cost).is_finite() or Decimal(p.proposal_review_cost)<0
                        or not Decimal(p.proposal_review_effort).is_finite() or Decimal(p.proposal_review_effort)<=0):
                    raise TaskConflict('Private proposal requires original observation and explicit finite review costs/effort')
                if (any(not Decimal(v).is_finite() or Decimal(v)<0 for v in (p.study_budget,p.study_estimated_cost))
                        or not Decimal(p.study_resource_requirement).is_finite() or Decimal(p.study_resource_requirement)<=0):
                    raise TaskConflict('Study requires explicit finite nonnegative budget/cost and positive staff requirement')
            self.assembler=OwnerInvestmentActionAssembler(registry=self.registry,organizations=self.organizations,
                provider=self,macro_version='gba-public-2026-08-21',source_mode='formal',
                policy_version=self.settings.policy_version,model_version=client.versions['model'])
            self.worker=OwnerInvestmentResultWorker(store=client.tasks,snapshots=self.snapshots,registry=self.registry,
                client_version=self.VERSION,model_version=client.versions['model'],validate_invocation=self.validate_invocation,
                validate_wait=self.validate_wait,validate_recovery=self.validate_recovery)
            self.observation_assembler=OwnerObservationActionAssembler(registry=self.registry,organizations=self.organizations,
                provider=self,macro_version='gba-public-2026-08-21',source_mode='formal',
                policy_version=self.settings.policy_version,model_version=client.versions['model'])
            self.observation_worker=OwnerObservationResultWorker(store=client.tasks,snapshots=self.snapshots,registry=self.registry,
                client_version=self.VERSION,model_version=client.versions['model'],validate_invocation=self.validate_invocation,
                validate_wait=self.validate_wait,validate_recovery=self.validate_recovery)
            self.proposal_assembler=OwnerProposalActionAssembler(registry=self.registry,organizations=self.organizations,
                provider=self,macro_version='gba-public-2026-08-21',source_mode='formal',
                policy_version=self.settings.policy_version,model_version=client.versions['model'])
            self.proposal_worker=OwnerProposalResultWorker(store=client.tasks,snapshots=self.snapshots,registry=self.registry,
                client_version=self.VERSION,model_version=client.versions['model'],validate_invocation=self.validate_invocation,
                validate_wait=self.validate_wait,validate_recovery=self.validate_recovery)
            self.study_assembler=OwnerStudyActionAssembler(registry=self.registry,organizations=self.organizations,
                provider=self,macro_version='gba-public-2026-08-21',source_mode='formal',
                policy_version=self.settings.policy_version,model_version=client.versions['model'])
            self.study_worker=OwnerStudyResultWorker(store=client.tasks,snapshots=self.snapshots,registry=self.registry,
                client_version=self.VERSION,model_version=client.versions['model'],validate_invocation=self.validate_invocation,
                validate_wait=self.validate_wait,validate_recovery=self.validate_recovery)
            self.study_intake=OwnerStudyProfessionalIntakeStep(self) if any(p.study_professional_intake is not None for p in self.policies) else None
            if install:self.install()
        except Exception:
            if self._owns_authority:self.authority.close()
            raise

    def proposal_bindings(self):
        return {('Owner','evaluate_project_opportunity'):self.propose}

    def seal_client_binding(self):
        client=self.assembly.client
        with client._lock:
            if (self._implementation is not None or client._calls or client._request_hashes
                    or client.binding_installation_blocked()
                    or any(client.proposal_handlers.get(key)!=handler for key,handler in self.proposal_bindings().items())):
                raise TaskConflict('Owner opportunity binding must be sealed once before requests, with its original handler')
            self._implementation=module_client_implementation(client)

    def install(self):
        client=self.assembly.client
        with client._lock:
            if self._implementation is not None or client._calls or client._request_hashes:
                raise TaskConflict('Owner opportunity must be installed before any original native request')
            for (role,operation),handler in self.proposal_bindings().items():
                client.bind_proposal_handler(role=role,operation=operation,handler=handler,client_version=self.VERSION)
            client.decision_handler=self.decide
            self.seal_client_binding()

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest()!=self.settings.file_sha256:
            raise TaskConflict('Owner opportunity independent source bytes changed')

    @staticmethod
    def _source_descriptors():
        from integration.bindings.gba_v1_progress_payments import read_own_progress_payments
        from integration.bindings.gba_v1_final_accounts import read_own_final_accounts
        return {name:module_factory_descriptor(function,'owner-opportunity-sources.v11') for name,function in
            [('prepare',prepare_opportunity_sources),('creation_history',prior_owner_initiations),('decline_history',prior_owner_declines),
             ('history_authority',authorize_owner_history),
             ('progress_payment_history',read_own_progress_payments),('observation_sources',prepare_observation_sources),
             ('final_account_history',read_own_final_accounts),
             ('observation_relation',attach_observation),('observation_origin',observation_origin),
             ('proposal_sources',prepare_proposal_sources),('proposal_origin',proposal_origin),('proposal_relation',attach_proposal),
             ('study_question',declare_study_followup),('study_target_scope',declared_study_scope),
             ('study_sources',prepare_study_sources),('study_origin',study_origin),
             ('study_service_offer',prepare_study_service_offer),
             ('study_professional_intake',prepare_intake_sources),
             ('preparation_origin',preparation_origin),
             ('saved_recovery',recover_saved_opportunity_proposal),('validate_saved_recovery',validate_saved_opportunity_stage)]}

    def _check(self):
        self.assembly._validate_components();self._check_file()
        if (task_digest(self.document)!=self._document_sha
                or task_digest(self.settings.model_dump(mode='json'))!=self._settings_sha
                or task_digest([p.model_dump(mode='json') for p in self.policies])!=self._policies_sha
                or task_digest(self.assembly.client.native_routes.settings.model_dump(mode='json'))!=self._native_settings
                or self._implementation is None or module_client_implementation(self.assembly.client)!=self._implementation
                or self._source_descriptors()!=self._source_pins
                or self.worker.store is not self.assembly.client.tasks or self.worker.registry is not self.registry
                or self.assembler.organizations is not self.organizations
                or self.observation_worker.store is not self.assembly.client.tasks
                or self.observation_worker.registry is not self.registry
                or self.observation_assembler.organizations is not self.organizations
                or self.proposal_worker.store is not self.assembly.client.tasks or self.proposal_worker.registry is not self.registry
                or self.proposal_assembler.organizations is not self.organizations
                or self.study_worker.store is not self.assembly.client.tasks or self.study_worker.registry is not self.registry
                or self.study_assembler.organizations is not self.organizations
                or self.authority.assembly is not self.assembly or self.authority.settings!=self.settings.authority
                or self.registry is not self.authority.registry or self.organizations is not self.authority.organizations
                or self.read_guard!=self.authority.read_guard):
            raise TaskConflict('Owner opportunity changes its original source plans, shared runtime or handlers')

    def _current(self,request):
        self._check();scope=owner_opportunity_scope(self.assembly,request,purpose='propose')
        policies=[p for p in self.policies if p.organization_id==scope['owner_id']]
        if len(policies)!=1:raise TaskConflict('Original Owner has no exact independently supplied opportunity policy')
        policy=policies[0];op=request.inputs['opportunity']
        if op['region'] not in policy.allowed_regions or op['project_type'] not in policy.project_use_codes:
            raise TaskConflict('Native opportunity leaves the independently declared region/use source support')
        return policy,scope

    def _sources(self,policy,request,scope,*,stage='investment'):
        history=prior_owner_initiations(self.assembly,organization_id=policy.organization_id,
            tick=scope['tick'],read_guard=self.read_guard,organizations=self.organizations)
        declines=prior_owner_declines(self.assembly,organization_id=policy.organization_id,tick=scope['tick'],
            read_guard=self.read_guard,workers={'OWN-A01':self.observation_worker,'OWN-A03':self.worker,
                'OWN-A16':self.proposal_worker,'OWN-A02':self.study_worker,
                **(self.study_intake.workers if self.study_intake is not None else {})},organizations=self.organizations)
        progress_payments=None
        if policy.max_prior_payment_requests is not None:
            progress_payments=self.assembly.read_own_progress_payments(organization_id=policy.organization_id,
                tick=scope['tick'],read_guard=self.read_guard)
        final_accounts=None
        if policy.max_prior_final_accounts is not None:
            final_accounts=self.assembly.read_own_final_accounts(organization_id=policy.organization_id,
                tick=scope['tick'],read_guard=self.read_guard)
        source=prepare_opportunity_sources(self,policy,request,scope,history,progress_payments=progress_payments,
            prior_declines=declines,final_accounts=final_accounts)
        if stage=='observation':return prepare_observation_sources(source,policy,request)
        if stage not in {'investment','proposal','study','study-intake'}:raise TaskConflict('Owner opportunity changes its original stage')
        if policy.with_observation:
            records=[r for r in self._records() if r['scope']==scope and r['native_request']==request.model_dump(mode='json')]
            if len(records)!=1 or 'observation' not in records[0] or 'result_sha256' not in records[0]['observation']:
                raise TaskConflict('Owner investment awaits its original current completed observation')
            technical=records[0]['observation'];identity=TaskIdentity(**technical['identity'])
            saved=checked_result(self.observation_worker,identity)
            original=prepare_observation_sources(source,policy,request)
            if (saved['result_sha256']!=technical['result_sha256'] or task_digest(original['objects'])!=technical['source_sha256']
                    or original['observed']!=technical['observed']):
                raise TaskConflict('Owner investment observation changed its original current sources')
            source=attach_observation(source,original=original,saved=saved,snapshot=self.snapshots.get(identity),
                organizations=self.organizations)
        if stage=='proposal':return prepare_proposal_sources(source,policy,request)
        if policy.with_proposal:
            original=prepare_proposal_sources(source,policy,request)
            records=[r for r in self._records() if r['scope']==scope and r['native_request']==request.model_dump(mode='json')]
            if len(records)!=1 or 'proposal' not in records[0] or 'result_sha256' not in records[0]['proposal']:
                raise TaskConflict('Owner investment awaits its exact current saved private proposal')
            technical=records[0]['proposal'];identity=TaskIdentity(**technical['identity'])
            saved=checked_result(self.proposal_worker,identity)
            if (identity.request_id!=records[0]['key']+':OWN-A16'
                    or saved['result_sha256']!=technical['result_sha256'] or task_digest(original['objects'])!=technical['source_sha256']
                    or original['observed']!=technical['observed']):
                raise TaskConflict('Owner investment private proposal changed its original current sources')
            source=attach_proposal(source,original,saved,self.snapshots.get(identity),self.organizations)
        if stage in {'study','study-intake'}:
            records=[r for r in self._records() if r['scope']==scope and r['native_request']==request.model_dump(mode='json')]
            if len(records)!=1 or 'investment' not in records[0] or 'result_sha256' not in records[0]['investment']:
                raise TaskConflict('Study awaits its exact saved original investment followup')
            technical=records[0]['investment'];identity=TaskIdentity(**technical['identity'])
            saved=checked_result(self.worker,identity)
            if (identity.request_id!=records[0]['key']+':OWN-A03' or saved['result_sha256']!=technical['result_sha256']
                    or technical['source_sha256']!=task_digest(source['objects']) or technical['observed']!=source['observed']):
                raise TaskConflict('Study changes its original investment request, result or source')
            study=prepare_study_sources(source,policy,request,saved,self.snapshots.get(identity),self.organizations)
            if policy.study_professional_intake is not None:
                return (prepare_intake_sources(self,study,policy,request,scope) if stage=='study-intake'
                    else self.study_intake.attach(study,policy,request,scope))
            if stage=='study-intake':raise TaskConflict('Professional study intake was not initially declared')
            return study
        return source

    def _study_authorization(self,policy,request,scope):
        record,=[r for r in self._records() if r['scope']==scope and r['native_request']==request.model_dump(mode='json')]
        technical=record.get('study')
        if not technical or 'result_sha256' not in technical:
            raise TaskConflict('Investment research followup awaits its actual bounded study authorization')
        source=self._sources(policy,request,scope,stage='study');identity=TaskIdentity(**technical['identity'])
        saved=checked_result(self.study_worker,identity)
        if (identity.request_id!=record['key']+':OWN-A02' or saved['result_sha256']!=technical['result_sha256']
                or task_digest(source['objects'])!=technical['source_sha256'] or source['observed']!=technical['observed']):
            raise TaskConflict('Study authorization changed its original same-request result or sources')
        return study_origin(source,saved,self.snapshots.get(identity),self.organizations)

    def project(self,*,context,organization_id,grants):
        policy,request,stage=self._bound[task_digest(context.model_dump(mode='json'))]
        _,scope=self._current(request);source=self._sources(policy,request,scope,stage=stage)
        if context!=source['context'] or organization_id!=policy.organization_id:
            raise TaskConflict('Owner opportunity reading substitutes its original private context')
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21',
            'state_version':'native-owner-opportunity:'+task_digest(source['objects']),'read_token':context.read_token,
            'business_time':context.business_time.model_dump(mode='json'),'organization_id':organization_id,'objects':source['objects']}

    def validate_invocation(self,row,prepared):
        policy,request,stage=self._bound[prepared.context_sha256];_,scope=self._current(request)
        source=self._sources(policy,request,scope,stage=stage)
        if (prepared.context!=source['context'] or row['identity']['organization_id']!=policy.organization_id
                or prepared.runner.registry is not self.registry):
            raise TaskConflict('Owner investment worker substitutes the original opportunity invocation')
        prepared.reading.recheck();return True

    def validate_wait(self,*args,**kwargs):
        raise TaskConflict('Unresolved investment needs source diagnosis and explicit continuation')

    def recovery_guard(self):
        return self.read_guard()

    def validate_recovery(self,row,saved,snapshot):
        return validate_saved_opportunity_stage(self,row,saved,snapshot)

    def recover_saved_proposal(self,request):
        return recover_saved_opportunity_proposal(self,request)

    def _records(self):
        with self.assembly.client.tasks._lock:
            rows=[json.loads(v) for v, in self.assembly.client.tasks._db.execute(
                'SELECT value FROM metadata WHERE key LIKE ?',(self.PREFIX+'%',))]
        if any(r['record_sha256']!=task_digest({k:v for k,v in r.items() if k!='record_sha256'}) for r in rows):
            raise TaskConflict('Owner opportunity technical request evidence changed')
        return rows

    def _save(self,key,record):
        record=deepcopy(record);record['record_sha256']=task_digest({k:v for k,v in record.items() if k!='record_sha256'})
        with self.assembly.client.tasks._transaction():
            self.assembly.client.tasks._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',(key,canonical(record)))
        return record

    def _summary(self,saved,source,request,*,stage='investment'):
        if stage=='proposal':
            choice,_=proposal_origin(source,saved,self.snapshots.get(TaskIdentity(**saved['identity'])),self.organizations)
            if choice!='no_proposal':raise TaskConflict('Only an original no-proposal result can end before investment')
            return False,'defer_project'
        if stage=='observation':
            choice,_=observation_origin(original=source,saved=saved,snapshot=self.snapshots.get(TaskIdentity(**saved['identity'])),
                organizations=self.organizations)
            if choice!='ignore':raise TaskConflict('Only an exact original ignore can end before investment')
            return False,'defer_project'
        if stage!='investment':raise TaskConflict('Unknown original opportunity result stage')
        payload=saved['result']['payload'];choice=payload['choice']
        if choice=='study_more':
            configured=[p for p in self.policies if p.organization_id==saved['identity']['organization_id']]
            if len(configured)!=1 or configured[0].study_question_code is None:
                raise TaskConflict('Unresolved investment branches cannot become native initiation or commercial rejection')
            policy,scope=self._current(request)
            self._study_authorization(policy,request,scope)
            return False,'defer_project'
        if choice=='authorize_preparation':
            preparation_origin(saved,self.snapshots.get(TaskIdentity(**saved['identity'])),organizations=self.organizations,worker=self.worker)
            return False,'defer_project'
        if choice=='reject':return False,'defer_project'
        if choice!='invest':raise TaskConflict('Unresolved investment branches cannot become native initiation or commercial rejection')
        selected,=[r['value'] for r in source['objects'] if r['ref']==payload['option_ref']]
        plan,=[r['value'] for r in source['objects'] if r['ref']==selected['investment_plan_ref']]
        budget=Decimal(str(request.inputs['opportunity']['budget']))
        money=[plan['incurred_cost']['value'],plan['expenditure_cap']['value'],
            *[r['amount']['value'] for r in plan['cash_uses']]]
        forecast=Decimal(money[0]['value'])+sum((Decimal(r['amount']['value']['value']) for r in plan['cash_uses']),Decimal(0))
        if (selected['intervention']!='new_build' or plan['scope']!=payload['scope']
                or any(m['currency']!='HKD' for m in money) or not budget.is_finite()
                or not forecast<=budget<=Decimal(plan['expenditure_cap']['value']['value'])):
            raise TaskConflict('Native initiation leaves the exact selected new-build investment scope or declared budget')
        return True,'initiate_project'

    def propose(self,request):
        with self.read_guard():
            policy,scope=self._current(request)
            key=self.PREFIX+task_digest([self.assembly.client.simulation_id,scope,request.request_id])
            if any(r['key']==key for r in self._records()):raise TaskConflict('Opportunity already claimed; recover original transport')
            record=self._save(key,{'key':key,'scope':scope,'state':'preparing','native_request':request.model_dump(mode='json')})
            if policy.with_observation:
                original=self._sources(policy,request,scope,stage='observation')
                for grant in original['grants']:self.organizations.authorize(grant)
                self._bound[task_digest(original['context'].model_dump(mode='json'))]=(policy,request.model_copy(deep=True),'observation')
                prepared=self.observation_assembler.build(original['context'],**deepcopy(original['action_input']))
                identity=self.observation_worker.register(prepared,request_id=key+':OWN-A01')
                record['observation']={'identity':identity.as_dict(),'source_sha256':task_digest(original['objects']),
                    'observed':original['observed']};record=self._save(key,record)
                self.observation_worker.execute(identity,prepared);saved=checked_result(self.observation_worker,identity)
                record['observation']['result_sha256']=saved['result_sha256'];record=self._save(key,record)
                if saved['result']['payload']['choice']=='ignore':
                    return self._form(key,record,original,saved,request,stage='observation')
            if policy.with_proposal:
                original=self._sources(policy,request,scope,stage='proposal')
                for grant in original['grants']:self.organizations.authorize(grant)
                self._bound[task_digest(original['context'].model_dump(mode='json'))]=(policy,request.model_copy(deep=True),'proposal')
                prepared=self.proposal_assembler.build(original['context'],**deepcopy(original['action_input']))
                identity=self.proposal_worker.register(prepared,request_id=key+':OWN-A16')
                record['proposal']={'identity':identity.as_dict(),'source_sha256':task_digest(original['objects']),
                    'observed':original['observed']};record=self._save(key,record)
                self.proposal_worker.execute(identity,prepared);saved=checked_result(self.proposal_worker,identity)
                record['proposal']['result_sha256']=saved['result_sha256'];record=self._save(key,record)
                if saved['result']['payload']['choice']=='no_proposal':
                    return self._form(key,record,original,saved,request,stage='proposal')
            source=self._sources(policy,request,scope)
            record.update(source_sha256=task_digest(source['objects']),context=source['context'].model_dump(mode='json'),
                action_input=source['action_input'],observed=source['observed'],source_grants=[g.model_dump(mode='json') for g in source['grants']])
            record=self._save(key,record)
            for grant in source['grants']:self.organizations.authorize(grant)
            context=source['context'];self._bound[task_digest(context.model_dump(mode='json'))]=(policy,request.model_copy(deep=True),'investment')
            prepared=self.assembler.build(context,**deepcopy(source['action_input']))
            identity=self.worker.register(prepared,request_id=key+':OWN-A03')
            record.update(identity=identity.as_dict(),investment={'identity':identity.as_dict(),
                'source_sha256':task_digest(source['objects']),'observed':source['observed']});record=self._save(key,record)
            self.worker.execute(identity,prepared);saved=checked_result(self.worker,identity)
            record['investment']['result_sha256']=saved['result_sha256'];record=self._save(key,record)
            if policy.study_question_code is not None and saved['result']['payload']['choice']=='study_more':
                if policy.study_professional_intake is not None:
                    record=self.study_intake.execute(policy,request,scope,key,record)
                original=self._sources(policy,request,scope,stage='study')
                for grant in original['grants']:self.organizations.authorize(grant)
                self._bound[task_digest(original['context'].model_dump(mode='json'))]=(policy,request.model_copy(deep=True),'study')
                prepared=self.study_assembler.build(original['context'],**deepcopy(original['action_input']))
                study_identity=self.study_worker.register(prepared,request_id=key+':OWN-A02')
                record['study']={'identity':study_identity.as_dict(),'source_sha256':task_digest(original['objects']),
                    'observed':original['observed']};record=self._save(key,record)
                self.study_worker.execute(study_identity,prepared);authorization=checked_result(self.study_worker,study_identity)
                record['study']['result_sha256']=authorization['result_sha256'];record=self._save(key,record)
            return self._form(key,record,source,saved,request,stage='investment')

    def _form(self,key,record,source,saved,request,*,stage):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        policy,scope=self._current(request);identity=TaskIdentity(**saved['identity'])
        accepted,_=self._summary(saved,source,request,stage=stage)
        response=AgentProposalResponseV1(request_id=request.request_id,action_type='initiate_project',accepted=accepted,
            utility=float(policy.utility),probability=float(policy.probability),reason=saved['result']['payload']['note'],
            data={'selected_concept':deepcopy(request.inputs['opportunity'])},factors={
                'micro_action_id':identity.action_id,'micro_task_key':identity.key,
                'micro_result_sha256':saved['result_sha256'],'native_owner_opportunity_scope':scope})
        if record.get('proposal_response_sha256') not in {None,task_digest(response.model_dump(mode='json'))}:
            raise TaskConflict('Recovered opportunity differs from its original proposal response')
        record.update(state='formed',terminal_stage=stage,identity=identity.as_dict(),
            source_sha256=task_digest(source['objects']),context=source['context'].model_dump(mode='json'),
            action_input=source['action_input'],observed=source['observed'],
            source_grants=[g.model_dump(mode='json') for g in source['grants']],
            result_sha256=saved['result_sha256'],proposal_response_sha256=task_digest(response.model_dump(mode='json')))
        self._save(key,record);return response

    def decide(self,request):
        if (request.agent.role,request.decision_type)!=('Owner','owner_project_opportunity'):return self._other_decision(request)
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1,AgentDecisionResponseV1
        from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
        with self.read_guard():
            self._check();scope=owner_opportunity_scope(self.assembly,request,purpose='decide')
            record,=[r for r in self._records() if r['state']=='formed' and r['scope']==scope]
            original=AgentProposalRequestV1.model_validate(record['native_request']);policy,_=self._current(original)
            stage=record.get('terminal_stage','investment')
            source=self._sources(policy,original,scope,stage=stage)
            worker={'observation':self.observation_worker,'investment':self.worker,'proposal':self.proposal_worker}[stage]
            saved=checked_result(worker,TaskIdentity(**record['identity']))
            proposal,=[t['output'] for t in self.assembly.client.tasks.for_organization(run_id=self.assembly.client.run_id,
                organization_id=scope['owner_id']) if t['identity']['purpose']=='propose' and t['identity']['action_id']=='evaluate_project_opportunity'
                and t['state']=='output_formed' and t['output'].get('factors',{}).get('native_owner_opportunity_scope')==scope]
            accepted,action=self._summary(saved,source,original,stage=stage);support=request.decision_support
            if (request.project!=original_candidate_snapshot(self.assembly,original)
                    or task_digest(source['objects'])!=record['source_sha256'] or source['observed']!=record['observed']
                    or source['context'].model_dump(mode='json')!=record['context'] or source['action_input']!=record['action_input']
                    or saved['result_sha256']!=record['result_sha256'] or task_digest(proposal)!=record['proposal_response_sha256']
                    or support.get('decision_factors')!=proposal['factors'] or support.get('accepted')!=accepted
                    or support.get('action_type')!='initiate_project' or proposal['accepted']!=accepted
                    or proposal['action_type']!='initiate_project'
                    or proposal['data']!={'selected_concept':original.inputs['opportunity']}
                    or action not in request.constraints.allowed_actions):
                raise TaskConflict('Opportunity final confirmation changes original candidate, sources, result or proposal')
            response=AgentDecisionResponseV1(request_id=request.request_id,agent_id=scope['owner_id'],action_type=action,
                decision=accepted,reason=proposal['reason'],data={**proposal['factors'],'proposal_response_sha256':task_digest(proposal)})
            ExternalAgentDecisionProvider._validated_action(request,response);return response

    def evidence(self):
        with self.read_guard():
            self._check()
            return {'version':self.VERSION,'source_file_sha256':self.settings.file_sha256,'requests':self._records(),
                'source_implementations':self._source_pins,
                'native_routes':self.assembly.client.native_routes.evidence(),
                'limits':'Original A03 consumes independent synthetic comparisons, forecasts, cash/debt and capacity disclosures. If enabled, original A01 observes the current native global demand index; follow advances and ignore returns native defer without A03. Optional original A16 forms private briefs using the same cash, protected old obligations and management commitments; A03 consumes only its complete declared comparison including the non-build baseline. Original no_proposal returns native defer without A03; partial drafts remain pending. Other observation/proposal results stop for review. Strictly earlier own native non-initiation events are authenticated separately from project creations; an optional decline-count preference affects only private future initiation. Only the native core creates projects. Optional declared unresolved comparison questions let original A03 study_more trigger original A02 internal_study/commission/stop authorization before native defer. Commission consumes either an explicitly assumed initial standing offer or an authenticated original professional A02 decision and recipient-scoped technical handoff; neither proves a formal appointment or external native message receipt. Later own actual non-initiation history retains the linked private authorization and exact original offer. No research is executed or reported; proposed allocations do not reserve resources. Local survey, professional report production and rights acquisition are not claimed. Initial rights and scale-method domains are explicit synthetic assumptions. No formal case, right, investment, spending, resource-reservation or loan ledger is created in micro/integration.'}


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Explicit synthetic owner opportunity composition requires offline mode')
    assembly.client.native_routes.attach(assembly)
    app=OwnerOpportunityApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
