"""Freeze original Government A06 issues, response provenance and revised materials."""
from dataclasses import dataclass
from typing import ClassVar

from integration.government_advice_actions import GovernmentAdviceActionAssembler, PreparedGovernmentAdvice
from src.actions.contracts.government_objects import (
    GovJurisdictionView, GovMatterView, GovRecipientView, GovResponseRequirementView,
)
from src.actions.contracts.government_supplement_objects import (
    GovSupplementCaseView, GovSupplementSubmissionView, GovSubmissionComponentView,
    GovSupplementProfileView, GovSupplementIssueView, GovSupplementRequirementView,
    GovSupplementRuleView, GovSupplementResponseView, GovResponseFactView,
    GovSupplementResultView, GovSupplementAssessmentView, GovSupplementQuestionView,
    GovSupplementClockView, GovSupplementDelayAuthorityView, GovSupplementTriggerView,
    GovSupplementRevisionView, government_supplement_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedGovernmentSupplement(PreparedGovernmentAdvice):
    ACTION_ID: ClassVar[str] = 'GOV-A06'


class GovernmentSupplementActionAssembler(GovernmentAdviceActionAssembler):
    """Preserve original lineage without closing issues or rewriting materials.

    Verified resolution, unchanged review coverage and lawful delay handling
    remain original processor decisions. No approval or refusal is inferred.
    """
    ACTION_ID = 'GOV-A06'
    SOURCE_SCHEMAS = staticmethod(government_supplement_schemas)

    def build(self, context, *, scope, case_ref, issue_refs, original_submission_ref,
            response_refs, current_submission_ref, reusable_assessment_refs, clock_rule_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'case_ref': case_ref, 'issue_refs': issue_refs,
            'original_submission_ref': original_submission_ref, 'response_refs': response_refs,
            'current_submission_ref': current_submission_ref,
            'reusable_assessment_refs': reusable_assessment_refs, 'clock_rule_ref': clock_rule_ref},
            prepared_type=PreparedGovernmentSupplement,
            validate_sources=validate_government_supplement_sources)


def validate_government_supplement_sources(action_input, *, context, organization_id, sources):
    """Bind original identities; leave evidence sufficiency and reuse to the processor."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Government supplement lacks its exact original concrete source')
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('Government supplement source leaves its original requested scope')
        return row

    if not scope_covers(context.scope, action_input.scope):
        raise TaskConflict('Government supplement input leaves its original invocation scope')
    for refs in (action_input.issue_refs, action_input.response_refs, action_input.reusable_assessment_refs):
        unique_refs(refs)
    case = read(action_input.case_ref, GovSupplementCaseView)
    original = read(action_input.original_submission_ref, GovSupplementSubmissionView)
    current = read(action_input.current_submission_ref, GovSupplementSubmissionView)
    clock = read(action_input.clock_rule_ref, GovSupplementClockView)
    if (case.organization_id != organization_id or case.current_submission_ref != current.ref
            or original.ref not in case.linked_submission_refs or current.ref not in case.linked_submission_refs
            or clock.case_ref != case.ref or clock.procedure_ref != case.procedure_ref):
        raise TaskConflict('Government supplement substitutes its original agency, submission lineage or clock')
    for submission in (original, current):
        if (submission.matter_ref != case.matter_ref or submission.procedure_ref != case.procedure_ref
                or submission.jurisdiction_ref != case.jurisdiction_ref
                or submission.recipient_organization_id != organization_id or submission.applicant_id != case.applicant_id):
            raise TaskConflict('Government supplement submission substitutes its original applicant or procedure')
        for ref in submission.component_refs:
            if ref.key() in sources:
                component = read(ref, GovSubmissionComponentView)
                if component.submission_ref != submission.ref:
                    raise TaskConflict('Government supplement component substitutes its original submission version')
    if case.jurisdiction_ref.key() in sources:
        jurisdiction = read(case.jurisdiction_ref, GovJurisdictionView)
        if jurisdiction.organization_id != organization_id:
            raise TaskConflict('Government supplement borrows another agency jurisdiction')
    if case.matter_ref.key() in sources:
        read(case.matter_ref, GovMatterView)

    profile = None
    if case.supplement_profile_ref.key() in sources:
        profile = read(case.supplement_profile_ref, GovSupplementProfileView)
        if (profile.organization_id != organization_id or profile.case_ref != case.ref
                or profile.original_submission_ref != original.ref or profile.current_submission_ref != current.ref
                or profile.clock_rule_ref != clock.ref):
            raise TaskConflict('Government supplement profile substitutes its original case or submission versions')
        if profile.revision_basis_ref is not None and profile.revision_basis_ref.key() in sources:
            revision = read(profile.revision_basis_ref, GovSupplementRevisionView)
            if (revision.case_ref != case.ref or revision.original_submission_ref != original.ref
                    or revision.original_content_sha256 != original.content_sha256
                    or revision.current_submission_ref != current.ref or revision.current_content_sha256 != current.content_sha256
                    or revision.procedure_ref != case.procedure_ref):
                raise TaskConflict('Government revision basis substitutes its original or current submission content')

    def assessment(ref):
        row = read(ref, GovSupplementAssessmentView)
        if (row.case_ref != case.ref or row.submission_ref != original.ref
                or row.content_sha256 != original.content_sha256):
            raise TaskConflict('Government reusable assessment substitutes its original reviewed submission')
        for component_ref in row.component_refs:
            if component_ref.key() in sources:
                component = read(component_ref, GovSubmissionComponentView)
                if component.submission_ref != original.ref or component.ref not in original.component_refs:
                    raise TaskConflict('Government assessment coverage substitutes its original submission component')

    for ref in action_input.reusable_assessment_refs:
        assessment(ref)
    if profile is not None:
        for ref in profile.assessment_refs:
            if ref.key() in sources:
                assessment(ref)

    def legal_rule(ref, issue_ref):
        rule = read(ref, GovSupplementRuleView)
        if (rule.organization_id != organization_id or rule.case_ref != case.ref
                or rule.purpose != 'supplement' or issue_ref not in rule.issue_refs):
            raise TaskConflict('Government supplement requirement substitutes its original legal basis')
        return rule

    issues = {}
    for ref in action_input.issue_refs:
        issue = read(ref, GovSupplementIssueView)
        if issue.case_ref != case.ref or issue.original_submission_ref != original.ref:
            raise TaskConflict('Government supplement issue substitutes its original case or submission')
        issues[ref.key()] = issue
        for requirement_ref in issue.requirement_refs:
            if requirement_ref.key() in sources:
                requirement = read(requirement_ref, GovSupplementRequirementView)
                if requirement.issue_ref != issue.ref:
                    raise TaskConflict('Government supplement issue borrows another requirement')
                if requirement.rule_ref.key() in sources:
                    legal_rule(requirement.rule_ref, issue.ref)
        if issue.verification_result_ref is not None and issue.verification_result_ref.key() in sources:
            result = read(issue.verification_result_ref, GovSupplementResultView)
            if (result.issue_ref != issue.ref or result.current_submission_ref != current.ref
                    or result.current_content_sha256 != current.content_sha256):
                raise TaskConflict('Government supplement verification substitutes its original issue or revised content')
        for question_ref in issue.question_refs:
            if question_ref.key() not in sources:
                continue
            row = read(question_ref, GovSupplementQuestionView)
            question = row.question
            if row.issue_ref != issue.ref or question.scope != issue.scope or row.ref not in question.target_refs:
                raise TaskConflict('Government supplement question substitutes its original issue or targets')
            if question.requirement_ref.key() in sources:
                legal_rule(question.requirement_ref, issue.ref)
            if question.response_requirement_ref.key() in sources:
                response_requirement = read(question.response_requirement_ref, GovResponseRequirementView)
                if response_requirement.rule_ref != question.requirement_ref or response_requirement.scope != question.scope:
                    raise TaskConflict('Government supplement response requirement substitutes its original rule or scope')
            for target_ref in question.target_refs:
                if target_ref.key() in sources:
                    target = read(target_ref, GovSupplementQuestionView)
                    if target.issue_ref != issue.ref or target.question != question:
                        raise TaskConflict('Government supplement targets substitute their original question')
            for recipient_ref in question.recipient_refs:
                if recipient_ref.key() in sources:
                    recipient = read(recipient_ref, GovRecipientView)
                    if recipient.scope != question.scope:
                        raise TaskConflict('Government supplement recipient substitutes its original question scope')

    for ref in action_input.response_refs:
        response = read(ref, GovSupplementResponseView)
        if profile is None or profile.choice != 'verify_response':
            continue
        issue = issues.get(response.issue_ref.key())
        if (issue is None or response.case_ref != case.ref or response.original_submission_ref != original.ref
                or response.current_submission_ref != current.ref or response.current_content_sha256 != current.content_sha256
                or response.author_actor_id not in profile.authorized_response_actor_ids):
            raise TaskConflict('Government supplement response substitutes its original issue, author or revised content')
        for fact_ref in response.fact_refs:
            if fact_ref.key() in sources:
                fact = read(fact_ref, GovResponseFactView)
                if fact.response_ref != response.ref or fact.requirement_ref not in issue.requirement_refs:
                    raise TaskConflict('Government response fact substitutes its original response or requirement')

    if profile is not None and profile.delay_rule_ref is not None and profile.delay_rule_ref.key() in sources:
        rule = read(profile.delay_rule_ref, GovSupplementRuleView)
        if rule.organization_id != organization_id or rule.case_ref != case.ref or rule.purpose != 'delay':
            raise TaskConflict('Government delay rule substitutes its original agency or case')
        if rule.delay_authority_ref is not None and rule.delay_authority_ref.key() in sources:
            authority = read(rule.delay_authority_ref, GovSupplementDelayAuthorityView)
            if (authority.organization_id != organization_id or authority.actor_id != context.actor_id
                    or authority.function_ref != context.function_ref or authority.case_ref != case.ref
                    or authority.rule_ref != rule.ref or authority.clock_rule_ref != clock.ref
                    or authority.next_trigger_ref != profile.next_trigger_ref):
                raise TaskConflict('Government delay authority substitutes its original actor, case or trigger')
        if profile.next_trigger_ref is not None and profile.next_trigger_ref.key() in sources:
            trigger = read(profile.next_trigger_ref, GovSupplementTriggerView)
            if trigger.case_ref != case.ref or trigger.rule_ref != rule.ref:
                raise TaskConflict('Government delay trigger substitutes its original case or rule')
    # The processor owns complete source sets, current authority, revision route,
    # unchanged component coverage, response event dedup, verified fact/method
    # recomputation and lawful deadlines. No issue, design or decision is changed.
