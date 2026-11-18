"""Read original A03 bid command results through actual authorized amendment sources."""
from copy import deepcopy
from dataclasses import dataclass

from integration.contractor_amendment_actions import ContractorAmendmentActionAssembler
from integration.contractor_formation_command_reader import (
    ContractorFormationCommandReader, ContractorFormationRecoveryBindings, ContractorFormationRecoverySettings,
    _build_protected_bid_command_dispatcher,
)
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference
from src.actions.contracts.contractor_amendment_objects import ContractorAmendmentRoundView, ContractorAmendmentRuleView
from src.actions.contracts.contractor_bid_objects import ContractorBidPackageView
from src.coordination.contractor_amendment_conditions import (
    ContractorAmendmentCommandConditionReading, _read_original_amendment_rule_bid,
    _read_original_expired_bid,
    _read_original_late_answer_bid,
)
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class ContractorAmendmentCommandCurrentSelection:
    request: RoleContractInvocation
    execution_ref: Reference


class ContractorAmendmentRecoverySettings(ContractorFormationRecoverySettings):
    """Explicit original commands and versions; JSON lists freeze inside the reader."""


@dataclass(frozen=True)
class ContractorAmendmentRecoveryBindings(ContractorFormationRecoveryBindings):
    """Actual A03 selector, guard, native query and successor validation callbacks."""


class ContractorAmendmentCommandReader(ContractorFormationCommandReader):
    """Use the original A03 assembler without running amendment or submission.

    The shared read boundary pins original source/model components, complete
    current input/context and old/current bid and command identity. Amendment
    selection additionally preserves the explicit prior/current package and
    round relationships. Choice, release rights, resources, fees and final
    amended submission remain original processor and transport checks.
    """
    ACTION_ID = 'CONTRACTOR-A03'
    ASSEMBLER_TYPE = ContractorAmendmentActionAssembler
    SELECTION_TYPE = ContractorAmendmentCommandCurrentSelection
    SCHEMA_VERSION = 'contractor-amendment-command-reader.v1'

    def _condition_codes(self):
        return super()._condition_codes() | {'original_procurement_disposition_required', 'original_procurement_disposition_change',
            'original_late_or_expired_submission_disposition', 'original_expired_bid_disposition', 'original_late_answer_disposition'}

    def _valid_wait_refs(self, check):
        if check.condition.condition_code == 'original_late_answer_disposition':
            refs = check.condition.object_refs
            return len(refs) == 2 and refs[0].kind == 'ClarificationRequest' and refs[1].kind == 'TenderAmendmentRule'
        if check.condition.condition_code == 'original_expired_bid_disposition':
            refs = check.condition.object_refs
            return len(refs) == 2 and refs[0].kind == 'Bid' and refs[1].kind == 'TimeWindow'
        if check.condition.condition_code == 'original_procurement_disposition_change':
            refs = check.condition.object_refs
            return len(refs) == 2 and refs[0].kind == 'TenderAmendmentRule' and refs[1].kind == 'Evidence'
        if check.condition.condition_code == 'original_late_or_expired_submission_disposition':
            refs = check.condition.object_refs
            return len(refs) == 2 and refs[0].kind == 'TenderAmendmentRule' and refs[1].kind == 'TimeWindow'
        return super()._valid_wait_refs(check)

    def _original_bid_refs(self, check, reading):
        if check.condition.condition_code == 'original_late_answer_disposition':
            _, _, _, bid = _read_original_late_answer_bid(reading, check.condition.object_refs)
            return (bid.submission_ref, bid.ref)
        if check.condition.condition_code == 'original_expired_bid_disposition':
            bid, _ = _read_original_expired_bid(reading, check.condition.object_refs)
            return (bid.submission_ref, bid.ref)
        if check.condition.condition_code in {'original_procurement_disposition_change', 'original_late_or_expired_submission_disposition'}:
            _, _, bid = _read_original_amendment_rule_bid(reading, check.condition.object_refs,
                window_wait=check.condition.condition_code == 'original_late_or_expired_submission_disposition')
            return (bid.submission_ref, bid.ref)
        return super()._original_bid_refs(check, reading)

    def _matches_original_command(self, condition, original):
        if condition.condition_code == 'original_procurement_disposition_required':
            return original.command_id in self.command_ids and original.status in {'rejected', 'not_submitted'}
        if condition.condition_code in {'original_procurement_disposition_change', 'original_late_or_expired_submission_disposition',
                'original_expired_bid_disposition', 'original_late_answer_disposition'}:
            return original.command_id in self.command_ids
        return super()._matches_original_command(condition, original)

    def _current_bid(self, prepared, current_execution):
        action_input, reading = prepared.action_input, prepared.reading
        package = reading.resolve(action_input.package_ref)
        tender_round = reading.resolve(action_input.round_ref)
        rule = reading.resolve(action_input.amendment_rule_ref)
        if (not isinstance(package, ContractorBidPackageView) or not isinstance(tender_round, ContractorAmendmentRoundView)
                or not isinstance(rule, ContractorAmendmentRuleView) or rule.organization_id != reading.organization_id
                or rule.prior_package_ref.key() != current_execution.package_ref.key()
                or rule.prior_round_ref.key() != current_execution.round_ref.key()
                or rule.current_package_ref.key() != package.ref.key() or rule.current_round_ref.key() != tender_round.ref.key()
                or package.round_ref.key() != tender_round.ref.key() or tender_round.package_ref.key() != package.ref.key()
                or tender_round.current_package_ref.key() != package.ref.key()
                or tender_round.amendment_rule_ref.key() != rule.ref.key()):
            raise TaskConflict('Amendment command reader substitutes original command or package/round replacement rule')
        return reading.resolve(action_input.bid_ref), action_input.bid_ref

    def _condition_reading(self, prepared, ref, bid_ref):
        return ContractorAmendmentCommandConditionReading(prepared.context, prepared.reading, ref, bid_ref,
            deepcopy(prepared.action_input.model_dump(mode='json')), prepared.action_input.amendment_rule_ref.model_copy(deep=True))


def build_assembled_contractor_amendment_command_dispatcher(*, inbox, store, assembler, command_ids,
        select_current, read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold the same source/authority/inbox/journal guard throughout A03 wakeup."""
    from integration.task_continuation import build_contractor_amendment_command_dispatcher

    reader = ContractorAmendmentCommandReader(assembler=assembler, command_ids=command_ids, select_current=select_current)
    return _build_protected_bid_command_dispatcher(inbox=inbox, store=store, reader=reader,
        build_dispatcher=build_contractor_amendment_command_dispatcher, read_guard=read_guard,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare, revalidate=revalidate)
