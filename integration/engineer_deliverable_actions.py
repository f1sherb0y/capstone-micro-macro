"""Freeze original Engineer A07 deliverables, completion and publication sources."""
from copy import deepcopy
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import ClassVar

from integration.engineer_opportunity_actions import EngineerOpportunityActionAssembler, PreparedEngineerOpportunity
from src.actions.contracts.engineer_submission_objects import (
    EngineerSubmissionDeliverableView, EngineerSubmissionProfileView, EngineerPublicationAuthorityView,
    EngineerTaskCompletionView, EngineerSubmissionCheckView, EngineerSigningBasisView, EngineerSigningVerificationView,
    EngineerSubmissionIssueView, EngineerSubmissionReleaseBasisView, EngineerSubmissionReleaseRecordView,
    EngineerSubmissionSavedView, engineer_submission_schemas,
)
from src.actions.contracts.engineer_planning_objects import EngineerPlanningWorkFactView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.common import ActionContext
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class PreparedEngineerDeliverable(PreparedEngineerOpportunity):
    ACTION_ID: ClassVar[str] = 'ENGINEER-A07'


class EngineerDeliverableActionAssembler(EngineerOpportunityActionAssembler):
    """Keep requested use, actual work and independent release evidence distinct.

    The original processor checks completion, investment, recipient authority,
    dependencies, independent signing/release conditions and prior submission identity.
    Assembly records no submission, delivery, fee, acceptance or allowed use.
    """
    ACTION_ID = 'ENGINEER-A07'
    SOURCE_SCHEMAS = staticmethod(engineer_submission_schemas)

    def build_from_registered_design(self, context, *, design_submission, design_identity,
            design_execution_versions, design_read_context, registration_ref, native_evidence_ref,
            native_source_sha256, relation_evidence_refs, read_guard, validate_history,
            validate_current, validate_receipt_relation, **source_refs):
        """Link an actual A05 artifact while retaining A07's independent gates."""
        return self._build_from_registered_professional_work(context, source_action_id='ENGINEER-A05',
            design_submission=design_submission, design_identity=design_identity,
            design_execution_versions=design_execution_versions, design_read_context=design_read_context,
            registration_ref=registration_ref, native_evidence_ref=native_evidence_ref,
            native_source_sha256=native_source_sha256, relation_evidence_refs=relation_evidence_refs,
            read_guard=read_guard, validate_history=validate_history, validate_current=validate_current,
            validate_receipt_relation=validate_receipt_relation, **source_refs)

    def build_from_registered_revision(self, context, *, revision_submission, revision_identity,
            revision_execution_versions, revision_read_context, registration_ref, native_evidence_ref,
            native_source_sha256, relation_evidence_refs, read_guard, validate_history,
            validate_current, validate_receipt_relation, **source_refs):
        """Link actual A09 revision lineage while retaining A07's independent gates."""
        return self._build_from_registered_professional_work(context, source_action_id='ENGINEER-A09',
            design_submission=revision_submission, design_identity=revision_identity,
            design_execution_versions=revision_execution_versions, design_read_context=revision_read_context,
            registration_ref=registration_ref, native_evidence_ref=native_evidence_ref,
            native_source_sha256=native_source_sha256, relation_evidence_refs=relation_evidence_refs,
            read_guard=read_guard, validate_history=validate_history, validate_current=validate_current,
            validate_receipt_relation=validate_receipt_relation, **source_refs)

    def _build_from_registered_professional_work(self, context, *, source_action_id,
            design_submission, design_identity, design_execution_versions, design_read_context,
            registration_ref, native_evidence_ref, native_source_sha256, relation_evidence_refs,
            read_guard, validate_history, validate_current, validate_receipt_relation, **source_refs):
        from integration.engineer_design_registration_handoff import prepare_engineer_design_registration_handoff
        from integration.engineer_design_results import EngineerDesignResultWorker
        from integration.engineer_change_revision_registration_handoff import prepare_engineer_change_revision_registration_handoff
        from integration.engineer_change_results import EngineerChangeResultWorker
        from integration.engineer_submission import EngineerResultSubmission
        from integration.macro_views import AuthorizedMacroViewAssembler
        from src.actions.contracts.engineer_design_objects import engineer_design_schemas
        from src.actions.contracts.engineer_change_objects import engineer_change_schemas
        from src.actions.contracts.references import ActionReadView

        if source_action_id == 'ENGINEER-A05':
            worker_type, schemas, prepare_handoff = (EngineerDesignResultWorker, engineer_design_schemas,
                prepare_engineer_design_registration_handoff)
        elif source_action_id == 'ENGINEER-A09':
            worker_type, schemas, prepare_handoff = (EngineerChangeResultWorker, engineer_change_schemas,
                prepare_engineer_change_revision_registration_handoff)
        else:
            raise TaskConflict('Professional registration requires original A05 or A09 source action')
        if (not isinstance(design_submission, EngineerResultSubmission)
                or design_submission.ACTION_ID != source_action_id
                or not isinstance(design_submission.worker, worker_type)
                or design_submission.worker.registry is not self.registry
                or design_submission.worker.store.run_id != self.organizations.run_id or self.source_mode != 'formal'
                or not all(callable(callback) for callback in
                    (read_guard, validate_history, validate_current, validate_receipt_relation))):
            raise TaskConflict('Professional handoff requires original source submission/worker and actual guarded checks')
        context = self._context(context)
        own_context = ActionContext.model_validate(design_read_context).model_copy(deep=True)
        if (own_context.contract_ref.kind != 'ActionContract' or own_context.contract_ref.id != source_action_id
                or own_context.execution_mode == 'offline_fixture'
                or any(getattr(own_context, name) != getattr(context, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('Professional history requires separate current source-action authority at A07 read time')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(source_refs)
        with read_guard(context.model_copy(deep=True)):
            receipt = design_submission.read_receipt(design_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected design submission cannot prove actual deliverable registration')
            own_views = AuthorizedMacroViewAssembler(self.organizations, self.provider, schemas(),
                macro_version=self.macro_version, source_mode='formal')
            own_resolver = own_views.build_resolver(own_context, source_action_id, 'Engineer')
            own_reading = ActionReadView(own_context, own_resolver, self.organizations, source_action_id, 'Engineer')
            saved = design_submission.worker.read_completed(design_identity, current_context=own_context,
                reading=own_reading, execution_versions=design_execution_versions, validate_current=validate_history)
            reading = self.build_result_reading(context)
            preflight = SimpleNamespace(context=context, action_input=action_input, reading=reading)

            def validate_link(**sources):
                if (sources['saved'].identity.as_dict() != receipt['identity']
                        or sources['saved'].record_sha256 != receipt['record_sha256']):
                    raise TaskConflict('Design receipt substitutes its original saved draft result')
                return (validate_current(**sources) is True
                    and validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True)

            handoff = prepare_handoff(saved, invocation=preflight,
                registration_ref=registration_ref, native_evidence_ref=native_evidence_ref,
                native_source_sha256=native_source_sha256, relation_evidence_refs=relation_evidence_refs,
                validate_current=validate_link)
            if design_submission.read_receipt(design_identity) != receipt:
                raise TaskConflict('Original design receipt changed during registered-artifact linkage')
            own_reading.recheck()
            if handoff['kind'] != 'prepared':
                return handoff
            invocation = self.build(context, **source_refs)
            if any(invocation.reading._reads.get(key) != row for key, row in reading._reads.items()):
                raise TaskConflict('Registered design linkage differs from the actual frozen A07 source snapshot')
            reading.recheck()
            invocation.reading.recheck()
            if design_submission.read_receipt(design_identity) != receipt:
                raise TaskConflict('Original design receipt changed before A07 source assembly completed')
            return {**handoff, 'provenance': {**handoff['provenance'], 'submission': deepcopy(receipt)},
                'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}

    def build(self, context, *, scope, deliverable_ref, task_completion_ref,
            requested_use, recipient_ids, signing_basis_refs, release_basis_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'deliverable_ref': deliverable_ref,
            'task_completion_ref': task_completion_ref, 'requested_use': requested_use,
            'recipient_ids': recipient_ids, 'signing_basis_refs': signing_basis_refs,
            'release_basis_refs': release_basis_refs}, prepared_type=PreparedEngineerDeliverable,
            validate_sources=validate_engineer_deliverable_sources)


def validate_engineer_deliverable_sources(action_input, *, context, organization_id, sources):
    """Check original task/content/version associations without determining release."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Engineer deliverable lacks its exact original concrete source')
        return row

    def same_deliverable(row, target):
        if row.deliverable_ref.key() != target.ref.key():
            raise TaskConflict('Engineer submission source changes its original deliverable version')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Engineer submission changes its original invocation scope')
    unique_refs(action_input.signing_basis_refs)
    unique_refs(action_input.release_basis_refs)
    deliverable = read(action_input.deliverable_ref, EngineerSubmissionDeliverableView)
    if deliverable.author_organization_id != organization_id:
        raise TaskConflict('Engineer submission borrows another organization authored deliverable')
    completion = same_deliverable(read(action_input.task_completion_ref, EngineerTaskCompletionView), deliverable)
    if (completion.organization_id != organization_id
            or completion.task_ref.key() != deliverable.task_ref.key()
            or completion.content_sha256 != deliverable.content_sha256):
        raise TaskConflict('Engineer completion changes original task, organization or content')
    unique_refs(completion.work_fact_refs)
    unique_refs(completion.check_refs)
    for ref in completion.work_fact_refs:
        if ref.key() in sources:
            fact = read(ref, EngineerPlanningWorkFactView)
            if fact.organization_id != organization_id or fact.task_ref.key() != completion.task_ref.key():
                raise TaskConflict('Engineer submission investment changes original task or organization')
    for ref in completion.check_refs:
        if ref.key() in sources:
            check = same_deliverable(read(ref, EngineerSubmissionCheckView), deliverable)
            if check.task_ref.key() != completion.task_ref.key() or check.content_sha256 != deliverable.content_sha256:
                raise TaskConflict('Engineer compilation check changes original task or content')
    dependencies = [read(ref, EngineerSubmissionDeliverableView)
        for ref in deliverable.dependency_refs if ref.key() in sources]
    for target in [deliverable, *dependencies]:
        unique_refs(target.dependency_refs)
        unique_refs(target.unresolved_issue_refs)
        for ref in target.unresolved_issue_refs:
            if ref.key() in sources:
                same_deliverable(read(ref, EngineerSubmissionIssueView), target)
    for ref in action_input.signing_basis_refs:
        basis = same_deliverable(read(ref, EngineerSigningBasisView), deliverable)
        if (basis.content_sha256 != deliverable.content_sha256
                or basis.appointment_ref.key() != deliverable.appointment_ref.key()
                or basis.requested_use != action_input.requested_use):
            raise TaskConflict('Engineer signing basis changes original content, appointment or use')
        if basis.original_record_ref.key() in sources:
            record = same_deliverable(read(basis.original_record_ref, EngineerSigningVerificationView), deliverable)
            if (record.content_sha256 != deliverable.content_sha256
                    or record.appointment_ref.key() != basis.appointment_ref.key()
                    or record.requested_use != basis.requested_use or record.code != basis.code):
                raise TaskConflict('Engineer signing verification changes its original content, appointment or condition')
        # The original processor verifies signer/issuer authority, actual record
        # digest, disciplines and satisfaction. Presence does not permit signing.
    for ref in action_input.release_basis_refs:
        basis = same_deliverable(read(ref, EngineerSubmissionReleaseBasisView), deliverable)
        if basis.requested_use != action_input.requested_use:
            raise TaskConflict('Engineer release basis changes its original requested use')
        if basis.original_record_ref.key() in sources:
            record = same_deliverable(read(basis.original_record_ref, EngineerSubmissionReleaseRecordView), deliverable)
            if record.requested_use != basis.requested_use or record.code != basis.code:
                raise TaskConflict('Engineer release basis changes its original record use or condition')
    if deliverable.submission_profile_ref.key() not in sources:
        return
    profile = same_deliverable(read(deliverable.submission_profile_ref, EngineerSubmissionProfileView), deliverable)
    if profile.organization_id != organization_id or profile.operation_id != context.operation_id:
        raise TaskConflict('Engineer submission profile changes original organization or operation')
    unique_refs(profile.completion_check_refs)
    unique_refs(profile.recipient_refs)
    unique_refs(profile.submission_refs)
    if profile.publication_authority_ref.key() in sources:
        publication = same_deliverable(read(profile.publication_authority_ref, EngineerPublicationAuthorityView), deliverable)
        if (publication.organization_id != organization_id or publication.actor_id != context.actor_id
                or publication.function_ref.key() != context.function_ref.key()):
            raise TaskConflict('Engineer publication authority changes its original actor or function')
    for ref in profile.submission_refs:
        if ref.key() in sources:
            saved = same_deliverable(read(ref, EngineerSubmissionSavedView), deliverable)
            if saved.organization_id != organization_id:
                raise TaskConflict('Engineer submission history changes its original organization')
