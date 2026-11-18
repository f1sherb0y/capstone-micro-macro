"""Check retained payment-file consistency without authenticating native effects."""
from integration.owner_payment_settlement import OwnerNativeSettlementObservation, OwnerPaymentSettlementReconciler
from integration.owner_payment_submission import OwnerPaymentExecutionObservation
from src.actions.contracts.common import ActionContext, TimePoint
from src.coordination.tasks import task_digest


def validate_retained_payment_settlement(*, issued, settlement, provenance, context):
    """Return a terminal native payload digest, or None for an uncertain group.

    File declarations do not authenticate issuance, the original interval start,
    postings or beneficiary credit. The actual reader/reconciler and receiver
    still validate those facts against the original authorized journal. This
    only binds the retained files to one coherent complete observation.
    """
    context = ActionContext.model_validate(context)
    expected = {'schema_version': 'owner-payment-issued-reception.v1', **provenance}
    if (set(provenance) != {'source_identity', 'source_record_sha256',
            'source_result_sha256', 'source_reading_sha256'}
            or not isinstance(issued, dict)
            or set(issued) != {*expected, 'submission_receipt', 'payment_plan', 'observation'}
            or any(issued[key] != value for key, value in expected.items())):
        raise ValueError('Retained payment files change original issued provenance')
    observation = OwnerPaymentExecutionObservation.model_validate(issued['observation'])
    final = all(line.execution.status not in {'unknown', 'pending'} for line in observation.lines)
    if not final:
        if settlement is not None:
            raise ValueError('Pending/unknown payment group cannot retain a completed settlement')
        return None
    expected = {'schema_version': OwnerPaymentSettlementReconciler.VERSION, **provenance,
        'issued_reception_sha256': task_digest(issued)}
    if (not isinstance(settlement, dict)
            or set(settlement) != {*expected, 'native_settlement_sha256', 'observation', 'issued_reception', 'effects'}
            or any(settlement[key] != value for key, value in expected.items())
            or task_digest(settlement['issued_reception']) != task_digest(issued)
            or not isinstance(settlement['effects'], list)):
        raise ValueError('Terminal payment files require the original settlement and its exact embedded issued observation')
    ledger = OwnerNativeSettlementObservation.model_validate(settlement['observation'])
    # The saved result export contains no original ActionContext. Check this
    # declared interval for consistency here; the runtime handoff authenticates
    # its start against SavedOwnerPayment.context rather than trusting the file.
    start = TimePoint.model_validate(ledger.native_payload['interval_start'])
    native = {'schema_version': 'owner-payment-native-settlement.v1',
        'issued_reception_sha256': task_digest(issued), 'source_identity': provenance['source_identity'],
        'source_record_sha256': provenance['source_record_sha256'],
        'source_reading_sha256': provenance['source_reading_sha256'],
        'interval_start': start.model_dump(mode='json'),
        'observed_at': ledger.observed_at.model_dump(mode='json'),
        'balances': [pair.model_dump(mode='json') for pair in ledger.balances],
        'postings': [posting.model_dump(mode='json') for posting in ledger.postings], 'coverage': 'complete'}
    digest = task_digest(native)
    evidence = ledger.native_evidence
    if (task_digest(ledger.native_payload) != digest or settlement['native_settlement_sha256'] != digest
            or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed'
            or evidence.content_hash != digest
            or evidence.effective_window is not None and not evidence.effective_window.contains(ledger.observed_at)
            or start.clock_ref != ledger.observed_at.clock_ref
            or ledger.observed_at.clock_ref != context.business_time.clock_ref
            or not start.offset <= ledger.observed_at.offset <= context.business_time.offset
            or any(line.receipt is None or line.receipt.ref != line.execution.receipt_ref
                or line.receipt.status != line.execution.status
                or line.execution.available_at.clock_ref != start.clock_ref
                or line.receipt.available_at.clock_ref != start.clock_ref
                or not start.offset <= line.execution.available_at.offset
                    <= line.receipt.available_at.offset <= ledger.observed_at.offset for line in observation.lines)):
        raise ValueError('Retained settlement changes native payload, evidence, command outcomes or observation interval')
    return digest
