"""Task-specific release gates and actual, exclusive input allocation snapshots."""
from typing import Literal

from src.actions.contracts.common import Measured, Reference, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.government_permit_objects import GovPermitView
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_planning_objects import ContractorWorkMandateView
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeCaseView, ServiceScopeOrganizationView, ServiceScopeProjectView, ServiceWorkScopeView


class ContractorReadyTaskView(CostSource):
    ref: ref_type('Task')
    organization_id: TextId
    mandate_ref: ref_type('Contract') | ref_type('WorkAuthorization')
    purpose: Literal['preparation', 'construction']
    action_ref: ref_type('ActionDefinition')
    readiness_profile_ref: ref_type('ReadinessProfile')
    requirement_refs: list[ref_type('Requirement')]
    predecessor_task_refs: list[ref_type('Task')]
    execution_window: TimeWindow
    state: Literal['planned', 'blocked', 'released', 'working', 'complete', 'cancelled']
    history_coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class ContractorReadyProfileView(CostSource):
    ref: ref_type('ReadinessProfile')
    task_ref: ref_type('Task')
    organization_id: TextId
    authority_ref: ref_type('Authorization')
    choice: Literal['request_release', 'rectify_dependency', 'resequence']
    requirement_refs: list[ref_type('Requirement')]
    replacement_task_refs: list[ref_type('Task')]
    note: TextId


class ContractorReadyRequirementView(CostSource):
    ref: ref_type('Requirement')
    task_ref: ref_type('Task')
    category: Literal['permit', 'design', 'site', 'resource', 'material', 'funding', 'authority', 'predecessor', 'professional']
    necessary: bool
    applicable: ValueState[bool]
    applicability_ref: ref_type('ReadinessApplicability')
    source_refs: list[ref_type('Permit') | ref_type('DeliverableRelease') | ref_type('SiteReadiness') | ref_type('ResourceAllocation') | ref_type('ReadinessEvidence') | ref_type('Task')]
    verification_ref: ref_type('ReadinessVerification') | None
    minimum_quantity: Measured | None
    responsible: ValueState[TextId]
    disposition: Literal['investigate', 'clarify', 'isolate', 'rectify', 'dispute']
    verifier_organization_id: TextId
    verifier_action_id: TextId


class ContractorReadyVerificationInput(StrictRecord):
    task_ref: ref_type('Task')
    requirement_ref: ref_type('Requirement')
    requirement_sha256: Digest
    task_scope: ScopeRef
    execution_window: TimeWindow
    applicability_ref: ref_type('ReadinessApplicability')
    applicability_sha256: Digest
    source_refs: list[Reference]
    source_sha256s: list[Digest]


class ContractorReadyApplicabilityView(GovReviewAuthored):
    ref: ref_type('ReadinessApplicability')
    task_ref: ref_type('Task')
    requirement_ref: ref_type('Requirement')
    applicable: ValueState[bool]


class ContractorReadyVerificationView(GovReviewAuthored):
    ref: ref_type('ReadinessVerification')
    task_ref: ref_type('Task')
    requirement_ref: ref_type('Requirement')
    input_sha256: Digest
    source_refs: list[ref_type('Permit') | ref_type('DeliverableRelease') | ref_type('SiteReadiness') | ref_type('ResourceAllocation') | ref_type('ReadinessEvidence') | ref_type('Task')]
    satisfied: ValueState[bool]
    status: Literal['ok', 'unknown', 'failed', 'unsupported']


class ContractorReadyDesignView(GovReviewAuthored):
    ref: ref_type('DeliverableRelease')
    mandate_ref: ref_type('Contract') | ref_type('WorkAuthorization')
    content_sha256: Digest
    purpose: Literal['preparation', 'construction']
    allowed_action_refs: list[ref_type('ActionDefinition')]
    released: ValueState[bool]
    professional_check_refs: list[ref_type('ReadinessVerification')]
    check_coverage: Literal['complete', 'partial', 'unknown']


class ContractorReadySiteView(GovReviewAuthored):
    ref: ref_type('SiteReadiness')
    task_ref: ref_type('Task')
    organization_id: TextId
    physically_delivered: ValueState[bool]
    safe_access: ValueState[bool]
    as_of: TimePoint


class ContractorReadyAllocationView(CostSource):
    ref: ref_type('ResourceAllocation')
    task_ref: ref_type('Task')
    organization_id: TextId
    resource_ref: ref_type('ResourcePool') | ref_type('MaterialBatch')
    resource_kind: Literal['resource', 'material']
    commitment_ref: ref_type('ReadinessAllocationFact')
    quantity: Measured
    execution_window: TimeWindow
    status: Literal['reserved', 'available', 'planned', 'expired', 'consumed', 'unknown']
    as_of: TimePoint


class ContractorReadyInputView(CostSource):
    ref: ref_type('ResourcePool') | ref_type('MaterialBatch')
    organization_id: TextId
    actual_available: ValueState[Measured]
    allocations: list[ref_type('ReadinessAllocationFact')]
    accepted: ValueState[bool]
    history_coverage: Literal['complete', 'partial', 'unknown']
    as_of: TimePoint


class ContractorReadyAllocationFactView(CostSource):
    ref: ref_type('ReadinessAllocationFact')
    resource_ref: ref_type('ResourcePool') | ref_type('MaterialBatch')
    task_ref: ref_type('Task')
    allocation_ref: ref_type('ResourceAllocation')
    quantity: Measured
    execution_window: TimeWindow
    core_event_id: TextId
    status: Literal['reserved', 'released', 'consumed']


class ContractorReadyEvidenceView(GovReviewAuthored):
    ref: ref_type('ReadinessEvidence')
    task_ref: ref_type('Task')
    requirement_ref: ref_type('Requirement')
    category: Literal['funding', 'authority', 'professional']
    actual: ValueState[bool]


class ContractorReadyActionView(CostSource):
    ref: ref_type('ActionDefinition')
    mandate_ref: ref_type('Contract') | ref_type('WorkAuthorization')
    purpose: Literal['preparation', 'construction']


def contractor_readiness_schemas():
    registry = common_projection_schemas()
    for kind, schema in {
        'Task': ContractorReadyTaskView, 'ReadinessProfile': ContractorReadyProfileView,
        'Requirement': ContractorReadyRequirementView, 'ReadinessApplicability': ContractorReadyApplicabilityView,
        'ReadinessVerification': ContractorReadyVerificationView, 'Permit': GovPermitView,
        'DeliverableRelease': ContractorReadyDesignView, 'SiteReadiness': ContractorReadySiteView,
        'ResourceAllocation': ContractorReadyAllocationView, 'ResourcePool': ContractorReadyInputView,
        'MaterialBatch': ContractorReadyInputView, 'ReadinessAllocationFact': ContractorReadyAllocationFactView,
        'ReadinessEvidence': ContractorReadyEvidenceView, 'ActionDefinition': ContractorReadyActionView,
        'Contract': ContractorWorkMandateView, 'WorkAuthorization': ContractorWorkMandateView,
        'ClockProfile': ServiceClockView, 'Organization': ServiceScopeOrganizationView,
        'OwnerCase': ServiceScopeCaseView, 'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView,
    }.items():
        registry.register_kind(kind, schema, str)
    return registry
