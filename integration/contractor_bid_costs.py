"""Adopt an original declared price for one explicitly mapped Contractor A02 line."""
from typing import Literal

from integration.tender_source_policy import supports_tender_source

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Reference, TextId, TimePoint, ref_type, walk_references
from src.actions.contracts.contractor_bid_objects import (
    ContractorBidCostView, ContractorBidPackageView, ContractorBidQuantityView, ContractorBidReferenceView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import CostSource, QSCostPriceView
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class ContractorBidCostAdoptionView(CostSource):
    """Independent Contractor adoption; a QS estimate alone is not private cost authority."""
    ref: ref_type('ContractorCostAdoption')
    run_id: TextId
    organization_id: TextId
    cost_ref: ref_type('CostBasis')
    package_ref: ref_type('ProcurementPackage')
    package_sha256: Digest
    quantity_basis_ref: ref_type('QuantityBasis')
    quantity_sha256: Digest
    quantity_line_key: TextId
    price_ref: ref_type('Price')
    price_sha256: Digest
    measurement_rule_ref: ref_type('MeasurementRule')
    measurement_rule_code: TextId
    delivery_code: TextId
    method_ref: ref_type('Method')
    adoption_evidence_refs: list[ref_type('Evidence')]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['CONTRACTOR-A02']
    authored_at: TimePoint
    allow_synthetic_assumptions: bool = False


def prepare_contractor_bid_cost(*, context, reading, adoption_ref, validate_current):
    """Copy an exact authorized price without dividing totals or executing a method.

    The host must validate actual source applicability and independent adoption.
    The caller must publish the returned projection at a fresh authorized token.
    QuantityBasis remains the original A02 schema; QS proxy quantities are not
    coerced into measured procurement quantities.
    """
    if not isinstance(reading, ActionReadView) or context.contract_ref.id != 'CONTRACTOR-A02':
        raise ValueError('Cost production requires its actual authorized A02 reading')
    reading.check_method_context(context, 'CONTRACTOR-A02')
    if not callable(validate_current):
        raise ValueError('Cost adoption requires an explicit current host validator')

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise ValueError('Cost production requires the exact original source schema and version')
        return row

    now = context.business_time

    def current(row):
        if (not scope_covers(row.scope, context.scope)
                or row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                or not row.effective_window.contains(now)):
            raise ValueError('Cost source is outside the current authorized scope or time')

    try:
        basis = read(Reference.model_validate(adoption_ref), ContractorBidCostAdoptionView)
        current(basis)
        if (basis.run_id != context.run_id or basis.organization_id != reading.organization_id
                or basis.scope != context.scope):
            raise ValueError('Cost adoption changes its original run, Contractor or scope')
        grant = read(basis.author_authority_ref, Authorization)
        assignment = reading.resolve(basis.author_function_ref)
        if (not isinstance(assignment, RoleAssignment) or assignment.role != 'Contractor'
                or assignment.function_ref != basis.author_function_ref
                or grant.organization_id != basis.organization_id or grant.actor_id != basis.author_actor_id
                or grant.function_ref != basis.author_function_ref or basis.author_action_id not in grant.action_ids
                or not any(scope_covers(scope, basis.scope) for scope in grant.scopes)
                or basis.authored_at.clock_ref != now.clock_ref or basis.authored_at.offset > basis.available_at.offset
                or not grant.validity.contains(basis.authored_at) or not grant.validity.contains(now)
                or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Cost adoption lacks its original Contractor author authority')
        package = read(basis.package_ref, ContractorBidPackageView)
        quantity = read(basis.quantity_basis_ref, ContractorBidQuantityView)
        price = read(basis.price_ref, QSCostPriceView)
        for row, expected in ((package, basis.package_sha256), (quantity, basis.quantity_sha256),
                              (price, basis.price_sha256)):
            current(row)
            if task_digest(row.model_dump(mode='json')) != expected:
                raise ValueError('Cost adoption substitutes an original source projection')
        if (reading.organization_id not in package.recipient_organization_ids
                or quantity.ref not in package.quantity_refs or quantity.package_ref != package.ref
                or not set(quantity.deliverable_refs) <= set(package.deliverable_refs)
                or quantity.measurement_rule_ref != basis.measurement_rule_ref):
            raise ValueError('Adopted cost changes the original procurement quantity or measurement rule')
        lines = [row for row in quantity.lines if row.local_key == basis.quantity_line_key]
        if len(lines) != 1:
            raise ValueError('Cost adoption requires one exact original quantity line')
        line = lines[0]
        if (len(set(line.coverage_keys)) != len(line.coverage_keys)
                or len(set(price.coverage_keys)) != len(price.coverage_keys)
                or set(price.coverage_keys) != set(line.coverage_keys)
                or not set(line.coverage_keys) <= set(package.coverage_keys)
                or set(price.excluded_coverage_keys).intersection(line.coverage_keys)
                or price.region_id != package.region_id
                or price.measurement_rule_code != basis.measurement_rule_code
                or price.delivery_code != basis.delivery_code or not price.valid_pricing_window.contains(now)):
            raise ValueError('Original price does not exactly cover the declared quantity, region, rule and delivery')
        references = [read(ref, ContractorBidReferenceView)
                      for ref in (basis.measurement_rule_ref, basis.method_ref)]
        for row in references:
            current(row)
            if row.package_ref != package.ref or row.organization_id not in (None, reading.organization_id):
                raise ValueError('Cost method/rule changes the original procurement or Contractor')
        if line.quantity.state == 'known' and line.quantity.value.unit != price.quantity_unit:
            raise ValueError('Cost adoption cannot convert original quantity units')
        if not basis.adoption_evidence_refs:
            return {'kind': 'needs_information', 'missing_fields': ['independent_contractor_cost_adoption'],
                    'requested_refs': [basis.ref]}
        unique_refs(basis.adoption_evidence_refs)
        source_refs = [*package.evidence_refs, *quantity.evidence_refs, *price.evidence_refs,
                       *[ref for row in references for ref in row.evidence_refs]]
        value_refs = [ref for value in (price.unit_rate, line.quantity)
                      for ref in walk_references(value) if ref.kind == 'Evidence']
        if set(basis.adoption_evidence_refs).intersection([*source_refs, *value_refs]):
            raise ValueError('Source price/quantity evidence cannot substitute independent Contractor adoption')
        evidence_refs = list({ref.key(): ref for ref in [*basis.evidence_refs, *basis.adoption_evidence_refs,
            *source_refs, *value_refs, *grant.basis_refs, *assignment.basis_refs]}.values())
        for ref in evidence_refs:
            evidence = read(ref, EvidenceRecord)
            if (evidence.effective_window is not None and not evidence.effective_window.contains(now)
                    or ref in basis.adoption_evidence_refs and not supports_tender_source(
                        evidence, allow_synthetic_assumptions=basis.allow_synthetic_assumptions)):
                raise ValueError('Cost source/adoption evidence is not current and independently observed')
        grants = [reading.resolve(ref) for ref in context.authorization_refs]
        if basis.cost_ref not in context.visible_refs or not any(
                isinstance(row, Authorization) and row.organization_id == reading.organization_id
                and row.actor_id == context.actor_id and row.function_ref == context.function_ref
                and 'CONTRACTOR-A02' in row.action_ids and row.validity.contains(now)
                and any(scope_covers(scope, context.scope) for scope in row.scopes)
                and basis.cost_ref in row.readable_refs for row in grants):
            raise ValueError('Produced cost target lacks current explicit read authority')
        if validate_current(context=context.model_copy(deep=True), adoption=basis.model_copy(deep=True),
                package=package.model_copy(deep=True), quantity=quantity.model_copy(deep=True),
                price=price.model_copy(deep=True)) is not None:
            raise ValueError('Actual original price and independent adoption require current host validation')
        projection = ContractorBidCostView(ref=basis.cost_ref, organization_id=reading.organization_id,
            package_ref=package.ref, quantity_basis_ref=quantity.ref, quantity_line_key=line.local_key,
            unit_rate=price.unit_rate.model_copy(deep=True), quantity_unit=price.quantity_unit,
            region_id=price.region_id, coverage_keys=list(price.coverage_keys), method_ref=basis.method_ref,
            status=quantity.status, author_actor_id=basis.author_actor_id,
            author_function_ref=basis.author_function_ref, author_authority_ref=basis.author_authority_ref,
            scope=context.scope, available_at=now, effective_window={'start': now, 'end': now, 'bounds': 'closed_closed'},
            evidence_refs=[ref.model_dump(mode='python') for ref in evidence_refs])
        return {'kind': 'prepared', 'cost_projection': projection,
            'adoption_ref': basis.ref, 'price_ref': price.ref,
            'source_mode': 'fixture' if context.execution_mode == 'offline_fixture' else 'formal',
            'cost_sha256': task_digest(projection.model_dump(mode='json')),
            'adoption_sha256': task_digest(basis.model_dump(mode='json')), 'price_sha256': basis.price_sha256,
            'quantity_sha256': basis.quantity_sha256, 'context_sha256': task_digest(context.model_dump(mode='json')),
            'limitations': ['Snapshot-only projection; publish at a fresh authorized token before A02 execution.',
                            'Original rate/unknown state preserved; no totals, FX, productivity or price inferred.',
                            'A02 independently checks completeness, pricing and programme; no macro effect.']}
    finally:
        reading.recheck()
