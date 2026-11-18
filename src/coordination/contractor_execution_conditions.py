"""Resolve original Contractor A07 waits without replaying construction inputs."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts import contractor_execution_objects as execution_objects
from src.actions.contracts.contractor_execution_objects import (
    ContractorExecutionRequestView, ContractorWorkExecutionView, ContractorWorkRecordView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.pricing import decimal_fraction
from src.organization.registry import scope_covers


_CODES = (
    'contractor-execution-query-original-command-before-any-replay',
    'contractor-execution-query-before-reusing-uncertain-inputs',
    'contractor-execution-original-operation-already-recorded',
)


@dataclass(frozen=True)
class ContractorExecutionConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_refs: tuple[Reference, ...]


def contractor_original_execution_profiles(read_current, validate_relation):
    """Register the three exact original A07 dependency waits.

    Current formal reading must include old/current executions, exact original
    requests and actual work records. Independent validation authenticates the
    original query and complete effects. A resolved command permits only a
    fresh existing-execution reconciliation. Failures require explicit review;
    unknown queries remain waiting and never consume construction inputs.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Contractor execution wait requires current reader and independent native history validation')

    def profile(code):
        def evaluate(check):
            source, old_refs = check.source['identity'], check.condition.object_refs
            if (source['action_id'] != 'CONTRACTOR-A07' or source['role'] != 'Contractor' or source['purpose'] != 'action'
                    or check.condition.condition_code != code or check.condition.trigger != 'dependency_change'
                    or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                    or not old_refs or len({(ref.kind, ref.id) for ref in old_refs}) != len(old_refs)
                    or any(ref.kind != 'WorkExecution' for ref in old_refs)):
                raise TaskConflict('Contractor wait changes original task/recipient or execution dependencies')
            selected = read_current(deepcopy(check))
            if (not isinstance(selected, ContractorExecutionConditionReading)
                    or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                    or not isinstance(selected.execution_refs, tuple)
                    or any(not isinstance(ref, Reference) for ref in selected.execution_refs)):
                raise TaskConflict('Contractor wait requires typed current authorized execution sources')
            context, reading, refs = selected.context.model_copy(deep=True), selected.reading, selected.execution_refs
            if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'CONTRACTOR-A07'
                    or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                    or len(refs) != len(old_refs) or len(set(refs)) != len(refs)
                    or {(ref.kind, ref.id) for ref in refs} != {(ref.kind, ref.id) for ref in old_refs}):
                raise TaskConflict('Contractor wait substitutes current run/action/time or original physical execution identities')
            reading.check_method_context(context, 'CONTRACTOR-A07')
            now = context.business_time
            current_refs = {(ref.kind, ref.id): ref for ref in refs}
            originals, currents, requests, records, observed = [], [], {}, {}, {}
            operations, businesses, events, net_work = set(), set(), set(), set()

            def available(row, *, historic=False):
                return (row.available_at.clock_ref == now.clock_ref and row.available_at.offset <= now.offset
                    and row.effective_window.start.clock_ref == now.clock_ref
                    and row.effective_window.end.clock_ref == now.clock_ref
                    and (historic or row.effective_window.contains(now)))

            def evidence(ref, *, historic=False, require_actual=False):
                item = reading.resolve(ref)
                if not isinstance(item, EvidenceRecord) or item.ref != ref:
                    raise TaskConflict('Contractor execution query substitutes exact Evidence source')
                if require_actual and (item.source_kind == 'synthetic' or item.basis_kind != 'observed'):
                    raise TaskConflict('Contractor execution query requires actual observed evidence')
                if item.effective_window is not None:
                    if (item.effective_window.start.clock_ref != now.clock_ref
                            or item.effective_window.end.clock_ref != now.clock_ref
                            or item.effective_window.start.offset > now.offset
                            or not historic and not item.effective_window.contains(now)):
                        return False
                if require_actual:
                    observed[ref.key()] = item.model_dump(mode='json')
                return True

            try:
                for old_ref in old_refs:
                    current_ref = current_refs[(old_ref.kind, old_ref.id)]
                    original, current = reading.resolve(old_ref), reading.resolve(current_ref)
                    if (not isinstance(original, ContractorWorkExecutionView) or not isinstance(current, ContractorWorkExecutionView)
                            or original.ref != old_ref or current.ref != current_ref
                            or current.run_id != source['run_id'] or current.organization_id != source['organization_id']
                            or any(getattr(original, field) != getattr(current, field) for field in (
                                'organization_id', 'run_id', 'task_ref', 'operation_id', 'business_key', 'request_ref', 'request_sha256', 'scope'))
                            or not scope_covers(context.scope, current.scope)
                            or original.status in {'recorded', 'failed', 'not_executed'} and current.status != original.status
                            or original.status == 'recorded' and (
                                current.core_event_id != original.core_event_id or current.recorded_at != original.recorded_at
                                or not {(ref.kind, ref.id) for ref in original.work_record_refs}
                                    <= {(ref.kind, ref.id) for ref in current.work_record_refs})
                            or current.operation_id in operations or current.business_key in businesses):
                        raise TaskConflict('Contractor query changes original request/operation/business/task/scope or repeats an execution')
                    operations.add(current.operation_id); businesses.add(current.business_key)
                    if not available(current):
                        return 'unavailable'
                    if not available(original, historic=True):
                        return 'unavailable'
                    for evidence_ref in original.evidence_refs:
                        if not evidence(evidence_ref, historic=True):
                            return 'unavailable'
                    if original.status == 'recorded':
                        unique_refs(original.work_record_refs); unique_refs(current.work_record_refs)
                        current_work = {ref.key()[:2]: ref for ref in current.work_record_refs}
                        for old_work_ref in original.work_record_refs:
                            new_work_ref = current_work[old_work_ref.key()[:2]]
                            before, after = reading.resolve(old_work_ref), reading.resolve(new_work_ref)
                            if getattr(before, 'ref', None) != old_work_ref or getattr(after, 'ref', None) != new_work_ref:
                                raise TaskConflict('Contractor work history substitutes an exact original/current source')
                            try:
                                execution_objects.validate_contractor_recorded_work_history(original, current, before, after)
                            except ValueError as error:
                                raise TaskConflict('Contractor work query rewrites known engineering history') from error
                            if not available(before, historic=True):
                                return 'unavailable'
                            for evidence_ref in (*before.evidence_refs, before.gross_quantity.basis_ref, before.net_quantity.basis_ref):
                                if not evidence(evidence_ref, historic=True, require_actual=True):
                                    return 'unavailable'
                            records[before.ref.key()] = before.model_dump(mode='json')
                    if current.status == 'submitted_unknown' or current.query_status in {'unknown', 'not_queried'}:
                        return 'waiting'
                    if current.status == 'failed':
                        return 'unavailable'
                    request = reading.resolve(current.request_ref)
                    if (not isinstance(request, ContractorExecutionRequestView) or request.ref != current.request_ref
                            or request.task_ref != current.task_ref or request.operation_id != current.operation_id
                            or request.business_key != current.business_key or request.scope_ref != current.scope
                            or task_digest(request.model_dump(mode='json')) != current.request_sha256):
                        raise TaskConflict('Contractor query substitutes the exact original submitted request content')
                    if not available(request, historic=True):
                        return 'unavailable'
                    for evidence_ref in request.evidence_refs:
                        if not evidence(evidence_ref, historic=True):
                            return 'unavailable'
                    requests[request.ref.key()] = request.model_dump(mode='json')
                    for evidence_ref in current.evidence_refs:
                        if not evidence(evidence_ref, require_actual=True):
                            return 'unavailable'
                    if current.status == 'recorded':
                        if (current.query_status != 'present' or current.core_event_id is None or current.core_event_id in events
                                or current.recorded_at is None or current.recorded_at.clock_ref != now.clock_ref
                                or current.recorded_at.offset > current.available_at.offset
                                or request.available_at.offset > current.recorded_at.offset
                                or len(set(current.work_record_refs)) != len(current.work_record_refs)):
                            raise TaskConflict('Recorded Contractor execution lacks distinct original native event and receipt chronology')
                        events.add(current.core_event_id)
                        for ref in current.work_record_refs:
                            record = reading.resolve(ref)
                            if (not isinstance(record, ContractorWorkRecordView) or record.ref != ref
                                    or record.core_event_id != current.core_event_id
                                    or record.gross_quantity.unit != record.net_quantity.unit
                                    or not scope_covers(current.scope, record.scope)):
                                raise TaskConflict('Contractor work record changes original execution, core event or units')
                            if not available(record, historic=True):
                                return 'unavailable'
                            command = current if record.execution_ref == current.ref else reading.resolve(record.execution_ref)
                            try:
                                execution_objects.validate_contractor_work_record_execution(current, record, command)
                            except ValueError as error:
                                raise TaskConflict('Contractor work query changes the exact original command source') from error
                            if not available(command, historic=True):
                                return 'unavailable'
                            for evidence_ref in command.evidence_refs:
                                if not evidence(evidence_ref, historic=True):
                                    return 'unavailable'
                            gross, net = decimal_fraction(record.gross_quantity.value), decimal_fraction(record.net_quantity.value)
                            if gross < 0 or net < 0 or net > gross:
                                raise TaskConflict('Contractor work record has invalid gross/net quantities')
                            if record.work_kind == 'rework':
                                if record.original_work_record_ref is None or record.original_work_record_ref == record.ref or net != 0:
                                    raise TaskConflict('Contractor rework cannot invent new net completion')
                                prior = reading.resolve(record.original_work_record_ref)
                                if (not isinstance(prior, ContractorWorkRecordView)
                                        or prior.ref != record.original_work_record_ref
                                        or prior.physical_work_key != record.physical_work_key
                                        or prior.available_at.clock_ref != now.clock_ref
                                        or prior.available_at.offset > current.recorded_at.offset):
                                    raise TaskConflict('Contractor rework substitutes original physical work history')
                                if not available(prior, historic=True):
                                    return 'unavailable'
                                for evidence_ref in (*prior.evidence_refs, prior.gross_quantity.basis_ref, prior.net_quantity.basis_ref):
                                    if not evidence(evidence_ref, historic=True, require_actual=True):
                                        return 'unavailable'
                                records[prior.ref.key()] = prior.model_dump(mode='json')
                            elif net > 0:
                                if record.physical_work_key in net_work:
                                    raise TaskConflict('Contractor query counts one physical work slice twice')
                                net_work.add(record.physical_work_key)
                            for evidence_ref in [*record.evidence_refs, record.gross_quantity.basis_ref, record.net_quantity.basis_ref]:
                                if not evidence(evidence_ref, historic=True, require_actual=True):
                                    return 'unavailable'
                            records[ref.key()] = record.model_dump(mode='json')
                    elif (current.status != 'not_executed' or current.query_status not in {'present', 'absent'}
                            or current.core_event_id is not None or current.recorded_at is not None or current.work_record_refs):
                        raise TaskConflict('Unexecuted Contractor command invents work effects or lacks actual absence confirmation')
                    originals.append(original.model_dump(mode='json'))
                    currents.append(current.model_dump(mode='json'))
                if validate_relation(source_identity=deepcopy(source), original_executions=deepcopy(originals),
                        current_executions=deepcopy(currents), requests=deepcopy(list(requests.values())),
                        work_records=deepcopy(list(records.values())), evidence=deepcopy(list(observed.values())),
                        context=context.model_copy(deep=True), reading=reading) is not True:
                    raise TaskConflict('Contractor wait lacks authentic original query and complete work/absence evidence')
                return 'ready'
            finally:
                reading.recheck()

        return ConditionProfile('CONTRACTOR-A07', code, '4', frozenset({'dependency_change'}), evaluate)

    return tuple(profile(code) for code in _CODES)
