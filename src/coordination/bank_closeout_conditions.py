"""Read original finance closeout/payment outcomes before fresh BANK-A11 work."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.bank_closeout_objects import BankCloseoutExecutionView, BankCloseoutProfileView
from src.actions.contracts.bank_debt_objects import BankDebtExecutionView, BankDebtReceiptView
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class BankCloseoutExecutionConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_ref: Reference
    profile_ref: Reference | None = None


def bank_original_closeout_execution_profile(read_current, validate_relation):
    """Register the exact dependency wait emitted by the original A11 processor.

    The application holds current source/authority/journal boundaries, supplies
    original and explicit current execution versions, and authenticates native
    query coverage independently. Payment receipts remain original evidence;
    no balance, debt, commitment or security is cleared by this condition.
    """
    return _bank_original_finance_execution_profile(read_current, validate_relation,
        action_id='BANK-A11', code='query_original_finance_closeout_or_payment',
        execution_kind='FinanceCloseoutExecution', execution_schema=BankCloseoutExecutionView,
        profile_schema=BankCloseoutProfileView,
        reading_type=BankCloseoutExecutionConditionReading, extra_identity_fields=('affected_scope',))


def _bank_original_finance_execution_profile(read_current, validate_relation, *, action_id, code,
        execution_kind, execution_schema, profile_schema, reading_type, extra_identity_fields=()):
    """Share original native payment/receipt checks between A10 and A11."""
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Bank finance wait requires current sources and independent actual query validation')
    schemas = {execution_kind: execution_schema, 'PaymentExecution': BankDebtExecutionView}

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != action_id or source['role'] != 'Bank' or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind not in schemas):
            raise TaskConflict('Bank closeout wait changes original task, recipient or execution selection')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, reading_type)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.execution_ref, Reference)):
            raise TaskConflict('Bank closeout wait requires typed current authorized execution sources')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        ref = selected.execution_ref.model_copy(deep=True)
        if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                or context.contract_ref.id != action_id or context.execution_mode != 'llm'
                or reading._resolver.source_mode != 'formal' or context.business_time != check.signal.business_time
                or context.operation_id == source['request_id']
                or (ref.kind, ref.id) != (old_refs[0].kind, old_refs[0].id)):
            raise TaskConflict('Bank closeout wait substitutes current context or original execution identity')
        reading.check_method_context(context, action_id)
        now = context.business_time
        receipts, observations = [], {}

        def actual_evidence(evidence_ref):
            evidence = reading.resolve(evidence_ref)
            if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic'
                    or evidence.basis_kind != 'observed'):
                raise TaskConflict('Bank closeout query lacks independent actual observed execution evidence')
            if evidence.effective_window is not None and not evidence.effective_window.contains(now):
                return False
            observations[evidence.ref.key()] = evidence.model_dump(mode='json')
            return True

        try:
            original, current = reading.resolve(old_refs[0]), reading.resolve(ref)
            schema = schemas[ref.kind]
            if (not isinstance(original, schema) or not isinstance(current, schema)
                    or original.ref.key() != old_refs[0].key() or current.ref.key() != ref.key()):
                raise TaskConflict('Bank closeout query changes original execution schema or reference')
            fields = ('arrangement_ref', 'business_key', 'scope')
            if ref.kind == execution_kind:
                fields += ('organization_id', 'run_id', 'profile_ref', 'profile_sha256', *extra_identity_fields)
                if current.organization_id != source['organization_id'] or current.run_id != source['run_id']:
                    raise TaskConflict('Finance closeout query changes original Bank or run')
            else:
                fields += ('lender_id', 'borrower_id', 'command_id')
                if (current.lender_id != source['organization_id']
                        or len({item.key() for item in current.receipt_refs}) != len(current.receipt_refs)
                        or not {item.key() for item in original.receipt_refs}
                            <= {item.key() for item in current.receipt_refs}):
                    raise TaskConflict('Finance payment query changes original lender or drops actual original receipts')
            if (any(getattr(original, field) != getattr(current, field) for field in fields)
                    or original.status in {'succeeded', 'failed', 'rejected'} and current.status != original.status):
                raise TaskConflict('Bank closeout query changes original business identity or a known final outcome')
            if ref.kind == execution_kind:
                executed_profile = reading.resolve(current.profile_ref)
                if (not isinstance(executed_profile, profile_schema) or executed_profile.ref != current.profile_ref
                        or executed_profile.arrangement_ref != current.arrangement_ref
                        or executed_profile.organization_id != current.organization_id
                        or executed_profile.scope != current.scope or executed_profile.business_key != current.business_key
                        or execution_kind == 'FinanceCloseoutExecution' and executed_profile.scope_ref != current.affected_scope
                        or content_digest(executed_profile) != current.profile_sha256):
                    raise TaskConflict('Finance query substitutes the original execution profile, facility or scope')
                if (executed_profile.available_at.clock_ref != now.clock_ref
                        or executed_profile.available_at.offset > now.offset):
                    return 'unavailable'
            if (current.available_at.clock_ref != now.clock_ref or current.available_at.offset > now.offset
                    or not current.effective_window.contains(now)):
                return 'unavailable'
            if current.status in {'unknown', 'pending', 'partial'}:
                return 'waiting'
            if ref.kind == 'PaymentExecution':
                if current.status == 'succeeded' and not current.receipt_refs:
                    return 'unavailable'
                events = set()
                for receipt_ref in current.receipt_refs:
                    receipt = reading.resolve(receipt_ref)
                    if (not isinstance(receipt, BankDebtReceiptView) or receipt.ref.key() != receipt_ref.key()
                            or (receipt.execution_ref.kind, receipt.execution_ref.id) != (ref.kind, ref.id)
                            or any(getattr(receipt, field) != getattr(current, field) for field in (
                                'arrangement_ref', 'lender_id', 'borrower_id', 'command_id', 'business_key'))
                            or receipt.event_id in events):
                        raise TaskConflict('Finance payment query substitutes or repeats an original receipt event')
                    events.add(receipt.event_id)
                    if (any(point.clock_ref != now.clock_ref for point in (
                            receipt.effective_at, receipt.verified_at, receipt.available_at))
                            or not receipt.effective_at.offset <= receipt.verified_at.offset <= receipt.available_at.offset <= now.offset):
                        return 'unavailable'
                    for evidence_ref in [*receipt.evidence_refs, receipt.amount.basis_ref]:
                        if not actual_evidence(evidence_ref):
                            return 'unavailable'
                    receipts.append(receipt.model_dump(mode='json'))
            for evidence_ref in current.evidence_refs:
                if not actual_evidence(evidence_ref):
                    return 'unavailable'
            if not observations:
                return 'unavailable'
            reading.recheck()
            if validate_relation(source_identity=deepcopy(source), original_execution=original.model_dump(mode='json'),
                    current_execution=current.model_dump(mode='json'), receipts=deepcopy(receipts),
                    evidence=deepcopy(list(observations.values())), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Bank closeout wait lacks authentic complete original native query coverage')
            profile_ref = getattr(selected, 'profile_ref', None)
            if ref.kind == execution_kind and profile_ref is not None:
                profile = reading.resolve(profile_ref)
                if (not isinstance(profile, profile_schema) or profile.ref != profile_ref
                        or profile.organization_id != source['organization_id'] or profile.scope != context.scope
                        or profile.arrangement_ref.key()[:2] != current.arrangement_ref.key()[:2]):
                    raise TaskConflict('Finance recovery lacks its selected actual current business profile')
                if profile.business_key == current.business_key:
                    return 'waiting'
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile(action_id, code, '2', frozenset({'dependency_change'}), evaluate)
