"""Freeze original Government A08 action-specific conditions and linked permit facts."""
from dataclasses import dataclass
from typing import ClassVar

from integration.government_advice_actions import GovernmentAdviceActionAssembler, PreparedGovernmentAdvice
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.government_objects import GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_decision_objects import GovDecisionNotificationView
from src.actions.contracts.government_permit_objects import (
    GovPermitView, GovPermitDecisionView, GovPermitEffectView, GovPermitActionView,
    GovPermitRuleView, GovPermitAuthorityView, GovPermitConditionView, GovPermitFactView,
    GovPermitDependencyView, GovPermitDependencyVerificationView, GovPermitResultView,
    GovPermitQuestionView, government_permit_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedGovernmentPermit(PreparedGovernmentAdvice):
    ACTION_ID: ClassVar[str] = 'GOV-A08'


class GovernmentPermitActionAssembler(GovernmentAdviceActionAssembler):
    """Preserve actual fulfillment sources without granting execution permission.

    Permit effect, verified fulfillment and cross-scope prerequisites remain
    original processor decisions. Other technical, funding and resource gates remain.
    """
    ACTION_ID = 'GOV-A08'
    SOURCE_SCHEMAS = staticmethod(government_permit_schemas)

    def build(self, context, *, scope, permit_ref, intended_action_ref, condition_refs,
            evidence_refs, verification_rule_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'permit_ref': permit_ref, 'intended_action_ref': intended_action_ref,
            'condition_refs': condition_refs, 'evidence_refs': evidence_refs,
            'verification_rule_ref': verification_rule_ref}, prepared_type=PreparedGovernmentPermit,
            validate_sources=validate_government_permit_sources)


def validate_government_permit_sources(action_input, *, context, organization_id, sources):
    """Bind original targets; linked permits retain their own broader or other scope."""
    def read(ref, schema, *, linked=False):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Government permit verification lacks its exact original concrete source')
        if hasattr(row, 'scope') and not linked and not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('Government permit source leaves its original intended action scope')
        return row

    if not scope_covers(context.scope, action_input.scope):
        raise TaskConflict('Government permit input leaves its original invocation scope')
    unique_refs(action_input.condition_refs)
    unique_refs(action_input.evidence_refs)
    permit = read(action_input.permit_ref, GovPermitView, linked=True)
    action = read(action_input.intended_action_ref, GovPermitActionView)
    rule = read(action_input.verification_rule_ref, GovPermitRuleView)

    def bound(row):
        if row.permit_ref != permit.ref or row.action_ref != action.ref:
            raise TaskConflict('Government condition source substitutes its original permit or intended action')

    bound(rule)
    if (permit.organization_id != organization_id or not scope_covers(permit.scope, action_input.scope)
            or action.permit_ref != permit.ref or action.scope != action_input.scope
            or rule.verification is None or rule.verification.organization_id != organization_id):
        raise TaskConflict('Government verification substitutes its original agency, action scope or rule purpose')
    profile = rule.verification
    if profile.verification_authority_ref.key() in sources:
        authority = read(profile.verification_authority_ref, GovPermitAuthorityView)
        bound(authority)
        if (authority.organization_id != organization_id or authority.actor_id != context.actor_id
                or authority.function_ref != context.function_ref):
            raise TaskConflict('Government condition authority substitutes its original verifier')
    for ref in action_input.evidence_refs:
        read(ref, EvidenceRecord)

    def linked_decision(row):
        if row.decision_ref.key() not in sources:
            return
        decision = read(row.decision_ref, GovPermitDecisionView, linked=True)
        if decision.permit_ref != row.ref or not scope_covers(decision.scope, row.scope):
            raise TaskConflict('Government permit substitutes its original formal decision or coverage')
        if decision.effect_rule_ref.key() not in sources:
            return
        effect = read(decision.effect_rule_ref, GovPermitEffectView, linked=True)
        if effect.decision_ref != decision.ref:
            raise TaskConflict('Government permit effect substitutes its original formal decision')
        for ref in decision.notification_refs:
            if ref.key() in sources:
                notification = read(ref, GovDecisionNotificationView, linked=True)
                if (notification.decision_ref != decision.ref
                        or notification.recipient_id not in effect.notification_recipient_ids):
                    raise TaskConflict('Government permit notification substitutes its original decision or recipient')

    linked_decision(permit)
    dependency_refs = list(action.dependency_refs)
    for ref in action_input.condition_refs:
        condition = read(ref, GovPermitConditionView)
        if condition.permit_ref != permit.ref or action.ref not in condition.action_refs:
            raise TaskConflict('Government condition substitutes its original permit or intended action')
        dependency_refs.extend(condition.dependency_refs)
        if condition.fact_ref is not None and condition.fact_ref.key() in sources:
            fact = read(condition.fact_ref, GovPermitFactView)
            bound(fact)
            if fact.condition_ref != condition.ref or not scope_covers(fact.scope, condition.scope):
                raise TaskConflict('Government fulfillment fact substitutes its original condition coverage')
        if condition.result_ref is not None and condition.result_ref.key() in sources:
            result = read(condition.result_ref, GovPermitResultView)
            bound(result)
            if result.condition_ref != condition.ref or result.scope != condition.scope:
                raise TaskConflict('Government condition result substitutes its original condition or coverage')
        for question_ref in condition.question_refs:
            if question_ref.key() not in sources:
                continue
            row = read(question_ref, GovPermitQuestionView)
            bound(row)
            question = row.question
            if (row.condition_ref != condition.ref or question.scope != row.scope
                    or question.requirement_ref != rule.ref or row.ref not in question.target_refs):
                raise TaskConflict('Government condition question substitutes its original condition, rule or targets')
            if question.response_requirement_ref.key() in sources:
                response = read(question.response_requirement_ref, GovResponseRequirementView)
                if response.rule_ref != rule.ref or response.scope != question.scope:
                    raise TaskConflict('Government condition response substitutes its original rule or scope')
            for target_ref in question.target_refs:
                if target_ref.key() in sources:
                    target = read(target_ref, GovPermitQuestionView)
                    bound(target)
                    if target.condition_ref != condition.ref or target.question != question:
                        raise TaskConflict('Government condition targets substitute their original question')
            for recipient_ref in question.recipient_refs:
                if recipient_ref.key() in sources:
                    recipient = read(recipient_ref, GovRecipientView)
                    if recipient.scope != question.scope:
                        raise TaskConflict('Government condition recipient substitutes its original question scope')

    for ref in set(dependency_refs):
        if ref.key() not in sources:
            continue
        dependency = read(ref, GovPermitDependencyView)
        bound(dependency)
        dependent_permit = None
        if dependency.dependent_permit_ref.key() in sources:
            dependent_permit = read(dependency.dependent_permit_ref, GovPermitView, linked=True)
            if not scope_covers(dependent_permit.scope, dependency.dependent_scope):
                raise TaskConflict('Government dependency substitutes its original dependent permit coverage')
            linked_decision(dependent_permit)
        if dependency.dependent_action_ref.key() in sources:
            dependent_action = read(dependency.dependent_action_ref, GovPermitActionView, linked=True)
            if (dependent_action.permit_ref != dependency.dependent_permit_ref
                    or dependent_action.scope != dependency.dependent_scope
                    or dependent_permit is not None and dependent_action.ref not in dependent_permit.allowed_action_refs):
                raise TaskConflict('Government dependency substitutes its original dependent action or scope')
        if dependency.verification_ref is not None and dependency.verification_ref.key() in sources:
            verification = read(dependency.verification_ref, GovPermitDependencyVerificationView)
            if (verification.dependency_ref != dependency.ref
                    or verification.dependent_permit_ref != dependency.dependent_permit_ref
                    or verification.dependent_action_ref != dependency.dependent_action_ref
                    or verification.dependent_scope != dependency.dependent_scope):
                raise TaskConflict('Government dependency verification substitutes its original cross-scope target')
    if profile.choice == 'request_condition_change':
        for ref in profile.change_rule_refs:
            if ref.key() in sources:
                change_rule = read(ref, GovPermitRuleView)
                bound(change_rule)
                if change_rule.change is None or change_rule.change.condition_ref != profile.selected_condition_ref:
                    raise TaskConflict('Government condition-change basis substitutes its original selected condition')
    # The processor owns complete action/condition coverage, current permit effect,
    # actual delivery and fulfillment, independent verifier rights, cross-scope
    # verification, method recomputation and change permission. No execution gate
    # is bypassed and no condition or permit is changed during assembly.
