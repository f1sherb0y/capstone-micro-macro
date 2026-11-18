"""BANK-A12 records future-only private lessons from received mature outcomes."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.bank_learning_objects import (
    BankLearningOrganizationView, BankLearningCaseView, BankLearningProjectView,
    BankLearningStateView, BankLearningProfileView, BankLearningObservationView, BankJudgmentView,
    BankHistoricalInformationView, BankVerifiedOutcomeView, BankLearningDimensionView, BankLearningMethodView,
    BankLearningPolicyRuleView, BankLearningAssessmentView, BankLearningExecutionView, LendingStrategyView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.bank_learning import LEARNING_METHOD, BankLearningSample
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def learn_bank_outcomes(context, action_input, reading):
    now,bank,scope=context.business_time,reading.organization_id,context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref!=now.clock_ref: _unsupported('bank-learning-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord): _unsupported('bank-learning-evidence-schema')
            if row.effective_window is not None: clock(row.effective_window.start)

    def read(ref,schema,historic=False,linked=False):
        row=reading.resolve(ref)
        if not isinstance(row,schema): _unsupported('bank-learning-projection:'+ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Learning input expands original bank authorized scope')
        evidence(getattr(row,'evidence_refs',[]))
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset: _needs('received_original_bank_learning_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now): _needs('current_original_bank_learning_source',[ref])
        return row

    def true(value): return isinstance(value,Known) and value.value is True

    def authorize(ref,actor,function,organization,action,at,target):
        grant=read(ref,Authorization,historic=True,linked=True);assignment=read(function,RoleAssignment,historic=True,linked=True)
        roles={'BANK':'Bank','OWN':'Owner','QS':'QS','ENGINEER':'Engineer','ARCHITECT':'Architect',
               'GOV':'Government','CONTRACTOR':'Contractor','SUPPLIER':'Supplier'}
        if (grant.actor_id!=actor or grant.function_ref!=function or grant.organization_id!=organization
                or assignment.role!=roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Learning substitutes original author/function/party/action authority')
        clock(at);clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('original_bank_learning_authority_at_execution',[ref])
        evidence(grant.basis_refs+assignment.basis_refs)
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset>row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Learning source precedes its original authorized author execution')
        return authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,
            row.author_organization_id,row.author_action_id,row.authored_at,row.scope)

    def wait(ref):
        reading.recheck()
        return {'kind':'deferred','reason_code':'query_original_bank_learning_execution','resume_condition':{
            'trigger':'dependency_change','object_refs':[ref],'earliest_time':None,'condition_code':'query_original_bank_learning_execution'}}

    def complete(**fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':profile.choice,'source_refs':profile.source_refs,**fields,
            'note':profile.note+' Private lesson/future strategy proposal only. Outcomes enter knowledge after actual receipt; original judgment and original information remain immutable. Error summaries do not prove risk calibration or effective learning. Existing debt/terms/cash and other banks knowledge remain governed by their own original records.'}}

    try:
        anchor=read(scope.ref,(BankLearningOrganizationView,BankLearningCaseView,BankLearningProjectView),linked=True)
        state=read(anchor.learning_state_ref,BankLearningStateView)
        profile=read(state.profile_ref,BankLearningProfileView)
        if (state.organization_id!=bank or state.scope!=scope or profile.organization_id!=bank or profile.state_ref!=state.ref
                or profile.actor_id!=context.actor_id or profile.function_ref!=context.function_ref or profile.scope!=scope
                or profile.authority_ref not in context.authorization_refs):
            raise ValueError('Bank learning substitutes original private bank/state/actor/scope/authority')
        authorize(profile.authority_ref,context.actor_id,context.function_ref,bank,'BANK-A12',now,scope)
        clock(state.as_of)
        if state.as_of!=now or state.coverage!='complete': _needs('complete_current_private_bank_learning_state')
        for supplied,original in [('observation_refs','observation_refs'),('prior_judgment_refs','judgment_refs'),('outcome_refs','outcome_refs'),('allowed_strategy_refs','allowed_strategy_refs')]:
            if keys(getattr(action_input,supplied))!=keys(getattr(state,original)): _needs('complete_original_bank_learning_'+supplied)
        if not keys(profile.source_refs)<=keys(state.observation_refs): raise ValueError('Learning selects observation private to another bank or outside original inputs')
        judgments={}
        for ref in state.judgment_refs:
            judgment=read(ref,BankJudgmentView,historic=True,linked=True);author(judgment)
            if judgment.lender_id!=bank or judgment.author_organization_id!=bank or not judgment.information_refs:
                raise ValueError('Learning substitutes original bank judgment or its original information')
            clock(judgment.evaluation_window.start);clock(judgment.evaluation_window.end)
            if judgment.authored_at.offset>judgment.evaluation_window.start.offset:
                raise ValueError('Original probability prediction is made after its evaluation began')
            keys(judgment.information_refs)
            if len(judgment.information_refs)!=len(judgment.information_sha256): raise ValueError('Original judgment information digest mapping incomplete')
            for information_ref,digest in zip(judgment.information_refs,judgment.information_sha256):
                information=read(information_ref,BankHistoricalInformationView,historic=True,linked=True);clock(information.known_at)
                if (information.recipient_organization_id!=bank or information.content_sha256!=digest
                        or information.known_at.offset>judgment.authored_at.offset or information.available_at.offset>judgment.authored_at.offset):
                    raise ValueError('Learning injects posterior information into original judgment')
            judgments[ref.key()]=judgment
        outcomes={};physical={}
        for ref in state.outcome_refs:
            outcome=read(ref,BankVerifiedOutcomeView,historic=True,linked=True);author(outcome)
            if outcome.lender_id!=bank or outcome.judgment_ref.key() not in judgments:
                raise ValueError('Outcome substitutes original bank or original judgment')
            judgment=judgments[outcome.judgment_ref.key()]
            if (outcome.judgment_sha256!=content_digest(judgment) or outcome.dimension_ref!=judgment.dimension_ref
                    or outcome.event_code!=judgment.event_code or outcome.evaluation_window!=judgment.evaluation_window):
                raise ValueError('Outcome changes original event/dimension/horizon or prediction content')
            identity=(outcome.physical_outcome_key,judgment.ref.key())
            if identity in physical: raise ValueError('Bank learning aliases one original verified outcome')
            physical[identity]=ref;outcomes[ref.key()]=outcome
        observations={};events=set()
        for ref in state.observation_refs:
            observation=read(ref,BankLearningObservationView,historic=True,linked=True);author(observation)
            clock(observation.observed_at);clock(observation.learned_at)
            if (observation.recipient_organization_id!=bank or observation.event_id in events or observation.outcome_ref.key() not in outcomes
                    or observation.observed_at.offset>observation.learned_at.offset or observation.learned_at.offset>now.offset
                    or observation.learned_at.offset>observation.available_at.offset):
                raise ValueError('Bank learning uses future/duplicate/unreceived/private outcome observation')
            events.add(observation.event_id);observations[ref.key()]=observation
        applied=set();business=set();pending=[];keys(state.execution_refs)
        for ref in state.execution_refs:
            execution=read(ref,BankLearningExecutionView,historic=True,linked=True)
            if execution.organization_id!=bank or execution.run_id!=context.run_id or execution.business_key in business:
                raise ValueError('Bank lesson history repeats original bank/run/business identity')
            business.add(execution.business_key)
            if execution.business_key==profile.business_key:
                original=read(execution.profile_ref,BankLearningProfileView,historic=True,linked=True)
                metadata={'ref','state_ref','available_at','effective_window'}
                if (original.organization_id!=execution.organization_id or original.scope!=execution.scope
                        or original.business_key!=execution.business_key or execution.profile_sha256!=content_digest(original)
                        or original.model_dump(exclude=metadata)!=profile.model_dump(exclude=metadata)):
                    raise ValueError('Bank learning changes payload under original lesson identity')
                return wait(execution.ref)
            if execution.status in {'unknown','pending'}: pending.append(execution)
            if execution.status=='succeeded':
                keys(execution.applied_outcome_refs)
                for outcome_ref in execution.applied_outcome_refs:
                    original=read(outcome_ref,BankVerifiedOutcomeView,historic=True,linked=True)
                    if original.lender_id!=bank: raise ValueError('Applied bank lesson belongs to another bank')
                    applied.add((original.physical_outcome_key,original.judgment_ref.key()))
        if profile.choice=='retain_judgment': return complete()
        if action_input.learning_method_ref is None: _unsupported('bank-learning-method-not-selected')
        if pending: return wait(pending[0].ref)
        if not profile.source_refs or profile.assessment_ref is None: _needs('original_selected_outcomes_and_saved_learning_assessment')
        method=read(action_input.learning_method_ref,BankLearningMethodView,linked=True);author(method)
        if method.lender_id!=bank or method.author_organization_id!=bank or method.calculation_method_ref!=LEARNING_METHOD or not true(method.supported):
            _unsupported('bank-selected-learning-method-domain')
        selected=[];selected_pairs=set();source_refs={method.ref.key():method.ref}
        for ref in profile.source_refs:
            observation=observations[ref.key()];outcome=outcomes[observation.outcome_ref.key()];judgment=judgments[outcome.judgment_ref.key()]
            if outcome.status=='failed': raise ObservationGap({'kind':'technical_error','error':{'kind':'unrecorded','correlation_id':context.operation_id,'code':'original-bank-outcome-verification-failed'},'retryability':'unknown'})
            if outcome.status=='unsupported': _unsupported('original-bank-outcome-verification-domain')
            if outcome.status!='verified' or not isinstance(outcome.occurred,Known) or now.offset<outcome.evaluation_window.end.offset:
                _needs('mature_original_verified_bank_outcome',[outcome.ref])
            if outcome.authored_at.offset<outcome.evaluation_window.end.offset or observation.learned_at.offset<outcome.available_at.offset:
                raise ValueError('Bank lesson predates mature verified outcome availability')
            if not isinstance(judgment.predicted_probability,Known): _needs('explicit_original_probability_prediction',[judgment.ref])
            identity=(outcome.physical_outcome_key,judgment.ref.key())
            if identity in selected_pairs or identity in applied: _needs('new_original_bank_outcome_without_duplicate_lesson',[outcome.ref])
            selected_pairs.add(identity)
            if judgment.dimension_ref.key() not in keys(method.dimension_refs): _unsupported('bank-learning-original-dimension-domain')
            dimension=read(judgment.dimension_ref,BankLearningDimensionView,linked=True)
            if dimension.lender_id!=bank or dimension.event_code!=judgment.event_code: raise ValueError('Bank learning replaces original risk event dimension')
            selected.append(BankLearningSample(judgment_ref=judgment.ref,outcome_ref=outcome.ref,dimension_ref=dimension.ref,
                predicted_probability=judgment.predicted_probability.value,occurred=outcome.occurred.value))
            for source_ref in [ref,outcome.ref,judgment.ref,dimension.ref]: source_refs[source_ref.key()]=source_ref
        saved=read(profile.assessment_ref,BankLearningAssessmentView,linked=True);grant=author(saved)
        if (saved.lender_id!=bank or saved.author_organization_id!=bank or saved.learning_method_ref!=method.ref
                or saved.data.samples!=selected or saved.input_sha256!=content_digest(saved.data)
                or not set(source_refs)<=keys(saved.data.source_refs) or not keys(saved.data.source_refs)<=keys(grant.readable_refs)):
            raise ValueError('Bank learning report substitutes original predictions/outcomes/method/input/read rights')
        if saved.status=='failed': raise ObservationGap({'kind':'technical_error','error':{'kind':'unrecorded','correlation_id':context.operation_id,'code':'original-bank-learning-calculation-failed'},'retryability':'unknown'})
        if saved.status=='unsupported': _unsupported('original-bank-learning-calculation-domain')
        if saved.status!='ok' or saved.report is None: _needs('original_calculable_bank_learning_report')
        for ref in saved.data.source_refs:
            source=reading.resolve(ref)
            if hasattr(source,'available_at'):
                clock(source.available_at)
                if source.available_at.offset>saved.authored_at.offset: raise ValueError('Learning calculation precedes original received facts')
        result=reading.calculate(LEARNING_METHOD,saved.data)
        if result.kind!='ok':
            if result.kind=='invalid_input': _unsupported('bank-learning-calculation-domain')
            raw=result.model_dump(mode='python')
            if result.kind=='needs_information': raw['requested_refs']=[]
            raise ObservationGap(raw)
        if result.value!=saved.report: raise ValueError('Bank learning report differs from exact original error summary')
        errors={d.dimension_ref.key():d for d in result.value.dimensions}
        if profile.choice=='record_lesson': return complete(affected_dimension_refs=[d.dimension_ref for d in result.value.dimensions])
        if profile.choice!='revise_strategy' or profile.strategy_ref is None or profile.strategy_ref.key() not in keys(state.allowed_strategy_refs):
            _needs('original_allowed_future_lending_strategy')
        strategy=read(profile.strategy_ref,LendingStrategyView,linked=True)
        authorize(strategy.authority_ref,strategy.author_actor_id,strategy.author_function_ref,bank,strategy.originating_action_id,now,strategy.scope_ref)
        if strategy.lender_id!=bank or strategy.originating_action_id!='BANK-A12' or not scope_covers(scope,strategy.scope_ref):
            raise ValueError('Learned strategy changes original lender or future-only action/scope')
        for test in strategy.signal_tests:
            if test.observation_ref.key() not in keys(profile.source_refs): raise ValueError('Strategy introduces facts outside learned bank observations')
            evidence([test.threshold.basis_ref])
            observation=observations[test.observation_ref.key()]
            if not isinstance(observation.measure,Known): _needs('original_declared_strategy_signal_measure',[observation.ref])
            measure=observation.measure.value;evidence([measure.basis_ref])
            if measure.unit!=test.threshold.unit: _unsupported('bank-learning-strategy-signal-units')
            actual,threshold=decimal_fraction(measure.value),decimal_fraction(test.threshold.value)
            if (test.predicate=='at_most' and actual>threshold) or (test.predicate=='at_least' and actual<threshold):
                _needs('original_future_strategy_signal_condition',[observation.ref])
        rules=[];keys(method.policy_rule_refs)
        for ref in method.policy_rule_refs:
            rule=read(ref,BankLearningPolicyRuleView,linked=True);author(rule)
            if rule.strategy_ref!=strategy.ref: continue
            if (rule.lender_id!=bank or rule.author_organization_id!=bank or rule.learning_method_ref!=method.ref
                    or rule.strategy_sha256!=content_digest(strategy) or not true(rule.permitted) or rule.minimum_samples<1
                    or not 0<=decimal_fraction(rule.maximum_mean_squared_error)<=1):
                raise ValueError('Future strategy revision substitutes original authorized error policy')
            if rule.dimension_ref.key() not in errors: _needs('original_error_evidence_for_strategy_dimension',[rule.dimension_ref])
            error=errors[rule.dimension_ref.key()]
            if error.sample_count<rule.minimum_samples or error.mean_squared_error.fraction()>decimal_fraction(rule.maximum_mean_squared_error):
                _needs('declared_original_strategy_learning_evidence_threshold',[rule.ref])
            rules.append(rule)
        if not rules or {r.dimension_ref.key() for r in rules}!=set(errors): _needs('complete_original_future_strategy_learning_policy')
        return complete(strategy_ref=strategy.ref)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
