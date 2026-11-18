"""Build whole-line bid tasks from original quantities and independently authored planning instructions."""
from typing import Annotated, Literal

from pydantic import Field

from integration.tender_source_policy import TenderSimulationSource, supports_tender_source

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Reference, ScopeRef, StrictRecord, TextId, TimeWindow, ref_type, walk_references
from src.actions.contracts.contractor_bid_objects import (
    ContractorBidAllocation, ContractorBidCapacityView, ContractorBidMethodView,
    ContractorBidPackageView, ContractorBidProgrammeView, ContractorBidQuantityTarget,
    ContractorBidQuantityView, ContractorBidReferenceView, ContractorBidResourceView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import task_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class ContractorBidSourceDigest(StrictRecord):
    ref: Reference
    sha256: Digest


class ContractorBidTaskInstruction(StrictRecord):
    local_key: TextId
    scope_ref: ScopeRef
    work_method_ref: ref_type('WorkMethod')
    window_ref: ref_type('TimeWindow')
    quantity_sources: Annotated[list[ContractorBidQuantityTarget], Field(min_length=1)]
    dependency_refs: list[ref_type('Dependency')]
    allocations: Annotated[list[ContractorBidAllocation], Field(min_length=1)]


class ContractorBidProgrammeBasisView(TenderSimulationSource):
    """An actual Contractor's explicit plan; no automatic sequencing or inferred resources."""
    ref: ref_type('ContractorProgrammeBasis')
    run_id: TextId
    organization_id: TextId
    programme_ref: ref_type('ProgrammeProposal')
    package_ref: ref_type('ProcurementPackage')
    capacity_ref: ref_type('ContractorCapacity')
    quantity_refs: Annotated[list[ref_type('QuantityBasis')], Field(min_length=1)]
    exclusion_refs: list[ref_type('Requirement')]
    source_digests: Annotated[list[ContractorBidSourceDigest], Field(min_length=1)]
    planning_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    tasks: Annotated[list[ContractorBidTaskInstruction], Field(min_length=1)]
    author_action_id: Literal['CONTRACTOR-A02']


def prepare_contractor_bid_programme(*, context, reading, basis_ref, validate_current):
    """Produce exact whole-line targets; A02 retains independent productivity/capacity checks.

    Splits remain supported by the original direct programme schema. This
    producer never invents split amounts, windows, dependencies, qualifications,
    productivity or available resources. A planned allocation is not a booking.
    """
    if not isinstance(reading, ActionReadView) or context.contract_ref.id != 'CONTRACTOR-A02' or not callable(validate_current):
        raise ValueError('Programme production requires its actual A02 reading and current host validation')
    reading.check_method_context(context, 'CONTRACTOR-A02')
    now = context.business_time
    provenance = {}

    def current(row):
        if (not scope_covers(row.scope, context.scope) or row.available_at.clock_ref != now.clock_ref
                or row.available_at.offset > now.offset or not row.effective_window.contains(now)):
            raise ValueError('Programme source is outside current scope or time')

    try:
        basis = reading.resolve(Reference.model_validate(basis_ref))
        if not isinstance(basis, ContractorBidProgrammeBasisView):
            raise ValueError('Programme requires its concrete authored planning basis')
        current(basis)
        if basis.run_id != context.run_id or basis.organization_id != reading.organization_id or basis.scope != context.scope:
            raise ValueError('Programme basis changes original run, Contractor or scope')
        grant = reading.resolve(basis.author_authority_ref)
        assignment = reading.resolve(basis.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or assignment.role != 'Contractor' or assignment.function_ref != basis.author_function_ref
                or grant.organization_id != basis.organization_id or grant.actor_id != basis.author_actor_id
                or grant.function_ref != basis.author_function_ref or basis.author_action_id not in grant.action_ids
                or basis.author_organization_id != basis.organization_id
                or not any(scope_covers(scope, basis.scope) for scope in grant.scopes)
                or basis.authored_at.clock_ref != now.clock_ref or basis.authored_at.offset > basis.available_at.offset
                or not grant.validity.contains(basis.authored_at) or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Programme instructions lack original Contractor author authority')
        unique_refs([row.ref for row in basis.source_digests])
        hashes = {row.ref.key(): row.sha256 for row in basis.source_digests}

        def read(ref, schema):
            row = reading.resolve(ref)
            if (not isinstance(row, schema) or hasattr(row, 'ref') and row.ref != ref
                    or hashes.get(ref.key()) != task_digest(row.model_dump(mode='json'))):
                raise ValueError('Programme substitutes an original source projection or omits its digest')
            if hasattr(row, 'available_at'):
                current(row)
            provenance[ref.key()] = row
            return row

        package = read(basis.package_ref, ContractorBidPackageView)
        capacity = read(basis.capacity_ref, ContractorBidCapacityView)
        if (capacity.organization_id != reading.organization_id or capacity.as_of != now
                or reading.organization_id not in package.recipient_organization_ids
                or set(basis.quantity_refs) != set(package.quantity_refs)
                or not set(basis.exclusion_refs) <= set(package.allowed_exclusion_refs)):
            raise ValueError('Programme changes original enterprise, package, quantities or exclusions')
        for refs in (basis.quantity_refs, basis.exclusion_refs):
            unique_refs(refs)
        excluded = set()
        for ref in basis.exclusion_refs:
            row = read(ref, ContractorBidReferenceView)
            if row.package_ref != package.ref:
                raise ValueError('Programme exclusion belongs to another original package')
            excluded.update(row.excluded_coverage_keys)
        if (excluded and not package.allow_limited_bid) or not excluded <= set(package.coverage_keys):
            raise ValueError('Programme removes original scope without procurement permission')
        included = set(package.coverage_keys) - excluded
        quantities, coverage = {}, set()
        for ref in basis.quantity_refs:
            row = read(ref, ContractorBidQuantityView)
            if row.package_ref != package.ref or not set(row.deliverable_refs) <= set(package.deliverable_refs):
                raise ValueError('Programme quantity changes original procurement/design versions')
            if row.status != 'ok':
                return {'kind': 'needs_information', 'missing_fields': ['successful_original_programme_quantities'], 'requested_refs': [ref]}
            for line in row.lines:
                key = (ref.key(), line.local_key)
                if key in quantities or len(set(line.coverage_keys)) != len(line.coverage_keys):
                    raise ValueError('Programme repeats an original quantity line or coverage key')
                if set(line.coverage_keys) <= excluded:
                    continue
                if not set(line.coverage_keys) <= included or coverage.intersection(line.coverage_keys):
                    raise ValueError('Programme quantity coverage overlaps or partly removes an original line')
                if line.quantity.state != 'known':
                    return {'kind': 'needs_information', 'missing_fields': ['known_original_programme_quantity'], 'requested_refs': [ref]}
                if decimal_fraction(line.quantity.value.value) <= 0:
                    raise ValueError('Programme requires positive original planned quantities')
                quantities[key] = line.quantity.value
                coverage.update(line.coverage_keys)
        if not included or coverage != included:
            return {'kind': 'needs_information', 'missing_fields': ['complete_included_programme_quantity_coverage'], 'requested_refs': [package.ref]}
        if len({task.local_key for task in basis.tasks}) != len(basis.tasks):
            raise ValueError('Programme repeats a task identity')
        planned, tasks = set(), []
        pools = {row.resource_ref.key(): row for row in capacity.resources}
        for instruction in basis.tasks:
            if not scope_covers(package.scope, instruction.scope_ref) or instruction.work_method_ref not in package.allowed_method_refs:
                raise ValueError('Programme task exceeds original scope or permitted work methods')
            method = read(instruction.work_method_ref, ContractorBidMethodView)
            window = read(instruction.window_ref, TimeWindow)
            if (window.start.clock_ref != now.clock_ref or window.bounds != 'closed_open'
                    or window.start.offset < now.offset or window.end.offset <= window.start.offset):
                raise ValueError('Programme requires an original future positive half-open work window')
            unique_refs(instruction.dependency_refs)
            for ref in instruction.dependency_refs:
                if read(ref, ContractorBidReferenceView).package_ref != package.ref:
                    raise ValueError('Programme dependency changes original package')
            targets = []
            for target in instruction.quantity_sources:
                key = (target.quantity_basis_ref.key(), target.quantity_line_key)
                if key not in quantities or key in planned:
                    raise ValueError('Whole-line programme repeats or invents an original quantity target')
                targets.append(quantities[key].model_copy(deep=True))
                planned.add(key)
            unique_refs([row.resource_ref for row in instruction.allocations])
            for allocation in instruction.allocations:
                pool = read(allocation.resource_ref, ContractorBidResourceView)
                original = pools.get(pool.ref.key())
                if (original is None or pool.organization_id != reading.organization_id or pool.total != original.total
                        or pool.resource_kind != method.resource_kind or pool.region_id != package.region_id
                        or allocation.task_scope_ref != instruction.scope_ref or allocation.window_ref != instruction.window_ref
                        or allocation.quantity.unit != method.capacity_unit or pool.total.unit != method.capacity_unit
                        or decimal_fraction(allocation.quantity.value) <= 0):
                    raise ValueError('Programme allocation changes actual pool, unit, location or original task/window')
            tasks.append({**instruction.model_dump(mode='python'), 'target_quantities': targets})
        if planned != set(quantities):
            return {'kind': 'needs_information', 'missing_fields': ['complete_whole_line_programme_assignment'], 'requested_refs': [basis.ref]}
        if set(hashes) != set(provenance):
            raise ValueError('Programme source digest set adds unrelated or unused original sources')
        source_evidence = [ref for row in provenance.values() for ref in getattr(row, 'evidence_refs', [])]
        source_evidence.extend(ref for row in provenance.values() for ref in walk_references(row) if ref.kind == 'Evidence')
        if set(basis.planning_evidence_refs).intersection(source_evidence):
            raise ValueError('Quantity/resource facts cannot substitute independent planning instructions')
        evidence_refs = [*basis.evidence_refs, *basis.planning_evidence_refs, *source_evidence,
            *grant.basis_refs, *assignment.basis_refs, *[row.basis_ref for row in quantities.values()],
            *[allocation.quantity.basis_ref for task in basis.tasks for allocation in task.allocations]]
        evidence_refs = list({ref.key(): ref for ref in evidence_refs}.values())
        for ref in evidence_refs:
            row = reading.resolve(ref)
            if (not isinstance(row, EvidenceRecord) or row.effective_window is not None and not row.effective_window.contains(now)
                    or ref in basis.planning_evidence_refs and not supports_tender_source(
                        row, allow_synthetic_assumptions=basis.allow_synthetic_assumptions)):
                raise ValueError('Programme evidence is not current and independently authored')
        grants = [reading.resolve(ref) for ref in context.authorization_refs]
        if basis.programme_ref not in context.visible_refs or not any(
                isinstance(row, Authorization) and row.organization_id == reading.organization_id
                and row.actor_id == context.actor_id and row.function_ref == context.function_ref
                and 'CONTRACTOR-A02' in row.action_ids and row.validity.contains(now)
                and any(scope_covers(scope, context.scope) for scope in row.scopes)
                and basis.programme_ref in row.readable_refs for row in grants):
            raise ValueError('Produced programme target lacks explicit current read authority')
        if validate_current(context=context.model_copy(deep=True), basis=basis.model_copy(deep=True),
                sources=[row.model_copy(deep=True) for row in provenance.values()]) is not None:
            raise ValueError('Actual original planning instructions and source relations require current host validation')
        projection = ContractorBidProgrammeView(ref=basis.programme_ref, organization_id=reading.organization_id,
            package_ref=package.ref, quantity_refs=list(basis.quantity_refs), tasks=tasks,
            author_actor_id=basis.author_actor_id, author_function_ref=basis.author_function_ref,
            author_authority_ref=basis.author_authority_ref, scope=context.scope, available_at=now,
            effective_window={'start': now, 'end': now, 'bounds': 'closed_closed'}, evidence_refs=evidence_refs)
        return {'kind': 'prepared', 'programme_projection': projection, 'basis_ref': basis.ref,
            'programme_sha256': task_digest(projection.model_dump(mode='json')),
            'basis_sha256': task_digest(basis.model_dump(mode='json')), 'context_sha256': task_digest(context.model_dump(mode='json')),
            'source_mode': 'fixture' if context.execution_mode == 'offline_fixture' else 'formal',
            'limitations': ['Whole original quantity lines only; direct programme schema retains explicit split-plan support.',
                           'A02 independently checks productivity, exact allocation demand and all shared occupancy.',
                           'Publish at a fresh token before use; no resource reservation, schedule optimization or actual work.']}
    finally:
        reading.recheck()
