"""Consume complete original payment command groups in a current Owner invocation."""
from copy import deepcopy
from dataclasses import dataclass, replace

from integration.owner_payment_results import SavedOwnerPayment
from integration.owner_payment_settlement import OwnerNativeSettlementObservation, OwnerPaymentSettlementReconciler
from integration.owner_payment_submission import OwnerPaymentExecutionObservation, OwnerPaymentSubmission
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_payment_objects import OwnerPaymentExecutionView, OwnerPaymentReceiptView
from src.coordination.tasks import TaskConflict, task_digest


OWNER_PAYMENT_EXECUTION_SOURCE_VERSION = 'owner-payment-execution-sources.v2'
PAYMENT_SETTLEMENT_RECEPTION_VERSION = 'owner-payment-settlement-reception.v2'


@dataclass(frozen=True)
class OwnerPaymentExecutionReception:
    saved: SavedOwnerPayment
    issued_reception: dict
    settlement: dict | None


def validate_received_payment_settlement(reception, *, observation, context):
    """Check the shared settlement envelope without reading or posting a ledger.

    The original reconciler and independent recipient validator still establish
    native authenticity, complete effects and actual beneficiary credit. This
    check binds their evidence to this exact issued group and observation time;
    it cannot turn an accepted command or payer debit into recipient cash.
    """
    final = all(line.execution.status not in {'unknown', 'pending'} for line in observation.lines)
    settlement = reception.settlement
    if not final:
        if settlement is not None:
            raise TaskConflict('Uncertain payment commands cannot claim completed financial reconciliation')
        return None
    saved, issued = reception.saved, reception.issued_reception
    expected = {'schema_version': OwnerPaymentSettlementReconciler.VERSION,
        'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
        'source_result_sha256': task_digest(saved.result.model_dump(mode='json')),
        'source_reading_sha256': saved.source_reading_sha256, 'issued_reception_sha256': task_digest(issued)}
    if (not isinstance(settlement, dict)
            or set(settlement) != {*expected, 'native_settlement_sha256', 'observation', 'issued_reception', 'effects'}
            or any(task_digest(settlement[key]) != task_digest(value) for key, value in expected.items())
            or task_digest(settlement['issued_reception']) != task_digest(issued)
            or not isinstance(settlement['effects'], list)):
        raise TaskConflict('Final payment reception lacks its exact original independently reconciled command group')
    ledger = OwnerNativeSettlementObservation.model_validate(settlement['observation']).model_copy(deep=True)
    native = {'schema_version': 'owner-payment-native-settlement.v1',
        'issued_reception_sha256': task_digest(issued), 'source_identity': saved.identity.as_dict(),
        'source_record_sha256': saved.record_sha256, 'source_reading_sha256': saved.source_reading_sha256,
        'interval_start': saved.context.business_time.model_dump(mode='json'),
        'observed_at': ledger.observed_at.model_dump(mode='json'),
        'balances': [pair.model_dump(mode='json') for pair in ledger.balances],
        'postings': [posting.model_dump(mode='json') for posting in ledger.postings], 'coverage': 'complete'}
    evidence = ledger.native_evidence
    if (task_digest(ledger.native_payload) != task_digest(native)
            or settlement['native_settlement_sha256'] != task_digest(native)
            or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed'
            or evidence.content_hash != task_digest(native)
            or evidence.effective_window is not None and not evidence.effective_window.contains(ledger.observed_at)
            or ledger.observed_at.clock_ref != context.business_time.clock_ref
            or saved.context.business_time.clock_ref != ledger.observed_at.clock_ref
            or not saved.context.business_time.offset <= ledger.observed_at.offset <= context.business_time.offset
            or any(line.receipt is None or line.receipt.ref != line.execution.receipt_ref
                or line.receipt.status != line.execution.status
                or line.receipt.available_at.clock_ref != ledger.observed_at.clock_ref
                or line.execution.available_at.clock_ref != ledger.observed_at.clock_ref
                or not saved.context.business_time.offset <= line.execution.available_at.offset
                    <= line.receipt.available_at.offset <= ledger.observed_at.offset for line in observation.lines)):
        raise TaskConflict('Received settlement changes original native evidence, command outcomes or observation interval')
    return ledger


def _check_evidence(reading, evidence, payload):
    current = reading.resolve(evidence.ref)
    if (not isinstance(current, EvidenceRecord) or current != evidence
            or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed'
            or evidence.content_hash != task_digest(payload)):
        raise TaskConflict('Current Owner sources lack original authentic observed native payment evidence')


def read_received_owner_payment_executions(prepared, *, payments, read_owner_payment_execution, validate_reception):
    """Retain complete command groups, actual receipts and current ledger mappings.

    The authorized reader returns OwnerPaymentExecutionReception from the same
    original Owner journal, actual query_execution and (when final) settlement
    reconciler query. None preserves unknown issuance by refusing preparation.
    Pending/unknown executions remain explicit and require no claimed settlement.
    The mandatory receiver validator authenticates those observations and their
    complete mapping to the current authorized private financial sources.
    """
    context, reading = prepared.context, prepared.reading
    if (prepared.ACTION_ID != 'OWN-A06' or context.execution_mode == 'offline_fixture' or not payments
            or not callable(read_owner_payment_execution) or not callable(validate_reception)):
        raise TaskConflict('Payment reception requires a formal Owner invocation and original authorized reader/validator')
    provenance, receptions, current_executions, current_receipts, financial = [], [], [], [], {}
    tasks, refs, commands, businesses, receipt_refs = set(), set(), set(), set(), set()
    try:
        reading.check_method_context(context, 'OWN-A06')
        for selection in payments:
            if not isinstance(selection, dict) or set(selection) != {'source_task_sha256', 'execution_refs'}:
                raise TaskConflict('Payment reception requires explicit original task and complete command references')
            reception = read_owner_payment_execution(context=context.model_copy(deep=True),
                source_task_sha256=selection['source_task_sha256'])
            if not isinstance(reception, OwnerPaymentExecutionReception) or not isinstance(reception.saved, SavedOwnerPayment):
                raise TaskConflict('Original payment issuance is unknown or lacks its authorized journal decision')
            reception = deepcopy(reception)
            saved, issued = reception.saved, reception.issued_reception
            result = saved.result.model_dump(mode='json')
            if (saved.identity.key != selection['source_task_sha256'] or saved.identity.key in tasks
                    or saved.identity.action_id != 'OWN-A06' or saved.identity.role != 'Owner'
                    or saved.identity.organization_id != reading.organization_id or saved.identity.run_id != context.run_id
                    or saved.context.execution_mode != context.execution_mode
                    or saved.context.business_time.clock_ref != context.business_time.clock_ref
                    or saved.context.business_time.offset > context.business_time.offset
                    or saved.audit.get('reading', {}).get('source_mode') != 'formal'
                    or saved.result.kind != 'completed' or saved.result.payload.choice not in {'pay', 'repay'}
                    or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
                    or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
                    or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
                    or any(saved.audit.get(key) != value for key, value in {'run_id': context.run_id,
                        'action_id': 'OWN-A06', 'operation_id': saved.context.operation_id,
                        'input_sha256': saved.identity.input_sha256, 'result_sha256': task_digest(result),
                        'result_kind': 'completed'}.items())):
                raise TaskConflict('Payment reception substitutes its own original formal action, sources or audit')
            tasks.add(saved.identity.key)
            expected = {'schema_version': 'owner-payment-issued-reception.v1', 'source_identity': saved.identity.as_dict(),
                'source_record_sha256': saved.record_sha256, 'source_result_sha256': task_digest(result),
                'source_reading_sha256': saved.source_reading_sha256}
            if (not isinstance(issued, dict) or set(issued) != {*expected, 'submission_receipt', 'payment_plan', 'observation'}
                    or any(issued[key] != value for key, value in expected.items())):
                raise TaskConflict('Received payment commands change original task/result/record/source provenance')
            plan = OwnerPaymentSubmission._payment_plan({'result': result, 'source_reading': saved.source_reading},
                {'context': saved.context.model_dump(mode='json'), 'action_input': saved.action_input.model_dump(mode='json')})
            observation = OwnerPaymentExecutionObservation.model_validate(issued['observation'])
            lines = sorted(observation.lines, key=lambda row: row.line_index)
            selected_refs = [Reference.model_validate(ref) for ref in selection['execution_refs']]
            selected_keys = [ref.key() for ref in selected_refs]
            if (issued['payment_plan'] != plan or [row.line_index for row in lines] != list(range(len(plan['lines'])))
                    or len(set(selected_keys)) != len(selected_keys)
                    or set(selected_keys) != {row.execution.ref.key() for row in lines}
                    or not set(selected_keys) <= {ref.key() for ref in prepared.action_input.pending_execution_refs}):
                raise TaskConflict('Payment reception omits an original planned command or substitutes partial allocations')
            envelope = issued['submission_receipt']
            correlation = {'run_id': context.run_id, 'organization_id': reading.organization_id,
                'request_id': saved.identity.request_id, 'task_sha256': task_digest(saved.identity.as_dict()),
                'output_sha256': task_digest(result)}
            if (not isinstance(envelope, dict) or set(envelope) != {*correlation, 'binding_id', 'macro_version',
                    'receipt_id', 'disposition', 'original_receipt'}
                    or any(envelope[key] != value for key, value in correlation.items())
                    or envelope['disposition'] != 'accepted'
                    or any(not isinstance(envelope[key], str) or not envelope[key].strip()
                        for key in ('binding_id', 'macro_version', 'receipt_id'))
                    or not isinstance(envelope['original_receipt'], dict) or not envelope['original_receipt']):
                raise TaskConflict('Received commands lack the original correlated accepted submission receipt')
            native = {'schema_version': 'owner-payment-native-execution.v1',
                'receipt_identity': {**correlation, 'binding_id': envelope['binding_id'], 'macro_version': envelope['macro_version']},
                'original_receipt': deepcopy(envelope['original_receipt']), 'source_identity': saved.identity.as_dict(),
                'source_record_sha256': saved.record_sha256, 'source_reading_sha256': saved.source_reading_sha256,
                'payment_plan': plan, 'lines': [row.model_dump(mode='json') for row in observation.lines], 'coverage': 'complete'}
            if task_digest(observation.native_payload) != task_digest(native):
                raise TaskConflict('Received payment changes its complete original native command history')
            _check_evidence(reading, observation.native_evidence, native)
            for row in lines:
                execution = reading.resolve(row.execution.ref)
                planned = plan['lines'][row.line_index]
                if (not isinstance(execution, OwnerPaymentExecutionView) or execution != row.execution
                        or execution.organization_id != reading.organization_id or execution.ref in refs
                        or execution.command_id in commands or execution.business_key in businesses
                        or execution.available_at.clock_ref != context.business_time.clock_ref
                        or execution.available_at.offset < saved.context.business_time.offset
                        or execution.available_at.offset > context.business_time.offset
                        or execution.operation != plan['choice']
                        or execution.authorization_ref.model_dump(mode='json') != plan['authorization_ref']
                        or execution.account_ref is None or execution.account_ref.model_dump(mode='json') != plan['account_ref']
                        or execution.amount.model_dump(mode='json') != planned['amount']
                        or execution.beneficiary_id != planned['payee_id']
                        or [ref.model_dump(mode='json') for ref in execution.obligation_refs] != [planned['obligation_ref']]
                        or [ref.model_dump(mode='json') for ref in execution.component_refs] != planned['component_refs']
                        or [part.model_dump(mode='json') for part in row.component_amounts] != planned['component_amounts']
                        or observation.native_evidence.ref not in execution.evidence_refs):
                    raise TaskConflict('Current Owner input duplicates or replaces an actual original payment command')
                refs.add(execution.ref); commands.add(execution.command_id); businesses.add(execution.business_key)
                current_executions.append(execution.model_copy(deep=True))
                if execution.status in {'unknown', 'pending'}:
                    if row.receipt is not None or execution.receipt_ref is not None:
                        raise TaskConflict('Uncertain payment reception cannot claim a terminal receipt')
                else:
                    receipt = reading.resolve(execution.receipt_ref) if execution.receipt_ref is not None else None
                    if (not isinstance(receipt, OwnerPaymentReceiptView) or receipt != row.receipt
                            or receipt.ref in receipt_refs or receipt.execution_ref != execution.ref
                            or receipt.command_id != execution.command_id or receipt.business_key != execution.business_key
                            or receipt.status != execution.status or receipt.amount != execution.amount
                            or receipt.beneficiary_id != execution.beneficiary_id
                            or receipt.available_at.clock_ref != context.business_time.clock_ref
                            or receipt.available_at.offset < execution.available_at.offset
                            or receipt.available_at.offset > context.business_time.offset
                            or observation.native_evidence.ref not in receipt.evidence_refs):
                        raise TaskConflict('Current Owner receipt changes original command identity or execution outcome')
                    receipt_refs.add(receipt.ref)
                    current_receipts.append(receipt.model_copy(deep=True))
            settlement_sha = None
            ledger = validate_received_payment_settlement(reception, observation=observation, context=context)
            if ledger is not None:
                settlement_sha = task_digest(ledger.native_payload)
                _check_evidence(reading, ledger.native_evidence, ledger.native_payload)
                for pair in ledger.balances:
                    ref = Reference.model_validate(pair.after['ref'])
                    current = reading.resolve(ref).model_dump(mode='json')
                    # Debt action views retain original terms/parties; the native
                    # ledger additionally exposes actual outstanding principal.
                    keys = ('ref', 'borrower_id', 'lender_id', 'arrangement_ref', 'obligation_refs', 'as_of', 'coverage') if ref.kind == 'Debt' else pair.after.keys()
                    if (pair.after.get('as_of') != ledger.observed_at.model_dump(mode='json')
                            or ledger.native_evidence.ref.model_dump(mode='json') not in pair.after.get('evidence_refs', [])
                            or any(current.get(key) != pair.after[key] for key in keys)
                            or ref.key() in financial and financial[ref.key()] != current):
                        raise TaskConflict('Current Owner financial sources replace independently reconciled native balances')
                    financial[ref.key()] = deepcopy(current)
            receptions.append(deepcopy(reception))
            provenance.append({**{key: value for key, value in expected.items() if key != 'schema_version'},
                'execution_refs': [ref.model_dump(mode='json') for ref in selected_refs],
                'issued_reception_sha256': task_digest(issued), 'native_settlement_sha256': settlement_sha})
        if validate_reception(receptions=deepcopy(receptions), executions=deepcopy(current_executions),
                receipts=deepcopy(current_receipts), financial_sources=deepcopy(list(financial.values())),
                context=context.model_copy(deep=True)) is not True:
            raise TaskConflict('Owner did not confirm native authenticity, complete command coverage or current financial mapping')
        return {'payments': provenance, 'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        reading.recheck()
        if (task_digest(reading.evidence()) != prepared.reading_sha256
                or task_digest(context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Payment reception changed original current Owner input or source snapshot')


def bind_owner_payment_execution_sources(sources, *, read_owner_payment_execution, validate_reception):
    """Attach actual original-payment reception to an existing Owner source factory.

    The reader authorizes current own-journal access and returns the original
    SavedOwnerPayment plus its actual query_execution reception and, for a fully
    final command group, independently reconciled native settlement. Receiver
    validation must verify the query/ledger authenticity and complete mapping
    under the current Owner guard. This binder creates no journal or endpoint.
    Configure payment_execution_inputs with an explicit operation selection of
    payments=[{source_task_sha256, execution_refs}], retaining all commands of
    each selected original task. Keep the returned source version in host config.
    """
    from integration.module_host import module_factory_descriptor
    from integration.owner_role_contract_host import OwnerRoleContractSources

    if (not isinstance(sources, OwnerRoleContractSources) or not callable(read_owner_payment_execution)
            or not callable(validate_reception) or sources.read_owner_payment_execution is not None):
        raise ValueError('Payment execution binding requires existing Owner sources and explicit new reader/validator')
    configuration = {'schema_version': OWNER_PAYMENT_EXECUTION_SOURCE_VERSION,
        'read_owner_payment_execution': module_factory_descriptor(read_owner_payment_execution, 'read_owner_payment_execution'),
        'validate_reception': module_factory_descriptor(validate_reception, 'validate_reception')}

    def evidence():
        if (module_factory_descriptor(read_owner_payment_execution, 'read_owner_payment_execution') != configuration['read_owner_payment_execution']
                or module_factory_descriptor(validate_reception, 'validate_reception') != configuration['validate_reception']):
            raise TaskConflict('Actual Owner payment execution source code changed')
        return {**deepcopy(sources.evidence()), 'owner_payment_execution_reception': deepcopy(configuration)}

    return replace(sources, version=sources.version + '+' + OWNER_PAYMENT_EXECUTION_SOURCE_VERSION, evidence=evidence,
        read_owner_payment_execution=read_owner_payment_execution,
        validate_owner_payment_execution_reception=validate_reception)
