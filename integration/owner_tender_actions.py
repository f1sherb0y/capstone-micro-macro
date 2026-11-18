"""Assemble original OWN-A09 procurement preparation or published-package inputs."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.owner_tender_objects import (
    OwnerEligibleBidderView, OwnerTenderBidView, OwnerTenderFundingView, OwnerTenderPackageView,
    OwnerTenderProcedureView, OwnerTenderProfileView, OwnerTenderRoundView, owner_tender_schemas,
)
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedOwnerTender(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A09'


class OwnerTenderActionAssembler(OwnerObservationActionAssembler):
    """Keep the explicit preparation/published discriminator and exact bid refs.

    Application code holds its current source/authorization guard. First
    publication never acquires an invented package or round reference. Ranking,
    funding, publication and modification checks remain in the processor.
    """
    ACTION_ID = 'OWN-A09'
    SOURCE_SCHEMAS = staticmethod(owner_tender_schemas)

    def build(self, context, *, package_context, round_refs, bidder_refs, bid_refs,
            evaluation_profile_ref, funding_ref):
        return self._prepare_supplied_snapshot(context,
            input_values={'package_context': package_context, 'round_refs': round_refs,
                'bidder_refs': bidder_refs, 'bid_refs': bid_refs,
                'evaluation_profile_ref': evaluation_profile_ref, 'funding_ref': funding_ref},
            prepared_type=PreparedOwnerTender, validate_sources=self._validate_tender_sources)

    @staticmethod
    def _validate_tender_sources(action_input, *, context, reading):
        validate_owner_tender_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_tender_sources(action_input, *, context, organization_id, sources):
    """Check original supplied versions without ranking or accepting a bid."""
    profile = sources.get(action_input.evaluation_profile_ref.key())
    funding = sources.get(action_input.funding_ref.key())
    if (not isinstance(profile, OwnerTenderProfileView) or profile.owner_organization_id != organization_id
            or not isinstance(funding, OwnerTenderFundingView) or funding.owner_organization_id != organization_id):
        raise TaskConflict('Owner tender changes its original evaluation or funding owner')
    for refs in (action_input.round_refs, action_input.bidder_refs, action_input.bid_refs):
        unique_refs(refs)
    package = None
    if action_input.package_context.kind == 'preparation':
        preparation = action_input.package_context
        if (preparation.scope_ref != context.scope or profile.package_ref is not None
                or profile.procedure_ref.key() != preparation.procedure_ref.key()
                or action_input.round_refs or action_input.bid_refs):
            raise TaskConflict('Owner first publication changes preparation scope/procedure or invents existing rounds/bids')
    else:
        package = sources.get(action_input.package_context.package_ref.key())
        if (not isinstance(package, OwnerTenderPackageView) or package.owner_organization_id != organization_id
                or package.owner_actor_id != context.actor_id or package.evaluation_profile_ref.key() != profile.ref.key()
                or profile.package_ref is None or profile.package_ref.key() != package.ref.key()
                or profile.procedure_ref.key() != package.procedure_ref.key()):
            raise TaskConflict('Owner tender changes the original published package, owner or evaluation profile')
    procedure = sources.get(profile.procedure_ref.key())
    if procedure is not None and (not isinstance(procedure, OwnerTenderProcedureView)
            or procedure.owner_organization_id != organization_id or procedure.evaluation_profile_ref.key() != profile.ref.key()):
        raise TaskConflict('Owner tender changes the original procedure/evaluation relation')
    for ref in action_input.round_refs:
        row = sources.get(ref.key())
        if (not isinstance(row, OwnerTenderRoundView) or row.owner_organization_id != organization_id
                or package is None or row.package_ref.key() != package.ref.key()
                or row.evaluation_profile_ref.key() != profile.ref.key()):
            raise TaskConflict('Owner tender round changes the original package, owner or evaluation rules')
    for ref in action_input.bidder_refs:
        if not isinstance(sources.get(ref.key()), OwnerEligibleBidderView):
            raise TaskConflict('Owner tender changes an original bidder projection')
    for ref in action_input.bid_refs:
        bid = sources.get(ref.key())
        if not isinstance(bid, OwnerTenderBidView) or package is None or bid.package_ref.key() != package.ref.key():
            raise TaskConflict('Owner tender bid changes the original package version')
        bidder = sources.get(bid.bidder_ref.key())
        if bidder is not None and (not isinstance(bidder, OwnerEligibleBidderView)
                or bid.bidder_organization_id != bidder.organization_id or bid.author_actor_id != bidder.actor_id
                or bid.author_function_ref.key() != bidder.function_ref.key()):
            raise TaskConflict('Owner tender bid changes its original submitting organization or author')
