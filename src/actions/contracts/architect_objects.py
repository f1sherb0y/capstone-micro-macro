"""Architect projection names backed by shared professional-service shapes."""
from src.actions.contracts.service_objects import (
    ServiceScopeOrganizationView as ArchitectScopeOrganizationView,
    ServiceClockView as ArchitectClockView,
    ServiceScopeCaseView as ArchitectScopeCaseView,
    ServiceScopeProjectView as ArchitectScopeProjectView,
    ServiceWorkScopeView as ArchitectWorkScopeView,
    ServiceRequestView as ArchitectServiceRequestView,
    ServiceTermsView as ArchitectServiceTermsView,
    ServiceIntakeCapabilityView as ArchitectIntakeCapabilityView,
    ServiceQualificationView as ArchitectQualificationView,
    ServiceResourceCalendarView as ArchitectResourceCalendarView,
    ServiceFeeBasisView as ArchitectFeeBasisView,
    ServiceWorkProfileView as ArchitectWorkProfileView,
    ServiceMethodView as ArchitectServiceMethodView,
    ServiceFeeCalculationView as ArchitectFeeCalculationView,
    ServiceDeliverableRequirementView as ArchitectDeliverableRequirementView,
    ServiceClarificationTargetView as ArchitectClarificationTargetView,
    ServiceResponseRequirementView as ArchitectResponseRequirementView,
    ServiceInternalFeeRuleView as ArchitectInternalFeeRuleView,
    ServiceUse as ArchitectUse, SourcedServiceProjection, ServiceCommissionAuthorityView,
    service_intake_schemas,
)


def architect_intake_schemas():
    return service_intake_schemas()
