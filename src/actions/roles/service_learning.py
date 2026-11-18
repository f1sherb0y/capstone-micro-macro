"""Shared private feedback, future judgments and independently approved training."""
from src.actions.contracts.common import EvidenceRecord, Known, StrictRecord
from src.actions.contracts.architect_learning_objects import architect_learning_types, ArchitectLearningJudgment, ArchitectJudgmentChange
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.architect_learning import LEARNING_METHOD, TRAINING_METHOD, ArchitectFeedbackInput, ArchitectFeedbackSample
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def update_service_experience(context, action_input, reading, *, action_id='ARCHITECT-A12',
        learning_types=None, capability_from_state=False, additional_action=None, prepare_assessment=False,
        prepare_training=False):
    if prepare_assessment and prepare_training:
        raise ValueError('Learning preparation requires one explicit report kind')
    types=learning_types or architect_learning_types()
    now,org,scope=context.business_time,reading.organization_id,context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref!=now.clock_ref: _unsupported('architect-learning-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord): _unsupported('architect-learning-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start);clock(row.effective_window.end)

    def read(ref,schema,historic=False,linked=False):
        row=reading.resolve(ref)
        if not isinstance(row,schema): _unsupported('architect-learning-projection:'+ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Learning source expands original authorized scope')
        evidence(getattr(row,'evidence_refs',[]))
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset: _needs('received_original_architect_learning_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start);clock(row.effective_window.end)
            if not historic and not row.effective_window.contains(now): _needs('current_original_architect_learning_source',[ref])
        return row

    def true(value): return isinstance(value,Known) and value.value is True

    def authorize(ref,actor,function,organization,action,at,target):
        grant=read(ref,Authorization,historic=True,linked=True);assignment=read(function,RoleAssignment,historic=True,linked=True)
        roles={'ARCHITECT':'Architect','ENGINEER':'Engineer','QS':'QS','OWN':'Owner','GOV':'Government',
               'CONTRACTOR':'Contractor','SUPPLIER':'Supplier','BANK':'Bank'}
        if (grant.actor_id!=actor or grant.function_ref!=function or grant.organization_id!=organization
                or assignment.function_ref!=function or assignment.role!=roles.get(action.split('-')[0])
                or action not in grant.action_ids or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Learning substitutes original author/function/organization/action/scope authority')
        clock(at);clock(grant.validity.start);clock(grant.validity.end)
        if not grant.validity.contains(at): _needs('original_architect_learning_authority_at_execution',[ref])
        evidence(grant.basis_refs+assignment.basis_refs)

    def author(row,own=False):
        clock(row.authored_at)
        if row.authored_at.offset>row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Learning source precedes original author execution')
        if own and row.author_organization_id!=org: raise ValueError('Learning replaces original private firm author')
        authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,
            row.author_organization_id,row.author_action_id,row.authored_at,row.scope)

    def wait(ref,code='query_original_architect_learning_execution'):
        reading.recheck()
        return {'kind':'deferred','reason_code':code,'resume_condition':{'trigger':'dependency_change',
            'object_refs':[ref],'earliest_time':None,'condition_code':code}}

    def complete(**fields):
        reading.recheck()
        if decision.choice=='analyze_error':
            return {'kind':'completed','payload':{'choice':decision.choice,'scope':scope,**fields,'note':
                'Original comparable cost forecast error record only. The original prediction and information remain immutable; this metric does not prove calibrated forecasts, improved capability or actual payment and conveys no private costs to other parties.'}}
        if decision.choice=='request_qualification_update':
            return {'kind':'completed','payload':{'choice':decision.choice,'scope':scope,**fields,'note':
                'Qualification evidence verification request only. Original credential status/scope/validity remain unchanged until the responsible service verifies and applies this exact issuer event. Training, text and private judgments never renew credentials or prove zero risk.'}}
        return {'kind':'completed','payload':{'choice':decision.choice,'scope':scope,**fields,'note':
            'Future private judgment or training proposal only. Original estimates, engineering records, capability and qualifications remain unchanged. Training requires separate approval, investment, scheduling and independently verified outputs; this proposal reserves no resources or funds and displaces no existing engagement.'}}

    def calculate(ref,data):
        result=reading.calculate(ref,data)
        if result.kind!='ok':
            if result.kind=='invalid_input': _unsupported('architect-learning-method-domain')
            raw=result.model_dump(mode='python')
            if result.kind=='needs_information': raw['requested_refs']=[]
            raise ObservationGap(raw)
        return result.value

    def feedback(ref):
        row=read(ref,types['Feedback'],historic=True,linked=True);author(row)
        clock(row.received_at);clock(row.event.occurred_at)
        if row.recipient_organization_id!=org: raise ValueError('Learning uses another organization private feedback')
        if row.received_at.offset>now.offset: _needs('actually_received_architect_feedback',[ref])
        if (row.event.occurred_at.offset>row.authored_at.offset or row.available_at.offset>row.received_at.offset
                or row.event_sha256!=content_digest(row.event)):
            raise ValueError('Feedback changes original event or knowledge chronology')
        keys([outcome.dimension_ref for outcome in row.event.outcomes])
        return row

    try:
        if action_input.scope!=scope: raise ValueError('Learning changes invocation scope')
        strategy=read(action_input.strategy_ref,types['Strategy']);author(strategy,own=True)
        state=read(strategy.learning_state_ref,types['ArchitectLearningState'])
        decision=read(strategy.decision_profile_ref,types['ArchitectLearningDecision']);author(decision,own=True)
        capability=read(state.capability_ref if capability_from_state else action_input.capability_ref,types['Capability']);author(capability,own=True)
        if (strategy.organization_id!=org or state.organization_id!=org or capability.organization_id!=org
                or state.strategy_ref!=strategy.ref or state.capability_ref!=capability.ref
                or decision.organization_id!=org or decision.strategy_ref!=strategy.ref
                or decision.actor_id!=context.actor_id or decision.function_ref!=context.function_ref
                or decision.authority_ref not in context.authorization_refs or state.scope!=scope or decision.scope!=scope):
            raise ValueError('Learning changes original private strategy, capability, state or current decision authority')
        authorize(decision.authority_ref,context.actor_id,context.function_ref,org,action_id,now,scope)
        if (getattr(decision,'monthly_client_task_ref',None) is not None
                or getattr(decision,'monthly_client_observation_ref',None) is not None):
            if (action_id!='ARCHITECT-A12' or prepare_assessment or prepare_training
                    or decision.monthly_client_task_ref is None or decision.monthly_client_observation_ref is None
                    or decision.monthly_portfolio_policy_ref is not None or decision.monthly_portfolio_observation_ref is not None
                    or decision.monthly_method_policy_ref is not None or decision.monthly_method_observation_ref is not None):
                raise ValueError('Client relationship recording requires paired original own sources, separate from portfolio/method/training')
            from src.actions.roles.architect_client_relationship import analyze_client_relationship
            return complete(feedback_refs=[],interpretation=analyze_client_relationship(
                context,action_input,reading,decision=decision,state=state,capability=capability))
        if (getattr(decision,'monthly_portfolio_policy_ref',None) is not None
                or getattr(decision,'monthly_portfolio_observation_ref',None) is not None):
            if (action_id!='ARCHITECT-A12' or prepare_assessment or prepare_training
                    or decision.monthly_method_policy_ref is not None or decision.monthly_method_observation_ref is not None):
                raise ValueError('Portfolio recording cannot replace another role, method analysis or formal training')
            from src.actions.roles.architect_monthly_portfolio import analyze_monthly_portfolio
            return complete(feedback_refs=[],interpretation=analyze_monthly_portfolio(
                context,action_input,reading,decision=decision,state=state,capability=capability))
        if (getattr(decision,'monthly_estimation_policy_ref',None) is not None
                or getattr(decision,'monthly_estimation_observation_ref',None) is not None):
            if action_id!='QS-A12' or prepare_assessment or prepare_training:
                raise ValueError('Monthly estimation cannot replace formal cost learning or training')
            from src.actions.roles.qs_monthly_estimation import analyze_monthly_estimation
            interpretation=analyze_monthly_estimation(context,action_input,reading,decision=decision,
                state=state,capability=capability)
            return complete(feedback_refs=[],interpretation=interpretation)
        if decision.monthly_method_policy_ref is not None or decision.monthly_method_observation_ref is not None:
            if (decision.monthly_method_policy_ref is None or decision.monthly_method_observation_ref is None
                    or prepare_assessment or prepare_training):
                raise ValueError('Monthly analysis requires both sources and cannot substitute a formal assessment or training estimate')
            from src.actions.roles.professional_monthly_methods import analyze_monthly_methods
            interpretation=analyze_monthly_methods(context,action_input,reading,decision=decision,state=state,
                capability=capability,action_id=action_id)
            return complete(feedback_refs=[],interpretation=interpretation)
        clock(state.as_of)
        if state.as_of!=now or state.coverage!='complete': _needs('complete_current_architect_learning_history')
        if keys(decision.feedback_refs)!=keys(action_input.feedback_refs) or not keys(action_input.feedback_refs)<=keys(state.received_feedback_refs):
            raise ValueError('Learning changes original selected received feedback')
        business=set();keys(state.execution_refs)
        for ref in state.execution_refs:
            execution=read(ref,types['ArchitectLearningExecution'],historic=True,linked=True)
            if execution.organization_id!=org or execution.run_id!=context.run_id or execution.strategy_ref.id!=strategy.ref.id or execution.business_key in business:
                raise ValueError('Learning execution repeats or replaces original run/firm/strategy/business identity')
            business.add(execution.business_key)
            if execution.business_key==decision.business_key:
                original=read(execution.decision_ref,types['ArchitectLearningDecision'],historic=True,linked=True)
                metadata={'ref','strategy_ref','available_at','effective_window'}
                if (original.strategy_ref!=execution.strategy_ref or original.organization_id!=execution.organization_id
                        or original.scope!=execution.scope or original.business_key!=execution.business_key
                        or execution.decision_sha256!=content_digest(original)
                        or original.model_dump(exclude=metadata)!=decision.model_dump(exclude=metadata)):
                    raise ValueError('Learning changes original content under old business identity')
                return wait(execution.ref)
            if execution.status in {'pending','unknown'}: return wait(execution.ref)
        events={};selected={}
        for ref in action_input.feedback_refs:
            row=feedback(ref);identity=row.event.event_key
            if identity in events and events[identity]!=row.event_sha256: raise ValueError('Feedback event identity changes original content')
            events[identity]=row.event_sha256
            selected.setdefault(identity,row)
        if prepare_assessment and decision.choice!='update_judgment':
            _needs('original_judgment_update_decision_before_learning_assessment')
        if prepare_training and decision.choice!='propose_training':
            _needs('original_training_proposal_decision_before_estimate')
        if additional_action is not None:
            result=additional_action(state,decision,strategy,capability,read,author,evidence,clock,complete,wait)
            if result is not None: return result
        if action_input.learning_profile_ref is None:
            if decision.choice!='record_feedback': _needs('selected_learning_profile_before_judgment_or_training')
            return complete(feedback_refs=action_input.feedback_refs,interpretation=decision.interpretation)
        if action_input.learning_profile_ref!=state.learning_profile_ref: raise ValueError('Learning substitutes original selected profile')
        profile=read(action_input.learning_profile_ref,types['LearningProfile']);author(profile,own=True)
        if profile.organization_id!=org or profile.strategy_ref!=strategy.ref: raise ValueError('Learning profile changes original firm or strategy')
        if decision.choice=='record_feedback': return complete(feedback_refs=action_input.feedback_refs,interpretation=decision.interpretation)
        if not true(profile.enabled): _needs('explicitly_enabled_architect_learning')
        if profile.calculation_method_ref!=LEARNING_METHOD: _unsupported('architect-selected-learning-mechanism')
        if not selected: _needs('received_original_feedback_for_learning')
        for row in selected.values():
            if row.status!='verified' or not true(row.verified): _needs('verified_original_architect_feedback',[row.ref])
            subject=read(row.event.subject_ref,StrictRecord,historic=True,linked=True)
            if content_digest(subject)!=row.event.subject_sha256: raise ValueError('Learning rewrites original subject content')
            if hasattr(subject,'available_at') and subject.available_at.offset>row.received_at.offset:
                raise ValueError('Learning injects subsequently received subject into earlier feedback')

        if decision.choice=='update_judgment':
            applied=set()
            if not keys(state.applied_feedback_refs)<=keys(state.received_feedback_refs): raise ValueError('Learning history applies unreceived feedback')
            for ref in state.applied_feedback_refs:
                row=feedback(ref);identity=row.event.event_key
                if identity in events and events[identity]!=row.event_sha256: raise ValueError('Applied feedback event changes original content')
                events[identity]=row.event_sha256;applied.add(identity)
            fresh={key:row for key,row in selected.items() if key not in applied}
            if not fresh: return wait(state.ref,'feedback_already_applied_to_original_judgment')
            dimensions={};keys(profile.dimension_refs)
            for ref in profile.dimension_refs:
                dimension=read(ref,types['JudgmentDimension']);author(dimension,own=True)
                if dimension.organization_id!=org or dimension.learning_profile_ref!=profile.ref or not dimension.value_refs or not dimension.outcome_codes:
                    raise ValueError('Learning dimension replaces original finite catalog')
                keys(dimension.value_refs)
                if len(set(dimension.outcome_codes))!=len(dimension.outcome_codes): raise ValueError('Learning repeats a declared outcome code')
                dimensions[ref.key()]=dimension
            current={};keys([c.dimension_ref for c in strategy.judgments])
            for change in strategy.judgments:
                dimension=dimensions.get(change.dimension_ref.key())
                if dimension is None or change.selected_value_ref.key() not in keys(dimension.value_refs):
                    raise ValueError('Current strategy judgment is outside selected finite catalog')
                value=read(change.selected_value_ref,types['JudgmentValue']);author(value,own=True)
                if value.organization_id!=org or value.dimension_ref!=dimension.ref: raise ValueError('Current judgment value changes original dimension')
                current[dimension.ref.key()]=value.ref
            rules={};keys(profile.rule_refs)
            for ref in profile.rule_refs:
                row=read(ref,types['LearningRule']);author(row,own=True);rule=row.rule
                dimension=dimensions.get(rule.dimension_ref.key())
                if (row.organization_id!=org or row.learning_profile_ref!=profile.ref or rule.rule_ref!=row.ref
                        or dimension is None or not set(rule.outcome_codes)<=set(dimension.outcome_codes)
                        or rule.selected_value_ref.key() not in keys(dimension.value_refs)):
                    raise ValueError('Learning rule substitutes original catalog, values or outcomes')
                value=read(rule.selected_value_ref,types['JudgmentValue']);author(value,own=True)
                if value.organization_id!=org or value.dimension_ref!=dimension.ref: raise ValueError('Learning value belongs to another firm or dimension')
                rules[ref.key()]=row
            samples=[]
            for row in fresh.values():
                for outcome in row.event.outcomes:
                    dimension=dimensions.get(outcome.dimension_ref.key())
                    if dimension is None: continue
                    if outcome.outcome_code not in dimension.outcome_codes: _unsupported('architect-feedback-outcome-domain')
                    samples.append(ArchitectFeedbackSample(feedback_ref=row.ref,event_key=row.event.event_key,
                        dimension_ref=outcome.dimension_ref,outcome_code=outcome.outcome_code))
            if not samples or not rules: _needs('declared_feedback_rules_and_matching_dimensions')
            # Preserve the evidence already checked on these original sources.
            # The method registry requires explicit Evidence refs in its input;
            # projection refs alone cannot prove the feedback/rule provenance.
            source_refs={ref.key():ref for ref in [strategy.ref,profile.ref,
                *[row.ref for row in fresh.values()],*profile.dimension_refs,*profile.rule_refs]}
            for row in (strategy,profile,*fresh.values(),*dimensions.values(),*rules.values()):
                source_refs.update({ref.key():ref for ref in row.evidence_refs})
            data=ArchitectFeedbackInput(samples=samples,rules=[row.rule for row in rules.values()],
                source_refs=list(source_refs.values()))
            if prepare_assessment:
                # A predeclared target lets publication be consumed by the same
                # immutable strategy/decision. Preparation does not read it;
                # the producer and persistence gates check target identity.
                reading.recheck()
                return {'kind':'prepared','input':data,'strategy_ref':strategy.ref,
                    'learning_profile_ref':profile.ref,'assessment_ref':decision.assessment_ref}
            if decision.assessment_ref is None: _needs('saved_original_architect_learning_assessment')
            saved=read(decision.assessment_ref,types['ArchitectLearningAssessment']);author(saved,own=True)
            if (saved.organization_id!=org or saved.strategy_ref!=strategy.ref or saved.learning_profile_ref!=profile.ref
                    or saved.data!=data or saved.input_sha256!=content_digest(data)):
                raise ValueError('Learning assessment differs from original received feedback and selected rules')
            if saved.status=='unsupported': _unsupported('architect-learning-assessment-domain')
            if saved.status!='ok' or saved.report is None: _needs('successful_original_architect_learning_assessment',[saved.ref])
            report=calculate(LEARNING_METHOD,data)
            if report!=saved.report: raise ValueError('Learning report differs from original declared rule calculation')
            changes=[];used=set()
            for selection in report.selections:
                if current.get(selection.dimension_ref.key())==selection.selected_value_ref: continue
                row=rules[selection.rule_ref.key()]
                changes.append(ArchitectJudgmentChange(dimension_ref=selection.dimension_ref,
                    selected_value_ref=selection.selected_value_ref,explanation=row.explanation))
                used.update(ref.key() for ref in selection.feedback_refs)
            if not changes: return wait(profile.ref,'no_new_declared_judgment_change')
            refs={ref.key():ref for row in fresh.values() if row.ref.key() in used for ref in row.evidence_refs}
            for row in (profile,saved,*[rules[s.rule_ref.key()] for s in report.selections]):
                refs.update({ref.key():ref for ref in row.evidence_refs})
            revision=ArchitectLearningJudgment(prior_strategy_ref=strategy.ref,learning_profile_ref=profile.ref,
                evidence_refs=list(refs.values()),changes=changes)
            return complete(revision=revision.model_dump(mode='python'))

        if decision.training_profile_ref is None or decision.training_profile_ref.key() not in keys(profile.training_profile_refs):
            _needs('original_allowed_training_request')
        training=read(decision.training_profile_ref,types['TrainingRequestProfile']);author(training,own=True)
        request=training.request
        if (training.organization_id!=org or training.learning_profile_ref!=profile.ref or training.capability_ref!=capability.ref
                or request.scope!=scope or request.work_profile_ref is None or capability.status!='current'):
            _needs('original_current_capability_and_sourced_training_work')
        authority=read(training.authority_ref,types['Authority']);author(authority,own=True);clock(authority.as_of)
        if (authority.organization_id!=org or authority.actor_id!=context.actor_id or authority.function_ref!=context.function_ref
                or authority.training_profile_ref!=training.ref or authority.capability_ref!=capability.ref
                or request.authority_basis_refs!=[authority.ref] or not true(authority.permitted)
                or authority.as_of!=now or authority.coverage!='complete'):
            _needs('current_independent_original_training_authority')
        if not keys(request.input_refs)<=keys(authority.allowed_input_refs): raise ValueError('Training request widens original input permission')
        required={strategy.ref.key(),capability.ref.key(),profile.ref.key(),training.estimate_ref.key(),request.work_profile_ref.key()}
        if not required<=keys(request.input_refs) or not keys(action_input.feedback_refs)<=keys(request.input_refs):
            raise ValueError('Training request omits original strategy, capability, feedback, method or estimate')
        if not request.output_requirement_refs or keys(request.output_requirement_refs)!=keys(authority.allowed_output_requirement_refs):
            _needs('explicit_authorized_verifiable_training_outputs')
        for ref in request.output_requirement_refs:
            requirement=read(ref,types['DeliverableRequirement']);author(requirement,own=True)
            if (requirement.organization_id!=org or requirement.training_profile_ref!=training.ref
                    or requirement.independent_verifier_id in {context.actor_id,requirement.author_actor_id}):
                raise ValueError('Training output must retain original independently verifiable criterion')
        work=read(request.work_profile_ref,types['WorkProfile']);author(work,own=True)
        if work.organization_id!=org or work.training_profile_ref!=training.ref or work.data.work_profile_ref!=work.ref or not true(work.supported):
            _needs('original_supported_training_work_method')
        if work.calculation_method_ref!=TRAINING_METHOD: _unsupported('architect-training-estimate-mechanism')
        if not set(work.data.participant_ids)<=set(authority.allowed_participant_ids):
            raise ValueError('Training substitutes participants outside original independent permission')
        for ref in request.output_requirement_refs:
            requirement=read(ref,types['DeliverableRequirement'])
            if requirement.independent_verifier_id in work.data.participant_ids:
                raise ValueError('Training participants cannot independently verify their own capability output')
        for ref in work.data.source_refs: read(ref,StrictRecord,historic=True,linked=True)
        evidence([work.data.per_participant_effort.basis_ref,work.data.cost_per_effort.basis_ref,work.data.fixed_cost.basis_ref])
        if prepare_training:
            # The estimate is needed before investment and scheduling can be
            # evaluated. Retain the predeclared target, without reading it.
            reading.recheck()
            return {'kind':'prepared','input':work.data,'estimate_ref':training.estimate_ref,
                'work_profile_ref':work.ref,'training_profile_ref':training.ref}
        estimate=read(training.estimate_ref,types['TrainingEstimate']);author(estimate,own=True);clock(estimate.executed_at)
        if (estimate.organization_id!=org or estimate.work_profile_ref!=work.ref or estimate.input_sha256!=content_digest(work.data)
                or estimate.executed_at.offset>estimate.authored_at.offset):
            raise ValueError('Training estimate changes original sourced work method or execution')
        if estimate.status=='unsupported': _unsupported('architect-training-estimate-domain')
        if estimate.status!='ok' or estimate.report is None: _needs('successful_original_training_estimate',[estimate.ref])
        report=calculate(TRAINING_METHOD,work.data)
        if report!=estimate.report: raise ValueError('Training report differs from exact original cost/effort estimate')
        if not isinstance(request.effort_estimate,Known) or request.effort_estimate.value!=report.effort:
            _needs('original_method_training_effort')
        evidence([authority.budget_limit.basis_ref,authority.actual_spent.basis_ref,authority.reserved_cost.basis_ref,authority.available_effort.basis_ref])
        costs=[authority.budget_limit,authority.actual_spent,authority.reserved_cost,report.estimated_cost]
        if len({m.currency for m in costs})!=1 or authority.available_effort.unit!=report.effort.unit:
            _unsupported('architect-training-budget-effort-units')
        if any(decimal_fraction(m.value)<0 for m in costs) or decimal_fraction(authority.available_effort.value)<0:
            raise ValueError('Training authority has negative original budget or available effort')
        available=decimal_fraction(authority.budget_limit.value)-decimal_fraction(authority.actual_spent.value)-decimal_fraction(authority.reserved_cost.value)
        if decimal_fraction(report.estimated_cost.value)>available or decimal_fraction(report.effort.value)>decimal_fraction(authority.available_effort.value):
            return wait(authority.ref,'training_investment_capacity_unavailable')
        if not isinstance(request.desired_window,Known): _needs('original_training_time_window')
        window=request.desired_window.value;clock(window.start);clock(window.end)
        clock(authority.allowed_window.start);clock(authority.allowed_window.end)
        if (window.bounds!='closed_open' or authority.allowed_window.bounds!='closed_open' or window.start.offset<now.offset
                or window.end.offset<=window.start.offset or window.start.offset<authority.allowed_window.start.offset
                or window.end.offset>authority.allowed_window.end.offset): _unsupported('architect-training-future-authorized-window')
        keys(request.dependency_refs)
        for ref in request.dependency_refs:
            dependency=read(ref,types['Dependency'])
            if dependency.training_profile_ref!=training.ref: raise ValueError('Training changes original dependency identity')
            if not true(dependency.satisfied): return wait(ref,'training_dependency_not_ready')
        for question in request.questions:
            if question.scope!=scope or not question.recipient_ids or not question.target_refs:
                raise ValueError('Training question must preserve specific original authorized scope and recipients')
            evidence(question.evidence_refs)
        return complete(request=request.model_dump(mode='python'),learning_profile_ref=profile.ref)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
