"""Freeze original QS A11 service history, resource and document-right sources."""
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import ClassVar

from integration.qs_market_actions import QSMarketActionAssembler, PreparedQSMarket
from src.actions.contracts.architect_transition_objects import (
    ArchitectTransitionBasisView, ArchitectTransitionAllocationView, ArchitectAllocationReleaseView,
    ArchitectTransitionAccessView, ArchitectExistingUseRightView,
    ArchitectRecallWorkProfileView, ArchitectTransitionExecutionView,
)
from src.actions.contracts.qs_transition_objects import (
    QSTransitionEngagementView, QSTransitionTaskView, QSTransitionDeliverableView,
    QSHandoverAcceptanceView, QSTransitionObligationView, QSTransitionContractView,
    QSTransitionSourceView, QSTransitionSourceAccessView, QSReviewEstimateView,
    qs_transition_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.roles.qs_change import content_digest
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedQSTransition(PreparedQSMarket):
    ACTION_ID: ClassVar[str] = 'QS-A11'


class QSTransitionActionAssembler(QSMarketActionAssembler):
    """Preserve cross-service history, authorship, licensed use and remaining debt.

    Original processor checks selected tasks, recall capacity, atomic allocation
    replacement, document access and independent successor acceptance. Assembly
    releases no resources, reserves no capacity and clears no service obligation.
    """
    ACTION_ID = 'QS-A11'
    SOURCE_SCHEMAS = staticmethod(qs_transition_schemas)

    def build(self, context, *, scope, engagement_ref, transition_basis_ref, task_refs,
            allocation_refs, deliverable_refs, residual_obligation_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'engagement_ref': engagement_ref, 'transition_basis_ref': transition_basis_ref,
            'task_refs': task_refs, 'allocation_refs': allocation_refs,
            'deliverable_refs': deliverable_refs, 'residual_obligation_refs': residual_obligation_refs},
            prepared_type=PreparedQSTransition, validate_sources=validate_qs_transition_sources)

    def build_from_submitted_transition(self, context, *, transition_submission, transition_identity,
            transition_execution_versions, execution_ref, native_evidence_ref, native_source_sha256,
            relation_evidence_refs, read_guard, validate_history, validate_current,
            validate_receipt_relation, **transition_refs):
        """Freeze independently observed execution of the original transition.

        Caller supplies actual registration/event evidence and holds the current
        source guard. Accepted registration is distinct from execution status;
        pending/unknown remains in history for the original processor to defer.
        No resources, rights, successor tasks or remaining debts are changed.
        """
        from integration.qs_submission import QSResultSubmission
        from integration.qs_transition_results import QSTransitionResultWorker

        if (not isinstance(transition_submission, QSResultSubmission)
                or transition_submission.ACTION_ID != self.ACTION_ID
                or not isinstance(transition_submission.worker, QSTransitionResultWorker)
                or transition_submission.worker.registry is not self.registry
                or transition_submission.worker.store.run_id != self.organizations.run_id
                or self.source_mode != 'formal' or not all(callable(callback) for callback in
                    (read_guard, validate_history, validate_current, validate_receipt_relation))):
            raise TaskConflict('Transition linkage requires original QS binding and actual guarded source/relation checks')
        execution_ref = Reference.model_validate(execution_ref)
        native_evidence_ref = Reference.model_validate(native_evidence_ref)
        relation_evidence_refs = [Reference.model_validate(ref) for ref in relation_evidence_refs]
        unique_refs(relation_evidence_refs)
        if not relation_evidence_refs or native_evidence_ref in relation_evidence_refs:
            raise TaskConflict('Transition execution requires native observation and separate relation evidence')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            receipt = transition_submission.read_receipt(transition_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected transition registration cannot prove an actual execution relation')
            invocation = self.build(context, **transition_refs)
            reading = invocation.reading
            saved = transition_submission.worker.read_completed(transition_identity,
                current_context=invocation.context, reading=reading,
                execution_versions=transition_execution_versions, validate_current=validate_history)
            if saved.identity.as_dict() != receipt['identity'] or saved.record_sha256 != receipt['record_sha256']:
                raise TaskConflict('Transition receipt substitutes the original task or saved result')
            originals = {Reference.model_validate(row['ref']).key(): row['projection']
                for row in saved.source_reading}
            original_basis = ArchitectTransitionBasisView.model_validate(
                originals[saved.action_input.transition_basis_ref.key()])
            execution = reading.resolve(execution_ref)
            engagement = reading.resolve(invocation.action_input.engagement_ref)
            if (not isinstance(execution, ArchitectTransitionExecutionView)
                    or not isinstance(engagement, QSTransitionEngagementView)
                    or execution.ref != execution_ref or execution.ref not in engagement.execution_refs
                    or execution.organization_id != reading.organization_id or execution.run_id != context.run_id
                    or execution.engagement_ref != saved.action_input.engagement_ref
                    or engagement.ref.kind != execution.engagement_ref.kind or engagement.ref.id != execution.engagement_ref.id
                    or execution.scope != saved.context.scope or not scope_covers(engagement.scope,original_basis.scope)
                    or execution.business_key != original_basis.business_key
                    or execution.basis_ref != original_basis.ref or execution.basis_sha256 != content_digest(original_basis)
                    or original_basis.choice != saved.result.payload.choice
                    or reading.resolve(original_basis.ref) != original_basis):
                raise TaskConflict('Transition execution changes original service, business key, proposal basis or source content')
            if original_basis.choice == 'pause':
                consistent = (saved.result.payload.basis_ref == original_basis.ref
                    and saved.result.payload.task_refs == original_basis.selected_task_refs)
            elif original_basis.choice == 'recall':
                consistent = (original_basis.recall_plan is not None
                    and saved.result.payload.plan.model_dump(mode='json') == original_basis.recall_plan.model_dump(mode='json'))
            else:
                consistent = (original_basis.package is not None
                    and saved.result.payload.package.model_dump(mode='json') == original_basis.package.model_dump(mode='json'))
            if not consistent:
                raise TaskConflict('Transition execution changes the actually saved original proposal branch')
            points = [saved.context.business_time, execution.available_at, context.business_time]
            if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                    or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                    or not execution.effective_window.contains(context.business_time)):
                raise TaskConflict('Transition execution changes actual event availability or clock')
            evidence = []
            for ref in [native_evidence_ref, *relation_evidence_refs]:
                row = reading.resolve(ref)
                if (not isinstance(row, EvidenceRecord) or row.ref != ref
                        or row.basis_kind != 'observed' or row.source_kind == 'synthetic'
                        or row.effective_window is not None and not row.effective_window.contains(context.business_time)):
                    raise TaskConflict('Transition linkage requires available actual observed native/relation evidence')
                evidence.append(row.model_dump(mode='json'))
            if evidence[0]['content_hash'] != native_source_sha256:
                raise TaskConflict('Transition observation substitutes the original native source digest')
            sources = dict(saved=deepcopy(saved), original_basis=original_basis.model_copy(deep=True),
                execution=execution.model_copy(deep=True), engagement=engagement.model_copy(deep=True),
                evidence=deepcopy(evidence), context=context.model_copy(deep=True), reading=reading)
            if (validate_current(**sources) is not True
                    or validate_receipt_relation(receipt=deepcopy(receipt), **sources) is not True):
                raise TaskConflict('Transition linkage requires independent actual execution and receipt-to-event validation')
            if transition_submission.read_receipt(transition_identity) != receipt:
                raise TaskConflict('Original transition receipt changed during execution linkage')
            reading.recheck()
            return {'kind':'prepared', 'source_mode':'formal',
                'provenance':{'task_sha256':saved.identity.key, 'record_sha256':saved.record_sha256,
                    'source_reading_sha256':saved.source_reading_sha256,
                    'basis_sha256':content_digest(original_basis),
                    'execution_ref':execution.ref.model_dump(mode='json'),
                    'execution_sha256':task_digest(execution.model_dump(mode='json')),
                    'execution_status':execution.status, 'native_source_sha256':native_source_sha256,
                    'evidence_sha256':task_digest(evidence), 'submission':deepcopy(receipt)},
                'invocation':replace(invocation, reading_sha256=task_digest(reading.evidence()))}


def validate_qs_transition_sources(action_input, *, context, organization_id, sources):
    """Check original service/actor/source identities without evaluating a transition."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('QS transition lacks its exact original concrete source')
        return row

    def same_engagement(row):
        if row.engagement_ref.key() != engagement.ref.key():
            raise TaskConflict('QS transition source changes its original engagement')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('QS transition changes its original invocation scope')
    engagement = read(action_input.engagement_ref, QSTransitionEngagementView)
    basis = same_engagement(read(action_input.transition_basis_ref, ArchitectTransitionBasisView))
    if (engagement.organization_id != organization_id or not scope_covers(engagement.scope, context.scope)
            or basis.scope != context.scope or basis.actor_id != context.actor_id
            or basis.function_ref.key() != context.function_ref.key()):
        raise TaskConflict('QS transition changes its original organization, actor, function or scope')
    for field in ('task_refs', 'allocation_refs', 'deliverable_refs', 'residual_obligation_refs'):
        unique_refs(getattr(action_input, field))
        unique_refs(getattr(engagement, 'usable_deliverable_refs' if field == 'deliverable_refs' else field))
    unique_refs(engagement.execution_refs)
    unique_refs(basis.selected_task_refs)
    unique_refs(basis.recipient_acceptance_refs)
    for ref in action_input.task_refs:
        task = same_engagement(read(ref, QSTransitionTaskView))
        if task.organization_id != organization_id or task.author_organization_id != organization_id:
            raise TaskConflict('QS transition task changes its original firm or author organization')
        unique_refs(task.dependency_refs)
        if task.allocation_ref is not None and task.allocation_ref.key() in sources:
            allocation = same_engagement(read(task.allocation_ref, ArchitectTransitionAllocationView))
            if allocation.task_ref.key() != task.ref.key():
                raise TaskConflict('QS transition task allocation changes its original task')
    for ref in action_input.allocation_refs:
        allocation = same_engagement(read(ref, ArchitectTransitionAllocationView))
        if allocation.organization_id != organization_id:
            raise TaskConflict('QS transition allocation changes its original firm')
        unique_refs(allocation.commitment_refs)
        if allocation.release_permission_ref.key() in sources:
            permission = read(allocation.release_permission_ref, ArchitectAllocationReleaseView)
            if permission.allocation_ref.key() != allocation.ref.key():
                raise TaskConflict('QS allocation release permission changes its original allocation')
    for ref in action_input.residual_obligation_refs:
        same_engagement(read(ref, QSTransitionObligationView))
    for ref in action_input.deliverable_refs:
        document = same_engagement(read(ref, QSTransitionDeliverableView))
        if document.historical_author_id != document.author_actor_id:
            raise TaskConflict('QS transition document changes its historical author')
        unique_refs(document.existing_use_right_refs)
        for right_ref in document.existing_use_right_refs:
            if right_ref.key() in sources:
                right = read(right_ref, ArchitectExistingUseRightView)
                if right.deliverable_ref.key() != document.ref.key():
                    raise TaskConflict('QS transition use right changes its original document')
    for ref in engagement.execution_refs:
        if ref.key() in sources:
            execution = read(ref, ArchitectTransitionExecutionView)
            if (execution.organization_id != organization_id or execution.run_id != context.run_id
                    or execution.engagement_ref.id != engagement.ref.id):
                raise TaskConflict('QS transition history changes its original run, firm or service')
            if execution.business_key == basis.business_key and execution.basis_ref.key() in sources:
                original = read(execution.basis_ref, ArchitectTransitionBasisView)
                if (original.engagement_ref != execution.engagement_ref or original.scope != execution.scope
                        or original.business_key != execution.business_key):
                    raise TaskConflict('QS transition execution substitutes its original basis or scope')
    if basis.recall_plan is not None:
        plan = basis.recall_plan
        unique_refs([item.task_ref for item in plan.items])
        for item in plan.items:
            unique_refs(item.dependency_refs)
        if plan.work_profile_ref.key() in sources:
            work = same_engagement(read(plan.work_profile_ref, ArchitectRecallWorkProfileView))
            if work.organization_id != organization_id or work.author_organization_id != organization_id:
                raise TaskConflict('QS recall work profile changes its original firm or author')
            unique_refs([resource.ref for resource in work.resources])
            unique_refs([commitment.commitment_ref for commitment in work.commitments])
    if basis.package is not None:
        package = basis.package
        if package.engagement_ref.key() != engagement.ref.key() or package.basis_ref.key() != basis.ref.key():
            raise TaskConflict('QS handover package changes its original service or basis')
        for field in ('deliverable_refs', 'access_basis_refs', 'release_allocation_refs',
                'retain_allocation_refs', 'remaining_task_refs', 'remaining_obligation_refs'):
            unique_refs(getattr(package, field))
        for ref in package.access_basis_refs:
            if ref.key() in sources:
                access = read(ref, ArchitectTransitionAccessView)
                if access.deliverable_ref.key() in sources:
                    document = read(access.deliverable_ref, QSTransitionDeliverableView)
                    same_engagement(document)
                    if access.author_organization_id != document.rights_controller_organization_id:
                        raise TaskConflict('QS handover access changes its original rights controller')
    for ref in basis.recipient_acceptance_refs:
        if ref.key() in sources:
            acceptance = same_engagement(read(ref, QSHandoverAcceptanceView))
            if acceptance.recipient_id != acceptance.author_actor_id:
                raise TaskConflict('QS handover acceptance changes its independent recipient author')

    # QS-specific sources retain original provider and contractual duty identities.
    for ref in action_input.residual_obligation_refs:
        obligation = read(ref, QSTransitionObligationView)
        if obligation.contract_ref.key() in sources:
            contract = read(obligation.contract_ref, QSTransitionContractView)
            if obligation.debtor_id != contract.debtor_id or obligation.payee_id != contract.payee_id:
                raise TaskConflict('QS transition obligation substitutes its original contract debtor or payee')
        unique_refs(obligation.supporting_task_refs)
        if not {ref.key() for ref in obligation.supporting_task_refs} <= {ref.key() for ref in engagement.task_refs}:
            raise TaskConflict('QS remaining obligation references support outside its original service task directory')
        for task_ref in obligation.supporting_task_refs:
            task = same_engagement(read(task_ref, QSTransitionTaskView))
            if (task.organization_id != organization_id or task.author_organization_id != organization_id
                    or not (scope_covers(task.scope, obligation.origin_scope)
                        or scope_covers(obligation.origin_scope, task.scope))):
                raise TaskConflict('QS remaining obligation borrows another firm or out-of-scope support task')
    for ref in action_input.deliverable_refs:
        document = read(ref, QSTransitionDeliverableView)
        unique_refs(document.price_source_refs)
        unique_refs(document.measurement_trace_refs)
        unique_refs(document.private_client_record_refs)
        for source_ref in [*document.price_source_refs, *document.measurement_trace_refs]:
            if source_ref.key() in sources:
                source = read(source_ref, QSTransitionSourceView)
                if source.provider_organization_id != source.author_organization_id:
                    raise TaskConflict('QS transition substitutes its original price or measurement provider')

    def supplied_estimate(task):
        if task.work_estimate_ref.key() in sources:
            estimate = read(task.work_estimate_ref, QSReviewEstimateView)
            if (estimate.task_ref != task.ref or estimate.work_profile_ref != task.work_profile_ref
                    or estimate.organization_id != task.organization_id
                    or estimate.author_organization_id != task.organization_id
                    or estimate.function_code != task.function_code):
                raise TaskConflict('QS review estimate substitutes its original task, method or organization')

    for ref in action_input.task_refs:
        supplied_estimate(read(ref, QSTransitionTaskView))
    for ref in basis.recipient_acceptance_refs:
        if ref.key() not in sources:
            continue
        acceptance = read(ref, QSHandoverAcceptanceView)
        unique_refs(acceptance.reviewed_deliverable_refs)
        unique_refs(acceptance.source_access_refs)
        if acceptance.review_task_ref.key() in sources:
            task = same_engagement(read(acceptance.review_task_ref, QSTransitionTaskView))
            supplied_estimate(task)
        for access_ref in acceptance.source_access_refs:
            if access_ref.key() in sources:
                access = read(access_ref, QSTransitionSourceAccessView)
                if access.recipient_id != acceptance.recipient_id:
                    raise TaskConflict('QS source access substitutes its original successor recipient')
    # Permissions, source digests, recall effort/capacity and retained fee/client/
    # dispute-support obligations remain original processor checks.
