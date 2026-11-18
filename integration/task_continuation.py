"""Replay a recipient's persisted feedback through explicit resume projections."""
from copy import deepcopy

from src.coordination.continuations import ResumeSignal
from src.coordination.tasks import TaskConflict, task_digest


def observation_signal_matches(row, projected, *, expected=None):
    """Match the original recipient event and complete JSON signal content."""
    if projected is None:
        return False
    signal = ResumeSignal.model_validate(projected)
    if (signal.run_id != row['run_id'] or signal.organization_id != row['organization_id']
            or signal.event_id != row['event_id']
            or task_digest(signal.payload) != task_digest(row['payload'])):
        return False
    return (expected is None or task_digest(signal.model_dump(mode='json'))
        == task_digest(ResumeSignal.model_validate(expected).model_dump(mode='json')))


class ObservationContinuationDispatcher:
    def __init__(self, *, inbox, journal, project_signal, prepare, revalidate, action_ids=None):
        if (inbox.run_id != journal.store.run_id
                or inbox.organization_ids != journal.store.organization_ids):
            raise TaskConflict("Observation and continuation stores must share one run and recipient set")
        if not all(callable(callback) for callback in (project_signal, prepare, revalidate)):
            raise ValueError("Explicit signal projection, preparation and current validation are required")
        self.inbox, self.journal = inbox, journal
        self.project_signal, self.prepare, self.revalidate = project_signal, prepare, revalidate
        self.action_ids = None if action_ids is None else frozenset(action_ids)

    def __call__(self, *, run_id, organization_id):
        links = []
        # Always scan persisted recipient feedback, including duplicate delivery.
        # A crash after inbox persistence but before wakeup loses no scheduling
        # hint. The journal deduplicates stable events and successor links.
        for row in self.inbox.for_organization(run_id=run_id, organization_id=organization_id):
            signal = self.project_signal(deepcopy(row))
            if signal is None:
                continue
            signal = ResumeSignal.model_validate(signal)
            if not observation_signal_matches(row, signal):
                raise TaskConflict("Resume projection cannot change feedback identity, recipient or payload")
            selected = {} if self.action_ids is None else {'action_ids': self.action_ids}
            links.extend(self.journal.wake(signal, prepare=self.prepare, revalidate=self.revalidate, **selected))
        return links


def build_commercial_continuation_dispatcher(*, inbox, store, read_current,
        project_signal, prepare, revalidate, extra_profiles=(), action_ids=None, validate_relation=None):
    """Wire explicit commercial A12 waits to durable recipient feedback.

    Host callbacks provide actual authorized projections and fresh successor
    invocations. Other waits require their own explicitly supplied profiles;
    this factory makes no claim that the macro supports query or new actions.
    """
    from src.coordination.commercial_conditions import commercial_continuation_profiles
    from src.coordination.continuations import ConditionRegistry, ContinuationJournal

    registry = ConditionRegistry([*commercial_continuation_profiles(read_current, validate_relation), *extra_profiles])
    journal = ContinuationJournal(store, registry)
    return ObservationContinuationDispatcher(inbox=inbox, journal=journal,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, action_ids=action_ids)


def build_owner_continuation_execution_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    """Wake the original A13 unknown-execution wait from actual query evidence.

    Application callbacks hold current authority and native source boundaries,
    preserve original duties and prepare/revalidate a distinct Owner invocation.
    This wiring only queues that invocation; it never executes a transition.
    """
    from src.coordination.owner_continuation_conditions import owner_original_continuation_execution_profile
    from src.coordination.continuations import ConditionRegistry, ContinuationJournal

    profiles = [owner_original_continuation_execution_profile(read_current, validate_relation), *extra_profiles]
    journal = ContinuationJournal(store, ConditionRegistry(profiles))
    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate, action_ids={'OWN-A13'})


def build_owner_asset_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    """Wake original A14 query waits without inventing cash or asset effects.

    The application holds actual source/authority/journal guards and independently
    prepares and validates a fresh invocation preserving original obligations.
    """
    from src.coordination.owner_asset_conditions import owner_original_asset_execution_profile
    from src.coordination.continuations import ConditionRegistry, ContinuationJournal

    profiles = [owner_original_asset_execution_profile(read_current, validate_relation), *extra_profiles]
    journal = ContinuationJournal(store, ConditionRegistry(profiles))
    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate, action_ids={'OWN-A14'})


def build_owner_operating_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    """Wake A15 original queries without changing policy, budgets or commitments.

    The application holds source/authority/journal guards and independently
    prepares/revalidates fresh work with original applied observations retained.
    """
    from src.coordination.owner_operating_conditions import owner_original_operating_execution_profile
    from src.coordination.continuations import ConditionRegistry, ContinuationJournal

    profiles = [owner_original_operating_execution_profile(read_current, validate_relation), *extra_profiles]
    journal = ContinuationJournal(store, ConditionRegistry(profiles))
    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate, action_ids={'OWN-A15'})


def build_architect_submission_receipt_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    """Resolve original A07 receipt waits under actual source/authority guards.

    Application preparation/revalidation preserves the exact original command,
    version work and fees. This queues new judgment only and never resubmits.
    """
    from src.coordination.architect_submission_conditions import architect_original_submission_receipt_profile
    from src.coordination.continuations import ConditionRegistry, ContinuationJournal

    profiles = [architect_original_submission_receipt_profile(read_current, validate_relation), *extra_profiles]
    journal = ContinuationJournal(store, ConditionRegistry(profiles))
    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate, action_ids={'ARCHITECT-A07'})


def build_engineer_submission_receipt_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    """Resolve original Engineer A07 receipts without bypassing signing/release gates.

    The application holds actual source/authority/journal guards and independently
    prepares/revalidates fresh judgment, preserving original version work and fees.
    """
    from src.coordination.engineer_submission_conditions import engineer_original_submission_receipt_profile
    from src.coordination.continuations import ConditionRegistry, ContinuationJournal

    profiles = [engineer_original_submission_receipt_profile(read_current, validate_relation), *extra_profiles]
    journal = ContinuationJournal(store, ConditionRegistry(profiles))
    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate, action_ids={'ENGINEER-A07'})


def build_bank_resolution_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    """Wake A10 original queries without debt release or repeated cash execution.

    The application holds current source/authority/journal guards and independently
    prepares/revalidates a distinct invocation with original obligations intact.
    """
    from src.coordination.bank_resolution_conditions import bank_original_resolution_execution_profile
    from src.coordination.continuations import ConditionRegistry, ContinuationJournal

    profiles = [bank_original_resolution_execution_profile(read_current, validate_relation), *extra_profiles]
    journal = ContinuationJournal(store, ConditionRegistry(profiles))
    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate, action_ids={'BANK-A10'})


def build_bank_closeout_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    """Wake original A11 queries without closing commitments or clearing debt.

    The application holds actual current source/authority/journal guards and
    prepares/revalidates a fresh invocation with all outstanding duties intact.
    """
    from src.coordination.bank_closeout_conditions import bank_original_closeout_execution_profile
    from src.coordination.continuations import ConditionRegistry, ContinuationJournal

    profiles = [bank_original_closeout_execution_profile(read_current, validate_relation), *extra_profiles]
    journal = ContinuationJournal(store, ConditionRegistry(profiles))
    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate, action_ids={'BANK-A11'})


def build_bank_learning_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    """Wake original BANK-A12 query waits without repeating learning effects.

    The application holds current source/authority/journal guards and supplies
    complete query sources plus independently prepared, revalidated successors.
    """
    from src.coordination.bank_learning_conditions import bank_original_learning_execution_profile
    from src.coordination.continuations import ConditionRegistry, ContinuationJournal

    profiles = [bank_original_learning_execution_profile(read_current, validate_relation), *extra_profiles]
    journal = ContinuationJournal(store, ConditionRegistry(profiles))
    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate, action_ids={'BANK-A12'})


def build_bank_execution_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate, extra_profiles=()):
    """Wire the original BANK-A07 prior-command wait to current native query evidence.

    Native events remain hints. The application supplies authorized original
    and current executions and independently authenticates full query history.
    prepare/revalidate must assemble a fresh existing-execution decision rather
    than replaying an old initiation. No transport or action executes here.
    """
    from src.coordination.bank_execution_conditions import bank_original_payment_command_profile
    from src.coordination.continuations import ConditionRegistry, ContinuationJournal

    if not callable(prepare):
        raise ValueError('Bank continuation requires an independent current preparation callback')
    registry = ConditionRegistry([bank_original_payment_command_profile(read_current, validate_relation), *extra_profiles])
    journal = ContinuationJournal(store, registry)

    def prepare_existing(source, signal):
        from src.coordination.continuations import ContinuationPreparation
        prepared = prepare(deepcopy(source), signal.model_copy(deep=True))
        if (not isinstance(prepared, ContinuationPreparation)
                or prepared.next_input.get('operation_context', {}).get('kind') != 'existing'):
            raise TaskConflict('Bank original-command continuation requires fresh existing-execution reconciliation, never initiation')
        from src.actions.contracts.common import Reference
        original = {Reference.model_validate(ref).key()[:2] for condition in source['conditions']
            if condition['condition_code'] == 'query_original_payment_command_before_new_execution'
            for ref in condition['object_refs']}
        refs = [Reference.model_validate(ref) for ref in prepared.next_input['operation_context'].get('execution_refs', [])]
        if original and (len(refs) != len(original) or {(ref.kind, ref.id) for ref in refs} != original):
            raise TaskConflict('Bank continuation must preserve all original command identities in current execution versions')
        return prepared

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare_existing, revalidate=revalidate, action_ids={'BANK-A07'})


def build_bank_funding_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Wire the original cash-shortfall wait without releasing holds or dispatching money."""
    from src.actions.contracts.common import Reference
    from src.coordination.bank_funding_conditions import bank_currency_path_cash_profile
    from src.coordination.continuations import ConditionRegistry, ContinuationJournal, ContinuationPreparation

    if not callable(prepare):
        raise ValueError('Bank cash continuation requires independent current preparation')
    journal = ContinuationJournal(store, ConditionRegistry([bank_currency_path_cash_profile(read_current, validate_relation)]))

    def prepare_current(source, signal):
        prepared = prepare(deepcopy(source), signal.model_copy(deep=True))
        if not isinstance(prepared, ContinuationPreparation):
            raise TaskConflict('Bank cash continuation requires a validated fresh invocation')
        operation = prepared.next_input.get('operation_context', {})
        if operation.get('kind') != 'initiate' or operation.get('prior_execution_refs') or prepared.next_input.get('receipt_refs'):
            raise TaskConflict('Bank cash continuation cannot replay an already submitted or uncertain execution')
        original = {Reference.model_validate(ref).key()[:2] for condition in source['conditions']
            if condition['condition_code'] == 'actual_same_currency_path_cash_after_original_reservations_available'
            for ref in condition['object_refs']}
        refs = [Reference.model_validate(operation[field]) for field in ('funding_account_ref', 'path_ref')]
        if len(original) != 2 or {(ref.kind, ref.id) for ref in refs} != original:
            raise TaskConflict('Bank cash continuation substitutes the original account or funding path')
        return prepared

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare_current, revalidate=revalidate, action_ids={'BANK-A07'})


def build_contractor_formation_command_dispatcher(*, inbox, store, command_ids, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Register explicit A04 command IDs and preserve their selected bids on wake."""
    from src.actions.contracts.common import ActionContext, Reference, ResumeCondition
    from src.actions.contracts.contractor_amendment_objects import ContractorAmendmentSubmissionView
    from src.actions.contracts.references import ActionReadView
    from src.actions.contracts.contractor_formation_objects import (
        ContractorFormationOfferView, ContractorFormationTermsView,
    )
    from src.coordination.contractor_formation_conditions import (
        ContractorFormationCommandConditionReading, contractor_original_formation_command_profile,
    )
    from src.coordination.continuations import (
        ConditionCheck, ConditionRegistry, ContinuationJournal, ContinuationPreparation,
    )

    if (not isinstance(command_ids, (tuple, list)) or not command_ids
            or not all(callable(callback) for callback in (read_current, validate_relation, project_signal, prepare, revalidate))):
        raise ValueError('Formation recovery requires explicit original commands and actual source/preparation validators')
    command_ids = tuple(command_ids)
    profiles = tuple(contractor_original_formation_command_profile(command_id, read_current, validate_relation)
        for command_id in command_ids)
    codes = frozenset(profile.condition_code for profile in profiles)
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_selected_bid(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in codes]
        if len(conditions) != 1 or not isinstance(preparation, ContinuationPreparation):
            raise TaskConflict('Formation successor requires one original selected bid command and validated invocation')
        selected = read_current(ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True)))
        if (not isinstance(selected, ContractorFormationCommandConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.execution_ref, Reference) or not isinstance(selected.bid_ref, Reference)):
            raise TaskConflict('Formation successor lacks its current authorized command reading')
        try:
            original_ref, bid_ref = conditions[0].object_refs
            execution = selected.reading.resolve(selected.execution_ref)
            offer_ref = Reference.model_validate(preparation.next_input.get('offer_ref'))
            terms_ref = Reference.model_validate(preparation.next_input.get('terms_ref'))
            offer, terms = selected.reading.resolve(offer_ref), selected.reading.resolve(terms_ref)
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or selected.context.run_id != source['identity']['run_id']
                    or selected.context.contract_ref.id != 'CONTRACTOR-A04'
                    or selected.context.execution_mode != 'llm'
                    or selected.context.business_time != signal.business_time
                    or selected.context.operation_id == source['identity']['request_id']
                    or selected.reading._resolver.source_mode != 'formal'
                    or selected.reading.organization_id != source['identity']['organization_id']
                    or (selected.execution_ref.kind, selected.execution_ref.id) != (original_ref.kind, original_ref.id)
                    or not isinstance(execution, ContractorAmendmentSubmissionView)
                    or (selected.bid_ref.kind, selected.bid_ref.id) != (bid_ref.kind, bid_ref.id)
                    or execution.bid_ref.key() != selected.bid_ref.key()
                    or execution.command_id not in tuple(command_ids)
                    or conditions[0].condition_code != 'query_original_command:' + execution.command_id
                    or not isinstance(offer, ContractorFormationOfferView) or not isinstance(terms, ContractorFormationTermsView)
                    or offer.bid_ref.key() != selected.bid_ref.key() or terms.bid_ref.key() != selected.bid_ref.key()
                    or offer.package_ref.key() != execution.package_ref.key() or terms.package_ref.key() != execution.package_ref.key()
                    or offer.round_ref.key() != execution.round_ref.key() or terms.round_ref.key() != execution.round_ref.key()
                    or offer.terms_ref.key() != terms_ref.key() or terms.offer_ref.key() != offer_ref.key()):
                raise TaskConflict('Formation successor substitutes another bid, package, round, command or current invocation')
            selected.reading.check_method_context(selected.context, 'CONTRACTOR-A04')
            selected.reading.recheck()
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_selected_bid, action_ids={'CONTRACTOR-A04'})


def build_contractor_amendment_command_dispatcher(*, inbox, store, command_ids, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Wire exact A03 commands to fresh judgment under the original amendment rule."""
    from src.actions.contracts.common import ActionContext, Reference, ResumeCondition
    from src.actions.contracts.contractor_amendment_objects import (
        ContractorAmendmentRoundView, ContractorAmendmentRuleView, ContractorAmendmentSubmissionView,
    )
    from src.actions.contracts.contractor_bid_objects import ContractorBidPackageView
    from src.actions.contracts.references import ActionReadView
    from src.coordination.contractor_amendment_conditions import (
        ContractorAmendmentCommandConditionReading, contractor_original_amendment_command_profile,
        contractor_original_amendment_disposition_profile,
        contractor_original_amendment_rule_disposition_profile, _read_original_amendment_rule_bid,
        contractor_original_amendment_window_profile,
        contractor_original_expired_bid_profile, _read_original_expired_bid,
        contractor_original_late_answer_profile, _read_original_late_answer_bid,
    )
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal, ContinuationPreparation

    if (not isinstance(command_ids, (tuple, list)) or not command_ids
            or not all(callable(callback) for callback in (read_current, validate_relation, project_signal, prepare, revalidate))):
        raise ValueError('Amendment recovery requires explicit original commands and actual source/preparation validators')
    command_ids = tuple(command_ids)
    profiles = tuple(contractor_original_amendment_command_profile(command, read_current, validate_relation)
        for command in command_ids) + (
            contractor_original_amendment_disposition_profile(read_current, validate_relation),
            contractor_original_amendment_rule_disposition_profile(read_current, validate_relation),
            contractor_original_amendment_window_profile(read_current, validate_relation),
            contractor_original_expired_bid_profile(read_current, validate_relation),
            contractor_original_late_answer_profile(read_current, validate_relation))
    codes = frozenset(profile.condition_code for profile in profiles)
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_amendment(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions'] if raw['condition_code'] in codes]
        if len(conditions) != 1 or not isinstance(preparation, ContinuationPreparation):
            raise TaskConflict('Amendment successor requires one original bid command and validated invocation')
        selected = read_current(ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True)))
        if (not isinstance(selected, ContractorAmendmentCommandConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.execution_ref, Reference) or not isinstance(selected.bid_ref, Reference)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Amendment successor lacks its current authorized invocation and command reading')
        try:
            context, reading = selected.context, selected.reading
            if conditions[0].condition_code == 'original_late_answer_disposition':
                _, _, _, bid = _read_original_late_answer_bid(reading, conditions[0].object_refs)
                original_ref, bid_ref = bid.submission_ref, bid.ref
            elif conditions[0].condition_code == 'original_expired_bid_disposition':
                bid, _ = _read_original_expired_bid(reading, conditions[0].object_refs)
                original_ref, bid_ref = bid.submission_ref, bid.ref
            elif conditions[0].condition_code in {'original_procurement_disposition_change', 'original_late_or_expired_submission_disposition'}:
                _, _, bid = _read_original_amendment_rule_bid(reading, conditions[0].object_refs,
                    window_wait=conditions[0].condition_code == 'original_late_or_expired_submission_disposition')
                original_ref, bid_ref = bid.submission_ref, bid.ref
            else:
                original_ref, bid_ref = conditions[0].object_refs
            if (preparation.next_context != context.model_dump(mode='json') or preparation.next_input != selected.action_input
                    or context.run_id != source['identity']['run_id'] or context.contract_ref.id != 'CONTRACTOR-A03'
                    or context.execution_mode != 'llm'
                    or context.business_time != signal.business_time or context.operation_id == source['identity']['request_id']
                    or reading._resolver.source_mode != 'formal' or reading.organization_id != source['identity']['organization_id']
                    or (selected.execution_ref.kind, selected.execution_ref.id) != (original_ref.kind, original_ref.id)
                    or (selected.bid_ref.kind, selected.bid_ref.id) != (bid_ref.kind, bid_ref.id)):
                raise TaskConflict('Amendment successor substitutes current context, input, recipient or original physical bid command')
            reading.check_method_context(context, 'CONTRACTOR-A03')
            execution = reading.resolve(selected.execution_ref)
            package = reading.resolve(Reference.model_validate(preparation.next_input.get('package_ref')))
            tender_round = reading.resolve(Reference.model_validate(preparation.next_input.get('round_ref')))
            rule = reading.resolve(Reference.model_validate(preparation.next_input.get('amendment_rule_ref')))
            if (preparation.next_input.get('bid_ref') != selected.bid_ref.model_dump(mode='json')
                    or not isinstance(execution, ContractorAmendmentSubmissionView)
                    or execution.ref.key() != selected.execution_ref.key() or execution.bid_ref.key() != selected.bid_ref.key()
                    or execution.organization_id != reading.organization_id or execution.command_id not in command_ids
                    or (conditions[0].condition_code != 'query_original_command:' + execution.command_id
                        and conditions[0].condition_code not in {
                            'original_procurement_disposition_required', 'original_procurement_disposition_change',
                            'original_late_or_expired_submission_disposition', 'original_expired_bid_disposition',
                            'original_late_answer_disposition'})
                    or not isinstance(package, ContractorBidPackageView) or not isinstance(tender_round, ContractorAmendmentRoundView)
                    or not isinstance(rule, ContractorAmendmentRuleView) or rule.organization_id != reading.organization_id
                    or rule.prior_package_ref.key() != execution.package_ref.key() or rule.prior_round_ref.key() != execution.round_ref.key()
                    or rule.current_package_ref.key() != package.ref.key() or rule.current_round_ref.key() != tender_round.ref.key()
                    or package.round_ref.key() != tender_round.ref.key() or tender_round.package_ref.key() != package.ref.key()
                    or tender_round.current_package_ref.key() != package.ref.key() or tender_round.amendment_rule_ref.key() != rule.ref.key()):
                raise TaskConflict('Amendment successor changes original bid result or authorized package/round replacement rule')
            if conditions[0].condition_code in {'original_procurement_disposition_required', 'original_procurement_disposition_change',
                    'original_late_or_expired_submission_disposition', 'original_expired_bid_disposition',
                    'original_late_answer_disposition'}:
                profile = journal.registry.get('CONTRACTOR-A03', conditions[0])
                if profile.evaluate(ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))) != 'ready':
                    raise TaskConflict('Amendment withdrawal disposition changed before successor validation')
            reading.recheck()
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_amendment, action_ids={'CONTRACTOR-A03'})


def build_contractor_execution_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Wire all three original A07 query waits to reconciliation without reissuing work."""
    from src.actions.contracts.common import Reference
    from src.coordination.contractor_execution_conditions import contractor_original_execution_profiles
    from src.coordination.continuations import ConditionRegistry, ContinuationJournal, ContinuationPreparation

    if not callable(prepare):
        raise ValueError('Contractor continuation requires independent current preparation')
    profiles = contractor_original_execution_profiles(read_current, validate_relation)
    codes = {profile.condition_code for profile in profiles}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def prepare_existing(source, signal):
        prepared = prepare(deepcopy(source), signal.model_copy(deep=True))
        if not isinstance(prepared, ContinuationPreparation):
            raise TaskConflict('Contractor continuation needs a validated fresh invocation')
        operation = prepared.next_input.get('execution_context', {})
        refs = [Reference.model_validate(ref) for ref in operation.get('execution_refs', [])]
        original = {Reference.model_validate(ref).key()[:2] for condition in source['conditions']
            if condition['condition_code'] in codes for ref in condition['object_refs']}
        if (operation.get('kind') != 'existing' or not original or len(refs) != len(original)
                or {(ref.kind, ref.id) for ref in refs} != original):
            raise TaskConflict('Contractor continuation must reconcile every original command; it cannot reissue construction inputs')
        return prepared

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare_existing, revalidate=revalidate, action_ids={'CONTRACTOR-A07'})


def build_supplier_execution_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Reconcile original A06 production commands without issuing new inputs."""
    from src.actions.contracts.common import Reference, ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal, ContinuationPreparation
    from src.coordination.supplier_execution_conditions import SupplierExecutionConditionReading, supplier_original_execution_profiles

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Supplier production continuation requires independent preparation and revalidation')
    profiles = supplier_original_execution_profiles(read_current, validate_relation)
    by_code = {profile.condition_code: profile for profile in profiles}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def prepare_existing(source, signal):
        prepared = prepare(deepcopy(source), signal.model_copy(deep=True))
        if not isinstance(prepared, ContinuationPreparation):
            raise TaskConflict('Supplier production continuation requires a validated current invocation')
        setup = prepared.next_input.get('execution_setup', {})
        refs = [Reference.model_validate(ref) for ref in setup.get('execution_refs', [])]
        history = [Reference.model_validate(ref) for ref in prepared.next_input.get('prior_execution_refs', [])]
        original = {Reference.model_validate(ref).key()[:2] for condition in source['conditions']
            if condition['condition_code'] in by_code for ref in condition['object_refs']}
        if (setup.get('kind') != 'reconciliation' or not original or len(refs) != len(original)
                or {(ref.kind, ref.id) for ref in refs} != original
                or len(set(history)) != len(history) or not set(refs) <= set(history)):
            raise TaskConflict('Supplier production continuation must query all original commands without replaying inputs')
        return prepared

    def revalidate_query(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions'] if raw['condition_code'] in by_code]
        if len(conditions) != 1:
            raise TaskConflict('Supplier production continuation requires its original emitted same-task wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, SupplierExecutionConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Supplier production successor requires typed current authorized sources')
        try:
            profile = next(item for item in supplier_original_execution_profiles(lambda _: selected, validate_relation)
                if item.condition_code == conditions[0].condition_code)
            if profile.evaluate(check) != 'ready':
                raise TaskConflict('Supplier production query is no longer available before successor registration')
            refs = [Reference.model_validate(ref) for ref in preparation.next_input.get('execution_setup', {}).get('execution_refs', [])]
            history = [Reference.model_validate(ref) for ref in preparation.next_input.get('prior_execution_refs', [])]
            if (preparation.next_input.get('execution_setup', {}).get('kind') != 'reconciliation'
                    or len(set(history)) != len(history) or not set(refs) <= set(history)
                    or preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input.get('task_ref') != selected.task_ref.model_dump(mode='json')
                    or refs != list(selected.execution_refs)
                    or selected.action_input is not None and preparation.next_input != selected.action_input):
                raise TaskConflict('Supplier production successor changes selected current task/context/history or query input')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare_existing, revalidate=revalidate_query, action_ids={'SUPPLIER-A06'})


def build_supplier_resource_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Rejudge original resource demand after querying all cross-task commands."""
    from src.coordination.supplier_resource_conditions import SupplierResourceConditionReading, supplier_original_resource_profile

    return _build_supplier_input_continuation_dispatcher(inbox=inbox, store=store, read_current=read_current,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare, revalidate=revalidate,
        reading_type=SupplierResourceConditionReading, profile_factory=supplier_original_resource_profile)


def build_supplier_inventory_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Rejudge original material demand after querying all inventory commands."""
    from src.coordination.supplier_inventory_conditions import SupplierInventoryConditionReading, supplier_original_inventory_profile

    return _build_supplier_input_continuation_dispatcher(inbox=inbox, store=store, read_current=read_current,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare, revalidate=revalidate,
        reading_type=SupplierInventoryConditionReading, profile_factory=supplier_original_inventory_profile)


def _build_supplier_input_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate, reading_type, profile_factory):
    """Preserve the selected original input wait and full current successor."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Supplier input recovery requires independent preparation and current validation')
    profile = profile_factory(read_current, validate_relation)
    journal = ContinuationJournal(store, ConditionRegistry([profile]))

    def revalidate_resource(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] == profile.condition_code]
        if len(conditions) != 1:
            raise TaskConflict('Supplier input recovery requires its original emitted input wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, reading_type) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Supplier input successor requires typed current authorized sources')
        try:
            current_profile = profile_factory(lambda _: selected, validate_relation)
            if current_profile.evaluate(check) != 'ready':
                raise TaskConflict('Supplier cross-task input queries are no longer complete before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input
                    or preparation.next_input.get('execution_setup', {}).get('kind') != 'production'):
                raise TaskConflict('Supplier input successor replaces selected current context/task/input or production branch')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_resource, action_ids={'SUPPLIER-A06'})


def build_government_review_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Recheck original A04 source readiness before exact successor registration."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.government_review_conditions import GovernmentReviewConditionReading, government_original_review_task_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Government review recovery requires independent preparation/current validation')
    profile = government_original_review_task_profile(read_current, validate_relation)
    journal = ContinuationJournal(store, ConditionRegistry([profile]))

    def revalidate_review(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] == profile.condition_code]
        if len(conditions) != 1:
            raise TaskConflict('Government review recovery requires original emitted case/task/submission wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, GovernmentReviewConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Government review successor requires typed current authorized sources')
        try:
            current = government_original_review_task_profile(lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('Government review original sources are no longer ready before registration')
            if preparation.next_context != selected.context.model_dump(mode='json') or preparation.next_input != selected.action_input:
                raise TaskConflict('Government review successor replaces selected exact current input/context')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_review, action_ids={'GOV-A04'})


def build_government_decision_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Recheck original A07 source readiness before exact successor registration."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.government_decision_conditions import (
        GovernmentDecisionConditionReading, government_original_decision_case_profile, government_original_decision_query_profile,
        government_original_decision_unresolved_profile,
    )
    from src.coordination.government_decision_notification import government_original_decision_notification_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Government decision recovery requires independent preparation/current validation')
    factories = (government_original_decision_case_profile, government_original_decision_query_profile,
        government_original_decision_unresolved_profile, government_original_decision_notification_profile)
    profiles = [factory(read_current, validate_relation) for factory in factories]
    by_code = {profile.condition_code: factory for profile, factory in zip(profiles, factories)}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_decision(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in by_code]
        if len(conditions) != 1:
            raise TaskConflict('Government decision recovery requires one original emitted supported wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, GovernmentDecisionConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Government decision successor requires typed current authorized sources')
        try:
            current = by_code[conditions[0].condition_code](lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('Government decision original sources are no longer ready before registration')
            if preparation.next_context != selected.context.model_dump(mode='json') or preparation.next_input != selected.action_input:
                raise TaskConflict('Government decision successor replaces selected exact current input/context')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_decision, action_ids={'GOV-A07'})


def build_government_supplement_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Recheck original A06 source readiness before exact successor registration."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.government_supplement_conditions import (
        GovernmentSupplementConditionReading, government_original_supplement_case_profile,
        government_original_supplement_window_profile, government_original_supplement_delay_basis_profile,
        government_original_supplement_delay_permission_profile,
        government_original_supplement_response_profile,
        government_original_supplement_reassessment_profile,
    )
    from src.coordination.government_supplement_transfer import government_original_supplement_transfer_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Government supplement recovery requires independent preparation/current validation')
    factories = (government_original_supplement_case_profile, government_original_supplement_window_profile,
        government_original_supplement_delay_basis_profile, government_original_supplement_delay_permission_profile,
        government_original_supplement_response_profile, government_original_supplement_reassessment_profile,
        government_original_supplement_transfer_profile)
    profiles = [factory(read_current, validate_relation) for factory in factories]
    by_code = {profile.condition_code: factory for profile, factory in zip(profiles, factories)}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_supplement(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in by_code]
        if len(conditions) != 1:
            raise TaskConflict('Government supplement recovery requires one original emitted supported wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, GovernmentSupplementConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Government supplement successor requires typed current authorized sources')
        try:
            current = by_code[conditions[0].condition_code](lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('Government supplement original sources are no longer ready before registration')
            if preparation.next_context != selected.context.model_dump(mode='json') or preparation.next_input != selected.action_input:
                raise TaskConflict('Government supplement successor replaces selected exact current input/context')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_supplement, action_ids={'GOV-A06'})


def build_government_consultation_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Recheck original A05 source readiness before exact successor registration."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.government_consultation_conditions import (
        GovernmentConsultationConditionReading, government_original_consultation_task_profile,
        government_original_consultation_active_profile, government_original_consultation_opinion_profile,
        government_original_consultation_no_opinion_profile,
    )
    from src.coordination.government_consultation_disclosure import (
        government_original_consultation_disclosure_profile, government_original_consultation_case_profile,
        government_original_consultation_applicability_profile,
    )
    from src.coordination.government_consultation_query import government_original_consultation_query_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Government consultation recovery requires independent preparation/current validation')
    factories = (government_original_consultation_task_profile, government_original_consultation_disclosure_profile,
        government_original_consultation_case_profile, government_original_consultation_active_profile,
        government_original_consultation_opinion_profile, government_original_consultation_no_opinion_profile,
        government_original_consultation_applicability_profile, government_original_consultation_query_profile)
    profiles = [factory(read_current, validate_relation) for factory in factories]
    by_code = {profile.condition_code: factory for profile, factory in zip(profiles, factories)}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_consultation(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in by_code]
        if len(conditions) != 1:
            raise TaskConflict('Government consultation recovery requires one original emitted supported wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, GovernmentConsultationConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Government consultation successor requires typed current authorized sources')
        try:
            current = by_code[conditions[0].condition_code](lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('Government consultation original sources are no longer ready before registration')
            if preparation.next_context != selected.context.model_dump(mode='json') or preparation.next_input != selected.action_input:
                raise TaskConflict('Government consultation successor replaces selected exact current input/context')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_consultation, action_ids={'GOV-A05'})


def build_government_scheduling_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Recheck original A03 task readiness before full-input successor registration."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.government_scheduling_conditions import (
        GovernmentSchedulingConditionReading, government_original_scheduling_profiles,
    )

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Government scheduling recovery requires independent preparation and current validation')
    profiles = government_original_scheduling_profiles(read_current, validate_relation)
    by_code = {profile.condition_code: profile for profile in profiles}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_scheduling(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in by_code]
        if len(conditions) != 1:
            raise TaskConflict('Government scheduling recovery requires its original emitted task wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, GovernmentSchedulingConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Government scheduling successor requires typed current authorized sources')
        try:
            current = next(profile for profile in government_original_scheduling_profiles(lambda _: selected, validate_relation)
                if profile.condition_code == conditions[0].condition_code)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('Government original scheduling task is no longer ready before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('Government scheduling successor replaces selected current context or full input')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_scheduling, action_ids={'GOV-A03'})


def build_government_inspection_task_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Resume registered original A10 task waits using current native facts."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.government_inspection_conditions import (
        GovernmentInspectionTaskConditionReading, government_original_inspection_profiles,
    )

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Government inspection recovery requires independent preparation and current validation')
    profiles = government_original_inspection_profiles(read_current, validate_relation)
    by_code = {profile.condition_code: profile for profile in profiles}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_task(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in by_code]
        if len(conditions) != 1:
            raise TaskConflict('Government inspection recovery requires its original emitted task wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, GovernmentInspectionTaskConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Government inspection successor requires typed current authorized sources')
        try:
            current = next(profile for profile in government_original_inspection_profiles(lambda _: selected, validate_relation)
                if profile.condition_code == conditions[0].condition_code)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('Government original inspection task is no longer ready before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('Government inspection successor replaces selected current context, task or full input')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_task, action_ids={'GOV-A10'})


def build_government_use_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Rejudge original A11 use planning after its native dependency is satisfied."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.government_use_conditions import GovernmentUseConditionReading, government_original_use_profiles

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Government use recovery requires independent preparation and current validation')
    profiles = government_original_use_profiles(read_current, validate_relation)
    by_code = {profile.condition_code: profile for profile in profiles}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_use(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in by_code]
        if len(conditions) != 1:
            raise TaskConflict('Government use recovery requires its original emitted dependency wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, GovernmentUseConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Government use successor requires typed authorized current sources')
        try:
            current = next(profile for profile in government_original_use_profiles(lambda _: selected, validate_relation)
                if profile.condition_code == conditions[0].condition_code)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('Government original use dependency is no longer ready before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('Government use successor replaces selected current context or full input')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_use, action_ids={'GOV-A11'})


def build_qs_bid_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Rejudge actual original bid round reactivation with its selected full input."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.qs_bid_conditions import QSBidConditionReading, qs_original_bid_round_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('QS bid recovery requires independent preparation and current validation')
    profile = qs_original_bid_round_profile(read_current, validate_relation)
    journal = ContinuationJournal(store, ConditionRegistry([profile]))

    def revalidate_bid(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] == profile.condition_code]
        if len(conditions) != 1:
            raise TaskConflict('QS bid recovery requires its original emitted round wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, QSBidConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('QS bid successor requires typed current authorized sources')
        try:
            current = qs_original_bid_round_profile(lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('QS original bid round is no longer active before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('QS bid successor replaces selected current context or full input')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_bid, action_ids={'QS-A06'})


def build_qs_procurement_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Rejudge actual original procurement task/round readiness with its selected full input."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.qs_procurement_conditions import QSProcurementConditionReading, qs_original_procurement_task_round_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('QS procurement recovery requires independent preparation and current validation')
    profile = qs_original_procurement_task_round_profile(read_current, validate_relation)
    journal = ContinuationJournal(store, ConditionRegistry([profile]))

    def revalidate_procurement(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] == profile.condition_code]
        if len(conditions) != 1:
            raise TaskConflict('QS procurement recovery requires its original emitted joint task/round wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, QSProcurementConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('QS procurement successor requires typed current authorized sources')
        try:
            current = qs_original_procurement_task_round_profile(lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('QS original procurement task/round is no longer ready before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('QS procurement successor replaces selected current context or full input')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_procurement, action_ids={'QS-A05'})


def build_qs_appointment_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Rejudge the exact original appointment task before successor registration."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.qs_appointment_conditions import (
        QSAppointmentConditionReading, qs_original_appointment_task_profile, qs_original_appointment_task_profiles,
    )

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('QS appointment recovery requires independent preparation and current validation')
    profiles = qs_original_appointment_task_profiles(read_current, validate_relation)
    codes = {profile.condition_code for profile in profiles}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_appointment(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in codes]
        if len(conditions) != 1:
            raise TaskConflict('QS appointment recovery requires its original emitted task wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, QSAppointmentConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('QS appointment successor requires typed current authorized sources')
        try:
            current = qs_original_appointment_task_profile(lambda _: selected, validate_relation,
                condition_code=conditions[0].condition_code)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('QS original appointment task is no longer ready before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('QS appointment successor replaces selected current context or full input')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_appointment, action_ids={'QS-A03'})


def build_qs_final_account_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Recheck authentic A09 query history before registering a fresh judgment."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.qs_final_account_conditions import (
        QSFinalAccountConditionReading, qs_original_final_account_execution_profile,
    )

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('QS final-account recovery requires independent preparation and current validation')
    profile = qs_original_final_account_execution_profile(read_current, validate_relation)
    journal = ContinuationJournal(store, ConditionRegistry([profile]))

    def revalidate_final_account(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] == profile.condition_code]
        if len(conditions) != 1:
            raise TaskConflict('QS final-account recovery requires its original execution wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, QSFinalAccountConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('QS final-account successor requires typed current authorized sources')
        try:
            current = qs_original_final_account_execution_profile(lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('QS original final-account query is no longer ready before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('QS final-account successor replaces selected current context or full input')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_final_account, action_ids={'QS-A09'})


def build_qs_learning_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Recheck preserved error application history before a new private judgment."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.qs_learning_conditions import QSLearningConditionReading, qs_original_cost_error_application_profile
    from src.coordination.architect_learning_conditions import ArchitectLearningConditionReading
    from src.coordination.qs_learning_execution_query import qs_original_learning_execution_profile
    from src.coordination.qs_training_conditions import (
        qs_original_training_dependency_profile, qs_original_training_capacity_profile,
    )
    from src.coordination.qs_learning_applied_feedback import (
        qs_original_applied_feedback_profile, qs_original_judgment_change_profile,
    )

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('QS learning recovery requires independent preparation and current validation')
    factories = (qs_original_cost_error_application_profile, qs_original_learning_execution_profile,
        qs_original_training_dependency_profile, qs_original_training_capacity_profile,
        qs_original_applied_feedback_profile, qs_original_judgment_change_profile)
    profiles = [factory(read_current, validate_relation) for factory in factories]
    by_code = {profile.condition_code: factory for profile, factory in zip(profiles, factories)}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_learning(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in by_code]
        if len(conditions) != 1:
            raise TaskConflict('QS learning recovery requires its original applied-pair, execution or training wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        expected_type = QSLearningConditionReading if conditions[0].condition_code == profiles[0].condition_code else ArchitectLearningConditionReading
        if not isinstance(selected, expected_type) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('QS learning successor requires typed current authorized sources')
        try:
            current = by_code[conditions[0].condition_code](lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('QS original learning wait is no longer ready before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('QS learning successor replaces selected current context or full input')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_learning, action_ids={'QS-A12'})


def build_qs_research_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Rejudge actual original research task readiness with its selected full input."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.qs_research_conditions import QSResearchConditionReading, qs_original_research_task_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('QS research recovery requires independent preparation and current validation')
    profile = qs_original_research_task_profile(read_current, validate_relation)
    journal = ContinuationJournal(store, ConditionRegistry([profile]))

    def revalidate_research(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] == profile.condition_code]
        if len(conditions) != 1:
            raise TaskConflict('QS research recovery requires its original emitted task wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, QSResearchConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('QS research successor requires typed current authorized sources')
        try:
            current = qs_original_research_task_profile(lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('QS original research task is no longer ready before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('QS research successor replaces selected current context or full input')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_research, action_ids={'QS-A13'})


def build_qs_cost_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Rejudge actual original cost task authorization with its selected full input."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.qs_cost_conditions import QSCostConditionReading, qs_original_cost_task_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('QS cost recovery requires independent preparation and current validation')
    profile = qs_original_cost_task_profile(read_current, validate_relation)
    journal = ContinuationJournal(store, ConditionRegistry([profile]))

    def revalidate_cost(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] == profile.condition_code]
        if len(conditions) != 1:
            raise TaskConflict('QS cost recovery requires its original emitted task wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, QSCostConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('QS cost successor requires typed current authorized sources')
        try:
            current = qs_original_cost_task_profile(lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('QS original cost task is no longer authorized before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('QS cost successor replaces selected current context or full input')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_cost, action_ids={'QS-A04'})


def build_qs_change_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Rejudge actual original claim resubmission with its selected full input."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.qs_change_conditions import QSChangeConditionReading, qs_original_change_claim_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('QS change recovery requires independent preparation and current validation')
    profile = qs_original_change_claim_profile(read_current, validate_relation)
    journal = ContinuationJournal(store, ConditionRegistry([profile]))

    def revalidate_change(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] == profile.condition_code]
        if len(conditions) != 1:
            raise TaskConflict('QS change recovery requires its original emitted claim wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, QSChangeConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('QS change successor requires typed current authorized sources')
        try:
            current = qs_original_change_claim_profile(lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('QS original change claim is no longer submitted before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('QS change successor replaces selected current context or full input')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_change, action_ids={'QS-A07'})


def build_qs_payment_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Rejudge the original submitted application using its current full input."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.qs_payment_conditions import QSPaymentConditionReading, qs_original_payment_application_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('QS payment recovery requires independent preparation and current validation')
    profile = qs_original_payment_application_profile(read_current, validate_relation)
    journal = ContinuationJournal(store, ConditionRegistry([profile]))

    def revalidate_payment(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] == profile.condition_code]
        if len(conditions) != 1:
            raise TaskConflict('QS payment recovery requires its original emitted application wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, QSPaymentConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('QS payment successor requires typed current authorized sources')
        try:
            current = qs_original_payment_application_profile(lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('QS original payment application is no longer submitted before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('QS payment successor replaces selected current context or full input')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_payment, action_ids={'QS-A08'})


def build_supplier_quality_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Rejudge original batch quality after complete native disposition query."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.supplier_quality_conditions import SupplierQualityConditionReading, supplier_original_disposition_profiles

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Supplier quality continuation requires independent preparation and current revalidation')
    profiles = supplier_original_disposition_profiles(read_current, validate_relation)
    by_code = {profile.condition_code: profile for profile in profiles}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_quality(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions'] if raw['condition_code'] in by_code]
        if len(conditions) != 1:
            raise TaskConflict('Supplier quality continuation requires its original emitted disposition wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, SupplierQualityConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Supplier quality successor requires typed authorized current sources')
        try:
            profile = next(item for item in supplier_original_disposition_profiles(lambda _: selected, validate_relation)
                if item.condition_code == conditions[0].condition_code)
            if profile.evaluate(check) != 'ready':
                raise TaskConflict('Supplier disposition history is no longer complete before successor registration')
            if (preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input != selected.action_input):
                raise TaskConflict('Supplier quality successor changes selected current batch/profile/input or context')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_quality, action_ids={'SUPPLIER-A07'})


def build_supplier_transport_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Wake the original A08 transport operation into a currently authorized query."""
    from src.actions.contracts.common import Reference, ResumeCondition
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.supplier_transport_conditions import (
        check_supplier_query_selection, supplier_original_transport_profile,
    )

    if not callable(revalidate):
        raise ValueError('Supplier transport continuation requires independent current revalidation')
    profile = supplier_original_transport_profile(read_current, validate_relation)
    journal = ContinuationJournal(store, ConditionRegistry([profile]))

    def revalidate_query(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(row) for row in source['conditions']
            if row['condition_code'] == profile.condition_code]
        if len(conditions) != 1:
            raise TaskConflict('Supplier continuation changes its original transport wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        current_profile = check_supplier_query_selection(selected)
        try:
            current = supplier_original_transport_profile(lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('Supplier original transport history is no longer ready before registration')
            refs = [Reference.model_validate(ref) for ref in preparation.next_input.get('shipment_refs', [])]
            original = {(ref.kind, ref.id) for ref in conditions[0].object_refs}
            if (selected.context.run_id != source['identity']['run_id']
                    or selected.reading.organization_id != source['identity']['organization_id']
                    or {(ref.kind, ref.id) for ref in selected.shipment_refs} != original
                    or preparation.next_context != selected.context.model_dump(mode='json')
                    or preparation.next_input.get('logistics_profile_ref') != selected.logistics_profile_ref.model_dump(mode='json')
                    or preparation.next_input.get('order_ref') != current_profile.order_ref.model_dump(mode='json')
                    or not set(selected.shipment_refs) <= set(refs) or len(set(refs)) != len(refs)
                    or not original <= {(ref.kind, ref.id) for ref in refs}):
                raise TaskConflict('Supplier successor must query all original transport commands under the selected current reconcile profile')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_query, action_ids={'SUPPLIER-A08'})


def build_government_permit_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Recheck original A08 permit effect before exact successor registration."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.government_permit_conditions import GovernmentPermitConditionReading, government_original_permit_effect_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Government permit recovery requires independent preparation/current validation')
    profile = government_original_permit_effect_profile(read_current, validate_relation)
    journal = ContinuationJournal(store, ConditionRegistry([profile]))

    def revalidate_permit(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] == profile.condition_code]
        if len(conditions) != 1:
            raise TaskConflict('Government permit recovery requires original emitted permit-effect wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, GovernmentPermitConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Government permit successor requires typed current authorized sources')
        try:
            current = government_original_permit_effect_profile(lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('Government permit original sources are no longer ready before registration')
            if preparation.next_context != selected.context.model_dump(mode='json') or preparation.next_input != selected.action_input:
                raise TaskConflict('Government permit successor replaces selected exact current input/context')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_permit, action_ids={'GOV-A08'})


def build_government_transition_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Recheck original A09 command query before exact successor registration."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.government_transition_conditions import GovernmentTransitionConditionReading, government_original_transition_query_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Government transition recovery requires independent preparation/current validation')
    from src.coordination.government_transition_notification import government_original_transition_notification_profile
    factories = (government_original_transition_query_profile, government_original_transition_notification_profile)
    profiles = [factory(read_current, validate_relation) for factory in factories]
    by_code = {profile.condition_code: factory for profile, factory in zip(profiles, factories)}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_transition(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in by_code]
        if len(conditions) != 1:
            raise TaskConflict('Government transition recovery requires original emitted original-command wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, GovernmentTransitionConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Government transition successor requires typed current authorized sources')
        try:
            current = by_code[conditions[0].condition_code](lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('Government transition original sources are no longer ready before registration')
            if preparation.next_context != selected.context.model_dump(mode='json') or preparation.next_input != selected.action_input:
                raise TaskConflict('Government transition successor replaces selected exact current input/context')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_transition, action_ids={'GOV-A09'})



def build_government_feedback_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Recheck original A12 work dependency before exact successor registration."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.government_feedback_conditions import (
        GovernmentFeedbackConditionReading, government_original_feedback_dependency_profile,
        government_original_feedback_assignment_profile, government_original_feedback_capacity_profile,
    )
    from src.coordination.government_feedback_execution_query import government_original_feedback_execution_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Government feedback recovery requires independent preparation/current validation')
    factories = (government_original_feedback_dependency_profile, government_original_feedback_assignment_profile,
        government_original_feedback_execution_profile, government_original_feedback_capacity_profile)
    profiles = [factory(read_current, validate_relation) for factory in factories]
    by_code = {profile.condition_code: factory for profile, factory in zip(profiles, factories)}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_feedback(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in by_code]
        if len(conditions) != 1:
            raise TaskConflict('Government feedback recovery requires original emitted work-dependency wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, GovernmentFeedbackConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Government feedback successor requires typed current authorized sources')
        try:
            current = by_code[conditions[0].condition_code](lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('Government feedback original sources are no longer ready before registration')
            if preparation.next_context != selected.context.model_dump(mode='json') or preparation.next_input != selected.action_input:
                raise TaskConflict('Government feedback successor replaces selected exact current input/context')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_feedback, action_ids={'GOV-A12'})


def build_architect_learning_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Recheck original Architect learning wait before exact successor registration."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.architect_learning_conditions import (
        ArchitectLearningConditionReading, architect_original_training_dependency_profile, architect_original_training_capacity_profile,
    )
    from src.coordination.architect_learning_execution_query import architect_original_learning_execution_profile
    from src.coordination.architect_learning_applied_feedback import architect_original_applied_feedback_profile
    from src.coordination.architect_learning_judgment_change import architect_original_judgment_change_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Architect learning recovery requires independent preparation/current validation')
    factories = (architect_original_training_dependency_profile, architect_original_learning_execution_profile,
        architect_original_training_capacity_profile, architect_original_applied_feedback_profile,
        architect_original_judgment_change_profile)
    profiles = [factory(read_current, validate_relation) for factory in factories]
    by_code = {profile.condition_code: factory for profile, factory in zip(profiles, factories)}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_learning(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in by_code]
        if len(conditions) != 1:
            raise TaskConflict('Architect learning recovery requires its original emitted wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, ArchitectLearningConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Architect learning successor requires typed current authorized sources')
        try:
            current = by_code[conditions[0].condition_code](lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('Architect learning original sources are no longer ready before registration')
            if preparation.next_context != selected.context.model_dump(mode='json') or preparation.next_input != selected.action_input:
                raise TaskConflict('Architect learning successor replaces selected exact current input/context')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_learning, action_ids={'ARCHITECT-A12'})


def build_engineer_learning_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    """Recheck original Engineer training sources before exact successor registration."""
    from src.actions.contracts.common import ResumeCondition
    from src.actions.contracts.references import ActionReadView
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.engineer_learning_conditions import (
        EngineerLearningConditionReading, engineer_original_training_dependency_profile, engineer_original_training_capacity_profile,
    )
    from src.coordination.engineer_learning_execution_query import engineer_original_learning_execution_profile
    from src.coordination.engineer_learning_applied_feedback import engineer_original_applied_feedback_profile
    from src.coordination.engineer_learning_judgment_change import engineer_original_judgment_change_profile
    from src.coordination.engineer_qualification_conditions import engineer_original_qualification_application_profile

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Engineer learning recovery requires independent preparation/current validation')
    factories = (engineer_original_training_dependency_profile, engineer_original_learning_execution_profile,
        engineer_original_training_capacity_profile, engineer_original_applied_feedback_profile,
        engineer_original_judgment_change_profile, engineer_original_qualification_application_profile)
    profiles = [factory(read_current, validate_relation) for factory in factories]
    by_code = {profile.condition_code: factory for profile, factory in zip(profiles, factories)}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_learning(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions']
            if raw['condition_code'] in by_code]
        if len(conditions) != 1:
            raise TaskConflict('Engineer learning recovery requires original emitted training-dependency wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, EngineerLearningConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Engineer learning successor requires typed current authorized sources')
        try:
            current = by_code[conditions[0].condition_code](lambda _: selected, validate_relation)
            if current.evaluate(check) != 'ready':
                raise TaskConflict('Engineer learning original sources are no longer ready before registration')
            if preparation.next_context != selected.context.model_dump(mode='json') or preparation.next_input != selected.action_input:
                raise TaskConflict('Engineer learning successor replaces selected exact current input/context')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_learning, action_ids={'ENGINEER-A12'})


def build_architect_transition_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    return _build_service_transition_continuation_dispatcher(inbox=inbox, store=store, read_current=read_current,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare, revalidate=revalidate)


def build_engineer_transition_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    return _build_service_transition_continuation_dispatcher(inbox=inbox, store=store, read_current=read_current,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare, revalidate=revalidate, engineer=True)


def build_qs_transition_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate):
    return _build_service_transition_continuation_dispatcher(inbox=inbox, store=store, read_current=read_current,
        validate_relation=validate_relation, project_signal=project_signal, prepare=prepare, revalidate=revalidate, qs=True)


def _build_service_transition_continuation_dispatcher(*, inbox, store, read_current,
        validate_relation, project_signal, prepare, revalidate, engineer=False, qs=False):
    if engineer and qs:
        raise ValueError('Service transition dispatcher requires one original role')
    from src.actions.contracts.common import ResumeCondition
    from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationJournal
    from src.coordination.architect_transition_conditions import (
        ArchitectTransitionConditionReading, architect_original_handover_acceptance_profile, architect_original_recall_window_profile,
        architect_original_recall_dependency_profile, architect_original_recall_capacity_profile,
    )
    from src.coordination.architect_transition_execution_query import architect_original_transition_execution_profile
    from src.coordination.architect_transition_allocation_query import (
        architect_original_recall_allocation_profile, architect_original_handover_allocation_profile,
    )

    if not callable(prepare) or not callable(revalidate):
        raise ValueError('Architect service recovery requires independent successor validation')
    factories = (architect_original_handover_acceptance_profile, architect_original_transition_execution_profile,
        architect_original_recall_window_profile, architect_original_recall_allocation_profile,
        architect_original_handover_allocation_profile, architect_original_recall_dependency_profile,
        architect_original_recall_capacity_profile)
    action_id = 'ARCHITECT-A11'
    if engineer:
        from src.coordination.engineer_transition_conditions import (
            engineer_original_handover_acceptance_profile, engineer_original_recall_window_profile,
            engineer_original_recall_allocation_profile, engineer_original_handover_allocation_profile,
            engineer_original_recall_dependency_profile, engineer_original_recall_capacity_profile,
        )
        from src.coordination.engineer_transition_execution_query import engineer_original_transition_execution_profile
        action_id, factories = 'ENGINEER-A11', (engineer_original_handover_acceptance_profile,
            engineer_original_transition_execution_profile, engineer_original_recall_window_profile,
            engineer_original_recall_allocation_profile, engineer_original_handover_allocation_profile,
            engineer_original_recall_dependency_profile, engineer_original_recall_capacity_profile)
    if qs:
        from src.coordination.qs_transition_conditions import (
            qs_original_handover_acceptance_profile, qs_original_recall_window_profile,
            qs_original_recall_allocation_profile, qs_original_handover_allocation_profile,
            qs_original_recall_dependency_profile, qs_original_recall_capacity_profile,
        )
        from src.coordination.qs_transition_execution_query import qs_original_transition_execution_profile
        action_id, factories = 'QS-A11', (qs_original_handover_acceptance_profile, qs_original_transition_execution_profile,
            qs_original_recall_window_profile, qs_original_recall_allocation_profile, qs_original_handover_allocation_profile,
            qs_original_recall_dependency_profile, qs_original_recall_capacity_profile)
    profiles = [factory(read_current, validate_relation) for factory in factories]
    profile_factories = {profile.condition_code: factory for profile, factory in zip(profiles, factories)}
    journal = ContinuationJournal(store, ConditionRegistry(profiles))

    def revalidate_transition(source, preparation, signal):
        conditions = [ResumeCondition.model_validate(raw) for raw in source['conditions'] if raw['condition_code'] in profile_factories]
        if len(conditions) != 1:
            raise TaskConflict('Architect service recovery requires one original emitted registered wait')
        check = ConditionCheck(deepcopy(source), conditions[0], signal.model_copy(deep=True))
        selected = read_current(deepcopy(check))
        if not isinstance(selected, ArchitectTransitionConditionReading):
            raise TaskConflict('Architect service successor requires actual current invocation sources')
        try:
            if profile_factories[check.condition.condition_code](lambda _: selected, validate_relation).evaluate(check) != 'ready':
                raise TaskConflict('Architect service condition no longer ready before successor registration')
            if preparation.next_context != selected.context.model_dump(mode='json') or preparation.next_input != selected.action_input:
                raise TaskConflict('Architect service successor replaces exact current input/context')
            return revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True)) is True
        finally:
            selected.reading.recheck()

    return ObservationContinuationDispatcher(inbox=inbox, journal=journal, project_signal=project_signal,
        prepare=prepare, revalidate=revalidate_transition, action_ids={action_id})
