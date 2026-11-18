"""Explicit actual closeout-feedback mapping to current Owner continuation sources."""
from copy import deepcopy

from integration.owner_closeout_feedback import OwnerCloseoutSubmissionFeedback
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_closeout_objects import OwnerCloseoutDecisionView
from src.actions.contracts.owner_continuation_objects import (
    OwnerCloseoutContinuationBasisView, OwnerContinuationContractView, OwnerContinuationDutyView,
    OwnerContinuationProfileView, OwnerContinuationStateView,
)
from src.actions.contracts.owner_payment_objects import OwnerPaymentObligationView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


def read_closeout_continuation_basis(prepared, *, feedback_record_sha256, basis_ref,
        read_closeout_feedback, validate_relation):
    """Consume authenticated historical feedback through an independent current mapping.

    read_closeout_feedback(context, feedback_record_sha256) reads the original
    persisted A12 feedback under its own authorized history/source guard. It
    must not project historical A12 contracts as current A13 contracts. The
    actual mapping/source application supplies the basis and validates each
    retained, settled, released or superseded residual item independently.
    This operation creates no transition, successor, cash or responsibility release.
    """
    context, reading = prepared.context, prepared.reading
    if (prepared.ACTION_ID != 'OWN-A13' or context.execution_mode == 'offline_fixture'
            or not callable(read_closeout_feedback) or not callable(validate_relation)):
        raise TaskConflict('Closeout continuation requires formal current A13 input and authorized history/mapping validators')
    try:
        reading.check_method_context(context, 'OWN-A13')
        record = read_closeout_feedback(context=context.model_copy(deep=True), feedback_record_sha256=feedback_record_sha256)
        if (not isinstance(record, dict) or set(record) != {'schema_version', 'identity', 'receipt', 'context',
                'observation', 'sources', 'source_evidence', 'configuration_sha256', 'record_sha256'}
                or record['schema_version'] != OwnerCloseoutSubmissionFeedback.VERSION
                or record['record_sha256'] != feedback_record_sha256
                or task_digest({key: value for key, value in record.items() if key != 'record_sha256'}) != feedback_record_sha256):
            raise TaskConflict('Continuation lacks the selected original authenticated closeout feedback record')
        identity = TaskIdentity(**record['identity'])
        receipt = record['receipt']
        if (identity.action_id != 'OWN-A12' or identity.role != 'Owner' or identity.purpose != 'action'
                or identity.organization_id != reading.organization_id or identity.run_id != context.run_id
                or record['observation']['target_action_id'] != 'OWN-A12'
                or receipt['identity'] != identity.as_dict() or receipt['receipt']['disposition'] != 'accepted'
                or receipt['receipt_sha256'] != task_digest(receipt['receipt'])
                or context.operation_id == identity.request_id or context.read_token == record['context']['read_token']
                or context.task_ref.model_dump(mode='json') == record['context']['task_ref']
                or record['context']['business_time']['clock_ref'] != context.business_time.clock_ref.model_dump(mode='json')
                or record['context']['business_time']['offset'] > context.business_time.offset):
            raise TaskConflict('Continuation substitutes original closeout owner, receipt or distinct current invocation')
        basis = reading.resolve(Reference.model_validate(basis_ref))
        if (not isinstance(basis, OwnerCloseoutContinuationBasisView) or basis.run_id != context.run_id
                or basis.organization_id != reading.organization_id or basis.source_task_sha256 != identity.key
                or basis.feedback_record_sha256 != feedback_record_sha256
                or basis.source_result_sha256 != receipt['receipt']['output_sha256']
                or basis.source_receipt_sha256 != receipt['receipt_sha256'] or basis.scope != context.scope
                or basis.available_at.clock_ref != context.business_time.clock_ref
                or basis.available_at.offset > context.business_time.offset
                or not basis.effective_window.contains(context.business_time)):
            raise TaskConflict('Independent continuation basis changes original closeout/receipt or current recipient/scope')
        sources = {Reference.model_validate(row['ref']).key(): row['projection'] for row in record['sources']}
        if len(sources) != len(record['sources']) or basis.decision_ref.key() not in sources:
            raise TaskConflict('Continuation basis omits original closeout decision or repeats historical source versions')
        decision = OwnerCloseoutDecisionView.model_validate(sources[basis.decision_ref.key()])
        profile = reading.resolve(prepared.action_input.continuation_profile_ref)
        state = reading.resolve(basis.continuation_state_ref)
        if (not isinstance(profile, OwnerContinuationProfileView) or not isinstance(state, OwnerContinuationStateView)
                or profile.state_ref != state.ref or state.organization_id != reading.organization_id
                or state.producer != 'core' or state.coverage != 'complete' or state.as_of != context.business_time
                or decision.author_organization_id != identity.organization_id or decision.status not in {'accepted', 'rejected'}
                or len({ref.key() for ref in basis.contract_refs}) != len(basis.contract_refs)
                or not set(basis.contract_refs) <= set(prepared.action_input.contract_refs)
                or not set(basis.contract_refs) <= set(state.contract_refs)
                or not any((ref.kind, ref.id) == (decision.contract_ref.kind, decision.contract_ref.id) for ref in basis.contract_refs)):
            raise TaskConflict('Continuation basis changes original contract relation or current actual core state/profile')
        for ref in basis.contract_refs:
            contract = reading.resolve(ref)
            if not isinstance(contract, OwnerContinuationContractView) or contract.owner_id != reading.organization_id:
                raise TaskConflict('Continuation mapping substitutes another owner contract')
        liabilities = {key for key in sources if key[0] in {'Obligation', 'ContinuingResponsibility',
            'Defect', 'Issue', 'SettlementComponent', 'ActualSettlementComponent'}}
        dispositions = {row.source_ref.key(): row for row in basis.dispositions}
        if len(dispositions) != len(basis.dispositions) or set(dispositions) != liabilities:
            raise TaskConflict('Continuation mapping omits, duplicates or invents an original residual-duty disposition')
        targets, observed_evidence = {}, {}
        input_obligations = {ref.key() for ref in prepared.action_input.obligation_refs}
        state_obligations = {ref.key() for ref in state.obligation_refs}
        state_duties = {ref.key() for ref in state.retained_duty_refs}
        for disposition in dispositions.values():
            if ((disposition.disposition in {'retained', 'superseded'} and not disposition.target_refs)
                    or len(set(disposition.target_refs)) != len(disposition.target_refs)
                    or len(set(disposition.basis_refs)) != len(disposition.basis_refs)
                    or basis.native_evidence_ref in disposition.basis_refs):
                raise TaskConflict('Residual-duty disposition lacks explicit independent targets or separate actual evidence')
            for ref in disposition.target_refs:
                target = reading.resolve(ref)
                if ref.kind == 'Obligation':
                    if (not isinstance(target, OwnerPaymentObligationView)
                            or target.as_of != context.business_time
                            or ref.key() not in input_obligations or ref.key() not in state_obligations):
                        raise TaskConflict('Continuation mapping drops an obligation from current input or actual state')
                elif ref.kind == 'ContinuingDuty':
                    if (not isinstance(target, OwnerContinuationDutyView) or ref.key() not in state_duties
                            or target.organization_id != reading.organization_id
                            or target.contract_ref is not None and target.contract_ref not in basis.contract_refs
                            or not set(target.obligation_refs) <= set(state.obligation_refs)):
                        raise TaskConflict('Continuation mapping changes original continuing duty or associated obligations')
                else:
                    raise TaskConflict('Residual-duty mapping target must be an actual obligation or continuing duty')
                targets[ref.key()] = target.model_dump(mode='json')
            for ref in disposition.basis_refs:
                evidence = reading.resolve(ref)
                if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic'
                        or evidence.basis_kind != 'observed'
                        or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
                    raise TaskConflict('Residual-duty release/retention lacks independent actual observed disposition evidence')
                observed_evidence[ref.key()] = evidence.model_dump(mode='json')
        native = {'schema_version': 'owner-closeout-continuation-native-basis.v1',
            'feedback_record_sha256': feedback_record_sha256, 'basis': basis.model_dump(mode='json'),
            'current_context': context.model_dump(mode='json'), 'current_input': prepared.action_input.model_dump(mode='json'),
            'continuation_state': state.model_dump(mode='json'), 'targets': list(targets.values()),
            'disposition_evidence': list(observed_evidence.values()), 'coverage': 'complete'}
        evidence = reading.resolve(basis.native_evidence_ref)
        if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed'
                or evidence.content_hash != task_digest(native) or evidence.ref not in basis.evidence_refs
                or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)
                or validate_relation(record=deepcopy(record), basis=basis.model_copy(deep=True),
                    native_payload=deepcopy(native), context=context.model_copy(deep=True), reading=reading) is not True):
            raise TaskConflict('Continuation lacks authentic complete closeout mapping and independently lawful residual-duty dispositions')
        return {'feedback_record_sha256': feedback_record_sha256, 'source_identity': identity.as_dict(),
            'basis_ref': basis.ref.model_dump(mode='json'), 'native_basis_sha256': task_digest(native),
            'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        reading.recheck()
        if (task_digest(reading.evidence()) != prepared.reading_sha256
                or task_digest(context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Closeout continuation relation changed original current input or source snapshot')


def bind_owner_closeout_continuation_sources(sources, *, read_closeout_feedback, validate_relation):
    """Attach authorized historical A12 reading and actual A13 mapping to Owner sources."""
    from dataclasses import replace
    from integration.module_host import module_factory_descriptor
    from integration.owner_role_contract_host import OwnerRoleContractSources

    if (not isinstance(sources, OwnerRoleContractSources) or sources.read_closeout_feedback is not None
            or not callable(read_closeout_feedback) or not callable(validate_relation)):
        raise ValueError('Closeout continuation binding requires existing sources and explicit new history/mapping validators')
    declared = {'schema_version': 'owner-closeout-continuation-sources.v1',
        'read_closeout_feedback': module_factory_descriptor(read_closeout_feedback, 'read_closeout_feedback'),
        'validate_relation': module_factory_descriptor(validate_relation, 'validate_relation')}

    def evidence():
        if (declared['read_closeout_feedback'] != module_factory_descriptor(read_closeout_feedback, 'read_closeout_feedback')
                or declared['validate_relation'] != module_factory_descriptor(validate_relation, 'validate_relation')):
            raise TaskConflict('Owner closeout continuation source code changed')
        return {**deepcopy(sources.evidence()), 'closeout_continuation': deepcopy(declared)}

    return replace(sources, version=sources.version + '+owner-closeout-continuation-sources.v1', evidence=evidence,
        read_closeout_feedback=read_closeout_feedback, validate_closeout_continuation=validate_relation)
