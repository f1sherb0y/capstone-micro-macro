"""Recompute BANK-A07 original-command waits from current authorized native sources."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.bank_execution_objects import BankExecutionReceiptView, BankExecutionSavedView
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class BankExecutionConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_refs: tuple[Reference, ...]
    action_input: dict | None = None


def bank_original_payment_command_profile(read_current, validate_relation):
    """Register the exact event wait emitted by the original A07 processor.

    read_current(check) independently supplies a formal current reading and
    current versions of all original PaymentExecution references. Both old
    and new versions must be authorized in that reading. validate_relation
    authenticates the native query/dispatch/receipt history and full coverage;
    the scheduling signal does not establish any of those facts. This profile
    does not query, submit, alter money, or select a new payment command.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Bank execution wait requires independent current reader and actual query-history validator')
    code = 'query_original_payment_command_before_new_execution'

    def evaluate(check):
        source = check.source['identity']
        old_refs = check.condition.object_refs
        if (source['action_id'] != 'BANK-A07' or source['role'] != 'Bank' or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'event'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or not old_refs or len(set(old_refs)) != len(old_refs)
                or len({(ref.kind, ref.id) for ref in old_refs}) != len(old_refs)
                or any(ref.kind != 'PaymentExecution' for ref in old_refs)):
            raise TaskConflict('Bank wait changes original task, recipient or complete original execution selection')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, BankExecutionConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.execution_refs, tuple)
                or any(not isinstance(ref, Reference) for ref in selected.execution_refs)):
            raise TaskConflict('Bank wait requires a typed current authorized execution reading')
        context, reading, refs = selected.context.model_copy(deep=True), selected.reading, selected.execution_refs
        if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'BANK-A07'
                or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                or context.business_time != check.signal.business_time
                or context.operation_id == source['request_id']
                or len(refs) != len(old_refs) or len(set(refs)) != len(refs)
                or {(ref.kind, ref.id) for ref in refs} != {(ref.kind, ref.id) for ref in old_refs}):
            raise TaskConflict('Bank wait substitutes current run/action/read point or original command identities')
        reading.check_method_context(context, 'BANK-A07')
        current_refs = {(ref.kind, ref.id): ref for ref in refs}
        originals, currents, receipts, observed = [], [], [], {}
        commands, businesses, events = set(), set(), set()
        now = context.business_time

        def actual_evidence(ref):
            item = reading.resolve(ref)
            if (not isinstance(item, EvidenceRecord) or item.source_kind == 'synthetic' or item.basis_kind != 'observed'):
                raise TaskConflict('Bank wait needs independent observed actual query/receipt evidence')
            if item.effective_window is not None and not item.effective_window.contains(now):
                return False
            observed[ref.key()] = item.model_dump(mode='json')
            return True

        try:
            for old_ref in old_refs:
                current_ref = current_refs[(old_ref.kind, old_ref.id)]
                original, current = reading.resolve(old_ref), reading.resolve(current_ref)
                if (not isinstance(original, BankExecutionSavedView) or not isinstance(current, BankExecutionSavedView)
                        or original.ref != old_ref or current.ref != current_ref
                        or current.lender_id != source['organization_id']
                        or any(getattr(original, field) != getattr(current, field) for field in (
                            'lender_id', 'borrower_id', 'arrangement_ref', 'approval_ref', 'path_ref',
                            'command_id', 'business_key', 'lines', 'scope'))
                        or current.command_id in commands or current.business_key in businesses):
                    raise TaskConflict('Bank current query changes original command, participants, approval, financial split or scope')
                commands.add(current.command_id); businesses.add(current.business_key)
                if (current.available_at.clock_ref != now.clock_ref or current.available_at.offset > now.offset
                        or not current.effective_window.contains(now)):
                    return 'unavailable'
                if (current.receipt_coverage != 'complete' or current.dispatch_state == 'unknown'
                        or current.confirmed_unexecuted_amount.state != 'known'
                        or set(current.line_dispatch_states) != {line.local_key for line in current.lines}
                        or 'unknown' in current.line_dispatch_states.values()):
                    return 'waiting'
                if len(set(current.receipt_refs)) != len(current.receipt_refs):
                    raise TaskConflict('Bank query repeats an original receipt reference')
                for ref in [current.dispatch_evidence_ref, *current.evidence_refs]:
                    if not actual_evidence(ref):
                        return 'unavailable'
                originals.append(original.model_dump(mode='json'))
                currents.append(current.model_dump(mode='json'))
                for ref in current.receipt_refs:
                    receipt = reading.resolve(ref)
                    if (not isinstance(receipt, BankExecutionReceiptView) or receipt.ref != ref
                            or (receipt.execution_ref.kind, receipt.execution_ref.id) != (current.ref.kind, current.ref.id)
                            or any(getattr(receipt, field) != getattr(current, field) for field in (
                                'lender_id', 'borrower_id', 'arrangement_ref', 'approval_ref', 'path_ref', 'command_id', 'business_key'))
                            or receipt.event_id in events):
                        raise TaskConflict('Bank query substitutes another original command receipt or repeats a native event')
                    events.add(receipt.event_id)
                    if (receipt.observed_at.clock_ref != now.clock_ref or receipt.observed_at.offset > now.offset
                            or receipt.available_at.clock_ref != now.clock_ref
                            or not receipt.observed_at.offset <= receipt.available_at.offset <= now.offset
                            or not receipt.effective_window.contains(now)):
                        return 'unavailable'
                    if receipt.status == 'unknown' or receipt.confirmed_unexecuted_amount.state != 'known':
                        return 'waiting'
                    for evidence_ref in receipt.evidence_refs:
                        if not actual_evidence(evidence_ref):
                            return 'unavailable'
                    receipts.append(receipt.model_dump(mode='json'))
            if validate_relation(source_identity=deepcopy(source), original_executions=deepcopy(originals),
                    current_executions=deepcopy(currents), receipts=deepcopy(receipts),
                    evidence=deepcopy(list(observed.values())), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Bank wait lacks authentic complete original native query/receipt coverage')
            # A known partial, failure, rejection or undispatched remainder only
            # permits a fresh decision. The normal processor still validates all
            # amounts/permissions; no successful payment or new dispatch follows.
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('BANK-A07', code, '1', frozenset({'event'}), evaluate)
