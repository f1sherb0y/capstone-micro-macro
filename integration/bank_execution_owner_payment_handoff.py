"""Original Bank receipt reconciliation to actual Owner draw execution observations."""
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction

from integration.bank_execution_results import BankExecutionResultWorker, SavedBankExecution
from src.actions.contracts.bank_execution_objects import (
    BankExecutionApprovalView, BankExecutionArrangementView, BankExecutionProfileView,
    BankExecutionReceiptView, BankExecutionSavedView,
)
from src.actions.contracts.common import EvidenceRecord, Known, Reference
from src.actions.contracts.owner_payment_objects import (
    OwnerBankExecutionReceptionView, OwnerPaymentDrawView, OwnerPaymentExecutionView, OwnerPaymentReceiptView,
)
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers

_AMOUNTS = ('beneficiary_cash', 'principal', 'withheld_fee', 'capitalized_fee', 'separate_fee_cash', 'bank_debit')


def _recheck(prepared):
    prepared.reading.recheck()
    if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
            or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Bank execution reception changed original Owner payment input or sources')


def _values(amounts, currency):
    values = {}
    for name in _AMOUNTS:
        money = getattr(amounts, name)
        value = Fraction(Decimal(money.value))
        if money.currency != currency or value < 0:
            raise TaskConflict('Bank receipt changes currency or reports a negative actual amount')
        values[name] = value
    if (values['principal'] != values['beneficiary_cash'] + values['withheld_fee'] + values['capitalized_fee']
            or values['bank_debit'] != values['beneficiary_cash'] + values['separate_fee_cash']):
        raise TaskConflict('Bank receipt principal, beneficiary cash, fees and bank debit do not reconcile')
    return values


def _receipt_history(execution, receipts, currency, *, observed_by):
    """Retain six separate totals and incremental/cumulative event identity."""
    expected = {line.local_key: line for line in execution.lines}
    if len(expected) != len(execution.lines):
        raise TaskConflict('Original Bank execution repeats a transfer line')
    caps = {key: _values(line.amounts, currency) for key, line in expected.items()}
    approved_principal = sum((values['principal'] for values in caps.values()), Fraction())
    if (execution.available_at.clock_ref != observed_by.clock_ref
            or execution.available_at.offset > observed_by.offset):
        raise TaskConflict('Original Bank execution was unavailable at the actual reconciliation')
    if len({(row.ref.kind, row.ref.id) for row in receipts}) != len(receipts):
        raise TaskConflict('Bank receipt history repeats a physical receipt across versions')
    totals = {key: {name: Fraction() for name in _AMOUNTS} for key in expected}
    states = {key: 'unknown' for key in expected}
    events, sequences = {}, set()
    for receipt in sorted(receipts, key=lambda row: row.sequence):
        if (receipt.observed_at.clock_ref != observed_by.clock_ref
                or receipt.available_at.clock_ref != observed_by.clock_ref
                or receipt.observed_at.offset > receipt.available_at.offset
                or receipt.available_at.offset > observed_by.offset):
            raise TaskConflict('Bank receipt observation or availability is after its actual reconciliation')
        if (receipt.execution_ref != execution.ref or receipt.arrangement_ref != execution.arrangement_ref
                or receipt.approval_ref != execution.approval_ref or receipt.path_ref != execution.path_ref
                or receipt.command_id != execution.command_id or receipt.business_key != execution.business_key
                or receipt.lender_id != execution.lender_id or receipt.borrower_id != execution.borrower_id):
            raise TaskConflict('Bank receipt changes original execution, parties, command or path')
        payload = receipt.model_dump(mode='json', exclude={'ref', 'evidence_refs', 'available_at', 'effective_window', 'observed_at'})
        if receipt.event_id in events:
            if events[receipt.event_id] != payload:
                raise TaskConflict('Repeated Bank receipt event changes its original content')
            continue
        if receipt.sequence in sequences or len({line.local_key for line in receipt.lines}) != len(receipt.lines):
            raise TaskConflict('Bank receipt repeats a ledger sequence or transfer line')
        events[receipt.event_id] = payload
        sequences.add(receipt.sequence)
        for line in receipt.lines:
            original = expected.get(line.local_key)
            if (original is None or original.transfer.destination_ref != line.destination_ref
                    or original.transfer.beneficiary_id != line.beneficiary_id):
                raise TaskConflict('Bank receipt credits another original destination or beneficiary')
            values = _values(line.amounts, currency)
            if receipt.status in {'unknown', 'failed', 'rejected'}:
                if any(values.values()):
                    raise TaskConflict('Unverified Bank receipt reports actual cash or principal')
                states[line.local_key] = receipt.status
                continue
            old = totals[line.local_key]
            if receipt.semantics == 'cumulative':
                if any(values[name] < old[name] for name in _AMOUNTS):
                    raise TaskConflict('Cumulative Bank receipt regresses already observed amounts')
                new = values
            else:
                new = {name: old[name] + values[name] for name in _AMOUNTS}
            cap = caps[line.local_key]
            if any(new[name] > cap[name] for name in _AMOUNTS):
                raise TaskConflict('Bank receipt exceeds the original approved cash/principal/fee components')
            totals[line.local_key] = new
            states[line.local_key] = receipt.status
        if not receipt.lines and receipt.status in {'unknown', 'failed', 'rejected'}:
            states = dict.fromkeys(expected, receipt.status)
        if receipt.status not in {'unknown', 'failed', 'rejected'} and isinstance(receipt.confirmed_unexecuted_amount, Known):
            remainder = receipt.confirmed_unexecuted_amount.value
            amount = Fraction(Decimal(remainder.value))
            paid_principal = sum((values['principal'] for values in totals.values()), Fraction())
            if remainder.currency != currency or amount < 0 or amount > approved_principal - paid_principal:
                raise TaskConflict('Bank receipt unexecuted amount exceeds original unpaid principal')
    return totals, states


def read_received_bank_execution(prepared, *, source_task_sha256, reception_ref,
        read_bank_execution, validate_reception, reception_sha256=None):
    if not callable(read_bank_execution) or not callable(validate_reception):
        raise TaskConflict('Owner reconciliation requires original Bank reader and actual receiver validator')
    try:
        saved = read_bank_execution(context=prepared.context.model_copy(deep=True),
            source_task_sha256=source_task_sha256)
        if not isinstance(saved, SavedBankExecution) or saved.identity.key != source_task_sha256:
            raise TaskConflict('Execution reader substituted the explicitly selected original Bank task')
        actual_sha256 = validate_received_bank_execution(saved, prepared=prepared, reception_ref=reception_ref,
            validate_reception=validate_reception)
        if reception_sha256 is not None and reception_sha256 != actual_sha256:
            raise TaskConflict('Bank execution reception replaces the explicitly retained original observation')
        provenance = {'source_task_sha256': saved.identity.key, 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': task_digest(saved.result.model_dump(mode='json')),
            'source_reading_sha256': saved.source_reading_sha256,
            'reception_ref': Reference.model_validate(reception_ref).model_dump(mode='json'),
            'execution_source_reading_sha256': prepared.reading_sha256}
        if reception_sha256 is not None:
            provenance['reception_sha256'] = actual_sha256
        return provenance
    finally:
        _recheck(prepared)


def validate_received_bank_execution(saved, *, prepared, reception_ref, validate_reception):
    """Validate received original receipt history; never create Owner cash or debt.

    The actual application verifies the complete native command/receipt mapping,
    original Owner authorization and settlement identities, event completeness,
    account cash/principal/fee/offset effects and authorized disclosure. A local
    Bank execute/cancel proposal is insufficient for this reception protocol.
    """
    context, reading = prepared.context, prepared.reading
    if (not isinstance(saved, SavedBankExecution) or prepared.ACTION_ID != 'OWN-A06'
            or saved.identity.action_id != 'BANK-A07' or saved.identity.role != 'Bank'
            or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
            or saved.context.contract_ref.id != 'BANK-A07' or saved.context.execution_mode != context.execution_mode
            or saved.result.kind != 'completed' or saved.result.payload.choice != 'reconcile'
            or not callable(validate_reception)
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise TaskConflict('Execution reception requires original Bank reconciliation and actual Owner validation')
    reading.check_method_context(context, 'OWN-A06')
    if task_digest(reading.evidence()) != prepared.reading_sha256:
        raise TaskConflict('Execution reception changes original Owner source snapshot')
    try:
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        if any(saved.audit.get(key) != value for key, value in {
                'run_id': context.run_id, 'action_id': 'BANK-A07', 'operation_id': saved.context.operation_id,
                'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
                'result_kind': 'completed'}.items()):
            raise TaskConflict('Execution reception lacks original successful Bank reconciliation audit')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Execution relation repeats an original Bank source')
            originals[key] = row['projection']
        original_arrangement = BankExecutionArrangementView.model_validate(originals[saved.action_input.arrangement_ref.key()])
        profile = BankExecutionProfileView.model_validate(originals[original_arrangement.execution_profile_ref.key()])
        grant = Authorization.model_validate(originals[profile.authority_ref.key()])
        assignment = RoleAssignment.model_validate(originals[saved.context.function_ref.key()])
        if (original_arrangement.lender_id != saved.identity.organization_id
                or profile.organization_id != saved.identity.organization_id
                or profile.arrangement_ref != original_arrangement.ref
                or grant.ref != profile.authority_ref or grant.ref not in saved.context.authorization_refs
                or grant.organization_id != saved.identity.organization_id or grant.actor_id != saved.context.actor_id
                or grant.function_ref != saved.context.function_ref or assignment.function_ref != saved.context.function_ref
                or assignment.role != 'Bank' or 'BANK-A07' not in grant.action_ids
                or not grant.validity.contains(saved.context.business_time)
                or not any(scope_covers(scope, saved.context.scope) for scope in grant.scopes)):
            raise TaskConflict('Execution reception lacks original independently authorized Bank reconciliation')
        original_schemas = BankExecutionResultWorker.SOURCE_SCHEMAS()
        for ref in [*grant.basis_refs, *assignment.basis_refs]:
            if ref.key() not in originals:
                raise TaskConflict('Execution reception omits an original Bank reconciliation authority basis')
            source = original_schemas.validate_projection(ref, originals[ref.key()])
            if ref.kind == 'Evidence':
                if (not isinstance(source, EvidenceRecord) or source.effective_window is not None
                        and not source.effective_window.contains(saved.context.business_time)):
                    raise TaskConflict('Bank reconciliation author evidence was not valid at the original decision')
        reception = reading.resolve(Reference.model_validate(reception_ref))
        if (not isinstance(reception, OwnerBankExecutionReceptionView)
                or reception.run_id != context.run_id or reception.recipient_organization_id != reading.organization_id
                or reception.author_organization_id != saved.identity.organization_id
                or reception.source_task_sha256 != saved.identity.key or reception.source_record_sha256 != saved.record_sha256
                or reception.source_result_sha256 != result_sha or reception.source_reading_sha256 != saved.source_reading_sha256
                or reception.bank_execution_ref not in saved.result.payload.execution_refs
                or reception.owner_execution_ref not in prepared.action_input.pending_execution_refs
                or not scope_covers(context.scope, reception.scope) or not reception.effective_window.contains(context.business_time)):
            raise TaskConflict('Execution reception substitutes original Bank, recipient or command observation')
        execution = BankExecutionSavedView.model_validate(originals[reception.bank_execution_ref.key()])
        approval = BankExecutionApprovalView.model_validate(originals[execution.approval_ref.key()])
        if (execution.ref != reception.bank_execution_ref or execution.arrangement_ref != original_arrangement.ref
                or approval.ref != execution.approval_ref or approval.arrangement_ref != execution.arrangement_ref
                or approval.lender_id != execution.lender_id or approval.borrower_id != execution.borrower_id
                or execution.ref not in approval.execution_refs or execution.lines != approval.lines
                or not scope_covers(approval.scope, saved.context.scope)
                or approval.approved_at.clock_ref != saved.context.business_time.clock_ref
                or approval.available_at.clock_ref != saved.context.business_time.clock_ref
                or approval.approved_at.offset > approval.available_at.offset
                or approval.available_at.offset > saved.context.business_time.offset):
            raise TaskConflict('Owner reception changes the original approved command, complete transfers or approval chronology')
        owner = reading.resolve(reception.owner_execution_ref)
        if (not isinstance(owner, OwnerPaymentExecutionView)
                or reception.owner_execution_sha256 != task_digest(owner.model_dump(mode='json'))
                or execution.lender_id != saved.identity.organization_id or execution.borrower_id != reading.organization_id
                or execution.receipt_coverage != 'complete' or owner.organization_id != execution.borrower_id
                or owner.operation != 'draw_request' or owner.arrangement_ref != execution.arrangement_ref
                or not execution.lines or any(line.transfer.beneficiary_id != owner.beneficiary_id for line in execution.lines)):
            raise TaskConflict('Owner draw execution changes original Bank command, arrangement or beneficiary')
        draw = reading.resolve(owner.authorization_ref)
        if (not isinstance(draw, OwnerPaymentDrawView) or draw.organization_id != reading.organization_id
                or draw.arrangement_ref != owner.arrangement_ref or draw.beneficiary_id != owner.beneficiary_id
                or draw.amount.currency != owner.amount.currency
                or Fraction(Decimal(owner.amount.value)) > Fraction(Decimal(draw.amount.value))):
            raise TaskConflict('Owner observation changes original draw authorization or approved amount')
        currency = owner.amount.currency
        if Fraction(Decimal(owner.amount.value)) <= 0:
            raise TaskConflict('Owner draw observation requires a positive original execution amount')
        expected = {line.local_key: _values(line.amounts, currency) for line in execution.lines}
        approved_principal = sum((row['principal'] for row in expected.values()), Fraction())
        if (approval.amount.currency != currency
                or approved_principal != Fraction(Decimal(approval.amount.value))
                or any(expected[line.local_key]['principal'] <= 0
                    or line.transfer.requested.currency != currency
                    or Fraction(Decimal(line.transfer.requested.value)) != expected[line.local_key]['beneficiary_cash']
                    for line in execution.lines)
                or approved_principal <= 0 or approved_principal > Fraction(Decimal(owner.amount.value))):
            raise TaskConflict('Bank approval amount or original transfer/principal split does not match the Owner draw')
        obligation_refs = [ref for line in execution.lines for ref in line.transfer.obligation_refs]
        obligations = {ref.key() for ref in obligation_refs}
        authorized_obligations = set() if draw.direct_payment_obligation_ref is None else {draw.direct_payment_obligation_ref.key()}
        if (len({(ref.kind, ref.id) for ref in obligation_refs}) != len(obligation_refs)
                or len({(ref.kind, ref.id) for ref in owner.obligation_refs}) != len(owner.obligation_refs)
                or obligations != {ref.key() for ref in owner.obligation_refs}
                or obligations != authorized_obligations):
            raise TaskConflict('Owner execution changes original direct-payment obligation identities')
        if len({ref.key() for ref in execution.receipt_refs}) != len(execution.receipt_refs):
            raise TaskConflict('Original Bank execution repeats a receipt reference')
        if not set(execution.receipt_refs) <= set(saved.action_input.receipt_refs):
            raise TaskConflict('Received Bank command borrows receipts outside original reconciliation input')
        receipts = [BankExecutionReceiptView.model_validate(originals[ref.key()]) for ref in execution.receipt_refs]
        totals, states = _receipt_history(execution, receipts, currency, observed_by=saved.context.business_time)
        if owner.status == 'succeeded' and (any(state != 'verified_final' for state in states.values())
                or any(totals[key] != expected[key] for key in expected)
                or approved_principal != Fraction(Decimal(owner.amount.value))):
            raise TaskConflict('Unknown or partial Bank receipts cannot prove full Owner draw success')
        if owner.status in {'failed', 'rejected'} and (any(state != owner.status for state in states.values())
                or any(any(row.values()) for row in totals.values())):
            raise TaskConflict('Owner failure/rejection contradicts original verified cash or unresolved Bank history')
        if owner.status in {'succeeded', 'failed', 'rejected'}:
            receipt = reading.resolve(owner.receipt_ref) if owner.receipt_ref is not None else None
            if (not isinstance(receipt, OwnerPaymentReceiptView) or receipt.execution_ref != owner.ref
                    or receipt.command_id != owner.command_id or receipt.business_key != owner.business_key
                    or receipt.amount != owner.amount or receipt.beneficiary_id != owner.beneficiary_id
                    or receipt.status != owner.status):
                raise TaskConflict('Owner terminal observation lacks its exact independent actual receipt')
        if owner.status in {'unknown', 'pending'} and owner.receipt_ref is not None:
            raise TaskConflict('Unresolved Owner draw cannot claim a terminal payment receipt')
        points = [saved.context.business_time, reception.received_at, reception.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or any(row.observed_at.clock_ref != context.business_time.clock_ref
                    or row.observed_at.offset > saved.context.business_time.offset for row in receipts)):
            raise TaskConflict('Execution reception changes original receipt observation or reception chronology')
        for ref in reception.evidence_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(reception.received_at)):
                raise TaskConflict('Execution reception evidence was not applicable at actual reception')
        native = reading.resolve(reception.native_evidence_ref)
        if (not isinstance(native, EvidenceRecord) or native.basis_kind != 'observed'
                or native.content_hash != reception.native_record_sha256
                or (native.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')
                or native.effective_window is not None and not native.effective_window.contains(reception.received_at)):
            raise TaskConflict('Execution reception lacks observed actual command/receipt mapping')
        if validate_reception(saved=deepcopy(saved), reception=reception.model_copy(deep=True),
                bank_execution=execution.model_copy(deep=True), bank_receipts=[row.model_copy(deep=True) for row in receipts],
                owner_execution=owner.model_copy(deep=True),
                actual_amounts={key: {name: str(value) for name, value in row.items()} for key, row in totals.items()},
                context=context.model_copy(deep=True)) is not True:
            raise TaskConflict('Owner did not confirm native receipt completeness, authorization, settlement/cash effects and lawful mapping')
        return task_digest(reception.model_dump(mode='json'))
    finally:
        _recheck(prepared)
