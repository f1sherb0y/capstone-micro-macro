"""Received covenant monitoring facts and scoped proposals; no enforcement ledger."""
from typing import Annotated, Literal

from pydantic import Field

from src.actions.contracts.common import ScopeRef, StrictRecord, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.domain import common_projection_schemas
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.service_objects import ServiceClockView, ServiceScopeOrganizationView, ServiceScopeCaseView, ServiceScopeProjectView, ServiceWorkScopeView

MonitoringMeasure = Literal['issue_notice', 'restrict_scope', 'release_restriction']


class BankMonitoringArrangementView(CostSource):
    ref: ref_type('FinanceArrangement')
    lender_id: TextId
    borrower_id: TextId
    terms_ref: ref_type('FinanceTerms')
    covenant_refs: list[ref_type('Covenant')]
    notice_refs: list[ref_type('CovenantNotice')]
    disclosure_refs: list[ref_type('MonitoringReport')]
    coverage: Literal['complete', 'partial', 'unknown']


class BankMonitoringProfileView(CostSource):
    ref: ref_type('MonitoringProfile')
    organization_id: TextId
    arrangement_ref: ref_type('FinanceArrangement')
    authority_ref: ref_type('Authorization')
    choice: Literal['continue', 'request_evidence', 'issue_notice', 'restrict_scope', 'release_restriction']
    target_covenant_ref: ref_type('Covenant') | None
    affected_scope: ScopeRef
    requirement_refs: list[ref_type('Requirement')]
    note: TextId


class BankMonitoringGate(StrictRecord):
    choice: MonitoringMeasure
    fact_codes: Annotated[list[TextId], Field(min_length=1)]
    prior_notice_required: bool
    remedy_window_must_expire: bool


class BankMonitoringCovenantView(CostSource):
    ref: ref_type('Covenant')
    arrangement_ref: ref_type('FinanceArrangement')
    terms_ref: ref_type('FinanceTerms')
    requirement_refs: list[ref_type('Requirement')]
    permitted_verifier_ids: Annotated[list[TextId], Field(min_length=1)]
    permitted_verifier_action_ids: Annotated[list[TextId], Field(min_length=1)]
    gates: list[BankMonitoringGate]


class BankMonitoringFact(StrictRecord):
    code: TextId
    satisfied: ValueState[bool]
    nature: Literal['verified', 'estimate', 'promise']
    evidence_refs: list[ref_type('Evidence')]


class BankMonitoringFinding(StrictRecord):
    dimension_ref: ref_type('RiskDimension')
    conclusion: ValueState[Literal['acceptable', 'unacceptable']]
    evidence_refs: list[ref_type('Evidence')]
    method_ref: ref_type('RiskMethod')


class BankMonitoringReportView(CostSource):
    ref: ref_type('MonitoringReport')
    arrangement_ref: ref_type('FinanceArrangement')
    covenant_ref: ref_type('Covenant')
    terms_ref: ref_type('FinanceTerms')
    author_organization_id: TextId
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: TextId
    observed_at: TimePoint
    facts: list[BankMonitoringFact]
    findings: list[BankMonitoringFinding]


class BankMonitoringNoticeView(CostSource):
    ref: ref_type('CovenantNotice')
    arrangement_ref: ref_type('FinanceArrangement')
    covenant_ref: ref_type('Covenant')
    terms_ref: ref_type('FinanceTerms')
    lender_id: TextId
    borrower_id: TextId
    choice: MonitoringMeasure
    affected_scope: ScopeRef
    status: Literal['active', 'released', 'superseded']
    delivery: Literal['verified_served', 'pending', 'unknown']
    served_at: TimePoint | None
    remedy_deadline: TimePoint | None
    delivery_evidence_refs: list[ref_type('Evidence')]


class BankMonitoringRequirementView(CostSource):
    ref: ref_type('Requirement')
    arrangement_ref: ref_type('FinanceArrangement')
    covenant_ref: ref_type('Covenant')
    responsible_id: TextId


class BankMonitoringDimensionView(CostSource):
    ref: ref_type('RiskDimension')
    method_ref: ref_type('RiskMethod')


class BankMonitoringMethodView(CostSource):
    ref: ref_type('RiskMethod')
    arrangement_ref: ref_type('FinanceArrangement')
    dimension_refs: Annotated[list[ref_type('RiskDimension')], Field(min_length=1)]
    permitted_author_ids: Annotated[list[TextId], Field(min_length=1)]
    result_use: Literal['monitoring_only']


def bank_monitoring_schemas():
    registry = common_projection_schemas()
    schemas = {
        'FinanceArrangement': BankMonitoringArrangementView, 'MonitoringProfile': BankMonitoringProfileView,
        'Covenant': BankMonitoringCovenantView, 'MonitoringReport': BankMonitoringReportView,
        'CovenantNotice': BankMonitoringNoticeView, 'Requirement': BankMonitoringRequirementView,
        'RiskDimension': BankMonitoringDimensionView, 'RiskMethod': BankMonitoringMethodView,
        'Organization': ServiceScopeOrganizationView, 'OwnerCase': ServiceScopeCaseView,
        'Project': ServiceScopeProjectView, 'WorkScope': ServiceWorkScopeView, 'ClockProfile': ServiceClockView,
    }
    for kind, schema in schemas.items(): registry.register_kind(kind, schema, str)
    return registry
