"""QS-A12 preserves original predictions and independently compares received outcomes."""
from src.actions.contracts.common import Known, StrictRecord
from src.actions.contracts.qs_learning_objects import (
    qs_learning_types, QSHistoricalCostPlanView, QSForecastInformationView, QSReceivedOutcomeView,
    QSOutcomeAccessView, QSComparisonResultView, QSOriginalOutcomeFacts, QSFrozenForecastView,
    QSExperienceDimensionView,
)
from src.actions.contracts.architect_learning_objects import ArchitectLearningFeedbackView, ArchitectLearningProfileView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.actions.roles.service_learning import update_service_experience
from src.methods.qs_learning import COMPARABILITY_METHOD, ERROR_METHOD, QSForecastComparisonInput, compare_original_forecast


def prepare_qs_forecast_comparison_input(context, action_input, reading):
    """Validate original forecast/outcome sources without requiring a future report."""
    return _learn_qs_cost_experience(context, action_input, reading, prepare_comparison=True)


def prepare_qs_forecast_error_input(context, action_input, reading):
    """Consume the original comparison without invoking its method again."""
    return _learn_qs_cost_experience(context, action_input, reading, prepare_error=True)


def prepare_qs_learning_assessment_input(context, action_input, reading):
    """Build original finite feedback/rule input without replaying stored cost methods."""
    return _learn_qs_cost_experience(context,action_input,reading,prepare_assessment=True)


def prepare_qs_training_estimate_input(context, action_input, reading):
    """Prepare sourced training work without reading its future estimate."""
    return _learn_qs_cost_experience(context,action_input,reading,prepare_training=True)


def learn_qs_cost_experience(context, action_input, reading):
    return _learn_qs_cost_experience(context, action_input, reading)


def _learn_qs_cost_experience(context, action_input, reading, *, prepare_comparison=False, prepare_error=False,
        prepare_assessment=False, prepare_training=False):
    now,org=context.business_time,reading.organization_id
    dependencies={}

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def true(value): return isinstance(value,Known) and value.value is True

    def analyze(state,decision,strategy,capability,read,author,evidence,clock,complete,wait):
        if keys(action_input.forecast_refs)!=keys(state.forecast_refs) or keys(action_input.outcome_refs)!=keys(state.outcome_refs):
            _needs('complete_original_received_qs_forecast_outcome_history')
        forecasts={};physical=set()
        for ref in action_input.forecast_refs:
            forecast=read(ref,QSHistoricalCostPlanView,historic=True,linked=True);author(forecast,own=True);clock(forecast.frozen_at)
            if (forecast.organization_id!=org or forecast.forecast_key in physical or forecast.frozen_at.offset>forecast.authored_at.offset
                    or not forecast.information_refs):
                raise ValueError('Cost learning substitutes immutable original prediction or information set')
            physical.add(forecast.forecast_key)
            source=read(forecast.immutable_source_ref,QSFrozenForecastView,historic=True,linked=True);author(source,own=True)
            if (content_digest(source)!=forecast.immutable_source_sha256 or source.forecast_ref!=forecast.ref
                    or any(getattr(source,name)!=getattr(forecast,name) for name in
                        ['organization_id','forecast_key','information_refs','comparison_basis','predicted_total','frozen_at'])):
                raise ValueError('Cost learning rewrites original forecast content')
            if source.available_at.offset>forecast.frozen_at.offset:
                raise ValueError('Original forecast cannot include later received forecast source')
            keys(forecast.information_refs)
            for ref in forecast.information_refs:
                information=read(ref,QSForecastInformationView,historic=True,linked=True);author(information,own=True);clock(information.received_at)
                if (information.organization_id!=org or information.forecast_ref!=forecast.ref
                        or information.available_at.offset>information.received_at.offset
                        or information.received_at.offset>forecast.frozen_at.offset):
                    raise ValueError('Cost learning injects posterior information into original forecast')
                original=read(information.original_source_ref,StrictRecord,historic=True,linked=True)
                if content_digest(original)!=information.original_source_sha256:
                    raise ValueError('Forecast information changes original source version/content')
                if hasattr(original,'available_at') and original.available_at.offset>information.received_at.offset:
                    raise ValueError('Forecast information precedes receipt of its original source')
            if isinstance(forecast.predicted_total,Known): evidence([forecast.predicted_total.value.basis_ref])
            forecasts[forecast.ref.key()]=forecast
        outcomes={};events={}
        for ref in action_input.outcome_refs:
            outcome=read(ref,QSReceivedOutcomeView,historic=True,linked=True);author(outcome)
            clock(outcome.received_at);clock(outcome.occurred_at)
            if outcome.recipient_organization_id!=org or outcome.author_organization_id!=outcome.provider_organization_id:
                raise ValueError('Cost learning consumes another recipient private outcome or substitutes its provider')
            if outcome.received_at.offset>now.offset: _needs('actually_received_qs_cost_outcome',[ref])
            if outcome.occurred_at.offset>outcome.authored_at.offset or outcome.available_at.offset>outcome.received_at.offset:
                raise ValueError('Cost outcome changes original event/knowledge chronology')
            forecast=forecasts.get(outcome.forecast_ref.key())
            if (forecast is None or outcome.forecast_key!=forecast.forecast_key or outcome.forecast_sha256!=content_digest(forecast)
                    or outcome.occurred_at.offset<forecast.frozen_at.offset):
                raise ValueError('Cost outcome substitutes original forecast or predates its actual prediction')
            access=read(outcome.access_basis_ref,QSOutcomeAccessView,linked=True);author(access)
            if (access.outcome_ref!=outcome.ref or access.provider_organization_id!=outcome.provider_organization_id
                    or access.author_organization_id!=outcome.provider_organization_id
                    or access.recipient_organization_id!=org or not true(access.permitted)):
                _needs('original_lawful_qs_actual_cost_access',[access.ref])
            identity=(outcome.provider_organization_id,outcome.event_key)
            facts=QSOriginalOutcomeFacts.model_validate({name:getattr(outcome,name) for name in QSOriginalOutcomeFacts.model_fields})
            digest=content_digest(facts)
            if identity in events and events[identity]!=digest:
                raise ValueError('Cost outcome repeats physical event with changed original content')
            events[identity]=digest;outcomes[outcome.ref.key()]=outcome
            if isinstance(outcome.actual_total,Known): evidence([outcome.actual_total.value.basis_ref])
        if decision.choice not in {'analyze_error','update_judgment'}:
            if prepare_comparison or prepare_error: _needs('original_qs_forecast_analysis_or_judgment_decision')
            return None
        cost_feedback=[]
        if decision.choice=='update_judgment' and action_input.learning_profile_ref is not None:
            profile=read(action_input.learning_profile_ref,ArchitectLearningProfileView);author(profile,own=True)
            dimensions=keys(profile.dimension_refs)
            for ref in action_input.feedback_refs:
                feedback=read(ref,ArchitectLearningFeedbackView,historic=True,linked=True)
                protected=feedback.event.subject_ref.kind in {'CostPlan','Outcome','MethodResult'}
                for result in feedback.event.outcomes:
                    if result.dimension_ref.key() not in dimensions:
                        continue
                    dimension=read(result.dimension_ref,QSExperienceDimensionView);author(dimension,own=True)
                    if dimension.organization_id!=org or dimension.learning_profile_ref!=profile.ref:
                        raise ValueError('QS cost feedback substitutes the original private learning dimension')
                    if dimension.purpose in {'estimation_assumptions','cost_experience'}:
                        protected=True
                if protected:
                    cost_feedback.append(feedback)
        if decision.choice=='update_judgment' and not forecasts and not outcomes:
            if prepare_comparison or prepare_error: _needs('original_qs_forecast_outcome_pair')
            if cost_feedback:
                _needs('original_comparable_qs_cost_error_before_forecast_judgment',
                    [row.event.subject_ref for row in cost_feedback])
            return None
        if (decision.forecast_ref is None or decision.outcome_ref is None
                or decision.forecast_ref.key() not in forecasts or decision.outcome_ref.key() not in outcomes):
            _needs('original_selected_qs_forecast_and_received_outcome_pair')
        forecast=forecasts[decision.forecast_ref.key()];outcome=outcomes[decision.outcome_ref.key()]
        if outcome.forecast_ref!=forecast.ref: raise ValueError('Cost analysis substitutes selected original forecast/outcome pair')
        if outcome.status!='verified' or not true(outcome.verified): _needs('mature_verified_original_qs_cost_outcome',[outcome.ref])
        data=QSForecastComparisonInput(forecast_ref=forecast.ref,outcome_ref=outcome.ref,
            forecast_basis=forecast.comparison_basis,outcome_basis=outcome.comparison_basis,
            forecast_total=forecast.predicted_total,outcome_total=outcome.actual_total,
            source_refs=[forecast.ref,outcome.ref,outcome.access_basis_ref,*forecast.information_refs])
        if prepare_comparison:
            reading.recheck()
            return {'kind':'prepared','input':data}
        if action_input.comparability_result_ref is None: _needs('independently_saved_qs_cost_comparability_result')

        def saved_result(ref,method,*,verify_method=True):
            saved=read(ref,QSComparisonResultView,linked=True);author(saved,own=True);clock(saved.executed_at)
            if (saved.organization_id!=org or saved.method_ref!=method or saved.data!=data
                    or saved.input_sha256!=content_digest(data) or saved.executed_at.offset>saved.authored_at.offset
                    or saved.executed_at.offset<outcome.received_at.offset):
                raise ValueError('QS comparison/error report changes original pair, input or received execution chronology')
            if saved.status=='unsupported': _unsupported('qs-cost-learning-method-domain')
            if saved.status!='ok' or saved.report is None: _needs('successful_original_qs_cost_comparison_or_error',[ref])
            if not verify_method:
                if saved.report!=compare_original_forecast(data):
                    raise ValueError('Saved comparison differs from its original declared exact cost bases')
                return saved
            result=reading.calculate(method,data)
            if result.kind!='ok':
                if result.kind=='invalid_input': _unsupported('qs-cost-learning-method-domain')
                raw=result.model_dump(mode='python')
                if result.kind=='needs_information': raw['requested_refs']=[]
                raise ObservationGap(raw)
            if result.value!=saved.report: raise ValueError('QS comparison/error differs from exact original basis calculation')
            return saved

        comparison=saved_result(action_input.comparability_result_ref,COMPARABILITY_METHOD,
            verify_method=not (prepare_error or prepare_assessment))
        if not comparison.report.comparable: _unsupported('original_qs_forecast_outcome_not_comparable')
        if comparison.report.status!='comparable': _needs('known_original_qs_forecast_outcome_amounts')
        if prepare_error:
            # Preserve a predeclared result reference for same-version report
            # consumption. The producer/store must match it without reading
            # the future error report as an input.
            pair_key=content_digest(QSOriginalOutcomeFacts.model_validate({name:getattr(outcome,name) for name in QSOriginalOutcomeFacts.model_fields}))
            if len(set(state.applied_error_pair_keys))!=len(state.applied_error_pair_keys):
                raise ValueError('QS history repeats applied original error pair')
            if pair_key in state.applied_error_pair_keys:
                return wait(state.ref,'original_qs_cost_error_already_applied')
            reading.recheck()
            return {'kind':'prepared','input':data,'comparison_dependency':comparison,
                'error_result_ref':decision.error_result_ref}
        if decision.error_result_ref is None: _needs('saved_original_comparable_qs_forecast_error')
        error=saved_result(decision.error_result_ref,ERROR_METHOD,verify_method=not prepare_assessment)
        if error.report!=comparison.report: raise ValueError('QS error changes independently established original comparison')
        pair_key=content_digest(QSOriginalOutcomeFacts.model_validate({name:getattr(outcome,name) for name in QSOriginalOutcomeFacts.model_fields}))
        if len(set(state.applied_error_pair_keys))!=len(state.applied_error_pair_keys): raise ValueError('QS history repeats applied original error pair')
        if pair_key in state.applied_error_pair_keys: return wait(state.ref,'original_qs_cost_error_already_applied')
        if decision.choice=='analyze_error':
            return complete(forecast_ref=forecast.ref,outcome_ref=outcome.ref,error_result_ref=error.ref)
        for feedback in cost_feedback:
            if (feedback.event.subject_ref!=error.ref or feedback.event.subject_sha256!=content_digest(error)):
                raise ValueError('QS cost judgment samples must each use the original comparable error, not unrelated feedback')
        matching=False
        for ref in action_input.feedback_refs:
            feedback=read(ref,ArchitectLearningFeedbackView,historic=True,linked=True)
            if feedback.event.subject_ref.key()==error.ref.key():
                if feedback.event.subject_sha256!=content_digest(error): raise ValueError('QS judgment feedback changes original saved error content')
                matching=True
            elif feedback.event.subject_ref.kind in {'CostPlan','Outcome','MethodResult'}:
                raise ValueError('QS forecast judgment must use the independently comparable saved error, not raw posterior cost')
        if not matching: _needs('verified_qs_feedback_on_original_comparable_error',[error.ref])
        if prepare_assessment:
            dependencies.update(comparison_dependency=comparison,error_dependency=error)
        return None

    result=update_service_experience(context,action_input,reading,action_id='QS-A12',learning_types=qs_learning_types(),
        capability_from_state=True,additional_action=analyze,prepare_assessment=prepare_assessment,
        prepare_training=prepare_training)
    if prepare_assessment and result['kind']=='prepared':
        return {**result,'dependencies':dependencies}
    return result
