"""Bind original A06 native integration registration to the A07 deliverable assembler."""
from copy import deepcopy

from integration.architect_deliverable_actions import ArchitectDeliverableActionAssembler
from src.actions.contracts.common import Reference
from src.coordination.tasks import TaskConflict, TaskIdentity


def prepare_architect_registered_integration(assembler, *, context, action_input, selection,
        read_integration, validate_mapping, read_guard):
    """Use original registered artifact and independent receipt/content checks.

    Caller holds the application source guard. The reader supplies the original
    A06 submission/identity/versions, separately authorized history context and
    independent history/current/receipt-relation validators. A07 still checks
    completion, dependencies, intended use, recipients and release authority.
    """
    if (not isinstance(assembler, ArchitectDeliverableActionAssembler) or assembler.source_mode != 'formal'
            or not all(callable(f) for f in (read_integration, validate_mapping, read_guard))):
        raise ValueError('Registered integration requires original formal A07 assembler and source callbacks')
    parameters = read_integration(context=context.model_copy(deep=True),
        source_task_sha256=selection['source_task_sha256'])
    required = {'integration_submission', 'integration_identity', 'integration_execution_versions',
        'integration_read_context', 'validate_history', 'validate_current', 'validate_receipt_relation'}
    if (not isinstance(parameters, dict) or set(parameters) != required
            or not isinstance(parameters['integration_identity'], TaskIdentity)
            or parameters['integration_identity'].key != selection['source_task_sha256']
            or parameters['integration_identity'].action_id != 'ARCHITECT-A06'
            or parameters['integration_identity'].run_id != context.run_id):
        raise TaskConflict('Integration reader substituted the selected original A06 task')
    registration = Reference.model_validate(selection['registration_ref'])
    native = Reference.model_validate(selection['native_evidence_ref'])
    relations = [Reference.model_validate(r) for r in selection['relation_evidence_refs']]
    if registration.kind != 'IntegrationRegistration' or native.kind != 'Evidence' or (
            not relations or len(set(relations)) != len(relations)
            or native in relations or any(r.kind != 'Evidence' for r in relations)):
        raise TaskConflict('Integration input needs original native registration and distinct relation evidence')
    result = assembler.build_from_registered_integration(context, **parameters, registration_ref=registration,
        native_evidence_ref=native, native_source_sha256=selection['native_source_sha256'],
        relation_evidence_refs=relations, read_guard=read_guard, **deepcopy(action_input))
    if result['kind'] != 'prepared':
        raise TaskConflict('Original integration registration remains unavailable: ' + result['reason_code'])
    prepared = result['invocation']
    if (prepared.context != context or prepared.action_input.model_dump(mode='json') != action_input
            or result['provenance']['task_sha256'] != selection['source_task_sha256']
            or result['provenance']['native_source_sha256'] != selection['native_source_sha256']
            or validate_mapping(context=context.model_copy(deep=True), action_input=deepcopy(action_input),
                selection=deepcopy(selection), provenance=deepcopy(result['provenance']),
                reading=prepared.reading) is not True):
        raise TaskConflict('Independent integration registration mapping rejected the original A07 invocation')
    prepared.reading.recheck()
    return prepared, deepcopy(result['provenance'])
