"""Produce A01 resource projections from the actual source-reconciled calendar."""
from typing import Literal

from integration.tender_source_policy import TenderSimulationSource, supports_tender_source

from integration.bindings.gba_v1_capacity import GbaCapacityMappingView, prepare_gba_capacity_input
from src.actions.contracts.common import EvidenceRecord, Known, Reference, TextId, TimePoint, TimeWindow, ValueState, ref_type
from src.actions.contracts.contractor_objects import (
    CommitmentSnapshotView, ContractorCapabilityView, QualificationView, ResourceCapacity,
)
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.owner_study_objects import unique_refs
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers
from src.coordination.tasks import task_digest


class GbaScreeningEnterpriseFactsView(TenderSimulationSource):
    """Independent enterprise competence; scalar capacity proves no qualifications."""
    ref: ref_type('GbaScreeningEnterpriseFacts')
    organization_ref: ref_type('Organization')
    run_id: TextId
    as_of: TimePoint
    capability_ref: ref_type('ContractorCapability')
    commitments_ref: ref_type('CommitmentSnapshot')
    mapping_ref: ref_type('GbaCapacityMapping')
    capability_window: TimeWindow
    work_types: ValueState[list[TextId]]
    method_refs: ValueState[list[ref_type('WorkMethod')]]
    qualification_coverage: Literal['complete','partial','unknown']
    qualification_refs: list[ref_type('Qualification')]
    competence_evidence_refs: list[ref_type('Evidence')]


def prepare_gba_screening_resource_projections(source, *, context, reading, facts_ref):
    """Copy original totals/occupancy/windows; no unit conversion or feasibility.

    The existing calendar producer first reconciles original scalar totals and
    occupancy. These projections translate the resulting typed rows directly;
    professional competence/qualification coverage remains independently sourced.
    The host must publish new immutable object versions before A01 execution.
    """
    if not isinstance(reading, ActionReadView) or context.contract_ref.id != 'CONTRACTOR-A01':
        raise ValueError('Screening resource production requires its actual authorized A01 reading')
    reading.check_method_context(context, 'CONTRACTOR-A01')
    facts_ref = Reference.model_validate(facts_ref)
    try:
        facts = reading.resolve(facts_ref)
        if not isinstance(facts, GbaScreeningEnterpriseFactsView) or facts.ref != facts_ref:
            raise ValueError('Enterprise competence requires its concrete original projection')
        now = context.business_time
        if (facts.run_id != context.run_id or facts.organization_ref.id != reading.organization_id
                or facts.author_organization_id != reading.organization_id or facts.scope != context.scope):
            raise ValueError('Enterprise facts substitute original firm, run, author or scope')
        if (facts.as_of != now or facts.available_at.clock_ref != now.clock_ref
                or facts.available_at.offset > now.offset or not facts.effective_window.contains(now)
                or not facts.capability_window.contains(now)):
            return {'kind':'needs_information', 'missing_fields':['current_independent_enterprise_competence'], 'requested_refs':[facts.ref]}
        grant = reading.resolve(facts.author_authority_ref)
        assignment = reading.resolve(facts.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or assignment.role != 'Contractor' or grant.organization_id != reading.organization_id
                or grant.actor_id != facts.author_actor_id or grant.function_ref != facts.author_function_ref
                or assignment.function_ref != facts.author_function_ref
                or facts.author_action_id not in grant.action_ids
                or not any(scope_covers(scope, facts.scope) for scope in grant.scopes)
                or facts.authored_at.clock_ref != now.clock_ref or facts.authored_at.offset > facts.available_at.offset
                or not grant.validity.contains(facts.authored_at) or not facts.effective_window.contains(facts.authored_at)):
            raise ValueError('Enterprise competence lacks original independent author authority')

        def evidence(ref, *, observed=False):
            value = reading.resolve(ref)
            if (not isinstance(value, EvidenceRecord) or observed and not supports_tender_source(
                    value, allow_synthetic_assumptions=facts.allow_synthetic_assumptions)
                    or value.effective_window is not None and not value.effective_window.contains(now)):
                raise ValueError('Enterprise competence lacks current independently sourced evidence')

        for ref in [*facts.evidence_refs, *grant.basis_refs, *assignment.basis_refs]:
            evidence(ref)
        if not facts.competence_evidence_refs:
            return {'kind':'needs_information', 'missing_fields':['independent_competence_and_qualification_coverage_evidence'],
                    'requested_refs':[facts.ref]}
        for ref in facts.competence_evidence_refs:
            evidence(ref, observed=context.execution_mode != 'offline_fixture')
        unique_refs(facts.qualification_refs)
        for ref in facts.qualification_refs:
            qualification = reading.resolve(ref)
            if not isinstance(qualification, QualificationView) or qualification.organization_ref != facts.organization_ref:
                raise ValueError('Enterprise qualification changes its original firm or schema')
        if isinstance(facts.method_refs, Known):
            unique_refs(facts.method_refs.value)
            for ref in facts.method_refs.value:
                reading.resolve(ref)
        prepared = prepare_gba_capacity_input(source, context=context, reading=reading, mapping_ref=facts.mapping_ref)
        if prepared['kind'] != 'prepared':
            return prepared
        mapping = reading.resolve(facts.mapping_ref)
        if not isinstance(mapping, GbaCapacityMappingView):
            raise ValueError('Screening calendar mapping requires its original concrete schema')
        capacity_evidence = {mapping.source_evidence_ref.key(),
                             *[ref.key() for ref in mapping.calendar_evidence_refs]}
        if any(ref.key() in capacity_evidence for ref in facts.competence_evidence_refs):
            raise ValueError('Resource totals/calendar cannot substitute independent professional competence evidence')
        data = prepared['data']
        if any(row.resource_ref.kind != 'Resource' for row in data.resources):
            return {'kind':'unsupported', 'capability_ref':{
                'kind':'Capability', 'id':'gba-screening-resource-pool-reference', 'version':'1'}}
        if facts.capability_window.start.clock_ref != data.clock_ref:
            raise ValueError('Enterprise capability window changes the explicit calendar clock')
        targets = (facts.capability_ref, facts.commitments_ref)
        current_grants = [reading.resolve(ref) for ref in context.authorization_refs]
        for target in targets:
            if target not in context.visible_refs or not any(
                    isinstance(row, Authorization) and row.organization_id == reading.organization_id
                    and row.actor_id == context.actor_id and row.function_ref == context.function_ref
                    and 'CONTRACTOR-A01' in row.action_ids and row.validity.contains(now)
                    and target in row.readable_refs for row in current_grants):
                raise ValueError('Produced capability/commitment target lacks current explicit read authority')
        evidence_refs = list({ref.key():ref for ref in [mapping.source_evidence_ref,
            *mapping.calendar_evidence_refs, *facts.evidence_refs, *facts.competence_evidence_refs]}.values())
        capability = ContractorCapabilityView(ref=facts.capability_ref, organization_ref=facts.organization_ref,
            effective_window=facts.capability_window, work_types=facts.work_types, method_refs=facts.method_refs,
            qualification_coverage=facts.qualification_coverage, resource_coverage='complete', evidence_refs=evidence_refs,
            resources=[ResourceCapacity(resource_ref=row.resource_ref, resource_kind=row.resource_kind,
                region_id={'state':'known','value':row.region_id}, total={'state':'known','value':row.total},
                effective_window=row.effective_window) for row in data.resources])
        commitments = CommitmentSnapshotView(ref=facts.commitments_ref, organization_ref=facts.organization_ref,
            as_of=now, coverage='complete', evidence_refs=evidence_refs,
            allocations=[row.model_dump(mode='python') for row in data.commitments])
        reading.recheck()
        return {'kind':'prepared', 'capability_projection':capability, 'commitments_projection':commitments,
            'context_sha256':task_digest(context.model_dump(mode='json')),
            'capability_sha256':task_digest(capability.model_dump(mode='json')),
            'commitments_sha256':task_digest(commitments.model_dump(mode='json')),
            'source_record_sha256':prepared['source_record_sha256'], 'capacity_input_sha256':prepared['input_sha256'],
            'enterprise_facts_sha256':task_digest(facts.model_dump(mode='json')),
            'qualification_refs':list(facts.qualification_refs), 'source_mode':prepared['source_mode'],
            'limitations':['Projections only; host must publish immutable authorized versions.',
                           'Normalized scalar resources prove no professional skill, eligibility or physical output.',
                           'No feasibility calculation, new commitment, resource reservation/release or macro effect.']}
    finally:
        reading.recheck()
