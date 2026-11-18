"""Project actual GBA shared capacity using its explicit original calendar mapping."""
from copy import deepcopy
from typing import Literal

from integration.bindings.gba_v1_capacity import GbaCapacityMappingView, prepare_gba_capacity_input
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Known, Measured, Reference, TextId, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_quote_objects import QuoteCapacityView, QuoteCommitment, QuotePool, QuoteResourcePoolView
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierQuoteCapacityAdoptionView(GovReviewAuthored):
    """Own Supplier adoption of exact macro facts and independently sourced calendar."""
    ref: ref_type('SupplierQuoteCapacityAdoption')
    run_id: TextId
    organization_id: TextId
    source_record_sha256: Digest
    mapping_ref: ref_type('GbaCapacityMapping')
    mapping_sha256: Digest
    capacity_ref: ref_type('SupplierCapacity')
    adoption_evidence_refs: list[ref_type('Evidence')]
    author_action_id: Literal['SUPPLIER-A03']


def add_supplier_quote_capacity_schemas(schemas):
    schemas.register_kind('GbaCapacityMapping', GbaCapacityMappingView, str)
    schemas.register_kind('SupplierQuoteCapacityAdoption', SupplierQuoteCapacityAdoptionView, str)
    return schemas


def prepare_supplier_quote_capacity(source, *, context, reading, adoption_ref, validate_current):
    """Copy normalized totals and sourced commitments without a feasibility call.

    The existing source producer reconciles actual current occupancy with the
    independent calendar. It requires complete supported mapping; missing data
    retains its original needs_information outcome. No scalar splitting, physical
    conversion, rate assumption or new reservation occurs. A03 derives its own
    actual demands later. Publish the complete capacity/pool set at a fresh token.
    """
    if (not isinstance(reading, ActionReadView) or context.contract_ref.kind != 'ActionContract'
            or context.contract_ref.id != 'SUPPLIER-A03' or not callable(validate_current)
            or not isinstance(source, dict)):
        raise ValueError('Capacity production requires actual A03 reading, macro record and current host validation')
    reading.check_method_context(context, 'SUPPLIER-A03')
    source = deepcopy(source)
    now = context.business_time

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise ValueError('Capacity adoption requires its exact original concrete source version')
        return row

    def evidence(ref, *, observed=False):
        row = read(ref, EvidenceRecord)
        if (observed and row.basis_kind != 'observed'
                or row.effective_window is not None and not row.effective_window.contains(now)):
            raise ValueError('Capacity source/adoption evidence is not current and independently observed')

    try:
        adoption = read(Reference.model_validate(adoption_ref), SupplierQuoteCapacityAdoptionView)
        mapping = read(adoption.mapping_ref, GbaCapacityMappingView)
        if (adoption.run_id != context.run_id or adoption.organization_id != reading.organization_id
                or adoption.author_organization_id != reading.organization_id or adoption.scope != context.scope
                or adoption.source_record_sha256 != source.get('record_sha256')
                or task_digest(mapping.model_dump(mode='json')) != adoption.mapping_sha256
                or adoption.available_at.clock_ref != now.clock_ref or adoption.available_at.offset > now.offset
                or not adoption.effective_window.contains(now)):
            raise ValueError('Capacity adoption changes original Supplier, run, scope, record or mapping')
        grant = read(adoption.author_authority_ref, Authorization)
        assignment = reading.resolve(adoption.author_function_ref)
        if (not isinstance(assignment, RoleAssignment) or assignment.role != 'Supplier'
                or assignment.function_ref != adoption.author_function_ref
                or grant.organization_id != reading.organization_id or grant.actor_id != adoption.author_actor_id
                or grant.function_ref != adoption.author_function_ref or adoption.author_action_id not in grant.action_ids
                or not any(scope_covers(scope, adoption.scope) for scope in grant.scopes)
                or adoption.authored_at.clock_ref != now.clock_ref or adoption.authored_at.offset > adoption.available_at.offset
                or not grant.validity.contains(adoption.authored_at) or not adoption.effective_window.contains(adoption.authored_at)):
            raise ValueError('Capacity adoption lacks independent original Supplier author authority')
        prepared = prepare_gba_capacity_input(source, context=context, reading=reading, mapping_ref=mapping.ref)
        if prepared['kind'] != 'prepared':
            return prepared
        data = prepared['data']
        if any(row.resource_ref.kind != 'ResourcePool' or row.resource_kind != row.resource_ref.id for row in data.resources):
            return {'kind': 'needs_information',
                'missing_fields': ['explicit_quote_resource_pool_kind_reference_mapping'], 'requested_refs': [mapping.ref]}
        unique_refs(adoption.adoption_evidence_refs)
        if not adoption.adoption_evidence_refs:
            raise ValueError('Capacity requires independent Supplier adoption evidence')
        source_refs = [*mapping.evidence_refs, mapping.source_evidence_ref, *mapping.calendar_evidence_refs,
            *[row.total.basis_ref for row in data.resources], *[row.quantity.basis_ref for row in data.commitments]]
        if set(adoption.adoption_evidence_refs).intersection(source_refs):
            raise ValueError('Original macro/calendar evidence cannot replace independent Supplier adoption')
        evidence_refs = list({ref.key(): ref for ref in [*source_refs, *adoption.evidence_refs,
            *adoption.adoption_evidence_refs, *grant.basis_refs, *assignment.basis_refs]}.values())
        for ref in evidence_refs:
            evidence(ref, observed=ref in adoption.adoption_evidence_refs)
        targets = [adoption.capacity_ref, *[row.resource_ref for row in data.resources]]
        unique_refs(targets)
        grants = [reading.resolve(ref) for ref in context.authorization_refs]
        for target in targets:
            if target not in context.visible_refs or not any(isinstance(row, Authorization)
                    and row.organization_id == reading.organization_id and row.actor_id == context.actor_id
                    and row.function_ref == context.function_ref and 'SUPPLIER-A03' in row.action_ids
                    and row.validity.contains(now) and target in row.readable_refs
                    and any(scope_covers(scope, context.scope) for scope in row.scopes) for row in grants):
                raise ValueError('Produced capacity/pool target lacks original explicit current read authority')
        if validate_current(context=context.model_copy(deep=True), adoption=adoption.model_copy(deep=True),
                mapping=mapping.model_copy(deep=True), source=deepcopy(source)) is not True:
            raise ValueError('Actual macro snapshot, calendar completeness and Supplier adoption require host verification')
        capacity = QuoteCapacityView(ref=adoption.capacity_ref, organization_id=reading.organization_id,
            as_of=now, resource_coverage='complete', commitment_coverage='complete',
            resources=[QuotePool(resource_ref=row.resource_ref, region_id=row.region_id,
                total=Known[Measured](state='known', value=row.total.model_copy(deep=True)),
                effective_window=row.effective_window.model_copy(deep=True)) for row in data.resources],
            commitments=[QuoteCommitment(**row.model_dump(mode='python')) for row in data.commitments],
            evidence_refs=evidence_refs)
        resources = [QuoteResourcePoolView(ref=row.resource_ref, organization_id=reading.organization_id,
            region_id=row.region_id, evidence_refs=evidence_refs) for row in data.resources]
        return {'kind': 'prepared', 'capacity_projection': capacity, 'resource_projections': resources,
            'capacity_sha256': task_digest(capacity.model_dump(mode='json')),
            'objects_sha256': task_digest([row.model_dump(mode='json') for row in [capacity, *resources]]),
            'source_record': deepcopy(source), 'source_record_sha256': prepared['source_record_sha256'],
            'capacity_input_sha256': prepared['input_sha256'], 'mapping_sha256': adoption.mapping_sha256,
            'adoption_sha256': task_digest(adoption.model_dump(mode='json')),
            'context_sha256': task_digest(context.model_dump(mode='json')), 'source_mode': prepared['source_mode'],
            'limitations': ['Snapshot only; publish capacity and original pool objects at a fresh authorized token.',
                'Original normalized precision retained; no physical productivity, feasibility or reservation inferred.']}
    finally:
        reading.recheck()
