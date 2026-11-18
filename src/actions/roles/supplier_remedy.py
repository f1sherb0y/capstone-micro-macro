"""SUPPLIER-A11 proposes corrections without erasing installed use or payment."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord,Known,TimeWindow
from src.actions.contracts.supplier_remedy_objects import (
    SupplierRemedyOrderView,SupplierRemedyOrderLineView,SupplierRemedyProfileView,SupplierRemedyProcedureView,
    SupplierSupplyChangeRequestView,SupplierSupplyChangeProposalView,SupplierInstalledUseView,SupplierRemovalRecordView,
    SupplierRemedyRightView,SupplierRemedyTaskPlanView,SupplierRemedyPhysicalSliceView,SupplierRemedyStepView,
    SupplierRemedyDependencyView,SupplierRemedyProductRequirementView,SupplierRemedyDeviationView,
    SupplierOriginalTransactionView,SupplierRefundExecutionView,SupplierRemedyAmountView,SupplierRemedyRequestView,
    SupplierQualityBatchView,SupplierVisibleDefectView,SupplierQualityEvidenceView,SupplierPlanningMethodView,SupplierPlanningResourceView,
    SupplierInventoryAllocationView,SupplierPlanningRequirementView,SupplierWorkAuthorityView,QuoteInventoryView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap,_needs,_unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.pricing import decimal_fraction
from src.methods.supplier_payment import CLAIM_METHOD
from src.organization.models import Authorization,RoleAssignment
from src.organization.registry import scope_covers


def propose_supply_remedy(context,action_input,reading):
    now,org,scope=context.business_time,reading.organization_id,context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref!=now.clock_ref:_unsupported('supplier-remedy-clock-alignment')

    def evidence(refs,*,at=None,historic=False):
        point=now if at is None else at
        clock(point)
        if point.offset>now.offset:_needs('received_original_supply_remedy_evidence_time')
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord):_unsupported('supplier-remedy-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if row.effective_window.start.offset>now.offset:_needs('received_original_supply_remedy_evidence',[ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_supply_remedy_evidence_valid_at_use',[ref])

    def read(ref,schema,historic=False,linked=False,*,evidence_at_field=None):
        row=reading.resolve(ref)
        if not isinstance(row,schema):_unsupported('supplier-remedy-projection:'+ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Remedy source expands original authorized scope')
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset:_needs('received_original_supply_remedy_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now):_needs('current_original_supply_remedy_source',[ref])
        point=None if evidence_at_field is None else getattr(row,evidence_at_field)
        if point is not None:
            clock(point)
            if point.offset>now.offset:_needs('received_original_supply_remedy_evidence_time',[ref])
            if point.offset>row.available_at.offset:raise ValueError('Remedy source precedes its actual event or authorship')
        evidence(getattr(row,'evidence_refs',[]),at=point,historic=historic)
        return row

    def true(value):return isinstance(value,Known) and value.value is True

    def authorize(ref,actor,function,organization,action,at,target):
        grant=read(ref,Authorization,historic=True,linked=True);assignment=read(function,RoleAssignment,historic=True,linked=True)
        roles={'SUPPLIER':'Supplier','CONTRACTOR':'Contractor','OWN':'Owner','QS':'QS','ENGINEER':'Engineer','ARCHITECT':'Architect','GOV':'Government','BANK':'Bank'}
        if (grant.actor_id!=actor or grant.function_ref!=function or grant.organization_id!=organization
                or assignment.function_ref!=function or assignment.role!=roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Supply remedy substitutes original independent actor/function/scope authority')
        clock(at);clock(grant.validity.start)
        if at.offset>now.offset:_needs('received_original_supply_remedy_author_time',[ref])
        if not grant.validity.contains(at):_needs('original_supply_remedy_authority_at_execution',[ref])
        for basis_ref in [*grant.basis_refs,*assignment.basis_refs]:
            if basis_ref.kind=='Evidence':evidence([basis_ref],at=at)
            else:reading.resolve(basis_ref)
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset>row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Remedy source precedes original actual author execution')
        return authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,row.author_organization_id,
            row.author_action_id,row.authored_at,row.scope)

    def q(value,unit=None,positive=False,*,at=None,historic=False):
        evidence([value.basis_ref],at=at,historic=historic);amount=decimal_fraction(value.value)
        if unit is not None and value.unit!=unit or amount<0 or positive and amount==0:
            raise ValueError('Remedy quantity changes original units or actual positive amount')
        return amount

    def cash(value,*,at=None,historic=False):
        evidence([value.basis_ref],at=at,historic=historic);amount=decimal_fraction(value.value)
        if value.currency!=order.currency or amount<0:raise ValueError('Remedy money changes original currency or is negative')
        return amount

    def product(line):
        if not scope_covers(scope,line.destination_scope_ref) or not line.requirement_refs:
            raise ValueError('Remedy product proposal changes original destination or omits specific requirements')
        quantity=q(line.quantity,positive=True);keys(line.requirement_refs);keys(line.deviation_refs)
        for ref in line.requirement_refs:
            req=read(ref,SupplierRemedyProductRequirementView)
            if req.order_ref!=order.ref or line.product_ref.key() not in keys(req.product_refs):
                raise ValueError('Remedy product requirement replaces original order or specification')
        for ref in line.deviation_refs:
            deviation=read(ref,SupplierRemedyDeviationView,evidence_at_field='authored_at');author(deviation)
            if (deviation.order_ref!=order.ref or deviation.product_ref!=line.product_ref or deviation.status=='rejected'
                    or not keys(deviation.requirement_refs)<=keys(line.requirement_refs)):
                raise ValueError('Remedy deviation substitutes original order/product or affected requirements')
        return quantity

    def complete(choice,**fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':choice,**fields,'note':profile.note+
            ' Proposal/task request only. Unaffected duties, original batch and installed consumption remain; repair quality and cost responsibility are separate. Removal, return transport, new supply and replacement installation require distinct authorized core records. Refund uses original transaction through payment services; no negative payment or cash/debt mutation occurs here.'}}

    def wait(code,refs):
        reading.recheck()
        return {'kind':'deferred','reason_code':code,'resume_condition':{'trigger':'dependency_change','object_refs':refs,
            'earliest_time':None,'condition_code':code}}

    try:
        order=read(action_input.order_ref,SupplierRemedyOrderView,linked=True)
        profile=read(action_input.remedy_profile_ref,SupplierRemedyProfileView)
        if (order.supplier_id!=org or not scope_covers(order.scope,scope) or profile.order_ref!=order.ref
                or profile.organization_id!=org or profile.actor_id!=context.actor_id or profile.function_ref!=context.function_ref
                or profile.scope!=scope or profile.authority_ref not in context.authorization_refs):
            raise ValueError('Supply remedy changes original order, supplier, actor or authority')
        if keys(action_input.authority_refs)!=keys(context.authorization_refs):
            _needs('exact_original_current_supply_remedy_authorizations')
        authorize(profile.authority_ref,context.actor_id,context.function_ref,org,'SUPPLIER-A11',now,scope)
        clock(order.as_of)
        if order.as_of!=now or order.coverage!='complete':_needs('complete_current_original_remedy_order_history')
        for supplied,original in [('batch_refs','batch_refs'),('installed_use_refs','material_use_refs'),('change_refs','change_refs'),('defect_refs','defect_refs')]:
            if keys(getattr(action_input,supplied))!=keys(getattr(order,original)):_needs('complete_original_remedy_'+supplied)
        procedure=read(profile.procedure_ref,SupplierRemedyProcedureView,evidence_at_field='authored_at');author(procedure)
        if (procedure.order_ref!=order.ref or procedure.author_organization_id!=order.buyer_id or not true(procedure.permitted)
                or profile.choice not in procedure.permitted_choices or not procedure.recipient_ids):
            _needs('independent_original_contract_remedy_procedure')
        if procedure.response_deadline is not None:
            clock(procedure.response_deadline)
            if now.offset>procedure.response_deadline.offset and not true(procedure.late_response_permitted):
                _needs('applicable_original_late_remedy_response_procedure')
        if keys(profile.affected_line_refs)&keys(profile.unaffected_line_refs) or keys(profile.affected_line_refs)|keys(profile.unaffected_line_refs)!=keys(order.line_refs):
            raise ValueError('Supply remedy must retain complete original affected/unaffected order-line partition')
        lines={ref.key():read(ref,SupplierRemedyOrderLineView,linked=True) for ref in order.line_refs}
        if any(row.order_ref!=order.ref for row in lines.values()):raise ValueError('Remedy line belongs to another order')
        batches={ref.key():read(ref,SupplierQualityBatchView,linked=True) for ref in action_input.batch_refs}
        if len({r.physical_batch_key for r in batches.values()})!=len(batches):raise ValueError('Remedy aliases physical batch under different versions')
        for batch in batches.values():
            clock(batch.as_of)
            if batch.as_of!=now:_needs('current_original_remedy_batch_state',[batch.ref])
        uses={};use_keys=set();removal_events=set()
        for ref in action_input.installed_use_refs:
            row=read(ref,SupplierInstalledUseView,historic=True,linked=True)
            if (row.order_ref!=order.ref or row.batch_ref.key() not in batches or row.physical_use_key in use_keys
                    or row.physical_batch_key!=batches[row.batch_ref.key()].physical_batch_key):
                raise ValueError('Installed use substitutes original order/batch or repeats physical consumption')
            use_keys.add(row.physical_use_key);q(row.quantity,positive=True,historic=True);keys(row.removal_record_refs);removed=Fraction(0)
            for removal_ref in row.removal_record_refs:
                original=read(removal_ref,SupplierRemovalRecordView,historic=True,linked=True)
                if original.material_use_ref!=row.ref or original.physical_use_key!=row.physical_use_key or original.core_event_id in removal_events:
                    raise ValueError('Material removal repeats or replaces original installed physical consumption')
                removal_events.add(original.core_event_id);removed+=q(original.quantity,row.quantity.unit,positive=True,historic=True)
            if removed>q(row.quantity,historic=True):raise ValueError('Recorded removals exceed original installed quantity')
            uses[ref.key()]=(row,q(row.quantity,historic=True)-removed)
        defects={};observations={}
        for ref in action_input.defect_refs:
            defect=read(ref,SupplierVisibleDefectView,linked=True)
            observed=read(defect.observation_ref,SupplierQualityEvidenceView,historic=True,linked=True,evidence_at_field='authored_at');author(observed);clock(observed.observed_at)
            if (defect.batch_ref.key() not in batches or defect.physical_batch_key!=batches[defect.batch_ref.key()].physical_batch_key
                    or observed.batch_ref!=defect.batch_ref or observed.physical_batch_key!=defect.physical_batch_key
                    or observed.kind not in {'actual_observation','actual_test'} or defect.ref.key() not in keys(observed.defect_refs)
                    or observed.observed_at.offset>observed.authored_at.offset or not scope_covers(observed.scope,defect.scope)):
                raise ValueError('Supply remedy defect lacks original actually observed physical batch')
            q(observed.sample_quantity,positive=True,at=observed.observed_at)
            if any(reading.resolve(ref).basis_kind!='observed' for ref in observed.evidence_refs):
                _needs('actual_observed_supply_remedy_defect_basis',[observed.ref])
            if observed.event_id in observations and observations[observed.event_id]!=observed.ref:
                raise ValueError('Remedy aliases original physical observation event')
            observations[observed.event_id]=observed.ref;defects[ref.key()]=defect
        changes={}
        for ref in action_input.change_refs:
            row=read(ref,SupplierSupplyChangeRequestView,historic=True,linked=True);author(row)
            if (row.order_ref!=order.ref or not keys(row.affected_line_refs)<=set(lines) or not keys(row.defect_refs)<=set(defects)
                    or row.author_organization_id not in {order.buyer_id,org}):
                raise ValueError('Supply change request substitutes original author/order/lines/known defects')
            changes[ref.key()]=row
        evidence(profile.basis_refs)
        keys(order.request_history_refs);business=set()
        for ref in order.request_history_refs:
            previous=read(ref,SupplierRemedyRequestView,historic=True,linked=True);author(previous)
            if previous.order_ref!=order.ref or previous.author_organization_id!=org or previous.business_key in business:
                raise ValueError('Remedy history repeats or substitutes original order/author/business request')
            business.add(previous.business_key)
            if previous.business_key==profile.business_key:
                original=read(previous.profile_ref,SupplierRemedyProfileView,historic=True,linked=True)
                if previous.choice!=profile.choice or original!=profile:
                    raise ValueError('Existing remedy business identity changes original choice/profile content')
                return wait('continue_original_supply_remedy_request',[previous.ref])
        if profile.request_ref is not None:
            if profile.request_ref.key() not in changes:raise ValueError('Remedy response invents original received change request')
            request=changes[profile.request_ref.key()]
            if request.status in {'withdrawn','resolved'}:_needs('original_open_supply_change_request')
        else:request=None
        if profile.choice=='decline_request':
            if request is None or not profile.basis_refs:_needs('original_request_and_specific_decline_basis')
            return complete('decline_request',request_ref=request.ref)
        if profile.choice=='propose_change':
            if profile.change_proposal_ref is None or not profile.affected_line_refs:_needs('original_concrete_supply_change_proposal')
            proposal=read(profile.change_proposal_ref,SupplierSupplyChangeProposalView,evidence_at_field='authored_at');author(proposal)
            if (proposal.order_ref!=order.ref or proposal.author_organization_id!=org or proposal.author_action_id!='SUPPLIER-A11'
                    or proposal.status not in {'proposal','pending'} or not proposal.description.strip() or not proposal.lines
                    or len(proposal.lines)!=len(proposal.line_order_refs) or keys(proposal.line_order_refs)!=keys(profile.affected_line_refs)):
                raise ValueError('Supply change proposal substitutes original affected order lines or author')
            for line,ref in zip(proposal.lines,proposal.line_order_refs):
                product(line)
                if not scope_covers(lines[ref.key()].scope,line.destination_scope_ref):raise ValueError('Proposed supply line expands original affected scope')
            return complete('propose_change',lines=[r.model_dump(mode='python') for r in proposal.lines],affected_line_refs=profile.affected_line_refs)

        if profile.choice in {'propose_refund','claim'}:
            if not profile.basis_refs or not profile.affected_line_refs:_needs('original_remedy_amount_problem_basis_and_affected_lines')
            if profile.proposed_amount.state not in {'known','unknown'}:_unsupported('supplier-remedy-amount-applicability')
            transactions=[];available=Fraction(0);keys(profile.transaction_refs);txn_events=set();refund_events=set()
            if profile.choice=='propose_refund':
                if not profile.transaction_refs or not keys(profile.transaction_refs)<=keys(order.transaction_refs):
                    _needs('original_actual_received_transactions_for_refund')
                for ref in profile.transaction_refs:
                    txn=read(ref,SupplierOriginalTransactionView,linked=True);clock(txn.as_of)
                    if (txn.order_ref!=order.ref or txn.payer_id!=order.buyer_id or txn.payee_id!=org or not true(txn.actual_received) or txn.core_event_id in txn_events
                            or txn.as_of!=now or not txn.refund_history_complete):
                        _needs('actual_original_transaction_and_complete_current_refund_history',[ref])
                    txn_events.add(txn.core_event_id);remaining=cash(txn.amount,historic=True);keys(txn.refund_execution_refs);refund_business=set()
                    for refund_ref in txn.refund_execution_refs:
                        refund=read(refund_ref,SupplierRefundExecutionView,historic=True,linked=True)
                        if refund.transaction_ref!=txn.ref or refund.business_key in refund_business:
                            raise ValueError('Refund history repeats original transaction business identity')
                        refund_business.add(refund.business_key)
                        if refund.status in {'unknown','pending'}:return wait('query_original_refund_before_new_proposal',[refund.ref])
                        if refund.status=='succeeded':
                            if refund.core_event_id is None or refund.core_event_id in refund_events:raise ValueError('Refund repeats original actual cash event')
                            refund_events.add(refund.core_event_id);remaining-=cash(refund.amount,historic=True)
                        elif refund.core_event_id is not None:raise ValueError('Failed/refused refund invents actual returned cash')
                    if remaining<0:raise ValueError('Refund history exceeds original actual received transaction')
                    available+=remaining;transactions.append(txn.ref)
            else:
                if not keys(profile.transaction_refs)<=keys(order.transaction_refs):
                    raise ValueError('Claim substitutes transactions from another order')
                for ref in profile.transaction_refs:
                    txn=read(ref,SupplierOriginalTransactionView,historic=True,linked=True)
                    if txn.order_ref!=order.ref or txn.payer_id!=order.buyer_id or txn.payee_id!=org or not true(txn.actual_received):
                        raise ValueError('Optional claim transaction must be original actual receipt')
                    transactions.append(txn.ref)
            if isinstance(profile.proposed_amount,Known):
                proposed=cash(profile.proposed_amount.value)
                if proposed<=0:_needs('positive_original_estimated_remedy_amount')
                if profile.assessment_ref is None:_needs('original_supported_remedy_amount_assessment')
                saved=read(profile.assessment_ref,SupplierRemedyAmountView,evidence_at_field='authored_at');grant=author(saved)
                if (saved.order_ref!=order.ref or saved.purpose!=('refund' if profile.choice=='propose_refund' else 'claim')
                        or keys(saved.affected_line_refs)!=keys(profile.affected_line_refs) or keys(saved.transaction_refs)!=keys(transactions)
                        or not keys(saved.defect_refs)<=set(defects) or saved.method_ref!=CLAIM_METHOD
                        or saved.input_sha256!=content_digest(saved.data) or not keys(saved.data.source_refs)<=keys(grant.readable_refs)
                        or saved.data.currency!=order.currency):
                    raise ValueError('Remedy amount substitutes original problem/transactions/source content or read rights')
                if saved.status=='failed':raise ObservationGap({'kind':'technical_error','error':{'kind':'unrecorded',
                    'correlation_id':context.operation_id,'code':'original-supply-remedy-amount-failed'},'retryability':'unknown'})
                if saved.status=='unsupported':_unsupported('original-supply-remedy-amount-support')
                if saved.status!='ok' or saved.report is None:_needs('original_calculable_remedy_amount')
                if (order.ref.key() not in keys(saved.data.source_refs)
                        or not keys(profile.affected_line_refs)<=keys(saved.data.source_refs)
                        or not keys(transactions)<=keys(saved.data.source_refs)
                        or not keys(profile.basis_refs)<=keys(saved.evidence_refs)):
                    raise ValueError('Remedy estimate omits original affected order/lines/transactions or concrete problem basis')
                for ref in saved.data.source_refs:
                    source=reading.resolve(ref)
                    if isinstance(source,EvidenceRecord):evidence([ref],at=saved.authored_at)
                    if hasattr(source,'available_at'):
                        clock(source.available_at)
                        if source.available_at.offset>saved.authored_at.offset:raise ValueError('Remedy estimate precedes original source availability')
                evidence([saved.data.quantity.basis_ref,saved.data.unit_price.basis_ref,saved.data.fixed_amount.basis_ref,
                    *[v.basis_ref for v in saved.data.deduction_amounts]],at=saved.authored_at)
                result=reading.calculate(CLAIM_METHOD,saved.data)
                if result.kind!='ok':
                    if result.kind=='invalid_input':_unsupported('supplier-remedy-amount-method-domain')
                    raw=result.model_dump(mode='python')
                    if result.kind=='needs_information':raw['requested_refs']=[]
                    raise ObservationGap(raw)
                if result.value!=saved.report or proposed!=decimal_fraction(result.value.payable):
                    raise ValueError('Proposed remedy amount differs from original supported estimate')
                if profile.choice=='propose_refund' and proposed>available:raise ValueError('Refund proposal exceeds original unrefunded actual transactions')
            if profile.choice=='propose_refund':
                return complete('propose_refund',original_transaction_refs=transactions,proposed_amount=profile.proposed_amount,basis_refs=profile.basis_refs)
            return complete('claim',order_line_refs=profile.affected_line_refs,proposed_amount=profile.proposed_amount,basis_refs=profile.basis_refs)

        if profile.choice not in {'repair','replace'} or profile.remedy_plan_ref is None or profile.disposition_scope is None:
            _needs('original_authorized_supply_remedy_plan_and_concrete_scope')
        if not scope_covers(scope,profile.disposition_scope) or not profile.source_defect_refs or not keys(profile.source_defect_refs)<=set(defects):
            raise ValueError('Physical remedy changes original scoped known defects')
        rights=[];keys(profile.right_refs)
        for ref in profile.right_refs:
            right=read(ref,SupplierRemedyRightView,evidence_at_field='authored_at');author(right)
            if (right.order_ref!=order.ref or right.organization_id!=org or right.batch_ref.key() not in batches
                    or profile.choice not in right.permitted_choices or not true(right.permitted)):
                _needs('independent_original_physical_remedy_disposition_right')
            batch=batches[right.batch_ref.key()]
            actual_owner=batch.owner_id
            if right.material_use_ref is not None:
                if right.material_use_ref.key() not in uses:raise ValueError('Remedy right omits original installed use')
                use,_=uses[right.material_use_ref.key()]
                if use.batch_ref!=batch.ref:raise ValueError('Remedy right changes installed batch')
                actual_owner=use.owner_id
            if right.owner_id!=actual_owner:raise ValueError('Remedy right substitutes actual physical owner')
            if right.authority_kind=='own_title' and (actual_owner!=org or right.author_organization_id!=org):
                raise ValueError('Supplier cannot assume ownership of customer material')
            if right.authority_kind=='owner_delegation' and right.author_organization_id!=right.owner_id:
                raise ValueError('Remedy delegation lacks actual owner authority')
            if right.authority_kind=='site_disposition':
                if right.material_use_ref is None or right.material_use_ref.key() not in uses:raise ValueError('Site disposition omits original installed use')
                original,_=uses[right.material_use_ref.key()]
                if right.author_organization_id!=original.site_operator_id or right.site_operator_id!=original.site_operator_id:
                    raise ValueError('Installed remedy lacks independent actual site authority')
            rights.append(right)
        plan=read(profile.remedy_plan_ref,SupplierRemedyTaskPlanView,evidence_at_field='authored_at');author(plan)
        if plan.order_ref!=order.ref or plan.author_organization_id!=org or plan.author_action_id!='SUPPLIER-A11' or not plan.tasks:
            raise ValueError('Remedy task plan replaces original order or supplier author')
        tasks={t.local_key:t for t in plan.tasks}
        if len(tasks)!=len(plan.tasks) or any(set(m)!=set(tasks) for m in [plan.task_defect_refs,plan.task_slice_refs,plan.task_step_refs]):
            raise ValueError('Remedy requires unique tasks and complete defect/slice/step bindings')
        slices={};slice_tasks={};steps={};graph={key:set() for key in tasks};covered_defects=set();windows={}
        used_inputs=set();allocation_events=set();stock_totals={}

        def input_mandate(ref,task):
            mandate=read(ref,SupplierWorkAuthorityView)
            if (mandate.organization_id!=org or mandate.order_ref!=order.ref or not true(mandate.permitted)
                    or task.mode not in mandate.permitted_modes or task.method_ref.key() not in keys(mandate.method_refs)
                    or not scope_covers(mandate.scope,task.scope_ref)):
                raise ValueError('Remedy input substitutes original order/work mandate')
            return mandate

        for task in plan.tasks:
            if not scope_covers(profile.disposition_scope,task.scope_ref):raise ValueError('Remedy task leaves original disposition scope')
            target=product(task.target)
            if profile.choice=='repair' and task.mode!='rework':raise ValueError('Repair task cannot replace original batch by manufactured new stock')
            method=read(task.method_ref,SupplierPlanningMethodView)
            if method.mode!=task.mode or method.product_ref!=task.target.product_ref or not true(method.supported):_unsupported('original_supply_remedy_method_support')
            if task.target.quantity.unit!=method.quantity_unit:raise ValueError('Remedy target changes supported method units')
            recipe={i.product_ref.key():i for i in method.material_inputs}
            keys([i.product_ref for i in method.material_inputs]);keys([i.product_ref for i in task.planned_inputs])
            if set(recipe)!=keys([i.product_ref for i in task.planned_inputs]):
                raise ValueError('Remedy task omits original material recipe')
            if task.mode=='purchase':
                if task.planned_inputs or task.resources or method.material_inputs or method.procurement_basis_ref is None or method.purchase_window_ref is None:
                    raise ValueError('Purchased replacement cannot create manufacture inputs or capacity')
                evidence([method.procurement_basis_ref]);window=read(method.purchase_window_ref,TimeWindow);clock(window.start);clock(window.end)
                if window.start.offset<now.offset:raise ValueError('Replacement purchase window precedes request')
            elif not task.resources:
                _needs('original_remedy_task_resource_intentions')
            for planned in task.planned_inputs:
                ingredient=recipe[planned.product_ref.key()];evidence([ingredient.basis_ref])
                required=q(planned.required,ingredient.unit,positive=True)
                if decimal_fraction(ingredient.quantity_per_output)<=0 or required!=decimal_fraction(ingredient.quantity_per_output)*target:
                    raise ValueError('Remedy inputs change original recipe quantity')
                available=Fraction(0)
                for ref in [*planned.available_allocation_refs,*planned.acquisition_requirement_refs]:
                    if (ref.kind,ref.id) in used_inputs:raise ValueError('Remedy reuses original new-input allocation or requirement')
                    used_inputs.add((ref.kind,ref.id))
                    if ref.kind=='InventoryAllocation':
                        row=read(ref,SupplierInventoryAllocationView);input_mandate(row.work_authority_ref,task)
                        inventory=read(row.inventory_ref,QuoteInventoryView,linked=True);clock(inventory.as_of)
                        if (row.organization_id!=org or row.product_ref!=planned.product_ref or row.status!='reserved'
                                or inventory.organization_id!=org or inventory.as_of!=now or inventory.coverage!='complete'
                                or row.core_event_id in allocation_events):
                            _needs('original_current_reserved_remedy_material_stock',[ref])
                        lot=[l for l in inventory.lots if l.batch_ref==row.batch_ref and l.product_ref==row.product_ref and l.status=='usable']
                        if len(lot)!=1:_needs('original_usable_remedy_input_batch',[ref])
                        amount=q(row.quantity,ingredient.unit,positive=True);allocation_events.add(row.core_event_id)
                        stock_totals[row.batch_ref.key()]=stock_totals.get(row.batch_ref.key(),Fraction(0))+amount
                        if stock_totals[row.batch_ref.key()]>min(q(lot[0].actual,ingredient.unit),q(lot[0].committed,ingredient.unit)):
                            raise ValueError('Remedy allocations exceed actual original reserved material')
                        available+=amount
                    else:
                        row=read(ref,SupplierPlanningRequirementView);mandate=input_mandate(row.work_authority_ref,task)
                        if (ref.key() not in keys(mandate.requirement_refs) or not true(row.permitted)
                                or row.purpose!='material' or row.target.product_ref!=planned.product_ref):
                            raise ValueError('Remedy acquisition substitutes original authorized material requirement')
                        available+=q(row.target.quantity,ingredient.unit,positive=True)
                if available<required:_needs('separate_sourced_remedy_material_acquisition')
            bindings=plan.task_defect_refs[task.local_key];keys(bindings)
            if not bindings or not keys(bindings)<=keys(profile.source_defect_refs):raise ValueError('Remedy task omits original specific defect')
            if any(defects[r.key()].status=='closed' for r in bindings):raise ValueError('Remedy task targets an already closed defect')
            covered_defects.update(keys(bindings));total=Fraction(0);keys(plan.task_slice_refs[task.local_key])
            for ref in plan.task_slice_refs[task.local_key]:
                original=read(ref,SupplierRemedyPhysicalSliceView)
                if original.plan_ref!=plan.ref or original.batch_ref.key() not in {defects[r.key()].batch_ref.key() for r in bindings}:
                    raise ValueError('Remedy slice replaces original affected physical defect batch')
                if original.physical_slice_key in slices and slices[original.physical_slice_key].ref!=original.ref:
                    raise ValueError('Remedy aliases original physical slice under different IDs')
                amount=q(original.quantity,task.target.quantity.unit,positive=True);total+=amount
                slices[original.physical_slice_key]=original;slice_tasks.setdefault(original.physical_slice_key,set()).add(task.local_key)
            if total!=target:raise ValueError('Remedy task target differs from exact original physical slice scope')
            keys(plan.task_step_refs[task.local_key])
            for ref in plan.task_step_refs[task.local_key]:
                step=read(ref,SupplierRemedyStepView)
                if (step.plan_ref!=plan.ref or step.task_key!=task.local_key or step.slice_ref.key() not in keys(plan.task_slice_refs[task.local_key])
                        or ref.key() in steps):raise ValueError('Remedy step replaces original task/slice or is repeated')
                keys(step.predecessor_step_refs);keys(step.required_inventory_allocation_refs);keys(step.required_supply_requirement_refs)
                if step.kind=='new_supply' and not step.required_inventory_allocation_refs and not step.required_supply_requirement_refs:
                    _needs('separate_original_actual_or_planned_new_replacement_inputs')
                if step.kind!='new_supply' and (step.required_inventory_allocation_refs or step.required_supply_requirement_refs):
                    raise ValueError('Removal/transport/installation cannot masquerade as new supply inputs')
                if step.kind=='new_supply':
                    for source_ref in [*step.required_inventory_allocation_refs,*step.required_supply_requirement_refs]:
                        schema=SupplierInventoryAllocationView if source_ref.kind=='InventoryAllocation' else SupplierPlanningRequirementView
                        source=read(source_ref,schema);input_mandate(source.work_authority_ref,task)
                        if source_ref not in [r for p in task.planned_inputs for r in [*p.available_allocation_refs,*p.acquisition_requirement_refs]]:
                            if task.mode!='purchase' or not isinstance(source,SupplierPlanningRequirementView) or source.target.product_ref!=task.target.product_ref or not true(source.permitted):
                                raise ValueError('New replacement input is not bound to original task recipe or purchase')
                steps[ref.key()]=step
            bound_inputs={r.key() for s in steps.values() if s.task_key==task.local_key for r in [*s.required_inventory_allocation_refs,*s.required_supply_requirement_refs]}
            if task.mode=='purchase':
                purchased=Fraction(0)
                for ref in {r.key():r for s in steps.values() if s.task_key==task.local_key for r in s.required_supply_requirement_refs}.values():
                    row=read(ref,SupplierPlanningRequirementView);mandate=input_mandate(row.work_authority_ref,task)
                    if (ref.key() not in keys(mandate.requirement_refs) or row.order_line_ref is None
                            or row.order_line_ref.key() not in keys(profile.affected_line_refs) or row.purpose!='order_output'):
                        raise ValueError('Replacement purchase lacks original authorized affected order output')
                    if (ref.kind,ref.id) in used_inputs:raise ValueError('Replacement purchase repeats original input requirement')
                    used_inputs.add((ref.kind,ref.id));purchased+=q(row.target.quantity,task.target.quantity.unit,positive=True)
                if purchased<target:_needs('separate_original_replacement_purchase_quantity')
            if profile.choice=='replace' and not {r.key() for p in task.planned_inputs for r in [*p.available_allocation_refs,*p.acquisition_requirement_refs]}<=bound_inputs:
                raise ValueError('Replacement step omits original separately planned new inputs')
            windows[task.local_key]=[window] if task.mode=='purchase' else [];keys([a.resource_ref for a in task.resources]);keys(task.dependency_refs)
            for allocation in task.resources:
                resource=read(allocation.resource_ref,SupplierPlanningResourceView,linked=True)
                if resource.organization_id!=org or allocation.scope_ref!=task.scope_ref or allocation.quantity.unit!=method.capacity_unit or resource.resource_kind!=method.resource_kind:
                    raise ValueError('Remedy resource intention substitutes original own resource/method/scope')
                q(allocation.quantity,positive=True);window=read(allocation.window_ref,TimeWindow);clock(window.start);clock(window.end)
                if window.start.offset<now.offset:raise ValueError('New remedy task window precedes request')
                windows[task.local_key].append(window)
        if covered_defects!=keys(profile.source_defect_refs):raise ValueError('Remedy tasks omit original selected defects')
        for task in plan.tasks:
            for ref in task.dependency_refs:
                dependency=read(ref,SupplierRemedyDependencyView)
                if dependency.plan_ref!=plan.ref or dependency.dependent_task_key!=task.local_key:raise ValueError('Remedy dependency substitutes original plan/task')
                for predecessor in dependency.predecessor_task_keys:
                    if predecessor not in tasks or predecessor==task.local_key:raise ValueError('Remedy predecessor is missing or self-referential')
                    graph[task.local_key].add(predecessor)
                    if windows[predecessor] and windows[task.local_key] and max(w.end.offset for w in windows[predecessor])>min(w.start.offset for w in windows[task.local_key]):
                        _needs('original_remedy_predecessor_window_completion')
        def acyclic(edges):
            active=set();visited=set()
            def visit(key):
                if key in active:raise ValueError('Physical remedy dependency cycle')
                if key not in visited:
                    active.add(key)
                    for predecessor in edges[key]:
                        if predecessor not in edges:raise ValueError('Physical remedy omits original predecessor record')
                        visit(predecessor)
                    active.remove(key);visited.add(key)
            for key in edges:visit(key)
        acyclic(graph);step_graph={key:keys(s.predecessor_step_refs) for key,s in steps.items()};acyclic(step_graph)
        def before(first,last,edges):return first in edges[last] or any(before(first,p,edges) for p in edges[last])
        totals={};use_totals={};right_totals={};rights_by_key={r.ref.key():r for r in rights}
        for physical,original in slices.items():
            batch=batches[original.batch_ref.key()];amount=q(original.quantity,batch.actual_quantity.unit,positive=True)
            applicable=[r for r in rights if r.batch_ref==batch.ref and scope_covers(r.scope,original.scope)]
            owner=rights_by_key.get(original.owner_right_ref.key())
            if owner not in applicable or owner.authority_kind not in {'own_title','owner_delegation'} or owner.material_use_ref!=original.material_use_ref:
                _needs('explicit_actual_owner_right_for_original_remedy_slice',[original.ref])
            right_totals[owner.ref.key()]=right_totals.get(owner.ref.key(),Fraction(0))+amount
            if right_totals[owner.ref.key()]>q(owner.maximum_quantity,batch.actual_quantity.unit,at=owner.authored_at):
                raise ValueError('Remedy slices exceed original owner-authorized quantity')
            slice_steps={k:s for k,s in steps.items() if s.slice_ref==original.ref};kinds={s.kind for s in slice_steps.values()}
            if profile.choice=='repair' and 'repair' not in kinds:raise ValueError('Repair slice omits concrete repair step')
            if profile.choice=='replace' and 'new_supply' not in kinds:raise ValueError('Replacement slice omits separate new supply input step')
            if original.material_use_ref is not None:
                if original.material_use_ref.key() not in uses:raise ValueError('Installed remedy invents original material use')
                use,remaining=uses[original.material_use_ref.key()]
                if use.batch_ref!=batch.ref or not scope_covers(profile.disposition_scope,use.scope):raise ValueError('Installed remedy replaces actual site scope')
                site=rights_by_key.get(original.site_right_ref.key()) if original.site_right_ref is not None else None
                if site not in applicable or site.authority_kind!='site_disposition' or site.material_use_ref!=use.ref:
                    _needs('independent_actual_site_disposition_authority',[use.ref])
                right_totals[site.ref.key()]=right_totals.get(site.ref.key(),Fraction(0))+amount
                if right_totals[site.ref.key()]>q(site.maximum_quantity,use.quantity.unit,at=site.authored_at):
                    raise ValueError('Remedy slices exceed original site-authorized quantity')
                use_totals[use.ref.key()]=use_totals.get(use.ref.key(),Fraction(0))+amount
                if use_totals[use.ref.key()]>remaining:raise ValueError('Remedy repeats already removed original installed consumption')
                if profile.choice=='replace':
                    if not {'remove','return_transport','new_supply','install_replacement'}<=kinds:
                        _needs('distinct_installed_removal_return_new_supply_and_install_steps')
                    for later,earlier in [('return_transport','remove'),('install_replacement','remove'),('install_replacement','new_supply')]:
                        if any(not any(before(a,b,step_graph) for a,s in slice_steps.items() if s.kind==earlier)
                                for b,s in slice_steps.items() if s.kind==later):
                            raise ValueError('Installed replacement steps bypass original removal/transport/new-input dependencies')
            else:
                if original.site_right_ref is not None:raise ValueError('Uninstalled slice substitutes site disposition')
                totals[batch.ref.key()]=totals.get(batch.ref.key(),Fraction(0))+amount
                if totals[batch.ref.key()]>q(batch.actual_quantity):raise ValueError('Uninstalled remedy exceeds actual remaining physical batch')
            selected=list(slice_tasks[physical])
            for i,first in enumerate(selected):
                for last in selected[i+1:]:
                    if not before(first,last,graph) and not before(last,first,graph):raise ValueError('Parallel remedy tasks repeat the same physical slice')
        return complete(profile.choice,tasks=[t.model_dump(mode='python') for t in plan.tasks],source_defect_refs=profile.source_defect_refs,
            disposition_scope_ref=profile.disposition_scope)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
