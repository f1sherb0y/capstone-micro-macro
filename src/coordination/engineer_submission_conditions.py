"""Resolve original Engineer A07 receipts before fresh independent submission judgment."""
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.engineer_submission_objects import EngineerSubmissionSavedView
from src.actions.contracts.references import ActionReadView
from src.coordination.architect_submission_conditions import _professional_original_submission_receipt_profile


@dataclass(frozen=True)
class EngineerSubmissionReceiptConditionReading:
    context: ActionContext
    reading: ActionReadView
    submission_ref: Reference


def engineer_original_submission_receipt_profile(read_current, validate_relation):
    """Keep original operation/choice and exact deliverable, command and payload.

    Actual formal sources and independent native query evidence must confirm an
    uncommitted command with no duplicate version work or fees. A ready query
    only permits fresh judgment; signing authority, professional checks, release
    conditions and publication still pass the original A07 gates independently.
    The application holds its source/authority/journal guard for the entire wake.
    """
    return _professional_original_submission_receipt_profile(read_current, validate_relation,
        action_id='ENGINEER-A07', role='Engineer', submission_schema=EngineerSubmissionSavedView,
        reading_type=EngineerSubmissionReceiptConditionReading, extra_identity_fields=('operation_id', 'choice'))
