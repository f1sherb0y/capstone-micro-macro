"""QS-A13 compares submitted scoped costs and respects original research limits."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Money
from src.actions.contracts.qs_research_objects import (
    QSResearchAuthorityView, QSResearchTaskView, QSResearchOptionView, QSResearchBasisView,
    QSResearchAssessmentView, QSResearchCostPlanView, QSResearchProfileView, QSResearchLimitView,
    QSResearchExpenseView, QSResearchCostFactView, QSResearchRequestView, QSResearchGapView,
    QSResearchResponseView, QSResearchNormalizationView, QSResearchMethodProjection,
    QSResearchReferenceView,
)
from src.actions.contracts.qs_cost_objects import QSCostBriefView, QSCostScopeView, QSCostPriceView, QSQuantityBasisView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.methods.qs_cost import COST_METHOD
from src.methods.qs_research import (
    RESEARCH_NORMALIZE_METHOD, RESEARCH_RANK_METHOD, ResearchNormalizationInput, ResearchRankInput,
    normalize_plans, rank_plans,
)
from src.methods.pricing import decimal_fraction, exact_decimal
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def compare_preliminary_costs(context, action_input, reading):
    return _compare_preliminary_costs(context, action_input, reading)


def prepare_qs_research_normalization_input(context, action_input, reading):
    """Prepare exact original cost adjustments without consuming future reports.

    Use a dedicated source reading under the application's current source guard.
    Ordinary comparison continues to require saved results; preparation grants no
    research continuation, professional finding or investment approval.
    """
    return _prepare_qs_research_comparison_input(context, action_input, reading, kind='normalization')


def prepare_qs_research_ranking_input(context, action_input, reading):
    """Prepare declared criteria from comparable costs and saved normalization.

    Preserve unknown risk, professional limits and disjoint scope coverage.
    Do not replay normalization or consume the future ranking report. Actual
    persisted normalization provenance remains an independent producer gate.
    """
    return _prepare_qs_research_comparison_input(context, action_input, reading, kind='ranking')


def _prepare_qs_research_comparison_input(context, action_input, reading, *, kind):
    if kind not in {'normalization','ranking'}:
        raise ValueError('Research comparison preparation supports only fixed normalization or ranking')
    if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A13'
            or action_input.scope != context.scope):
        raise ValueError('Research comparison preparation requires its original QS A13 scope and contract')
    reading.check_method_context(context, 'QS-A13')
    before = reading.method_evidence()
    future_keys = {key for key,row in reading._reads.items()
        if isinstance(row,QSResearchMethodProjection) and row.comparison is not None
        and (kind=='normalization' or row.comparison.kind=='ranking')}

    def check_preparation_reading():
        if reading.method_evidence() != before or future_keys.intersection(reading._reads):
            raise ValueError('Research comparison preparation cannot execute methods or consume future comparison results')

    check_preparation_reading()
    try:
        return _compare_preliminary_costs(context, action_input, reading,
            prepare_normalization=kind=='normalization', prepare_ranking=kind=='ranking', future_keys=future_keys)
    finally:
        check_preparation_reading()
        reading.recheck()
        check_preparation_reading()


def _compare_preliminary_costs(context, action_input, reading, *, prepare_normalization=False,
        prepare_ranking=False, future_keys=None):
    scope,now,sources=action_input.scope,context.business_time,{}

    def clock(point):
        if point.clock_ref!=now.clock_ref:_unsupported('qs-research-clock-conversion')

    def current(window,at=now):
        clock(window.start);clock(at)
        return window.contains(at)

    def evidence(refs):
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord):_unsupported('qs-research-evidence-schema')
            if row.effective_window is not None and not current(row.effective_window):_needs('current_research_evidence',[ref])

    def read(ref,schema,active=True):
        if (prepare_normalization or prepare_ranking) and ref.key() in future_keys:
            raise ValueError('Research comparison preparation cannot read a future comparison result')
        row=reading.resolve(ref)
        if not isinstance(row,schema):_unsupported('qs-research-projection:'+ref.kind)
        if (prepare_normalization or prepare_ranking) and isinstance(row,QSResearchProfileView):
            targets=[target for target in (row.normalization_result_ref,row.ranking_result_ref) if target is not None]
            unique_refs(targets)
            future_keys.update(target.key() for target in targets
                if prepare_normalization or target==row.ranking_result_ref)
            if future_keys.intersection(reading._reads):
                raise ValueError('Research comparison preparation already contains future comparison results')
        evidence(getattr(row,'evidence_refs',[]))
        if hasattr(row,'scope') and row.scope!=scope:raise ValueError('Research source changes original authorized scope')
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset:_needs('received_research_source',[ref])
            if active and not current(row.effective_window):_needs('current_research_source',[ref])
        sources[ref.key()]=ref
        return row

    def authority(ref,actor,function,action,roles,at=now,organization=None):
        grant=read(ref,Authorization);assignment=read(function,RoleAssignment)
        evidence(grant.basis_refs+assignment.basis_refs)
        if (grant.actor_id!=actor or grant.function_ref!=function or assignment.role not in roles
                or (organization is not None and grant.organization_id!=organization)):
            raise ValueError('Research author or legal organization differs from original authority')
        if not current(grant.validity,at) or action not in grant.action_ids or not any(scope_covers(s,scope) for s in grant.scopes):
            _needs('original_research_authority',[ref])

    def author(row,roles={'QS'},organization=None):
        assignment=read(row.author_function_ref,RoleAssignment)
        actions={'QS':{'QS-A04','QS-A13'},'Architect':{'ARCHITECT-A04','ARCHITECT-A05','ARCHITECT-A13'},
            'Engineer':{'ENGINEER-A04','ENGINEER-A05','ENGINEER-A13'},'Supplier':{'SUPPLIER-A02','SUPPLIER-A03','SUPPLIER-A13'}}
        if row.author_action_id not in actions.get(assignment.role,set()):_unsupported('qs-research-author-function')
        authority(row.author_authority_ref,row.author_actor_id,row.author_function_ref,row.author_action_id,roles,
            getattr(row,'calculated_at',row.available_at),organization)

    def completed(choice,**fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':choice,'scope':scope,
            'note':'Limited original-cost research only; professional limits, exclusions and uncertainty retained; no new estimate, work, fee, supplier reservation or investment approval',**fields}}

    def original_method(ref):
        projection=read(ref,QSResearchMethodProjection)
        row=projection.cost or projection.comparison
        evidence(row.evidence_refs)
        if row.scope!=scope:raise ValueError('Original method result changes research scope')
        clock(row.available_at);clock(row.calculated_at)
        if row.available_at.offset>now.offset or row.calculated_at.offset>row.available_at.offset:_needs('received_original_research_calculation',[ref])
        if not current(row.effective_window):_needs('current_original_research_calculation',[ref])
        author(row,organization=reading.organization_id if projection.comparison is not None else None)
        if row.status=='failed':raise ObservationGap({'kind':'technical_error','error':{'kind':'unrecorded',
            'correlation_id':context.operation_id,'code':'original_research_calculation_failed'},'retryability':'unknown'})
        if row.status=='unsupported':_unsupported('qs-research-original-method-domain')
        return projection,row

    try:
        brief=read(action_input.brief_ref,QSCostBriefView)
        task=read(action_input.task_ref,QSResearchTaskView)
        grant=read(action_input.research_authority_ref,QSResearchAuthorityView)
        basis=read(action_input.comparison_basis_ref,QSResearchBasisView)
        limit=read(action_input.expenditure_limit_ref,QSResearchLimitView)
        if (task.brief_ref!=brief.ref or task.organization_id!=reading.organization_id or task.function_ref!=context.function_ref
                or task.comparison_basis_ref!=basis.ref or task.expenditure_limit_ref!=limit.ref
                or grant.brief_ref!=brief.ref or grant.task_ref!=task.ref or grant.delegate_actor_id!=context.actor_id
                or grant.delegate_organization_id!=reading.organization_id or grant.delegate_function_ref!=context.function_ref
                or limit.task_ref!=task.ref or limit.organization_id!=reading.organization_id):
            raise ValueError('Research changes original brief, task, delegation, comparison or spending limit')
        authority(task.authority_ref,context.actor_id,task.function_ref,'QS-A13',{'QS'},organization=reading.organization_id)
        authority(limit.authority_ref,context.actor_id,task.function_ref,'QS-A13',{'QS'},organization=reading.organization_id)
        clock(grant.granted_at)
        if grant.granted_at.offset>grant.available_at.offset:_needs('received_original_research_delegation')
        authority(grant.client_authority_ref,grant.client_actor_id,grant.client_function_ref,grant.client_action_id,{'Owner'},
            grant.granted_at,grant.client_organization_id)
        if grant.permission.state!='known' or not grant.permission.value:_needs('independent_client_research_permission',[grant.ref])
        if 'research' not in grant.allowed_uses or 'research' not in brief.allowed_uses:_needs('authorized_preliminary_research_use')
        if task.status=='waiting':
            reading.recheck()
            return {'kind':'deferred','reason_code':'qs_research_task_waiting','resume_condition':{'trigger':'dependency_change',
                'object_refs':[task.ref],'earliest_time':None,'condition_code':'qs.research.task_ready'}}
        for name in ('option_refs','assessment_refs','cost_plan_refs'):
            unique_refs(getattr(action_input,name))
            if set(getattr(action_input,name))!=set(getattr(task,name)):_needs('exact_original_research_'+name)
        if basis.comparison_profile_ref is None:_needs('explicit_research_comparison_profile')
        profile=read(basis.comparison_profile_ref,QSResearchProfileView)
        if profile.task_ref!=task.ref or profile.comparison_basis_ref!=basis.ref:raise ValueError('Comparison profile changes original task or basis')
        if prepare_normalization or prepare_ranking:
            target=profile.normalization_result_ref if prepare_normalization else profile.ranking_result_ref
            if target is None:_needs('declared_qs_research_normalization_target' if prepare_normalization
                else 'declared_qs_research_ranking_target',[profile.ref])
            unique_refs(profile.selected_plan_refs)
        if limit.as_of!=now:_needs('current_research_limit_snapshot')
        evidence([limit.budget_cap.basis_ref,limit.effort_cap.basis_ref])
        unique_refs(limit.expense_refs)
        used_cash,used_effort,facts=Fraction(),Fraction(),{}
        for ref in limit.expense_refs:
            expense=read(ref,QSResearchExpenseView);fact=read(expense.cost_fact_ref,QSResearchCostFactView)
            if (expense.task_ref!=task.ref or fact.task_ref!=task.ref or fact.organization_id!=reading.organization_id
                    or expense.status!=fact.status or expense.amount!=fact.amount or expense.effort!=fact.effort):
                raise ValueError('Research expense changes original task, cost fact, amount or effort')
            evidence([expense.amount.basis_ref,expense.effort.basis_ref])
            if expense.amount.currency!=limit.budget_cap.currency or expense.effort.unit!=limit.effort_cap.unit:
                _unsupported('qs-research-budget-unit-conversion')
            amount,work=decimal_fraction(expense.amount.value),decimal_fraction(expense.effort.value)
            if amount<0 or work<0:raise ValueError('Research cost cannot be silently credited')
            fact_identity,actual=(fact.ref.kind,fact.ref.id),(amount,work,fact.status)
            if fact_identity in facts:
                if facts[fact_identity]!=actual:_needs('current_single_original_qs_research_cost_fact',[fact.ref])
                continue
            facts[fact_identity]=actual
            used_cash+=amount;used_effort+=work
        if decimal_fraction(limit.budget_cap.value)<0 or decimal_fraction(limit.effort_cap.value)<0:raise ValueError('Research caps cannot be negative')
        cash=decimal_fraction(limit.budget_cap.value)-used_cash;effort=decimal_fraction(limit.effort_cap.value)-used_effort
        at_limit=limit.status!='active' or task.status=='closed' or cash<=0 or effort<=0
        if (prepare_normalization or prepare_ranking) and at_limit:
            _needs('authorized_qs_research_normalization_within_current_limits' if prepare_normalization
                else 'authorized_qs_research_ranking_within_current_limits',[task.ref,limit.ref])
        options=[read(ref,QSResearchOptionView) for ref in action_input.option_refs]
        by_option={r.ref:r for r in options}
        recipients=set(brief.recipient_ids)|{grant.client_actor_id}
        for option in options:
            if option.brief_ref!=brief.ref:raise ValueError('Research option belongs to another demand version')
            author(option,{'Architect','Engineer'});recipients.add(option.author_actor_id)
        questions,seen=[],set()

        def question(issue,option=None):
            found=[]
            for ref in task.question_refs:
                row=read(ref,QSResearchGapView)
                if row.issue!=issue or (option is not None and row.option_ref not in {None,option}):continue
                response=read(row.response_requirement_ref,QSResearchResponseView)
                if (row.brief_ref!=brief.ref or row.task_ref!=task.ref or response.task_ref!=task.ref
                        or not set(row.recipient_ids)<=set(response.recipient_ids) or not set(row.recipient_ids)<=recipients
                        or not set(row.blocking_uses)<=set(grant.allowed_uses)):
                    raise ValueError('Research question changes original brief, task, recipients or uses')
                found.append(row)
                if row.ref.key() not in seen:
                    seen.add(row.ref.key());questions.append({'scope':scope,'target_refs':[row.ref],'question':row.question,
                        'recipient_ids':row.recipient_ids,'evidence_refs':row.evidence_refs,'blocking_uses':row.blocking_uses,
                        'response_requirement_ref':response.ref})
            if not found:_needs('registered_research_'+issue+'_question')

        blocked=set()
        for option in options:
            if 'research' not in option.allowed_uses:question('assessment',option.ref);blocked.add(option.ref)
        for ref in action_input.assessment_refs:
            assessment=read(ref,QSResearchAssessmentView);author(assessment,{'Architect','Engineer','QS','Supplier'})
            if assessment.brief_ref!=brief.ref or assessment.option_ref not in by_option:raise ValueError('Professional input changes research brief or option version')
            if assessment.status=='failed':raise ObservationGap({'kind':'technical_error','error':{'kind':'unrecorded',
                'correlation_id':context.operation_id,'code':'original_research_assessment_failed'},'retryability':'unknown'})
            if assessment.status=='unsupported':_unsupported('qs-research-professional-method-domain')
            if (assessment.finding=='conflict' or (assessment.finding=='uncovered' and set(assessment.covered_scope_keys)&set(profile.required_scope_keys))
                    or 'research' not in assessment.allowed_uses):
                question('assessment',assessment.option_ref);blocked.add(assessment.option_ref)
        plans=[read(ref,QSResearchCostPlanView) for ref in action_input.cost_plan_refs]
        selected=set(profile.selected_plan_refs) if profile.selected_plan_refs else {p.ref for p in plans}
        if not selected<={p.ref for p in plans}:raise ValueError('Comparison selects an undeclared cost plan')
        selected_plans=[p for p in plans if p.ref in selected]
        groups={ref:[p for p in selected_plans if p.draft.option_ref==ref] for ref in by_option}
        costs,plan_costs,plan_coverage,normal_inputs,normal_bases={},{},{},[],[]
        unique_refs(profile.normalization_basis_refs)
        normal_by_plan={}
        for ref in profile.normalization_basis_refs:
            norm=read(ref,QSResearchNormalizationView);author(norm,organization=reading.organization_id)
            if norm.plan_ref in normal_by_plan:raise ValueError('Multiple normalization bases for one original plan')
            normal_by_plan[norm.plan_ref]=norm
        for plan in plans:
            author(plan)
            if plan.brief_ref!=brief.ref or plan.draft.option_ref not in by_option:raise ValueError('Cost plan changes current demand or option version')
            if plan.ref not in selected:continue
            option=by_option[plan.draft.option_ref]
            original_basis=read(plan.draft.comparison_basis_ref,QSResearchBasisView,False)
            if plan.status!='submitted' or plan.draft.complete_total is None or plan.draft.missing_items or plan.draft.calculation_ref is None:
                question('cost_plan',option.ref);blocked.add(option.ref);continue
            projection,calc=original_method(plan.draft.calculation_ref)
            if (projection.cost is None or calc.method_ref!=COST_METHOD or calc.brief_ref!=brief.ref
                    or calc.option_ref!=option.ref or calc.cost_scope_ref!=plan.draft.cost_scope_ref
                    or calc.comparison_basis_ref!=original_basis.ref or calc.quantity_schedule_ref!=plan.draft.quantity_schedule_ref
                    or calc.known_subtotal!=plan.draft.known_subtotal or calc.complete_total!=plan.draft.complete_total
                    or [(r.line_key,r.quantity,r.amount) for r in calc.lines]!=[(r.line_key,r.quantity,r.amount) for r in plan.draft.lines]):
                raise ValueError('Submitted A04 plan differs from original saved calculation or input versions')
            cost_scope=read(plan.draft.cost_scope_ref,QSCostScopeView,False)
            if cost_scope.option_ref!=option.ref or {r.line_key for r in cost_scope.items}!={r.line_key for r in plan.draft.lines}:
                raise ValueError('Cost plan loses original declared scope lines')
            if (set(calc.quantity_basis_refs)!={r.quantity_basis_ref for r in cost_scope.items if r.quantity_basis_ref is not None}
                    or set(calc.price_refs)!={r.price_ref for r in cost_scope.items if r.price_ref is not None}):
                raise ValueError('A04 calculation changes the complete original quantity/price set')
            quantity_rows=[read(ref,QSQuantityBasisView,False) for ref in calc.quantity_basis_refs]
            quantities={r.line_key:r for r in quantity_rows}
            if len(quantities)!=len(quantity_rows):raise ValueError('Original A04 quantity bases repeat a line identity')
            if (calc.available_at.offset>plan.available_at.offset or cost_scope.available_at.offset>calc.calculated_at.offset
                    or original_basis.available_at.offset>calc.calculated_at.offset):
                _needs('saved_A04_calculation_after_original_versions',[calc.ref])
            total,coverage=Fraction(),set()
            scope_items={r.line_key:r for r in cost_scope.items}
            for line in plan.draft.lines:
                quantity=quantities.get(line.line_key);item=scope_items[line.line_key]
                if line.amount.state!='known' or line.quantity.state!='known' or quantity is None or line.price_ref is None:
                    raise ValueError('Complete cost plan has an uncomputed original line')
                price=read(line.price_ref,QSCostPriceView,False)
                if (quantity.available_at.offset>calc.calculated_at.offset or price.available_at.offset>calc.calculated_at.offset
                        or not current(quantity.effective_window,calc.calculated_at) or not current(price.effective_window,calc.calculated_at)
                        or not current(price.valid_pricing_window,original_basis.pricing_time)):
                    raise ValueError('Saved A04 amount uses unavailable or inapplicable original quantity/price')
                if (quantity.ref!=item.quantity_basis_ref or price.ref!=item.price_ref or price.ref not in calc.price_refs
                        or quantity.option_ref!=option.ref or quantity.quantity!=line.quantity or price.unit_rate.state!='known'
                        or quantity.cost_component_ref!=item.cost_component_ref or line.cost_component_ref!=item.cost_component_ref
                        or price.cost_component_ref!=item.cost_component_ref or price.quantity_unit!=line.quantity.value.unit
                        or price.measurement_rule_code!=quantity.measurement_rule_code or line.calculation_ref!=calc.ref
                        or price.region_id!=original_basis.region_id or price.delivery_code!=original_basis.delivery_code
                        or not set(item.coverage_keys)<=set(price.coverage_keys)
                        or set(price.coverage_keys)&set(price.excluded_coverage_keys)
                        or price.unit_rate.value.currency!=line.amount.value.currency or line.amount.value.currency!=original_basis.currency):
                    raise ValueError('A04 computed line loses original applicable quantity or price')
                keys=set(item.coverage_keys)|set(price.coverage_keys)
                if coverage&keys:raise ValueError('A04 cost plan repeats installation, parent/child or regional physical coverage')
                coverage.update(keys)
                evidence([line.quantity.value.basis_ref,line.amount.value.basis_ref,price.unit_rate.value.basis_ref])
                value=decimal_fraction(line.quantity.value.value)*decimal_fraction(price.unit_rate.value.value)
                if value<0 or value!=decimal_fraction(line.amount.value.value):raise ValueError('A04 saved amount disagrees with original exact quantity times rate')
                total+=value
            if (coverage!=set(plan.coverage_keys) or plan.draft.known_subtotal.state!='known'
                    or total!=decimal_fraction(plan.draft.complete_total.value)
                    or plan.draft.complete_total!=plan.draft.known_subtotal.value):
                raise ValueError('A04 scoped total or physical coverage disagrees with original computed lines')
            norm=normal_by_plan.get(plan.ref)
            target_scope=(set(norm.target_scope_keys) if norm is not None and norm.target_scope_keys is not None
                else set(profile.required_scope_keys) if len(groups[option.ref])==1 else set(plan.coverage_keys))
            plan_coverage[plan.ref]=target_scope
            if not target_scope<=set(profile.required_scope_keys):
                question('comparison',option.ref);blocked.add(option.ref);continue
            differences={'scope:'+k for k in set(plan.coverage_keys)^target_scope}
            if original_basis.region_id!=basis.region_id:differences.add('region:'+original_basis.region_id+'->'+basis.region_id)
            if original_basis.pricing_time!=basis.pricing_time:differences.add('price_time:'+str(original_basis.pricing_time.offset)+'->'+str(basis.pricing_time.offset))
            if original_basis.delivery_code!=basis.delivery_code:differences.add('delivery:'+original_basis.delivery_code+'->'+basis.delivery_code)
            dimensions={r.code:r.value for r in plan.comparison_dimensions}
            option_dimensions={r.code:r.value for r in option.comparison_dimensions}
            if (len(dimensions)!=len(plan.comparison_dimensions) or len(option_dimensions)!=len(option.comparison_dimensions)):
                raise ValueError('Original comparison dimension repeated')
            for dimension in profile.required_dimensions:
                value=dimensions.get(dimension.code)
                if dimension.value.state!='known' or value is None or value.state!='known' or option_dimensions.get(dimension.code)!=value:
                    question('comparison',option.ref);blocked.add(option.ref)
                elif value.value!=dimension.value.value:differences.add('dimension:'+dimension.code)
            if option.ref in blocked:continue
            same=not differences and plan.draft.complete_total.currency==basis.currency
            if same and norm is None:plan_costs[plan.ref]=plan.draft.complete_total;continue
            if norm is None or profile.normalization_result_ref is None:
                question('comparison',option.ref);blocked.add(option.ref);continue
            if (norm.comparison_basis_ref!=basis.ref or norm.original_amount!=plan.draft.complete_total
                    or norm.target_currency!=basis.currency or set(norm.difference_keys)!=differences):
                raise ValueError('Cost normalization changes original scoped amount or comparison differences')
            if set(r.difference_key for r in norm.adjustments)!=differences or norm.fx_rate.state!='known':
                question('comparison',option.ref);blocked.add(option.ref);continue
            evidence([norm.fx_basis_ref,*[r.amount.basis_ref for r in norm.adjustments]])
            normal_bases.append(norm.ref);normal_inputs.append({'plan_ref':plan.ref,'original_amount':norm.original_amount,
                'fx_rate':norm.fx_rate.value,'fx_basis_ref':norm.fx_basis_ref,'adjustments':norm.adjustments})
        for option in options:
            if not groups[option.ref]:question('cost_plan',option.ref);blocked.add(option.ref)
        if not options:question('cost_plan')
        if prepare_normalization:
            if not normal_inputs:_needs('original_qs_research_plans_requiring_normalization',profile.normalization_basis_refs)
            reading.recheck()
            return {'kind':'prepared', 'input':ResearchNormalizationInput(currency=basis.currency,
                plans=normal_inputs,source_refs=list(sources.values())),
                'calculation_ref':profile.normalization_result_ref, 'task_ref':task.ref,
                'profile_ref':profile.ref, 'comparison_basis_ref':basis.ref,
                'plan_refs':[row['plan_ref'] for row in normal_inputs], 'normalization_basis_refs':normal_bases}
        normalization_refs=[]

        def comparison_method(ref,kind,method,plan_refs):
            projection,row=original_method(ref)
            if (projection.comparison is None or row.kind!=kind or row.method_ref!=method or row.task_ref!=task.ref
                    or row.profile_ref!=profile.ref or row.comparison_basis_ref!=basis.ref
                    or set(row.plan_refs)!=set(plan_refs) or set(row.normalization_basis_refs)!=set(normal_bases)):
                raise ValueError('Comparison result changes original task, plans, profile or transformation bases')
            if profile.available_at.offset>row.calculated_at.offset or any(p.available_at.offset>row.calculated_at.offset for p in plans if p.ref in plan_refs):
                _needs('comparison_after_original_source_versions',[ref])
            if any(normal_by_plan[p].available_at.offset>row.calculated_at.offset for p in normal_by_plan if normal_by_plan[p].ref in normal_bases):
                _needs('comparison_after_original_normalization_bases',[ref])
            return row

        if profile.normalization_result_ref is not None:
            row=comparison_method(profile.normalization_result_ref,'normalization',RESEARCH_NORMALIZE_METHOD,[r['plan_ref'] for r in normal_inputs])
            if row.ranked_groups:raise ValueError('Normalization cannot substitute for ranking')
            normalization_input=ResearchNormalizationInput(currency=basis.currency,plans=normal_inputs,source_refs=list(sources.values()))
            if prepare_ranking:
                normalized_costs=row.normalized_costs
                expected={value.plan_ref:value for value in normalization_input.plans}
                if (len(normalized_costs)!=len(expected) or {value.plan_ref for value in normalized_costs}!=set(expected)
                        or any(value.amount.currency!=basis.currency
                            or value.amount.basis_ref!=expected[value.plan_ref].fx_basis_ref
                            or decimal_fraction(value.amount.value)<0 for value in normalized_costs)):
                    raise ValueError('Saved ranking dependency changes original normalized plan set, currency or numeric basis')
            else:
                # Consume the saved report and verify its exact arithmetic;
                # registered production belongs to the guarded save entry.
                report=normalize_plans(normalization_input)
                if row.normalized_costs!=report.normalized_costs:raise ValueError('Saved normalized costs disagree with original exact sourced transformations')
                normalized_costs=report.normalized_costs
            normalization_refs.append(row.ref)
            for value in normalized_costs:
                plan_costs[value.plan_ref]=value.amount
        uncertainties={}
        for option,option_plans in groups.items():
            if not option_plans or option in blocked:continue
            coverage=set();total=Fraction()
            for plan in option_plans:
                keys=plan_coverage.get(plan.ref,set())
                if plan.ref not in plan_costs or coverage&keys:
                    question('comparison',option);blocked.add(option);break
                coverage.update(keys);total+=decimal_fraction(plan_costs[plan.ref].value)
            if option in blocked:continue
            if coverage!=set(profile.required_scope_keys):question('comparison',option);blocked.add(option);continue
            # Summarize disjoint submitted scopes for comparison only; create no new A04 plan.
            costs[option]=Money(value=exact_decimal(total),currency=basis.currency,basis_ref=plan_costs[option_plans[0].ref].basis_ref)
            values=[p.uncertainty for p in option_plans]
            uncertainties[option]=values[0].value if values and all(v.state=='known' and v==values[0] for v in values) else None
        comparable=bool(plans) and bool(options) and not blocked and set(costs)==set(by_option)
        if prepare_ranking:
            if not comparable:_needs('comparable_original_qs_research_costs_before_ranking',action_input.cost_plan_refs)
            if any(c.metric=='risk' for c in profile.criteria) and any(v is None for v in uncertainties.values()):
                _needs('known_original_qs_research_risk_for_selected_criteria',[profile.ref])
            for criterion in profile.criteria:evidence([criterion.basis_ref])
            for option in by_option:
                evidence([costs[option].basis_ref])
                if uncertainties[option] is not None:evidence([uncertainties[option].basis_ref])
            reading.recheck()
            return {'kind':'prepared', 'input':ResearchRankInput(criteria=profile.criteria,options=[{
                    'option_ref':option,'price':costs[option],'risk':uncertainties.get(option)} for option in by_option],
                    source_refs=list(sources.values())),
                'calculation_ref':profile.ranking_result_ref, 'task_ref':task.ref, 'profile_ref':profile.ref,
                'comparison_basis_ref':basis.ref, 'plan_refs':[plan.ref for plan in selected_plans],
                'normalization_basis_refs':normal_bases, 'normalization_result_ref':profile.normalization_result_ref}
        ranked=[];ranking_tied=False
        if comparable and profile.ranking_result_ref is not None:
            if any(c.metric=='risk' for c in profile.criteria) and any(v is None for v in uncertainties.values()):
                question('ranking');comparable=False
            else:
                row=comparison_method(profile.ranking_result_ref,'ranking',RESEARCH_RANK_METHOD,[p.ref for p in selected_plans])
                if row.normalized_costs:raise ValueError('Ranking must consume original costs without replacing them')
                for criterion in profile.criteria:evidence([criterion.basis_ref])
                if profile.normalization_result_ref is not None:
                    _,normal=original_method(profile.normalization_result_ref)
                    if normal.calculated_at.offset>row.calculated_at.offset:_needs('ranking_after_original_normalized_costs',[row.ref])
                report=rank_plans(ResearchRankInput(criteria=profile.criteria,options=[{
                    'option_ref':option,'price':costs[option],'risk':uncertainties.get(option)} for option in by_option],source_refs=list(sources.values())))
                if row.ranked_groups!=report.ranked_groups:raise ValueError('Saved ranking differs from selected criteria or exact tie groups')
                # QSComparison has a strict list; a tied ordering must not suggest a unique rank.
                if any(len(group)>1 for group in report.ranked_groups):ranking_tied=True
                else:ranked=[group[0] for group in report.ranked_groups]
        comparison={'option_refs':action_input.option_refs,'cost_plan_refs':action_input.cost_plan_refs,
            'comparison_basis_ref':basis.ref,'comparable':comparable,'normalization_result_refs':normalization_refs,
            'ranked_option_refs':ranked if comparable else [],'missing_items':questions,
            'explanation':'Original scoped costs only; differences, uncertainty, professional limits and exclusions remain explicit; no feasibility or investment approval'
                + ('; selected method reports tied options, so a strict ranking is withheld' if ranking_tied else '')}
        if at_limit:return completed('deliver_at_limit',comparison=comparison,remaining_questions=questions)
        if not comparable and profile.missing_policy=='request_research' and task.request_profile_ref is not None:
            request=read(task.request_profile_ref,QSResearchRequestView)
            if request.task_ref!=task.ref or set(request.authority_basis_refs)!={grant.ref}:
                raise ValueError('Research request changes original task or independent delegation')
            if request.purpose not in grant.allowed_purposes:_needs('independently_authorized_research_request_purpose')
            unique_refs(request.input_refs);unique_refs(request.output_requirement_refs);unique_refs(request.dependency_refs)
            if request.incremental_budget.state=='known':
                budget=request.incremental_budget.value;evidence([budget.basis_ref])
                if budget.currency!=limit.budget_cap.currency:_unsupported('qs-research-request-budget-conversion')
                if decimal_fraction(budget.value)<0:raise ValueError('Research request budget cannot be negative')
                if decimal_fraction(budget.value)>cash:return completed('deliver_at_limit',comparison=comparison,remaining_questions=questions)
            elif request.work_profile_ref is not None:_needs('estimated_research_incremental_budget')
            if request.effort_estimate.state=='known':
                value=request.effort_estimate.value;evidence([value.basis_ref])
                if value.unit!=limit.effort_cap.unit:_unsupported('qs-research-request-effort-conversion')
                if decimal_fraction(value.value)<0:raise ValueError('Research request effort cannot be negative')
                if decimal_fraction(value.value)>effort:return completed('deliver_at_limit',comparison=comparison,remaining_questions=questions)
            elif request.work_profile_ref is not None:_needs('estimated_research_request_effort')
            if request.desired_window.state=='known':
                window=request.desired_window.value
                clock(window.start);clock(window.end)
                if window.start.offset<now.offset:_needs('future_original_qs_research_request_window')
            for ref in request.input_refs:
                read(ref,QSResearchReferenceView)
            for ref in [*request.output_requirement_refs,*request.dependency_refs,
                        *([request.work_profile_ref] if request.work_profile_ref is not None else [])]:
                original=read(ref,QSResearchReferenceView)
                if original.task_ref!=task.ref:
                    raise ValueError('Research request borrows another task work, requirement or dependency')
            if not questions:question('comparison')
            return completed('request_research',questions=questions,request={
                'scope':scope,'purpose':request.purpose,'input_refs':request.input_refs,'output_requirement_refs':request.output_requirement_refs,
                'work_profile_ref':request.work_profile_ref,'effort_estimate':request.effort_estimate,'desired_window':request.desired_window,
                'authority_basis_refs':request.authority_basis_refs,'dependency_refs':request.dependency_refs,'questions':questions})
        if not comparable:return completed('cannot_rank',comparison=comparison,reason='Missing submitted scoped costs, incompatible comparison basis or unresolved professional/uncertainty input')
        return completed('compare',comparison=comparison)
    except ObservationGap as exc:
        reading.recheck()
        return exc.result
