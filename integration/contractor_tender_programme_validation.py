"""Corroborate original tender planning instructions with independent documentary input."""
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Literal

from integration.contractor_bid_programme import ContractorBidProgrammeBasisView
from integration.tender_source_policy import TenderDocumentOrigin, validate_document_origin
from src.actions.contracts.common import (
    ActionContext, EvidenceRecord, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow,
    ref_type, walk_references,
)
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import Digest


class TenderProgrammeObservationSource(StrictRecord):
    evidence_ref: ref_type('Evidence')
    evidence_locator: TextId
    file_path: TextId
    file_sha256: Digest
    allow_synthetic: bool = False


class TenderProgrammeValidationSettings(StrictRecord):
    observations: dict[TextId, TenderProgrammeObservationSource]


class ObservedTenderProgramme(TenderDocumentOrigin):
    """Supplied observation of authored instructions; never an inferred schedule."""
    schema_version: Literal['contractor-programme-observation.v1']
    run_id: TextId
    organization_id: TextId
    scope: ScopeRef
    available_at: TimePoint
    effective_window: TimeWindow
    basis: ContractorBidProgrammeBasisView


def _read_observation(config):
    raw = Path(config.file_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != config.file_sha256:
        raise TaskConflict('Planning observation differs from its explicitly configured original file SHA')

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Planning observation repeats a JSON field')
            value[key] = item
        return value

    def reject_constant(value):
        raise ValueError('Planning observation requires finite JSON values')

    value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object, parse_constant=reject_constant)
    return ObservedTenderProgramme.model_validate_json(json.dumps(value, allow_nan=False))


def validate_programme(*, context, basis, sources, application, settings):
    """Check independent input; development assumptions require explicit opt-in.

    The producer retains author authority, method, coverage, whole-line target,
    dependency and allocation checks. This gate corroborates the complete basis
    and re-reads its exact original source versions. It does not generate the
    observation, calculate productivity, certify feasibility, reserve resources
    or convert a plan into physical work or a native receipt.
    """
    configuration = TenderProgrammeValidationSettings.model_validate(settings).model_copy(deep=True)
    context = ActionContext.model_validate(context).model_copy(deep=True)
    config = configuration.observations.get(context.operation_id)
    application._check()
    if (config is None or application.host is None or context.run_id != application.store.run_id
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'CONTRACTOR-A02'
            or context.execution_mode == 'offline_fixture' or not isinstance(basis, ContractorBidProgrammeBasisView)
            or not isinstance(sources, list) or not sources):
        raise TaskConflict('Programme requires original formal A02 sources and an explicit operation observation')
    application.host._check(bound=True)
    reading = application.host.pipeline.assembler.build_capacity_reading(context)
    reading.check_method_context(context, 'CONTRACTOR-A02')
    if (reading._organizations is not application.organizations or reading._resolver.source_mode != 'formal'
            or reading.organization_id != basis.organization_id or basis.run_id != context.run_id
            or basis.scope != context.scope or reading.resolve(basis.ref) != basis
            or config.evidence_ref not in basis.planning_evidence_refs):
        raise TaskConflict('Programme substitutes its original authorized basis, organization or planning evidence')
    keys = [item.ref.key() for item in basis.source_digests]
    if len(set(keys)) != len(keys):
        raise TaskConflict('Planning basis repeats an original source reference')
    originals = []
    for item in basis.source_digests:
        source = reading.resolve(item.ref)
        if task_digest(source.model_dump(mode='json')) != item.sha256:
            raise TaskConflict('Programme source differs from its original authored projection digest')
        originals.append(source)
    # TimeWindow projections have no embedded ref. Compare the complete typed
    # source multiset while retaining each explicit ref and SHA in the basis.
    if Counter(task_digest(item.model_dump(mode='json')) for item in sources) != Counter(
            task_digest(item.model_dump(mode='json')) for item in originals):
        raise TaskConflict('Programme callback changes or omits the original full source projection set')
    original_evidence = {ref.key() for source in originals for ref in walk_references(source)
        if ref.kind == 'Evidence'}
    if config.evidence_ref.key() in original_evidence:
        raise TaskConflict('Original quantities or resources cannot substitute independent planning instructions')
    evidence = reading.resolve(config.evidence_ref)
    if (not isinstance(evidence, EvidenceRecord) or evidence.locator != config.evidence_locator
            or evidence.content_hash != config.file_sha256
            or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
        raise TaskConflict('Programme lacks its current independent observed documentary input')
    observed = _read_observation(config)
    validate_document_origin(observed, evidence, allow_synthetic=config.allow_synthetic)
    now = context.business_time
    if (observed.run_id != context.run_id or observed.organization_id != reading.organization_id
            or observed.scope != context.scope or observed.available_at.clock_ref != now.clock_ref
            or observed.available_at.clock_ref != basis.authored_at.clock_ref
            or observed.available_at.offset < basis.authored_at.offset or observed.available_at.offset > now.offset
            or not observed.effective_window.contains(now)
            or not observed.effective_window.contains(observed.available_at) or observed.basis != basis):
        raise TaskConflict('Observed programme changes the full original instructions, author, sources or availability')
    reading.recheck()
    if (reading.resolve(basis.ref) != basis or reading.resolve(config.evidence_ref) != evidence
            or hashlib.sha256(Path(config.file_path).read_bytes()).hexdigest() != config.file_sha256):
        raise TaskConflict('Original planning basis or independent observation changed during validation')
    application.host._check(bound=True)
    application._check()
