"""Freeze original QS A12 private feedback, judgment and training sources."""
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import ClassVar

from integration.qs_market_actions import QSMarketActionAssembler, PreparedQSMarket
from src.actions.contracts.architect_learning_objects import (
    ArchitectLearningCapabilityView, ArchitectLearningFeedbackView, ArchitectLearningProfileView,
    ArchitectLearningValueView, ArchitectLearningRuleView, ArchitectTrainingProfileView,
    ArchitectTrainingWorkView, ArchitectTrainingEstimateView, ArchitectTrainingAuthorityView,
    ArchitectTrainingRequirementView, ArchitectTrainingDependencyView,
)
from src.actions.contracts.qs_learning_objects import (
    QSLearningStrategyView, QSLearningStateView, QSLearningDecisionView,
    QSExperienceDimensionView, QSLearningAssessmentView, QSLearningExecutionView,
    QSHistoricalCostPlanView, QSFrozenForecastView, QSForecastInformationView,
    QSReceivedOutcomeView, QSOutcomeAccessView, QSComparisonResultView,
    qs_learning_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class PreparedQSLearning(PreparedQSMarket):
    ACTION_ID: ClassVar[str] = 'QS-A12'


class QSLearningActionAssembler(QSMarketActionAssembler):
    """Preserve private feedback and explicit finite judgment/training declarations.

    Original processor checks event chronology/deduplication, selected rules,
    saved assessments and separately authorized training estimates/investment.
    Assembly rewrites no forecast and changes no strategy, capability, budget or schedule.
    """
    ACTION_ID = 'QS-A12'
    SOURCE_SCHEMAS = staticmethod(qs_learning_schemas)

    def build(self, context, *, scope, forecast_refs, outcome_refs, feedback_refs,
            comparability_result_ref, learning_profile_ref, strategy_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'strategy_ref': strategy_ref, 'forecast_refs': forecast_refs,
            'outcome_refs': outcome_refs, 'comparability_result_ref': comparability_result_ref,
            'feedback_refs': feedback_refs, 'learning_profile_ref': learning_profile_ref},
            prepared_type=PreparedQSLearning, validate_sources=validate_qs_learning_sources)

    def prepare_comparability(self, context, *, calculation_ref, author_authority_ref,
            validate_current, **source_refs):
        """Produce the report under the caller's actual source writer guard."""
        from integration.qs_learning_calculations import prepare_qs_forecast_comparability

        prepared = self.build(context, comparability_result_ref=None, **source_refs)
        return prepare_qs_forecast_comparability(context=prepared.context, action_input=prepared.action_input,
            reading=prepared.reading, calculation_ref=calculation_ref,
            author_authority_ref=author_authority_ref, validate_current=validate_current)

    def prepare_assessment(self, context, *, assessment_ref, author_authority_ref,
            validate_current, **source_refs):
        """Produce original finite-rule assessment under the caller's source writer guard."""
        from integration.qs_learning_assessments import prepare_qs_learning_assessment

        prepared=self.build(context,**source_refs)
        return prepare_qs_learning_assessment(context=prepared.context,action_input=prepared.action_input,
            reading=prepared.reading,assessment_ref=assessment_ref,
            author_authority_ref=author_authority_ref,validate_current=validate_current)

    def prepare_training_estimate(self, context, *, estimate_ref, author_authority_ref,
            validate_current, **source_refs):
        """Estimate original training work under the caller's actual source guard."""
        from integration.qs_training_estimates import prepare_qs_training_estimate

        prepared = self.build(context, **source_refs)
        return prepare_qs_training_estimate(context=prepared.context, action_input=prepared.action_input,
            reading=prepared.reading, estimate_ref=estimate_ref,
            author_authority_ref=author_authority_ref, validate_current=validate_current)

    def save_assessment(self, context, *, publications, read_guard,
            assessment_ref, author_authority_ref, validate_current, **source_refs):
        """Save the actual finite-rule report before explicit fresh-token publication."""
        from integration.qs_learning_assessment_publication import QSLearningAssessmentPublicationStore
        from integration.qs_learning_assessments import prepare_qs_learning_assessment

        if (not isinstance(publications,QSLearningAssessmentPublicationStore)
                or publications.registry is not self.registry or publications.organizations is not self.organizations
                or publications.methods is not self.methods or not callable(read_guard)):
            raise TaskConflict('Learning assessment save requires original registries and actual source writer guard')
        with read_guard(context):
            prepared=self.build(context,**source_refs)
            calculation=prepare_qs_learning_assessment(context=prepared.context,action_input=prepared.action_input,
                reading=prepared.reading,assessment_ref=assessment_ref,
                author_authority_ref=author_authority_ref,validate_current=validate_current)
            if calculation['kind']!='prepared':
                return calculation
            record=publications.save(calculation,context=prepared.context,action_input=prepared.action_input,reading=prepared.reading)
            return {'kind':'prepared','calculation':calculation,'record':record}

    def save_training_estimate(self, context, *, publications, read_guard,
            estimate_ref, author_authority_ref, validate_current, **source_refs):
        """Save the original work estimate before a separate publication call."""
        from integration.qs_training_estimate_publication import QSTrainingEstimatePublicationStore
        from integration.qs_training_estimates import prepare_qs_training_estimate

        if (not isinstance(publications,QSTrainingEstimatePublicationStore)
                or publications.registry is not self.registry or publications.organizations is not self.organizations
                or publications.methods is not self.methods or not callable(read_guard)
                or publications.store.run_id != self.organizations.run_id):
            raise TaskConflict('Training estimate save requires original registries, run and actual source guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            prepared = self.build(context,**source_refs)
            calculation = prepare_qs_training_estimate(context=prepared.context,action_input=prepared.action_input,
                reading=prepared.reading,estimate_ref=estimate_ref,
                author_authority_ref=author_authority_ref,validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation,context=prepared.context,
                action_input=prepared.action_input,reading=prepared.reading)
            return {'kind':'prepared','calculation':calculation,'record':record}

    def save_comparability(self, context, *, publications, read_guard,
            calculation_ref, author_authority_ref, validate_current, **source_refs):
        """Save the actual report before a separate explicit fresh-token publication."""
        from integration.qs_learning_calculation_publication import QSLearningComparabilityPublicationStore
        from integration.qs_learning_calculations import prepare_qs_forecast_comparability

        if (not isinstance(publications,QSLearningComparabilityPublicationStore)
                or publications.registry is not self.registry or publications.organizations is not self.organizations
                or publications.methods is not self.methods or not callable(read_guard)):
            raise TaskConflict('Comparison save requires original registries and actual source writer guard')
        with read_guard(context):
            prepared = self.build(context,comparability_result_ref=None,**source_refs)
            calculation = prepare_qs_forecast_comparability(context=prepared.context,action_input=prepared.action_input,
                reading=prepared.reading,calculation_ref=calculation_ref,
                author_authority_ref=author_authority_ref,validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation,context=prepared.context,
                action_input=prepared.action_input,reading=prepared.reading)
            return {'kind':'prepared','calculation':calculation,'record':record}

    def build_from_applied_judgment(self, context, *, learning_submission, learning_identity,
            learning_execution_versions, execution_ref, native_evidence_ref, native_source_sha256,
            relation_evidence_refs, read_guard, validate_history, validate_current,
            validate_receipt_relation, **source_refs):
        """Freeze the actual successor strategy/state without applying learning again."""
        from integration.qs_submission import QSResultSubmission
        from integration.qs_learning_results import QSLearningResultWorker
        from integration.qs_learning_application_handoff import prepare_qs_judgment_application_handoff

        if (not isinstance(learning_submission,QSResultSubmission) or learning_submission.ACTION_ID != self.ACTION_ID
                or not isinstance(learning_submission.worker,QSLearningResultWorker)
                or learning_submission.worker.registry is not self.registry
                or learning_submission.worker.store.run_id != self.organizations.run_id
                or self.source_mode != 'formal' or not all(callable(callback) for callback in
                    (read_guard,validate_history,validate_current,validate_receipt_relation))):
            raise TaskConflict('Judgment application linkage requires original QS binding and actual guarded source checks')
        context=self._context(context)
        with read_guard(context.model_copy(deep=True)):
            receipt=learning_submission.read_receipt(learning_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected judgment registration cannot prove an actual applied strategy')
            invocation=self.build(context,**source_refs)
            saved=learning_submission.worker.read_completed(learning_identity,current_context=invocation.context,
                reading=invocation.reading,execution_versions=learning_execution_versions,validate_current=validate_history)

            def validate_link(**sources):
                if (sources['saved'].identity.as_dict() != receipt['identity']
                        or sources['saved'].record_sha256 != receipt['record_sha256']):
                    raise TaskConflict('Judgment application receipt substitutes original task or result')
                return (validate_current(**sources) is True
                    and validate_receipt_relation(receipt=deepcopy(receipt),**sources) is True)

            handoff=prepare_qs_judgment_application_handoff(saved,invocation=invocation,
                execution_ref=execution_ref,native_evidence_ref=native_evidence_ref,
                native_source_sha256=native_source_sha256,relation_evidence_refs=relation_evidence_refs,
                validate_current=validate_link)
            if handoff['kind'] != 'prepared':
                return handoff
            if learning_submission.read_receipt(learning_identity) != receipt:
                raise TaskConflict('Original judgment registration receipt changed during applied-strategy linkage')
            invocation.reading.recheck()
            return {**handoff,'provenance':{**handoff['provenance'],'submission':deepcopy(receipt)},
                'invocation':replace(invocation,reading_sha256=task_digest(invocation.reading.evidence()))}

    def build_from_training_task(self, context, *, learning_submission, learning_identity,
            learning_execution_versions, training_task_ref, native_evidence_ref, native_source_sha256,
            relation_evidence_refs, read_guard, validate_history, validate_current,
            validate_receipt_relation, **source_refs):
        """Freeze the actual registered task without starting training or applying effects."""
        from integration.qs_submission import QSResultSubmission
        from integration.qs_learning_results import QSLearningResultWorker
        from integration.qs_training_task_handoff import prepare_qs_training_task_handoff

        if (not isinstance(learning_submission,QSResultSubmission) or learning_submission.ACTION_ID != self.ACTION_ID
                or not isinstance(learning_submission.worker,QSLearningResultWorker)
                or learning_submission.worker.registry is not self.registry
                or learning_submission.worker.store.run_id != self.organizations.run_id or self.source_mode != 'formal'
                or not all(callable(callback) for callback in
                    (read_guard,validate_history,validate_current,validate_receipt_relation))):
            raise TaskConflict('Training task linkage requires original QS binding and actual guarded source checks')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            receipt = learning_submission.read_receipt(learning_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected training proposal cannot prove native task registration')
            invocation = self.build(context,**source_refs)
            saved = learning_submission.worker.read_completed(learning_identity,current_context=invocation.context,
                reading=invocation.reading,execution_versions=learning_execution_versions,validate_current=validate_history)

            def validate_link(**sources):
                if (sources['saved'].identity.as_dict() != receipt['identity']
                        or sources['saved'].record_sha256 != receipt['record_sha256']):
                    raise TaskConflict('Training task receipt substitutes its original proposal result')
                return (validate_current(**sources) is True
                    and validate_receipt_relation(receipt=deepcopy(receipt),**sources) is True)

            handoff = prepare_qs_training_task_handoff(saved,invocation=invocation,
                training_task_ref=training_task_ref,native_evidence_ref=native_evidence_ref,
                native_source_sha256=native_source_sha256,relation_evidence_refs=relation_evidence_refs,
                validate_current=validate_link)
            if handoff['kind'] != 'prepared':
                return handoff
            if learning_submission.read_receipt(learning_identity) != receipt:
                raise TaskConflict('Original training registration receipt changed during native task linkage')
            invocation.reading.recheck()
            return {**handoff,'provenance':{**handoff['provenance'],'submission':deepcopy(receipt)},
                'invocation':replace(invocation,reading_sha256=task_digest(invocation.reading.evidence()))}

    def prepare_error(self, context, *, calculation_ref, author_authority_ref,
            validate_current, **source_refs):
        """Consume the original comparison under the caller's actual source writer guard."""
        from integration.qs_learning_calculations import prepare_qs_forecast_error

        prepared = self.build(context, **source_refs)
        return prepare_qs_forecast_error(context=prepared.context,action_input=prepared.action_input,
            reading=prepared.reading,calculation_ref=calculation_ref,
            author_authority_ref=author_authority_ref,validate_current=validate_current)

    def save_error(self, context, *, publications, read_guard,
            calculation_ref, author_authority_ref, validate_current, **source_refs):
        """Persist one error with its original comparison before explicit publication."""
        from integration.qs_learning_error_publication import QSLearningErrorPublicationStore
        from integration.qs_learning_calculations import prepare_qs_forecast_error

        if (not isinstance(publications,QSLearningErrorPublicationStore)
                or publications.registry is not self.registry or publications.organizations is not self.organizations
                or publications.methods is not self.methods or not callable(read_guard)):
            raise TaskConflict('Error save requires original registries and actual source writer guard')
        with read_guard(context):
            prepared = self.build(context,**source_refs)
            calculation = prepare_qs_forecast_error(context=prepared.context,action_input=prepared.action_input,
                reading=prepared.reading,calculation_ref=calculation_ref,
                author_authority_ref=author_authority_ref,validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation,context=prepared.context,
                action_input=prepared.action_input,reading=prepared.reading)
            return {'kind':'prepared','calculation':calculation,'record':record}


def validate_qs_learning_sources(action_input, *, context, organization_id, sources):
    """Check original private identities without interpreting feedback or training."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('QS learning lacks its exact original concrete source')
        return row

    def own(row):
        if (row.organization_id != organization_id
                or hasattr(row, 'author_organization_id') and row.author_organization_id != organization_id):
            raise TaskConflict('QS learning source changes its original private firm or author')
        return row

    def feedback(ref):
        row = read(ref, ArchitectLearningFeedbackView)
        if row.recipient_organization_id != organization_id:
            raise TaskConflict('QS learning uses another firm private feedback')
        unique_refs([outcome.dimension_ref for outcome in row.event.outcomes])
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('QS learning changes its original invocation scope')
    strategy = own(read(action_input.strategy_ref, QSLearningStrategyView))
    unique_refs(action_input.feedback_refs)
    unique_refs([change.dimension_ref for change in strategy.judgments])
    for ref in action_input.feedback_refs:
        feedback(ref)
    state = None
    if strategy.learning_state_ref.key() in sources:
        state = own(read(strategy.learning_state_ref, QSLearningStateView))
        if state.strategy_ref.key() != strategy.ref.key() or state.scope != context.scope:
            raise TaskConflict('QS learning state changes its original strategy, capability or scope')
        if state.capability_ref.key() in sources:
            capability = own(read(state.capability_ref, ArchitectLearningCapabilityView))
            unique_refs(capability.qualification_refs)
        for refs in (state.received_feedback_refs, state.applied_feedback_refs, state.execution_refs):
            unique_refs(refs)
        for ref in state.applied_feedback_refs:
            if ref.key() in sources:
                feedback(ref)
        for ref in state.execution_refs:
            if ref.key() in sources:
                execution = own(read(ref, QSLearningExecutionView))
                if execution.run_id != context.run_id or execution.strategy_ref.id != strategy.ref.id:
                    raise TaskConflict('QS learning execution history changes its original run or strategy')
    decision = None
    if strategy.decision_profile_ref.key() in sources:
        decision = own(read(strategy.decision_profile_ref, QSLearningDecisionView))
        if (decision.strategy_ref.key() != strategy.ref.key() or decision.actor_id != context.actor_id
                or decision.function_ref.key() != context.function_ref.key() or decision.scope != context.scope):
            raise TaskConflict('QS learning decision changes its original strategy, actor, function or scope')
        unique_refs(decision.feedback_refs)
        if state is not None:
            for ref in state.execution_refs:
                execution = sources.get(ref.key())
                if execution is not None and execution.business_key == decision.business_key:
                    original = sources.get(execution.decision_ref.key())
                    if original is not None and (not isinstance(original, QSLearningDecisionView)
                            or original.strategy_ref != execution.strategy_ref
                            or original.organization_id != execution.organization_id or original.scope != execution.scope
                            or original.business_key != execution.business_key):
                        raise TaskConflict('QS learning execution substitutes its original decision or strategy version')
    # QS forecasts and actual outcomes retain independent original identities.
    unique_refs(action_input.forecast_refs)
    unique_refs(action_input.outcome_refs)
    forecasts = {}
    for ref in action_input.forecast_refs:
        forecast = own(read(ref, QSHistoricalCostPlanView))
        forecasts[ref.key()] = forecast
        unique_refs(forecast.information_refs)
        if forecast.immutable_source_ref.key() in sources:
            frozen = own(read(forecast.immutable_source_ref, QSFrozenForecastView))
            if frozen.forecast_ref != forecast.ref or frozen.forecast_key != forecast.forecast_key:
                raise TaskConflict('QS frozen forecast substitutes its original prediction identity')
        for information_ref in forecast.information_refs:
            if information_ref.key() in sources:
                information = own(read(information_ref, QSForecastInformationView))
                if information.forecast_ref != forecast.ref:
                    raise TaskConflict('QS forecast information substitutes another original prediction')
    for ref in action_input.outcome_refs:
        outcome = read(ref, QSReceivedOutcomeView)
        if (outcome.recipient_organization_id != organization_id
                or outcome.author_organization_id != outcome.provider_organization_id):
            raise TaskConflict('QS learning outcome substitutes its original recipient or provider')
        forecast = forecasts.get(outcome.forecast_ref.key())
        if forecast is not None and outcome.forecast_key != forecast.forecast_key:
            raise TaskConflict('QS outcome substitutes its original forecast identity')
        if outcome.access_basis_ref.key() in sources:
            access = read(outcome.access_basis_ref, QSOutcomeAccessView)
            if (access.outcome_ref != outcome.ref or access.provider_organization_id != outcome.provider_organization_id
                    or access.author_organization_id != outcome.provider_organization_id
                    or access.recipient_organization_id != organization_id):
                raise TaskConflict('QS outcome access substitutes its original outcome, provider or recipient')
    if state is not None:
        unique_refs(state.forecast_refs)
        unique_refs(state.outcome_refs)
    if action_input.comparability_result_ref is not None:
        own(read(action_input.comparability_result_ref, QSComparisonResultView))
    if decision is not None and decision.error_result_ref is not None and decision.error_result_ref.key() in sources:
        own(read(decision.error_result_ref, QSComparisonResultView))
    # Original forecast/source hashes and chronology, complete histories, mature
    # actual outcomes, comparable pairs and error arithmetic stay in the processor.
    if action_input.learning_profile_ref is None:
        return
    profile = own(read(action_input.learning_profile_ref, ArchitectLearningProfileView))
    if profile.strategy_ref.key() != strategy.ref.key():
        raise TaskConflict('QS learning profile changes its original strategy')
    if state is not None and state.learning_profile_ref != profile.ref:
        raise TaskConflict('QS learning changes its original selected profile')
    for refs in (profile.dimension_refs, profile.rule_refs, profile.training_profile_refs):
        unique_refs(refs)
    for ref in profile.dimension_refs:
        if ref.key() in sources:
            dimension = own(read(ref, QSExperienceDimensionView))
            if dimension.learning_profile_ref.key() != profile.ref.key():
                raise TaskConflict('QS judgment dimension changes its original learning profile')
            unique_refs(dimension.value_refs)
            for value_ref in dimension.value_refs:
                if value_ref.key() in sources:
                    value = own(read(value_ref, ArchitectLearningValueView))
                    if value.dimension_ref.key() != dimension.ref.key():
                        raise TaskConflict('QS judgment value changes its original dimension')
    for ref in profile.rule_refs:
        if ref.key() in sources:
            rule = own(read(ref, ArchitectLearningRuleView))
            if rule.learning_profile_ref.key() != profile.ref.key() or rule.rule.rule_ref.key() != rule.ref.key():
                raise TaskConflict('QS learning rule changes its original profile or rule identity')
    if decision is None:
        return
    if decision.assessment_ref is not None and decision.assessment_ref.key() in sources:
        assessment = own(read(decision.assessment_ref, QSLearningAssessmentView))
        if assessment.strategy_ref.key() != strategy.ref.key() or assessment.learning_profile_ref.key() != profile.ref.key():
            raise TaskConflict('QS learning assessment changes its original strategy or profile')
    if decision.training_profile_ref is None or decision.training_profile_ref.key() not in sources:
        return
    training = own(read(decision.training_profile_ref, ArchitectTrainingProfileView))
    request = training.request
    for refs in (request.input_refs, request.output_requirement_refs, request.authority_basis_refs, request.dependency_refs):
        unique_refs(refs)
    if training.authority_ref.key() in sources:
        authority = own(read(training.authority_ref, ArchitectTrainingAuthorityView))
        unique_refs(authority.allowed_input_refs)
        unique_refs(authority.allowed_output_requirement_refs)
    if request.work_profile_ref is not None and request.work_profile_ref.key() in sources:
        work = own(read(request.work_profile_ref, ArchitectTrainingWorkView))
        if work.data.work_profile_ref.key() != work.ref.key():
            raise TaskConflict('QS training work data changes its original work profile')
        if training.estimate_ref.key() in sources:
            estimate = own(read(training.estimate_ref, ArchitectTrainingEstimateView))
            if estimate.work_profile_ref.key() != work.ref.key():
                raise TaskConflict('QS training estimate changes its original work profile')
    for ref in request.output_requirement_refs:
        if ref.key() in sources:
            requirement = own(read(ref, ArchitectTrainingRequirementView))
            if requirement.training_profile_ref.key() != training.ref.key():
                raise TaskConflict('QS training output changes its original training profile')
    for ref in request.dependency_refs:
        if ref.key() in sources:
            dependency = read(ref, ArchitectTrainingDependencyView)
            if dependency.training_profile_ref.key() != training.ref.key():
                raise TaskConflict('QS training dependency changes its original training profile')
