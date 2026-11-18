"""CONTRACTOR-A03 versioned proposals; submission/release are host operations."""
from src.actions.contracts.common import EvidenceRecord, TimeWindow
from src.actions.contracts.contractor_amendment_objects import (
    ContractorAmendmentBidView, ContractorAmendmentRoundView,
    ContractorAmendmentRuleView, ContractorAmendmentProfileView,
    ContractorAmendmentQuestionView, ContractorAmendmentSubmissionView,
    ContractorAmendmentReservationView, ContractorSavedBidDraft,
)
from src.actions.contracts.contractor_bid_objects import ContractorBidPackageView, ContractorBidReferenceView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.contractor_bid import prepare_bid
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def amend_bid(context, action_input, reading):
    now = context.business_time

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('contractor-amendment-clock-alignment')

    def read(ref, schema, *, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'contractor-amendment-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(row.scope, context.scope):
            raise ValueError('Amendment input leaves original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_amendment_input', [ref])
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now):
                _needs('current_original_amendment_input', [ref])
        for basis in getattr(row, 'evidence_refs', []): evidence(basis, historical=historical)
        return row

    def evidence(ref, *, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, EvidenceRecord): _unsupported('contractor-amendment-evidence-schema')
        if row.effective_window is not None:
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now):
                _needs('current_original_amendment_evidence', [ref])

    def window(ref):
        row = read(ref, TimeWindow); clock(row.start); return row

    def deferred(code, refs, condition):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
            'trigger': 'event', 'object_refs': refs, 'earliest_time': None, 'condition_code': condition}}

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    try:
        bid = read(action_input.bid_ref, ContractorAmendmentBidView, historical=True)
        if bid.organization_id != reading.organization_id or not scope_covers(bid.draft.scope_ref, context.scope):
            raise ValueError('Amendment targets another contractor or bid scope')
        execution = read(bid.submission_ref, ContractorAmendmentSubmissionView)
        if (execution.organization_id != reading.organization_id or not same(execution.bid_ref, bid.ref)
                or not same(execution.package_ref, bid.draft.package_ref) or not same(execution.round_ref, bid.round_ref)):
            raise ValueError('Original command identity does not belong to this bid version')
        evidence(execution.result_basis_ref)
        if execution.status in {'unknown', 'pending'}:
            return deferred('original_bid_submission_reconciliation_required', [execution.ref, bid.ref],
                            f'query_original_command:{execution.command_id}')
        if execution.status == 'failed':
            reading.recheck()
            return {'kind': 'technical_error', 'error': {'kind': 'unrecorded',
                    'correlation_id': execution.command_id, 'code': 'original_bid_submission_failed'},
                    'retryability': 'unknown'}
        package = read(action_input.package_ref, ContractorBidPackageView)
        tender_round = read(action_input.round_ref, ContractorAmendmentRoundView)
        rule = read(action_input.amendment_rule_ref, ContractorAmendmentRuleView)
        if (not same(package.round_ref, tender_round.ref)
                or not same(tender_round.package_ref, package.ref)
                or not same(tender_round.current_package_ref, package.ref)
                or not same(tender_round.amendment_rule_ref, rule.ref)
                or not same(rule.prior_package_ref, bid.draft.package_ref)
                or not same(rule.current_package_ref, package.ref)
                or not same(rule.prior_round_ref, bid.round_ref)
                or not same(rule.current_round_ref, tender_round.ref)
                or rule.organization_id != reading.organization_id
                or reading.organization_id not in package.recipient_organization_ids
                or tender_round.organization_id not in {None, reading.organization_id}):
            raise ValueError('Amendment is not the original authorized package/round replacement')
        if not _known(tender_round.allowed, 'original_round_amendment_permission'):
            _needs('original_round_amendment_permission', [tender_round.ref])
        clock(rule.notice_received_at)
        if rule.notice_received_at.offset > now.offset:
            _needs('received_current_amendment_notice', [rule.ref])
        evidence(rule.disposition_basis_ref)
        profile = read(rule.profile_ref, ContractorAmendmentProfileView)
        if profile.organization_id != reading.organization_id or not same(profile.bid_ref, bid.ref):
            raise ValueError('Revision choice belongs to another organization or bid version')
        grant = read(profile.authority_ref, Authorization)
        function = read(context.function_ref, RoleAssignment)
        if (grant.actor_id != context.actor_id or grant.function_ref != context.function_ref
                or grant.organization_id != reading.organization_id or function.role != 'Contractor'
                or 'CONTRACTOR-A03' not in grant.action_ids
                or not any(scope_covers(scope, context.scope) for scope in grant.scopes)):
            raise ValueError('Revision lacks original independent actor/scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(now): _needs('current_original_amendment_authority')
        for ref in [*grant.basis_refs, *function.basis_refs]: evidence(ref)
        choice = profile.choice
        if execution.status in {'rejected', 'not_submitted'} and choice != 'withdraw':
            return deferred('original_bid_submission_not_effective', [execution.ref, bid.ref],
                            'original_procurement_disposition_required')
        if choice not in rule.dispositions or choice not in rule.action_window_refs:
            _needs('original_template_amendment_disposition_and_window', [rule.ref])
        disposition = rule.dispositions[choice]
        if disposition != 'allowed':
            return deferred(f'original_amendment_{disposition}', [rule.ref, rule.disposition_basis_ref],
                            'original_procurement_disposition_change')
        if not window(rule.action_window_refs[choice]).contains(now):
            return deferred('original_amendment_outside_template_window', [rule.ref, rule.action_window_refs[choice]],
                            'original_late_or_expired_submission_disposition')
        changed = keys(rule.changed_requirement_refs)
        acknowledged = keys(profile.acknowledged_requirement_refs)
        if not changed <= acknowledged: _needs('read_all_original_changed_requirements', rule.changed_requirement_refs)
        for ref in profile.acknowledged_requirement_refs:
            row = read(ref, ContractorBidReferenceView)
            if not same(row.package_ref, package.ref) or row.organization_id not in {None, reading.organization_id}:
                raise ValueError('Acknowledgement changes current package or contractor')
            if not _known(row.allowed, 'original_changed_requirement_use'):
                _needs('original_changed_requirement_use', [ref])
        keys(action_input.clarification_refs)
        questions = {}
        for ref in action_input.clarification_refs:
            row = read(ref, ContractorAmendmentQuestionView)
            if (row.organization_id != reading.organization_id or not same(row.bid_ref, bid.ref)
                    or not same(row.package_ref, package.ref) or not same(row.round_ref, tender_round.ref)):
                raise ValueError('Clarification targets another original bid/package/round')
            if not keys(row.requirement_refs) <= acknowledged:
                _needs('read_original_clarification_requirements', row.requirement_refs)
            questions[ref.key()] = row
        if keys(action_input.reservation_refs) != keys(bid.reservation_refs):
            _needs('complete_original_bid_temporary_reservations', bid.reservation_refs)
        for ref in action_input.reservation_refs:
            row = read(ref, ContractorAmendmentReservationView, historical=True)
            if (row.organization_id != reading.organization_id or not same(row.bid_ref, bid.ref)
                    or not same(row.round_ref, bid.round_ref) or row.reservation_kind != 'temporary_bid'
                    or row.contract_ref is not None or row.status == 'converted'):
                raise ValueError('Amendment cannot release another contract or converted reservation')
            evidence(row.release_basis_ref, historical=True)
        payload = {'choice': choice, 'prior_bid_ref': bid.ref, 'note': profile.note}
        if choice == 'explain':
            if changed or any(q.requires_revision for q in questions.values()):
                _needs('full_bid_revision_for_scope_or_price_changes')
            if not questions or keys([a.question_ref for a in profile.answers]) != set(questions):
                _needs('complete_original_clarification_answers', action_input.clarification_refs)
            for answer in profile.answers:
                if not answer.answer.strip() or answer.changed_requirement_refs:
                    _needs('explanation_without_hidden_bid_changes')
                if not window(questions[answer.question_ref.key()].answer_window_ref).contains(now):
                    return deferred('original_clarification_outside_template_window', [answer.question_ref, rule.ref],
                                    'original_late_answer_disposition')
                unique_refs(answer.evidence_refs)
                for ref in answer.evidence_refs: evidence(ref)
            payload['answers'] = [answer.model_dump(mode='python') for answer in profile.answers]
        elif choice == 'revise':
            pricing = profile.revision_input
            if pricing is None: _needs('complete_original_replacement_bid_inputs')
            if not same(pricing.package_ref, package.ref): raise ValueError('Replacement uses another package version')
            # Reuse the pure proposal validator with the real A03 reading context and author authority.
            result = prepare_bid(context, pricing, reading, profile_action_id='CONTRACTOR-A03')
            if result['kind'] != 'completed': return result
            if result['payload']['choice'] != 'submit_bid': _needs('complete_replacement_bid_not_decline')
            replacement = result['payload']['bid']
            if ContractorSavedBidDraft.model_validate(replacement) == bid.draft:
                _needs('actual_complete_bid_revision_or_maintain')
            payload.update(replacement_bid=replacement, changed_requirement_refs=rule.changed_requirement_refs)
        elif choice == 'maintain':
            if not rule.maintain_prior_version_allowed or any(q.requires_revision for q in questions.values()):
                _needs('original_permission_to_maintain_prior_bid_without_new_scope_commitment')
            if not window(bid.draft.validity_ref).contains(now):
                return deferred('prior_bid_expired', [bid.ref, bid.draft.validity_ref], 'original_expired_bid_disposition')
        # withdraw is only a proposal. Host releases these bid reservations after an effective receipt.
        reading.recheck()
        return {'kind': 'completed', 'payload': payload}
    except ObservationGap as gap:
        reading.recheck(); return gap.result
