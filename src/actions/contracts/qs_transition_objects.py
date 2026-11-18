"""QS handover preserves quantity/price trails and distinct contract obligations."""
from typing import Literal

from src.actions.contracts import architect_transition_objects as shared
from src.actions.contracts.common import Measured, ScopeRef, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.qs_cost_objects import CostSource


class QSTransitionEngagementView(shared.ArchitectTransitionEngagementView):
    service_contract_ref: ref_type('Contract')
    client_contract_refs: list[ref_type('Contract')]


class QSTransitionTaskView(shared.ArchitectTransitionTaskView):
    planned_window: TimeWindow
    review_target_refs: list[ref_type('Deliverable')]
    work_estimate_ref: ref_type('WorkEstimate')


class QSTransitionDeliverableView(shared.ArchitectTransitionDeliverableView):
    conclusion_scope: ScopeRef
    price_source_refs: list[ref_type('PriceSource')]
    measurement_trace_refs: list[ref_type('MeasurementTrace')]
    private_client_record_refs: list[ref_type('ClientRecord')]


class QSTransitionSourceView(GovReviewAuthored):
    ref: ref_type('PriceSource') | ref_type('MeasurementTrace')
    provider_organization_id: TextId
    original_content_sha256: TextId


class QSTransitionPriceSourceView(QSTransitionSourceView):
    ref: ref_type('PriceSource')


class QSTransitionMeasurementTraceView(QSTransitionSourceView):
    ref: ref_type('MeasurementTrace')


class QSTransitionSourceAccessView(GovReviewAuthored):
    ref: ref_type('SourceAccess')
    source_ref: ref_type('PriceSource') | ref_type('MeasurementTrace')
    source_sha256: TextId
    recipient_id: TextId
    permitted: ValueState[bool]
    content_kind: Literal['licensed_price_or_measurement_only']


class QSHandoverAcceptanceView(shared.ArchitectHandoverAcceptanceView):
    review_task_ref: ref_type('Task')
    reviewed_deliverable_refs: list[ref_type('Deliverable')]
    source_access_refs: list[ref_type('SourceAccess')]
    inherited_private_client_data: Literal[False]
    inherited_confirmation: Literal[False]


class QSReviewEstimateView(GovReviewAuthored):
    ref: ref_type('WorkEstimate')
    task_ref: ref_type('Task')
    work_profile_ref: ref_type('WorkProfile')
    organization_id: TextId
    function_code: TextId
    effort: Measured
    executed_at: TimePoint
    status: Literal['succeeded','unknown','failed','unsupported']


class QSTransitionContractView(CostSource):
    ref: ref_type('Contract')
    debtor_id: TextId
    payee_id: TextId


class QSTransitionObligationView(shared.OwnerPaymentObligationView):
    engagement_ref: ref_type('Engagement')
    contract_ref: ref_type('Contract')
    obligation_role: Literal['qs_service_fee','client_contract','dispute_support']
    physical_obligation_key: TextId
    supporting_task_refs: list[ref_type('Task')]


def qs_transition_types():
    return {**shared.architect_transition_types(),
        'Engagement':QSTransitionEngagementView,'Task':QSTransitionTaskView,
        'Deliverable':QSTransitionDeliverableView,'HandoverAcceptance':QSHandoverAcceptanceView,
        'PriceSource':QSTransitionPriceSourceView,'MeasurementTrace':QSTransitionMeasurementTraceView,
        'SourceAccess':QSTransitionSourceAccessView,'WorkEstimate':QSReviewEstimateView,
        'Contract':QSTransitionContractView,'Obligation':QSTransitionObligationView,
    }


def qs_transition_schemas():
    return contractor_bid_schemas(qs_transition_types())
