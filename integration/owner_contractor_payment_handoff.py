"""Relate lawfully shared actual Owner payments to Contractor A10 sources."""
from copy import deepcopy

from integration.owner_payment_execution_reception import (
    OwnerPaymentExecutionReception, validate_received_payment_settlement,
)
from integration.owner_payment_results import SavedOwnerPayment
from integration.owner_payment_submission import OwnerPaymentExecutionObservation, OwnerPaymentSubmission
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.contractor_payment_objects import ContractorPaymentContractView, ContractorRequestableComponentView
from src.actions.contracts.owner_payment_objects import OwnerPaymentExecutionView, OwnerPaymentReceiptView, OwnerPaymentObligationView
from src.coordination.tasks import TaskConflict, task_digest


CONTRACTOR_RECEIVED_PAYMENT_SOURCE_VERSION = 'contractor-received-payment-sources.v2'


def read_received_contractor_payments(prepared, *, source_task_sha256, execution_refs,
        read_owner_payment, validate_reception):
    """Read selected beneficiary payments without generating Contractor cash.

    The application authorizes disclosure of the original Owner journal/native
    evidence before returning OwnerPaymentExecutionReception. Only selected
    commands to this Contractor enter its invocation. Receiver validation must
    prove complete authorized disclosure, actual beneficiary credit (separate
    from payer debit) and mapping to current receivable components/own accounts.
    A fully final group requires the original independent settlement, tied to
    its embedded issuance and native ledger evidence. Payer ledger projections
    are not resolved as Contractor accounts or copied into its cash balances.
    Unknown execution remains unresolved; no account increase is inferred here.
    """
    context, reading = prepared.context, prepared.reading
    if (prepared.ACTION_ID != 'CONTRACTOR-A10' or context.execution_mode == 'offline_fixture'
            or not execution_refs or not callable(read_owner_payment) or not callable(validate_reception)):
        raise TaskConflict('Contractor payment reception requires formal sources and explicit Owner reader/receiver validation')
    try:
        reading.check_method_context(context, 'CONTRACTOR-A10')
        contract = reading.resolve(prepared.action_input.contract_ref)
        if not isinstance(contract, ContractorPaymentContractView) or contract.contractor_id != reading.organization_id:
            raise TaskConflict('Received payment substitutes original Contractor contract')
        reception = read_owner_payment(context=context.model_copy(deep=True), source_task_sha256=source_task_sha256)
        if not isinstance(reception, OwnerPaymentExecutionReception) or not isinstance(reception.saved, SavedOwnerPayment):
            raise TaskConflict('Original Owner payment issuance is unknown or lacks lawful shared provenance')
        reception = deepcopy(reception)
        saved, issued = reception.saved, reception.issued_reception
        result = saved.result.model_dump(mode='json')
        if (saved.identity.key != source_task_sha256 or saved.identity.run_id != context.run_id
                or saved.identity.organization_id != contract.client_id
                or saved.identity.role != 'Owner' or saved.identity.action_id != 'OWN-A06'
                or saved.context.execution_mode == 'offline_fixture'
                or saved.audit.get('reading', {}).get('source_mode') != 'formal'
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'pay'
                or saved.context.business_time.clock_ref != context.business_time.clock_ref
                or saved.context.business_time.offset > context.business_time.offset
                or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
                or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
                or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
                or any(saved.audit.get(key) != value for key, value in {'run_id': context.run_id,
                    'action_id': 'OWN-A06', 'operation_id': saved.context.operation_id,
                    'input_sha256': saved.identity.input_sha256, 'result_sha256': task_digest(result),
                    'result_kind': 'completed'}.items())):
            raise TaskConflict('Contractor reception changes the original payer, payment choice, journal or source audit')
        expected = {'schema_version': 'owner-payment-issued-reception.v1', 'source_identity': saved.identity.as_dict(),
            'source_record_sha256': saved.record_sha256, 'source_result_sha256': task_digest(result),
            'source_reading_sha256': saved.source_reading_sha256}
        if (not isinstance(issued, dict) or set(issued) != {*expected, 'submission_receipt', 'payment_plan', 'observation'}
                or any(issued[key] != value for key, value in expected.items())):
            raise TaskConflict('Shared payment observation substitutes original task/result/source provenance')
        plan = OwnerPaymentSubmission._payment_plan({'result': result, 'source_reading': saved.source_reading},
            {'context': saved.context.model_dump(mode='json'), 'action_input': saved.action_input.model_dump(mode='json')})
        observation = OwnerPaymentExecutionObservation.model_validate(issued['observation'])
        rows = {row.execution.ref.key(): row for row in observation.lines}
        selected = [Reference.model_validate(ref) for ref in execution_refs]
        if (issued['payment_plan'] != plan or len(rows) != len(observation.lines)
                or sorted(row.line_index for row in rows.values()) != list(range(len(plan['lines'])))
                or len({(ref.kind, ref.id) for ref in selected}) != len(selected)
                or not {ref.key() for ref in selected} <= {ref.key() for ref in prepared.action_input.execution_refs}
                or any(ref.key() not in rows for ref in selected)):
            raise TaskConflict('Contractor reception borrows an unselected execution or changes original complete command allocations')
        envelope = issued['submission_receipt']
        correlation = {'run_id': context.run_id, 'organization_id': contract.client_id,
            'request_id': saved.identity.request_id, 'task_sha256': task_digest(saved.identity.as_dict()),
            'output_sha256': task_digest(result)}
        if (not isinstance(envelope, dict) or set(envelope) != {*correlation, 'binding_id', 'macro_version',
                'receipt_id', 'disposition', 'original_receipt'}
                or any(envelope[key] != value for key, value in correlation.items())
                or envelope['disposition'] != 'accepted'
                or any(not isinstance(envelope[key], str) or not envelope[key].strip()
                    for key in ('binding_id', 'macro_version', 'receipt_id'))
                or not isinstance(envelope['original_receipt'], dict) or not envelope['original_receipt']):
            raise TaskConflict('Shared payment lacks its original correlated actual accepted registration')
        native = {'schema_version': 'owner-payment-native-execution.v1',
            'receipt_identity': {**correlation, 'binding_id': envelope['binding_id'], 'macro_version': envelope['macro_version']},
            'original_receipt': deepcopy(envelope['original_receipt']), 'source_identity': saved.identity.as_dict(),
            'source_record_sha256': saved.record_sha256, 'source_reading_sha256': saved.source_reading_sha256,
            'payment_plan': plan, 'lines': [row.model_dump(mode='json') for row in observation.lines], 'coverage': 'complete'}
        evidence = reading.resolve(observation.native_evidence.ref)
        if (task_digest(observation.native_payload) != task_digest(native) or not isinstance(evidence, EvidenceRecord)
                or evidence != observation.native_evidence or evidence.source_kind == 'synthetic'
                or evidence.basis_kind != 'observed' or evidence.content_hash != task_digest(native)):
            raise TaskConflict('Shared actual payment lacks complete independent authentic native evidence')
        ledger = validate_received_payment_settlement(reception, observation=observation, context=context)
        executions, receipts, components = [], [], {}
        commands, businesses = set(), set()
        for ref in selected:
            row = rows[ref.key()]
            execution = reading.resolve(ref)
            line = plan['lines'][row.line_index]
            if (not isinstance(execution, OwnerPaymentExecutionView) or execution != row.execution
                    or execution.organization_id != contract.client_id or execution.beneficiary_id != contract.contractor_id
                    or execution.operation != 'pay' or execution.command_id in commands or execution.business_key in businesses
                    or execution.amount.model_dump(mode='json') != line['amount']
                    or execution.beneficiary_id != line['payee_id']
                    or execution.authorization_ref.model_dump(mode='json') != plan['authorization_ref']
                    or execution.account_ref is None or execution.account_ref.model_dump(mode='json') != plan['account_ref']
                    or [ref.model_dump(mode='json') for ref in execution.obligation_refs] != [line['obligation_ref']]
                    or [ref.model_dump(mode='json') for ref in execution.component_refs] != line['component_refs']
                    or [part.model_dump(mode='json') for part in row.component_amounts] != line['component_amounts']
                    or execution.available_at.clock_ref != context.business_time.clock_ref
                    or not saved.context.business_time.offset <= execution.available_at.offset <= context.business_time.offset
                    or evidence.ref not in execution.evidence_refs):
                raise TaskConflict('Actual payer command changes original Contractor beneficiary, account, amount or component allocation')
            commands.add(execution.command_id); businesses.add(execution.business_key)
            for component_ref in execution.component_refs:
                component = reading.resolve(component_ref)
                if not isinstance(component, ContractorRequestableComponentView):
                    raise TaskConflict('Received payment lacks original concrete Contractor receivable component')
                obligation = reading.resolve(component.obligation_ref)
                if (not isinstance(obligation, OwnerPaymentObligationView)
                        or component.contract_ref != contract.ref or component.payee_id != contract.contractor_id
                        or component.debtor_id != contract.client_id or component.settlement_mode != 'cash'
                        or component.obligation_ref not in prepared.action_input.obligation_refs
                        or component.obligation_ref not in execution.obligation_refs
                        or obligation.payee_id != contract.contractor_id or obligation.debtor_id != contract.client_id
                        or component.ref not in obligation.component_refs):
                    raise TaskConflict('Received payment borrows another contract or original receivable component')
                components[component.ref.key()] = component.model_copy(deep=True)
            if execution.status in {'unknown', 'pending'}:
                if execution.receipt_ref is not None or row.receipt is not None:
                    raise TaskConflict('Unknown Contractor receipt cannot prove actual cash arrival')
            else:
                receipt = reading.resolve(execution.receipt_ref) if execution.receipt_ref is not None else None
                if (not isinstance(receipt, OwnerPaymentReceiptView) or receipt != row.receipt
                        or receipt.execution_ref != execution.ref or receipt.command_id != execution.command_id
                        or receipt.business_key != execution.business_key or receipt.status != execution.status
                        or receipt.amount != execution.amount or receipt.beneficiary_id != contract.contractor_id
                        or receipt.available_at.clock_ref != context.business_time.clock_ref
                        or not execution.available_at.offset <= receipt.available_at.offset <= context.business_time.offset
                        or evidence.ref not in receipt.evidence_refs):
                    raise TaskConflict('Contractor payment receipt changes original native execution identity or outcome')
                receipts.append(receipt.model_copy(deep=True))
            executions.append(execution.model_copy(deep=True))
        accounts = [reading.resolve(ref).model_copy(deep=True) for ref in prepared.action_input.account_refs]
        if any(account.organization_id != contract.contractor_id for account in accounts):
            raise TaskConflict('Received payment cannot borrow the payer account as Contractor cash')
        if validate_reception(reception=deepcopy(reception), contract=contract.model_copy(deep=True),
                executions=deepcopy(executions), receipts=deepcopy(receipts),
                components=deepcopy(list(components.values())), accounts=deepcopy(accounts),
                context=context.model_copy(deep=True)) is not True:
            raise TaskConflict('Contractor did not confirm authorized disclosure, actual beneficiary credit and current receivable mapping')
        return {**{key: value for key, value in expected.items() if key != 'schema_version'},
            'execution_refs': [ref.model_dump(mode='json') for ref in selected],
            'issued_reception_sha256': task_digest(issued),
            'native_settlement_sha256': task_digest(ledger.native_payload) if ledger is not None else None,
            'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        reading.recheck()
        if (task_digest(reading.evidence()) != prepared.reading_sha256
                or task_digest(context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Shared Owner payment changed the original Contractor input or authorized source snapshot')


def bind_contractor_received_payment_sources(sources, *, read_owner_payment, validate_reception):
    """Attach authorized actual payer observations to an existing Contractor factory."""
    from dataclasses import replace
    from integration.contractor_role_contract_host import ContractorRoleContractSources
    from integration.module_host import module_factory_descriptor

    if (not isinstance(sources, ContractorRoleContractSources) or sources.read_owner_payment is not None
            or not callable(read_owner_payment) or not callable(validate_reception)):
        raise ValueError('Contractor payment reception requires existing sources and explicit new reader/validator')
    declared = {'schema_version': CONTRACTOR_RECEIVED_PAYMENT_SOURCE_VERSION,
        'read_owner_payment': module_factory_descriptor(read_owner_payment, 'read_owner_payment'),
        'validate_reception': module_factory_descriptor(validate_reception, 'validate_reception')}

    def evidence():
        if (declared['read_owner_payment'] != module_factory_descriptor(read_owner_payment, 'read_owner_payment')
                or declared['validate_reception'] != module_factory_descriptor(validate_reception, 'validate_reception')):
            raise TaskConflict('Contractor payment reception changed actual reader/validator code')
        return {**deepcopy(sources.evidence()), 'received_owner_payment': deepcopy(declared)}

    return replace(sources, version=sources.version + '+' + CONTRACTOR_RECEIVED_PAYMENT_SOURCE_VERSION,
        read_owner_payment=read_owner_payment, validate_received_payments=validate_reception, evidence=evidence)
