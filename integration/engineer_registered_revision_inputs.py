"""Bind original Engineer A09 native revision registration to the A07 deliverable assembler."""
from copy import deepcopy

from integration.engineer_deliverable_actions import EngineerDeliverableActionAssembler
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskConflict, TaskIdentity


def prepare_engineer_registered_revision(assembler, *, context, action_input, selection,
        read_revision, validate_mapping, read_guard):
    """Use the original registered revision draft and independent actual receipt checks.

    Caller holds its application source guard. The reader supplies the original
    A09 submission/identity/versions, separately authorized history context and
    independent history/current/receipt-relation validators. Native registration
    grants no resolved issue, completed revision work, signing or use permission.
    """
    if (not isinstance(assembler, EngineerDeliverableActionAssembler) or assembler.source_mode != 'formal'
            or not all(callable(f) for f in (read_revision, validate_mapping, read_guard))):
        raise ValueError('Registered revision input requires original formal Engineer A07 assembler and source callbacks')
    parameters = read_revision(context=context.model_copy(deep=True),
        source_task_sha256=selection['source_task_sha256'])
    required = {'revision_submission', 'revision_identity', 'revision_execution_versions',
        'revision_read_context', 'validate_history', 'validate_current', 'validate_receipt_relation'}
    if (not isinstance(parameters, dict) or set(parameters) != required
            or not isinstance(parameters['revision_identity'], TaskIdentity)
            or parameters['revision_identity'].key != selection['source_task_sha256']
            or parameters['revision_identity'].action_id != 'ENGINEER-A09'
            or parameters['revision_identity'].run_id != context.run_id):
        raise TaskConflict('Revision reader substituted the selected original A09 task')
    registration = Reference.model_validate(selection['registration_ref'])
    native = Reference.model_validate(selection['native_evidence_ref'])
    relations = [Reference.model_validate(r) for r in selection['relation_evidence_refs']]
    if registration.kind != 'EngineerRevisionRegistration' or native.kind != 'Evidence' or (
            not relations or len(set(relations)) != len(relations)
            or native in relations or any(r.kind != 'Evidence' for r in relations)):
        raise TaskConflict('Revision input needs original native registration and distinct relation evidence')
    result = assembler.build_from_registered_revision(context, **parameters, registration_ref=registration,
        native_evidence_ref=native, native_source_sha256=selection['native_source_sha256'],
        relation_evidence_refs=relations, read_guard=read_guard, **deepcopy(action_input))
    if result['kind'] != 'prepared':
        raise TaskConflict('Original revision registration remains unavailable: ' + result['reason_code'])
    prepared = result['invocation']
    if (prepared.context != context or prepared.action_input.model_dump(mode='json') != action_input
            or result['provenance']['task_sha256'] != selection['source_task_sha256']
            or result['provenance']['native_source_sha256'] != selection['native_source_sha256']
            or validate_mapping(context=context.model_copy(deep=True), action_input=deepcopy(action_input),
                selection=deepcopy(selection), provenance=deepcopy(result['provenance']),
                reading=prepared.reading) is not True):
        raise TaskConflict('Independent revision registration mapping rejected the original Engineer A07 invocation')
    prepared.reading.recheck()
    return prepared, deepcopy(result['provenance'])
