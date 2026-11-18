"""Project an original published QS procurement schedule into one A02 quantity basis."""
from typing import Literal

from integration.tender_source_policy import supports_tender_source

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Reference, StrictRecord, TextId, TimePoint, ref_type, walk_references
from src.actions.contracts.contractor_bid_objects import (
    ContractorBidDeliverableView, ContractorBidPackageView, ContractorBidQuantityView,
    ContractorBidReferenceView, contractor_bid_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.qs_procurement_objects import (
    QSMeasurementRuleView, QSProcurementDesignView, QSProcurementDocumentView, QSProcurementQuantityView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class ContractorQuantityDesignLink(StrictRecord):
    design_ref: ref_type('Deliverable')
    design_sha256: Digest
    released_ref: ref_type('ReleasedDeliverable')
    released_sha256: Digest


class ContractorQuantityMappingView(CostSource):
    """Explicit source/publication relation; target released objects already exist."""
    ref: ref_type('ContractorQuantityMapping')
    run_id: TextId
    organization_id: TextId
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
    relation_evidence_refs: list[ref_type('Evidence')]
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['CONTRACTOR-A02']
    authored_at: TimePoint
    allow_synthetic_assumptions: bool = False


def contractor_quantity_source_schemas():
    """Separate original-source resolver; never replace A02's rule/quantity schemas."""
    return contractor_bid_schemas({'QuantitySchedule': QSProcurementQuantityView,
        'ProcurementDocument': QSProcurementDocumentView, 'Deliverable': QSProcurementDesignView,
        'MeasurementRule': QSMeasurementRuleView})


def prepare_contractor_bid_quantity(*, context, reading, source_reading, mapping_ref, validate_current):
    """Copy all declared schedule lines; no proxy conversion, measurement or aggregation.

    Original QS and current A02 representations use separately supplied providers
    at the same authorized read point. The host must prove their actual source
    and released-document relation, including native publication, before use.
    """
    if (not isinstance(reading, ActionReadView) or not isinstance(source_reading, ActionReadView)
            or context.contract_ref.id != 'CONTRACTOR-A02' or not callable(validate_current)
            or reading.organization_id != source_reading.organization_id):
        raise ValueError('Quantity production requires original/current authorized A02 readings and host validation')
    for view in (reading, source_reading):
        view.check_method_context(context, 'CONTRACTOR-A02')
    now = context.business_time

    def read(view, ref, schema, digest=None):
        row = view.resolve(ref)
        if (not isinstance(row, schema) or row.ref != ref
                or digest is not None and task_digest(row.model_dump(mode='json')) != digest):
            raise ValueError('Quantity source substitutes its original schema, version or projection')
        if isinstance(row, CostSource) and (not scope_covers(row.scope, context.scope)
                or row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                or not row.effective_window.contains(now)):
            raise ValueError('Quantity source exceeds the current scope or time')
        return row

    def author(view, row, role, at, organization=None):
        grant = read(view, row.author_authority_ref, Authorization)
        assignment = view.resolve(row.author_function_ref)
        if (not isinstance(assignment, RoleAssignment) or assignment.role != role
                or assignment.function_ref != row.author_function_ref or grant.actor_id != row.author_actor_id
                or grant.function_ref != row.author_function_ref or row.author_action_id not in grant.action_ids
                or organization is not None and grant.organization_id != organization
                or not grant.validity.contains(at) or not any(scope_covers(scope, row.scope) for scope in grant.scopes)):
            raise ValueError('Quantity source lacks original author function/authority')
        return [*grant.basis_refs, *assignment.basis_refs]

    try:
        mapping = read(reading, Reference.model_validate(mapping_ref), ContractorQuantityMappingView)
        if (mapping.run_id != context.run_id or mapping.organization_id != reading.organization_id
                or mapping.scope != context.scope or mapping.authored_at.clock_ref != now.clock_ref
                or mapping.authored_at.offset > mapping.available_at.offset
                or not mapping.effective_window.contains(mapping.authored_at)):
            raise ValueError('Quantity relation changes its original run, Contractor or authorship time')
        target_evidence = [*mapping.evidence_refs, *author(reading, mapping, 'Contractor',
            mapping.authored_at, reading.organization_id)]
        package = read(reading, mapping.package_ref, ContractorBidPackageView, mapping.package_sha256)
        if (reading.organization_id not in package.recipient_organization_ids
                or mapping.quantity_ref not in package.quantity_refs):
            raise ValueError('Quantity production changes its original procurement recipient or target')
        document = read(source_reading, mapping.document_ref, QSProcurementDocumentView, mapping.document_sha256)
        schedule = read(source_reading, mapping.schedule_ref, QSProcurementQuantityView, mapping.schedule_sha256)
        source_rule = read(source_reading, mapping.measurement_rule_ref, QSMeasurementRuleView, mapping.source_rule_sha256)
        target_rule = read(reading, mapping.measurement_rule_ref, ContractorBidReferenceView, mapping.target_rule_sha256)
        source_evidence = [*document.evidence_refs, *schedule.evidence_refs, *source_rule.evidence_refs,
            *author(source_reading, document, 'QS', document.available_at),
            *author(source_reading, schedule, 'QS', schedule.available_at)]
        if document.status != 'published':
            return {'kind': 'needs_information', 'missing_fields': ['original_authorized_published_procurement_document'],
                    'requested_refs': [document.ref]}
        if (document.round_ref != schedule.round_ref or document.draft.quantity_schedule_ref != schedule.ref
                or document.draft.procurement_scope_ref != schedule.procurement_scope_ref
                or document.draft.measurement_rule_ref != source_rule.ref or schedule.measurement_rule_ref != source_rule.ref
                or set(document.draft.design_refs) != set(schedule.design_refs)
                or 'procurement' not in source_rule.allowed_uses or target_rule.package_ref != package.ref
                or target_rule.organization_id not in (None, reading.organization_id)):
            raise ValueError('Quantity document changes the original procurement, schedule or rule relation')
        unique_refs([link.design_ref for link in mapping.design_links])
        unique_refs([link.released_ref for link in mapping.design_links])
        if (not mapping.design_links or {link.design_ref for link in mapping.design_links} != set(schedule.design_refs)
                or not {link.released_ref for link in mapping.design_links} <= set(package.deliverable_refs)):
            raise ValueError('Quantity relation omits original designs or adds unauthorized released targets')
        designs = {}
        original_author_actions = {
            'Architect': {'ARCHITECT-A04', 'ARCHITECT-A05', 'ARCHITECT-A13'},
            'Engineer': {'ENGINEER-A04', 'ENGINEER-A05', 'ENGINEER-A13'},
            'QS': {'QS-A04', 'QS-A05'},
        }
        for link in mapping.design_links:
            original = read(source_reading, link.design_ref, QSProcurementDesignView, link.design_sha256)
            released = read(reading, link.released_ref, ContractorBidDeliverableView, link.released_sha256)
            if ('procurement' not in original.allowed_uses or 'procurement' not in released.allowed_uses
                    or released.package_ref != package.ref or released.maturity not in package.permitted_maturities):
                raise ValueError('Quantity design/release lacks original procurement permission or maturity')
            role = {'ARCHITECT-A07': 'Architect', 'ENGINEER-A07': 'Engineer', 'QS-A05': 'QS'}[released.author_action_id]
            target_evidence.extend([*released.evidence_refs, *author(reading, released, role, released.available_at)])
            assignment = source_reading.resolve(original.author_function_ref)
            if (not isinstance(assignment, RoleAssignment)
                    or original.author_action_id not in original_author_actions.get(assignment.role, set())):
                raise ValueError('Quantity source design lacks its original supported professional author action')
            source_evidence.extend([*original.evidence_refs,
                *author(source_reading, original, assignment.role, original.available_at)])
            designs[original.ref.key()] = original
        coverage = set()
        for line in schedule.lines:
            design = designs.get(line.design_ref.key())
            if (design is None or not scope_covers(package.scope, line.covered_scope)
                    or not set(line.coverage_keys) <= set(design.coverage_keys)
                    or not set(line.coverage_keys) <= set(package.coverage_keys)
                    or coverage.intersection(line.coverage_keys)
                    or line.quantity.state == 'known' and line.quantity.value.unit not in source_rule.supported_units):
                raise ValueError('Quantity lines change original coverage, scope, design or supported unit')
            coverage.update(line.coverage_keys)
            source_evidence.extend([*line.basis_refs,
                *[ref for ref in walk_references(line.quantity) if ref.kind == 'Evidence']])
        if not mapping.relation_evidence_refs:
            return {'kind': 'needs_information', 'missing_fields': ['independent_procurement_quantity_release_relation'],
                    'requested_refs': [mapping.ref]}
        unique_refs(mapping.relation_evidence_refs)
        if set(mapping.relation_evidence_refs).intersection(source_evidence):
            raise ValueError('Original quantity evidence cannot substitute publication/release relation evidence')
        target_evidence.extend([*package.evidence_refs, *target_rule.evidence_refs, *mapping.relation_evidence_refs])
        for view, refs in ((reading, target_evidence), (source_reading, source_evidence)):
            for ref in {ref.key(): ref for ref in refs}.values():
                evidence = read(view, ref, EvidenceRecord)
                if (evidence.effective_window is not None and not evidence.effective_window.contains(now)
                        or ref in mapping.relation_evidence_refs and not supports_tender_source(
                            evidence, allow_synthetic_assumptions=mapping.allow_synthetic_assumptions)):
                    raise ValueError('Quantity/publication relation evidence is not current and independently observed')
                if view is source_reading and read(reading, ref, EvidenceRecord) != evidence:
                    raise ValueError('Projected quantity evidence is absent or different in the target authorized view')
        grants = [reading.resolve(ref) for ref in context.authorization_refs]
        if mapping.quantity_ref not in context.visible_refs or not any(
                isinstance(grant, Authorization) and grant.organization_id == reading.organization_id
                and grant.actor_id == context.actor_id and grant.function_ref == context.function_ref
                and 'CONTRACTOR-A02' in grant.action_ids and grant.validity.contains(now)
                and any(scope_covers(scope, context.scope) for scope in grant.scopes)
                and mapping.quantity_ref in grant.readable_refs for grant in grants):
            raise ValueError('Produced quantity target lacks current explicit read authority')
        if validate_current(context=context.model_copy(deep=True), mapping=mapping.model_copy(deep=True),
                document=document.model_copy(deep=True), schedule=schedule.model_copy(deep=True),
                source_reading=source_reading, reading=reading) is not None:
            raise ValueError('Actual published quantity/design relation requires fresh host validation')
        evidence_refs = list({ref.key(): ref for ref in [*target_evidence, *source_evidence]}.values())
        projection = ContractorBidQuantityView(ref=mapping.quantity_ref, package_ref=package.ref,
            deliverable_refs=[link.released_ref for link in mapping.design_links],
            measurement_rule_ref=target_rule.ref.model_dump(mode='python'),
            lines=[{'local_key': line.line_key, 'coverage_keys': list(line.coverage_keys),
                    'quantity': line.quantity.model_copy(deep=True)} for line in schedule.lines], status='ok',
            scope=context.scope, available_at=now, effective_window={'start': now, 'end': now, 'bounds': 'closed_closed'},
            evidence_refs=[ref.model_dump(mode='python') for ref in evidence_refs])
        return {'kind': 'prepared', 'quantity_projection': projection, 'mapping_ref': mapping.ref,
            'quantity_sha256': task_digest(projection.model_dump(mode='json')),
            'mapping_sha256': task_digest(mapping.model_dump(mode='json')), 'schedule_sha256': mapping.schedule_sha256,
            'document_sha256': mapping.document_sha256, 'context_sha256': task_digest(context.model_dump(mode='json')),
            'source_mode': 'fixture' if context.execution_mode == 'offline_fixture' else 'formal',
            'source_open_questions': [row.model_dump(mode='json') for row in document.draft.open_questions],
            'source_design_limitations': {row.ref.id: list(row.limitations) for row in designs.values()},
            'limitations': ['Declared original quantities only; no measurement, aggregation or QS proxy conversion.',
                           'Unknown quantities preserved; A02 independently checks complete priced coverage.',
                           'Snapshot-only projection requires immutable publication; no macro release or bid asserted.']}
    finally:
        reading.recheck()
        source_reading.recheck()
