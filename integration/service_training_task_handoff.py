"""Relate saved service training proposals to independently registered tasks."""
from copy import deepcopy

from src.actions.contracts.architect_learning_objects import (
    ArchitectTrainingProfileView, ArchitectLearningStrategyView, ArchitectLearningDecisionView, ArchitectTrainingTaskView,
)
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_learning_objects import QSLearningStrategyView, QSLearningDecisionView, QSTrainingTaskView
from src.actions.contracts.engineer_learning_objects import (
    EngineerLearningStrategyView, EngineerLearningDecisionView, EngineerTrainingTaskView,
)
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest


def prepare_service_training_task_handoff(saved, *, invocation, training_task_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current, action_id):
    """Inspect actual task registration; never start training or improve capability.

    Caller holds the actual source/authorization guard. Native task registration
    and independent relation evidence must identify the original saved proposal.
    The host gate checks native authorship, private access and actual registration.
    Execution state is retained as supplied, without inferring investment,
    completed deliverables, independent evaluation or capability effects.
    """
    if action_id == 'QS-A12':
        from integration.qs_learning_results import SavedQSLearning
        saved_model, role = SavedQSLearning, 'QS'
        strategy_model, decision_model, task_model = QSLearningStrategyView, QSLearningDecisionView, QSTrainingTaskView
        wait_code = 'query_original_qs_training_task_registration'
    elif action_id == 'ARCHITECT-A12':
        from integration.architect_learning_results import SavedArchitectLearning
        saved_model, role = SavedArchitectLearning, 'Architect'
        strategy_model, decision_model, task_model = ArchitectLearningStrategyView, ArchitectLearningDecisionView, ArchitectTrainingTaskView
        wait_code = 'query_original_architect_training_task_registration'
    elif action_id == 'ENGINEER-A12':
        from integration.engineer_learning_results import SavedEngineerLearning
        saved_model, role = SavedEngineerLearning, 'Engineer'
        strategy_model, decision_model, task_model = EngineerLearningStrategyView, EngineerLearningDecisionView, EngineerTrainingTaskView
        wait_code = 'query_original_engineer_training_task_registration'
    else:
        raise TaskConflict('Training task handoff requires a supported fixed action route')

    context, reading = invocation.context, invocation.reading
    if (not isinstance(saved,saved_model) or saved.current_context != context
            or saved.identity.action_id != action_id or saved.identity.role != role
            or saved.identity.run_id != context.run_id or saved.identity.organization_id != reading.organization_id
            or saved.result.kind != 'completed' or saved.result.payload.choice != 'propose_training'
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or saved.audit.get('input_sha256') != saved.identity.input_sha256
            or saved.audit.get('result_sha256') != task_digest(saved.result.model_dump(mode='json'))
            or saved.audit.get('result_kind') != 'completed' or not callable(validate_current)
            or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Training task handoff requires original saved proposal and actual formal reading')
    reading.check_method_context(context,action_id)
    task_ref = Reference.model_validate(training_task_ref)
    native_ref = Reference.model_validate(native_evidence_ref)
    relation_refs = [Reference.model_validate(ref) for ref in relation_evidence_refs]
    unique_refs(relation_refs)
    if not relation_refs or native_ref in relation_refs:
        raise TaskConflict('Training task handoff needs separate native and independent relation evidence')
    try:
        sources = {Reference.model_validate(row['ref']).key():row['projection'] for row in saved.source_reading}
        strategy = strategy_model.model_validate(sources[saved.action_input.strategy_ref.key()])
        decision = decision_model.model_validate(sources[strategy.decision_profile_ref.key()])
        training = ArchitectTrainingProfileView.model_validate(sources[decision.training_profile_ref.key()])
        task = reading.resolve(task_ref)
        if (not isinstance(task,task_model) or task.ref != task_ref
                or task.run_id != context.run_id or task.organization_id != reading.organization_id
                or task.task_sha256 != saved.identity.key or task.record_sha256 != saved.record_sha256
                or task.decision_ref != decision.ref or task.decision_sha256 != content_digest(decision)
                or task.business_key != decision.business_key or task.training_profile_ref != training.ref
                or task.estimate_ref != training.estimate_ref
                or task.request.model_dump(mode='json') != saved.result.payload.request.model_dump(mode='json')
                or task.request != training.request or task.scope != saved.context.scope
                or saved.result.payload.learning_profile_ref != training.learning_profile_ref):
            raise TaskConflict('Training task substitutes original proposal, request, decision, work estimate or private scope')
        points = [saved.context.business_time,task.authored_at,task.available_at,context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left,right in zip(points,points[1:]))
                or not task.effective_window.contains(context.business_time)):
            raise TaskConflict('Training task changes original proposal, registration or receipt chronology')
        if task.registration_status != 'registered':
            return {'kind':'deferred','reason_code':wait_code,
                'resume_condition':{'trigger':'dependency_change','object_refs':[task.ref],
                    'earliest_time':None,'condition_code':wait_code}}
        evidence = []
        for ref in [native_ref,*relation_refs]:
            row = reading.resolve(ref)
            if (not isinstance(row,EvidenceRecord) or row.ref != ref or row.basis_kind != 'observed'
                    or row.source_kind == 'synthetic'
                    or row.effective_window is not None and not row.effective_window.contains(context.business_time)):
                raise TaskConflict('Training task requires current observed native and independent relation evidence')
            evidence.append(row.model_dump(mode='json'))
        if evidence[0]['content_hash'] != native_source_sha256:
            raise TaskConflict('Training task changes its actual native registration source')
        if validate_current(saved=deepcopy(saved),decision=decision.model_copy(deep=True),
                training=training.model_copy(deep=True),task=task.model_copy(deep=True),evidence=deepcopy(evidence),
                context=context.model_copy(deep=True),reading=reading) is not True:
            raise TaskConflict('Training task requires independent actual native relation, privacy and author verification')
        return {'kind':'prepared','source_mode':'formal','training_task_ref':task.ref,
            'execution_status':task.execution_status,'provenance':{
                'task_sha256':saved.identity.key,'record_sha256':saved.record_sha256,
                'source_reading_sha256':saved.source_reading_sha256,'decision_sha256':content_digest(decision),
                'training_task_sha256':content_digest(task),'native_source_sha256':native_source_sha256,
                'evidence_sha256':task_digest(evidence)}}
    finally:
        reading.recheck()
