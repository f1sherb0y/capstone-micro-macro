"""Inspect actual qualification application after independent issuer verification."""
from copy import deepcopy

from integration.engineer_qualification_verification_handoff import prepare_engineer_qualification_verification_handoff
from src.actions.contracts.architect_learning_objects import ArchitectLearningCapabilityView
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.engineer_learning_objects import (
    EngineerLearningStrategyView, EngineerLearningStateView, EngineerLearningDecisionView,
    EngineerLearningExecutionView, EngineerQualificationView, EngineerQualificationEventView,
    EngineerQualificationVerificationView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest


def prepare_engineer_qualification_application_handoff(saved, *, invocation, verification_ref,
        verification_native_evidence_ref, verification_source_sha256, verification_relation_evidence_refs,
        validate_verification, execution_ref, applied_qualification_ref, native_evidence_ref,
        native_source_sha256, relation_evidence_refs, validate_current):
    """Relate actual issuer application to the original saved request, without writes.

    Caller holds the actual source/authorization guard. Separate verification
    and application gates must check native provenance, issuer authority and
    receipt relations. Undeclared credential status/standing rules remain the
    issuer service's responsibility; this handoff manufactures no update.
    """
    if not callable(validate_current):
        raise TaskConflict('Qualification application requires independent actual source validation')
    verified = prepare_engineer_qualification_verification_handoff(saved, invocation=invocation,
        verification_ref=verification_ref, native_evidence_ref=verification_native_evidence_ref,
        native_source_sha256=verification_source_sha256, relation_evidence_refs=verification_relation_evidence_refs,
        validate_current=validate_verification)
    if verified['kind'] != 'prepared':
        return verified
    if verified['verification_status'] != 'verified':
        raise TaskConflict('Failed or rejected issuer verification cannot prove applied qualification')
    context, reading = invocation.context, invocation.reading

    def read(ref, model):
        ref = Reference.model_validate(ref)
        row = reading.resolve(ref)
        if not isinstance(row, model) or row.ref != ref:
            raise TaskConflict('Qualification application lacks its exact concrete source version')
        return row

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    try:
        originals = {Reference.model_validate(row['ref']).key():row['projection'] for row in saved.source_reading}
        strategy = EngineerLearningStrategyView.model_validate(originals[saved.action_input.strategy_ref.key()])
        state = EngineerLearningStateView.model_validate(originals[strategy.learning_state_ref.key()])
        decision = EngineerLearningDecisionView.model_validate(originals[strategy.decision_profile_ref.key()])
        qualification = EngineerQualificationView.model_validate(originals[decision.qualification_ref.key()])
        verification = read(verified['verification_ref'], EngineerQualificationVerificationView)
        event = EngineerQualificationEventView.model_validate(originals[verification.qualification_event_ref.key()])
        execution = read(execution_ref, EngineerLearningExecutionView)
        if (execution.run_id != context.run_id or execution.organization_id != reading.organization_id
                or execution.strategy_ref != strategy.ref or execution.decision_ref != decision.ref
                or execution.decision_sha256 != content_digest(decision) or execution.business_key != decision.business_key):
            raise TaskConflict('Qualification application substitutes original execution or request identity')
        if execution.status != 'succeeded':
            code = 'query_original_engineer_qualification_application'
            return {'kind':'deferred','reason_code':code,'resume_condition':{
                'trigger':'dependency_change','object_refs':[execution.ref],'earliest_time':None,'condition_code':code}}
        current = read(applied_qualification_ref, EngineerQualificationView)
        current_strategy = read(invocation.action_input.strategy_ref, EngineerLearningStrategyView)
        current_state = read(current_strategy.learning_state_ref, EngineerLearningStateView)
        prior_capability = ArchitectLearningCapabilityView.model_validate(originals[state.capability_ref.key()])
        capability = read(current_state.capability_ref, ArchitectLearningCapabilityView)
        if (current.ref.id != qualification.ref.id or current.ref == qualification.ref or type(current.ref.version) is not str
                or current.organization_id != reading.organization_id
                or current.issuer_organization_id != qualification.issuer_organization_id
                or current.author_organization_id != qualification.issuer_organization_id
                or current.credential_key != qualification.credential_key or current.personnel_ids != qualification.personnel_ids
                or current.scope != qualification.scope or current.coverage != 'complete' or current.as_of != context.business_time
                or not keys(qualification.event_refs) <= keys(current.event_refs) or event.ref.key() not in keys(current.event_refs)
                or current_strategy.ref.id != strategy.ref.id or current_strategy.organization_id != reading.organization_id
                or current_strategy.judgments != strategy.judgments or current_strategy.scope != strategy.scope
                or current_state.organization_id != reading.organization_id or current_state.strategy_ref != current_strategy.ref
                or current_state.learning_profile_ref != state.learning_profile_ref or current_state.scope != state.scope
                or current_state.coverage != 'complete' or current_state.as_of != context.business_time
                or keys(current_state.qualification_refs) != (keys(state.qualification_refs) - {qualification.ref.key()}) | {current.ref.key()}
                or keys(invocation.action_input.qualification_refs) != keys(current_state.qualification_refs)
                or keys(current_state.applied_qualification_event_refs) != keys(state.applied_qualification_event_refs) | {event.ref.key()}
                or event.ref.key() in keys(state.applied_qualification_event_refs)
                or keys(current_state.execution_refs) != keys(state.execution_refs) | {execution.ref.key()}
                or keys(current_state.received_feedback_refs) != keys(state.received_feedback_refs)
                or keys(current_state.applied_feedback_refs) != keys(state.applied_feedback_refs)
                or capability.organization_id != reading.organization_id or capability.ref.id != prior_capability.ref.id
                or capability.verified_capability_codes != prior_capability.verified_capability_codes
                or capability.status != prior_capability.status or capability.scope != prior_capability.scope
                or keys(capability.qualification_refs) != keys(current_state.qualification_refs)):
            raise TaskConflict('Qualification application changes unrelated credential, judgment, feedback or capability history')
        # Apply only issuer-declared values; other status/standing semantics
        # are independently checked against the actual issuer service below.
        if (event.next_validity is not None and current.validity != event.next_validity
                or event.next_discipline_codes and current.discipline_codes != event.next_discipline_codes
                or event.next_region_ids and current.region_ids != event.next_region_ids
                or event.next_service_codes and current.service_codes != event.next_service_codes):
            raise TaskConflict('Qualification application substitutes issuer-declared validity or scope')
        physical = set()
        for ref in current_state.applied_qualification_event_refs:
            row = read(ref, EngineerQualificationEventView)
            identity = (row.issuer_organization_id, row.credential_key, row.event_key)
            if row.organization_id != reading.organization_id or identity in physical:
                raise TaskConflict('Qualification application repeats a physical issuer event or another holder')
            physical.add(identity)
        points = [verification.available_at, current.authored_at, current.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or event.effective_at.clock_ref != context.business_time.clock_ref or event.effective_at.offset > context.business_time.offset
                or any(left.offset > right.offset for left,right in zip(points,points[1:]))
                or execution.available_at.clock_ref != context.business_time.clock_ref
                or not verification.available_at.offset <= execution.available_at.offset <= context.business_time.offset
                or current_state.available_at.clock_ref != context.business_time.clock_ref
                or current_state.available_at.offset > context.business_time.offset
                or any(not row.effective_window.contains(context.business_time) for row in (current,current_state,current_strategy,capability))):
            raise TaskConflict('Qualification application changes issuer-effective, execution or observation chronology')
        native = Reference.model_validate(native_evidence_ref)
        relations = [Reference.model_validate(ref) for ref in relation_evidence_refs]
        if not relations or native in relations:
            raise TaskConflict('Qualification application needs separate native and independent relation evidence')
        unique_refs(relations)
        evidence = []
        for ref in [native,*relations]:
            row = read(ref,EvidenceRecord)
            if (row.basis_kind != 'observed' or row.source_kind == 'synthetic'
                    or row.effective_window is not None and not row.effective_window.contains(context.business_time)):
                raise TaskConflict('Qualification application requires current actual native and relation observations')
            evidence.append(row.model_dump(mode='json'))
        if evidence[0]['content_hash'] != native_source_sha256:
            raise TaskConflict('Qualification application substitutes actual native source content')
        if validate_current(saved=deepcopy(saved),decision=decision.model_copy(deep=True),
                original_qualification=qualification.model_copy(deep=True),event=event.model_copy(deep=True),
                verification=verification.model_copy(deep=True),execution=execution.model_copy(deep=True),
                qualification=current.model_copy(deep=True),state=current_state.model_copy(deep=True),
                capability=capability.model_copy(deep=True),evidence=deepcopy(evidence),
                context=context.model_copy(deep=True),reading=reading) is not True:
            raise TaskConflict('Qualification application requires actual issuer rule, authority and native relation validation')
        return {'kind':'prepared','source_mode':'formal','qualification_ref':current.ref,'provenance':{
            'verification':deepcopy(verified['provenance']),'task_sha256':saved.identity.key,
            'record_sha256':saved.record_sha256,'execution_sha256':content_digest(execution),
            'qualification_sha256':content_digest(current),'state_sha256':content_digest(current_state),
            'native_source_sha256':native_source_sha256,'evidence_sha256':task_digest(evidence)}}
    finally:
        reading.recheck()
