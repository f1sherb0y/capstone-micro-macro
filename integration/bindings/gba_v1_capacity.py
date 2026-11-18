"""Produce capacity inputs only with explicitly sourced GBA calendar semantics."""
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from integration.tender_source_policy import TenderSimulationSource, supports_tender_source

from src.actions.contracts.common import EvidenceRecord, Known, Reference, TextId, TimePoint, ValueState, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_bid_objects import contractor_bid_schemas
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.owner_study_objects import unique_refs
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers
from src.methods.capacity import CapacityInput
from src.coordination.tasks import task_digest


class GbaCapacityMappingView(TenderSimulationSource):
    """Independent host calendar/region/kind evidence, never inferred from tick."""
    ref: ref_type('GbaCapacityMapping')
    organization_id: TextId
    run_id: TextId
    simulation_id: TextId
    source_record_sha256: Digest
    source_evidence_ref: ref_type('Evidence')
    calendar_evidence_refs: list[ref_type('Evidence')]
    supported: ValueState[bool]
    coverage: Literal['complete','partial','unknown']
    as_of: TimePoint
    data: CapacityInput


def gba_capacity_source_schemas():
    return contractor_bid_schemas({'GbaCapacityMapping':GbaCapacityMappingView})


def prepare_gba_capacity_input(source, *, context, reading, mapping_ref=None):
    """Keep source numbers/units and demand windows exact; do not calculate.

    Host supplies an authorized complete mapping with independently sourced
    future occupancy, location, resource kind, clock and demands. Formal reads
    require observed calendar evidence; offline fixtures may declare assumptions.
    The result is method input, never a capacity result, reservation or release.
    """
    def missing(*fields):
        return {'kind':'needs_information','missing_fields':list(fields),
                'requested_refs':[] if mapping_ref is None else [mapping_ref]}

    if (not isinstance(source,dict) or source.get('schema_version') != 'gba-v1-enterprise-resources.v1'
            or source.get('macro_version') != 'gba-public-2026-08-21'
            or source.get('resource_unit') != 'normalized_enterprise_capacity'
            or task_digest(source.get('facts')) != source.get('facts_sha256')
            or task_digest({key:value for key,value in source.items() if key != 'record_sha256'}) != source.get('record_sha256')):
        raise ValueError('Capacity producer requires an intact original GBA resource source record')
    if not isinstance(reading,ActionReadView):
        raise ValueError('Capacity producer requires an actual authorized action read view')
    reading.check_method_context(context,context.contract_ref.id)
    if source['run_id'] != context.run_id or source['organization_id'] != reading.organization_id:
        raise ValueError('Capacity source changes original run or private enterprise recipient')
    if mapping_ref is None:
        return missing('explicit_clock_region_resource_kind_mapping','complete_sourced_future_occupancy_calendar','authorized_capacity_demands')
    mapping_ref = Reference.model_validate(mapping_ref)
    try:
        mapping = reading.resolve(mapping_ref)
        if not isinstance(mapping,GbaCapacityMappingView) or mapping.ref != mapping_ref:
            raise ValueError('Capacity producer lacks its concrete sourced mapping schema')
        if (mapping.organization_id != reading.organization_id or mapping.run_id != context.run_id
                or mapping.simulation_id != source['simulation_id'] or mapping.scope != context.scope
                or mapping.source_record_sha256 != source['record_sha256']):
            raise ValueError('Capacity mapping substitutes original enterprise, scope, simulation or snapshot')
        now = context.business_time
        if (mapping.as_of != now or mapping.available_at.clock_ref != now.clock_ref or mapping.available_at.offset > now.offset
                or mapping.effective_window.start.clock_ref != now.clock_ref
                or mapping.effective_window.end.clock_ref != now.clock_ref
                or not mapping.effective_window.contains(now)):
            return missing('current_sourced_capacity_mapping')
        grant = reading.resolve(mapping.author_authority_ref)
        assignment = reading.resolve(mapping.author_function_ref)
        if (not isinstance(grant,Authorization) or not isinstance(assignment,RoleAssignment)
                or mapping.author_organization_id != reading.organization_id
                or grant.organization_id != mapping.author_organization_id
                or grant.actor_id != mapping.author_actor_id or grant.function_ref != mapping.author_function_ref
                or assignment.function_ref != mapping.author_function_ref
                or mapping.author_action_id not in grant.action_ids
                or not any(scope_covers(scope,mapping.scope) for scope in grant.scopes)):
            raise ValueError('Capacity mapping substitutes its original firm author authority')
        if (mapping.authored_at.clock_ref != now.clock_ref
                or mapping.authored_at.offset > mapping.available_at.offset
                or grant.validity.start.clock_ref != now.clock_ref or grant.validity.end.clock_ref != now.clock_ref
                or not grant.validity.contains(mapping.authored_at)
                or not mapping.effective_window.contains(mapping.authored_at)):
            return missing('valid_original_capacity_mapping_authority')
        for ref in [*mapping.evidence_refs,*grant.basis_refs,*assignment.basis_refs]:
            if not isinstance(reading.resolve(ref),EvidenceRecord):
                raise ValueError('Capacity mapping author lacks original typed authority evidence')
        if (not isinstance(mapping.supported,Known) or mapping.supported.value is not True
                or mapping.coverage != 'complete'):
            return missing('supported_complete_future_occupancy_mapping')
        evidence = reading.resolve(mapping.source_evidence_ref)
        if (not isinstance(evidence,EvidenceRecord) or evidence.basis_kind != 'observed'
                or evidence.content_hash != source['record_sha256']):
            raise ValueError('Capacity source evidence changes the actual observed source content')
        if not mapping.calendar_evidence_refs:
            return missing('independent_clock_region_future_calendar_evidence')
        for ref in mapping.calendar_evidence_refs:
            row = reading.resolve(ref)
            if not isinstance(row,EvidenceRecord):
                raise ValueError('Capacity calendar lacks typed source evidence')
            if context.execution_mode != 'offline_fixture' and not supports_tender_source(
                    row, allow_synthetic_assumptions=mapping.allow_synthetic_assumptions):
                return missing('observed_formal_future_occupancy_calendar')
            if row.effective_window is not None and (
                    row.effective_window.start.clock_ref != now.clock_ref
                    or row.effective_window.end.clock_ref != now.clock_ref
                    or not row.effective_window.contains(now)):
                return missing('current_calendar_evidence')
        data = mapping.data
        if data.clock_ref != now.clock_ref or len(data.resources) != 1:
            raise ValueError('Normalized enterprise scalar cannot be split into invented physical resources')
        resource = data.resources[0]
        if resource.total.unit != source['resource_unit']:
            raise ValueError('GBA capacity producer performs no implicit normalized-to-physical unit conversion')
        if not resource.effective_window.contains(now):
            return missing('resource_effective_at_current_read_point')
        facts = source['facts']
        total = Fraction(Decimal(str(facts['total_resource_capacity'])))
        occupied = Fraction(Decimal(str(facts['occupied_resource'])))
        if total < 0 or occupied < 0 or Fraction(Decimal(resource.total.value)) != total:
            raise ValueError('Capacity mapping changes the actual normalized enterprise total')
        current_occupied = sum((Fraction(Decimal(row.quantity.value)) for row in data.commitments
                                if row.window.contains(now)),Fraction(0))
        if current_occupied != occupied:
            return missing('calendar_reconciled_with_actual_current_enterprise_occupancy')
        # The serialized GBA float is retained as a decimal transport value;
        # this does not claim greater accuracy than the original macro number.
        for demand in data.demands:
            if (demand.unit != resource.total.unit or demand.resource_kind != resource.resource_kind
                    or demand.region_id != resource.region_id):
                raise ValueError('Capacity demand changes the explicitly sourced unit/kind/location')
            if demand.window.start.offset < now.offset:
                return missing('current_or_future_authorized_demand_window')
        basis = [resource.total.basis_ref,*[row.quantity.basis_ref for row in data.commitments],
                 *[ref for demand in data.demands for ref in demand.basis_refs]]
        for ref in basis:
            if not isinstance(reading.resolve(ref),EvidenceRecord):
                raise ValueError('Capacity quantities/demands lack their authorized original evidence')
        required_refs = {mapping.ref.key(),mapping.source_evidence_ref.key(),
                         *[ref.key() for ref in mapping.calendar_evidence_refs]}
        if not required_refs <= {ref.key() for ref in data.source_refs}:
            raise ValueError('Capacity input omits its original mapping and observed source provenance')
        unique_refs(data.source_refs)
        for ref in data.source_refs: reading.resolve(ref)
        return {'kind':'prepared','data':data.model_copy(deep=True),
                'input_sha256':task_digest(data.model_dump(mode='json')),
                'source_record_sha256':source['record_sha256'],
                'source_mode':'fixture' if context.execution_mode == 'offline_fixture' else 'formal',
                'limitations':['Method input only; no feasibility, reservation or core execution.',
                                'Numeric precision remains that of the original serialized macro values.',
                                'Future occupancy/location/clock semantics come from independent host evidence.']}
    finally:
        reading.recheck()
