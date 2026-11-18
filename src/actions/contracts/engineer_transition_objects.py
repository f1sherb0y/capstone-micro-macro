"""Engineering handover retains original conclusions and independent review work."""
from typing import Literal

from src.actions.contracts import architect_transition_objects as shared
from src.actions.contracts.common import Measured, Reference, ScopeRef, StrictRecord, TextId, TimeWindow, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.engineer_planning_objects import EngineerPlanningQualificationView, EngineerPlanningAccessView
from src.actions.contracts.government_review_objects import GovReviewAuthored


class EngineerRecallToolDemand(StrictRecord):
    resource_ref: ref_type('ResourcePool')
    capacity: Measured


class EngineerTransitionTaskView(shared.ArchitectTransitionTaskView):
    discipline_code: TextId
    professional_method_refs: list[ref_type('ProfessionalMethod')]
    tool_demands: list[EngineerRecallToolDemand]
    site_access_ref: ref_type('SiteAccess') | None
    planned_window: TimeWindow
    review_target_refs: list[ref_type('Deliverable')]


class EngineerRecallResourceView(shared.ArchitectRecallResourceView):
    asset_role: Literal['personnel','equipment']
    physical_resource_key: TextId
    discipline_codes: list[TextId]
    qualification_refs: list[ref_type('Qualification')]
    effort_per_capacity_tick: Measured | None


class EngineerRecallWorkProfileView(shared.ArchitectRecallWorkProfileView):
    resources: list[EngineerRecallResourceView]


class EngineerTransitionDeliverableView(shared.ArchitectTransitionDeliverableView):
    discipline_code: TextId
    conclusion_scope: ScopeRef
    original_conclusion: TextId
    verification_status: Literal['passed','failed','unverified','limited']
    professional_method_refs: list[ref_type('ProfessionalMethod')]
    input_refs: list[Reference]
    missing_dependency_refs: list[ref_type('Dependency')]


class EngineerHandoverAcceptanceView(shared.ArchitectHandoverAcceptanceView):
    review_task_ref: ref_type('Task')
    reviewed_deliverable_refs: list[ref_type('Deliverable')]
    declared_missing_dependency_refs: list[ref_type('Dependency')]
    missing_input_policy: Literal['limit_conclusions','request_recheck','decline_new_scope']
    inherited_private_memory: Literal[False]
    inherited_verification: Literal[False]


class EngineerTransitionMethodView(GovReviewAuthored):
    ref: ref_type('ProfessionalMethod')
    organization_id: TextId
    discipline_codes: list[TextId]
    function_codes: list[TextId]
    supported: ValueState[bool]
    purpose: Literal['service_delivery','investigation','check','review']


def engineer_transition_types():
    return {**shared.architect_transition_types(),
        'Task':EngineerTransitionTaskView,'WorkProfile':EngineerRecallWorkProfileView,
        'ResourcePool':EngineerRecallResourceView,'Deliverable':EngineerTransitionDeliverableView,
        'HandoverAcceptance':EngineerHandoverAcceptanceView,'ProfessionalMethod':EngineerTransitionMethodView,
        'Qualification':EngineerPlanningQualificationView,'SiteAccess':EngineerPlanningAccessView,
    }


def engineer_transition_schemas():
    return contractor_bid_schemas(engineer_transition_types())
