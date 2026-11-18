"""Assemble original OWN-A08 applications and notice responses."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_regulatory_objects import (
    OwnerRegulatoryAuthorityView, OwnerRegulatoryCaseView, OwnerRegulatoryNoticeView,
    OwnerRegulatoryProfileView, OwnerRegulatoryRequirementView, OwnerRegulatorySubmissionView,
    owner_regulatory_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedOwnerRegulatory(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A08'


class OwnerRegulatoryActionAssembler(OwnerObservationActionAssembler):
    """Preserve applicant identity, original cases, notices and submitted work.

    The application holds its current source/authorization guard. The original
    processor evaluates delegation, jurisdiction, procedure and deadlines.
    Preparation creates no application, receipt, permit or regulatory decision.
    """
    ACTION_ID = 'OWN-A08'
    SOURCE_SCHEMAS = staticmethod(owner_regulatory_schemas)

    def build(self, context, *, scope_ref, regulatory_requirement_ref, applicant_id,
            authority_candidates, submission_refs, notice_refs, case_refs):
        return self._prepare_supplied_snapshot(context,
            input_values={'scope_ref': scope_ref, 'regulatory_requirement_ref': regulatory_requirement_ref,
                'applicant_id': applicant_id, 'authority_candidates': authority_candidates,
                'submission_refs': submission_refs, 'notice_refs': notice_refs, 'case_refs': case_refs},
            prepared_type=PreparedOwnerRegulatory, validate_sources=self._validate_regulatory_sources)

    @staticmethod
    def _validate_regulatory_sources(action_input, *, context, reading):
        validate_owner_regulatory_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_regulatory_sources(action_input, *, context, organization_id, sources):
    """Validate supplied identity links without inferring jurisdiction or approval."""
    requirement = sources.get(action_input.regulatory_requirement_ref.key())
    if (action_input.scope_ref != context.scope or not isinstance(requirement, OwnerRegulatoryRequirementView)
            or requirement.applicant_id != action_input.applicant_id):
        raise TaskConflict('Owner regulatory input changes its original requirement, applicant or invocation scope')
    for refs in (action_input.authority_candidates, action_input.submission_refs, action_input.notice_refs,
            action_input.case_refs):
        unique_refs(refs)
    for ref in action_input.authority_candidates:
        if not isinstance(sources.get(ref.key()), OwnerRegulatoryAuthorityView):
            raise TaskConflict('Owner regulatory candidate changes its original authority projection')
    for refs, schema in ((action_input.submission_refs, OwnerRegulatorySubmissionView),
            (action_input.case_refs, OwnerRegulatoryCaseView)):
        for ref in refs:
            source = sources.get(ref.key())
            if (not isinstance(source, schema) or source.applicant_id != action_input.applicant_id
                    or source.requirement_ref.key() != requirement.ref.key()):
                raise TaskConflict('Owner regulatory submission or case changes the original applicant/requirement')
    for ref in action_input.notice_refs:
        notice = sources.get(ref.key())
        if not isinstance(notice, OwnerRegulatoryNoticeView) or notice.applicant_id != action_input.applicant_id:
            raise TaskConflict('Owner regulatory notice changes the original applicant')
        case = sources.get(notice.case_ref.key())
        if case is not None and (not isinstance(case, OwnerRegulatoryCaseView)
                or case.applicant_id != action_input.applicant_id or case.requirement_ref.key() != requirement.ref.key()
                or case.authority_ref.key() != notice.authority_ref.key()):
            raise TaskConflict('Owner regulatory notice changes its original case/authority relation')
    # The actor's Owner organization may differ from the applicant under an
    # explicit agency authorization. The original processor decides delegation.
    profile = sources.get(requirement.decision_profile_ref.key())
    if profile is not None and (not isinstance(profile, OwnerRegulatoryProfileView)
            or profile.organization_id != organization_id or profile.requirement_ref.key() != requirement.ref.key()):
        raise TaskConflict('Owner regulatory profile changes the original decision owner or requirement')
