"""Original Owner A06 draw instruction to an actual received Bank A06 DrawRequest."""
from copy import deepcopy

from integration.bank_draw_actions import PreparedBankDraw
from integration.owner_payment_results import SavedOwnerPayment
from src.actions.contracts.bank_draw_objects import (
    BankDrawArrangementView, BankDrawConditionView, BankDrawRequestView, OwnerDrawRequestReceiptView,
)
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_payment_objects import (
    OwnerPaymentArrangementView, OwnerPaymentAuthorizationView, OwnerPaymentDrawConditionView,
    OwnerPaymentDrawView, OwnerPaymentScopeView,
)
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def _recheck(prepared):
    prepared.reading.recheck()
    if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
            or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Owner draw reception changed original Bank approval input or sources')


def read_received_owner_draw_request(prepared, *, source_task_sha256, receipt_ref,
        read_owner_payment, validate_reception, receipt_sha256=None):
    if not callable(read_owner_payment) or not callable(validate_reception):
        raise TaskConflict('Bank draw reception requires original Owner reader and actual receiver validator')
    try:
        saved = read_owner_payment(context=prepared.context.model_copy(deep=True),
            source_task_sha256=source_task_sha256)
        if not isinstance(saved, SavedOwnerPayment) or saved.identity.key != source_task_sha256:
            raise TaskConflict('Draw reader substituted the explicitly selected original Owner task')
        actual_sha256 = validate_received_owner_draw_request(saved, prepared=prepared, receipt_ref=receipt_ref,
            validate_reception=validate_reception)
        if receipt_sha256 is not None and receipt_sha256 != actual_sha256:
            raise TaskConflict('Owner draw receipt replaces the explicitly retained original reception')
        provenance = {'source_task_sha256': saved.identity.key, 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': task_digest(saved.result.model_dump(mode='json')),
            'source_reading_sha256': saved.source_reading_sha256,
            'receipt_ref': Reference.model_validate(receipt_ref).model_dump(mode='json'),
            'execution_source_reading_sha256': prepared.reading_sha256}
        if receipt_sha256 is not None:
            provenance['receipt_sha256'] = actual_sha256
        return provenance
    finally:
        _recheck(prepared)


def validate_received_owner_draw_request(saved, *, prepared, receipt_ref, validate_reception):
    """Retain original request amount, beneficiary, authorization and condition evidence.

    Destination accounts, purpose, transfer/fee basis and batch identity absent
    from the public Owner result must come from the observed native request.
    The authorized application verifies that complete mapping and original
    request history, including additional draws and unknown prior executions.
    Bank approval and transfer effects stay with their original boundaries.
    """
    context, reading = prepared.context, prepared.reading
    if (not isinstance(saved, SavedOwnerPayment) or not isinstance(prepared, PreparedBankDraw)
            or context.contract_ref.id != 'BANK-A06'
            or saved.identity.action_id != 'OWN-A06' or saved.identity.role != 'Owner'
            or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
            or saved.context.contract_ref.id != 'OWN-A06' or saved.context.execution_mode != context.execution_mode
            or saved.result.kind != 'completed' or saved.result.payload.choice != 'draw_request'
            or not callable(validate_reception)
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise TaskConflict('Draw reception requires original successful Owner draw instruction and actual Bank validation')
    reading.check_method_context(context, 'BANK-A06')
    if task_digest(reading.evidence()) != prepared.reading_sha256:
        raise TaskConflict('Draw reception changed original Bank source snapshot')
    try:
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        if any(saved.audit.get(key) != value for key, value in {
                'run_id': context.run_id, 'action_id': 'OWN-A06', 'operation_id': saved.context.operation_id,
                'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
                'result_kind': 'completed'}.items()):
            raise TaskConflict('Received request lacks original successful Owner draw audit')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Draw relation repeats an original Owner source')
            originals[key] = row['projection']
        receipt = reading.resolve(Reference.model_validate(receipt_ref))
        if (not isinstance(receipt, OwnerDrawRequestReceiptView)
                or receipt.run_id != context.run_id or receipt.recipient_organization_id != reading.organization_id
                or receipt.author_organization_id != saved.identity.organization_id
                or receipt.source_task_sha256 != saved.identity.key or receipt.source_record_sha256 != saved.record_sha256
                or receipt.source_result_sha256 != result_sha or receipt.source_reading_sha256 != saved.source_reading_sha256
                or receipt.draw_request_ref != prepared.action_input.draw_request_ref
                or not scope_covers(context.scope, receipt.scope) or not receipt.effective_window.contains(context.business_time)):
            raise TaskConflict('Draw receipt substitutes original Owner, Bank recipient, decision or request')
        subject = OwnerPaymentScopeView.model_validate(originals[saved.action_input.scope_ref.ref.key()])
        decision = OwnerPaymentAuthorizationView.model_validate(originals[subject.payment_authorization_ref.key()])
        draw = OwnerPaymentDrawView.model_validate(originals[receipt.owner_draw_authorization_ref.key()])
        arrangement = OwnerPaymentArrangementView.model_validate(originals[draw.arrangement_ref.key()])
        request = reading.resolve(receipt.draw_request_ref)
        if (not isinstance(request, BankDrawRequestView)
                or receipt.draw_request_sha256 != task_digest(request.model_dump(mode='json'))
                or receipt.owner_draw_authorization_sha256 != task_digest(draw.model_dump(mode='json'))
                or subject.organization_id != saved.identity.organization_id or decision.organization_id != subject.organization_id
                or decision.actor_id != saved.context.actor_id or decision.function_ref != saved.context.function_ref
                or decision.choice != 'draw_request' or decision.draw_authorization_ref != draw.ref
                or draw.organization_id != saved.identity.organization_id
                or draw.arrangement_ref != saved.result.payload.arrangement_ref
                or request.arrangement_ref != draw.arrangement_ref or request.arrangement_ref != prepared.action_input.arrangement_ref
                or request.borrower_id != draw.organization_id or request.lender_id != reading.organization_id
                or arrangement.borrower_id != request.borrower_id or arrangement.lender_id != request.lender_id
                or request.scope != receipt.scope or not scope_covers(saved.context.scope, receipt.scope)
                or request.author_action_id != 'OWN-A06' or request.author_actor_id != saved.context.actor_id
                or request.author_function_ref != saved.context.function_ref
                or request.author_authority_ref != decision.authority_ref
                or request.requested_amount != saved.result.payload.amount or draw.amount != saved.result.payload.amount
                or draw.beneficiary_id != saved.result.payload.beneficiary_id
                or request.purpose_ref != prepared.action_input.purpose_ref
                or receipt.transfer_lines != request.transfer_lines or not request.transfer_lines
                or any(line.beneficiary_id != draw.beneficiary_id for line in request.transfer_lines)):
            raise TaskConflict('Received request changes original complete draw instruction, amount, parties or native transfers')
        expected_obligations = set() if draw.direct_payment_obligation_ref is None else {draw.direct_payment_obligation_ref.key()}
        actual_obligations = [ref.key() for line in request.transfer_lines for ref in line.obligation_refs]
        if set(actual_obligations) != expected_obligations or len(set(actual_obligations)) != len(actual_obligations):
            raise TaskConflict('Received draw request duplicates or substitutes the original direct-payment obligation')
        grant = reading.resolve(request.author_authority_ref)
        original_grant = Authorization.model_validate(originals[request.author_authority_ref.key()])
        assignment = reading.resolve(request.author_function_ref)
        original_assignment = RoleAssignment.model_validate(originals[request.author_function_ref.key()])
        if (not isinstance(grant, Authorization) or grant != original_grant
                or not isinstance(assignment, RoleAssignment) or assignment != original_assignment
                or assignment.role != 'Owner' or assignment.function_ref != saved.context.function_ref
                or request.author_authority_ref not in saved.context.authorization_refs
                or grant.organization_id != request.borrower_id or grant.actor_id != request.author_actor_id
                or grant.function_ref != request.author_function_ref or 'OWN-A06' not in grant.action_ids
                or not grant.validity.contains(saved.context.business_time)
                or not any(scope_covers(scope, receipt.scope) for scope in grant.scopes)):
            raise TaskConflict('Actual draw request lacks original independent borrower authorization')
        relations = {row.original_ref.key(): row for row in receipt.condition_relations}
        if (len(relations) != len(receipt.condition_relations)
                or set(relations) != {ref.key() for ref in draw.condition_refs}
                or len({row.received_ref.key() for row in receipt.condition_relations}) != len(relations)):
            raise TaskConflict('Draw reception omits or duplicates original condition mappings')
        evidence = set()
        received_arrangement = reading.resolve(request.arrangement_ref)
        if not isinstance(received_arrangement, BankDrawArrangementView):
            raise TaskConflict('Draw reception requires original actual Bank facility projection')
        condition_roots = {ref.key() for ref in (*request.condition_refs, *received_arrangement.each_draw_condition_refs)}
        for key, relation in relations.items():
            original = OwnerPaymentDrawConditionView.model_validate(originals[key])
            current = reading.resolve(relation.received_ref)
            if (not isinstance(current, BankDrawConditionView)
                    or relation.original_sha256 != task_digest(originals[key])
                    or relation.received_sha256 != task_digest(current.model_dump(mode='json'))
                    or original.arrangement_ref != draw.arrangement_ref or original.draw_authorization_ref != draw.ref
                    or original.borrower_id != request.borrower_id or current.arrangement_ref != request.arrangement_ref
                    or current.stage not in {'batch', 'each_draw'} or current.draw_request_ref != request.ref
                    or current.ref.key() not in condition_roots
                    or original.satisfied != current.outcome
                    or original.verified_at != current.verified_at
                    or original.verified_at.clock_ref != saved.context.business_time.clock_ref
                    or original.available_at.clock_ref != original.verified_at.clock_ref
                    or original.verified_at.offset > original.available_at.offset
                    or original.available_at.offset > saved.context.business_time.offset
                    or original.evidence_ref not in current.verification_evidence_refs
                    or any(getattr(original, field) != getattr(current, field) for field in (
                        'verifier_organization_id', 'verifier_actor_id', 'verifier_function_ref',
                        'verifier_authority_ref', 'verifier_action_id'))):
                raise TaskConflict('Received draw condition changes original verification, evidence, authority or batch')
            evidence.add(original.evidence_ref.key())
        if (evidence != {ref.key() for ref in draw.condition_evidence_refs}
                or evidence != {ref.key() for ref in saved.result.payload.condition_refs}
                or not evidence <= {ref.key() for ref in prepared.action_input.condition_evidence_refs}):
            raise TaskConflict('Received request drops original independently verified draw evidence')
        points = [saved.context.business_time, request.available_at, receipt.received_at,
            receipt.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))):
            raise TaskConflict('Draw reception changes original instruction, request or receipt chronology')
        for ref in [*grant.basis_refs, *assignment.basis_refs]:
            source = reading.resolve(ref)
            if originals.get(ref.key()) != source.model_dump(mode='json'):
                raise TaskConflict('Draw author basis changes its original saved source content')
            if ref.kind == 'Evidence':
                if (not isinstance(source, EvidenceRecord) or source.effective_window is not None
                        and not source.effective_window.contains(saved.context.business_time)):
                    raise TaskConflict('Draw author evidence was not valid at the original Owner instruction')
        for ref in receipt.evidence_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(receipt.received_at)):
                raise TaskConflict('Draw receipt evidence was not applicable at actual reception')
        native = reading.resolve(receipt.native_evidence_ref)
        if (not isinstance(native, EvidenceRecord) or native.basis_kind != 'observed'
                or native.content_hash != receipt.native_record_sha256
                or (native.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')
                or native.effective_window is not None and not native.effective_window.contains(receipt.received_at)):
            raise TaskConflict('Draw receipt lacks observed actual native borrower request')
        if validate_reception(saved=deepcopy(saved), receipt=receipt.model_copy(deep=True),
                owner_authorization=draw.model_copy(deep=True), owner_arrangement=arrangement.model_copy(deep=True),
                request=request.model_copy(deep=True), context=context.model_copy(deep=True)) is not True:
            raise TaskConflict('Bank did not confirm actual request, destination/fee/purpose mapping, history and lawful disclosure')
        return task_digest(receipt.model_dump(mode='json'))
    finally:
        _recheck(prepared)
