"""Keep development assumptions distinct from observed documentary/native facts."""
from typing import Literal

from src.actions.contracts.common import EvidenceRecord, StrictRecord
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.coordination.tasks import TaskConflict


class TenderSimulationSource(GovReviewAuthored):
    # Formal here means an authorized source transport, not real-world truth.
    # The opt-in is part of the versioned authored input and its digest.
    allow_synthetic_assumptions: bool = False


class TenderDocumentOrigin(StrictRecord):
    source_mode: Literal['documentary', 'synthetic_assumption'] = 'documentary'


def supports_tender_source(evidence, *, allow_synthetic_assumptions=False):
    """Accept an assumption only with both explicit policy and original labels."""
    return isinstance(evidence, EvidenceRecord) and (
        evidence.basis_kind == 'observed' or allow_synthetic_assumptions
        and evidence.source_kind == 'synthetic' and evidence.basis_kind == 'assumed')


def validate_document_origin(document, evidence, *, allow_synthetic=False):
    """An explicit synthetic input never acquires documentary/observed status."""
    if (not isinstance(evidence, EvidenceRecord)
            or document.source_mode == 'documentary' and not (
                evidence.source_kind in {'real_user', 'real_public'} and evidence.basis_kind == 'observed')
            or document.source_mode == 'synthetic_assumption' and not (
                allow_synthetic and evidence.source_kind == 'synthetic' and evidence.basis_kind == 'assumed')):
        raise TaskConflict('Tender document requires matching original provenance and explicit opt-in for synthetic assumptions')
