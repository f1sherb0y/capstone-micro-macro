"""Owner choices over original professional versions; no technical release effects."""
from typing import Literal

from src.actions.contracts.common import Money, ScopeRef, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView


class OwnerDesignScopeChoice(StrictRecord):
    scope_ref: ScopeRef
    basis_refs: list[ref_type('Evidence')]
    condition_refs: list[ref_type('Requirement')]


class OwnerDesignBriefView(CostSource):
    ref: ref_type('OwnerBrief')
    organization_id: TextId
    decision_profile_ref: ref_type('OwnerDesignProfile')
    requirement_refs: list[ref_type('Requirement')]
    desired_delivery_at: ValueState[TimePoint]
    status: Literal['current', 'superseded', 'withdrawn']


class OwnerDesignProfileView(CostSource):
    ref: ref_type('OwnerDesignProfile')
    organization_id: TextId
    brief_ref: ref_type('OwnerBrief')
    authority_ref: ref_type('Authorization')
    choice: Literal['confirm_need', 'choose_option', 'request_revision', 'accept_service', 'authorize_use']
    option_ref: ref_type('ProjectOption') | None
    comparison_ref: ref_type('OptionComparison') | None
    submission_ref: ref_type('DeliverableSubmission') | None
    use_ref: ref_type('RequestedUse') | None
    scope_choice: OwnerDesignScopeChoice
    requirement_refs: list[ref_type('Requirement')]
    acknowledged_issue_refs: list[ref_type('Issue')]
    accepted_delivery_conflict: bool
    note: TextId


class OwnerDesignAuthoredView(CostSource):
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId


class OwnerDesignOptionView(OwnerDesignAuthoredView):
    ref: ref_type('ProjectOption')
    brief_ref: ref_type('OwnerBrief')
    evidence_refs_for_choice: list[ref_type('Evidence')]
    earliest_supported_delivery_at: ValueState[TimePoint]
    cost_estimate: ValueState[Money]
    issue_refs: list[ref_type('Issue')]
    status: Literal['current', 'superseded', 'withdrawn']


class OwnerDesignComparisonView(OwnerDesignAuthoredView):
    ref: ref_type('OptionComparison')
    brief_ref: ref_type('OwnerBrief')
    option_refs: list[ref_type('ProjectOption')]
    issue_refs: list[ref_type('Issue')]
    comparison_basis_refs: list[ref_type('Evidence')]
    status: Literal['comparable', 'not_comparable', 'failed']


class OwnerDesignSubmissionView(OwnerDesignAuthoredView):
    ref: ref_type('DeliverableSubmission')
    brief_ref: ref_type('OwnerBrief')
    owner_organization_id: TextId
    deliverable_refs: list[ref_type('ReleasedDeliverable')]
    service_terms_ref: ref_type('ServiceTerms')
    issue_refs: list[ref_type('Issue')]
    status: Literal['submitted', 'superseded', 'withdrawn']


class OwnerDesignDeliverableView(OwnerDesignAuthoredView):
    ref: ref_type('ReleasedDeliverable')
    submission_ref: ref_type('DeliverableSubmission')
    brief_ref: ref_type('OwnerBrief')
    maturity: Literal['research', 'performance_requirement', 'tender_design', 'construction_release']
    allowed_use_codes: list[TextId]
    status: Literal['current', 'superseded', 'withdrawn']


class OwnerDesignServiceTermsView(CostSource):
    ref: ref_type('ServiceTerms')
    owner_organization_id: TextId
    service_organization_id: TextId
    submission_ref: ref_type('DeliverableSubmission')
    required_deliverable_refs: list[ref_type('ReleasedDeliverable')]
    acceptance_condition_refs: list[ref_type('Requirement')]
    status: Literal['effective', 'pending', 'terminated']


class OwnerDesignUseView(CostSource):
    ref: ref_type('RequestedUse')
    organization_id: TextId
    submission_ref: ref_type('DeliverableSubmission')
    brief_ref: ref_type('OwnerBrief')
    deliverable_refs: list[ref_type('ReleasedDeliverable')]
    use_code: Literal['research', 'procurement', 'construction', 'operation']
    use_rule_ref: ref_type('DeliverableUseRule')
    condition_refs: list[ref_type('Requirement')]
    purpose: Literal['requested_use']


class OwnerDesignUseRuleView(OwnerDesignAuthoredView):
    ref: ref_type('DeliverableUseRule')
    submission_ref: ref_type('DeliverableSubmission')
    use_code: Literal['research', 'procurement', 'construction', 'operation']
    required_condition_refs: list[ref_type('Requirement')]
    permitted_maturities: list[Literal['research', 'performance_requirement', 'tender_design', 'construction_release']]
    required_condition_kinds: list[Literal['professional', 'regulatory', 'rights', 'funding', 'service_acceptance', 'other']]
    allowed: ValueState[bool]


class OwnerDesignRequirementView(OwnerDesignAuthoredView):
    ref: ref_type('Requirement')
    brief_ref: ref_type('OwnerBrief')
    submission_ref: ref_type('DeliverableSubmission') | None
    purpose: Literal['owner_need', 'change_request', 'condition']
    condition_kind: Literal['professional', 'regulatory', 'rights', 'funding', 'service_acceptance', 'other']
    evaluated_deliverable_refs: list[ref_type('ReleasedDeliverable')]
    satisfied: ValueState[bool]
    permission: ValueState[bool]
    affected_dependency_refs: list[ref_type('Dependency')]
    reuse_dependency_refs: list[ref_type('Dependency')]
    dependency_coverage: Literal['complete', 'partial', 'unknown']


class OwnerDesignDependencyView(OwnerDesignAuthoredView):
    ref: ref_type('Dependency')
    brief_ref: ref_type('OwnerBrief')
    requirement_ref: ref_type('Requirement')
    source_deliverable_refs: list[ref_type('ReleasedDeliverable')]
    affected: bool
    reuse_basis_ref: ref_type('Evidence') | None
    issue_refs: list[ref_type('Issue')]


class OwnerDesignIssueView(OwnerDesignAuthoredView):
    ref: ref_type('Issue')
    brief_ref: ref_type('OwnerBrief')
    submission_ref: ref_type('DeliverableSubmission') | None
    status: Literal['open', 'resolved']
    blocking_use_codes: list[TextId]
    resolution_basis_ref: ref_type('Evidence') | None


def owner_design_schemas():
    registry = common_projection_schemas()
    schemas = {
        'OwnerBrief': OwnerDesignBriefView, 'OwnerDesignProfile': OwnerDesignProfileView,
        'ProjectOption': OwnerDesignOptionView, 'OptionComparison': OwnerDesignComparisonView,
        'DeliverableSubmission': OwnerDesignSubmissionView, 'ReleasedDeliverable': OwnerDesignDeliverableView,
        'ServiceTerms': OwnerDesignServiceTermsView, 'RequestedUse': OwnerDesignUseView,
        'DeliverableUseRule': OwnerDesignUseRuleView, 'Requirement': OwnerDesignRequirementView,
        'Dependency': OwnerDesignDependencyView, 'Issue': OwnerDesignIssueView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView, 'ClockProfile': ServiceClockView,
    }
    for kind, schema in schemas.items(): registry.register_kind(kind, schema, str)
    return registry
