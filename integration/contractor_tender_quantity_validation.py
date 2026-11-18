"""Validate an independently supplied documentary QS-to-Contractor quantity relation."""
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from integration.contractor_bid_quantities import ContractorQuantityDesignLink, ContractorQuantityMappingView
from integration.tender_source_policy import TenderDocumentOrigin, validate_document_origin
from src.actions.contracts.common import (
    ActionContext, EvidenceRecord, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow, ref_type,
)
from src.actions.contracts.qs_procurement_objects import (
    QSProcurementDesignView, QSProcurementDocumentView, QSProcurementQuantityView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import Digest


class TenderQuantityRelationSettings(StrictRecord):
    evidence_ref: ref_type('Evidence')
    evidence_locator: TextId
    file_path: TextId
    file_sha256: Digest
    allow_synthetic: bool = False


class TenderQuantityRelationSource(TenderQuantityRelationSettings):
    mapping_ref: ref_type('ContractorQuantityMapping')


class TenderQuantityRelationSetSettings(StrictRecord):
    relations: Annotated[list[TenderQuantityRelationSource], Field(min_length=1)]

    @model_validator(mode='after')
    def unique_relations(self):
        if len({row.mapping_ref.key() for row in self.relations}) != len(self.relations):
            raise ValueError('Quantity observations repeat the same full mapping reference')
        return self


TenderQuantityValidationSettings = TenderQuantityRelationSettings | TenderQuantityRelationSetSettings


def _select_relation(settings, mapping_ref):
    if isinstance(settings, TenderQuantityRelationSetSettings) or isinstance(settings, dict) and 'relations' in settings:
        configured = TenderQuantityRelationSetSettings.model_validate(settings).model_copy(deep=True)
        matches = [row for row in configured.relations if row.mapping_ref == mapping_ref]
        if len(matches) != 1:
            raise TaskConflict('Quantity relation lacks an explicitly configured observation for its full original reference')
        return matches[0]
    return TenderQuantityRelationSettings.model_validate(settings).model_copy(deep=True)


class ObservedTenderQuantityRelation(TenderDocumentOrigin):
    """Explicit observed input, never an invented native receipt or measurement."""
    schema_version: Literal['contractor-quantity-relation-observation.v1']
    run_id: TextId
    organization_id: TextId
    scope: ScopeRef
    available_at: TimePoint
    effective_window: TimeWindow
    mapping_ref: ref_type('ContractorQuantityMapping')
    mapping_sha256: Digest
    package_ref: ref_type('ProcurementPackage')
    package_sha256: Digest
    quantity_ref: ref_type('QuantityBasis')
    document_ref: ref_type('ProcurementDocument')
    document_sha256: Digest
    schedule_ref: ref_type('QuantitySchedule')
    schedule_sha256: Digest
    measurement_rule_ref: ref_type('MeasurementRule')
    source_rule_sha256: Digest
    target_rule_sha256: Digest
    design_links: list[ContractorQuantityDesignLink]
    source_open_questions: list[dict]
    source_designs: list[dict]


def _read_relation(config):
    raw = Path(config.file_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != config.file_sha256:
        raise TaskConflict('Independent quantity relation file changed its explicitly configured source SHA')

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Quantity relation file repeats a JSON field')
            value[key] = item
        return value

    def reject_constant(value):
        raise ValueError('Quantity relation file requires finite JSON values')

    value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object, parse_constant=reject_constant)
    return ObservedTenderQuantityRelation.model_validate_json(json.dumps(value, allow_nan=False))


def validate_quantity_relation(*, context, mapping, document, schedule, source_reading, reading, application, settings):
    """Professional quantity callback for the configured tender application.

    Read a supplied real_user/real_public observed relation artifact with the
    original evidence locator/hash and explicit refs. Source and target readings
    retain the original producer's separate schemas and author checks. This
    callback confirms documentary correspondence; it neither measures quantity
    nor confirms a native release/receipt endpoint or clears source limitations.
    The application supplies the artifact, not an automatically generated claim.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    application._check()
    if (not isinstance(reading, ActionReadView) or not isinstance(source_reading, ActionReadView)
            or not isinstance(mapping, ContractorQuantityMappingView)
            or not isinstance(document, QSProcurementDocumentView) or not isinstance(schedule, QSProcurementQuantityView)
            or context.run_id != application.store.run_id or context.contract_ref.id != 'CONTRACTOR-A02'
            or reading.organization_id != source_reading.organization_id
            or reading._organizations is not application.organizations
            or source_reading._organizations is not application.organizations
            or context.execution_mode == 'offline_fixture'
            or reading._resolver.source_mode != 'formal' or source_reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Independent quantity relation requires original current formal A02 source and target readings')
    config = _select_relation(settings, mapping.ref)
    for view in (reading, source_reading):
        view.check_method_context(context, 'CONTRACTOR-A02')
        view.recheck()
    if (reading.resolve(mapping.ref) != mapping or source_reading.resolve(document.ref) != document
            or source_reading.resolve(schedule.ref) != schedule or document.status != 'published'
            or config.evidence_ref not in mapping.relation_evidence_refs):
        raise TaskConflict('Quantity relation substitutes original supplied mappings, source document or independent evidence')
    evidence = reading.resolve(config.evidence_ref)
    if (not isinstance(evidence, EvidenceRecord) or evidence.locator != config.evidence_locator
            or evidence.content_hash != config.file_sha256
            or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
        raise TaskConflict('Quantity relation requires its original currently valid independently observed documentary source')
    observed = _read_relation(config)
    validate_document_origin(observed, evidence, allow_synthetic=config.allow_synthetic)
    if (observed.run_id != context.run_id or observed.organization_id != reading.organization_id
            or observed.scope != context.scope or observed.available_at.clock_ref != context.business_time.clock_ref
            or observed.available_at.offset > context.business_time.offset
            or not observed.effective_window.contains(context.business_time)
            or not observed.effective_window.contains(observed.available_at)):
        raise TaskConflict('Observed quantity relation changes the original recipient, scope or current availability')
    names = ('package_ref', 'package_sha256', 'quantity_ref', 'document_ref', 'document_sha256', 'schedule_ref',
        'schedule_sha256', 'measurement_rule_ref', 'source_rule_sha256', 'target_rule_sha256')
    if (observed.mapping_ref != mapping.ref or observed.mapping_sha256 != task_digest(mapping.model_dump(mode='json'))
            or any(getattr(observed, name) != getattr(mapping, name) for name in names)
            or observed.design_links != mapping.design_links
            or observed.document_sha256 != task_digest(document.model_dump(mode='json'))
            or observed.schedule_sha256 != task_digest(schedule.model_dump(mode='json'))):
        raise TaskConflict('Independent quantity relation does not corroborate the exact original source/target versions')
    questions = [row.model_dump(mode='json') for row in document.draft.open_questions]
    designs = []
    for link in mapping.design_links:
        design = source_reading.resolve(link.design_ref)
        if (not isinstance(design, QSProcurementDesignView)
                or task_digest(design.model_dump(mode='json')) != link.design_sha256):
            raise TaskConflict('Independent quantity relation changes an original QS design source')
        designs.append({'ref': design.ref.model_dump(mode='json'), 'projection_sha256': link.design_sha256,
            'limitations': list(design.limitations)})
    if observed.source_open_questions != questions or observed.source_designs != designs:
        raise TaskConflict('Independent quantity observation drops original unresolved questions or design limitations')
    for view in (reading, source_reading):
        view.recheck()
    if (reading.resolve(config.evidence_ref) != evidence
            or hashlib.sha256(Path(config.file_path).read_bytes()).hexdigest() != config.file_sha256):
        raise TaskConflict('Independent quantity observation changed during source relation validation')
    application._check()
