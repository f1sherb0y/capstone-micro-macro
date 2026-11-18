"""Original Supplier A04 drafts drive native project-order acceptance."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from pydantic import Field, model_validator

from integration.bank_financing_private import checked_result, evidence_binding
from integration.contractor_tender_authority_runtime import TenderAuthorityRuntimeSettings, build_authority_runtime
from integration.contractor_supply_native import ContractorSupplySettings, ContractorSupplyNativeApplication
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension, module_client_implementation, module_factory_descriptor
from integration.native_contract_supply import signed_contract_for_supply
from integration.supplier_order_actions import SupplierOrderActionAssembler
from integration.supplier_order_native_feedback import prior_supply_decisions, prior_supply_selections
from integration.supplier_order_native_decline import DECLINES, decline_for_supply
from integration.supplier_screening_decline_feedback import screening_decline_feedback
from integration.supply_native_outcome_query import query_supplier_outcome, query_contractor_supply_outcome, _original_result
from integration.supplier_order_native_recovery import recover_saved_supply_proposal, saved_supply_preflight, validate_saved_supply_stage
from integration.unstarted_action_continuation import execute_original_stage
from integration.supplier_order_native_scope import supply_scope
from integration.supplier_order_results import SupplierOrderResultWorker
from integration.supplier_order_native_quote import SupplierOrderQuoteStep, quote_for_order
from integration.supplier_order_native_product import product_for_quote
from integration.supplier_order_native_screening import screening_for_product
from integration.supplier_product_actions import SupplierProductActionAssembler
from integration.supplier_product_results import SupplierProductResultWorker
from integration.supplier_screening_actions import SupplierScreeningActionAssembler
from integration.supplier_screening_results import SupplierScreeningResultWorker
from integration.supplier_quote_actions import SupplierQuoteActionAssembler
from integration.supplier_quote_results import SupplierQuoteResultWorker
from src.actions.contracts.common import ActionContext, EvidenceRecord, Measured, Reference, StrictRecord, TextId, ref_type
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest
from src.methods.models import Digest


class SupplierOrderNativePlan(StrictRecord):
    organization_id: TextId
    project_id: TextId
    contractor_id: TextId | None=None
    tick: int=Field(ge=1)
    context: ActionContext
    action_input: dict
    objects: list[dict]
    native_evidence_ref: ref_type('Evidence')
    utility: Measured
    probability: Measured
    max_prior_selections: int | None=Field(default=None,ge=1,strict=True)
    decline_after_prior_declines: int | None=Field(default=None,ge=1,strict=True)
    require_native_award: bool=False
    quote: SupplierOrderQuoteStep | None=None

    @model_validator(mode='after')
    def actual_context(self):
        c=self.context
        if self.contractor_id is not None and not self.require_native_award:
            raise ValueError('Conditional buyer sources require an actual earlier native award')
        if self.decline_after_prior_declines is not None and not (
                self.quote and self.quote.product and self.quote.product.screening):
            raise ValueError('Supplier decline feedback requires the original A01 screening stage')
        if (c.contract_ref.id!='SUPPLIER-A04' or c.scope.kind!='project'
                or c.scope.ref.id!=self.project_id or c.business_time.offset!=self.tick or c.execution_mode=='offline_fixture'
                or len({task_digest(r['ref']) for r in self.objects})!=len(self.objects)):
            raise ValueError('Supply plan changes its original actor, action, scope, time or source identities')
        if self.quote is not None:
            q=self.quote.context
            if (q.run_id!=c.run_id or q.actor_id!=c.actor_id or q.scope!=c.scope or q.business_time!=c.business_time
                    or q.function_ref!=c.function_ref or q.read_token==c.read_token):
                raise ValueError('Supply quote must preserve its actual original supplier, project, clock and separate read point')
        contexts=[c]+([self.quote.context] if self.quote else [])
        if self.quote and self.quote.product:
            contexts.append(self.quote.product.context)
            if self.quote.product.screening:contexts.append(self.quote.product.screening.context)
        if (len({row.read_token for row in contexts})!=len(contexts)
                or len({row.operation_id for row in contexts})!=len(contexts)):
            raise ValueError('Supply stages require distinct original operations and read points')
        return self


class SupplierOrderNativeSettings(StrictRecord):
    version: TextId
    policy_version: TextId
    authority: TenderAuthorityRuntimeSettings
    file_path: TextId
    file_sha256: Digest
    contractor: ContractorSupplySettings | None=None
    allow_saved_recovery: bool=False
    continue_unstarted_actions_on_error: bool=False


class SupplierOrderNativeApplication:
    VERSION='gba-v1-supplier-order.v15'
    PREFIX='supplier_order_native_request:'

    def __init__(self,*,assembly,settings,authority=None,install=True):
        self.assembly=assembly;self.settings=SupplierOrderNativeSettings.model_validate(settings).model_copy(deep=True)
        self._check_file();doc=json.loads(Path(self.settings.file_path).read_bytes())
        if (set(doc)!={'schema_version','run_id','plans'} or doc['schema_version']!='supplier-order-native-input.v1'
                or doc['run_id']!=assembly.client.run_id):raise TaskConflict('Supply input changes its original schema or run')
        self.plans=[SupplierOrderNativePlan.model_validate(p) for p in doc['plans']]
        keys=[(p.organization_id,p.project_id,p.tick,p.contractor_id) for p in self.plans]
        if not keys or len(keys)!=len(set(keys)) or any(p.context.run_id!=doc['run_id'] for p in self.plans):
            raise TaskConflict('Supply inputs need unique original selectors in the same run')
        for org,project,tick,buyer in keys:
            if buyer is None and any(k[:3]==(org,project,tick) and k[3] is not None for k in keys):
                raise TaskConflict('Supply inputs mix unconditional and conditional buyer selectors')
        self._plans_sha=task_digest([p.model_dump(mode='json') for p in self.plans]);self._settings_sha=task_digest(self.settings.model_dump(mode='json'))
        self._award_reader=module_factory_descriptor(signed_contract_for_supply,'native-contract-supply.v1')
        self._screening_feedback_code=module_factory_descriptor(screening_decline_feedback,'supplier-screening-decline-feedback.v1')
        self._query_code=self._query_descriptors()
        self._owns_authority=authority is None
        self.authority=authority or build_authority_runtime(assembly=assembly,settings=self.settings.authority)
        if self.authority.assembly is not assembly or self.authority.settings!=self.settings.authority:
            raise TaskConflict('Supply shared authority must match its exact declared assembly and snapshot')
        self.registry,self.organizations=self.authority.registry,self.authority.organizations
        self.read_guard=self.authority.read_guard;self.snapshots=InvocationSnapshotStore(assembly.client.tasks)
        self.recovery_guard=self.read_guard;self._recovery_code=self._recovery_descriptor()
        self._bound={};self._implementation=None;client=assembly.client;routes=client.native_routes
        self._other_decision=client.decision_handler;self._native_settings=task_digest(routes.settings.model_dump(mode='json'))
        try:
            if routes.settings.query_saved_supply_on_error and not self.settings.allow_saved_recovery:
                raise TaskConflict('Supply query on error requires explicit saved-result recovery authorization')
            if (not routes.settings.micro_supplier_order_scope or ('Supplier','consider_supply_order') in routes._proposals
                    or ('Supplier','supplier_order_acceptance') in routes._decisions):
                raise TaskConflict('Micro supply acceptance needs exclusive original proposal/final ownership')
            self.assembler=SupplierOrderActionAssembler(registry=self.registry,organizations=self.organizations,provider=self,
                macro_version='gba-public-2026-08-21',source_mode='formal',policy_version=self.settings.policy_version,
                model_version=client.versions['model'])
            self.worker=SupplierOrderResultWorker(store=client.tasks,snapshots=self.snapshots,registry=self.registry,
                client_version=self.VERSION,model_version=client.versions['model'],validate_invocation=self.validate_invocation,
                validate_wait=self.validate_wait,validate_recovery=self.validate_recovery)
            self.quote_assembler=SupplierQuoteActionAssembler(registry=self.registry,organizations=self.organizations,provider=self,
                macro_version='gba-public-2026-08-21',source_mode='formal',policy_version=self.settings.policy_version,
                model_version=client.versions['model'])
            self.quote_worker=SupplierQuoteResultWorker(store=client.tasks,snapshots=self.snapshots,registry=self.registry,
                client_version=self.VERSION,model_version=client.versions['model'],validate_invocation=self.validate_invocation,
                validate_wait=self.validate_wait,validate_recovery=self.validate_recovery)
            self.product_assembler=SupplierProductActionAssembler(registry=self.registry,organizations=self.organizations,provider=self,
                macro_version='gba-public-2026-08-21',source_mode='formal',policy_version=self.settings.policy_version,
                model_version=client.versions['model'])
            self.product_worker=SupplierProductResultWorker(store=client.tasks,snapshots=self.snapshots,registry=self.registry,
                client_version=self.VERSION,model_version=client.versions['model'],validate_invocation=self.validate_invocation,
                validate_wait=self.validate_wait,validate_recovery=self.validate_recovery)
            self.screening_assembler=SupplierScreeningActionAssembler(registry=self.registry,organizations=self.organizations,provider=self,
                macro_version='gba-public-2026-08-21',source_mode='formal',policy_version=self.settings.policy_version,
                model_version=client.versions['model'])
            self.screening_worker=SupplierScreeningResultWorker(store=client.tasks,snapshots=self.snapshots,registry=self.registry,
                client_version=self.VERSION,model_version=client.versions['model'],validate_invocation=self.validate_invocation,
                validate_wait=self.validate_wait,validate_recovery=self.validate_recovery)
            self.contractor=None
            if (self.settings.contractor is not None)!=routes.settings.micro_contractor_supply_scope:
                raise TaskConflict('Micro Contractor supply must be explicitly configured with exclusive native routing')
            if self.settings.contractor is not None:
                self.contractor=ContractorSupplyNativeApplication(supplier=self,settings=self.settings.contractor)
            if install:self.install()
        except Exception:
            if self._owns_authority:self.authority.close()
            raise

    def proposal_bindings(self):
        result={('Supplier','consider_supply_order'):self.propose}
        if self.contractor is not None:
            result[('Contractor','select_supplier')]=self.contractor.propose
        return result

    def seal_client_binding(self):
        client=self.assembly.client
        with client._lock:
            if (self._implementation is not None or client._calls or client._request_hashes
                    or client.binding_installation_blocked()
                    or any(client.proposal_handlers.get(key)!=handler for key,handler in self.proposal_bindings().items())):
                raise TaskConflict('Supply client binding must be sealed once before requests, preserving every owned handler')
            self._implementation=module_client_implementation(client)

    def install(self):
        client=self.assembly.client
        with client._lock:
            for (role,operation),handler in self.proposal_bindings().items():
                client.bind_proposal_handler(role=role,operation=operation,handler=handler,
                    client_version=self.VERSION+':'+role)
            client.decision_handler=self.decide
            self.seal_client_binding()

    def _check_file(self):
        if hashlib.sha256(Path(self.settings.file_path).read_bytes()).hexdigest()!=self.settings.file_sha256:
            raise TaskConflict('Supply independent inputs changed their pinned bytes')

    @staticmethod
    def _recovery_descriptor():
        return {name:module_factory_descriptor(function,'supplier-saved-recovery.v1')
            for name,function in [('preflight',saved_supply_preflight),('validate',validate_saved_supply_stage),
                ('reconcile',recover_saved_supply_proposal),('unstarted',execute_original_stage)]}

    def _check(self):
        self.assembly._validate_components();self._check_file()
        if self.contractor is not None:self.contractor.check_components()
        if (task_digest(self.settings.model_dump(mode='json'))!=self._settings_sha
                or self.recovery_guard is not self.read_guard or self._recovery_descriptor()!=self._recovery_code
                or any(w.validate_recovery!=self.validate_recovery
                    for w in (self.worker,self.quote_worker,self.product_worker,self.screening_worker))
                or self._query_descriptors()!=self._query_code
                or module_factory_descriptor(signed_contract_for_supply,'native-contract-supply.v1')!=self._award_reader
                or module_factory_descriptor(screening_decline_feedback,'supplier-screening-decline-feedback.v1')!=self._screening_feedback_code
                or task_digest([p.model_dump(mode='json') for p in self.plans])!=self._plans_sha
                or task_digest(self.assembly.client.native_routes.settings.model_dump(mode='json'))!=self._native_settings
                or self._implementation is None or module_client_implementation(self.assembly.client)!=self._implementation
                or self.worker.store is not self.assembly.client.tasks or self.worker.registry is not self.registry
                or self.assembler.organizations is not self.organizations
                or self.quote_worker.store is not self.worker.store or self.quote_worker.registry is not self.registry
                or self.quote_assembler.organizations is not self.organizations
                or self.product_worker.store is not self.worker.store or self.product_worker.registry is not self.registry
                or self.product_assembler.organizations is not self.organizations
                or self.screening_worker.store is not self.worker.store or self.screening_worker.registry is not self.registry
                or self.screening_assembler.organizations is not self.organizations):
            raise TaskConflict('Supply host changes original sources, plans, handlers or shared runtime')

    @staticmethod
    def _query_descriptors():
        return {name:module_factory_descriptor(function,'native-supply-outcome-query.v1') for name,function in
            [('supplier',query_supplier_outcome),('contractor',query_contractor_supply_outcome),
             ('original_result',_original_result)]}

    def query_native_outcome(self,identity,*,organization_id,tick):
        return query_supplier_outcome(self,identity,organization_id=organization_id,tick=tick)

    def plan_for_scope(self,organization_id,scope):
        plans=[p for p in self.plans if (p.organization_id,p.project_id,p.tick)==(organization_id,scope['project_id'],scope['tick'])
            and (p.contractor_id is None or p.contractor_id==scope['contractor_id'])]
        if len(plans)!=1:raise TaskConflict('Supply request has no unique independent current plan')
        return plans[0]

    def _current(self,request):
        self._check();scope=supply_scope(self.assembly,request,purpose='propose')
        if request.operation!='consider_supply_order':raise TaskConflict('Micro supply acceptance needs the original Supplier request')
        plan=self.plan_for_scope(request.agent.agent_id,scope)
        inputs=plan.action_input;project=self.assembly.engine.projects[plan.project_id]
        proposal,=[r['value'] for r in plan.objects if r['ref']==inputs['order_proposal_ref']]
        offer,=[r['value'] for r in plan.objects if r['ref']==inputs['offer_ref']]
        grants=self.organizations.grants(plan.context,'SUPPLIER-A04','Supplier')
        if (not grants or grants[0].organization_id!=plan.organization_id or proposal['scope']!=plan.context.scope.model_dump(mode='json')
                or any(r['supplier_organization_id']!=plan.organization_id or r['buyer_id']!=scope['contractor_id']
                    or r['payer_id']!=scope['contractor_id'] for r in (proposal,offer))
                or proposal['recipient_actor_id']!=plan.context.actor_id
                or not any(c.get('contractor_id')==scope['contractor_id'] for c in project.contracts)
                or request.inputs['required_resource']!=0.35):
            raise TaskConflict('Supply sources change the actual supplier, signed-project buyer/payer or scope')
        return plan,scope

    def _sources(self,plan,request,*,stage='order'):
        selected=self._step(plan,stage)
        self._authorize_step(plan,stage)
        objects=deepcopy(selected.objects)
        history=prior_supply_selections(self.assembly,organization_id=plan.organization_id,tick=plan.tick,read_guard=self.read_guard,query_original=self.query_native_outcome)
        observed={'scope':supply_scope(self.assembly,request,purpose='propose'),
            'native_request_sha256':task_digest(request.model_dump(mode='json')),'prior_supply_selections':history,
            'max_prior_selections':plan.max_prior_selections,
            'prior_supply_decisions':prior_supply_decisions(self.assembly,organization_id=plan.organization_id,tick=plan.tick,
                read_guard=self.read_guard,workers={'SUPPLIER-A01':self.screening_worker,'SUPPLIER-A02':self.product_worker,
                    'SUPPLIER-A03':self.quote_worker,'SUPPLIER-A04':self.worker},query_original=self.query_native_outcome)}
        if plan.require_native_award:
            observed['native_signed_contract']=signed_contract_for_supply(self.assembly,
                scope=observed['scope'],organization_id=plan.organization_id)
        native=selected.native_evidence_ref
        if stage=='screening':
            feedback=screening_decline_feedback(self,plan=plan,objects=objects,history=observed['prior_supply_decisions'])
            if feedback is not None:observed['screening_decline_feedback']=feedback
        if stage=='product' and plan.quote.product.screening is not None:
            saved,technical=self._completed_step(plan,request,'screening')
            observed['screening']=screening_for_product(saved,invocation=self.snapshots.get(TaskIdentity(**technical['identity'])),
                step=plan.quote.product.screening,product=plan.quote.product,objects=objects)
        if stage=='quote' and plan.quote.product is not None:
            saved,technical=self._completed_step(plan,request,'product')
            observed['product']=product_for_quote(saved,invocation=self.snapshots.get(TaskIdentity(**technical['identity'])),
                step=plan.quote.product,quote=plan.quote,objects=objects)
        if stage=='order' and plan.quote is not None:
            technical,=[r for r in self._records() if r['scope']==observed['scope']
                and r['native_request']['agent']['agent_id']==plan.organization_id
                and r['native_request']==request.model_dump(mode='json')]
            step=technical.get('quote')
            if not step or 'result_sha256' not in step:raise TaskConflict('A04 awaits its original completed quote preparation')
            saved=checked_result(self.quote_worker,TaskIdentity(**step['identity']))
            original_objects,original_observed=self._sources(plan,request,stage='quote')
            if (saved['result_sha256']!=step['result_sha256'] or task_digest(original_objects)!=step['source_sha256']
                    or original_observed!=step['observed']):raise TaskConflict('Supply quote changed its original current input sources')
            observed['quote']=quote_for_order(saved,invocation=self.snapshots.get(TaskIdentity(**step['identity'])),
                step=plan.quote,plan=plan,objects=objects)
        if stage=='order' and plan.max_prior_selections is not None and len(history)>=plan.max_prior_selections:
            profile,=[r['value'] for r in objects if r['ref']==plan.action_input['formation_profile_ref']]
            if profile['policy']!='evaluate' or plan.native_evidence_ref.model_dump(mode='json') not in profile['evidence_refs']:
                raise TaskConflict('Supply feedback policy lacks its explicit baseline and observed evidence dependency')
            profile['policy']='reject_new_orders'
        evidence_binding(objects,native.model_dump(mode='json'),observed)
        return objects,observed

    @staticmethod
    def _step(plan,stage):
        product=plan.quote.product if plan.quote else None
        selected={'order':plan,'quote':plan.quote,'product':product,'screening':product.screening if product else None}.get(stage)
        if selected is None:raise TaskConflict('Supply source selection changes its declared original stage')
        return selected

    def _completed_step(self,plan,request,stage):
        scope=supply_scope(self.assembly,request,purpose='propose')
        technical,=[r for r in self._records() if r['scope']==scope
            and r['native_request']==request.model_dump(mode='json')]
        step=technical.get(stage)
        if not step or 'result_sha256' not in step:raise TaskConflict('Supply awaits its original completed '+stage)
        worker={'screening':self.screening_worker,'product':self.product_worker,'quote':self.quote_worker}[stage]
        saved=checked_result(worker,TaskIdentity(**step['identity']))
        self._authorize_step(plan,stage,source_reading=saved['source_reading'])
        objects,observed=self._sources(plan,request,stage=stage)
        if (saved['result_sha256']!=step['result_sha256'] or task_digest(objects)!=step['source_sha256']
                or observed!=step['observed']):raise TaskConflict('Supply predecessor changed its original current sources')
        return saved,step

    def _authorize_step(self,plan,stage,*,source_reading=()):
        """Resolve actor ownership through current original grants, not ID equality."""
        context=self._step(plan,stage).context
        grants=self.organizations.grants(context,context.contract_ref.id,'Supplier')
        if any(g.organization_id!=plan.organization_id for g in grants):
            raise TaskConflict('Supply stage actor is not authorized for the original Supplier organization')
        permitted={r.key() for g in grants for r in g.readable_refs} & {r.key() for r in context.visible_refs}
        if any(Reference.model_validate(row['ref']).key() not in permitted for row in source_reading):
            raise TaskConflict('Supply handoff lost current authority for its original private reading')

    def _product_history(self,plan,request,saved):
        original,_=self._completed_step(plan,request,'product')
        if (saved.identity.as_dict()!=original['identity'] or saved.record_sha256!=original['record_sha256']
                or saved.result.model_dump(mode='json')!=original['result']
                or list(saved.source_reading)!=original['source_reading']):
            raise TaskConflict('Quote handoff changes its actual original saved product result')
        return True

    def _screening_history(self,plan,request,saved):
        original,_=self._completed_step(plan,request,'screening')
        if (saved.identity.as_dict()!=original['identity'] or saved.record_sha256!=original['record_sha256']
                or saved.result.model_dump(mode='json')!=original['result']
                or list(saved.source_reading)!=original['source_reading']):
            raise TaskConflict('Product handoff changes its actual original saved screening result')
        return True

    def _screening_current(self,plan,request,*,saved,context,basis,original,inquiry,requirements):
        self._screening_history(plan,request,saved)
        product=plan.quote.product;objects,_=self._sources(plan,request,stage='product')
        selected={task_digest(r['ref']):r['value'] for r in objects}
        expected=selected[task_digest(product.screening.handoff_basis_ref.model_dump(mode='json'))]
        if (context!=product.context or basis.model_dump(mode='json')!=expected or original!=inquiry
                or inquiry.model_dump(mode='json')!=selected[task_digest(product.action_input['inquiry_ref'])]
                or {task_digest(r.ref.model_dump(mode='json')) for r in requirements}
                    !={task_digest(r) for r in product.action_input['requirement_refs']}
                or any(r.model_dump(mode='json')!=selected[task_digest(r.ref.model_dump(mode='json'))] for r in requirements)):
            raise TaskConflict('Product handoff changes the actual received inquiry or independent requirement sources')
        return True

    def _product_current(self,plan,request,*,saved,context,basis,proposals):
        self._product_history(plan,request,saved)
        objects,_=self._sources(plan,request,stage='quote')
        expected,=[r['value'] for r in objects if r['ref']==plan.quote.product.handoff_basis_ref.model_dump(mode='json')]
        selected={task_digest(r['ref']):r['value'] for r in objects}
        if (context!=plan.quote.context or basis.model_dump(mode='json')!=expected
                or {task_digest(p.ref.model_dump(mode='json')) for p in proposals}
                    !={task_digest(r) for r in plan.quote.action_input['product_proposal_refs']}
                or any(p.model_dump(mode='json')!=selected[task_digest(p.ref.model_dump(mode='json'))] for p in proposals)):
            raise TaskConflict('Quote handoff changes the original current independent product sources')
        return True

    def project(self,*,context,organization_id,grants):
        bound=self._bound.get(task_digest(context.model_dump(mode='json')))
        if bound is None or organization_id!=bound[0].organization_id:raise TaskConflict('Supply view changes its bound private request')
        plan,request,stage=bound;self._current(request);objects,_=self._sources(plan,request,stage=stage)
        return {'run_id':context.run_id,'macro_version':'gba-public-2026-08-21','state_version':'native-supply:'+task_digest(objects),
            'read_token':context.read_token,'business_time':context.business_time.model_dump(mode='json'),
            'organization_id':organization_id,'objects':objects}

    def validate_invocation(self,row,prepared):
        plan,request,stage=self._bound[prepared.context_sha256];self._current(request)
        context=self._step(plan,stage).context
        if (prepared.context!=context or row['identity']['organization_id']!=plan.organization_id
                or prepared.runner.registry is not self.registry):raise TaskConflict('Supply worker changes its original invocation')
        prepared.reading.recheck();return True

    def validate_wait(self,*args,**kwargs):raise TaskConflict('Unresolved supply acceptance needs diagnosis and explicit continuation')

    def _execute_stage(self,worker,identity,prepared,key,record,stage):
        return execute_original_stage(worker=worker,identity=identity,prepared=prepared,
            enabled=self.settings.continue_unstarted_actions_on_error,record=record,stage=stage,
            save_record=lambda value:self._save(key,value))

    def validate_recovery(self,row,saved,snapshot):
        return validate_saved_supply_stage(self,row,saved,snapshot)

    def recover_saved_proposal(self,request):
        return recover_saved_supply_proposal(self,request)

    def _records(self,*,prefix=None):
        with self.assembly.client.tasks._lock:
            rows=[json.loads(v) for v, in self.assembly.client.tasks._db.execute('SELECT value FROM metadata WHERE key LIKE ?',((prefix or self.PREFIX)+'%',))]
        if any(r['record_sha256']!=task_digest({k:v for k,v in r.items() if k!='record_sha256'}) for r in rows):
            raise TaskConflict('Supply original technical request record changed')
        return rows

    def _save(self,key,value):
        value=deepcopy(value);value['record_sha256']=task_digest({k:v for k,v in value.items() if k!='record_sha256'})
        with self.assembly.client.tasks._transaction():
            self.assembly.client.tasks._db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)',(key,canonical(value)))
        return value

    def _summary(self,result,stage='order'):
        choice=result['payload']['choice']
        if stage in DECLINES:
            if choice!=DECLINES[stage][1]:raise TaskConflict('Only an explicit completed upstream commercial decline can reject supply')
            return False,'decline_supply_order'
        if choice not in {'accept','reject'}:raise TaskConflict('Supply partial, revised or unresolved proposals cannot become full native acceptance')
        accepted=choice=='accept';return accepted,'accept_supply_order' if accepted else 'decline_supply_order'

    def _form(self,request,plan,scope,record,prepared,saved,*,stage='order'):
        identity=TaskIdentity(**saved['identity']);objects,observed=self._sources(plan,request,stage=stage)
        response=self._proposal_response(request,plan,scope,identity,saved,objects,prepared.reading,stage=stage)
        if stage!='order':
            record['decline_binding']=decline_for_supply(saved,invocation=self.snapshots.get(identity),plan=plan,stage=stage)
        record.update(identity=identity.as_dict(),source_sha256=task_digest(objects),observed=observed,
            result_sha256=saved['result_sha256'],terminal_stage=stage)
        record.update(state='formed',proposal_response_sha256=task_digest(response.model_dump(mode='json')))
        self._save(record['key'],record);return response

    def _proposal_response(self,request,plan,scope,identity,saved,objects,reading,*,stage='order'):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        accepted,action=self._summary(saved['result'],stage)
        # Indicators remain the explicitly sourced native comparison measures,
        # never a price, stock reservation or inferred upstream acceptance.
        for metric,unit in [(plan.utility,'score'),(plan.probability,'probability')]:
            basis=next((r['value'] for r in objects if r['ref']==metric.basis_ref.model_dump(mode='json')),None)
            if metric.unit!=unit or not 0<=Decimal(metric.value)<=1 or basis is None:
                raise TaskConflict('Supply native indicators need explicit bounded units and evidence')
            if not isinstance(reading.resolve(metric.basis_ref),EvidenceRecord):
                raise TaskConflict('Supply native indicators require evidence in the actual deciding stage')
        response=AgentProposalResponseV1(request_id=request.request_id,action_type=action,accepted=accepted,
            utility=float(plan.utility.value),probability=float(plan.probability.value),reason=saved['result']['payload']['note'],
            data={'offer_score':float(plan.utility.value)},factors={'micro_action_id':identity.action_id,'micro_task_key':identity.key,
                'micro_result_sha256':saved['result_sha256'],'native_supply_scope':scope})
        return response

    def propose(self,request):
        with self.read_guard():
            plan,scope=self._current(request)
            key=self.PREFIX+task_digest([self.assembly.client.simulation_id,plan.organization_id,scope,request.request_id])
            if any(r['key']==key for r in self._records()):raise TaskConflict('Supply request already claimed; recover its original transport')
            record=self._save(key,{'key':key,'scope':scope,'state':'preparing','native_request':request.model_dump(mode='json')})
            self._bound[task_digest(plan.context.model_dump(mode='json'))]=(plan,request.model_copy(deep=True),'order')
            if plan.quote is not None:
                q=plan.quote;self._bound[task_digest(q.context.model_dump(mode='json'))]=(plan,request.model_copy(deep=True),'quote')
                if q.product is not None:
                    p=q.product;self._bound[task_digest(p.context.model_dump(mode='json'))]=(plan,request.model_copy(deep=True),'product')
                    if p.screening is not None:
                        s=p.screening;self._bound[task_digest(s.context.model_dump(mode='json'))]=(plan,request.model_copy(deep=True),'screening')
                        screening_objects,screening_observed=self._sources(plan,request,stage='screening')
                        screening=self.screening_assembler.build(s.context,**deepcopy(s.action_input))
                        for row in screening_objects:screening.reading.resolve(Reference.model_validate(row['ref']))
                        screening=replace(screening,reading_sha256=task_digest(screening.reading.evidence()))
                        screening_identity=self.screening_worker.register(screening,request_id=key+':SUPPLIER-A01')
                        record['screening']={'identity':screening_identity.as_dict(),'source_sha256':task_digest(screening_objects),'observed':screening_observed}
                        record=self._save(key,record)
                        self._execute_stage(self.screening_worker,screening_identity,screening,key,record,'screening')
                        screening_saved=checked_result(self.screening_worker,screening_identity)
                        record['screening']['result_sha256']=screening_saved['result_sha256'];record=self._save(key,record)
                        if screening_saved['result']['payload']['choice']=='decline':
                            return self._form(request,plan,scope,record,screening,screening_saved,stage='screening')
                        if screening_saved['result']['payload']['choice']!='respond':
                            raise TaskConflict('Only an actual full screening response supports this product composition; other results need review')
                    product_objects,product_observed=self._sources(plan,request,stage='product')
                    if p.screening is None:product=self.product_assembler.build(p.context,**deepcopy(p.action_input))
                    else:
                        screening_identity=TaskIdentity(**record['screening']['identity'])
                        handoff=self.product_assembler.build_from_screening(p.context,screening_worker=self.screening_worker,
                            screening_identity=screening_identity,screening_execution_versions=screening_identity.versions,
                            basis_ref=p.screening.handoff_basis_ref,validate_history=lambda saved:self._screening_history(plan,request,saved),
                            validate_current=lambda **kwargs:self._screening_current(plan,request,**kwargs),**deepcopy(p.action_input))
                        if handoff['kind']!='prepared':raise TaskConflict('Original screening handoff remains unresolved before product preparation')
                        product=handoff['invocation']
                    for row in product_objects:product.reading.resolve(Reference.model_validate(row['ref']))
                    product=replace(product,reading_sha256=task_digest(product.reading.evidence()))
                    product_identity=self.product_worker.register(product,request_id=key+':SUPPLIER-A02')
                    record['product']={'identity':product_identity.as_dict(),'source_sha256':task_digest(product_objects),'observed':product_observed}
                    record=self._save(key,record)
                    self._execute_stage(self.product_worker,product_identity,product,key,record,'product')
                    product_saved=checked_result(self.product_worker,product_identity)
                    record['product']['result_sha256']=product_saved['result_sha256'];record=self._save(key,record)
                    if product_saved['result']['payload']['choice']=='decline':
                        return self._form(request,plan,scope,record,product,product_saved,stage='product')
                    if product_saved['result']['payload']['choice'] not in {'propose_original','propose_substitute'}:
                        raise TaskConflict('Unresolved or declined product requires explicit review before quote preparation')
                quote_objects,quote_observed=self._sources(plan,request,stage='quote')
                if q.product is None:quoted=self.quote_assembler.build(q.context,**deepcopy(q.action_input))
                else:
                    product_identity=TaskIdentity(**record['product']['identity'])
                    handoff=self.quote_assembler.build_from_products(q.context,product_worker=self.product_worker,
                        product_identity=product_identity,product_execution_versions=product_identity.versions,
                        basis_ref=q.product.handoff_basis_ref,validate_history=lambda saved:self._product_history(plan,request,saved),
                        validate_current=lambda **kwargs:self._product_current(plan,request,**kwargs),**deepcopy(q.action_input))
                    if handoff['kind']!='prepared':raise TaskConflict('Original product handoff remains unresolved before quote preparation')
                    quoted=handoff['invocation']
                for row in quote_objects:quoted.reading.resolve(Reference.model_validate(row['ref']))
                quoted=replace(quoted,reading_sha256=task_digest(quoted.reading.evidence()))
                quote_identity=self.quote_worker.register(quoted,request_id=key+':SUPPLIER-A03')
                record['quote']={'identity':quote_identity.as_dict(),'source_sha256':task_digest(quote_objects),'observed':quote_observed}
                record=self._save(key,record)
                self._execute_stage(self.quote_worker,quote_identity,quoted,key,record,'quote')
                quote_saved=checked_result(self.quote_worker,quote_identity)
                record['quote']['result_sha256']=quote_saved['result_sha256'];record=self._save(key,record)
                if quote_saved['result']['payload']['choice']=='decline_quote':
                    return self._form(request,plan,scope,record,quoted,quote_saved,stage='quote')
                if quote_saved['result']['payload']['choice']!='quote':
                    raise TaskConflict('Unresolved or declined quote requires explicit review of the independent existing order')
            objects,observed=self._sources(plan,request);prepared=self.assembler.build(plan.context,**deepcopy(plan.action_input))
            # A04's base assembly reads only the primary inputs. Freeze this
            # invocation's declared dependency versions before registration,
            # including actual feedback Evidence and the commitment plan.
            for row in objects:prepared.reading.resolve(Reference.model_validate(row['ref']))
            prepared=replace(prepared,reading_sha256=task_digest(prepared.reading.evidence()))
            identity=self.worker.register(prepared,request_id=key+':SUPPLIER-A04')
            record.update(identity=identity.as_dict(),source_sha256=task_digest(objects),observed=observed)
            record=self._save(key,record)
            self._execute_stage(self.worker,identity,prepared,key,record,'order');saved=checked_result(self.worker,identity)
            return self._form(request,plan,scope,record,prepared,saved)

    def decide(self,request):
        if self.contractor is not None and (request.agent.role,request.decision_type)==('Contractor','contractor_supplier_selection'):
            return self.contractor.decide(request)
        if (request.agent.role,request.decision_type)!=('Supplier','supplier_order_acceptance'):return self._other_decision(request)
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1,AgentDecisionResponseV1
        with self.read_guard():
            self._check();scope=supply_scope(self.assembly,request,purpose='decide')
            record,=[r for r in self._records() if r['state']=='formed' and r['scope']==scope
                and r['native_request']['agent']['agent_id']==request.agent.agent_id]
            original=AgentProposalRequestV1.model_validate(record['native_request']);plan,_=self._current(original)
            stage=record.get('terminal_stage','order')
            worker={'order':self.worker,'screening':self.screening_worker,'product':self.product_worker,'quote':self.quote_worker}[stage]
            identity=TaskIdentity(**record['identity']);saved=checked_result(worker,identity)
            objects,observed=self._sources(plan,original,stage=stage)
            if stage!='order' and decline_for_supply(saved,invocation=self.snapshots.get(identity),plan=plan,stage=stage)!=record.get('decline_binding'):
                raise TaskConflict('Supply confirmation changes its original complete-demand decline')
            accepted,action=self._summary(saved['result'],stage);support=request.decision_support
            proposal,=[t['output'] for t in self.assembly.client.tasks.for_organization(run_id=plan.context.run_id,organization_id=plan.organization_id)
                if t['identity']['purpose']=='propose' and t['identity']['action_id']=='consider_supply_order' and t['state']=='output_formed'
                and t['output'].get('factors',{}).get('native_supply_scope')==scope]
            if (task_digest(objects)!=record['source_sha256'] or observed!=record['observed'] or saved['result_sha256']!=record['result_sha256']
                    or task_digest(proposal)!=record['proposal_response_sha256'] or support.get('decision_factors')!=proposal['factors']
                    or support.get('accepted')!=accepted or support.get('action_type')!=action
                    or support.get('offer_score')!=proposal['data']['offer_score'] or action not in request.constraints.allowed_actions):
                raise TaskConflict('Supply confirmation changes its original micro result, proposal or current sources')
            return AgentDecisionResponseV1(request_id=request.request_id,agent_id=plan.organization_id,action_type=action,decision=accepted,
                reason=saved['result']['payload']['note'],data={**proposal['data'],**proposal['factors'],
                    'proposal_response_sha256':record['proposal_response_sha256']})

    def evidence(self):
        with self.read_guard():
            self._check();return {'version':self.VERSION,'source_file_sha256':self.settings.file_sha256,'requests':self._records(),
                **({'contractor':self.contractor.evidence()} if self.contractor is not None else {}),
                'native_routes':self.assembly.client.native_routes.evidence(),
                'saved_recovery':{'enabled':self.settings.allow_saved_recovery,'code':self._recovery_code,
                    'entry':'assembly.client.recover_proposal(original_request)',
                    'limits':'Original in-process completed terminal result only; no unstarted stage, processor replay, engine restart or formal order.'},
                'unstarted_continuation':{'enabled':self.settings.continue_unstarted_actions_on_error,
                    'implementation':'integration.unstarted_action_continuation:execute_original_stage',
                    'limits':'Same open native call and registered original invocation only. No repeat preparation, missing-stage creation, unknown-result replay or engine restart.'},
                'limits':'Original A04 drafts or complete-demand A01/A02/A03 declines map to native project supply willingness/selection, not detailed SupplyOrder, stock reservation or payment.'}


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    if offline is not True:raise ValueError('Supply development composition requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app=SupplierOrderNativeApplication(assembly=assembly,settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION,evidence=app.evidence,close=app.authority.close,writer_guard=app.read_guard)
