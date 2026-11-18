"""OWN-A09 same-version procurement decisions with original rounds preserved."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, TimeWindow
from src.actions.contracts.owner_tender_objects import (
    OwnerTenderProcedureView, OwnerTenderProfileView, OwnerTenderPackageView, OwnerTenderRoundView,
    OwnerEligibleBidderView, OwnerTenderBidView, OwnerTenderFundingView, OwnerTenderSubmissionView,
    OwnerTenderReferenceView, OwnerTenderClarificationView, OwnerTenderTransitionView,
    OwnerTenderFundingCommitmentView, OwnerTenderNotificationView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.owner_tender import OWNER_TENDER_METHOD
from src.methods.qs_bid import BidRankInput
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def organize_tender(context, action_input, reading):
    scope, now, evidence_basis, sources = context.scope, context.business_time, {}, {}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('owner-tender-clock-alignment')

    def current(window, *, at=None):
        point = now if at is None else at
        clock(window.start); clock(point)
        if point.offset > now.offset: _needs('received_original_tender_author_time')
        if not window.contains(point):
            _needs('current_original_tender_source' if at is None else 'original_tender_source_valid_when_submitted')

    def evidence(refs, *, at=None):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('owner-tender-evidence-schema')
            if row.effective_window is not None: current(row.effective_window, at=at)
            evidence_basis[ref.key()] = row.ref

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'owner-tender-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(row.scope, scope):
            raise ValueError('Tender projection does not cover original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_tender_input', [ref])
            current(row.effective_window)
        evidence(getattr(row, 'evidence_refs', [])); sources[ref.key()] = ref
        return row

    def authority(ref, actor, function, action, roles, organization=None, *, at=None, target_scope=None):
        grant = read(ref, Authorization); assignment = read(function, RoleAssignment)
        if (grant.actor_id != actor or grant.function_ref != function or assignment.role not in roles
                or assignment.function_ref != function
                or (organization is not None and grant.organization_id != organization)
                or action not in grant.action_ids
                or not any(scope_covers(s, target_scope or scope) for s in grant.scopes)):
            raise ValueError('Tender author or owner lacks independent original authority')
        current(grant.validity, at=at)
        for basis_ref in [*grant.basis_refs, *assignment.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=at)
            else:
                reading.resolve(basis_ref); sources[basis_ref.key()] = basis_ref

    def own_authority(ref):
        authority(ref, context.actor_id, context.function_ref, 'OWN-A09', {'Owner'}, reading.organization_id)

    def rule(ref):
        row = read(ref, OwnerTenderReferenceView)
        if row.procedure_ref != procedure.ref: raise ValueError('Tender requirement changes original procedure')
        if not _known(row.permission, 'original_procurement_rule_permission'):
            _needs('original_procurement_rule_permission', [ref])
        return row

    def questions(rows, subjects):
        if not rows or len({r.local_key for r in rows}) != len(rows):
            raise ValueError('Tender questions require nonempty distinct local identities')
        keys = {ref.key() for ref in subjects}
        for question in rows:
            if question.subject_ref.key() not in keys: raise ValueError('Tender question changes original subject')
            reading.resolve(question.subject_ref)
            if question.issue_ref is not None: reading.resolve(question.issue_ref)
            unique_refs(question.requirement_refs)
            for ref in question.requirement_refs: rule(ref)
            evidence(question.evidence_refs)
        return rows

    def completed(choice, note, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'note': note, **fields}}

    def budget():
        funding = read(action_input.funding_ref, OwnerTenderFundingView)
        if funding.owner_organization_id != reading.organization_id: raise ValueError('Procurement funding belongs to another owner')
        own_authority(funding.authority_ref); clock(funding.as_of)
        if funding.as_of != now or funding.coverage != 'complete' or funding.kind != 'authorized_procurement_budget':
            _needs('current_complete_authorized_procurement_budget')
        limit = _known(funding.authorized_limit, 'authorized_procurement_budget_limit'); evidence([limit.basis_ref])
        amount = decimal_fraction(limit.value)
        if amount < 0: raise ValueError('Authorized procurement budget is negative')
        occupied = Fraction(); unique_refs([row.ref for row in funding.prior_commitments])
        for row in funding.prior_commitments:
            original = read(row.ref, OwnerTenderFundingCommitmentView)
            if (original.owner_organization_id != reading.organization_id or original.procedure_ref != procedure.ref
                    or original.amount != row.amount):
                raise ValueError('Funding occupancy changes original owner, procurement scope or committed amount')
            evidence([row.amount.basis_ref])
            if row.amount.currency != limit.currency: _unsupported('owner-tender-budget-currency-conversion')
            value = decimal_fraction(row.amount.value)
            if value < 0: raise ValueError('Prior procurement commitment is negative')
            occupied += value
        return limit.currency, max(Fraction(), amount - occupied)

    def invite_ids():
        selected = []
        for ref in profile.invitation_bidder_refs:
            row = bidders.get(ref.key())
            if row is None: raise ValueError('Invitation selects an undeclared bidder')
            if row.status != 'active': continue
            if not _known(row.invitation_permission, 'original_bidder_invitation_permission'): continue
            if not _known(row.eligibility, 'original_bidder_invitation_eligibility'): continue
            for ref in row.eligibility_rule_refs: rule(ref)
            selected.append(row.organization_id)
        if len(set(selected)) != len(selected): raise ValueError('Tender invites the same real organization twice')
        return selected

    def transition(choice):
        if profile.transition_ref is None: _needs('original_authorized_tender_transition')
        row = read(profile.transition_ref, OwnerTenderTransitionView); own_authority(row.authority_ref)
        if row.prior_package_ref != package.ref or row.operation != choice:
            raise ValueError('Tender transition changes original package or operation')
        unique_refs(row.replaced_round_refs)
        if not row.replaced_round_refs or not set(row.replaced_round_refs) <= set(action_input.round_refs):
            raise ValueError('Tender transition must cover nonempty declared original rounds')
        original = [rounds[ref.key()] for ref in row.replaced_round_refs]
        if row.relation != 'legal_parallel' and (not row.stop_accepting_bids or not row.stop_awards):
            raise ValueError('Replacement/continuation must explicitly stop original bid intake and award scope')
        if row.relation == 'legal_parallel':
            if row.parallel_permission_ref is None: _needs('original_legal_parallel_procurement_permission')
            rule(row.parallel_permission_ref)
        clock(row.effective_at)
        if row.effective_at.offset < now.offset: _needs('current_or_future_tender_transition_effective_time')
        pending = {ref for r in original for ref in r.pending_selection_refs}
        reserved = {ref for r in original for ref in r.reservation_refs}
        contracts = {ref for r in original for ref in r.established_contract_refs}
        if (set(row.pending_selection_refs) != pending or set(row.reservation_refs) != reserved
                or set(row.preserve_contract_refs) != contracts):
            raise ValueError('Tender transition omits original pending selection, reservation or established contract')
        for ref in [*row.pending_selection_refs, *row.reservation_refs, *row.preserve_contract_refs]: reading.resolve(ref)
        if row.reservation_handling == 'original_release_basis' and reserved and not row.release_basis_refs:
            _needs('independent_original_reservation_release_basis')
        for ref in row.release_basis_refs: rule(ref)
        rule(row.late_acceptance_rule_ref)
        all_bidders = {r.organization_id for r in bidders.values()}
        if not all_bidders <= set(row.notify_bidder_ids): _needs('complete_original_affected_bidder_notifications')
        notification = read(row.notification_plan_ref, OwnerTenderNotificationView); own_authority(notification.authority_ref)
        if (notification.package_ref != package.ref or set(notification.round_refs) != set(row.replaced_round_refs)
                or set(notification.recipient_ids) != set(row.notify_bidder_ids)):
            raise ValueError('Tender transition notification changes original package, affected rounds or recipients')
        if choice == 'cancel_round':
            if len(row.replaced_round_refs) != 1: raise ValueError('Cancellation must select one exact original round')
            return completed('cancel_round', 'Original-round cancellation decision only; old contracts/costs retained and late acceptance follows original rule',
                             round_ref=row.replaced_round_refs[0])
        draft = row.revision
        if draft is None or draft.prior_package_ref != package.ref or draft.scope_ref != scope:
            raise ValueError('Tender revision requires a complete new same-scope draft with original predecessor')
        if draft.evaluation_profile_ref != profile.ref: reading.resolve(draft.evaluation_profile_ref)
        unique_refs(draft.requirement_refs)
        if not draft.requirement_refs: _needs('complete_revised_procurement_requirements')
        for ref in draft.requirement_refs: rule(ref)
        evidence(draft.basis_refs)
        if not draft.basis_refs: _needs('original_tender_revision_basis')
        window = read(draft.submission_window_ref, TimeWindow); clock(window.start)
        if window.start.offset < now.offset: _needs('future_revised_tender_submission_window')
        return completed(choice, 'Complete revision/re-tender draft and original-round disposition; no old bid rollover, contract termination or reservation release',
                         package_draft=draft, replaced_round_refs=row.replaced_round_refs)

    try:
        for refs in (action_input.round_refs, action_input.bidder_refs, action_input.bid_refs): unique_refs(refs)
        profile = read(action_input.evaluation_profile_ref, OwnerTenderProfileView)
        if profile.owner_organization_id != reading.organization_id: raise ValueError('Tender profile belongs to another owner')
        authority(profile.author_authority_ref, profile.author_actor_id, profile.author_function_ref, 'OWN-A09', {'Owner'}, reading.organization_id)
        preparing = action_input.package_context.kind == 'preparation'
        package, rounds = None, {}
        if preparing:
            ctx = action_input.package_context
            if ctx.scope_ref != scope or profile.package_ref is not None or profile.procedure_ref != ctx.procedure_ref:
                raise ValueError('First publication changes original preparation scope/procedure or invents a package reference')
            if action_input.round_refs or action_input.bid_refs:
                raise ValueError('First publication cannot consume nonexistent new package rounds or bids')
            procedure = read(ctx.procedure_ref, OwnerTenderProcedureView)
        else:
            package = read(action_input.package_context.package_ref, OwnerTenderPackageView)
            if (package.owner_organization_id != reading.organization_id or package.owner_actor_id != context.actor_id
                    or package.evaluation_profile_ref != profile.ref or profile.package_ref != package.ref
                    or profile.procedure_ref != package.procedure_ref):
                raise ValueError('Published package/profile changes owner, procedure or original package version')
            own_authority(package.authority_ref)
            procedure = read(package.procedure_ref, OwnerTenderProcedureView)
            if set(package.round_refs) != set(action_input.round_refs) or set(package.bidder_refs) != set(action_input.bidder_refs):
                _needs('complete_original_package_rounds_and_visible_bidders')
            declared_bids = []
            for ref in action_input.round_refs:
                row = read(ref, OwnerTenderRoundView)
                if row.package_ref != package.ref or row.owner_organization_id != reading.organization_id or row.evaluation_profile_ref != profile.ref:
                    raise ValueError('Tender round changes original package, owner or evaluation rules')
                unique_refs(row.bid_refs); declared_bids.extend(row.bid_refs); rounds[ref.key()] = row
            unique_refs(declared_bids)
            if set(declared_bids) != set(action_input.bid_refs): _needs('complete_original_package_bid_set', declared_bids)
        if procedure.owner_organization_id != reading.organization_id or procedure.evaluation_profile_ref != profile.ref:
            raise ValueError('Procurement procedure changes original owner or evaluation profile')
        own_authority(procedure.authority_ref)
        bidders = {ref.key(): read(ref, OwnerEligibleBidderView) for ref in action_input.bidder_refs}
        bids = {}
        for ref in action_input.bid_refs:
            row = read(ref, OwnerTenderBidView)
            bidder = bidders.get(row.bidder_ref.key())
            if (bidder is None or row.bidder_organization_id != bidder.organization_id or row.author_actor_id != bidder.actor_id
                    or row.author_function_ref != bidder.function_ref or row.package_ref != package.ref
                    or row.round_ref.key() not in rounds or ref not in rounds[row.round_ref.key()].bid_refs):
                raise ValueError('Bid changes original submitting organization, function, package or round')
            roles = {'Supplier'} if row.author_action_id == 'SUPPLIER-A03' else {'Contractor'}
            clock(row.submitted_at)
            if row.submitted_at.offset > row.available_at.offset: raise ValueError('Bid receipt precedes original submission')
            authority(row.author_authority_ref, row.author_actor_id, row.author_function_ref, row.author_action_id,
                      roles, row.bidder_organization_id, at=row.submitted_at, target_scope=row.scope)
            bids[ref.key()] = row
        for choice in profile.choice_order:
            if preparing:
                if choice != 'publish_package': continue
                ctx = action_input.package_context
                unique_refs(ctx.technical_submission_refs); unique_refs(ctx.requirement_refs)
                if (set(ctx.technical_submission_refs) != set(procedure.required_technical_submission_refs)
                        or set(ctx.requirement_refs) != set(procedure.requirement_refs)):
                    _needs('complete_original_first_publication_inputs')
                if not _known(procedure.publication_permission, 'original_owner_publication_permission'):
                    _needs('original_owner_publication_permission')
                for ref in ctx.technical_submission_refs:
                    row = read(ref, OwnerTenderSubmissionView)
                    role = read(row.author_function_ref, RoleAssignment).role
                    allowed = {'Architect': {'ARCHITECT-A07'}, 'Engineer': {'ENGINEER-A07'}, 'QS': {'QS-A05'}}
                    if row.author_action_id not in allowed.get(role, set()): _unsupported('owner-tender-technical-submission-author-action')
                    authority(row.author_authority_ref, row.author_actor_id, row.author_function_ref, row.author_action_id, {role})
                    if row.status not in {'submitted', 'accepted'} or 'procurement' not in row.allowed_uses or not _known(row.readiness, 'original_procurement_deliverable_readiness'):
                        _needs('submitted_authorized_procurement_deliverable')
                quantity = _known(ctx.quantity_basis, 'original_procurement_quantity_basis')
                if procedure.quantity_basis_ref is not None and quantity != procedure.quantity_basis_ref:
                    raise ValueError('First publication changes original declared quantity basis')
                rule(quantity)
                for ref in ctx.requirement_refs: rule(ref)
                window = read(procedure.submission_window_ref, TimeWindow); clock(window.start)
                if window.start.offset < now.offset: _needs('future_first_tender_submission_window')
                currency, allowance = budget()
                minimum = _known(procedure.minimum_authorized_budget, 'original_publication_minimum_budget_requirement')
                evidence([minimum.basis_ref])
                if minimum.currency != currency: _unsupported('owner-tender-publication-budget-currency-conversion')
                if decimal_fraction(minimum.value) < 0: raise ValueError('Publication budget requirement is negative')
                if allowance < decimal_fraction(minimum.value): _needs('authorized_funding_for_original_procurement_publication')
                selected = invite_ids()
                if procedure.publication_mode == 'invitation' and not selected: _needs('nonempty_authorized_tender_invitation_set')
                return completed('publish_package', 'First-publication draft only; core assigns package/round identities and sends authorized notices',
                    package={'scope_ref': scope, 'technical_submission_refs': ctx.technical_submission_refs,
                        'quantity_basis_ref': quantity, 'procedure_ref': procedure.ref, 'requirement_refs': ctx.requirement_refs,
                        'submission_window_ref': procedure.submission_window_ref, 'evaluation_profile_ref': profile.ref}, bidder_ids=selected)
            if choice == 'publish_package': continue
            if choice in {'revise_package', 'retender', 'cancel_round'}: return transition(choice)
            if package.status != 'published': continue
            if choice == 'invite':
                selected = invite_ids()
                if not selected: continue
                if not any(row.status == 'open' and row.accepts_new_bids for row in rounds.values()):
                    _needs('original_round_open_for_invitation')
                return completed('invite', 'Original authorized invitations only; no bidder acceptance or contract', bidder_ids=selected)
            if choice == 'clarify':
                if profile.clarification_ref is None: continue
                clarification = read(profile.clarification_ref, OwnerTenderClarificationView)
                if clarification.package_ref != package.ref or not clarification.request_refs:
                    raise ValueError('Tender clarification changes original package or lacks original requests')
                if (clarification.contains_competitor_private_data
                        or not set(clarification.actual_recipient_ids) <= set(clarification.permitted_recipient_ids)):
                    _needs('authorized_fair_tender_clarification_without_private_competitor_data')
                disclosure = rule(clarification.publication_rule_ref)
                if (not clarification.actual_recipient_ids
                        or not set(clarification.actual_recipient_ids) <= set(disclosure.allowed_recipient_ids)
                        or not set(disclosure.required_public_recipient_ids) <= set(clarification.actual_recipient_ids)):
                    _needs('original_rule_authorized_and_complete_clarification_recipients')
                for ref in clarification.request_refs: rule(ref)
                target = {'kind': 'package', 'package_ref': package.ref, 'request_refs': clarification.request_refs}
                subjects = [package.ref]
                if clarification.bid_ref is not None:
                    if clarification.bid_ref.key() not in bids: raise ValueError('Tender clarification borrows an undeclared bid')
                    target = {'kind': 'bid', 'bid_ref': clarification.bid_ref, 'request_refs': clarification.request_refs}
                    subjects = [clarification.bid_ref]
                return completed('clarify', 'Original-rule clarification response only; no price/terms changes or private competitor disclosure',
                                 target=target, responses=questions(clarification.responses, [*subjects, *clarification.request_refs]))
            if choice in {'evaluate', 'negotiate'}:
                if profile.selected_round_ref is None or profile.selected_round_ref.key() not in rounds:
                    _needs('explicit_original_selected_tender_round')
                round_view = rounds[profile.selected_round_ref.key()]
                if round_view.status != 'closed_for_bids' or not round_view.accepts_awards:
                    _needs('original_round_ready_for_evaluation_or_negotiation')
                currency, allowance = budget()
                eligible, rejected, comparison_rows, unknown = [], [], [], []
                for ref in round_view.bid_refs:
                    bid = bids[ref.key()]; bidder = bidders[bid.bidder_ref.key()]
                    if bidder.eligibility.state != 'known' or bid.compliance.state != 'known':
                        unknown.append(ref); continue
                    for requirement in [*bidder.eligibility_rule_refs, *bid.compliance_rule_refs]: rule(requirement)
                    if not bidder.eligibility.value or not bid.compliance.value or bid.status == 'withdrawn' or bidder.status == 'withdrawn':
                        if not bidder.eligibility_rule_refs or not bid.compliance_rule_refs:
                            _needs('original_bid_exclusion_rule_and_evidence', [ref])
                        rejected.append(ref); continue
                    price = _known(bid.total_price, 'original_submitted_tender_total'); evidence([price.basis_ref])
                    if price.currency != currency: _unsupported('owner-tender-price-budget-currency-conversion')
                    if decimal_fraction(price.value) < 0: raise ValueError('Bid price is negative')
                    if decimal_fraction(price.value) > allowance:
                        rejected.append(ref); continue
                    rule(bid.pricing_basis_ref)
                    risk = None
                    if any(row.metric == 'risk' for row in profile.criteria):
                        risk = _known(bid.risk, 'original_selected_tender_risk'); evidence([risk.basis_ref])
                    eligible.append(ref); comparison_rows.append({'bid_ref': ref, 'price': price, 'risk': risk})
                if unknown: _needs('original_bid_eligibility_and_compliance', unknown)
                if choice == 'negotiate':
                    if profile.negotiation_bid_ref not in eligible: continue
                    return completed('negotiate', 'Original-bid negotiation request; original terms remain until independent valid acceptance',
                        bid_ref=profile.negotiation_bid_ref, questions=questions(profile.negotiation_questions, [profile.negotiation_bid_ref]))
                if len({bids[ref.key()].pricing_basis_ref.key() for ref in eligible}) > 1:
                    _needs('same_original_comparison_price_basis_or_sourced_normalization')
                ranked = []
                if eligible:
                    if not profile.criteria: _needs('explicit_original_tender_comparison_criteria')
                    for criterion in profile.criteria: evidence([criterion.basis_ref])
                    result = reading.calculate(OWNER_TENDER_METHOD, BidRankInput(criteria=profile.criteria,
                        bids=comparison_rows, source_refs=list(sources.values())))
                    if result.kind != 'ok':
                        if result.kind == 'invalid_input': _unsupported('owner-tender-ranking-domain')
                        raw = result.model_dump(mode='python')
                        if result.kind == 'needs_information': raw['requested_refs'] = []
                        raise ObservationGap(raw)
                    ranked = [ref for group in result.value.ranked_groups for ref in group]
                return completed('evaluate', 'Same-round evaluation; equal score groups retain no strict preference; zero/all-rejected bids allowed; no award or acceptance',
                    ranked_bid_refs=ranked, rejected_bid_refs=rejected, evidence_refs=list(evidence_basis.values()))
        _needs('eligible_original_owner_tender_choice')
    except ObservationGap as gap:
        reading.recheck(); return gap.result
