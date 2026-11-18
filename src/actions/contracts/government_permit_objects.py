"""Original action-specific permit conditions and actual fulfillment evidence."""
from typing import Literal
from pydantic import model_validator

from src.actions.contracts.common import DecimalString, Measured, ScopeRef, StrictRecord, TextId, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.government_advice_objects import GovAdviceSource
from src.actions.contracts.government_objects import GovIntakeQuestion, GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.government_decision_objects import GovFormalDecisionView, GovDecisionNotificationView
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView
from src.methods.government_rules import GovRuleReport


class GovPermitView(GovAdviceSource):
    ref: ref_type('Permit')
    organization_id: TextId
    decision_ref: ref_type('Decision')
    condition_refs: list[ref_type('PermitCondition')]
    allowed_action_refs: list[ref_type('ActionDefinition')]
    status: Literal['valid', 'expired', 'suspended', 'revoked', 'unknown']
    effective: ValueState[bool]


class GovPermitDecisionView(GovFormalDecisionView):
    outcome: Literal['approve', 'approve_with_conditions', 'refuse', 'defer_by_procedure']
    permit_ref: ref_type('Permit')
    effect_rule_ref: ref_type('EffectRule')


class GovPermitEffectView(GovAdviceSource):
    ref: ref_type('EffectRule')
    decision_ref: ref_type('Decision')
    mode: Literal['on_signed_record', 'on_actual_delivery']
    notification_recipient_ids: list[TextId]


class GovPermitActionView(GovAdviceSource):
    ref: ref_type('ActionDefinition')
    permit_ref: ref_type('Permit')
    applicable_condition_refs: list[ref_type('PermitCondition')]
    dependency_refs: list[ref_type('PermitDependency')]
    coverage: Literal['complete', 'partial', 'unknown']


class GovPermitVerificationConfig(StrictRecord):
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    verification_authority_ref: ref_type('Authority')
    choice: Literal['verify', 'request_evidence', 'request_condition_change']
    selected_condition_ref: ref_type('PermitCondition') | None
    change_rule_refs: list[ref_type('Rule')]
    change_reason: TextId | None


class GovPermitAuthorityView(GovAdviceSource):
    ref: ref_type('Authority')
    organization_id: TextId
    actor_id: TextId
    function_ref: ref_type('FunctionAssignment')
    permit_ref: ref_type('Permit')
    action_ref: ref_type('ActionDefinition')
    condition_refs: list[ref_type('PermitCondition')]
    purposes: list[Literal['verify', 'request_change']]
    permitted: ValueState[bool]


class GovPermitConditionView(GovAdviceSource):
    ref: ref_type('PermitCondition')
    permit_ref: ref_type('Permit')
    action_refs: list[ref_type('ActionDefinition')]
    criterion: Literal['numeric_interval', 'code_equals', 'unmodeled']
    method_ref: ref_type('Method') | None
    applicable: ValueState[bool]
    fact_ref: ref_type('ConditionFact') | None
    result_ref: ref_type('MethodResult') | None
    evidence_refs_required: list[ref_type('Evidence')]
    dependency_refs: list[ref_type('PermitDependency')]
    question_refs: list[ref_type('EvidenceTarget')]
    unit: TextId | None
    minimum: DecimalString | None
    maximum: DecimalString | None
    expected_code: TextId | None


class GovPermitFactView(GovReviewAuthored):
    ref: ref_type('ConditionFact')
    condition_ref: ref_type('PermitCondition')
    permit_ref: ref_type('Permit')
    action_ref: ref_type('ActionDefinition')
    fulfillment: Literal['actual', 'commitment', 'unknown']
    measured_value: ValueState[Measured] | None
    code_value: ValueState[TextId] | None


class GovPermitDependencyView(GovReviewAuthored):
    ref: ref_type('PermitDependency')
    permit_ref: ref_type('Permit')
    action_ref: ref_type('ActionDefinition')
    dependent_permit_ref: ref_type('Permit')
    dependent_action_ref: ref_type('ActionDefinition')
    dependent_scope: ScopeRef
    verification_ref: ref_type('DependencyVerification') | None


class GovPermitDependencyVerificationView(GovReviewAuthored):
    ref: ref_type('DependencyVerification')
    dependency_ref: ref_type('PermitDependency')
    dependent_permit_ref: ref_type('Permit')
    dependent_action_ref: ref_type('ActionDefinition')
    dependent_scope: ScopeRef
    satisfied: ValueState[bool]
    status: Literal['ok', 'unknown', 'failed', 'unsupported']


class GovPermitResultView(GovReviewAuthored):
    ref: ref_type('MethodResult')
    permit_ref: ref_type('Permit')
    action_ref: ref_type('ActionDefinition')
    condition_ref: ref_type('PermitCondition')
    method_ref: ref_type('Method')
    input_sha256: Digest
    report: GovRuleReport | None
    status: Literal['ok', 'unknown', 'failed', 'unsupported']


class GovPermitQuestionView(GovAdviceSource):
    ref: ref_type('EvidenceTarget')
    permit_ref: ref_type('Permit')
    action_ref: ref_type('ActionDefinition')
    condition_ref: ref_type('PermitCondition')
    question: GovIntakeQuestion


class GovConditionChangeConfig(StrictRecord):
    condition_ref: ref_type('PermitCondition')
    permitted: ValueState[bool]


class GovPermitRuleView(GovAdviceSource):
    ref: ref_type('Rule')
    permit_ref: ref_type('Permit')
    action_ref: ref_type('ActionDefinition')
    verification: GovPermitVerificationConfig | None
    change: GovConditionChangeConfig | None

    @model_validator(mode='after')
    def one_rule_purpose(self):
        if (self.verification is None) == (self.change is None):
            raise ValueError('Permit rule must have exactly one original verification or condition-change purpose')
        return self


def government_permit_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'Permit': GovPermitView, 'Decision': GovPermitDecisionView, 'DecisionNotification': GovDecisionNotificationView,
        'EffectRule': GovPermitEffectView, 'ActionDefinition': GovPermitActionView,
        'Rule': GovPermitRuleView,
        'Authority': GovPermitAuthorityView, 'PermitCondition': GovPermitConditionView,
        'ConditionFact': GovPermitFactView, 'PermitDependency': GovPermitDependencyView,
        'DependencyVerification': GovPermitDependencyVerificationView, 'MethodResult': GovPermitResultView,
        'EvidenceTarget': GovPermitQuestionView, 'RegulatoryRecipient': GovRecipientView,
        'ResponseRequirement': GovResponseRequirementView, 'ClockProfile': ServiceClockView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    return registry
