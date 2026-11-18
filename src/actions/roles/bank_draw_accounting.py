"""Read original draw usage and receipts without changing approval, cash or debt."""
from fractions import Fraction
from src.actions.contracts.bank_draw_objects import BankDrawExecutionView, BankDrawBatchView
from src.actions.roles.owner import _needs
from src.methods.pricing import decimal_fraction


def read_draw_usage(*, capacity, arrangement, lender, currency, read, amount, receipt, evidence, keys):
    """Return usage and consumed physical receipt identities across all batches."""
    def same(left, right):
        return left.key() == right.key()

    usage, executed, batch_keys = Fraction(), Fraction(), set()
    batches, execution_rows, receipt_ids = {}, {}, set()
    for ref in capacity.execution_refs:
        row = read(ref, BankDrawExecutionView, historical=True)
        if row.lender_id != lender or not same(row.arrangement_ref, arrangement.ref): raise ValueError('Pending execution changes original facility/lender')
        amount(row.amount, currency, True); execution_rows[ref.key()] = row
    if len({row.command_id for row in execution_rows.values()}) != len(execution_rows):
        raise ValueError('Draw capacity copies an original execution command')
    for ref in capacity.approved_batch_refs:
        batch = read(ref, BankDrawBatchView, historical=True)
        if batch.lender_id != lender or not same(batch.arrangement_ref, arrangement.ref) or batch.batch_key in batch_keys:
            raise ValueError('Draw capacity copies or changes an actual facility batch')
        batch_keys.add(batch.batch_key); batches[ref.key()] = batch
        approved = amount(batch.approved_amount, currency, True); released = amount(batch.released_amount, currency)
        actual = amount(batch.executed_principal, currency); executed += actual
        if actual + released > approved: raise ValueError('Executed/released draw principal exceeds original approval')
        usage += approved - released
        keys(batch.execution_refs); batch_unknown, batch_actual = Fraction(), Fraction()
        for ref_ in batch.execution_refs:
            row = execution_rows.get(ref_.key())
            if row is None or not same(row.batch_ref, batch.ref) or not same(row.draw_request_ref, batch.draw_request_ref):
                raise ValueError('Batch snapshot drops or changes an original execution identity')
            if row.status in {'unknown', 'pending'}: batch_unknown += decimal_fraction(row.amount.value)
            else:
                if row.receipt_ref is None: _needs('original_terminal_draw_execution_receipt', [row.ref])
                r, value = receipt(row.receipt_ref, currency)
                receipt_identity = (r.ref.kind, r.ref.id)
                if receipt_identity in receipt_ids: raise ValueError('Draw execution reuses an original receipt across versions')
                receipt_ids.add(receipt_identity)
                if (r.kind != 'draw' or r.batch_ref is None or not same(r.batch_ref, batch.ref)
                        or r.command_id != row.command_id or r.status != row.status or value != decimal_fraction(row.amount.value)):
                    raise ValueError('Draw receipt changes original execution amount/command/status')
                if row.status == 'succeeded': batch_actual += value
        if batch_actual != actual or batch_unknown > approved - released - actual:
            raise ValueError('Original executed/unknown principal is not retained within approved facility usage')
        release_total = Fraction(); keys(batch.release_receipt_refs)
        for ref_ in batch.release_receipt_refs:
            r, value = receipt(ref_, currency)
            receipt_identity = (r.ref.kind, r.ref.id)
            if (receipt_identity in receipt_ids or r.kind != 'draw_cancelled' or r.status != 'succeeded'
                    or r.batch_ref is None or not same(r.batch_ref, batch.ref)):
                raise ValueError('Draw release has no distinct effective cancellation receipt')
            receipt_ids.add(receipt_identity); release_total += value
        if release_total != released: raise ValueError('Released facility amount differs from original effective cancellation receipts')
        if released and batch.release_basis_ref is None: _needs('original_effective_draw_release_basis')
        if batch.release_basis_ref is not None: evidence([batch.release_basis_ref])
    if keys([r for batch in batches.values() for r in batch.execution_refs]) != keys(capacity.execution_refs):
        raise ValueError('Facility executions are omitted, copied or unrelated to original approved batches')
    return usage, executed, batches, execution_rows, receipt_ids
