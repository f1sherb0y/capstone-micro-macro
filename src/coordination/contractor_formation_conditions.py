"""Resolve exact original Contractor A04 bid command waits before fresh judgment."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.contractor_amendment_objects import (
    ContractorAmendmentBidView, ContractorAmendmentSubmissionView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, _text


@dataclass(frozen=True)
class ContractorFormationCommandConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_ref: Reference
    bid_ref: Reference


def contractor_original_formation_command_profile(command_id, read_current, validate_relation):
    """Register one explicit command, preserving the processor's dynamic wait code.

    The application holds source/authority/journal guards. A native validator
    authenticates the original bid submission result; persisted feedback is
    only a scheduling hint. Ready permits fresh A04 judgment, whose original
    accepted/failed/rejected checks and independent agreement gates still run.
    No command, contract, acceptance, reservation or payment is issued here.
    """
    return _contractor_original_bid_command_profile(command_id, read_current, validate_relation,
        action_id='CONTRACTOR-A04', reading_type=ContractorFormationCommandConditionReading)


def _contractor_original_bid_command_profile(command_id, read_current, validate_relation, *, action_id, reading_type):
    """Share exact original bid-result checks while keeping A03/A04 judgment separate."""
    if action_id not in {'CONTRACTOR-A03', 'CONTRACTOR-A04'}:
        raise ValueError('Original bid command query supports only amendment or formation waits')
    _text(command_id)
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Bid command command wait requires actual sources and independent native query validation')
    code = 'query_original_command:' + command_id

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != action_id or source['role'] != 'Contractor'
                or source['purpose'] != 'action' or check.condition.condition_code != code
                or check.condition.trigger != 'event' or check.signal.run_id != source['run_id']
                or check.signal.organization_id != source['organization_id'] or len(old_refs) != 2
                or old_refs[0].kind != 'SubmissionExecution' or old_refs[1].kind != 'Bid'):
            raise TaskConflict('Bid command command wait changes original action, recipient, command or selected bid')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, reading_type)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.execution_ref, Reference) or not isinstance(selected.bid_ref, Reference)):
            raise TaskConflict('Bid command command wait requires typed current authorized submission sources')
        context, reading, ref = (selected.context.model_copy(deep=True), selected.reading,
            selected.execution_ref.model_copy(deep=True))
        old_ref, bid_ref = old_refs
        current_bid_ref = selected.bid_ref.model_copy(deep=True)
        now = context.business_time
        if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                or context.contract_ref.id != action_id or context.execution_mode != 'llm'
                or reading._resolver.source_mode != 'formal' or now != check.signal.business_time
                or context.operation_id == source['request_id'] or (ref.kind, ref.id) != (old_ref.kind, old_ref.id)
                or (current_bid_ref.kind, current_bid_ref.id) != (bid_ref.kind, bid_ref.id)
                or not {old_ref.key(), bid_ref.key(), ref.key(), current_bid_ref.key()}
                    <= {item.key() for item in context.visible_refs}):
            raise TaskConflict('Bid command query substitutes current formal context or original bid execution')
        reading.check_method_context(context, action_id)
        try:
            bid = reading.resolve(bid_ref)
            current_bid = reading.resolve(current_bid_ref)
            original, current = reading.resolve(old_ref), reading.resolve(ref)
            if (not isinstance(bid, ContractorAmendmentBidView) or bid.ref.key() != bid_ref.key()
                    or bid.organization_id != source['organization_id'] or bid.submission_ref.key() != old_ref.key()
                    or not isinstance(current_bid, ContractorAmendmentBidView) or current_bid.ref.key() != current_bid_ref.key()
                    or current_bid.submission_ref.key() != ref.key()
                    or any(getattr(bid, field) != getattr(current_bid, field) for field in (
                        'organization_id', 'round_ref', 'draft', 'reservation_refs', 'scope'))
                    or not isinstance(original, ContractorAmendmentSubmissionView)
                    or not isinstance(current, ContractorAmendmentSubmissionView)
                    or original.ref.key() != old_ref.key() or current.ref.key() != ref.key()
                    or current.organization_id != source['organization_id'] or current.command_id != command_id
                    or original.bid_ref.key() != bid.ref.key() or current.bid_ref.key() != current_bid.ref.key()
                    or current.package_ref.key() != bid.draft.package_ref.key()
                    or current.round_ref.key() != bid.round_ref.key()
                    or any(getattr(original, field) != getattr(current, field) for field in (
                        'organization_id', 'package_ref', 'round_ref', 'command_id', 'scope'))
                    or original.status in {'accepted', 'rejected', 'failed', 'not_submitted'}
                        and current.status != original.status):
                raise TaskConflict('Bid command query changes original command, exact selected bid/package/round or known outcome')
            if (current.available_at.clock_ref != now.clock_ref or current.available_at.offset > now.offset
                    or not current.effective_window.contains(now)):
                return 'unavailable'
            if current.status in {'unknown', 'pending'}:
                return 'waiting'
            observations = {}
            for evidence_ref in [current.result_basis_ref, *current.evidence_refs]:
                evidence = reading.resolve(evidence_ref)
                if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic'
                        or evidence.basis_kind != 'observed'):
                    raise TaskConflict('Bid command command result requires actual observed native query evidence')
                if evidence.effective_window is not None and not evidence.effective_window.contains(now):
                    return 'unavailable'
                observations[evidence.ref.key()] = evidence.model_dump(mode='json')
            reading.recheck()
            if validate_relation(source_identity=deepcopy(source), original_bid=bid.model_dump(mode='json'),
                    current_bid=current_bid.model_dump(mode='json'),
                    original_execution=original.model_dump(mode='json'), current_execution=current.model_dump(mode='json'),
                    evidence=deepcopy(list(observations.values())), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Bid command wait lacks authentic complete original native command query coverage')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile(action_id, code, '1', frozenset({'event'}), evaluate)
