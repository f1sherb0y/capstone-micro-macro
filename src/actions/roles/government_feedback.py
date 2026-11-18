"""GOV-A12 preserves received observations and proposes work or policy evaluation."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, StrictRecord
from src.actions.contracts.government_feedback_objects import (
    GovObservationProfileView, GovWorkingAuthorityView, GovReceivedFeedbackView, GovVisibleStatisticView,
    GovStatisticSnapshotView, GovAvailableProjectView, GovFeedbackWorkView, GovFeedbackTaskView,
    GovFeedbackEstimateView, GovFeedbackRequestEstimateView, GovFeedbackDependencyView, GovFeedbackAssignmentView, GovFeedbackCalendarView,
    GovPolicyControlView, GovPolicyInstrumentView, GovFeedbackRuleView, GovFeedbackRequirementView,
    GovFeedbackExecutionView, GovRecipientView, GovResponseRequirementView, GovReviewQualificationView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, CapacityDemand, CapacityResource, ExactAmount
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def analyze_government_feedback(context, action_input, reading):
    now,org,scope=context.business_time,reading.organization_id,context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref!=now.clock_ref: _unsupported('government-feedback-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord): _unsupported('government-feedback-evidence-schema')
            if row.effective_window is not None: clock(row.effective_window.start);clock(row.effective_window.end)

    def read(ref,schema,historic=False,linked=False):
        row=reading.resolve(ref)
        if not isinstance(row,schema): _unsupported('government-feedback-projection:'+ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Government feedback expands original authorized scope')
        evidence(getattr(row,'evidence_refs',[]))
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset: _needs('received_original_government_feedback_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start);clock(row.effective_window.end)
            if not historic and not row.effective_window.contains(now): _needs('current_original_government_feedback_source',[ref])
        return row

    def true(value): return isinstance(value,Known) and value.value is True

    def authorize(ref,actor,function,organization,action,at,target):
        grant=read(ref,Authorization,historic=True,linked=True);assignment=read(function,RoleAssignment,historic=True,linked=True)
        roles={'GOV':'Government','OWN':'Owner','QS':'QS','ARCHITECT':'Architect','ENGINEER':'Engineer',
               'CONTRACTOR':'Contractor','SUPPLIER':'Supplier','BANK':'Bank'}
        if (grant.actor_id!=actor or grant.function_ref!=function or grant.organization_id!=organization
                or assignment.function_ref!=function or assignment.role!=roles.get(action.split('-')[0])
                or action not in grant.action_ids or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Feedback substitutes original actor/function/organization/action/scope authority')
        clock(at);clock(grant.validity.start);clock(grant.validity.end)
        if not grant.validity.contains(at): _needs('original_government_feedback_authority_at_execution',[ref])
        evidence(grant.basis_refs+assignment.basis_refs)
        return grant

    def author(row,own=False):
        clock(row.authored_at)
        if row.authored_at.offset>row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Feedback source precedes original author execution')
        if own and row.author_organization_id!=org: raise ValueError('Feedback substitutes original agency author')
        authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,row.author_organization_id,
            row.author_action_id,row.authored_at,row.scope)

    def wait(ref,code):
        reading.recheck()
        return {'kind':'deferred','reason_code':code,'resume_condition':{'trigger':'dependency_change','object_refs':[ref],
            'earliest_time':None,'condition_code':code}}

    def complete(**fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':profile.choice,'scope':scope,**fields,'note':
            'Received feedback/work/policy suggestion only. Complaints remain unverified unless separately proved. Missing/lagged statistics remain unknown. No policy parameters, legal conditions, historical decisions, Owner projects/budgets, available stock, cash or performance are changed. Policy evaluation, quantification, validation, freeze, publication, effective/transition rules and actual actor receipt require separate execution.'}}

    def questions(rows):
        for question in rows:
            if question.scope!=scope or not question.target_refs or not question.recipient_refs:
                raise ValueError('Feedback investigation needs specific original scoped targets/recipients')
            keys(question.target_refs);keys(question.recipient_refs);evidence(question.evidence_refs)
            if not keys(question.recipient_refs)<=keys(authority.allowed_recipient_refs):
                raise ValueError('Feedback investigation adds an unauthorized recipient')
            rule=read(question.requirement_ref,GovFeedbackRuleView);author(rule)
            response=read(question.response_requirement_ref,GovResponseRequirementView,linked=True)
            if rule.organization_id!=org or rule.purpose!='information_request' or not true(rule.permitted) or response.rule_ref!=rule.ref:
                _needs('original_feedback_question_rule_and_response_requirement')
            if not scope_covers(response.scope,scope): raise ValueError('Feedback response requirement changes original target scope')
            for ref in question.target_refs: read(ref,StrictRecord,linked=True)
            for ref in question.recipient_refs:
                recipient=read(ref,GovRecipientView,linked=True)
                if not scope_covers(recipient.scope,scope): raise ValueError('Feedback recipient has no original target scope')

    def request_check(request,purpose):
        if request.scope!=scope or request.purpose!=purpose or request.authority_basis_refs!=[authority.ref]:
            raise ValueError('Government feedback request changes original task purpose/scope/authority')
        supplied=keys(request.input_refs)
        if (not supplied<=keys(authority.allowed_input_refs)
                or not keys([*action_input.feedback_refs,*action_input.visible_statistic_refs,profile.ref])<=supplied):
            raise ValueError('Government feedback request widens or omits original observed inputs')
        if not request.output_requirement_refs or not keys(request.output_requirement_refs)<=keys(authority.allowed_output_requirement_refs):
            _needs('original_verifiable_government_feedback_task_outputs')
        for ref in request.output_requirement_refs:
            requirement=read(ref,GovFeedbackRequirementView);author(requirement,own=True)
            if requirement.organization_id!=org or requirement.requested_purpose!=purpose:
                raise ValueError('Feedback task output changes original purpose/agency')
        for ref in request.input_refs: read(ref,StrictRecord,historic=True,linked=True)
        questions(request.questions);keys(request.dependency_refs)
        for ref in request.dependency_refs: read(ref,GovFeedbackDependencyView)
        if isinstance(request.effort_estimate,Known):
            evidence([request.effort_estimate.value.basis_ref])
            if request.work_profile_ref is None or decimal_fraction(request.effort_estimate.value.value)<=0:
                raise ValueError('Known feedback task effort requires original positive work method')
        if request.work_profile_ref is not None:
            work=read(request.work_profile_ref,GovFeedbackWorkView);author(work,own=True)
            if work.organization_id!=org: raise ValueError('Feedback request borrows another agency work method')
            if isinstance(request.effort_estimate,Known):
                if work.request_estimate_ref is None: _needs('original_saved_feedback_request_effort_estimate')
                estimate=read(work.request_estimate_ref,GovFeedbackRequestEstimateView);author(estimate,own=True);clock(estimate.executed_at)
                if (estimate.organization_id!=org or estimate.work_profile_ref!=work.ref or estimate.purpose!=purpose
                        or keys(estimate.input_refs)!=supplied or keys(estimate.output_requirement_refs)!=keys(request.output_requirement_refs)
                        or estimate.effort!=request.effort_estimate.value or estimate.executed_at.offset>estimate.authored_at.offset):
                    raise ValueError('Feedback request effort changes original sourced method execution')
                if estimate.status=='unsupported': _unsupported('government-feedback-request-estimate-domain')
                if estimate.status!='succeeded': _needs('successful_original_feedback_request_estimate',[estimate.ref])
        if isinstance(request.desired_window,Known):
            window=request.desired_window.value;clock(window.start);clock(window.end)
            if (window.bounds!='closed_open' or window.end.offset<=window.start.offset or window.start.offset<now.offset
                    or window.start.offset<authority.allowed_window.start.offset or window.end.offset>authority.allowed_window.end.offset):
                raise ValueError('Feedback request bypasses original future authorized time window')

    try:
        if action_input.scope!=scope: raise ValueError('Feedback changes invocation scope')
        profile=read(action_input.observation_profile_ref,GovObservationProfileView);author(profile,own=True)
        authority=read(action_input.working_authority_ref,GovWorkingAuthorityView);author(authority,own=True)
        if (profile.organization_id!=org or profile.scope!=scope or profile.actor_id!=context.actor_id or profile.function_ref!=context.function_ref
                or profile.authority_ref not in context.authorization_refs or profile.working_authority_ref!=authority.ref
                or profile.policy_control_profile_ref!=action_input.policy_control_profile_ref or authority.organization_id!=org
                or authority.actor_id!=context.actor_id or authority.function_ref!=context.function_ref or not true(authority.permitted)
                or profile.choice not in authority.allowed_choices):
            raise ValueError('Feedback changes original agency/actor/working scope/action permission')
        authorize(profile.authority_ref,context.actor_id,context.function_ref,org,'GOV-A12',now,scope)
        clock(profile.as_of);clock(authority.as_of);clock(authority.allowed_window.start);clock(authority.allowed_window.end)
        if profile.as_of!=now or authority.as_of!=now or profile.coverage!='complete' or authority.coverage!='complete':
            _needs('complete_current_original_agency_feedback_and_work_authority')
        for supplied,original in [('feedback_refs','feedback_refs'),('visible_statistic_refs','statistic_refs')]:
            if keys(getattr(action_input,supplied))!=keys(getattr(profile,original)): raise ValueError('Feedback changes original actually visible input set')
        business=set();keys(profile.execution_refs)
        for ref in profile.execution_refs:
            execution=read(ref,GovFeedbackExecutionView,historic=True,linked=True)
            if execution.organization_id!=org or execution.run_id!=context.run_id or execution.business_key in business:
                raise ValueError('Feedback history repeats original run/agency/business identity')
            business.add(execution.business_key)
            if execution.business_key==profile.business_key:
                original=read(execution.profile_ref,GovObservationProfileView,historic=True,linked=True)
                metadata={'ref','execution_refs','available_at','effective_window','as_of'}
                if (original.organization_id!=execution.organization_id or original.scope!=execution.scope
                        or original.business_key!=execution.business_key
                        or execution.profile_sha256!=content_digest(original)
                        or original.model_dump(exclude=metadata)!=profile.model_dump(exclude=metadata)):
                    raise ValueError('Feedback changes original content under old business identity')
                return wait(ref,'query_original_government_feedback_execution')
            if execution.status in {'unknown','pending'}: return wait(ref,'query_original_government_feedback_execution')
        events={}
        for ref in action_input.feedback_refs:
            feedback=read(ref,GovReceivedFeedbackView,historic=True,linked=True);author(feedback)
            clock(feedback.observed_at);clock(feedback.received_at)
            if feedback.recipient_organization_id!=org: raise ValueError('Feedback is private to another agency')
            if feedback.received_at.offset>now.offset: _needs('actually_received_government_feedback',[ref])
            if feedback.observed_at.offset>feedback.authored_at.offset or feedback.available_at.offset>feedback.received_at.offset:
                raise ValueError('Feedback substitutes original observation/receipt chronology')
            source=read(feedback.event_source_ref,StrictRecord,historic=True,linked=True)
            if content_digest(source)!=feedback.event_source_sha256: raise ValueError('Feedback changes original event evidence')
            if hasattr(source,'available_at') and source.available_at.offset>feedback.received_at.offset:
                raise ValueError('Feedback predates actual receipt of its original evidence source')
            if feedback.event_key in events and events[feedback.event_key]!=feedback.event_source_sha256:
                raise ValueError('Repeated government feedback changes original physical event')
            events[feedback.event_key]=feedback.event_source_sha256
        for ref in action_input.visible_statistic_refs:
            statistic=read(ref,GovVisibleStatisticView,historic=True,linked=True);author(statistic)
            clock(statistic.reporting_window.start);clock(statistic.reporting_window.end);clock(statistic.received_at)
            if statistic.recipient_organization_id!=org or not scope_covers(scope,statistic.sampling_scope):
                raise ValueError('Statistics borrow private or hidden full-scope observations')
            if statistic.received_at.offset>now.offset: _needs('actually_received_lagged_government_statistic',[ref])
            if (statistic.reporting_lag_ticks<0 or statistic.reporting_window.end.offset>statistic.authored_at.offset
                    or statistic.available_at.offset>statistic.received_at.offset
                    or statistic.reporting_window.end.offset+statistic.reporting_lag_ticks>statistic.received_at.offset):
                raise ValueError('Statistic erases original reporting scope or observation lag')
            original=read(statistic.source_ref,GovStatisticSnapshotView,historic=True,linked=True);author(original)
            fields=['metric','measure','sampling_scope','reporting_window','case_ids','project_ids','available_project_refs','coverage']
            if content_digest(original)!=statistic.source_sha256 or any(getattr(original,f)!=getattr(statistic,f) for f in fields):
                raise ValueError('Statistic changes original reported snapshot or measure')
            if original.available_at.offset>statistic.received_at.offset: raise ValueError('Statistic predates received source report')
            if len(set(statistic.case_ids))!=len(statistic.case_ids) or len(set(statistic.project_ids))!=len(statistic.project_ids):
                raise ValueError('Statistic repeats original physical cases or projects')
            keys(statistic.available_project_refs);available=set();unknown=False
            for project_ref in statistic.available_project_refs:
                project=read(project_ref,GovAvailableProjectView,historic=True,linked=True);author(project);clock(project.observed_at)
                if (project.project_id in available or project.observed_at.offset>statistic.reporting_window.end.offset
                        or project.observed_at.offset>project.authored_at.offset or project.available_at.offset>statistic.received_at.offset):
                    raise ValueError('Available stock duplicates projects or uses observations after reporting cutoff')
                if not true(project.actual_available): unknown=True
                available.add(project.project_id)
            if isinstance(statistic.measure,Known):
                evidence([statistic.measure.value.basis_ref])
                if statistic.coverage!='complete': raise ValueError('Missing/partial statistical coverage cannot be replaced by a complete known measure')
                counts={'case_count':len(statistic.case_ids),'project_count':len(statistic.project_ids),'available_project_count':len(available)}
                if statistic.metric in counts and (decimal_fraction(statistic.measure.value.value)!=counts[statistic.metric]
                        or statistic.measure.value.unit!=('cases' if statistic.metric=='case_count' else 'projects')):
                    raise ValueError('Government statistic conflates original cases, projects or available stock')
                if statistic.metric=='available_project_count' and unknown: _needs('verified_actual_available_stock_observations')
        if profile.choice=='record_feedback':
            from src.actions.roles.government_monthly import analyze_monthly_business
            judgment=analyze_monthly_business(context,reading,profile)
            interpretation=profile.interpretation if judgment is None else judgment.model_dump_json()
            return complete(feedback_refs=action_input.feedback_refs,interpretation=interpretation)
        if profile.choice=='investigate':
            if profile.investigation_request is None or not profile.questions: _needs('specific_original_feedback_investigation_request')
            questions(profile.questions);request_check(profile.investigation_request,'investigation')
            if profile.investigation_request.questions!=profile.questions: raise ValueError('Investigation drops original scoped questions')
            return complete(questions=profile.questions,request=profile.investigation_request.model_dump(mode='python'))
        if profile.choice=='propose_policy':
            if profile.policy_proposal is None: _needs('original_scoped_policy_suggestion')
            proposal=profile.policy_proposal
            if (proposal.observation_profile_ref!=profile.ref or proposal.target_scope!=scope
                    or keys(proposal.issue_refs)!=keys(action_input.feedback_refs)
                    or keys(proposal.statistic_refs)!=keys(action_input.visible_statistic_refs)
                    or not proposal.proposed_instrument_refs or not keys(proposal.proposed_instrument_refs)<=keys(authority.allowed_instrument_refs)):
                raise ValueError('Policy proposal changes original issue/statistic/scope or allowed instrument')
            if action_input.policy_control_profile_ref is not None:
                control=read(action_input.policy_control_profile_ref,GovPolicyControlView);author(control,own=True)
                if control.organization_id!=org: raise ValueError('Policy control profile belongs to another agency')
                if true(control.endogenous_control_enabled) and not keys(proposal.proposed_instrument_refs)<=keys(control.allowed_instrument_refs):
                    raise ValueError('Policy evaluation substitutes enabled control instrument catalog')
            for ref in proposal.proposed_instrument_refs:
                instrument=read(ref,GovPolicyInstrumentView);author(instrument,own=True)
                if instrument.organization_id!=org or instrument.target_scope!=scope or not true(instrument.permitted_for_proposal):
                    _needs('original_allowed_policy_proposal_instrument',[ref])
                if not instrument.legal_basis_refs: _needs('original_policy_suggestion_legal_basis',[ref])
                for basis_ref in instrument.legal_basis_refs:
                    rule=read(basis_ref,GovFeedbackRuleView);author(rule)
                    if rule.organization_id!=org or rule.purpose!='proposal_basis' or not true(rule.permitted): _needs('original_policy_suggestion_rule_basis',[basis_ref])
            evidence(proposal.evidence_refs)
            if not proposal.evidence_refs: _needs('original_policy_suggestion_observation_evidence')
            request_check(proposal.evaluation_request,'policy_evaluation')
            return complete(proposal=proposal.model_dump(mode='python'))
        if profile.work_plan is None or not profile.work_plan.items: _needs('original_authorized_work_arrangement_plan')
        plan=profile.work_plan;selected=keys([i.task_ref for i in plan.items])
        if not selected<=keys(authority.authorized_task_refs) or not keys(authority.required_task_refs)<=selected:
            raise ValueError('Feedback work arrangement omits mandatory work or adds unauthorized tasks')
        work=read(plan.work_profile_ref,GovFeedbackWorkView);author(work,own=True)
        evidence([work.effort_per_capacity_tick.basis_ref]);productivity=decimal_fraction(work.effort_per_capacity_tick.value)
        if work.organization_id!=org or productivity<=0 or work.effort_per_capacity_tick.unit!=work.effort_unit:
            _unsupported('government-feedback-work-productivity-domain')
        calendar=read(authority.calendar_ref,GovFeedbackCalendarView);clock(calendar.as_of)
        if calendar.organization_id!=org or calendar.as_of!=now or calendar.coverage!='complete': _needs('current_complete_agency_work_calendar')
        resources={r.ref.id:r for r in calendar.resources};people=set()
        if len(resources)!=len(calendar.resources): raise ValueError('Work arrangement aliases original agency resources')
        for resource in calendar.resources:
            if resource.organization_id!=org or not isinstance(resource.personnel_ids,Known) or not resource.personnel_ids.value:
                _needs('original_real_agency_personnel')
            clock(resource.available_at);clock(resource.effective_window.start);clock(resource.effective_window.end)
            if resource.available_at.offset>now.offset or not resource.effective_window.contains(now):
                _needs('current_received_original_agency_feedback_resource',[resource.ref])
            ids=resource.personnel_ids.value
            if len(set(ids))!=len(ids) or people.intersection(ids): raise ValueError('Work arrangement duplicates actual shared agency personnel')
            people.update(ids);evidence(resource.evidence_refs+[resource.total.basis_ref])
        commitments={c.commitment_ref.key():c for c in calendar.commitments};keys([c.commitment_ref for c in calendar.commitments])
        if set(calendar.commitment_assignment_refs)!={c.commitment_ref.id for c in calendar.commitments}:
            raise ValueError('Work calendar omits original commitment/assignment relation')
        demands=[];excluded=set()
        for item in plan.items:
            task=read(item.task_ref,GovFeedbackTaskView);author(task,own=True)
            if (task.organization_id!=org or task.work_profile_ref!=work.ref or task.status not in {'authorized','waiting'}
                    or item.existing_assignment_ref!=task.existing_assignment_ref or keys(item.dependency_refs)!=keys(task.dependency_refs)):
                raise ValueError('Work arrangement changes original task/method/dependencies/assignment')
            clock(item.window.start);clock(item.window.end)
            if (item.window.bounds!='closed_open' or item.window.start.offset<now.offset or item.window.end.offset<=item.window.start.offset
                    or item.window.start.offset<authority.allowed_window.start.offset or item.window.end.offset>authority.allowed_window.end.offset):
                raise ValueError('Work arrangement changes original authorized future window')
            estimate=read(task.estimate_ref,GovFeedbackEstimateView);author(estimate,own=True);clock(estimate.executed_at)
            if estimate.status=='unsupported': _unsupported('government-feedback-work-estimate-domain')
            if (estimate.task_ref!=task.ref or estimate.work_profile_ref!=work.ref or estimate.status!='succeeded'
                    or estimate.executed_at.offset>estimate.authored_at.offset or not isinstance(task.remaining_effort,Known)):
                _needs('successful_original_remaining_work_method_estimate',[task.ref])
            if item.effort!=estimate.remaining_effort or task.remaining_effort.value!=item.effort or item.effort.unit!=work.effort_unit:
                raise ValueError('Work arrangement changes original method remaining effort')
            evidence([item.effort.basis_ref]);effort=decimal_fraction(item.effort.value)
            shares=[decimal_fraction(v) for v in task.resource_effort_shares.values()]
            if (effort<=0 or any(v<=0 for v in shares) or sum(shares,Fraction())!=1
                    or not item.resource_ids or len(set(item.resource_ids))!=len(item.resource_ids) or set(item.resource_ids)!=set(task.resource_effort_shares)):
                raise ValueError('Work arrangement substitutes original sourced effort or personnel shares')
            task_grant=authorize(task.authority_ref,task.actor_id,task.function_ref,org,task.execution_action_id,item.window.start,task.scope)
            if task_grant.validity.end.offset<item.window.end.offset: _needs('original_task_authority_for_entire_feedback_work_window')
            for ref in task.dependency_refs:
                dependency=read(ref,GovFeedbackDependencyView)
                if dependency.task_ref!=task.ref: raise ValueError('Work arrangement substitutes original dependency task')
                if not true(dependency.satisfied): return wait(ref,'government_feedback_work_dependency_pending')
            if item.existing_assignment_ref is not None:
                assignment=read(item.existing_assignment_ref,GovFeedbackAssignmentView)
                if assignment.task_ref!=task.ref or assignment.organization_id!=org: raise ValueError('Work rearrangement substitutes original assignment')
                if assignment.status=='unknown': return wait(assignment.ref,'query_original_feedback_work_assignment')
                if assignment.status=='effective':
                    if assignment.ref.key() not in keys(authority.replacement_assignment_refs): _needs('independent_atomic_work_replacement_permission')
                    old=keys(assignment.commitment_refs)
                    if not old or old&excluded: raise ValueError('Work arrangement aliases held assignment commitments')
                    for key in old:
                        commitment=commitments.get(key)
                        if commitment is None or calendar.commitment_assignment_refs[commitment.commitment_ref.id]!=assignment.ref:
                            raise ValueError('Work arrangement removes another original task commitment')
                    excluded.update(old)
            for identity in item.resource_ids:
                resource=resources.get(identity)
                if resource is None or resource.region_id!=task.region_id or task.function_code not in resource.function_codes or not set(task.discipline_codes)<=set(resource.discipline_codes):
                    _needs('suitable_original_agency_feedback_work_personnel')
                if not task.discipline_codes or resource.total.unit!=work.capacity_unit:
                    _unsupported('government-feedback-original-work-discipline-capacity-unit')
                grant=authorize(resource.authority_ref,resource.actor_id,resource.function_ref,org,task.execution_action_id,item.window.start,task.scope)
                clock(resource.effective_window.start);clock(resource.effective_window.end)
                if (grant.validity.end.offset<item.window.end.offset or not resource.effective_window.contains(item.window.start)
                        or resource.effective_window.end.offset<item.window.end.offset): _needs('original_agency_executor_authority_for_work_window')
                qualifications=[read(ref,GovReviewQualificationView) for ref in resource.qualification_refs]
                for person in resource.personnel_ids.value:
                    if not all(any(q.organization_id==org and person in q.personnel_ids and q.region_id==task.region_id
                            and discipline in q.discipline_codes and task.function_code in q.function_codes and true(q.valid)
                            and q.effective_window.contains(item.window.start) and q.effective_window.end.offset>=item.window.end.offset
                            for q in qualifications) for discipline in task.discipline_codes): _needs('original_qualified_feedback_work_personnel')
                demand=effort*decimal_fraction(task.resource_effort_shares[identity])/productivity/(item.window.end.offset-item.window.start.offset)
                demands.append(CapacityDemand(resource_kind=resource.ref.id,region_id=resource.region_id,unit=resource.total.unit,
                    amount=ExactAmount.from_fraction(demand),window=item.window,basis_refs=[item.effort.basis_ref,work.effort_per_capacity_tick.basis_ref]))
        data=CapacityInput(clock_ref=now.clock_ref,demands=demands,
            resources=[CapacityResource(resource_ref=r.ref,resource_kind=r.ref.id,region_id=r.region_id,total=r.total,effective_window=r.effective_window) for r in calendar.resources],
            commitments=[c for c in calendar.commitments if c.commitment_ref.key() not in excluded],source_refs=[calendar.ref,work.ref,authority.ref,*[i.task_ref for i in plan.items]])
        result=reading.calculate(CAPACITY_METHOD,data)
        if result.kind!='ok':
            if result.kind=='invalid_input': _unsupported('government-feedback-capacity-method-domain')
            raw=result.model_dump(mode='python')
            if result.kind=='needs_information': raw['requested_refs']=[]
            raise ObservationGap(raw)
        if not result.value.feasible: return wait(calendar.ref,'government_feedback_work_capacity_unavailable')
        return complete(plan=plan.model_dump(mode='python'),basis_ref=authority.ref)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
