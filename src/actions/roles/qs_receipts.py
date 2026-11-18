"""Original QS cash streams; aliases and cumulative events never add cash twice."""
from fractions import Fraction
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_payment_objects import QSPaymentReceiptView, QSPaymentExecutionView
from src.actions.roles.owner import _needs


def reconcile_original_receipts(contract, refs, read, amount):
    unique_refs(refs)
    events, streams, businesses = {}, {}, {}
    for ref in refs:
        row = read(ref, QSPaymentReceiptView)
        if row.contract_ref != contract.ref or row.payer_id != contract.payer_id or row.beneficiary_id != contract.beneficiary_id:
            raise ValueError('Payment receipt changes original contract or payer/beneficiary')
        execution = read(row.execution_ref, QSPaymentExecutionView)
        fields = ('contract_ref', 'certificate_ref', 'credit_ref', 'purpose', 'payer_id', 'beneficiary_id', 'command_id', 'business_key')
        if any(getattr(row, field) != getattr(execution, field) for field in fields) or ref not in execution.receipt_refs:
            raise ValueError('Receipt changes its original payment execution or command')
        unique_refs(execution.receipt_refs)
        if not set(execution.receipt_refs) <= set(refs):
            _needs('complete_original_payment_execution_receipts', [execution.ref])
        if row.purpose == 'advance':
            if row.credit_ref is None or row.certificate_ref is not None:
                raise ValueError('Advance cash must reference its original credit, not a certificate payment')
        elif row.certificate_ref is None or row.credit_ref is not None:
            raise ValueError('Certified cash must reference its original certificate, not an advance credit')
        business = (row.purpose, row.business_key)
        if business in businesses and businesses[business] != execution.ref.key():
            _needs('reconciled_same_business_payment_executions', [execution.ref])
        businesses[business] = execution.ref.key()
        body = row.model_dump(mode='json'); body.pop('ref'); body.pop('evidence_refs'); body.pop('available_at'); body.pop('effective_window')
        if row.event_id in events:
            if events[row.event_id] != body:
                raise ValueError('Repeated payment event changes original cash content')
            continue
        events[row.event_id] = body
        streams.setdefault(execution.ref.key(), []).append(row)
    totals = {}
    for rows in streams.values():
        rows.sort(key=lambda row: row.sequence)
        if len({r.sequence for r in rows}) != len(rows) or len({r.semantics for r in rows}) != 1:
            raise ValueError('Payment stream has ambiguous original sequence or cash semantics')
        total, uncertain = Fraction(), False
        for row in rows:
            if row.status in {'failed', 'rejected'}:
                if row.amount.state == 'known' and amount(row.amount.value) != 0:
                    raise ValueError('Failed payment event cannot recognize positive cash')
                continue
            if row.status == 'unknown' or row.amount.state != 'known':
                uncertain = True; continue
            value = amount(row.amount.value)
            if value < 0:
                raise ValueError('Refunds require their separately authorized execution')
            if row.semantics == 'cumulative':
                if value < total:
                    raise ValueError('Original cumulative receipt cannot erase already received cash')
                total = value
            else:
                total += value
        identity = (rows[0].purpose, rows[0].credit_ref or rows[0].certificate_ref)
        old_value, old_uncertain = totals.get(identity, (Fraction(), False))
        totals[identity] = (old_value + total, old_uncertain or uncertain)
    return totals
