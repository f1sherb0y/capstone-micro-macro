"""Assemble original authorized OWN-A07 design decision inputs."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_design_objects import (
    OwnerDesignBriefView, OwnerDesignComparisonView, OwnerDesignIssueView,
    OwnerDesignProfileView, OwnerDesignSubmissionView, owner_design_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.models import Authorization
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedOwnerDesign(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A07'


class OwnerDesignActionAssembler(OwnerObservationActionAssembler):
    """Keep exact brief, submissions, comparisons, authority and issue refs.

    Applications hold their actual source/authorization guard. The processor
    retains maturity, allowed use, service acceptance and design choices.
    Assembly creates no design release, acceptance or construction authority.
    """
    ACTION_ID = 'OWN-A07'
    SOURCE_SCHEMAS = staticmethod(owner_design_schemas)

    def build(self, context, *, brief_ref, submission_refs, comparison_refs, authority_ref, issue_refs):
        return self._prepare_supplied_snapshot(context,
            input_values={'brief_ref': brief_ref, 'submission_refs': submission_refs,
                'comparison_refs': comparison_refs, 'authority_ref': authority_ref, 'issue_refs': issue_refs},
            prepared_type=PreparedOwnerDesign, validate_sources=self._validate_design_sources)

    @staticmethod
    def _validate_design_sources(action_input, *, context, reading):
        validate_owner_design_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_design_sources(action_input, *, context, organization_id, sources):
    """Check supplied source relations; retain all original business gates."""
    brief = sources.get(action_input.brief_ref.key())
    authority = sources.get(action_input.authority_ref.key())
    if (not isinstance(brief, OwnerDesignBriefView) or brief.organization_id != organization_id
            or not isinstance(authority, Authorization) or not scope_covers(context.scope, brief.scope)):
        raise TaskConflict('Owner design changes its original brief owner, authority projection or invocation scope')
    for refs in (action_input.submission_refs, action_input.comparison_refs, action_input.issue_refs):
        unique_refs(refs)
    for refs, schema in ((action_input.submission_refs, OwnerDesignSubmissionView),
            (action_input.comparison_refs, OwnerDesignComparisonView), (action_input.issue_refs, OwnerDesignIssueView)):
        for ref in refs:
            source = sources.get(ref.key())
            if not isinstance(source, schema) or source.brief_ref.key() != brief.ref.key():
                raise TaskConflict('Owner design submission, comparison or issue changes the original brief version')
            if isinstance(source, OwnerDesignSubmissionView) and source.owner_organization_id != organization_id:
                raise TaskConflict('Owner design submission changes the original owner recipient')
    # Missing decision profiles remain the original processor's missing-input
    # boundary; never infer a choice or an acceptance from submitted work.
    profile = sources.get(brief.decision_profile_ref.key())
    if profile is not None and (not isinstance(profile, OwnerDesignProfileView)
            or profile.organization_id != organization_id or profile.brief_ref.key() != brief.ref.key()
            or profile.authority_ref.key() != action_input.authority_ref.key()):
        raise TaskConflict('Owner design profile changes the original owner, brief or decision authority')
