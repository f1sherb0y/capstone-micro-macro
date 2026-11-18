"""OWN-A15 changes future private policy or proposes authorized operating limits."""
from src.actions.contracts.common import EvidenceRecord, Known, TimeWindow
from src.actions.contracts.owner_operating_objects import (
    OwnerOperatingPortfolioView, OwnerOperatingProfileView, OwnerOperatingProjectView,
    OwnerOperatingObservationView, OwnerOperatingPreferenceView, OwnerLearningMethodView,
    OwnerLearningAssessmentView, OwnerResearchBudgetView, OwnerOperatingTaskView,
    OwnerOperatingCommitmentView, OwnerOperatingResourceView, OwnerAllocationRevisionView,
    OwnerOperatingExecutionView, OwnerPaymentObligationView,
)
from src.actions.contracts.service_objects import ServiceScopeOrganizationView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.owner_learning import LEARNING_METHOD
from src.methods.pricing import decimal_fraction
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, CapacityResource, CapacityCommitment, CapacityDemand, ExactAmount
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def decide_owner_operations(context, action_input, reading):
    now, owner, scope=context.business_time,reading.organization_id,context.scope
    monthly_judgment=None

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref!=now.clock_ref: _unsupported('owner-operating-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord): _unsupported('owner-operating-evidence-schema')
            if row.effective_window is not None: clock(row.effective_window.start)

    def read(ref,schema,historic=False,linked=False):
        row=reading.resolve(ref)
        if not isinstance(row,schema): _unsupported('owner-operating-projection:'+ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Owner operations expand original authorized scope')
        evidence(getattr(row,'evidence_refs',[]))
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset: _needs('received_original_owner_operating_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now): _needs('current_original_owner_operating_source',[ref])
        return row

    def true(value): return isinstance(value,Known) and value.value is True

    def authorize(ref,actor,function,organization,action,at,target):
        grant=read(ref,Authorization,historic=True,linked=True);assignment=read(function,RoleAssignment,historic=True,linked=True)
        roles={'OWN':'Owner','BANK':'Bank','CONTRACTOR':'Contractor','SUPPLIER':'Supplier','QS':'QS',
               'ENGINEER':'Engineer','ARCHITECT':'Architect','GOV':'Government'}
        if (grant.actor_id!=actor or grant.function_ref!=function or grant.organization_id!=organization
                or assignment.role!=roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Owner operating source substitutes original author/function/party/action authority')
        clock(at);clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('original_owner_operating_authority_at_execution',[ref])
        evidence(grant.basis_refs+assignment.basis_refs)
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset>row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Owner operating source precedes its original author execution')
        return authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,
            row.author_organization_id,row.author_action_id,row.authored_at,row.scope)

    def wait(ref):
        reading.recheck()
        return {'kind':'deferred','reason_code':'query_original_owner_operating_execution','resume_condition':{
            'trigger':'dependency_change','object_refs':[ref],'earliest_time':None,'condition_code':'query_original_owner_operating_execution'}}

    def calculated(method,data):
        result=reading.calculate(method,data)
        if result.kind!='ok':
            if result.kind=='invalid_input': _unsupported('owner-operating-method-domain')
            raw=result.model_dump(mode='python')
            if result.kind=='needs_information': raw['requested_refs']=[]
            raise ObservationGap(raw)
        return result.value

    def complete(**fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':profile.choice,'basis_refs':profile.basis_refs,**fields,
            'note':monthly_judgment.model_dump_json() if monthly_judgment is not None else profile.note+' Future policy/authorization/schedule proposal only. Whole original due obligations survive even without projects; payment remains OWN-A06. Budget limits do not create cash. Preferences do not rewrite historical decisions, outcomes or returns, and a score update does not prove effective learning. Existing commitments change only through authorized atomic core revision.'}}

    try:
        organization=read(action_input.organization_ref,ServiceScopeOrganizationView,linked=True)
        portfolio=read(action_input.portfolio_ref,OwnerOperatingPortfolioView)
        profile=read(action_input.operating_profile_ref,OwnerOperatingProfileView)
        if (organization.ref.id!=owner or portfolio.organization_id!=owner or profile.organization_id!=owner
                or profile.portfolio_ref!=portfolio.ref or profile.actor_id!=context.actor_id or profile.function_ref!=context.function_ref
                or profile.authority_ref not in context.authorization_refs or profile.scope!=scope or portfolio.scope!=scope):
            raise ValueError('Owner operations change original organization/portfolio/actor/scope/authority')
        authorize(profile.authority_ref,context.actor_id,context.function_ref,owner,'OWN-A15',now,scope)
        clock(portfolio.as_of)
        if portfolio.as_of!=now or portfolio.coverage!='complete': _needs('complete_current_whole_owner_operating_portfolio')
        if keys(action_input.obligation_refs)!=keys(portfolio.obligation_refs) or keys(action_input.observation_refs)!=keys(portfolio.observation_refs):
            _needs('all_original_owner_obligations_and_visible_observations')
        if not keys(profile.basis_refs)<=keys(portfolio.observation_refs): raise ValueError('Operating policy invents private observation basis')
        for ref in portfolio.project_refs:
            project=read(ref,OwnerOperatingProjectView,linked=True)
            if project.organization_id!=owner or not keys(project.obligation_refs)<=keys(portfolio.obligation_refs):
                raise ValueError('Operating project substitutes organization or omits original project debts')
        keys(portfolio.project_refs)
        for ref in portfolio.obligation_refs:
            obligation=read(ref,OwnerPaymentObligationView,linked=True);clock(obligation.as_of);clock(obligation.due_at)
            if obligation.debtor_id!=owner or obligation.as_of!=now:
                _needs('current_original_whole_owner_due_obligations',[ref])
        observations={};events=set()
        for ref in portfolio.observation_refs:
            observation=read(ref,OwnerOperatingObservationView,historic=True,linked=True);author(observation);clock(observation.observed_at)
            if (observation.recipient_organization_id!=owner or observation.event_id in events
                    or observation.observed_at.offset>observation.authored_at.offset):
                raise ValueError('Owner observation is private to another party, future or a duplicate physical event')
            events.add(observation.event_id);observations[ref.key()]=observation
        applied=set();applied_events=set();pending=[];business=set();keys(portfolio.execution_refs)
        for ref in portfolio.execution_refs:
            execution=read(ref,OwnerOperatingExecutionView,historic=True,linked=True)
            if execution.organization_id!=owner or execution.run_id!=context.run_id or execution.business_key in business:
                raise ValueError('Operating execution repeats original organization/run/business identity')
            business.add(execution.business_key)
            if execution.business_key==profile.business_key:
                original=read(execution.profile_ref,OwnerOperatingProfileView,historic=True,linked=True)
                metadata={'ref','portfolio_ref','available_at','effective_window'}
                if (original.organization_id!=execution.organization_id or original.scope!=execution.scope
                        or original.business_key!=execution.business_key or execution.profile_sha256!=content_digest(original)
                        or original.model_dump(exclude=metadata)!=profile.model_dump(exclude=metadata)):
                    raise ValueError('Operating proposal changes original business content')
                return wait(execution.ref)
            if execution.status in {'unknown','pending'}: pending.append(execution)
            if execution.status=='succeeded':
                for applied_ref in execution.applied_observation_refs:
                    prior_observation=read(applied_ref,OwnerOperatingObservationView,historic=True,linked=True)
                    if prior_observation.recipient_organization_id!=owner:
                        raise ValueError('Operating history substitutes another organization outcome')
                    applied.add((applied_ref.kind,applied_ref.id));applied_events.add(prior_observation.event_id)
        if profile.monthly_strategy_policy_ref is not None or profile.monthly_strategy_observation_ref is not None:
            from src.actions.roles.owner_monthly_strategy import select_monthly_strategy
            monthly_judgment=select_monthly_strategy(context,action_input,reading,profile=profile,portfolio=portfolio,
                observations=observations,read=read,author=author)
            profile=profile.model_copy(update={'choice':monthly_judgment.original_choice,
                'preference_profile_ref':monthly_judgment.proposed_preference_ref if monthly_judgment.participate else None})
        if profile.choice=='retain_policy': return complete()
        if profile.choice=='revise_preferences':
            if profile.preference_profile_ref is None: _needs('original_explicit_future_preference_profile')
            prior=read(portfolio.current_preference_ref,OwnerOperatingPreferenceView,linked=True);author(prior)
            proposed=read(profile.preference_profile_ref,OwnerOperatingPreferenceView,linked=True);author(proposed)
            if (prior.organization_id!=owner or proposed.organization_id!=owner or proposed.author_organization_id!=owner
                    or proposed.prior_profile_ref!=prior.ref or proposed.purpose!=prior.purpose or not proposed.scores
                    or set(proposed.scores)!=set(prior.scores) or keys(proposed.basis_refs)!=keys(profile.basis_refs)):
                raise ValueError('Preferences substitute original purpose/domain/prior policy or evidence')
            if any(not 0<=decimal_fraction(v)<=1 for v in [*prior.scores.values(),*proposed.scores.values()]):
                raise ValueError('Declared preference scores leave original bounded domain')
            if proposed.requires_learning:
                if action_input.learning_method_ref is None: _unsupported('owner-preference-learning-method-not-selected')
                if proposed.learning_assessment_ref is None or not proposed.basis_refs: _needs('original_saved_learning_evidence_assessment')
                method=read(action_input.learning_method_ref,OwnerLearningMethodView,linked=True);author(method)
                if method.organization_id!=owner or method.calculation_method_ref!=LEARNING_METHOD or not true(method.supported):
                    _unsupported('owner-selected-learning-method-domain')
                selected=[observations[r.key()] for r in proposed.basis_refs]
                for observation in selected:
                    if observation.kind!='verified_outcome' or not true(observation.verified) or observation.outcome_code not in method.outcome_scores or not observation.dimension_codes:
                        _needs('original_verified_outcomes_for_learning',[observation.ref])
                    if (observation.ref.kind,observation.ref.id) in applied or observation.event_id in applied_events:
                        _needs('new_original_outcome_or_explicit_reevaluation_method',[observation.ref])
                if pending: return wait(pending[0].ref)
                expected=[]
                for observation in sorted(selected,key=lambda r:(r.observed_at.offset,r.event_id)):
                    if len(set(observation.dimension_codes))!=len(observation.dimension_codes): raise ValueError('Learning repeats original outcome dimension')
                    for dimension in sorted(observation.dimension_codes):
                        if dimension not in prior.scores or dimension not in method.learning_rates: _unsupported('original-owner-learning-dimension')
                        expected.append({'observation_ref':observation.ref.model_dump(mode='python'),'dimension_code':dimension,
                            'outcome_score':method.outcome_scores[observation.outcome_code],'learning_rate':method.learning_rates[dimension]})
                saved=read(proposed.learning_assessment_ref,OwnerLearningAssessmentView,linked=True);grant=author(saved)
                if (saved.organization_id!=owner or saved.prior_profile_ref!=prior.ref or saved.preference_profile_ref!=proposed.ref
                        or saved.learning_method_ref!=method.ref or saved.data.previous_scores!=prior.scores
                        or [s.model_dump(mode='python') for s in saved.data.samples]!=expected or saved.input_sha256!=content_digest(saved.data)
                        or not {prior.ref.key(),method.ref.key(),*keys(proposed.basis_refs)}<=keys(saved.data.source_refs)
                        or not keys(saved.data.source_refs)<=keys(grant.readable_refs)):
                    raise ValueError('Learning assessment substitutes original evidence/order/rules/input/read rights')
                if saved.status=='failed': raise ObservationGap({'kind':'technical_error','error':{'kind':'unrecorded','correlation_id':context.operation_id,'code':'original-owner-learning-failed'},'retryability':'unknown'})
                if saved.status=='unsupported': _unsupported('original-owner-learning-method-support')
                if saved.status!='ok' or saved.report is None: _needs('original_calculable_learning_report')
                for ref in saved.data.source_refs:
                    source=reading.resolve(ref)
                    if hasattr(source,'available_at'):
                        clock(source.available_at)
                        if source.available_at.offset>saved.authored_at.offset: raise ValueError('Learning report precedes original received evidence')
                report=calculated(LEARNING_METHOD,saved.data)
                if report!=saved.report or report.updated_scores!=proposed.scores: raise ValueError('Preference update differs from original exact declared evidence method')
            return complete(preference_profile_ref=proposed.ref)
        if profile.choice=='revise_research_budget':
            if profile.proposed_limit is None or profile.budget_authority_ref is None: _needs('original_research_limit_and_budget_authority')
            budget=read(profile.budget_authority_ref,OwnerResearchBudgetView,linked=True);author(budget);clock(budget.as_of)
            if budget.organization_id!=owner or budget.author_organization_id!=owner or budget.as_of!=now or budget.coverage!='complete' or not true(budget.permitted):
                _needs('current_original_authorized_research_budget_boundary')
            values=[profile.proposed_limit,budget.maximum_limit,budget.actual_spent,budget.reserved]
            for value in values:
                evidence([value.basis_ref])
                if value.currency!=budget.currency or decimal_fraction(value.value)<0: raise ValueError('Research limit changes currency or creates negative budget')
            limit=decimal_fraction(profile.proposed_limit.value)
            if limit>decimal_fraction(budget.maximum_limit.value) or limit<decimal_fraction(budget.actual_spent.value)+decimal_fraction(budget.reserved.value):
                raise ValueError('Research cap exceeds authority or erases already spent/reserved research')
            return complete(proposed_limit=profile.proposed_limit)

        if profile.choice!='rebalance_tasks' or not profile.allocations or len(profile.allocations)!=len(profile.allocation_task_refs):
            _needs('original_explicit_task_allocation_mapping')
        if pending: return wait(pending[0].ref)
        portfolio_tasks=keys(portfolio.task_refs)
        required_tasks=keys(portfolio.required_task_refs)
        allocated_tasks=keys(profile.allocation_task_refs)
        if (not required_tasks<=portfolio_tasks or not allocated_tasks<=portfolio_tasks
                or not required_tasks<=allocated_tasks):
            raise ValueError('Rebalance invents tasks or drops mandatory continuing/debt tasks')
        tasks={ref.key():read(ref,OwnerOperatingTaskView,linked=True) for ref in profile.allocation_task_refs}
        pools={};commitments={};physical=set();physical_loads=set()
        for ref in portfolio.resource_refs:
            pool=read(ref,OwnerOperatingResourceView,linked=True);clock(pool.as_of)
            if pool.organization_id!=owner or pool.physical_pool_key in physical: raise ValueError('Rebalance aliases original shared management pool')
            if pool.as_of!=now or pool.coverage!='complete' or not true(pool.permitted) or not isinstance(pool.total,Known): _needs('current_complete_actual_owner_resource_pool',[ref])
            physical.add(pool.physical_pool_key);pools[ref.key()]=pool;keys(pool.commitment_refs)
            for commitment_ref in pool.commitment_refs:
                commitment=read(commitment_ref,OwnerOperatingCommitmentView,linked=True);clock(commitment.as_of);clock(commitment.window.start)
                if (commitment.organization_id!=owner or commitment.resource_ref!=pool.ref or commitment.as_of!=now
                        or commitment.physical_commitment_key in physical_loads): raise ValueError('Rebalance repeats or substitutes original actual shared load')
                if commitment.status=='unknown' or not isinstance(commitment.capacity_quantity,Known): _needs('known_original_owner_resource_commitment',[commitment.ref])
                physical_loads.add(commitment.physical_commitment_key);commitments[commitment.ref.key()]=commitment
        keys(portfolio.resource_refs);replaced=keys(profile.replaced_commitment_refs)
        if not replaced<=set(commitments): raise ValueError('Rebalance replaces unknown original commitment')
        if replaced:
            if profile.allocation_revision_ref is None: _needs('original_atomic_allocation_revision_permission')
            revision=read(profile.allocation_revision_ref,OwnerAllocationRevisionView,linked=True);author(revision)
            if (revision.organization_id!=owner or revision.author_organization_id!=owner or revision.portfolio_ref!=portfolio.ref
                    or not true(revision.permitted) or keys(revision.commitment_refs)!=replaced
                    or not keys(revision.task_refs)<=set(tasks) or any(commitments[k].task_ref.key() not in keys(revision.task_refs) for k in replaced)):
                raise ValueError('Rebalance replaces existing capacity without original atomic task revision authority')
        demands=[];pairs=set()
        for allocation,task_ref in zip(profile.allocations,profile.allocation_task_refs):
            task=tasks[task_ref.key()];author(task)
            if task.organization_id!=owner or not true(task.permitted) or task.status in {'completed','cancelled'} or not keys(task.obligation_refs)<=keys(portfolio.obligation_refs):
                _needs('original_authorized_owner_task_for_rebalance',[task.ref])
            if allocation.task_target.kind=='existing':
                if allocation.task_target.task_ref!=task.ref: raise ValueError('Rebalance changes original existing task')
            elif allocation.task_target.local_key!=task.local_key or allocation.task_target.scope_ref!=task.scope or task.status!='proposed':
                raise ValueError('Rebalance fabricates a new task instead of original authorized draft')
            if allocation.resource_ref.key() not in pools or allocation.resource_ref.key() not in keys(task.resource_refs): raise ValueError('Rebalance substitutes authorized original task resource')
            pool=pools[allocation.resource_ref.key()];window=read(allocation.window_ref,TimeWindow);clock(window.start);clock(window.end)
            identity=(task.ref.key(),pool.ref.key(),allocation.window_ref.key())
            if identity in pairs: raise ValueError('Rebalance repeats original task/resource/window allocation')
            pairs.add(identity);evidence([allocation.quantity.basis_ref])
            if window.start.offset<now.offset or allocation.quantity.unit!=pool.total.value.unit or decimal_fraction(allocation.quantity.value)<=0:
                raise ValueError('Rebalance creates historical work or changes resource units/quantity')
            demands.append(CapacityDemand(resource_kind=pool.ref.id,region_id=pool.region_id,unit=allocation.quantity.unit,
                amount=ExactAmount.from_fraction(decimal_fraction(allocation.quantity.value)),window=window,basis_refs=[allocation.quantity.basis_ref]))
        data=CapacityInput(clock_ref=now.clock_ref,demands=demands,
            resources=[CapacityResource(resource_ref=p.ref,resource_kind=p.ref.id,region_id=p.region_id,total=p.total.value,effective_window=p.effective_window) for p in pools.values()],
            commitments=[CapacityCommitment(commitment_ref=c.ref,resource_ref=c.resource_ref,quantity=c.capacity_quantity.value,window=c.window) for key,c in commitments.items() if c.status=='held' and key not in replaced],
            source_refs=[portfolio.ref,profile.ref,*portfolio.resource_refs,*[c.ref for c in commitments.values()]])
        report=calculated(CAPACITY_METHOD,data)
        if not report.feasible: _needs('shared_owner_management_capacity_for_original_rebalance')
        return complete(allocations=[a.model_dump(mode='python') for a in profile.allocations])
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
