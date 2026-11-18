"""Freeze original Engineer A12 private feedback, judgment and training sources."""
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import ClassVar

from integration.engineer_opportunity_actions import EngineerOpportunityActionAssembler, PreparedEngineerOpportunity
from src.actions.contracts.architect_learning_objects import (
    ArchitectLearningCapabilityView, ArchitectLearningFeedbackView, ArchitectLearningProfileView,
    ArchitectLearningValueView, ArchitectLearningRuleView, ArchitectTrainingProfileView,
    ArchitectTrainingWorkView, ArchitectTrainingEstimateView, ArchitectTrainingAuthorityView,
    ArchitectTrainingRequirementView, ArchitectTrainingDependencyView,
)
from src.actions.contracts.engineer_learning_objects import (
    EngineerLearningStrategyView, EngineerLearningStateView, EngineerLearningDecisionView,
    EngineerExperienceDimensionView, EngineerLearningAssessmentView, EngineerLearningExecutionView,
    EngineerQualificationView, EngineerQualificationEventView, EngineerQualificationUpdateBasisView,
    engineer_learning_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class PreparedEngineerLearning(PreparedEngineerOpportunity):
    ACTION_ID: ClassVar[str] = 'ENGINEER-A12'


class EngineerLearningActionAssembler(EngineerOpportunityActionAssembler):
    """Preserve private feedback and explicit finite judgment/training declarations.

    Original processor checks event chronology/deduplication, selected rules,
    saved assessments and separately authorized training estimates/investment.
    Assembly changes no strategy, qualification, capability, budget or schedule.
    """
    ACTION_ID = 'ENGINEER-A12'
    SOURCE_SCHEMAS = staticmethod(engineer_learning_schemas)

    def prepare_training_estimate(self, context, *, estimate_ref, author_authority_ref,
            validate_current, **source_refs):
        """Estimate original training work under the caller's actual source guard."""
        from integration.engineer_training_estimates import prepare_engineer_training_estimate

        prepared = self.build(context, **source_refs)
        return prepare_engineer_training_estimate(context=prepared.context, action_input=prepared.action_input,
            reading=prepared.reading, estimate_ref=estimate_ref,
            author_authority_ref=author_authority_ref, validate_current=validate_current)

    def save_training_estimate(self, context, *, publications, read_guard,
            estimate_ref, author_authority_ref, validate_current, **source_refs):
        """Save the sourced work estimate before explicit fresh-token publication."""
        from integration.engineer_training_estimate_publication import EngineerTrainingEstimatePublicationStore
        from integration.engineer_training_estimates import prepare_engineer_training_estimate

        if (not isinstance(publications, EngineerTrainingEstimatePublicationStore)
                or publications.registry is not self.registry or publications.organizations is not self.organizations
                or publications.methods is not self.methods or not callable(read_guard)):
            raise TaskConflict('Engineer training save requires original registries and actual source writer guard')
        with read_guard(context):
            prepared = self.build(context, **source_refs)
            calculation = prepare_engineer_training_estimate(context=prepared.context,
                action_input=prepared.action_input, reading=prepared.reading, estimate_ref=estimate_ref,
                author_authority_ref=author_authority_ref, validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=prepared.context,
                action_input=prepared.action_input, reading=prepared.reading)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record}

    def prepare_assessment(self, context, *, assessment_ref, author_authority_ref,
            validate_current, **source_refs):
        """Produce finite-rule assessment under the caller's actual source guard."""
        from integration.engineer_learning_assessments import prepare_engineer_learning_assessment

        prepared = self.build(context, **source_refs)
        return prepare_engineer_learning_assessment(context=prepared.context, action_input=prepared.action_input,
            reading=prepared.reading, assessment_ref=assessment_ref,
            author_authority_ref=author_authority_ref, validate_current=validate_current)

    def save_assessment(self, context, *, publications, read_guard,
            assessment_ref, author_authority_ref, validate_current, **source_refs):
        """Save the finite-rule report before explicit fresh-token publication."""
        from integration.engineer_learning_assessment_publication import EngineerLearningAssessmentPublicationStore
        from integration.engineer_learning_assessments import prepare_engineer_learning_assessment

        if (not isinstance(publications, EngineerLearningAssessmentPublicationStore)
                or publications.registry is not self.registry or publications.organizations is not self.organizations
                or publications.methods is not self.methods or not callable(read_guard)):
            raise TaskConflict('Engineer assessment save requires original registries and actual source writer guard')
        with read_guard(context):
            prepared = self.build(context, **source_refs)
            calculation = prepare_engineer_learning_assessment(context=prepared.context,
                action_input=prepared.action_input, reading=prepared.reading, assessment_ref=assessment_ref,
                author_authority_ref=author_authority_ref, validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=prepared.context,
                action_input=prepared.action_input, reading=prepared.reading)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record}

    def build_from_applied_judgment(self, context, *, learning_submission, learning_identity,
            learning_execution_versions, execution_ref, native_evidence_ref, native_source_sha256,
            relation_evidence_refs, read_guard, validate_history, validate_current,
            validate_receipt_relation, **source_refs):
        """Freeze the actual successor strategy/state without applying learning again."""
        from integration.engineer_submission import EngineerResultSubmission
        from integration.engineer_learning_results import EngineerLearningResultWorker
        from integration.engineer_learning_application_handoff import prepare_engineer_judgment_application_handoff

        if (not isinstance(learning_submission,EngineerResultSubmission) or learning_submission.ACTION_ID != self.ACTION_ID
                or not isinstance(learning_submission.worker,EngineerLearningResultWorker)
                or learning_submission.worker.registry is not self.registry
                or learning_submission.worker.store.run_id != self.organizations.run_id
                or self.source_mode != 'formal' or not all(callable(callback) for callback in
                    (read_guard,validate_history,validate_current,validate_receipt_relation))):
            raise TaskConflict('Judgment application linkage requires original Engineer binding and actual guarded source checks')
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

            handoff=prepare_engineer_judgment_application_handoff(saved,invocation=invocation,
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
        from integration.engineer_submission import EngineerResultSubmission
        from integration.engineer_learning_results import EngineerLearningResultWorker
        from integration.engineer_training_task_handoff import prepare_engineer_training_task_handoff

        if (not isinstance(learning_submission,EngineerResultSubmission) or learning_submission.ACTION_ID != self.ACTION_ID
                or not isinstance(learning_submission.worker,EngineerLearningResultWorker)
                or learning_submission.worker.registry is not self.registry
                or learning_submission.worker.store.run_id != self.organizations.run_id or self.source_mode != 'formal'
                or not all(callable(callback) for callback in
                    (read_guard,validate_history,validate_current,validate_receipt_relation))):
            raise TaskConflict('Training task linkage requires original Engineer binding and actual guarded source checks')
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

            handoff = prepare_engineer_training_task_handoff(saved,invocation=invocation,
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

    def build_from_qualification_verification(self, context, *, learning_submission, learning_identity,
            learning_execution_versions, verification_ref, native_evidence_ref, native_source_sha256,
            relation_evidence_refs, read_guard, validate_history, validate_current,
            validate_receipt_relation, **source_refs):
        """Relate actual issuer verification to the saved request without applying credentials."""
        from integration.engineer_submission import EngineerResultSubmission
        from integration.engineer_learning_results import EngineerLearningResultWorker
        from integration.engineer_qualification_verification_handoff import prepare_engineer_qualification_verification_handoff

        if (not isinstance(learning_submission,EngineerResultSubmission) or learning_submission.ACTION_ID != self.ACTION_ID
                or not isinstance(learning_submission.worker,EngineerLearningResultWorker)
                or learning_submission.worker.registry is not self.registry
                or learning_submission.worker.store.run_id != self.organizations.run_id or self.source_mode != 'formal'
                or not all(callable(callback) for callback in
                    (read_guard,validate_history,validate_current,validate_receipt_relation))):
            raise TaskConflict('Qualification verification linkage requires original Engineer binding and actual guarded source checks')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            receipt = learning_submission.read_receipt(learning_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected qualification request cannot prove native issuer verification')
            invocation = self.build(context,**source_refs)
            saved = learning_submission.worker.read_completed(learning_identity,current_context=invocation.context,
                reading=invocation.reading,execution_versions=learning_execution_versions,validate_current=validate_history)

            def validate_link(**sources):
                if (sources['saved'].identity.as_dict() != receipt['identity']
                        or sources['saved'].record_sha256 != receipt['record_sha256']):
                    raise TaskConflict('Qualification verification receipt substitutes its original request result')
                return (validate_current(**sources) is True
                    and validate_receipt_relation(receipt=deepcopy(receipt),**sources) is True)

            handoff = prepare_engineer_qualification_verification_handoff(saved,invocation=invocation,
                verification_ref=verification_ref,native_evidence_ref=native_evidence_ref,
                native_source_sha256=native_source_sha256,relation_evidence_refs=relation_evidence_refs,
                validate_current=validate_link)
            if handoff['kind'] != 'prepared':
                return handoff
            if learning_submission.read_receipt(learning_identity) != receipt:
                raise TaskConflict('Original qualification request receipt changed during verification linkage')
            invocation.reading.recheck()
            return {**handoff,'provenance':{**handoff['provenance'],'submission':deepcopy(receipt)},
                'invocation':replace(invocation,reading_sha256=task_digest(invocation.reading.evidence()))}

    def build_from_applied_qualification(self, context, *, learning_submission, learning_identity,
            learning_execution_versions, verification_ref, verification_native_evidence_ref,
            verification_source_sha256, verification_relation_evidence_refs, execution_ref,
            applied_qualification_ref, native_evidence_ref, native_source_sha256, relation_evidence_refs,
            read_guard, validate_history, validate_verification, validate_current,
            validate_receipt_relation, **source_refs):
        """Relate actual issuer application to its saved request without applying it."""
        from integration.engineer_submission import EngineerResultSubmission
        from integration.engineer_learning_results import EngineerLearningResultWorker
        from integration.engineer_qualification_application_handoff import prepare_engineer_qualification_application_handoff

        if (not isinstance(learning_submission,EngineerResultSubmission) or learning_submission.ACTION_ID != self.ACTION_ID
                or not isinstance(learning_submission.worker,EngineerLearningResultWorker)
                or learning_submission.worker.registry is not self.registry
                or learning_submission.worker.store.run_id != self.organizations.run_id or self.source_mode != 'formal'
                or not all(callable(callback) for callback in
                    (read_guard,validate_history,validate_verification,validate_current,validate_receipt_relation))):
            raise TaskConflict('Qualification application linkage requires original binding and actual guarded source checks')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            receipt = learning_submission.read_receipt(learning_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected qualification request cannot prove actual issuer application')
            invocation = self.build(context,**source_refs)
            saved = learning_submission.worker.read_completed(learning_identity,current_context=invocation.context,
                reading=invocation.reading,execution_versions=learning_execution_versions,validate_current=validate_history)

            def validate_link(callback, sources):
                if (sources['saved'].identity.as_dict() != receipt['identity']
                        or sources['saved'].record_sha256 != receipt['record_sha256']):
                    raise TaskConflict('Qualification application receipt substitutes its original request result')
                return (callback(**sources) is True
                    and validate_receipt_relation(receipt=deepcopy(receipt),**sources) is True)

            handoff = prepare_engineer_qualification_application_handoff(saved,invocation=invocation,
                verification_ref=verification_ref,verification_native_evidence_ref=verification_native_evidence_ref,
                verification_source_sha256=verification_source_sha256,
                verification_relation_evidence_refs=verification_relation_evidence_refs,
                validate_verification=lambda **sources: validate_link(validate_verification,sources),
                execution_ref=execution_ref,applied_qualification_ref=applied_qualification_ref,
                native_evidence_ref=native_evidence_ref,native_source_sha256=native_source_sha256,
                relation_evidence_refs=relation_evidence_refs,
                validate_current=lambda **sources: validate_link(validate_current,sources))
            if handoff['kind'] != 'prepared':
                return handoff
            if learning_submission.read_receipt(learning_identity) != receipt:
                raise TaskConflict('Original qualification request receipt changed during application linkage')
            invocation.reading.recheck()
            return {**handoff,'provenance':{**handoff['provenance'],'submission':deepcopy(receipt)},
                'invocation':replace(invocation,reading_sha256=task_digest(invocation.reading.evidence()))}

    def build(self, context, *, scope, qualification_refs, feedback_refs, learning_profile_ref, strategy_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'strategy_ref': strategy_ref, 'qualification_refs': qualification_refs,
            'feedback_refs': feedback_refs, 'learning_profile_ref': learning_profile_ref},
            prepared_type=PreparedEngineerLearning, validate_sources=validate_engineer_learning_sources)


def validate_engineer_learning_sources(action_input, *, context, organization_id, sources):
    """Check original private identities without interpreting feedback or training."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Engineer learning lacks its exact original concrete source')
        return row

    def own(row):
        if (row.organization_id != organization_id
                or hasattr(row, 'author_organization_id') and row.author_organization_id != organization_id):
            raise TaskConflict('Engineer learning source changes its original private firm or author')
        return row

    def feedback(ref):
        row = read(ref, ArchitectLearningFeedbackView)
        if row.recipient_organization_id != organization_id:
            raise TaskConflict('Engineer learning uses another firm private feedback')
        unique_refs([outcome.dimension_ref for outcome in row.event.outcomes])
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Engineer learning changes its original invocation scope')
    strategy = own(read(action_input.strategy_ref, EngineerLearningStrategyView))
    unique_refs(action_input.qualification_refs)
    for ref in action_input.qualification_refs:
        qualification = read(ref, EngineerQualificationView)
        if qualification.organization_id != organization_id:
            raise TaskConflict('Engineer qualification changes its original credential subject')
        unique_refs(qualification.event_refs)
        for event_ref in qualification.event_refs:
            if event_ref.key() in sources:
                event = read(event_ref, EngineerQualificationEventView)
                if (event.qualification_ref.key() != qualification.ref.key() or event.organization_id != organization_id
                        or event.issuer_organization_id != qualification.issuer_organization_id
                        or event.credential_key != qualification.credential_key):
                    raise TaskConflict('Engineer qualification event changes its original credential or issuer')
    unique_refs(action_input.feedback_refs)
    unique_refs([change.dimension_ref for change in strategy.judgments])
    for ref in action_input.feedback_refs:
        feedback(ref)
    state = None
    if strategy.learning_state_ref.key() in sources:
        state = own(read(strategy.learning_state_ref, EngineerLearningStateView))
        if state.strategy_ref.key() != strategy.ref.key() or state.scope != context.scope:
            raise TaskConflict('Engineer learning state changes its original strategy, capability or scope')
        unique_refs(state.qualification_refs)
        unique_refs(state.applied_qualification_event_refs)
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
                execution = own(read(ref, EngineerLearningExecutionView))
                if execution.run_id != context.run_id or execution.strategy_ref.id != strategy.ref.id:
                    raise TaskConflict('Engineer learning execution history changes its original run or strategy')
    decision = None
    if strategy.decision_profile_ref.key() in sources:
        decision = own(read(strategy.decision_profile_ref, EngineerLearningDecisionView))
        if (decision.strategy_ref.key() != strategy.ref.key() or decision.actor_id != context.actor_id
                or decision.function_ref.key() != context.function_ref.key() or decision.scope != context.scope):
            raise TaskConflict('Engineer learning decision changes its original strategy, actor, function or scope')
        unique_refs(decision.feedback_refs)
        if state is not None:
            for ref in state.execution_refs:
                execution = sources.get(ref.key())
                if execution is not None and execution.business_key == decision.business_key:
                    original = sources.get(execution.decision_ref.key())
                    if original is not None and (not isinstance(original, EngineerLearningDecisionView)
                            or original.strategy_ref != execution.strategy_ref
                            or original.organization_id != execution.organization_id or original.scope != execution.scope
                            or original.business_key != execution.business_key):
                        raise TaskConflict('Engineer learning execution substitutes its original decision or strategy version')
    if (decision is not None and decision.qualification_update_basis_ref is not None
            and decision.qualification_update_basis_ref.key() in sources):
        basis = read(decision.qualification_update_basis_ref, EngineerQualificationUpdateBasisView)
        if basis.organization_id != organization_id:
            raise TaskConflict('Engineer qualification update basis changes its original credential subject')
        if basis.qualification_ref.key() in sources:
            qualification = read(basis.qualification_ref, EngineerQualificationView)
            if (basis.issuer_organization_id != qualification.issuer_organization_id
                    or basis.credential_key != qualification.credential_key):
                raise TaskConflict('Engineer qualification update basis changes its original issuer or credential')
    # Actual issuer authority, verified event chronology/digest, completeness and
    # request-only effects remain processor decisions; training does not renew credentials.
    if action_input.learning_profile_ref is None:
        return
    profile = own(read(action_input.learning_profile_ref, ArchitectLearningProfileView))
    if profile.strategy_ref.key() != strategy.ref.key():
        raise TaskConflict('Engineer learning profile changes its original strategy')
    if state is not None and state.learning_profile_ref != profile.ref:
        raise TaskConflict('Engineer learning changes its original selected profile')
    for refs in (profile.dimension_refs, profile.rule_refs, profile.training_profile_refs):
        unique_refs(refs)
    for ref in profile.dimension_refs:
        if ref.key() in sources:
            dimension = own(read(ref, EngineerExperienceDimensionView))
            if dimension.learning_profile_ref.key() != profile.ref.key():
                raise TaskConflict('Engineer judgment dimension changes its original learning profile')
            unique_refs(dimension.value_refs)
            for value_ref in dimension.value_refs:
                if value_ref.key() in sources:
                    value = own(read(value_ref, ArchitectLearningValueView))
                    if value.dimension_ref.key() != dimension.ref.key():
                        raise TaskConflict('Engineer judgment value changes its original dimension')
    for ref in profile.rule_refs:
        if ref.key() in sources:
            rule = own(read(ref, ArchitectLearningRuleView))
            if rule.learning_profile_ref.key() != profile.ref.key() or rule.rule.rule_ref.key() != rule.ref.key():
                raise TaskConflict('Engineer learning rule changes its original profile or rule identity')
    if decision is None:
        return
    if decision.assessment_ref is not None and decision.assessment_ref.key() in sources:
        assessment = own(read(decision.assessment_ref, EngineerLearningAssessmentView))
        if assessment.strategy_ref.key() != strategy.ref.key() or assessment.learning_profile_ref.key() != profile.ref.key():
            raise TaskConflict('Engineer learning assessment changes its original strategy or profile')
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
            raise TaskConflict('Engineer training work data changes its original work profile')
        if training.estimate_ref.key() in sources:
            estimate = own(read(training.estimate_ref, ArchitectTrainingEstimateView))
            if estimate.work_profile_ref.key() != work.ref.key():
                raise TaskConflict('Engineer training estimate changes its original work profile')
    for ref in request.output_requirement_refs:
        if ref.key() in sources:
            requirement = own(read(ref, ArchitectTrainingRequirementView))
            if requirement.training_profile_ref.key() != training.ref.key():
                raise TaskConflict('Engineer training output changes its original training profile')
    for ref in request.dependency_refs:
        if ref.key() in sources:
            dependency = read(ref, ArchitectTrainingDependencyView)
            if dependency.training_profile_ref.key() != training.ref.key():
                raise TaskConflict('Engineer training dependency changes its original training profile')
