"""Assemble original OWN-A11 contract-management inputs without changing obligations."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_contract_objects import (
    OwnerContractAssessmentView, OwnerContractCashSourceView, OwnerContractChangeView,
    OwnerContractClaimView, OwnerContractDecisionView, OwnerContractEvidenceView,
    OwnerContractFundingView, OwnerContractIssueView, OwnerContractRecordView,
    OwnerContractRequirementView, OwnerContractReservationView, OwnerContractRuleView,
    OwnerContractTermsView, OwnerContractView, owner_contract_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.models import Authorization


@dataclass(frozen=True)
class PreparedOwnerContract(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A11'


class OwnerContractActionAssembler(OwnerObservationActionAssembler):
    """Keep exact contract, issues, assessments, committed evidence and funding.

    Applications hold their current source/authorization guard. The original
    processor evaluates effective terms, independent assessments, scope rights,
    available cash and change/claim choices. Assembly issues no instruction,
    changes no contract price and creates no payment or accepted obligation.
    """
    ACTION_ID = 'OWN-A11'
    SOURCE_SCHEMAS = staticmethod(owner_contract_schemas)

    def build(self, context, *, contract_ref, issue_refs, assessment_refs,
            evidence_refs, authority_ref, funding_ref):
        return self._prepare_supplied_snapshot(context,
            input_values={'contract_ref': contract_ref, 'issue_refs': issue_refs,
                'assessment_refs': assessment_refs, 'evidence_refs': evidence_refs,
                'authority_ref': authority_ref, 'funding_ref': funding_ref},
            prepared_type=PreparedOwnerContract, validate_sources=self._validate_contract_sources)

    @staticmethod
    def _validate_contract_sources(action_input, *, context, reading):
        validate_owner_contract_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_contract_sources(action_input, *, context, organization_id, sources):
    """Validate supplied original identities while leaving business gates intact."""
    contract = sources.get(action_input.contract_ref.key())
    funding = sources.get(action_input.funding_ref.key())
    authority = sources.get(action_input.authority_ref.key())
    if (not isinstance(contract, OwnerContractView) or contract.owner_id != organization_id
            or not isinstance(funding, OwnerContractFundingView) or funding.organization_id != organization_id
            or not isinstance(authority, Authorization)):
        raise TaskConflict('Owner contract management changes the original contract owner, funding or authority projection')
    for refs in (action_input.issue_refs, action_input.assessment_refs, action_input.evidence_refs):
        unique_refs(refs)

    def bound(ref, schema, *, required=False):
        row = sources.get(ref.key())
        if row is None and not required:
            return None
        if (not isinstance(row, schema) or row.contract_ref.key() != contract.ref.key()
                or row.terms_ref.key() != contract.terms_ref.key()):
            raise TaskConflict('Owner contract source substitutes another original contract or terms version')
        return row

    for refs, schema in ((action_input.issue_refs, OwnerContractIssueView),
            (action_input.assessment_refs, OwnerContractAssessmentView)):
        for ref in refs:
            bound(ref, schema, required=True)
    for ref in action_input.evidence_refs:
        evidence = sources.get(ref.key())
        if not isinstance(evidence, OwnerContractEvidenceView) or evidence.contract_ref.key() != contract.ref.key():
            raise TaskConflict('Owner committed evidence substitutes another original contract')
        record = bound(evidence.original_record_ref, OwnerContractRecordView)
        if record is not None and record.content_sha256 != evidence.content_sha256:
            raise TaskConflict('Owner committed evidence changes its original recorded content digest')
    terms = sources.get(contract.terms_ref.key())
    if terms is not None and (not isinstance(terms, OwnerContractTermsView)
            or terms.contract_ref.key() != contract.ref.key() or terms.owner_id != organization_id
            or terms.contractor_id != contract.contractor_id):
        raise TaskConflict('Owner contract management changes the original terms or legal parties')
    bound(contract.change_rule_ref, OwnerContractRuleView)
    profile = sources.get(contract.decision_profile_ref.key())
    if profile is not None:
        if (not isinstance(profile, OwnerContractDecisionView) or profile.organization_id != organization_id
                or profile.contract_ref.key() != contract.ref.key()
                or profile.authority_ref.key() != action_input.authority_ref.key()):
            raise TaskConflict('Owner contract management changes the original decision owner, contract or authority')
        for ref in [*profile.requested_requirement_refs, *profile.scope_choice.condition_refs]:
            bound(ref, OwnerContractRequirementView)
        for ref in profile.acknowledged_issue_refs:
            bound(ref, OwnerContractIssueView)
        for ref in profile.component_refs:
            bound(ref, OwnerContractClaimView)
        change = bound(profile.change_ref, OwnerContractChangeView) if profile.change_ref is not None else None
        if change is not None and profile.terms_ref is not None:
            if change.replacement_terms_ref.key() != profile.terms_ref.key():
                raise TaskConflict('Owner contract change selects another replacement terms version')
            replacement = sources.get(profile.terms_ref.key())
            if replacement is not None and (not isinstance(replacement, OwnerContractTermsView)
                    or replacement.contract_ref.key() != contract.ref.key() or replacement.owner_id != organization_id
                    or replacement.contractor_id != contract.contractor_id or replacement.prior_terms_ref is None
                    or replacement.prior_terms_ref.key() != contract.terms_ref.key() or replacement.change_ref is None
                    or replacement.change_ref.key() != change.ref.key()):
                raise TaskConflict('Owner pending replacement terms change the original contract, parties or prior terms')
    for ref in funding.source_refs:
        source = sources.get(ref.key())
        if source is None:
            continue
        if not isinstance(source, OwnerContractCashSourceView) or source.organization_id != organization_id:
            raise TaskConflict('Owner contract funding source changes its original account owner')
        for reservation_ref in source.reservation_refs:
            reservation = sources.get(reservation_ref.key())
            if reservation is not None and (not isinstance(reservation, OwnerContractReservationView)
                    or reservation.organization_id != organization_id or reservation.source_ref.key() != source.ref.key()):
                raise TaskConflict('Owner contract reservation changes its original account or owner')
