"""Assemble explicit authorized OWN-A02 bounded study inputs."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_proposal_objects import ProposalFundingView, ProposalPriorBriefView
from src.actions.contracts.owner_study_objects import (
    StudyCandidateView, StudyCaseView, StudyIssueView, StudyPriorPlanView, StudyProfileView,
    StudyResourceView, StudyServiceOfferView, owner_study_schemas, unique_refs,
)
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedOwnerStudy(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A02'


class OwnerStudyActionAssembler(OwnerObservationActionAssembler):
    """Preserve the complete input, nullable brief and original spending limit.

    The application supplies actual cases, offers and private resources under
    its source/authorization guard. A02 retains all method and business checks;
    preparing an input creates no study task, commission or spending effect.
    """
    ACTION_ID = 'OWN-A02'
    SOURCE_SCHEMAS = staticmethod(owner_study_schemas)

    def build(self, context, *, case_ref, brief_ref, issue_refs, service_candidates,
            study_profile_ref, spending_limit):
        return self._prepare_supplied_snapshot(context,
            input_values={'case_ref': case_ref, 'brief_ref': brief_ref, 'issue_refs': issue_refs,
                'service_candidates': service_candidates, 'study_profile_ref': study_profile_ref,
                'spending_limit': spending_limit}, prepared_type=PreparedOwnerStudy,
            validate_sources=self._validate_study_sources)

    @staticmethod
    def _validate_study_sources(action_input, *, context, reading):
        validate_owner_study_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_study_sources(action_input, *, context, organization_id, sources):
    """Check supplied source identities without calculating study feasibility."""
    case = sources.get(action_input.case_ref.key())
    profile = sources.get(action_input.study_profile_ref.key())
    if (not isinstance(case, StudyCaseView) or not isinstance(profile, StudyProfileView)
            or case.organization_id != organization_id or profile.organization_id != organization_id
            or profile.case_ref.key() != case.ref.key()
            or context.scope.kind == 'assessment_case' and context.scope.ref.key() != case.ref.key()
            or context.scope.kind == 'organization' and context.scope.ref.id != organization_id):
        raise TaskConflict('Owner study changes its original private case/profile identity or own scope')
    unique_refs(action_input.issue_refs)
    unique_refs(action_input.service_candidates)
    if action_input.brief_ref is not None:
        brief = sources.get(action_input.brief_ref.key())
        if (not isinstance(brief, ProposalPriorBriefView) or brief.organization_id != organization_id
                or brief.case_ref.key() != case.ref.key() or brief.objective_ref.key() != case.objective_ref.key()
                or brief.ref.key() not in {ref.key() for ref in case.brief_refs}):
            raise TaskConflict('Owner study brief changes the original owner/case/objective association')
    for ref in action_input.issue_refs:
        issue = sources.get(ref.key())
        if (not isinstance(issue, StudyIssueView) or issue.case_ref.key() != case.ref.key()
                or issue.scope.kind != 'assessment_case' or issue.scope.ref.key() != case.ref.key()
                or ref.key() not in {item.key() for item in case.issue_refs}):
            raise TaskConflict('Owner study question belongs to another private case')
    for ref in action_input.service_candidates:
        offer = sources.get(ref.key())
        if not isinstance(offer, StudyServiceOfferView) or offer.case_ref.key() != case.ref.key():
            raise TaskConflict('Owner study supplied offer changes the original private case')
    # Validate only supplied output dependencies. Stop/defer/missing-input
    # branches remain in the original processor; no dependency is fabricated.
    funding = sources.get(profile.funding_ref.key())
    if funding is not None and (not isinstance(funding, ProposalFundingView) or funding.organization_id != organization_id):
        raise TaskConflict('Owner study substitutes another owner funding position')
    for ref in profile.history_refs:
        prior = sources.get(ref.key())
        if prior is not None and (not isinstance(prior, StudyPriorPlanView)
                or prior.organization_id != organization_id or prior.case_ref.key() != case.ref.key()):
            raise TaskConflict('Owner study history substitutes another owner or case')
    local_keys = set()
    for ref in profile.candidate_refs:
        candidate = sources.get(ref.key())
        if candidate is None:
            continue
        if (not isinstance(candidate, StudyCandidateView) or candidate.organization_id != organization_id
                or candidate.case_ref.key() != case.ref.key() or candidate.local_key in local_keys):
            raise TaskConflict('Owner study candidate changes its original owner/case or repeats task identity')
        local_keys.add(candidate.local_key)
        for allocation in candidate.allocations:
            pool = sources.get(allocation.resource_ref.key())
            if pool is not None and (not isinstance(pool, StudyResourceView) or pool.organization_id != organization_id):
                raise TaskConflict('Owner study allocation substitutes another owner private resources')
