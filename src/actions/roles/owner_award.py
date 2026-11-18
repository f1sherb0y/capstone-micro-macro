"""OWN-A10 expresses owner acceptance; formal relationship is a host transaction."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.owner_award_objects import (
    OwnerAwardRoundView, OwnerAwardOfferView, OwnerAwardTermsView, OwnerAwardAcceptanceView,
    OwnerAwardConditionView, OwnerAwardPolicyView, OwnerAwardSnapshotView, OwnerAwardCommitmentView,
    OwnerAwardAllocationView, OwnerAwardReferenceView, OwnerAwardTemplateView, award_agreement_digest,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def decide_award(context, action_input, reading):
    scope, now, sources = context.scope, context.business_time, {}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('owner-award-clock-alignment')

    def current(window, at=now):
        clock(window.start); clock(at)
        if at.offset > now.offset: _needs('received_original_award_author_time')
        return window.contains(at)

    def evidence(refs, *, at=now):
        clock(at)
        if at.offset > now.offset: _needs('received_original_award_evidence_time')
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('owner-award-evidence-schema')
            if row.effective_window is not None and not current(row.effective_window, at):
                _needs('original_award_evidence_valid_at_use', [ref])
            sources[ref.key()] = ref

    def read(ref, schema, active=True, covered=True, *, evidence_at_field=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'owner-award-projection:{ref.kind}')
        if covered and hasattr(row, 'scope') and not scope_covers(row.scope, scope):
            raise ValueError('Award projection changes original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_award_input', [ref])
            if active and not current(row.effective_window): _needs('current_original_award_input', [ref])
        point = now if evidence_at_field is None else getattr(row, evidence_at_field)
        clock(point)
        if point.offset > now.offset: _needs('received_original_award_evidence_time', [ref])
        if evidence_at_field is not None and point.offset > row.available_at.offset:
            raise ValueError('Award source receipt precedes its original decision')
        evidence(getattr(row, 'evidence_refs', []), at=point); sources[ref.key()] = ref; return row

    def authority(ref, actor, function, action, roles, organization, at=now, *, target_scope=None):
        grant = read(ref, Authorization); assignment = read(function, RoleAssignment)
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or assignment.function_ref != function or assignment.role not in roles or action not in grant.action_ids
                or not any(scope_covers(s, target_scope or scope) for s in grant.scopes)):
            raise ValueError('Award party lacks original independent legal organization/function authority')
        if not current(grant.validity, at): _needs('valid_original_award_authority', [ref])
        for basis_ref in [*grant.basis_refs, *assignment.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=at)
            else:
                reading.resolve(basis_ref); sources[basis_ref.key()] = basis_ref

    def own_authority(ref, *, target_scope=None):
        authority(ref, context.actor_id, context.function_ref, 'OWN-A10', {'Owner'}, reading.organization_id,
                  target_scope=target_scope)

    def completed(choice, note, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'note': note, **fields}}

    def reference(ref):
        row = read(ref, OwnerAwardReferenceView)
        if row.offer_ref != offer.ref or row.terms_ref != terms.ref:
            raise ValueError('Award template/clause/change points to another offer or terms version')
        if not _known(row.permission, 'original_award_reference_permission'): _needs('original_award_reference_permission')
        return row

    def condition(ref):
        row = read(ref, OwnerAwardConditionView)
        if row.offer_ref != offer.ref or row.terms_ref != terms.ref: raise ValueError('Award condition changes original agreement')
        assignment = read(row.verifier_function_ref, RoleAssignment)
        verifier = read(row.verifier_authority_ref, Authorization)
        authority(row.verifier_authority_ref, row.verifier_actor_id, row.verifier_function_ref,
                  row.verifier_action_id, {assignment.role}, verifier.organization_id, target_scope=row.scope)
        return row

    try:
        own_authority(action_input.authority_ref)
        round_view = read(action_input.round_ref, OwnerAwardRoundView)
        offer = read(action_input.selected_offer_ref, OwnerAwardOfferView, active=False)
        terms = read(action_input.final_terms_ref, OwnerAwardTermsView, active=False)
        snapshot = read(action_input.commitment_snapshot_ref, OwnerAwardSnapshotView)
        profile = read(snapshot.formation_profile_ref, OwnerAwardPolicyView)
        if (round_view.owner_organization_id != reading.organization_id or offer.owner_organization_id != reading.organization_id
                or offer.round_ref != round_view.ref or offer.package_ref != round_view.package_ref
                or offer.ref not in round_view.offer_refs or terms.offer_ref != offer.ref or terms.round_ref != round_view.ref
                or terms.ref != offer.final_terms_ref or terms.owner_organization_id != reading.organization_id
                or terms.counterparty_organization_id != offer.counterparty_organization_id
                or snapshot.organization_id != reading.organization_id or profile.owner_organization_id != reading.organization_id
                or profile.offer_ref != offer.ref or profile.terms_ref != terms.ref):
            raise ValueError('Award changes original selected offer, round, parties, final terms or owner snapshot')
        own_authority(action_input.authority_ref, target_scope=terms.scope)
        own_authority(snapshot.authority_ref, target_scope=terms.scope)
        own_authority(profile.authority_ref, target_scope=terms.scope)
        if len(set(profile.choice_order)) != len(profile.choice_order): raise ValueError('Award policy repeats a choice')
        counterparty_roles = {'Supplier'} if offer.author_action_id.startswith('SUPPLIER-') else {'Contractor'}
        authority(offer.author_authority_ref, offer.author_actor_id, offer.author_function_ref,
                  offer.author_action_id, counterparty_roles, offer.counterparty_organization_id, offer.available_at,
                  target_scope=offer.scope)
        terms_role = read(terms.author_function_ref, RoleAssignment).role
        if terms_role == 'Owner':
            if terms.author_action_id != 'OWN-A10': raise ValueError('Final owner terms lack original award authority')
            terms_org = reading.organization_id
        elif terms_role in counterparty_roles:
            if terms.author_action_id not in {'CONTRACTOR-A02', 'CONTRACTOR-A03', 'CONTRACTOR-A04', 'SUPPLIER-A03', 'SUPPLIER-A04'}:
                raise ValueError('Final counterparty terms lack original independent negotiating authority')
            terms_org = offer.counterparty_organization_id
        else: raise ValueError('Final terms author does not represent either real party')
        authority(terms.author_authority_ref, terms.author_actor_id, terms.author_function_ref, terms.author_action_id,
                  {terms_role}, terms_org, terms.available_at, target_scope=terms.scope)
        if (len(set(terms.required_party_ids)) != len(terms.required_party_ids)
                or set(terms.required_party_ids) != {reading.organization_id, offer.counterparty_organization_id}
                or offer.counterparty_organization_id == reading.organization_id):
            raise ValueError('Award requires two distinct actual parties, without duplicated or invented acceptors')
        unique_refs(terms.clause_refs); unique_refs(terms.condition_refs); unique_refs(offer.condition_refs)
        if set(offer.condition_refs) != set(terms.condition_refs): raise ValueError('Final terms silently remove or change original offer conditions')
        if len(set(terms.scope_keys)) != len(terms.scope_keys): raise ValueError('Award repeats original procurement coverage')
        template = read(terms.contract_template_ref, OwnerAwardTemplateView)
        if (template.offer_ref != offer.ref or template.terms_ref != terms.ref
                or template.required_stage != terms.stage or not _known(template.permission, 'original_award_template_permission')):
            raise ValueError('Original contract template does not authorize these offer/terms/stage')
        if not set(template.required_condition_refs) <= set(terms.condition_refs):
            raise ValueError('Final terms omit original formation-template conditions')
        if not set(template.required_owner_resource_kinds) <= {d.resource_kind for d in terms.owner_resource_demands}:
            _needs('complete_original_owner_management_and_resource_demand')
        if template.counterparty_capacity_required and snapshot.counterparty_capacity_condition_ref is None:
            _needs('original_counterparty_capacity_formation_condition')
        for ref in terms.clause_refs: reference(ref)
        conditions = [condition(ref) for ref in terms.condition_refs]
        acceptance_state, accepted, digest = {}, set(), award_agreement_digest(terms)
        unique_refs(action_input.party_acceptance_refs)
        for ref in action_input.party_acceptance_refs:
            row = read(ref, OwnerAwardAcceptanceView, active=False, evidence_at_field='decided_at')
            if row.run_id != context.run_id or row.party_id not in terms.required_party_ids:
                raise ValueError('Party acceptance belongs to another run or legal party')
            clock(row.decided_at)
            if row.decided_at.offset > row.available_at.offset: raise ValueError('Party acceptance receipt precedes decision')
            role = read(row.author_function_ref, RoleAssignment).role
            required_roles = {'Owner'} if row.party_id == reading.organization_id else counterparty_roles
            if role not in required_roles: raise ValueError('Acceptance author does not hold the actual party signing role')
            allowed = {'Owner': {'OWN-A10'}, 'Contractor': {'CONTRACTOR-A04'}, 'Supplier': {'SUPPLIER-A04'}}
            if row.author_action_id not in allowed.get(role, set()): raise ValueError('Party acceptance has no independent signing action')
            authority(row.author_authority_ref, row.author_actor_id, row.author_function_ref, row.author_action_id,
                      {role}, row.party_id, row.decided_at, target_scope=row.scope)
            matches = (row.offer_ref == offer.ref and row.round_ref == round_view.ref and row.terms_ref == terms.ref
                       and row.agreement_sha256 == digest and row.scope == terms.scope)
            if row.status != 'active' or not current(row.effective_window) or not matches: continue
            if row.party_id in acceptance_state: raise ValueError('Award repeats an active acceptance for one actual party')
            acceptance_state[row.party_id] = row.choice
            if row.choice == 'accept': accepted.add(row.party_id)
        for choice in profile.choice_order:
            if choice == 'reject': return completed('reject', profile.reject_reason)
            if choice == 'revise':
                unique_refs(profile.requested_change_refs)
                if not profile.requested_change_refs: continue
                for ref in profile.requested_change_refs: reference(ref)
                return completed('revise', 'Original agreement revision request only; original effective obligations remain',
                                 requested_change_refs=profile.requested_change_refs)
            if offer.status != 'offered' or not current(offer.effective_window) or not current(terms.effective_window):
                return completed('reject', 'Selected original offer is withdrawn, superseded or no longer effective; no accepted fields or new commitments')
            if round_view.status not in {'closed_for_bids', 'awarded'} or not round_view.accepts_awards:
                _needs('original_round_still_authorized_for_award')
            if acceptance_state.get(offer.counterparty_organization_id) in {'reject', 'revise'}:
                return completed('reject', 'Counterparty rejected or requested revision of these exact terms; no formation or commitment')
            clock(snapshot.as_of)
            if snapshot.as_of != now or snapshot.coverage != 'complete': _needs('complete_current_original_owner_commitments')
            price = terms.total_price; evidence([price.basis_ref])
            if decimal_fraction(price.value) < 0: raise ValueError('Final agreement price is negative')
            budget = _known(snapshot.authorized_budget, 'current_authorized_owner_award_budget'); evidence([budget.basis_ref])
            if budget.currency != price.currency: _unsupported('owner-award-budget-currency-conversion')
            if decimal_fraction(budget.value) < 0: raise ValueError('Authorized award budget is negative')
            spent = Fraction(); unique_refs([row.ref for row in snapshot.funding_uses])
            for use in snapshot.funding_uses:
                original = read(use.ref, OwnerAwardCommitmentView, covered=False)
                if original.owner_organization_id != reading.organization_id or original.amount != use.amount:
                    raise ValueError('Owner funding occupancy changes original identity or committed amount')
                evidence([use.amount.basis_ref])
                if use.amount.currency != price.currency: _unsupported('owner-award-prior-commitment-currency')
                if decimal_fraction(use.amount.value) < 0: raise ValueError('Prior owner funding commitment is negative')
                spent += decimal_fraction(use.amount.value)
            if decimal_fraction(price.value) > decimal_fraction(budget.value) - spent:
                continue
            unique_refs(snapshot.allocation_refs)
            for ref in snapshot.allocation_refs:
                allocation = read(ref, OwnerAwardAllocationView, covered=False)
                if allocation.owner_organization_id != reading.organization_id:
                    raise ValueError('Award allocation belongs to another owner')
                reading.resolve(allocation.contract_ref)
                if allocation.status == 'released':
                    if allocation.release_basis_ref is None: _needs('independent_original_contract_allocation_release_basis')
                    release = condition(allocation.release_basis_ref)
                    if release.verification.state != 'known' or not release.verification.value:
                        _needs('verified_independent_original_allocation_release')
                elif set(allocation.scope_keys) & set(terms.scope_keys):
                    _needs('original_scope_not_already_committed_or_valid_partial_allocation')
            clock(terms.work_window.start)
            if terms.work_window.start.offset < now.offset: _needs('current_or_future_original_contract_work_window')
            for resource in snapshot.resources: evidence([resource.total.basis_ref])
            for use in snapshot.resource_commitments:
                original = read(use.commitment_ref, OwnerAwardCommitmentView, covered=False)
                if (original.owner_organization_id != reading.organization_id or original.resource_ref is None
                        or original.resource_ref.key() != use.resource_ref.key() or original.quantity != use.quantity
                        or original.window != use.window):
                    raise ValueError('Original owner management/resource occupancy changed before award')
                evidence([use.quantity.basis_ref])
            if terms.owner_resource_demands:
                for demand in terms.owner_resource_demands: evidence(demand.basis_refs)
                result = reading.calculate(CAPACITY_METHOD, CapacityInput(clock_ref=now.clock_ref,
                    demands=terms.owner_resource_demands, resources=snapshot.resources,
                    commitments=snapshot.resource_commitments, source_refs=list(sources.values())))
                if result.kind != 'ok':
                    if result.kind == 'invalid_input': _unsupported('owner-award-resource-comparison-domain')
                    raw = result.model_dump(mode='python')
                    if result.kind == 'needs_information': raw['requested_refs'] = []
                    raise ObservationGap(raw)
                if not result.value.feasible: continue
            final_conditions = list(terms.condition_refs)
            if snapshot.counterparty_capacity_condition_ref is not None:
                condition(snapshot.counterparty_capacity_condition_ref); final_conditions.append(snapshot.counterparty_capacity_condition_ref)
            if offer.counterparty_organization_id not in accepted:
                if not profile.allow_owner_acceptance_pending_other_parties: _needs('independent_current_counterparty_acceptance')
                if not profile.pending_party_condition_refs: _needs('original_pending_counterparty_acceptance_condition')
                for ref in profile.pending_party_condition_refs:
                    if condition(ref).kind != 'counterparty_acceptance': raise ValueError('Pending-party requirement has another meaning')
                    final_conditions.append(ref)
            # Conditions are retained even if verified; host independently gates each formation stage.
            final_conditions = list({ref.key(): ref for ref in final_conditions}.values())
            return completed('accept', 'Owner acceptance only; exact party decisions, conditions, signatures and unchanged current commitments must be atomically rechecked by contract core',
                             offer_ref=offer.ref, terms_ref=terms.ref, condition_refs=final_conditions)
        _needs('authorized_award_with_available_budget_resources_or_original_revision')
    except ObservationGap as gap:
        reading.recheck(); return gap.result
