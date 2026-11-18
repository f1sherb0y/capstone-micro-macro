"""Select original reviewer opinions for a separately authorized author response."""
from integration.architect_review_results import ArchitectReviewResultWorker, SavedArchitectReview
from integration.architect_review_task_reader import (
    ArchitectReviewTaskReader, ArchitectReviewTaskReaderSettings, _bind_review_sources,
)


class ArchitectReviewOpinionReaderSettings(ArchitectReviewTaskReaderSettings):
    """submission_read_context is the current original reviewer's A08 authority.

    recipient_context is the author's distinct current A08 response authority.
    publication_receipt_sha256 pins the original accepted reviewer submission
    receipt, separate from the actual received-opinion receipt in author inputs.
    """


class ArchitectReviewOpinionReader(ArchitectReviewTaskReader):
    """Provide the exact seven parameters required by received-opinion assembly.

    Reuse guarded original-result/hash checks; accept only a completed review,
    never a previous author response. The original assembler and independent
    validators confirm actual opinion/comment reception, authorship, privacy,
    target and author-task relation. This reader creates no opinion, comment,
    response, revised content, use release or regulatory approval.
    """
    SETTINGS_TYPE = ArchitectReviewOpinionReaderSettings
    WORKER_TYPE = ArchitectReviewResultWorker
    SAVED_TYPE = SavedArchitectReview
    SOURCE_ACTION_ID = 'ARCHITECT-A08'
    EXPECTED_CHOICE = 'review'
    RECEIPT_SCHEMA = 'architect-review-saved-receipt.v1'
    PARAMETER_PREFIX = 'reviewer'
    READ_CONTEXT_PARAMETER = 'reviewer_read_context'


def bind_review_opinion_sources(*, sources, reader, validate_mapping, version):
    """Pair the actual opinion reader and independent current author-input mapping."""
    if not isinstance(reader, ArchitectReviewOpinionReader):
        raise ValueError('Opinion binding requires the original reviewer opinion reader')
    return _bind_review_sources(sources=sources, reader=reader, validate_mapping=validate_mapping, version=version,
        source_action='ARCHITECT-A08', reader_field='read_review_opinion', validator_field='validate_review_opinion_mapping',
        schema_version='v3-review-opinion-source-binding.v1', evidence_field='v3_review_opinion_binding')
