"""Validate independent adoption documents, with explicit synthetic development inputs."""
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from integration.contractor_bid_costs import ContractorBidCostAdoptionView
from integration.tender_source_policy import TenderDocumentOrigin, validate_document_origin
from src.actions.contracts.common import (
    ActionContext, EvidenceRecord, Money, ScopeRef, StrictRecord, TextId, TimePoint, TimeWindow,
    ValueState, ref_type, walk_references,
)
from src.actions.contracts.contractor_bid_objects import (
    ContractorBidPackageView, ContractorBidQuantityLine, ContractorBidQuantityView,
)
from src.actions.contracts.qs_cost_objects import QSCostPriceView
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import Digest


class TenderCostAdoptionSettings(StrictRecord):
    evidence_ref: ref_type('Evidence')
    evidence_locator: TextId
    file_path: TextId
    file_sha256: Digest
    allow_synthetic: bool = False


class TenderCostAdoptionSource(TenderCostAdoptionSettings):
    adoption_ref: ref_type('ContractorCostAdoption')


class TenderCostAdoptionSetSettings(StrictRecord):
    adoptions: Annotated[list[TenderCostAdoptionSource], Field(min_length=1)]

    @model_validator(mode='after')
    def unique_adoptions(self):
        if len({row.adoption_ref.key() for row in self.adoptions}) != len(self.adoptions):
            raise ValueError('Cost observations repeat the same full adoption reference')
        return self


TenderCostValidationSettings = TenderCostAdoptionSettings | TenderCostAdoptionSetSettings


def _select_adoption(settings, adoption_ref):
    if isinstance(settings, TenderCostAdoptionSetSettings) or isinstance(settings, dict) and 'adoptions' in settings:
        configured = TenderCostAdoptionSetSettings.model_validate(settings).model_copy(deep=True)
        matches = [row for row in configured.adoptions if row.adoption_ref == adoption_ref]
        if len(matches) != 1:
            raise TaskConflict('Cost adoption lacks an explicitly configured observation for its full original reference')
        return matches[0]
    return TenderCostAdoptionSettings.model_validate(settings).model_copy(deep=True)


class ObservedTenderCostAdoption(TenderDocumentOrigin):
    """Independent adoption input; no inferred cost, procurement order or cash effect."""
    schema_version: Literal['contractor-cost-adoption-observation.v1']
    run_id: TextId
    organization_id: TextId
    scope: ScopeRef
    available_at: TimePoint
    effective_window: TimeWindow
    adoption_ref: ref_type('ContractorCostAdoption')
    adoption_sha256: Digest
    cost_ref: ref_type('CostBasis')
    package_ref: ref_type('ProcurementPackage')
    package_sha256: Digest
    quantity_basis_ref: ref_type('QuantityBasis')
    quantity_sha256: Digest
    quantity_line_key: TextId
    quantity_line: ContractorBidQuantityLine
    price_ref: ref_type('Price')
    price_sha256: Digest
    price_source_locator: TextId
    unit_rate: ValueState[Money]
    quantity_unit: TextId
    region_id: TextId
    coverage_keys: list[TextId]
    excluded_coverage_keys: list[TextId]
    measurement_rule_ref: ref_type('MeasurementRule')
    measurement_rule_code: TextId
    delivery_code: TextId
    method_ref: ref_type('Method')
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    authored_at: TimePoint


def _read_adoption(config):
    raw = Path(config.file_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != config.file_sha256:
        raise TaskConflict('Independent cost adoption file differs from its explicitly configured SHA')

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Cost adoption file repeats a JSON field')
            value[key] = item
        return value

    def reject_constant(value):
        raise ValueError('Cost adoption file requires finite JSON values')

    value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique_object, parse_constant=reject_constant)
    return ObservedTenderCostAdoption.model_validate_json(json.dumps(value, allow_nan=False))


def validate_cost_adoption(*, context, adoption, package, quantity, price, application, settings):
    """Configured professional.cost callback over actual supplied documentary sources.

    The original producer retains author authority, price applicability, units,
    coverage and method checks. This callback corroborates the explicit private
    adoption against independent documentary input (or explicitly enabled,
    labelled synthetic assumptions) and re-reads the
    exact current originals. It neither authenticates network origin nor turns a
    QS estimate into private costs, a native procurement order or payment fact.
    Unknown quantities and rates remain their original typed unknown states.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    application._check()
    if (application.host is None or context.run_id != application.store.run_id
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'CONTRACTOR-A02'
            or context.execution_mode == 'offline_fixture' or not isinstance(adoption, ContractorBidCostAdoptionView)
            or not isinstance(package, ContractorBidPackageView) or not isinstance(quantity, ContractorBidQuantityView)
            or not isinstance(price, QSCostPriceView)):
        raise TaskConflict('Cost adoption requires the installed original application and formal typed A02 sources')
    config = _select_adoption(settings, adoption.ref)
    reading = application.host.pipeline.assembler.build_capacity_reading(context)
    if (reading._organizations is not application.organizations or reading._resolver.source_mode != 'formal'
            or reading.organization_id != adoption.organization_id or adoption.run_id != context.run_id
            or adoption.scope != context.scope or config.evidence_ref not in adoption.adoption_evidence_refs):
        raise TaskConflict('Cost adoption changes current original Contractor authority or independent evidence')
    for source in (adoption, package, quantity, price):
        if reading.resolve(source.ref) != source:
            raise TaskConflict('Cost adoption substitutes an original currently authorized source projection')
    lines = [line for line in quantity.lines if line.local_key == adoption.quantity_line_key]
    if len(lines) != 1:
        raise TaskConflict('Independent cost adoption requires one exact original quantity line')
    line = lines[0]
    source_evidence = [*package.evidence_refs, *quantity.evidence_refs, *price.evidence_refs]
    source_evidence.extend(ref for value in (price.unit_rate, line.quantity)
        for ref in walk_references(value) if ref.kind == 'Evidence')
    if config.evidence_ref in source_evidence:
        raise TaskConflict('Original price or quantity evidence cannot substitute independent Contractor adoption')
    evidence = reading.resolve(config.evidence_ref)
    if (not isinstance(evidence, EvidenceRecord) or evidence.locator != config.evidence_locator
            or evidence.content_hash != config.file_sha256
            or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
        raise TaskConflict('Cost adoption lacks its original currently valid independent observed documentary source')
    observed = _read_adoption(config)
    validate_document_origin(observed, evidence, allow_synthetic=config.allow_synthetic)
    now = context.business_time
    if (observed.run_id != context.run_id or observed.organization_id != reading.organization_id
            or observed.scope != context.scope or observed.available_at.clock_ref != now.clock_ref
            or observed.available_at.clock_ref != adoption.authored_at.clock_ref
            or observed.available_at.offset < adoption.authored_at.offset
            or observed.available_at.offset > now.offset or not observed.effective_window.contains(now)
            or not observed.effective_window.contains(observed.available_at)):
        raise TaskConflict('Observed cost adoption changes its original recipient, scope or current availability')
    names = ('cost_ref', 'package_ref', 'package_sha256', 'quantity_basis_ref', 'quantity_sha256', 'quantity_line_key',
        'price_ref', 'price_sha256', 'measurement_rule_ref', 'measurement_rule_code', 'delivery_code', 'method_ref',
        'author_actor_id', 'author_function_ref', 'author_authority_ref', 'authored_at')
    if (observed.adoption_ref != adoption.ref
            or observed.adoption_sha256 != task_digest(adoption.model_dump(mode='json'))
            or any(getattr(observed, name) != getattr(adoption, name) for name in names)
            or observed.quantity_line != line or observed.package_sha256 != task_digest(package.model_dump(mode='json'))
            or observed.quantity_sha256 != task_digest(quantity.model_dump(mode='json'))
            or observed.price_sha256 != task_digest(price.model_dump(mode='json'))):
        raise TaskConflict('Independent cost observation does not corroborate the exact original adoption and source versions')
    if (observed.price_source_locator != price.source_locator
            or any(getattr(observed, name) != getattr(price, name) for name in
                ('unit_rate', 'quantity_unit', 'region_id', 'coverage_keys', 'excluded_coverage_keys'))):
        raise TaskConflict('Independent cost adoption changes the original price, unknown state, unit or coverage')
    reading.recheck()
    if (reading.resolve(config.evidence_ref) != evidence
            or hashlib.sha256(Path(config.file_path).read_bytes()).hexdigest() != config.file_sha256):
        raise TaskConflict('Independent cost adoption source changed during validation')
    application._check()
