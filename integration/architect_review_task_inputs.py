"""Bind an actual A07 review-task registration to the original A08 reviewer assembler."""
from copy import deepcopy

from integration.architect_review_actions import ArchitectReviewActionAssembler
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskConflict, TaskIdentity


def prepare_architect_received_review_task(assembler, *, context, action_input, selection,
        read_task, validate_mapping, read_guard):
    """Read actual original submission/history and independent review intake.

    Caller holds its application source guard. The reader supplies the actual
    A07 submission, identity, versions and separately authorized history context,
    plus independent history/current/receipt-relation validators. Submission
    acceptance alone never grants reviewer authority or proves task intake.
    """
    if (not isinstance(assembler, ArchitectReviewActionAssembler) or assembler.source_mode != 'formal'
            or not all(callable(f) for f in (read_task, validate_mapping, read_guard))):
        raise ValueError('Review task input requires original formal assembler and independent source callbacks')
    parameters = read_task(context=context.model_copy(deep=True),
        source_task_sha256=selection['source_task_sha256'])
    required = {'deliverable_submission', 'deliverable_identity', 'deliverable_execution_versions',
        'submission_read_context', 'validate_history', 'validate_current', 'validate_receipt_relation'}
    if (not isinstance(parameters, dict) or set(parameters) != required
            or not isinstance(parameters['deliverable_identity'], TaskIdentity)
            or parameters['deliverable_identity'].key != selection['source_task_sha256']
            or parameters['deliverable_identity'].action_id != 'ARCHITECT-A07'
            or parameters['deliverable_identity'].run_id != context.run_id):
        raise TaskConflict('Review task reader substituted the selected original A07 task')
    registration = Reference.model_validate(selection['registration_ref'])
    native = Reference.model_validate(selection['native_evidence_ref'])
    relations = [Reference.model_validate(r) for r in selection['relation_evidence_refs']]
    if registration.kind != 'ArchitectReviewTaskRegistration' or native.kind != 'Evidence' or (
            not relations or len(set(relations)) != len(relations)
            or native in relations or any(r.kind != 'Evidence' for r in relations)):
        raise TaskConflict('Review task needs original registration and distinct native/relation evidence')
    result = assembler.build_from_review_task(context, **parameters, registration_ref=registration,
        native_evidence_ref=native, native_source_sha256=selection['native_source_sha256'],
        relation_evidence_refs=relations, read_guard=read_guard, **deepcopy(action_input))
    if result['kind'] != 'prepared':
        raise TaskConflict('Original review task intake remains unavailable: ' + result['reason_code'])
    prepared = result['invocation']
    if (prepared.context != context or prepared.action_input.model_dump(mode='json') != action_input
            or result['provenance']['task_sha256'] != selection['source_task_sha256']
            or result['provenance']['native_source_sha256'] != selection['native_source_sha256']
            or validate_mapping(context=context.model_copy(deep=True), action_input=deepcopy(action_input),
                selection=deepcopy(selection), provenance=deepcopy(result['provenance']),
                reading=prepared.reading) is not True):
        raise TaskConflict('Independent review task mapping rejected the original reviewer invocation')
    prepared.reading.recheck()
    return prepared, deepcopy(result['provenance'])
