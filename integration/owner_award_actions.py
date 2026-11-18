"""Assemble original OWN-A10 inputs without forming contracts or commitments."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_award_objects import (
    OwnerAwardAcceptanceView, OwnerAwardAllocationView, OwnerAwardCommitmentView,
    OwnerAwardConditionView, OwnerAwardOfferView, OwnerAwardPolicyView,
    OwnerAwardReferenceView, OwnerAwardRoundView, OwnerAwardSnapshotView,
    OwnerAwardTermsView, owner_award_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.models import Authorization


@dataclass(frozen=True)
class PreparedOwnerAward(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A10'


class OwnerAwardActionAssembler(OwnerObservationActionAssembler):
    """Freeze exact offers, terms, independent acceptances and current snapshots.

    Applications hold their actual source/authorization guard. Authorization,
    acceptance freshness, agreement digests, budget, capacity and formation
    conditions remain original processor checks. No contract is created here.
    """
    ACTION_ID = 'OWN-A10'
    SOURCE_SCHEMAS = staticmethod(owner_award_schemas)

    def build(self, context, *, round_ref, selected_offer_ref, final_terms_ref,
            party_acceptance_refs, authority_ref, commitment_snapshot_ref):
        return self._prepare_supplied_snapshot(context,
            input_values={'round_ref': round_ref, 'selected_offer_ref': selected_offer_ref,
                'final_terms_ref': final_terms_ref, 'party_acceptance_refs': party_acceptance_refs,
                'authority_ref': authority_ref, 'commitment_snapshot_ref': commitment_snapshot_ref},
            prepared_type=PreparedOwnerAward, validate_sources=self._validate_award_sources)

    @staticmethod
    def _validate_award_sources(action_input, *, context, reading):
        validate_owner_award_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_award_sources(action_input, *, context, organization_id, sources):
    """Check supplied source identities without treating selection as formation."""
    round_view = sources.get(action_input.round_ref.key())
    offer = sources.get(action_input.selected_offer_ref.key())
    terms = sources.get(action_input.final_terms_ref.key())
    snapshot = sources.get(action_input.commitment_snapshot_ref.key())
    authority = sources.get(action_input.authority_ref.key())
    if (not isinstance(round_view, OwnerAwardRoundView) or round_view.owner_organization_id != organization_id
            or not isinstance(offer, OwnerAwardOfferView) or offer.owner_organization_id != organization_id
            or not isinstance(terms, OwnerAwardTermsView) or terms.owner_organization_id != organization_id
            or not isinstance(snapshot, OwnerAwardSnapshotView) or snapshot.organization_id != organization_id
            or not isinstance(authority, Authorization)):
        raise TaskConflict('Owner award changes the original owner round, offer, terms, snapshot or authority projection')
    if (offer.round_ref.key() != round_view.ref.key() or offer.package_ref.key() != round_view.package_ref.key()
            or offer.ref.key() not in {ref.key() for ref in round_view.offer_refs}
            or terms.offer_ref.key() != offer.ref.key() or terms.round_ref.key() != round_view.ref.key()
            or terms.ref.key() != offer.final_terms_ref.key()
            or terms.counterparty_organization_id != offer.counterparty_organization_id):
        raise TaskConflict('Owner award changes the original selected offer, final terms, round or counterparty')
    unique_refs(action_input.party_acceptance_refs)
    for ref in action_input.party_acceptance_refs:
        acceptance = sources.get(ref.key())
        if (not isinstance(acceptance, OwnerAwardAcceptanceView) or acceptance.run_id != context.run_id
                or acceptance.party_id not in terms.required_party_ids):
            raise TaskConflict('Owner award substitutes another run or legal party acceptance')
        # Historical versions, withdrawn/rejected decisions and digest mismatch
        # remain visible to the original processor; they never imply agreement.
    profile = sources.get(snapshot.formation_profile_ref.key())
    if profile is not None and (not isinstance(profile, OwnerAwardPolicyView)
            or profile.owner_organization_id != organization_id
            or profile.offer_ref.key() != offer.ref.key() or profile.terms_ref.key() != terms.ref.key()):
        raise TaskConflict('Owner award changes the original formation policy owner or agreement')
    for use in snapshot.funding_uses:
        original = sources.get(use.ref.key())
        if original is not None and (not isinstance(original, OwnerAwardCommitmentView)
                or original.owner_organization_id != organization_id or original.amount != use.amount):
            raise TaskConflict('Owner award changes the original funding occupancy identity or amount')
    for use in snapshot.resource_commitments:
        original = sources.get(use.commitment_ref.key())
        if original is not None and (not isinstance(original, OwnerAwardCommitmentView)
                or original.owner_organization_id != organization_id or original.resource_ref is None
                or original.resource_ref.key() != use.resource_ref.key()
                or original.quantity != use.quantity or original.window != use.window):
            raise TaskConflict('Owner award changes the original resource occupancy identity or quantity/window')
    for ref in snapshot.allocation_refs:
        allocation = sources.get(ref.key())
        if allocation is not None and (not isinstance(allocation, OwnerAwardAllocationView)
                or allocation.owner_organization_id != organization_id):
            raise TaskConflict('Owner award allocation changes the original owner')
    condition_refs = [*offer.condition_refs, *terms.condition_refs]
    reference_refs = [terms.contract_template_ref, *terms.clause_refs]
    if isinstance(profile, OwnerAwardPolicyView):
        condition_refs.extend(profile.pending_party_condition_refs)
        reference_refs.extend(profile.requested_change_refs)
    if snapshot.counterparty_capacity_condition_ref is not None:
        condition_refs.append(snapshot.counterparty_capacity_condition_ref)
    for refs, schema in ((condition_refs, OwnerAwardConditionView), (reference_refs, OwnerAwardReferenceView)):
        for ref in refs:
            source = sources.get(ref.key())
            if source is not None and (not isinstance(source, schema)
                    or source.offer_ref.key() != offer.ref.key() or source.terms_ref.key() != terms.ref.key()):
                raise TaskConflict('Owner award condition, template, clause or change substitutes another agreement')
