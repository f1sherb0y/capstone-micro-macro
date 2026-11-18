"""Shared service transitions preserve original output, authorship and obligations."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.architect_transition_objects import architect_transition_types
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.pricing import decimal_fraction
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, CapacityResource, CapacityDemand, ExactAmount
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def transition_service(context, action_input, reading, *, action_id='ARCHITECT-A11',
        document_input='usable_deliverable_refs', transition_types=None, resource_check=None,
        recall_demands=None, acceptance_check=None, obligation_check=None, recall_task_check=None):
    types=transition_types or architect_transition_types()
    now,org,scope=context.business_time,reading.organization_id,context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref!=now.clock_ref: _unsupported('architect-transition-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord): _unsupported('architect-transition-evidence-schema')
            if row.effective_window is not None: clock(row.effective_window.start)

    def read(ref,schema,historic=False,linked=False):
        row=reading.resolve(ref)
        if not isinstance(row,schema): _unsupported('architect-transition-projection:'+ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Service transition widens original authorized scope')
        evidence(getattr(row,'evidence_refs',[]))
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset: _needs('received_original_service_transition_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now): _needs('current_original_service_transition_source',[ref])
        return row

    def true(value): return isinstance(value,Known) and value.value is True

    def authorize(ref,actor,function,organization,action,at,target):
        grant=read(ref,Authorization,historic=True,linked=True);assignment=read(function,RoleAssignment,historic=True,linked=True)
        roles={'ARCHITECT':'Architect','ENGINEER':'Engineer','QS':'QS','OWN':'Owner','GOV':'Government',
               'CONTRACTOR':'Contractor','SUPPLIER':'Supplier','BANK':'Bank'}
        if (grant.actor_id!=actor or grant.function_ref!=function or grant.organization_id!=organization
                or assignment.function_ref!=function
                or assignment.role!=roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Transition substitutes original author/function/party/action/scope authority')
        clock(at);clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('original_service_transition_authority_at_execution',[ref])
        evidence(grant.basis_refs+assignment.basis_refs)

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset>row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Transition source precedes actual original author execution')
        authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,row.author_organization_id,
            row.author_action_id,row.authored_at,row.scope)

    def wait(refs,code='service_transition_dependency',earliest=None):
        if earliest is not None: clock(earliest)
        reading.recheck()
        return {'kind':'deferred','reason_code':code,'resume_condition':{'trigger':'dependency_change',
            'object_refs':refs,'earliest_time':earliest,'condition_code':code}}

    def complete(**fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':basis.choice,'scope':scope,**fields,'note':basis.note+
            ' Transition proposal only. Original authorship, licensed use, fee debt and continuing support remain. Handover conveys authorized documents, never predecessor private memory. Resource release/new reservation needs actual core transition; recall does not guarantee immediate availability.'}}

    try:
        if action_input.scope!=scope: raise ValueError('Transition changes invocation scope')
        engagement=read(action_input.engagement_ref,types['Engagement'],linked=True)
        basis=read(action_input.transition_basis_ref,types['ServiceTransitionBasis']);author(basis)
        if (engagement.organization_id!=org or basis.engagement_ref!=engagement.ref or basis.scope!=scope
                or basis.actor_id!=context.actor_id or basis.function_ref!=context.function_ref
                or basis.authority_ref not in context.authorization_refs or not scope_covers(engagement.scope,scope)):
            raise ValueError('Transition changes original service/actor/scope/organization')
        authorize(basis.authority_ref,context.actor_id,context.function_ref,org,action_id,now,scope)
        if basis.author_organization_id not in {org,engagement.client_id} or not true(basis.permitted):
            _needs('original_valid_service_pause_recall_exit_or_handover_basis')
        clock(engagement.as_of)
        if engagement.as_of!=now or engagement.coverage!='complete': _needs('complete_current_original_service_transition_history')
        for field in ('task_refs','allocation_refs','usable_deliverable_refs','residual_obligation_refs'):
            if keys(getattr(action_input,document_input if field=='usable_deliverable_refs' else field))!=keys(getattr(engagement,field)): _needs('all_original_service_transition_'+field)
        tasks={};allocations={};physical=set()
        for ref in engagement.task_refs:
            task=read(ref,types['Task'],linked=True);author(task)
            if task.engagement_ref!=engagement.ref or task.organization_id!=org or task.author_organization_id!=org:
                raise ValueError('Transition task belongs to another service or author organization')
            tasks[ref.key()]=task
        for ref in engagement.allocation_refs:
            allocation=read(ref,types['ResourceAllocation'],linked=True);clock(allocation.as_of)
            if (allocation.engagement_ref!=engagement.ref or allocation.organization_id!=org or allocation.as_of!=now
                    or allocation.physical_allocation_key in physical or allocation.task_ref.key() not in tasks):
                raise ValueError('Transition repeats or substitutes actual original resource allocation')
            physical.add(allocation.physical_allocation_key);allocations[ref.key()]=allocation
        for task in tasks.values():
            if task.allocation_ref is not None and (task.allocation_ref.key() not in allocations or allocations[task.allocation_ref.key()].task_ref!=task.ref):
                raise ValueError('Transition omits original task allocation')
        for ref in engagement.residual_obligation_refs:
            obligation=read(ref,types['Obligation'],linked=True);clock(obligation.as_of)
            if obligation_check is not None:
                obligation_check(obligation,engagement,read)
            elif org not in {obligation.debtor_id,obligation.payee_id} or obligation.as_of!=now:
                _needs('original_current_remaining_service_fee_and_other_obligations',[ref])
        deliverables={}
        for ref in engagement.usable_deliverable_refs:
            document=read(ref,types['Deliverable'],historic=True,linked=True);author(document)
            if document.engagement_ref!=engagement.ref or document.historical_author_id!=document.author_actor_id or document.status!='available':
                raise ValueError('Transition substitutes original available authored document')
            keys(document.existing_use_right_refs)
            for right_ref in document.existing_use_right_refs:
                right=read(right_ref,types['DeliverableUseRight'],historic=True,linked=True);author(right)
                if right.deliverable_ref!=document.ref: raise ValueError('Transition substitutes existing document use right')
            deliverables[ref.key()]=document
        business=set();keys(engagement.execution_refs)
        for ref in engagement.execution_refs:
            execution=read(ref,types['ServiceTransitionExecution'],historic=True,linked=True)
            if execution.organization_id!=org or execution.run_id!=context.run_id or execution.engagement_ref.id!=engagement.ref.id or execution.business_key in business:
                raise ValueError('Transition history repeats original run/service/business identity')
            business.add(execution.business_key)
            if execution.business_key==basis.business_key:
                original=read(execution.basis_ref,types['ServiceTransitionBasis'],historic=True,linked=True)
                metadata={'ref','engagement_ref','available_at','effective_window'}
                if (original.engagement_ref!=execution.engagement_ref or original.scope!=execution.scope
                        or original.business_key!=execution.business_key or execution.basis_sha256!=content_digest(original)
                        or original.model_dump(exclude=metadata)!=basis.model_dump(exclude=metadata)):
                    raise ValueError('Transition changes original content under old business identity')
                return wait([execution.ref],'query_original_service_transition')
            if execution.status in {'unknown','pending'} and basis.choice!='pause': return wait([execution.ref],'query_original_service_transition')
        if basis.choice=='pause':
            if not basis.selected_task_refs or not keys(basis.selected_task_refs)<=set(tasks): _needs('specific_original_pause_tasks')
            for ref in basis.selected_task_refs:
                task=tasks[ref.key()]
                if not scope_covers(scope,task.scope) or not true(task.permitted) or task.status in {'complete','cancelled'}:
                    _needs('original_authorized_active_task_pause',[ref])
            return complete(task_refs=basis.selected_task_refs,basis_ref=basis.ref)
        if basis.choice=='recall':
            if basis.recall_plan is None or not basis.recall_plan.items:
                return wait([basis.ref],'recall_requires_new_available_window',basis.defer_until)
            plan=basis.recall_plan;work=read(plan.work_profile_ref,types['WorkProfile'],linked=True);clock(work.as_of)
            author(work)
            if work.author_organization_id!=org: raise ValueError('Recall work method must retain original firm author')
            if work.engagement_ref!=engagement.ref or work.organization_id!=org or work.as_of!=now or work.coverage!='complete':
                _needs('current_complete_cross_engagement_recall_capacity')
            resources={r.ref.id:r for r in work.resources};people=set()
            if len(resources)!=len(work.resources): raise ValueError('Recall aliases original resource pool')
            commitments={c.commitment_ref.key():c for c in work.commitments}
            keys([c.commitment_ref for c in work.commitments])
            if set(work.commitment_allocation_refs)!={c.commitment_ref.id for c in work.commitments}:
                raise ValueError('Recall calendar omits original commitment allocation identity')
            for resource in work.resources:
                clock(resource.available_at);clock(resource.effective_window.start);clock(resource.effective_window.end)
                if resource.available_at.offset>now.offset or not resource.effective_window.contains(now):
                    _needs('current_received_original_recall_resource',[resource.ref])
                evidence(resource.evidence_refs+[resource.total.basis_ref]+
                    ([resource.effort_per_capacity_tick.basis_ref] if resource.effort_per_capacity_tick is not None else []))
                if resource_check is not None:
                    resource_check(resource,read,evidence)
                else:
                    if resource.organization_id!=org or not resource.personnel_ids or people.intersection(resource.personnel_ids) or len(set(resource.personnel_ids))!=len(resource.personnel_ids):
                        raise ValueError('Recall duplicates actual personnel or uses another firm resource')
                    people.update(resource.personnel_ids)
                if not true(resource.qualified): _needs('original_qualified_recall_personnel')
            selected=keys([i.task_ref for i in plan.items])
            if selected!=keys(basis.selected_task_refs) or not selected<=set(tasks): raise ValueError('Recall plan changes original authorized task selection')
            demands=[];excluded=set();replacement_refs=[];items={i.task_ref.key():i for i in plan.items}
            predecessors={key:set() for key in selected}
            for item in plan.items:
                task=tasks[item.task_ref.key()]
                if (not scope_covers(scope,task.scope) or task.work_profile_ref!=work.ref
                        or task.status not in {'paused','waiting','active'} or not true(task.permitted)):
                    _needs('original_authorized_recall_task',[task.ref])
                if not isinstance(task.remaining_effort,Known) or not isinstance(task.method_remaining_effort,Known): _needs('original_method_remaining_recall_work',[task.ref])
                expected=task.method_remaining_effort.value;remaining=task.remaining_effort.value;evidence([expected.basis_ref,remaining.basis_ref,item.effort.basis_ref])
                if (item.effort.unit!=expected.unit or remaining.unit!=expected.unit or decimal_fraction(item.effort.value)!=decimal_fraction(expected.value)
                        or decimal_fraction(remaining.value)!=decimal_fraction(expected.value) or decimal_fraction(item.effort.value)<=0):
                    raise ValueError('Recall effort differs from original sourced method remaining work')
                if item.existing_allocation_ref!=task.allocation_ref or keys(item.dependency_refs)!=keys(task.dependency_refs):
                    raise ValueError('Recall bypasses original allocation/dependency identity')
                clock(item.window.start);clock(item.window.end)
                if (item.window.start.offset<now.offset or item.window.bounds!='closed_open'
                        or item.window.end.offset<=item.window.start.offset): _unsupported('recall-future-positive-half-open-window')
                if recall_task_check is not None:
                    recall_task_check(task,item,resources,read,author,evidence,clock)
                if recall_demands is not None:
                    demands.extend(recall_demands(task,item,resources,read,author,evidence,clock))
                else:
                    if not item.resource_ids or len(set(item.resource_ids))!=len(item.resource_ids) or set(item.resource_ids)!=set(task.resource_effort_shares):
                        raise ValueError('Recall substitutes original method resource effort shares')
                    shares=[decimal_fraction(v) for v in task.resource_effort_shares.values()]
                    if any(v<=0 for v in shares) or sum(shares,Fraction())!=1: raise ValueError('Recall source effort shares do not partition original work')
                    for resource_id in item.resource_ids:
                        if resource_id not in resources: _needs('original_recall_resource_version')
                        resource=resources[resource_id];rate=decimal_fraction(resource.effort_per_capacity_tick.value)
                        if task.function_code not in resource.function_codes or resource.effort_per_capacity_tick.unit!=item.effort.unit or rate<=0:
                            _unsupported('recall-original-professional-productivity')
                        amount=decimal_fraction(item.effort.value)*decimal_fraction(task.resource_effort_shares[resource_id])/rate/(item.window.end.offset-item.window.start.offset)
                        demands.append(CapacityDemand(resource_kind=resource.ref.id,region_id=resource.region_id,unit=resource.total.unit,
                            amount=ExactAmount.from_fraction(amount),window=item.window,basis_refs=[item.effort.basis_ref,resource.effort_per_capacity_tick.basis_ref]))
                if task.allocation_ref is not None:
                    allocation=allocations[task.allocation_ref.key()]
                    if allocation.status=='unknown': return wait([allocation.ref],'query_original_recall_allocation')
                    if allocation.status=='held':
                        permission=read(allocation.release_permission_ref,types['AllocationReleasePermission'],linked=True);author(permission)
                        if permission.allocation_ref!=allocation.ref or permission.author_organization_id!=org or not true(permission.permitted): _needs('original_atomic_recall_allocation_replacement')
                        original_commitments=keys(allocation.commitment_refs)
                        if excluded.intersection(original_commitments) or not original_commitments:
                            raise ValueError('Recall aliases or omits original held allocation commitments')
                        for key in original_commitments:
                            commitment=commitments.get(key)
                            if (commitment is None or work.commitment_allocation_refs[commitment.commitment_ref.id]!=allocation.ref):
                                raise ValueError('Recall replaces another task allocation commitment')
                        excluded.update(original_commitments)
                        replacement_refs.extend([allocation.ref,permission.ref])
                for ref in item.dependency_refs:
                    dependency=read(ref,types['Dependency'],linked=True)
                    if dependency.task_ref!=task.ref: raise ValueError('Recall dependency changes original task')
                    predecessor_key=dependency.predecessor_task_ref.key() if dependency.predecessor_task_ref is not None else None
                    if predecessor_key==task.ref.key(): raise ValueError('Recall task cannot depend on itself')
                    if predecessor_key in selected: predecessors[task.ref.key()].add(predecessor_key)
                    if not true(dependency.satisfied):
                        predecessor=items.get(dependency.predecessor_task_ref.key()) if dependency.predecessor_task_ref is not None else None
                        if predecessor is None or predecessor.window.end.offset>item.window.start.offset: return wait([ref],'recall_dependency_not_ready')
            remaining=set(selected)
            while remaining:
                ready={key for key in remaining if not predecessors[key].intersection(remaining)}
                if not ready: raise ValueError('Recall task dependencies contain a cycle')
                remaining-=ready
            if not excluded<=keys([c.commitment_ref for c in work.commitments]): raise ValueError('Recall replacement omits original occupied commitments')
            data=CapacityInput(clock_ref=now.clock_ref,demands=demands,
                resources=[CapacityResource(resource_ref=r.ref,resource_kind=r.ref.id,region_id=r.region_id,total=r.total,effective_window=r.effective_window) for r in work.resources],
                commitments=[c for c in work.commitments if c.commitment_ref.key() not in excluded],
                source_refs=[work.ref,basis.ref,*[i.task_ref for i in plan.items],*[r.ref for r in work.resources],*replacement_refs])
            result=reading.calculate(CAPACITY_METHOD,data)
            if result.kind!='ok':
                if result.kind=='invalid_input': _unsupported('recall-capacity-method-domain')
                raw=result.model_dump(mode='python')
                if result.kind=='needs_information': raw['requested_refs']=[]
                raise ObservationGap(raw)
            if not result.value.feasible: return wait([work.ref],'recall_capacity_unavailable',basis.defer_until)
            return complete(plan=plan.model_dump(mode='python'))

        if basis.package is None: _needs('original_authorized_service_handover_package')
        package=basis.package
        if package.engagement_ref!=engagement.ref or package.basis_ref!=basis.ref or not package.recipient_ids or len(set(package.recipient_ids))!=len(package.recipient_ids):
            raise ValueError('Handover substitutes original service/basis/recipients')
        remaining_tasks={k for k,t in tasks.items() if t.status not in {'complete','cancelled'}}
        if keys(package.remaining_task_refs)!=remaining_tasks or keys(package.remaining_obligation_refs)!=keys(engagement.residual_obligation_refs):
            raise ValueError('Service exit/handover omits original ongoing support tasks or fee/debt obligations')
        released=keys(package.release_allocation_refs);retained=keys(package.retain_allocation_refs)
        if released&retained or released|retained!=set(allocations): raise ValueError('Handover must partition original allocations without overlap')
        for key in released:
            allocation=allocations[key]
            if allocation.status=='unknown': return wait([allocation.ref],'query_original_handover_allocation')
            if allocation.status!='held': raise ValueError('Handover cannot release an already released allocation')
            permission=read(allocation.release_permission_ref,types['AllocationReleasePermission'],linked=True);author(permission)
            if permission.allocation_ref!=allocation.ref or permission.author_organization_id!=org or not true(permission.permitted): _needs('original_authorized_transition_resource_release')
        if keys(package.deliverable_refs)!=set(deliverables): raise ValueError('Handover must retain original legally usable documents')
        accesses=set();keys(package.access_basis_refs)
        for ref in package.access_basis_refs:
            access=read(ref,types['AccessBasis'],linked=True);author(access)
            if access.deliverable_ref.key() not in deliverables or access.recipient_id not in package.recipient_ids or not true(access.permitted):
                _needs('original_legal_document_access_for_recipient',[ref])
            if access.author_organization_id!=deliverables[access.deliverable_ref.key()].rights_controller_organization_id:
                raise ValueError('Handover document grant must come from original rights controller')
            identity=(access.deliverable_ref.key(),access.recipient_id)
            if identity in accesses: raise ValueError('Handover repeats original recipient document grant')
            accesses.add(identity)
        if accesses!={(key,recipient) for key in deliverables for recipient in package.recipient_ids}: _needs('all_original_handover_recipient_document_rights')
        accepted=set();keys(basis.recipient_acceptance_refs)
        for ref in basis.recipient_acceptance_refs:
            acceptance=read(ref,types['HandoverAcceptance'],linked=True);author(acceptance)
            if (acceptance.engagement_ref!=engagement.ref or acceptance.package_sha256!=content_digest(package)
                    or acceptance.recipient_id!=acceptance.author_actor_id or acceptance.recipient_id not in package.recipient_ids
                    or acceptance.recipient_id in accepted or not scope_covers(acceptance.independent_review_scope,scope)):
                raise ValueError('Successor handover acceptance substitutes original package/actor/review scope')
            if true(acceptance.accepted):
                if acceptance_check is not None:
                    acceptance_check(acceptance,package,deliverables,read,author,evidence,clock)
                accepted.add(acceptance.recipient_id)
        if accepted!=set(package.recipient_ids): return wait([basis.ref],'handover_waiting_independent_recipient_acceptance')
        return complete(package=package.model_dump(mode='python'))
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
