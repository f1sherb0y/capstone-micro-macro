"""Freeze original Architect A07 deliverables, completion and publication sources."""
from copy import deepcopy
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import ClassVar

from integration.architect_opportunity_actions import ArchitectOpportunityActionAssembler, PreparedArchitectOpportunity
from src.actions.contracts.architect_submission_objects import (
    ArchitectSubmissionDeliverableView, ArchitectSubmissionProfileView, ArchitectPublicationAuthorityView,
    ArchitectTaskCompletionView, ArchitectSubmissionCheckView, ArchitectSubmissionReviewView,
    ArchitectSubmissionIssueView, ArchitectSubmissionReleaseBasisView, ArchitectSubmissionReleaseRecordView,
    ArchitectSubmissionSavedView, architect_submission_schemas,
)
from src.actions.contracts.architect_planning_objects import ArchitectPlanningWorkFactView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.common import ActionContext
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class PreparedArchitectDeliverable(PreparedArchitectOpportunity):
    ACTION_ID: ClassVar[str] = 'ARCHITECT-A07'


class ArchitectDeliverableActionAssembler(ArchitectOpportunityActionAssembler):
    """Keep requested use, actual work and independent release evidence distinct.

    The original processor checks completion, investment, recipient authority,
    dependencies, review/release conditions and prior submission identity.
    Assembly records no submission, delivery, fee, acceptance or allowed use.
    """
    ACTION_ID = 'ARCHITECT-A07'
    SOURCE_SCHEMAS = staticmethod(architect_submission_schemas)

    def build_from_registered_integration(self, context, *, integration_submission, integration_identity,
            integration_execution_versions, integration_read_context, registration_ref, native_evidence_ref,
            native_source_sha256, relation_evidence_refs, read_guard, validate_history,
            validate_current, validate_receipt_relation, **source_refs):
        """Link an actual A06 artifact while retaining A07's independent gates."""
        from integration.architect_integration_registration_handoff import prepare_architect_integration_registration_handoff
        from integration.architect_integration_results import ArchitectIntegrationResultWorker
        from integration.architect_submission import ArchitectResultSubmission
        from integration.macro_views import AuthorizedMacroViewAssembler
        from src.actions.contracts.architect_integration_objects import architect_integration_schemas
        from src.actions.contracts.references import ActionReadView

        if (not isinstance(integration_submission, ArchitectResultSubmission)
                or integration_submission.ACTION_ID != 'ARCHITECT-A06'
                or not isinstance(integration_submission.worker, ArchitectIntegrationResultWorker)
                or integration_submission.worker.registry is not self.registry
                or integration_submission.worker.store.run_id != self.organizations.run_id or self.source_mode != 'formal'
                or not all(callable(callback) for callback in
                    (read_guard, validate_history, validate_current, validate_receipt_relation))):
            raise TaskConflict('Integration handoff requires original A06 submission/worker and actual guarded source checks')
        context = self._context(context)
        own_context = ActionContext.model_validate(integration_read_context).model_copy(deep=True)
        if (own_context.contract_ref.kind != 'ActionContract' or own_context.contract_ref.id != 'ARCHITECT-A06'
                or own_context.execution_mode == 'offline_fixture'
                or any(getattr(own_context, name) != getattr(context, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('Integration history requires separate current A06 authority at the same A07 read time')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(source_refs)
        with read_guard(context.model_copy(deep=True)):
            receipt = integration_submission.read_receipt(integration_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected integration submission cannot prove actual deliverable registration')
            own_views = AuthorizedMacroViewAssembler(self.organizations, self.provider, architect_integration_schemas(),
                macro_version=self.macro_version, source_mode='formal')
            own_resolver = own_views.build_resolver(own_context, 'ARCHITECT-A06', 'Architect')
            own_reading = ActionReadView(own_context, own_resolver, self.organizations, 'ARCHITECT-A06', 'Architect')
            saved = integration_submission.worker.read_completed(integration_identity, current_context=own_context,
                reading=own_reading, execution_versions=integration_execution_versions, validate_current=validate_history)
            reading = self.build_result_reading(context)
            preflight = SimpleNamespace(context=context, action_input=action_input, reading=reading)

            def validate_link(**sources):
                if (sources['saved'].identity.as_dict() != receipt['identity']
                        or sources['saved'].record_sha256 != receipt['record_sha256']):
                    raise TaskConflict('Integration receipt substitutes its original saved draft result')
                return (validate_current(**sources) is True
                    and validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True)

            handoff = prepare_architect_integration_registration_handoff(saved, invocation=preflight,
                registration_ref=registration_ref, native_evidence_ref=native_evidence_ref,
                native_source_sha256=native_source_sha256, relation_evidence_refs=relation_evidence_refs,
                validate_current=validate_link)
            if integration_submission.read_receipt(integration_identity) != receipt:
                raise TaskConflict('Original integration receipt changed during registered-artifact linkage')
            own_reading.recheck()
            if handoff['kind'] != 'prepared':
                return handoff
            invocation = self.build(context, **source_refs)
            if any(invocation.reading._reads.get(key) != row for key, row in reading._reads.items()):
                raise TaskConflict('Registered integration linkage differs from the actual frozen A07 source snapshot')
            reading.recheck()
            invocation.reading.recheck()
            if integration_submission.read_receipt(integration_identity) != receipt:
                raise TaskConflict('Original integration receipt changed before A07 source assembly completed')
            return {**handoff, 'provenance': {**handoff['provenance'], 'submission': deepcopy(receipt)},
                'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}

    def build(self, context, *, scope, deliverable_ref, dependency_refs,
            task_completion_ref, requested_use, recipient_ids,
            review_requirement_ref, release_basis_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'deliverable_ref': deliverable_ref, 'dependency_refs': dependency_refs,
            'task_completion_ref': task_completion_ref, 'requested_use': requested_use,
            'recipient_ids': recipient_ids, 'review_requirement_ref': review_requirement_ref,
            'release_basis_refs': release_basis_refs}, prepared_type=PreparedArchitectDeliverable,
            validate_sources=validate_architect_deliverable_sources)


def validate_architect_deliverable_sources(action_input, *, context, organization_id, sources):
    """Check original task/content/version associations without determining release."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Architect deliverable lacks its exact original concrete source')
        return row

    def same_deliverable(row, target):
        if row.deliverable_ref.key() != target.ref.key():
            raise TaskConflict('Architect submission source changes its original deliverable version')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Architect submission changes its original invocation scope')
    unique_refs(action_input.dependency_refs)
    unique_refs(action_input.release_basis_refs)
    deliverable = read(action_input.deliverable_ref, ArchitectSubmissionDeliverableView)
    if deliverable.author_organization_id != organization_id:
        raise TaskConflict('Architect submission borrows another organization authored deliverable')
    completion = same_deliverable(read(action_input.task_completion_ref, ArchitectTaskCompletionView), deliverable)
    if (completion.organization_id != organization_id
            or completion.task_ref.key() != deliverable.task_ref.key()
            or completion.content_sha256 != deliverable.content_sha256):
        raise TaskConflict('Architect completion changes original task, organization or content')
    unique_refs(completion.work_fact_refs)
    unique_refs(completion.check_refs)
    for ref in completion.work_fact_refs:
        if ref.key() in sources:
            fact = read(ref, ArchitectPlanningWorkFactView)
            if fact.organization_id != organization_id or fact.task_ref.key() != completion.task_ref.key():
                raise TaskConflict('Architect submission investment changes original task or organization')
    for ref in completion.check_refs:
        if ref.key() in sources:
            check = same_deliverable(read(ref, ArchitectSubmissionCheckView), deliverable)
            if check.task_ref.key() != completion.task_ref.key() or check.content_sha256 != deliverable.content_sha256:
                raise TaskConflict('Architect compilation check changes original task or content')
    dependencies = [read(ref, ArchitectSubmissionDeliverableView) for ref in action_input.dependency_refs]
    for target in [deliverable, *dependencies]:
        unique_refs(target.dependency_refs)
        unique_refs(target.unresolved_issue_refs)
        for ref in target.unresolved_issue_refs:
            if ref.key() in sources:
                same_deliverable(read(ref, ArchitectSubmissionIssueView), target)
    if action_input.review_requirement_ref is not None:
        review = same_deliverable(read(action_input.review_requirement_ref, ArchitectSubmissionReviewView), deliverable)
        if review.requested_use != action_input.requested_use:
            raise TaskConflict('Architect review requirement changes its original requested use')
    for ref in action_input.release_basis_refs:
        basis = same_deliverable(read(ref, ArchitectSubmissionReleaseBasisView), deliverable)
        if basis.requested_use != action_input.requested_use:
            raise TaskConflict('Architect release basis changes its original requested use')
        if basis.original_record_ref.key() in sources:
            record = same_deliverable(read(basis.original_record_ref, ArchitectSubmissionReleaseRecordView), deliverable)
            if record.requested_use != basis.requested_use or record.code != basis.code:
                raise TaskConflict('Architect release basis changes its original record use or condition')
    if deliverable.submission_profile_ref.key() not in sources:
        return
    profile = same_deliverable(read(deliverable.submission_profile_ref, ArchitectSubmissionProfileView), deliverable)
    if profile.organization_id != organization_id or profile.operation_id != context.operation_id:
        raise TaskConflict('Architect submission profile changes original organization or operation')
    unique_refs(profile.completion_check_refs)
    unique_refs(profile.recipient_refs)
    unique_refs(profile.submission_refs)
    if profile.publication_authority_ref.key() in sources:
        publication = same_deliverable(read(profile.publication_authority_ref, ArchitectPublicationAuthorityView), deliverable)
        if (publication.organization_id != organization_id or publication.actor_id != context.actor_id
                or publication.function_ref.key() != context.function_ref.key()):
            raise TaskConflict('Architect publication authority changes its original actor or function')
    for ref in profile.submission_refs:
        if ref.key() in sources:
            saved = same_deliverable(read(ref, ArchitectSubmissionSavedView), deliverable)
            if saved.organization_id != organization_id:
                raise TaskConflict('Architect submission history changes its original organization')
