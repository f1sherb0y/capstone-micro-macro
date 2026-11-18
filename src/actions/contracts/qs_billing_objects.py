"""QS service fees use distinct projections with shared fee-record shapes.

Structural inheritance does not grant engineering or QS authority; the processor
binds the original QS-A10 function, organization and independent authorization.
"""
from src.actions.contracts.engineer_billing_objects import (
    EngineerBillingEngagementView, EngineerBillingProfileView, EngineerBillingClauseView,
    EngineerBillingWorkFactView, EngineerBillingCalculationView, EngineerBillingClaimView,
    EngineerBillingReceiptView, EngineerBillingExecutionView, EngineerBillingQuestionView,
    EngineerBillingAdvanceCreditView, EngineerBillingPayableView,
    EngineerBillingCostAccountingLine, EngineerBillingCostAccountingView,
)
from src.actions.contracts.service_objects import service_intake_schemas
from typing import Annotated, Literal
from pydantic import Field
from src.actions.contracts.common import TextId, TimePoint, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.methods.models import Digest


class QSBillingEngagementView(EngineerBillingEngagementView):
    pass


class QSBillingProfileView(EngineerBillingProfileView):
    pass


class QSBillingClauseView(EngineerBillingClauseView):
    pass


class QSBillingWorkFactView(EngineerBillingWorkFactView):
    pass


class QSBillingCalculationView(EngineerBillingCalculationView):
    pass


class QSBillingClaimView(EngineerBillingClaimView):
    pass


class QSBillingReceiptView(EngineerBillingReceiptView):
    pass


class QSBillingExecutionView(EngineerBillingExecutionView):
    pass


class QSBillingQuestionView(EngineerBillingQuestionView):
    pass


class QSBillingAdvanceCreditView(EngineerBillingAdvanceCreditView):
    pass


class QSBillingPayableView(EngineerBillingPayableView):
    pass


class QSBillingCostAccountingLine(EngineerBillingCostAccountingLine):
    pass


class QSBillingCostAccountingView(EngineerBillingCostAccountingView):
    lines: list[QSBillingCostAccountingLine]


class QSBillingClaimHandoffBasisView(GovReviewAuthored):
    """Independent observed relation between a saved proposal and a native claim."""
    ref: ref_type('QSBillingClaimHandoffBasis')
    run_id: TextId
    organization_id: TextId
    task_sha256: Digest
    record_sha256: Digest
    input_sha256: Digest
    context_sha256: Digest
    result_sha256: Digest
    audit_sha256: Digest
    source_reading_sha256: Digest
    claim_ref: ref_type('FeeClaim')
    claim_sha256: Digest
    registered_at: TimePoint
    native_claim_id: TextId
    native_event_id: TextId
    native_source_sha256: Digest
    native_evidence_ref: ref_type('Evidence')
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['QS-A10']


def qs_billing_types():
    return {
        'Engagement': QSBillingEngagementView,
        'BillingProfile': QSBillingProfileView,
        'BillingClause': QSBillingClauseView,
        'WorkFact': QSBillingWorkFactView,
        'FeeCalculation': QSBillingCalculationView,
        'FeeClaim': QSBillingClaimView,
        'PaymentReceipt': QSBillingReceiptView,
        'PaymentExecution': QSBillingExecutionView,
        'EvidenceTarget': QSBillingQuestionView,
        'AdvanceCredit': QSBillingAdvanceCreditView,
        'Obligation': QSBillingPayableView,
        'WorkCostAccounting': QSBillingCostAccountingView,
    }


def qs_billing_schemas():
    schemas = service_intake_schemas(overrides=qs_billing_types())
    schemas.register_kind('QSBillingClaimHandoffBasis', QSBillingClaimHandoffBasisView, str)
    return schemas
