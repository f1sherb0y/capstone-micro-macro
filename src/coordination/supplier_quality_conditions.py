"""Resolve original Supplier A07 disposition waits from actual batch history."""
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_quality_objects import (
    SupplierBatchDispositionExecutionView, SupplierBatchLineageLedgerView,
    SupplierQualityBatchView, SupplierQualityProfileView,
)
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.actions.roles.supplier_quality_history import validate_isolation_release_recheck
from src.methods.pricing import decimal_fraction


_CODES = ('query_original_batch_disposition_before_new_effect', 'continue_original_batch_disposition')


@dataclass(frozen=True)
class SupplierQualityConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_refs: tuple[Reference, ...]
    original_action_input: dict
    action_input: dict


def supplier_original_disposition_profiles(read_current, validate_relation):
    """Authenticate original disposition outcomes before a fresh authorized judgment.

    Original inputs come from immutable waiting-task snapshots. The current
    complete physical batch ledger preserves all original execution identities.
    Unknown queries remain waiting. No history is synthesized and no command
    is replayed: a successor uses the independently selected current profile,
    and ordinary A07 inspection, disposition-right and rework gates still run.
    Native validation proves complete query/effect history and that a current
    proposed disposition is a separately authorized decision, not a renamed
    retry of the already recorded original command.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Supplier disposition wait requires actual sources and native query/history validation')

    def profile_for(code):
        def evaluate(check):
            source, old_refs = check.source['identity'], check.condition.object_refs
            if (source['action_id'] != 'SUPPLIER-A07' or source['role'] != 'Supplier' or source['purpose'] != 'action'
                    or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                    or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                    or not old_refs or any(ref.kind != 'BatchDispositionExecution' for ref in old_refs)
                    or len({ref.key()[:2] for ref in old_refs}) != len(old_refs)
                    or code == 'continue_original_batch_disposition' and len(old_refs) != 1):
                raise TaskConflict('Supplier disposition wait replaces original task/recipient or command selection')
            selected = read_current(deepcopy(check))
            if (not isinstance(selected, SupplierQualityConditionReading) or not isinstance(selected.context, ActionContext)
                    or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.execution_refs, tuple)
                    or any(not isinstance(ref, Reference) for ref in selected.execution_refs)
                    or not isinstance(selected.original_action_input, dict) or not isinstance(selected.action_input, dict)):
                raise TaskConflict('Supplier disposition wait requires typed current reading and original saved input')
            context, reading = selected.context.model_copy(deep=True), selected.reading
            try:
                refs = selected.execution_refs
                if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                        or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A07'
                        or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                        or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                        or len(refs) != len(old_refs) or len({ref.key()[:2] for ref in refs}) != len(refs)
                        or {ref.key()[:2] for ref in refs} != {ref.key()[:2] for ref in old_refs}
                        or task_digest(selected.original_action_input) != source['input_sha256']):
                    raise TaskConflict('Supplier disposition wait substitutes original snapshot/commands or current read point')
                reading.check_method_context(context, 'SUPPLIER-A07')
                original_input, current_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
                original_batch = reading.resolve(Reference.model_validate(original_input['batch_ref']))
                batch = reading.resolve(Reference.model_validate(current_input['batch_ref']))
                if (not isinstance(original_batch, SupplierQualityBatchView) or not isinstance(batch, SupplierQualityBatchView)
                        or original_batch.ref.key()[:2] != batch.ref.key()[:2] or batch.organization_id != source['organization_id']
                        or any(getattr(original_batch, field) != getattr(batch, field) for field in (
                            'organization_id', 'owner_id', 'product_ref', 'physical_batch_key', 'scope'))
                        or original_batch.actual_quantity.unit != batch.actual_quantity.unit
                        or current_input.get('scope_ref') != context.scope.model_dump(mode='json')):
                    raise TaskConflict('Supplier disposition recovery changes original physical batch, title, product, scope or units')
                original_profile = reading.resolve(Reference.model_validate(original_input['inspection_profile_ref']))
                profile = reading.resolve(Reference.model_validate(current_input['inspection_profile_ref']))
                if (not isinstance(original_profile, SupplierQualityProfileView) or not isinstance(profile, SupplierQualityProfileView)
                        or original_profile.batch_ref != original_batch.ref or original_profile.organization_id != batch.organization_id
                        or profile.batch_ref != batch.ref or profile.organization_id != batch.organization_id
                        or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
                        or profile.authority_ref not in context.authorization_refs or profile.scope != context.scope):
                    raise TaskConflict('Supplier disposition recovery lacks original demand and current own judgment authority')
                for field in ('requirement_refs', 'evidence_refs', 'known_defect_refs'):
                    before = {Reference.model_validate(ref).key()[:2] for ref in original_input[field]}
                    current = {Reference.model_validate(ref).key()[:2] for ref in current_input[field]}
                    if not before <= current:
                        raise TaskConflict('Supplier disposition recovery hides original requirements, observations or known defects')
                old_ledger, ledger = reading.resolve(original_batch.lineage_ledger_ref), reading.resolve(batch.lineage_ledger_ref)
                if (not isinstance(old_ledger, SupplierBatchLineageLedgerView) or not isinstance(ledger, SupplierBatchLineageLedgerView)
                        or old_ledger.ref.key()[:2] != ledger.ref.key()[:2]
                        or any(row.physical_batch_key != batch.physical_batch_key or row.organization_id != batch.organization_id
                            for row in (old_ledger, ledger))
                        or old_ledger.original_quantity != ledger.original_quantity
                        or not {ref.key() for ref in old_refs} <= {ref.key() for ref in old_ledger.execution_refs}
                        or not {ref.key()[:2] for ref in old_ledger.execution_refs} <= {ref.key()[:2] for ref in ledger.execution_refs}
                        or not {ref.key() for ref in refs} <= {ref.key() for ref in ledger.execution_refs}
                        or len({ref.key()[:2] for ref in ledger.execution_refs}) != len(ledger.execution_refs)):
                    raise TaskConflict('Supplier disposition recovery replaces original complete physical lineage or command history')
                now = context.business_time

                def available(row, *, historic=False):
                    return (row.available_at.clock_ref == now.clock_ref and row.available_at.offset <= now.offset
                        and row.effective_window.start.clock_ref == now.clock_ref
                        and row.effective_window.start.offset <= now.offset
                        and (historic or row.effective_window.contains(now)))

                observed = {}

                def actual(ref, *, at=None, historic=False):
                    row = reading.resolve(ref)
                    if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                        raise TaskConflict('Supplier disposition query requires actual observed physical batch evidence')
                    point = now if at is None else at
                    if point.clock_ref != now.clock_ref or point.offset > now.offset:
                        return False
                    if row.effective_window is not None:
                        if (row.effective_window.start.clock_ref != now.clock_ref
                                or row.effective_window.start.offset > now.offset
                                or (at is not None or not historic) and not row.effective_window.contains(point)):
                            return False
                    observed[ref.key()] = row.model_dump(mode='json')
                    return True

                def amount(measured):
                    if measured.unit != batch.actual_quantity.unit or decimal_fraction(measured.value) < 0:
                        raise TaskConflict('Supplier disposition ledger changes physical quantity units or uses negative stock')
                    return decimal_fraction(measured.value)

                if (ledger.coverage != 'complete' or ledger.as_of != now or batch.as_of != now
                        or not all(available(row) for row in (batch, profile, ledger))):
                    return 'unavailable'
                for row in (batch, profile, ledger):
                    for ref in row.evidence_refs:
                        if not actual(ref):
                            return 'unavailable'
                initial, remaining, scrapped, outflow, isolated = [amount(getattr(ledger, field)) for field in (
                    'original_quantity', 'actual_remaining', 'scrapped_quantity', 'other_outflow', 'isolated_quantity')]
                if initial - scrapped - outflow != remaining or remaining != amount(batch.actual_quantity) or isolated > remaining:
                    raise TaskConflict('Supplier disposition query restores consumed/scrapped stock or changes actual remaining batch')
                old_rows, rows, rechecks = [], [], {}
                released_rechecks = {}
                current_by_physical = {ref.key()[:2]: ref for ref in ledger.execution_refs}
                for old_ref in old_ledger.execution_refs:
                    original = reading.resolve(old_ref)
                    current = reading.resolve(current_by_physical[old_ref.key()[:2]])
                    if (not isinstance(original, SupplierBatchDispositionExecutionView) or not isinstance(current, SupplierBatchDispositionExecutionView)
                            or original.ref != old_ref or any(getattr(original, field) != getattr(current, field) for field in (
                                'physical_batch_key', 'organization_id', 'operation_id', 'business_key', 'choice', 'quantity', 'scope'))
                            or original.status != 'submitted_unknown' and current.status != original.status
                            or original.status == 'recorded' and any(getattr(original, field) != getattr(current, field) for field in (
                                'core_event_id', 'isolated_quantity_decrease', 'release_basis_ref'))):
                        raise TaskConflict('Supplier disposition query replaces an original command, quantity or known effect')
                    if old_ref.key() in {ref.key() for ref in old_refs}:
                        if (code == 'continue_original_batch_disposition' and (
                                original.choice != original_profile.choice or original.quantity != original_profile.quantity
                                or original.business_key != original_profile.business_key and original.operation_id != source['request_id'])):
                            raise TaskConflict('Supplier continue wait is unrelated to its original submitted disposition')
                        if (code == 'query_original_batch_disposition_before_new_effect'
                                and original.status != 'submitted_unknown' and original.query_status not in {'unknown', 'not_queried'}):
                            raise TaskConflict('Supplier original query wait does not select an originally uncertain command')
                    old_rows.append(original.model_dump(mode='json'))
                commands, businesses, events = set(), set(), set()
                total_scrap, total_isolation = Fraction(), Fraction()
                for ref in ledger.execution_refs:
                    row = reading.resolve(ref)
                    if (not isinstance(row, SupplierBatchDispositionExecutionView) or row.ref != ref
                            or row.physical_batch_key != batch.physical_batch_key or row.organization_id != batch.organization_id
                            or row.operation_id in commands or row.business_key in businesses):
                        raise TaskConflict('Supplier disposition query repeats or substitutes an original command or physical batch')
                    commands.add(row.operation_id); businesses.add(row.business_key)
                    if not available(row,historic=True):
                        return 'unavailable'
                    if row.status == 'submitted_unknown' or row.query_status in {'unknown', 'not_queried'}:
                        return 'waiting'
                    q, decrease = amount(row.quantity), amount(row.isolated_quantity_decrease)
                    if (q <= 0 or decrease > q or row.choice == 'isolate' and decrease != 0
                            or row.choice == 'release_isolation' and decrease != q):
                        raise TaskConflict('Supplier disposition query changes original physical isolation/scrap quantity split')
                    for evidence_ref in [*row.evidence_refs, row.quantity.basis_ref, row.isolated_quantity_decrease.basis_ref]:
                        if not actual(evidence_ref,historic=True):
                            return 'unavailable'
                    if row.status == 'recorded':
                        if row.query_status != 'present' or row.core_event_id is None or row.core_event_id in events:
                            raise TaskConflict('Recorded batch disposition lacks distinct actual native event')
                        events.add(row.core_event_id)
                        if row.choice == 'scrap':
                            total_scrap += q; total_isolation -= decrease
                        elif row.choice == 'isolate':
                            total_isolation += q
                        else:
                            if row.release_basis_ref is None:
                                raise TaskConflict('Isolation release has no original passed scoped recheck')
                            try:
                                recheck, recheck_sources = validate_isolation_release_recheck(row, batch,
                                    now=now, resolve=reading.resolve, amount=amount, released=released_rechecks)
                            except ValueError as exc:
                                raise TaskConflict('Isolation release lacks original method/authority or repeats recheck coverage') from exc
                            for original_source in recheck_sources:
                                if isinstance(original_source, EvidenceRecord) and not actual(original_source.ref,at=recheck.authored_at):
                                    return 'unavailable'
                            rechecks[recheck.ref.key()] = recheck.model_dump(mode='json')
                            total_isolation -= q
                    elif row.core_event_id is not None or decrease != 0:
                        raise TaskConflict('Rejected or failed batch disposition cannot imply actual physical effects')
                    rows.append(row.model_dump(mode='json'))
                if total_scrap != scrapped or total_isolation != isolated:
                    raise TaskConflict('Supplier complete disposition history differs from actual current lineage ledger')
                if context.operation_id in commands or profile.choice in {'isolate', 'scrap', 'rework'} and profile.business_key in businesses:
                    raise TaskConflict('Supplier current disposition must use an independently authorized fresh judgment, never replay a saved command')
                for field in ('original_quantity', 'actual_remaining', 'scrapped_quantity', 'other_outflow', 'isolated_quantity'):
                    if not actual(getattr(ledger, field).basis_ref):
                        return 'unavailable'
                if not actual(batch.actual_quantity.basis_ref):
                    return 'unavailable'
                if validate_relation(source_identity=deepcopy(source), original_action_input=original_input, action_input=current_input,
                        original_batch=original_batch.model_copy(deep=True), batch=batch.model_copy(deep=True),
                        original_profile=original_profile.model_copy(deep=True), profile=profile.model_copy(deep=True),
                        original_ledger=old_ledger.model_copy(deep=True), ledger=ledger.model_copy(deep=True),
                        original_executions=deepcopy(old_rows), current_executions=deepcopy(rows),
                        rechecks=deepcopy(list(rechecks.values())), evidence=deepcopy(list(observed.values())),
                        context=context.model_copy(deep=True), reading=reading) is not True:
                    raise TaskConflict('Supplier disposition wait lacks native complete query/lineage and independent current judgment validation')
                return 'ready'
            finally:
                reading.recheck()

        return ConditionProfile('SUPPLIER-A07', code, '3', frozenset({'dependency_change'}), evaluate)

    return tuple(profile_for(code) for code in _CODES)
