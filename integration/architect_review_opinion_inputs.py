"""Bind a configured received reviewer opinion to the original A08 author assembler."""
from copy import deepcopy

from integration.architect_review_actions import ArchitectReviewActionAssembler
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskConflict, TaskIdentity


def prepare_architect_received_opinion(assembler, *, context, action_input, selection,
        read_opinion, validate_mapping, read_guard):
    """Use original receipt/history gates, never fabricate an author response.

    The caller holds its application source guard. The reader returns the
    actual reviewer submission/identity/versions, current reviewer read context
    and independent history/current/receipt-relation validators required by
    build_from_received_opinion. Explicit config pins receipt and evidence refs.
    """
    if (not isinstance(assembler, ArchitectReviewActionAssembler) or assembler.source_mode != 'formal'
            or not all(callable(f) for f in (read_opinion, validate_mapping, read_guard))):
        raise ValueError('Received review opinion requires original formal assembler and independent source callbacks')
    parameters = read_opinion(context=context.model_copy(deep=True),
        source_task_sha256=selection['source_task_sha256'])
    required = {'reviewer_submission', 'reviewer_identity', 'reviewer_execution_versions',
        'reviewer_read_context', 'validate_history', 'validate_current', 'validate_receipt_relation'}
    if (not isinstance(parameters, dict) or set(parameters) != required
            or not isinstance(parameters['reviewer_identity'], TaskIdentity)
            or parameters['reviewer_identity'].key != selection['source_task_sha256']
            or parameters['reviewer_identity'].action_id != 'ARCHITECT-A08'
            or parameters['reviewer_identity'].run_id != context.run_id):
        raise TaskConflict('Received opinion reader substituted the configured original reviewer task')
    receipt = Reference.model_validate(selection['receipt_ref'])
    native = Reference.model_validate(selection['native_evidence_ref'])
    relations = [Reference.model_validate(r) for r in selection['relation_evidence_refs']]
    if receipt.kind != 'ArchitectReviewOpinionReceipt' or native.kind != 'Evidence' or (
            not relations or len(set(relations)) != len(relations)
            or native in relations or any(r.kind != 'Evidence' for r in relations)):
        raise TaskConflict('Received opinion needs a distinct native receipt and independent relation evidence')
    result = assembler.build_from_received_opinion(context, **parameters, receipt_ref=receipt,
        native_evidence_ref=native, native_source_sha256=selection['native_source_sha256'],
        relation_evidence_refs=relations, read_guard=read_guard, **deepcopy(action_input))
    if result['kind'] != 'prepared':
        # No invocation is frozen by the original assembler while receipt or
        # author task is unavailable. Do not fall back to ordinary A08 assembly.
        raise TaskConflict('Original review opinion or author task remains unavailable: ' + result['reason_code'])
    prepared = result['invocation']
    if (prepared.context != context or prepared.action_input.model_dump(mode='json') != action_input
            or result['provenance']['task_sha256'] != selection['source_task_sha256']
            or result['provenance']['native_source_sha256'] != selection['native_source_sha256']
            or validate_mapping(context=context.model_copy(deep=True), action_input=deepcopy(action_input),
                selection=deepcopy(selection), provenance=deepcopy(result['provenance']),
                reading=prepared.reading) is not True):
        raise TaskConflict('Independent opinion mapping validation rejected the original author invocation')
    prepared.reading.recheck()
    return prepared, deepcopy(result['provenance'])
