"""Bind original A05 native design registration to the A06 integration assembler."""
from copy import deepcopy

from integration.architect_integration_actions import ArchitectIntegrationActionAssembler
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskConflict, TaskIdentity


def prepare_architect_registered_design(assembler, *, context, action_input, selection,
        read_design, validate_mapping, read_guard):
    """Use the original registered draft and independent actual receipt checks.

    Caller holds its application source guard. The reader supplies the original
    A05 submission/identity/versions, separately authorized history context and
    independent history/current/receipt-relation validators. Native registration
    grants no integrated design, technical review, approval or use permission.
    """
    if (not isinstance(assembler, ArchitectIntegrationActionAssembler) or assembler.source_mode != 'formal'
            or not all(callable(f) for f in (read_design, validate_mapping, read_guard))):
        raise ValueError('Registered design input requires original formal A06 assembler and source callbacks')
    parameters = read_design(context=context.model_copy(deep=True),
        source_task_sha256=selection['source_task_sha256'])
    required = {'design_submission', 'design_identity', 'design_execution_versions',
        'design_read_context', 'validate_history', 'validate_current', 'validate_receipt_relation'}
    if (not isinstance(parameters, dict) or set(parameters) != required
            or not isinstance(parameters['design_identity'], TaskIdentity)
            or parameters['design_identity'].key != selection['source_task_sha256']
            or parameters['design_identity'].action_id != 'ARCHITECT-A05'
            or parameters['design_identity'].run_id != context.run_id):
        raise TaskConflict('Design reader substituted the selected original A05 task')
    registration = Reference.model_validate(selection['registration_ref'])
    native = Reference.model_validate(selection['native_evidence_ref'])
    relations = [Reference.model_validate(r) for r in selection['relation_evidence_refs']]
    if registration.kind != 'DesignRegistration' or native.kind != 'Evidence' or (
            not relations or len(set(relations)) != len(relations)
            or native in relations or any(r.kind != 'Evidence' for r in relations)):
        raise TaskConflict('Design input needs original native registration and distinct relation evidence')
    result = assembler.build_from_registered_design(context, **parameters, registration_ref=registration,
        native_evidence_ref=native, native_source_sha256=selection['native_source_sha256'],
        relation_evidence_refs=relations, read_guard=read_guard, **deepcopy(action_input))
    if result['kind'] != 'prepared':
        raise TaskConflict('Original design registration remains unavailable: ' + result['reason_code'])
    prepared = result['invocation']
    if (prepared.context != context or prepared.action_input.model_dump(mode='json') != action_input
            or result['provenance']['task_sha256'] != selection['source_task_sha256']
            or result['provenance']['native_source_sha256'] != selection['native_source_sha256']
            or validate_mapping(context=context.model_copy(deep=True), action_input=deepcopy(action_input),
                selection=deepcopy(selection), provenance=deepcopy(result['provenance']),
                reading=prepared.reading) is not True):
        raise TaskConflict('Independent design registration mapping rejected the original A06 invocation')
    prepared.reading.recheck()
    return prepared, deepcopy(result['provenance'])
