"""Archive actual original debt-resolution results without releasing debt or replaying them."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.bank_resolution_objects import (
    BankResolutionArrangementView, BankResolutionProfileView, BankResolutionExecutionView,
)
from src.actions.contracts.bank_debt_objects import BankDebtExecutionView, BankDebtReceiptView
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.bank_debt_conditions import BankDebtConditionReading
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


EXECUTION_CODE = 'query_original_resolution_or_cash_execution'
_TERMINAL = {'succeeded', 'failed', 'rejected'}
_PROFILE_METADATA = {'ref', 'arrangement_ref', 'available_at', 'effective_window'}


@dataclass(frozen=True)
class BankResolutionTerminalReading(BankDebtConditionReading):
    queried_execution_refs: tuple[Reference, ...] = ()


def check_original_resolution_payments(*, arrangement, payments, read, original_context):
    """Recheck the completed payment facts preceding the original A10 wait."""
    at = original_context.business_time
    payment_refs, commands, business, events = set(), set(), set(), set()

    def amount(value):
        number = decimal_fraction(value.value)
        if value.currency != arrangement.currency or number < 0:
            raise TaskConflict('Resolution archive changes original payment currency or nonnegative amount')
        return number

    for payment in payments:
        physical = payment.ref.key()[:2]
        if physical in payment_refs or payment.command_id in commands or payment.business_key in business:
            raise TaskConflict('Resolution archive repeats an original payment identity/command/business key')
        payment_refs.add(physical); commands.add(payment.command_id); business.add(payment.business_key)
        if payment.status in {'unknown', 'pending', 'partial'}:
            raise TaskConflict('Resolution archive bypasses original earlier uncertain payment gate')
        if payment.status == 'succeeded' and not payment.receipt_refs:
            raise TaskConflict('Resolution archive lacks original successful payment receipts')
        if len({ref.key()[:2] for ref in payment.receipt_refs}) != len(payment.receipt_refs):
            raise TaskConflict('Resolution archive duplicates original payment receipt references')
        for ref in payment.receipt_refs:
            receipt = read(ref, BankDebtReceiptView, original=True)
            if (receipt.execution_ref != payment.ref or receipt.arrangement_ref != arrangement.ref
                    or receipt.lender_id != arrangement.lender_id or receipt.borrower_id != arrangement.borrower_id
                    or receipt.command_id != payment.command_id or receipt.business_key != payment.business_key
                    or receipt.event_id in events):
                raise TaskConflict('Resolution archive substitutes or repeats original actual payment receipt')
            if (any(point.clock_ref != at.clock_ref for point in (
                    receipt.effective_at, receipt.verified_at, receipt.available_at))
                    or not receipt.effective_at.offset <= receipt.verified_at.offset <= receipt.available_at.offset <= at.offset):
                raise TaskConflict('Resolution archive introduces a receipt not effective and verified at original wait time')
            received = amount(receipt.amount)
            if received <= 0:
                raise TaskConflict('Resolution archive requires positive original actual receipt amount')
            effects = [effect.debt_component_ref.key()[:2] for effect in receipt.principal_effects]
            if len(set(effects)) != len(effects):
                raise TaskConflict('Resolution archive duplicates original receipt principal effects')
            if sum((amount(effect.amount) for effect in receipt.principal_effects), 0) > received:
                raise TaskConflict('Resolution archive receipt principal effects exceed original actual amount')
            events.add(receipt.event_id)


def check_bank_resolution_terminal(check, selected, validate_relation, *, terminal=False, closeout=False):
    action_id = 'BANK-A11' if closeout else 'BANK-A10'
    code = 'query_original_finance_closeout_or_payment' if closeout else EXECUTION_CODE
    execution_kind = 'FinanceCloseoutExecution' if closeout else 'DebtResolutionExecution'
    arrangement_type, profile_type, execution_type = (
        BankResolutionArrangementView, BankResolutionProfileView, BankResolutionExecutionView)
    if closeout:
        from src.actions.contracts.bank_closeout_objects import (
            BankCloseoutArrangementView, BankCloseoutProfileView, BankCloseoutExecutionView,
        )
        arrangement_type, profile_type, execution_type = (
            BankCloseoutArrangementView, BankCloseoutProfileView, BankCloseoutExecutionView)
    source = check.source['identity']
    if (terminal is not True or source['action_id'] != action_id or source['role'] != 'Bank'
            or source['purpose'] != 'action' or check.condition.condition_code != code
            or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != (execution_kind,)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, BankResolutionTerminalReading) or not isinstance(selected.reading, ActionReadView)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not callable(validate_relation)):
        raise TaskConflict('Resolution terminal archive requires original same-business execution wait')
    context, original_context, reading = selected.context, selected.original_context, selected.reading
    original_input = selected.original_action_input
    raw = original_input.model_dump(mode='json')
    if (raw != selected.action_input.model_dump(mode='json') or task_digest(raw) != source['input_sha256']
            or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or original_context.operation_id != source['request_id'] or context.operation_id != source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original_context.contract_ref
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != action_id
            or context.actor_id != original_context.actor_id or context.function_ref != original_context.function_ref
            or context.scope != original_context.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Resolution terminal archive replaces original input, firm, scope or actual current authority')
    reading.check_method_context(context, action_id)
    rows = {}

    def read(ref, schema, *, original=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            raise TaskConflict('Resolution terminal archive lacks exact original/query typed sources')
        at = original_context.business_time if original else context.business_time
        if hasattr(row, 'available_at') and (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Resolution terminal archive introduces unavailable original/query sources')
        rows[ref.key()] = row
        return row

    arrangement = read(original_input.arrangement_ref, arrangement_type, original=True)
    profile_ref = arrangement.closeout_profile_ref if closeout else original_input.resolution_profile_ref
    profile = read(profile_ref, profile_type, original=True)
    affected_scope = profile.scope_ref if closeout else profile.affected_scope
    if (arrangement.lender_id != source['organization_id'] or arrangement.coverage != 'complete'
            or arrangement.as_of != original_context.business_time or profile.organization_id != arrangement.lender_id
            or profile.arrangement_ref != arrangement.ref or profile.actor_id != original_context.actor_id
            or profile.function_ref != original_context.function_ref or profile.scope != original_context.scope
            or not closeout and profile.authority_ref != original_input.authority_ref
            or profile.authority_ref not in original_context.authorization_refs
            or not scope_covers(arrangement.scope, original_context.scope)
            or not scope_covers(original_context.scope, affected_scope)):
        raise TaskConflict('Resolution terminal archive changes original complete facility, profile or affected scope')
    input_links = (('debt_refs', 'debt_refs'), ('security_refs', 'security_refs')) if closeout else (
        ('notice_refs', 'notice_refs'), ('unpaid_refs', 'obligation_refs'),
        ('security_refs', 'security_refs'), ('remedy_refs', 'remedy_refs'))
    for supplied, saved in input_links:
        refs = getattr(original_input, supplied)
        if len({ref.key() for ref in refs}) != len(refs) or {ref.key() for ref in refs} != {ref.key() for ref in getattr(arrangement, saved)}:
            raise TaskConflict('Resolution terminal archive omits original obligations, rights or remedy history')
    grant = read(profile.authority_ref, Authorization)
    function = read(profile.function_ref, RoleAssignment)
    if (grant.organization_id != arrangement.lender_id or grant.actor_id != original_context.actor_id
            or grant.function_ref != original_context.function_ref or action_id not in grant.action_ids
            or grant.validity.start.clock_ref != original_context.business_time.clock_ref
            or grant.validity.end.clock_ref != original_context.business_time.clock_ref
            or not grant.validity.contains(original_context.business_time) or function.role != 'Bank'
            or not any(scope_covers(scope, original_context.scope) for scope in grant.scopes)):
        raise TaskConflict('Resolution terminal archive lacks original independent Bank action authority')
    payments = []
    for ref in arrangement.payment_execution_refs:
        payment = read(ref, BankDebtExecutionView, original=True)
        if (payment.arrangement_ref != arrangement.ref or payment.lender_id != arrangement.lender_id
                or payment.borrower_id != arrangement.borrower_id
                or not closeout and payment.status in {'unknown', 'pending', 'partial'}):
            raise TaskConflict('Resolution terminal archive bypasses original earlier uncertain payment gate')
        payments.append(payment)
    if closeout:
        from src.coordination.bank_closeout_terminal import check_original_closeout_ledger
        check_original_closeout_ledger(original_input=original_input, arrangement=arrangement,
            payments=payments, read=read, original_context=original_context)
    else:
        check_original_resolution_payments(arrangement=arrangement, payments=payments,
            read=read, original_context=original_context)
    execution_refs = arrangement.closeout_execution_refs if closeout else arrangement.resolution_execution_refs
    history = [read(ref, execution_type, original=True) for ref in execution_refs]
    if (len({row.business_key for row in history}) != len(history)
            or len({row.ref.key()[:2] for row in history}) != len(history)
            or any(row.organization_id != arrangement.lender_id or row.run_id != source['run_id']
                or row.arrangement_ref.key()[:2] != arrangement.ref.key()[:2] for row in history)):
        raise TaskConflict('Resolution terminal archive duplicates or substitutes original business history')
    def blocked(row):
        if row.business_key == profile.business_key:
            return True
        if closeout:
            overlap = (affected_scope.kind == row.affected_scope.kind and affected_scope.ref == row.affected_scope.ref
                and (affected_scope == row.affected_scope or bool({ref.key() for ref in affected_scope.coverage_refs}
                    & {ref.key() for ref in row.affected_scope.coverage_refs})))
            return (profile.choice != 'retain' and row.status in {'unknown', 'pending'}
                and overlap)
        return row.status in {'unknown', 'pending'} and profile.choice in {'accept_restructure', 'enforce', 'accounting_writeoff'}

    first = next((row for row in history if blocked(row)), None)
    if first is None or first.business_key != profile.business_key or tuple(check.condition.object_refs) != (first.ref,):
        raise TaskConflict('Resolution terminal archive differs from original first same-business gate')
    executed_profile = read(first.profile_ref, profile_type, original=True)
    if (executed_profile.arrangement_ref != first.arrangement_ref
            or executed_profile.organization_id != first.organization_id or executed_profile.scope != first.scope
            or executed_profile.business_key != first.business_key
            or closeout and executed_profile.scope_ref != first.affected_scope
            or content_digest(executed_profile) != first.profile_sha256
            or executed_profile.model_dump(exclude=_PROFILE_METADATA) != profile.model_dump(exclude=_PROFILE_METADATA)):
        raise TaskConflict('Resolution terminal archive rewrites original executed profile/business content')
    if len(selected.queried_execution_refs) != 1 or selected.queried_execution_refs[0].key()[:2] != first.ref.key()[:2]:
        raise TaskConflict('Resolution terminal archive replaces original execution identity')
    execution = read(selected.queried_execution_refs[0], execution_type)
    identity_fields = ('organization_id', 'run_id', 'arrangement_ref', 'business_key', 'profile_ref', 'profile_sha256', 'scope')
    if closeout:
        identity_fields += ('affected_scope',)
    if (any(getattr(first, field) != getattr(execution, field) for field in identity_fields)
            or first.status in _TERMINAL and first.status != execution.status):
        raise TaskConflict('Resolution terminal archive rewrites original execution content or known result')
    now = context.business_time
    if (execution.effective_window.start.clock_ref != now.clock_ref or execution.effective_window.end.clock_ref != now.clock_ref
            or not execution.effective_window.contains(now)):
        return 'unavailable', None
    if execution.status not in _TERMINAL or not execution.evidence_refs:
        return 'waiting', None
    evidence = []
    for ref in execution.evidence_refs:
        row = read(ref, EvidenceRecord)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Resolution terminal archive requires actual observed execution query evidence')
        if row.effective_window is not None and (row.effective_window.start.clock_ref != now.clock_ref
                or row.effective_window.end.clock_ref != now.clock_ref or not row.effective_window.contains(now)):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    # Retain original debts, rights, notices and remedy sources in the archive;
    # a resolution outcome alone does not prove forgiveness, enforcement or cash.
    for ref in (*walk_references(original_input), *walk_references(arrangement)):
        reading.resolve(ref)
    resolution = dict(schema_version='bank-closeout-execution-resolution.v1' if closeout else 'bank-resolution-execution-resolution.v1', disposition=execution.status,
        execution=execution.model_dump(mode='json'), original_action_input=raw, action_input=raw,
        original_context=original_context.model_dump(mode='json'), context=context.model_dump(mode='json'),
        sources=reading.evidence(), evidence=evidence)
    terminal_option = {'terminal_closeout_execution': True} if closeout else {'terminal_resolution_execution': True}
    if validate_relation(source_identity=deepcopy(source), condition_code=code, **terminal_option,
            original_context=original_context.model_copy(deep=True), original_action_input=raw,
            context=context.model_copy(deep=True), resolution=deepcopy(resolution), reading=reading) is not True:
        raise TaskConflict('Resolution terminal archive lacks native original execution/debt/current authority authentication')
    return 'ready', resolution
