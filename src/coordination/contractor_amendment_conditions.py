"""Resolve original Contractor A03 bid commands before independent disposition."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, TimeWindow
from src.actions.contracts.contractor_amendment_objects import (
    ContractorAmendmentBidView, ContractorAmendmentProfileView, ContractorAmendmentQuestionView,
    ContractorAmendmentRuleView, ContractorAmendmentSubmissionView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionCheck, ConditionProfile
from src.coordination.contractor_formation_conditions import _contractor_original_bid_command_profile
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class ContractorAmendmentCommandConditionReading:
    context: ActionContext
    reading: ActionReadView
    execution_ref: Reference
    bid_ref: Reference
    action_input: dict
    rule_ref: Reference | None = None


def contractor_original_amendment_command_profile(command_id, read_current, validate_relation):
    """Resolve A03's exact dynamic event code under the application's original guard.

    Unknown/pending commands stay waiting. Authentic final result evidence only
    permits fresh disposition judgment: failure retains its original technical
    error; rejected/not-submitted results do not establish an effective bid.
    Explain/revise/maintain/withdraw, reservation release and amended submission
    remain independently checked by the original A03 processor and endpoints.
    """
    return _contractor_original_bid_command_profile(command_id, read_current, validate_relation,
        action_id='CONTRACTOR-A03', reading_type=ContractorAmendmentCommandConditionReading)


def contractor_original_amendment_disposition_profile(read_current, validate_relation):
    """Wake an ineffective bid only for an explicitly permitted withdrawal judgment.

    Known rejection/non-submission remains unchanged. The current actual rule
    and profile must select withdrawal with an allowed current template window.
    Independent native validation covers both original command and disposition
    evidence. Ready grants no release of reservations or effective withdrawal;
    those still require the original processor and an actual submission receipt.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Amendment disposition requires actual sources and independent native validation')
    code = 'original_procurement_disposition_required'

    def evaluate(check):
        source, refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'CONTRACTOR-A03' or source['role'] != 'Contractor' or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'event'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(refs) != 2 or refs[0].kind != 'SubmissionExecution' or refs[1].kind != 'Bid'):
            raise TaskConflict('Amendment disposition changes original action, recipient or bid command')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, ContractorAmendmentCommandConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.execution_ref, Reference) or not isinstance(selected.bid_ref, Reference)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Amendment disposition requires actual typed current sources and input')
        reading, context = selected.reading, selected.context.model_copy(deep=True)
        try:
            original = reading.resolve(refs[0])
            current = reading.resolve(selected.execution_ref)
            if (not isinstance(original, ContractorAmendmentSubmissionView)
                    or original.status not in {'rejected', 'not_submitted'}
                    or not isinstance(current, ContractorAmendmentSubmissionView) or current.status != original.status):
                raise TaskConflict('Amendment disposition cannot erase original rejection or non-submission')
            rule_ref = Reference.model_validate(selected.action_input.get('amendment_rule_ref'))
            rule = reading.resolve(rule_ref)
            if not isinstance(rule, ContractorAmendmentRuleView) or rule.ref.key() != rule_ref.key():
                raise TaskConflict('Amendment disposition lacks its exact current native rule')
            profile = reading.resolve(rule.profile_ref)
            if (rule.organization_id != source['organization_id']
                    or rule.prior_package_ref.key() != current.package_ref.key()
                    or rule.prior_round_ref.key() != current.round_ref.key()
                    or rule.current_package_ref.model_dump(mode='json') != selected.action_input.get('package_ref')
                    or rule.current_round_ref.model_dump(mode='json') != selected.action_input.get('round_ref')
                    or not isinstance(profile, ContractorAmendmentProfileView) or profile.ref.key() != rule.profile_ref.key()
                    or profile.organization_id != source['organization_id'] or profile.bid_ref.key() != selected.bid_ref.key()
                    or selected.action_input.get('bid_ref') != selected.bid_ref.model_dump(mode='json')):
                raise TaskConflict('Amendment disposition substitutes original bid or package/round rule relationships')
            now = context.business_time
            for row in (rule, profile):
                if (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                        or not row.effective_window.contains(now)):
                    return 'unavailable'
            if (rule.notice_received_at.clock_ref != now.clock_ref or rule.notice_received_at.offset > now.offset):
                return 'unavailable'
            if profile.choice != 'withdraw' or rule.dispositions.get('withdraw') != 'allowed':
                return 'waiting'
            window_ref = rule.action_window_refs.get('withdraw')
            if window_ref is None:
                return 'unavailable'
            window = reading.resolve(window_ref)
            if not isinstance(window, TimeWindow) or not window.contains(now):
                return 'unavailable'
            observations = {}
            for ref in [rule.disposition_basis_ref, *rule.evidence_refs, *profile.evidence_refs]:
                evidence = reading.resolve(ref)
                if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic'
                        or evidence.basis_kind != 'observed'):
                    raise TaskConflict('Amendment disposition requires actual observed native rule evidence')
                if evidence.effective_window is not None and not evidence.effective_window.contains(now):
                    return 'unavailable'
                observations[evidence.ref.key()] = evidence.model_dump(mode='json')

            def validate_disposition(**query):
                return validate_relation(**query, disposition_rule=rule.model_dump(mode='json'),
                    disposition_profile=profile.model_dump(mode='json'), withdrawal_window=window.model_dump(mode='json'),
                    disposition_evidence=deepcopy(list(observations.values())))

            query = contractor_original_amendment_command_profile(original.command_id, lambda _: selected, validate_disposition)
            condition = check.condition.model_copy(deep=True, update={'condition_code': query.condition_code})
            return query.evaluate(ConditionCheck(deepcopy(check.source), condition, check.signal.model_copy(deep=True)))
        finally:
            reading.recheck()

    return ConditionProfile('CONTRACTOR-A03', code, '1', frozenset({'event'}), evaluate)


def _read_original_amendment_rule_bid(reading, refs, *, window_wait=False):
    """Recover the exact bid behind the original rule/evidence wait references."""
    if (len(refs) != 2 or refs[0].kind != 'TenderAmendmentRule'
            or refs[1].kind != ('TimeWindow' if window_wait else 'Evidence')):
        raise TaskConflict('Amendment rule wait requires its original rule and exact evidence/window')
    rule = reading.resolve(refs[0])
    if (not isinstance(rule, ContractorAmendmentRuleView) or rule.ref.key() != refs[0].key()
            or (not window_wait and rule.disposition_basis_ref.key() != refs[1].key())
            or rule.organization_id != reading.organization_id):
        raise TaskConflict('Amendment rule wait changes original rule, recipient or disposition evidence')
    profile = reading.resolve(rule.profile_ref)
    if (not isinstance(profile, ContractorAmendmentProfileView) or profile.ref.key() != rule.profile_ref.key()
            or profile.organization_id != reading.organization_id):
        raise TaskConflict('Amendment rule wait lacks original independent disposition profile')
    if window_wait:
        window_ref = rule.action_window_refs.get(profile.choice)
        if window_ref is None or window_ref.key() != refs[1].key() or not isinstance(reading.resolve(window_ref), TimeWindow):
            raise TaskConflict('Amendment window wait substitutes the original selected choice window')
    bid = reading.resolve(profile.bid_ref)
    if (not isinstance(bid, ContractorAmendmentBidView) or bid.ref.key() != profile.bid_ref.key()
            or bid.organization_id != reading.organization_id or bid.draft.package_ref.key() != rule.prior_package_ref.key()
            or bid.round_ref.key() != rule.prior_round_ref.key()):
        raise TaskConflict('Amendment rule wait changes the original bid/package/round')
    return rule, profile, bid


def _read_original_expired_bid(reading, refs):
    if len(refs) != 2 or refs[0].kind != 'Bid' or refs[1].kind != 'TimeWindow':
        raise TaskConflict('Expired bid wait requires its exact original bid and validity window')
    bid = reading.resolve(refs[0])
    window = reading.resolve(refs[1])
    if (not isinstance(bid, ContractorAmendmentBidView) or bid.ref.key() != refs[0].key()
            or bid.organization_id != reading.organization_id or bid.draft.validity_ref.key() != refs[1].key()
            or not isinstance(window, TimeWindow)):
        raise TaskConflict('Expired bid wait substitutes original bid content or validity window')
    return bid, window


def _read_original_late_answer_bid(reading, refs):
    if len(refs) != 2 or refs[0].kind != 'ClarificationRequest' or refs[1].kind != 'TenderAmendmentRule':
        raise TaskConflict('Late answer wait requires its exact original question and amendment rule')
    question, rule = reading.resolve(refs[0]), reading.resolve(refs[1])
    if (not isinstance(question, ContractorAmendmentQuestionView) or question.ref.key() != refs[0].key()
            or not isinstance(rule, ContractorAmendmentRuleView) or rule.ref.key() != refs[1].key()):
        raise TaskConflict('Late answer wait substitutes original question or rule schema')
    original, profile, bid = _read_original_amendment_rule_bid(reading, [rule.ref, rule.disposition_basis_ref])
    if (profile.choice != 'explain' or question.organization_id != reading.organization_id
            or question.bid_ref.key() != bid.ref.key() or question.package_ref.key() != rule.current_package_ref.key()
            or question.round_ref.key() != rule.current_round_ref.key()
            or sum(answer.question_ref.key() == question.ref.key() for answer in profile.answers) != 1
            or not isinstance(reading.resolve(question.answer_window_ref), TimeWindow)):
        raise TaskConflict('Late answer wait changes original explained bid, question, package/round or answer window')
    return question, original, profile, bid


def contractor_original_expired_bid_profile(read_current, validate_relation):
    """Permit fresh A03 disposition without renewing an expired bid implicitly.

    The original bid draft, command and reservations stay fixed. Maintain can
    wake only when the exact original validity window is current and explicitly
    permitted. Other choices require their own actual rule/window evidence;
    all detailed amendment checks and effective receipts remain independent.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Expired bid disposition requires actual sources and independent native validation')
    code = 'original_expired_bid_disposition'

    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != 'CONTRACTOR-A03' or source['role'] != 'Contractor' or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'event'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Expired bid wait changes original action, condition or recipient')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, ContractorAmendmentCommandConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.rule_ref, Reference) or not isinstance(selected.bid_ref, Reference)
                or not isinstance(selected.execution_ref, Reference) or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Expired bid disposition lacks typed current authorized sources')
        reading, context = selected.reading, selected.context.model_copy(deep=True)
        try:
            if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.id != 'CONTRACTOR-A03' or context.execution_mode != 'llm'
                    or reading._resolver.source_mode != 'formal' or context.business_time != check.signal.business_time
                    or context.operation_id == source['request_id']):
                raise TaskConflict('Expired bid wait substitutes current formal context')
            reading.check_method_context(context, 'CONTRACTOR-A03')
            bid, validity = _read_original_expired_bid(reading, check.condition.object_refs)
            rule = reading.resolve(selected.rule_ref)
            if (not isinstance(rule, ContractorAmendmentRuleView) or rule.ref.key() != selected.rule_ref.key()
                    or rule.organization_id != source['organization_id'] or rule.prior_package_ref.key() != bid.draft.package_ref.key()
                    or rule.prior_round_ref.key() != bid.round_ref.key()
                    or selected.action_input.get('amendment_rule_ref') != rule.ref.model_dump(mode='json')
                    or selected.action_input.get('package_ref') != rule.current_package_ref.model_dump(mode='json')
                    or selected.action_input.get('round_ref') != rule.current_round_ref.model_dump(mode='json')):
                raise TaskConflict('Expired bid disposition substitutes original package/round or current native rule')
            profile = reading.resolve(rule.profile_ref)
            if (not isinstance(profile, ContractorAmendmentProfileView) or profile.ref.key() != rule.profile_ref.key()
                    or profile.organization_id != source['organization_id'] or profile.bid_ref.key() != selected.bid_ref.key()
                    or selected.action_input.get('bid_ref') != selected.bid_ref.model_dump(mode='json')):
                raise TaskConflict('Expired bid choice substitutes current bid or independent profile')
            now = context.business_time
            for row in (rule, profile):
                if (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                        or not row.effective_window.contains(now)):
                    return 'unavailable'
            if rule.notice_received_at.clock_ref != now.clock_ref or rule.notice_received_at.offset > now.offset:
                return 'unavailable'
            if rule.dispositions.get(profile.choice) != 'allowed':
                return 'waiting'
            window_ref = rule.action_window_refs.get(profile.choice)
            if window_ref is None:
                return 'unavailable'
            window = reading.resolve(window_ref)
            if not isinstance(window, TimeWindow) or not window.contains(now):
                return 'unavailable'
            if profile.choice == 'maintain' and (not rule.maintain_prior_version_allowed or not validity.contains(now)):
                return 'waiting'
            original_execution = reading.resolve(bid.submission_ref)
            current_execution = reading.resolve(selected.execution_ref)
            if (not isinstance(original_execution, ContractorAmendmentSubmissionView)
                    or not isinstance(current_execution, ContractorAmendmentSubmissionView)):
                raise TaskConflict('Expired bid wait lacks actual original command results')
            if current_execution.status in {'rejected', 'not_submitted'} and profile.choice != 'withdraw':
                return 'waiting'
            observed = {}
            for ref in [rule.disposition_basis_ref, *rule.evidence_refs, *profile.evidence_refs]:
                evidence = reading.resolve(ref)
                if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed'):
                    raise TaskConflict('Expired bid disposition requires actual observed native permission evidence')
                if evidence.effective_window is not None and not evidence.effective_window.contains(now):
                    return 'unavailable'
                observed[evidence.ref.key()] = evidence.model_dump(mode='json')

            def validate_disposition(**query):
                return validate_relation(**query, original_bid_validity=validity.model_dump(mode='json'),
                    disposition_rule=rule.model_dump(mode='json'), disposition_profile=profile.model_dump(mode='json'),
                    disposition_window=window.model_dump(mode='json'), disposition_evidence=deepcopy(list(observed.values())))

            query = contractor_original_amendment_command_profile(original_execution.command_id, lambda _: selected, validate_disposition)
            condition = check.condition.model_copy(deep=True, update={'condition_code': query.condition_code,
                'object_refs': [bid.submission_ref.model_copy(deep=True), bid.ref.model_copy(deep=True)]})
            return query.evaluate(ConditionCheck(deepcopy(check.source), condition, check.signal.model_copy(deep=True)))
        finally:
            reading.recheck()

    return ConditionProfile('CONTRACTOR-A03', code, '1', frozenset({'event'}), evaluate)


def contractor_original_amendment_rule_disposition_profile(read_current, validate_relation):
    """Recheck a refused/pending template disposition without assuming permission."""
    return _contractor_original_amendment_rule_profile(read_current, validate_relation,
        code='original_procurement_disposition_change', window_wait=False)


def contractor_original_amendment_window_profile(read_current, validate_relation):
    """Recheck the original template window using actual current permission.

    A changed window must preserve its physical identity for the same choice,
    and native validation must authenticate its new version and clock. A newly
    selected disposition still needs its own explicit permitted window. No
    deadline extension, bid effectiveness or reservation release is inferred.
    """
    return _contractor_original_amendment_rule_profile(read_current, validate_relation,
        code='original_late_or_expired_submission_disposition', window_wait=True)


def contractor_original_late_answer_profile(read_current, validate_relation):
    """Recheck actual permission for the original late clarification answer.

    Preserve the exact question's content and original bid/command. An explain
    choice needs a current version of the same physical answer window and a
    complete explicit answer. Other dispositions keep their independent A03
    gates; no late acceptance or effective answer receipt is manufactured.
    """
    return _contractor_original_amendment_rule_profile(read_current, validate_relation,
        code='original_late_answer_disposition', window_wait=False, late_answer=True)


def _contractor_original_amendment_rule_profile(read_current, validate_relation, *, code, window_wait, late_answer=False):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Amendment rule disposition needs actual sources and independent native validation')

    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != 'CONTRACTOR-A03' or source['role'] != 'Contractor' or source['purpose'] != 'action'
                or check.condition.condition_code != code or check.condition.trigger != 'event'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Amendment template wait changes original action, recipient or condition')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, ContractorAmendmentCommandConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.rule_ref, Reference) or not isinstance(selected.execution_ref, Reference)
                or not isinstance(selected.bid_ref, Reference) or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Amendment template wait requires typed current rule, command and input')
        reading, context = selected.reading, selected.context.model_copy(deep=True)
        try:
            if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.id != 'CONTRACTOR-A03' or context.execution_mode != 'llm'
                    or reading._resolver.source_mode != 'formal' or context.business_time != check.signal.business_time
                    or context.operation_id == source['request_id']):
                raise TaskConflict('Amendment template wait substitutes current formal context or recipient')
            reading.check_method_context(context, 'CONTRACTOR-A03')
            old_question = None
            if late_answer:
                old_question, original, old_profile, old_bid = _read_original_late_answer_bid(reading, check.condition.object_refs)
            else:
                original, old_profile, old_bid = _read_original_amendment_rule_bid(
                    reading, check.condition.object_refs, window_wait=window_wait)
            current = reading.resolve(selected.rule_ref)
            if (not isinstance(current, ContractorAmendmentRuleView) or current.ref.key() != selected.rule_ref.key()
                    or (current.ref.kind, current.ref.id) != (original.ref.kind, original.ref.id)
                    or any(getattr(original, field) != getattr(current, field) for field in (
                        'organization_id', 'prior_package_ref', 'current_package_ref', 'prior_round_ref', 'current_round_ref', 'scope'))
                    or (current.profile_ref.kind, current.profile_ref.id) != (original.profile_ref.kind, original.profile_ref.id)
                    or old_profile.choice not in original.action_window_refs
                    or original.dispositions.get(old_profile.choice) not in (
                        {'allowed'} if window_wait or late_answer else {'refused', 'pending'})
                    or selected.action_input.get('amendment_rule_ref') != current.ref.model_dump(mode='json')
                    or selected.action_input.get('package_ref') != current.current_package_ref.model_dump(mode='json')
                    or selected.action_input.get('round_ref') != current.current_round_ref.model_dump(mode='json')):
                raise TaskConflict('Amendment template wait substitutes original rule/package/round or independent profile')
            profile = reading.resolve(current.profile_ref)
            if (not isinstance(profile, ContractorAmendmentProfileView) or profile.ref.key() != current.profile_ref.key()
                    or profile.organization_id != source['organization_id'] or profile.bid_ref.key() != selected.bid_ref.key()
                    or selected.action_input.get('bid_ref') != selected.bid_ref.model_dump(mode='json')):
                raise TaskConflict('Amendment template choice substitutes current bid or organization')
            question = None
            answer_window = old_answer_window = None
            if late_answer:
                refs = [Reference.model_validate(raw) for raw in selected.action_input.get('clarification_refs', [])]
                matching = [ref for ref in refs if (ref.kind, ref.id) == (old_question.ref.kind, old_question.ref.id)]
                if len(matching) != 1:
                    raise TaskConflict('Late answer disposition must retain its original question exactly once')
                question = reading.resolve(matching[0])
                if (not isinstance(question, ContractorAmendmentQuestionView) or question.ref.key() != matching[0].key()
                        or any(getattr(question, field) != getattr(old_question, field) for field in (
                            'organization_id', 'package_ref', 'round_ref', 'requires_revision', 'requirement_refs', 'scope'))
                        or question.bid_ref.key() != selected.bid_ref.key()
                        or (question.answer_window_ref.kind, question.answer_window_ref.id)
                            != (old_question.answer_window_ref.kind, old_question.answer_window_ref.id)):
                    raise TaskConflict('Late answer disposition changes original question content, bid or physical answer window')
                old_answer_window = reading.resolve(old_question.answer_window_ref)
                answer_window = reading.resolve(question.answer_window_ref)
                if (not isinstance(answer_window, TimeWindow)
                        or answer_window.start.clock_ref != old_answer_window.start.clock_ref):
                    raise TaskConflict('Late answer disposition substitutes the original business clock')
            now = context.business_time
            for row in ((current, profile, question) if question is not None else (current, profile)):
                if (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                        or not row.effective_window.contains(now)):
                    return 'unavailable'
            if current.notice_received_at.clock_ref != now.clock_ref or current.notice_received_at.offset > now.offset:
                return 'unavailable'
            if current.dispositions.get(profile.choice) != 'allowed':
                return 'waiting'
            window_ref = current.action_window_refs.get(profile.choice)
            if window_ref is None:
                return 'unavailable'
            window = reading.resolve(window_ref)
            if not isinstance(window, TimeWindow) or not window.contains(now):
                return 'unavailable'
            if late_answer and profile.choice == 'explain':
                answers = [answer for answer in profile.answers if answer.question_ref.key() == question.ref.key()]
                if (not answer_window.contains(now) or question.requires_revision or len(answers) != 1
                        or not answers[0].answer.strip() or answers[0].changed_requirement_refs):
                    return 'waiting'
            original_window = None
            if window_wait:
                old_window_ref = check.condition.object_refs[1]
                original_window = reading.resolve(old_window_ref)
                if (window.start.clock_ref != original_window.start.clock_ref
                        or profile.choice == old_profile.choice
                            and (window_ref.kind, window_ref.id) != (old_window_ref.kind, old_window_ref.id)):
                    raise TaskConflict('Amendment window update substitutes original physical window or business clock')
            execution = reading.resolve(selected.execution_ref)
            original_execution = reading.resolve(old_bid.submission_ref)
            if not isinstance(execution, ContractorAmendmentSubmissionView) or not isinstance(original_execution, ContractorAmendmentSubmissionView):
                raise TaskConflict('Amendment template wait lacks actual original command results')
            if execution.status in {'rejected', 'not_submitted'} and profile.choice != 'withdraw':
                return 'waiting'
            observations = {}
            for ref in [current.disposition_basis_ref, *current.evidence_refs, *profile.evidence_refs,
                    *(question.evidence_refs if question is not None else [])]:
                evidence = reading.resolve(ref)
                if (not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed'):
                    raise TaskConflict('Amendment template permission requires actual observed native evidence')
                if evidence.effective_window is not None and not evidence.effective_window.contains(now):
                    return 'unavailable'
                observations[evidence.ref.key()] = evidence.model_dump(mode='json')

            def validate_disposition(**query):
                window_evidence = ({'original_disposition_window': original_window.model_dump(mode='json')}
                    if original_window is not None else {})
                answer_evidence = ({'original_clarification': old_question.model_dump(mode='json'),
                    'current_clarification': question.model_dump(mode='json'),
                    'original_answer_window': old_answer_window.model_dump(mode='json'),
                    'current_answer_window': answer_window.model_dump(mode='json')}
                    if late_answer else {})
                return validate_relation(**query, original_disposition_rule=original.model_dump(mode='json'),
                    original_disposition_profile=old_profile.model_dump(mode='json'),
                    disposition_rule=current.model_dump(mode='json'), disposition_profile=profile.model_dump(mode='json'),
                    disposition_window=window.model_dump(mode='json'), disposition_evidence=deepcopy(list(observations.values())),
                    **window_evidence, **answer_evidence)

            query = contractor_original_amendment_command_profile(original_execution.command_id, lambda _: selected, validate_disposition)
            condition = check.condition.model_copy(deep=True, update={'condition_code': query.condition_code,
                'object_refs': [old_bid.submission_ref.model_copy(deep=True), old_bid.ref.model_copy(deep=True)]})
            return query.evaluate(ConditionCheck(deepcopy(check.source), condition, check.signal.model_copy(deep=True)))
        finally:
            reading.recheck()

    return ConditionProfile('CONTRACTOR-A03', code, '1', frozenset({'event'}), evaluate)
