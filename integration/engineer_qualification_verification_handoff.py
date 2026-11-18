"""Relate saved qualification requests to actual independent issuer verification."""
from copy import deepcopy

from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.engineer_learning_objects import (
    EngineerLearningStrategyView, EngineerLearningDecisionView, EngineerQualificationView,
    EngineerQualificationEventView, EngineerQualificationUpdateBasisView, EngineerQualificationVerificationView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest


def prepare_engineer_qualification_verification_handoff(saved, *, invocation, verification_ref,
        native_evidence_ref, native_source_sha256, relation_evidence_refs, validate_current):
    """Inspect issuer verification under the caller's source/authorization guard.

    The independent gate checks actual issuer/service authority, request and
    native receipt relation, and private access. A verified record here proves
    no applied credential state, renewed validity or improved capability.
    """
    from integration.engineer_learning_results import SavedEngineerLearning

    context, reading = invocation.context, invocation.reading
    if (not isinstance(saved, SavedEngineerLearning) or saved.current_context != context
            or saved.identity.action_id != 'ENGINEER-A12' or saved.identity.role != 'Engineer'
            or saved.identity.run_id != context.run_id or saved.identity.organization_id != reading.organization_id
            or saved.result.kind != 'completed' or saved.result.payload.choice != 'request_qualification_update'
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or saved.audit.get('input_sha256') != saved.identity.input_sha256
            or saved.audit.get('result_sha256') != task_digest(saved.result.model_dump(mode='json'))
            or saved.audit.get('result_kind') != 'completed' or not callable(validate_current)
            or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Qualification handoff requires the original saved request and current formal reading')
    reading.check_method_context(context, 'ENGINEER-A12')
    target = Reference.model_validate(verification_ref)
    native = Reference.model_validate(native_evidence_ref)
    relations = [Reference.model_validate(ref) for ref in relation_evidence_refs]
    unique_refs(relations)
    if not relations or native in relations:
        raise TaskConflict('Qualification verification needs separate native and independent relation evidence')
    try:
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        strategy = EngineerLearningStrategyView.model_validate(originals[saved.action_input.strategy_ref.key()])
        decision = EngineerLearningDecisionView.model_validate(originals[strategy.decision_profile_ref.key()])
        qualification = EngineerQualificationView.model_validate(originals[decision.qualification_ref.key()])
        basis = EngineerQualificationUpdateBasisView.model_validate(originals[decision.qualification_update_basis_ref.key()])
        event = EngineerQualificationEventView.model_validate(originals[basis.qualification_event_ref.key()])
        verification = reading.resolve(target)
        request = saved.result.payload
        if (not isinstance(verification, EngineerQualificationVerificationView) or verification.ref != target
                or verification.run_id != context.run_id or verification.organization_id != reading.organization_id
                or verification.task_sha256 != saved.identity.key or verification.record_sha256 != saved.record_sha256
                or verification.decision_ref != decision.ref or verification.decision_sha256 != content_digest(decision)
                or verification.business_key != decision.business_key
                or verification.qualification_ref != qualification.ref or request.qualification_ref != qualification.ref
                or verification.update_basis_ref != basis.ref or verification.qualification_event_ref != event.ref
                or verification.qualification_event_sha256 != content_digest(event)
                or verification.issuer_organization_id != qualification.issuer_organization_id
                or verification.author_organization_id != qualification.issuer_organization_id
                or verification.verification_service_id != basis.verification_service_id
                or verification.request_evidence_refs != request.evidence_refs or verification.scope != saved.context.scope):
            raise TaskConflict('Qualification verification substitutes original request, issuer, event, basis or private scope')
        unique_refs(verification.request_evidence_refs)
        points = [saved.context.business_time, verification.authored_at, verification.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or not verification.effective_window.contains(context.business_time)):
            raise TaskConflict('Qualification verification changes original request or receipt chronology')
        if verification.status in {'pending','unknown'}:
            code = 'query_original_engineer_qualification_verification'
            return {'kind':'deferred', 'reason_code':code, 'resume_condition':{
                'trigger':'dependency_change', 'object_refs':[verification.ref], 'earliest_time':None, 'condition_code':code}}
        evidence = []
        for ref in [native, *relations]:
            row = reading.resolve(ref)
            if (not isinstance(row, EvidenceRecord) or row.ref != ref or row.basis_kind != 'observed'
                    or row.source_kind == 'synthetic'
                    or row.effective_window is not None and not row.effective_window.contains(context.business_time)):
                raise TaskConflict('Qualification verification requires current actual native and relation observations')
            evidence.append(row.model_dump(mode='json'))
        if evidence[0]['content_hash'] != native_source_sha256:
            raise TaskConflict('Qualification verification changes its actual native source')
        if validate_current(saved=deepcopy(saved), decision=decision.model_copy(deep=True),
                qualification=qualification.model_copy(deep=True), basis=basis.model_copy(deep=True),
                event=event.model_copy(deep=True), verification=verification.model_copy(deep=True),
                evidence=deepcopy(evidence), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Qualification verification requires actual issuer/service authority, native relation and privacy checks')
        return {'kind':'prepared', 'source_mode':'formal', 'verification_ref':verification.ref,
            'verification_status':verification.status, 'provenance':{
                'task_sha256':saved.identity.key, 'record_sha256':saved.record_sha256,
                'source_reading_sha256':saved.source_reading_sha256, 'decision_sha256':content_digest(decision),
                'qualification_event_sha256':content_digest(event), 'verification_sha256':content_digest(verification),
                'native_source_sha256':native_source_sha256, 'evidence_sha256':task_digest(evidence)}}
    finally:
        reading.recheck()
