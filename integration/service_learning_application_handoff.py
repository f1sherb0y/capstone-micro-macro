"""Relate saved service judgment revisions to independently applied state."""
from copy import deepcopy

from src.actions.contracts.architect_learning_objects import (
    ArchitectLearningFeedbackView, ArchitectLearningStrategyView, ArchitectLearningStateView,
    ArchitectLearningDecisionView, ArchitectLearningAssessmentView, ArchitectLearningExecutionView,
)
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.qs_learning_objects import (
    QSLearningStrategyView, QSLearningStateView, QSLearningDecisionView,
    QSLearningAssessmentView, QSLearningExecutionView, QSReceivedOutcomeView, QSOriginalOutcomeFacts,
)
from src.actions.contracts.engineer_learning_objects import (
    EngineerLearningStrategyView, EngineerLearningStateView, EngineerLearningDecisionView,
    EngineerLearningAssessmentView, EngineerLearningExecutionView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest


def prepare_service_judgment_application_handoff(saved, *, invocation, execution_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current, action_id):
    """Inspect actual application; never write a strategy or recognize an error.

    Caller holds the actual source/authorization guard. validate_current must
    verify native application/event, private access and new-strategy authorship.
    This relation preserves old learning history and immutable forecasts; actual
    capability, training, external records and cash remain independent facts.
    """
    # Roles and concrete types are selected only by these fixed code routes.
    if action_id == 'QS-A12':
        from integration.qs_learning_results import SavedQSLearning
        saved_model, role = SavedQSLearning, 'QS'
        strategy_model, state_model, decision_model = QSLearningStrategyView, QSLearningStateView, QSLearningDecisionView
        assessment_model, execution_model = QSLearningAssessmentView, QSLearningExecutionView
        wait_code = 'query_original_qs_judgment_application'
    elif action_id == 'ARCHITECT-A12':
        from integration.architect_learning_results import SavedArchitectLearning
        saved_model, role = SavedArchitectLearning, 'Architect'
        strategy_model, state_model, decision_model = ArchitectLearningStrategyView, ArchitectLearningStateView, ArchitectLearningDecisionView
        assessment_model, execution_model = ArchitectLearningAssessmentView, ArchitectLearningExecutionView
        wait_code = 'query_original_architect_judgment_application'
    elif action_id == 'ENGINEER-A12':
        from integration.engineer_learning_results import SavedEngineerLearning
        saved_model, role = SavedEngineerLearning, 'Engineer'
        strategy_model, state_model, decision_model = EngineerLearningStrategyView, EngineerLearningStateView, EngineerLearningDecisionView
        assessment_model, execution_model = EngineerLearningAssessmentView, EngineerLearningExecutionView
        wait_code = 'query_original_engineer_judgment_application'
    else:
        raise TaskConflict('Judgment application requires a supported fixed action route')

    context,reading = invocation.context,invocation.reading
    if (not isinstance(saved,saved_model) or saved.current_context != context
            or saved.identity.action_id != action_id or saved.identity.role != role
            or saved.identity.run_id != context.run_id or saved.identity.organization_id != reading.organization_id
            or saved.result.kind != 'completed' or saved.result.payload.choice != 'update_judgment'
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or saved.audit.get('input_sha256') != saved.identity.input_sha256
            or saved.audit.get('result_sha256') != task_digest(saved.result.model_dump(mode='json'))
            or saved.audit.get('result_kind') != 'completed'
            or not callable(validate_current) or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Judgment application requires its original saved revision and current formal reading')
    reading.check_method_context(context,action_id)
    execution_ref = Reference.model_validate(execution_ref)
    native_evidence_ref = Reference.model_validate(native_evidence_ref)
    relation_evidence_refs = [Reference.model_validate(ref) for ref in relation_evidence_refs]
    unique_refs(relation_evidence_refs)
    if not relation_evidence_refs or native_evidence_ref in relation_evidence_refs:
        raise TaskConflict('Judgment application requires separate native and independent relation evidence')

    def read(ref,schema):
        row=reading.resolve(ref)
        if not isinstance(row,schema) or row.ref != ref:
            raise TaskConflict('Judgment application requires exact original concrete source versions')
        return row

    try:
        originals={Reference.model_validate(row['ref']).key():row['projection'] for row in saved.source_reading}
        strategy=strategy_model.model_validate(originals[saved.action_input.strategy_ref.key()])
        state=state_model.model_validate(originals[strategy.learning_state_ref.key()])
        decision=decision_model.model_validate(originals[strategy.decision_profile_ref.key()])
        execution=read(execution_ref,execution_model)
        current_strategy=read(invocation.action_input.strategy_ref,strategy_model)
        current_state=read(current_strategy.learning_state_ref,state_model)
        if (execution.run_id != context.run_id or execution.organization_id != reading.organization_id
                or execution.strategy_ref != strategy.ref or execution.decision_ref != decision.ref
                or execution.decision_sha256 != content_digest(decision) or execution.business_key != decision.business_key
                or execution.ref not in current_state.execution_refs):
            raise TaskConflict('Applied judgment execution substitutes the original run, strategy, decision or business identity')
        if execution.status != 'succeeded':
            return {'kind':'deferred','reason_code':wait_code,
                'resume_condition':{'trigger':'dependency_change','object_refs':[execution.ref],
                    'earliest_time':None,'condition_code':wait_code}}
        revision=saved.result.payload.revision
        unique_refs([row.dimension_ref for row in revision.changes])
        unique_refs([row.dimension_ref for row in current_strategy.judgments])
        expected={row.dimension_ref.key():row.selected_value_ref for row in strategy.judgments}
        expected.update({row.dimension_ref.key():row.selected_value_ref for row in revision.changes})
        actual={row.dimension_ref.key():row.selected_value_ref for row in current_strategy.judgments}
        if (revision.prior_strategy_ref != strategy.ref or current_strategy.ref == strategy.ref
                or current_strategy.ref.id != strategy.ref.id or type(current_strategy.ref.version) is not str
                or current_strategy.organization_id != reading.organization_id
                or current_strategy.author_organization_id != reading.organization_id
                or current_state.organization_id != reading.organization_id or current_state.strategy_ref != current_strategy.ref
                or current_state.capability_ref != state.capability_ref
                or current_state.learning_profile_ref != state.learning_profile_ref
                or revision.learning_profile_ref != state.learning_profile_ref or actual != expected
                or current_strategy.scope != strategy.scope or current_state.scope != state.scope
                or current_state.coverage != 'complete' or current_state.as_of != context.business_time):
            raise TaskConflict('Applied judgment changes unaffected dimensions, original private scope, profile or capability')
        history_fields = ('received_feedback_refs','applied_feedback_refs','execution_refs')
        if action_id == 'QS-A12':
            history_fields += ('forecast_refs','outcome_refs')
        elif action_id == 'ENGINEER-A12':
            history_fields += ('qualification_refs','applied_qualification_event_refs')
        for name in history_fields:
            unique_refs(getattr(state,name));unique_refs(getattr(current_state,name))
        if (not {ref.key() for ref in state.received_feedback_refs} <= {ref.key() for ref in current_state.received_feedback_refs}
                or not {ref.key() for ref in state.execution_refs} <= {ref.key() for ref in current_state.execution_refs}):
            raise TaskConflict('Applied judgment drops original received feedback or execution history')
        if action_id == 'QS-A12':
            for name in ('forecast_refs','outcome_refs'):
                if not {ref.key() for ref in getattr(state,name)} <= {ref.key() for ref in getattr(current_state,name)}:
                    raise TaskConflict('Applied judgment drops original immutable forecast or received outcome history')
        elif action_id == 'ENGINEER-A12':
            # Qualification changes require their independent issuer process;
            # this handoff proves only the saved private judgment application.
            for name in ('qualification_refs','applied_qualification_event_refs'):
                if {ref.key() for ref in getattr(state,name)} != {ref.key() for ref in getattr(current_state,name)}:
                    raise TaskConflict('Applied Engineer judgment changes independent qualification history')
            unique_refs(invocation.action_input.qualification_refs)
            if ({ref.key() for ref in invocation.action_input.qualification_refs}
                    != {ref.key() for ref in current_state.qualification_refs}):
                raise TaskConflict('Applied Engineer judgment substitutes current qualification inputs')
        assessment=assessment_model.model_validate(originals[decision.assessment_ref.key()])
        if assessment.report is None:
            raise TaskConflict('Applied judgment lacks the original saved assessment report')
        changed={row.dimension_ref.key() for row in revision.changes}
        used={ref.key() for selection in assessment.report.selections if selection.dimension_ref.key() in changed
            for ref in selection.feedback_refs}
        allowed={ref.key() for ref in saved.action_input.feedback_refs}
        applied={ref.key() for ref in state.applied_feedback_refs}
        if (not used or not used <= allowed or used & applied
                or {ref.key() for ref in current_state.applied_feedback_refs} != applied | used
                or not (applied | used) <= {ref.key() for ref in current_state.received_feedback_refs}):
            raise TaskConflict('Applied judgment repeats, omits or adds feedback outside its original changed-dimension assessment')
        events=set()
        for ref in current_state.applied_feedback_refs:
            feedback=read(ref,ArchitectLearningFeedbackView)
            if feedback.recipient_organization_id != reading.organization_id or feedback.event.event_key in events:
                raise TaskConflict('Applied judgment repeats a physical feedback event or borrows another private recipient')
            events.add(feedback.event.event_key)
        if action_id == 'QS-A12':
            pair_keys=set(state.applied_error_pair_keys)
            if len(pair_keys) != len(state.applied_error_pair_keys):
                raise TaskConflict('Original QS history repeats an applied error pair')
            if saved.action_input.forecast_refs or saved.action_input.outcome_refs:
                outcome=QSReceivedOutcomeView.model_validate(originals[decision.outcome_ref.key()])
                pair=content_digest(QSOriginalOutcomeFacts.model_validate({name:getattr(outcome,name)
                    for name in QSOriginalOutcomeFacts.model_fields}))
                if pair in pair_keys:
                    raise TaskConflict('Applied judgment repeats the original recognized forecast/outcome error pair')
                pair_keys.add(pair)
            if (len(set(current_state.applied_error_pair_keys)) != len(current_state.applied_error_pair_keys)
                    or set(current_state.applied_error_pair_keys) != pair_keys):
                raise TaskConflict('Applied judgment drops, duplicates or invents recognized error pairs')
        points=[saved.context.business_time,current_strategy.authored_at,
            current_strategy.available_at,context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left,right in zip(points,points[1:]))
                or not current_strategy.effective_window.contains(context.business_time)
                or not current_state.effective_window.contains(context.business_time)
                or execution.available_at.clock_ref != context.business_time.clock_ref
                or not saved.context.business_time.offset <= execution.available_at.offset <= context.business_time.offset
                or current_state.available_at.clock_ref != context.business_time.clock_ref
                or current_state.available_at.offset > context.business_time.offset):
            raise TaskConflict('Applied judgment changes native execution, strategy or current-state chronology')
        evidence=[]
        for ref in [native_evidence_ref,*relation_evidence_refs]:
            row=read(ref,EvidenceRecord)
            if (row.basis_kind != 'observed' or row.source_kind == 'synthetic'
                    or row.effective_window is not None and not row.effective_window.contains(context.business_time)):
                raise TaskConflict('Applied judgment requires current actual observed native and relation evidence')
            evidence.append(row.model_dump(mode='json'))
        if evidence[0]['content_hash'] != native_source_sha256:
            raise TaskConflict('Applied judgment changes native application source content')
        if validate_current(saved=deepcopy(saved),original_strategy=strategy.model_copy(deep=True),
                original_state=state.model_copy(deep=True),decision=decision.model_copy(deep=True),
                execution=execution.model_copy(deep=True),strategy=current_strategy.model_copy(deep=True),
                state=current_state.model_copy(deep=True),evidence=deepcopy(evidence),
                context=context.model_copy(deep=True),reading=reading) is not True:
            raise TaskConflict('Applied judgment requires actual native application, privacy and source-author verification')
        return {'kind':'prepared','source_mode':'formal','provenance':{
            'task_sha256':saved.identity.key,'record_sha256':saved.record_sha256,
            'source_reading_sha256':saved.source_reading_sha256,'decision_sha256':content_digest(decision),
            'execution_sha256':content_digest(execution),'strategy_sha256':content_digest(current_strategy),
            'state_sha256':content_digest(current_state),'native_source_sha256':native_source_sha256,
            'evidence_sha256':task_digest(evidence)}}
    finally:
        reading.recheck()
