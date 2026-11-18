"""Produce A02 capacity and original resource rows from sourced GBA calendar data."""
from typing import Literal

from integration.tender_source_policy import TenderSimulationSource, supports_tender_source

from integration.bindings.gba_v1_capacity import GbaCapacityMappingView, prepare_gba_capacity_input
from src.actions.contracts.common import EvidenceRecord, Reference, TextId, TimePoint, ref_type
from src.actions.contracts.contractor_bid_objects import (
    ContractorBidCapacityView, ContractorBidCommitmentView, ContractorBidResourceView, contractor_bid_schemas,
)
from src.actions.contracts.contractor_objects import QualificationView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class GbaBidEnterpriseFactsView(TenderSimulationSource):
    """Independent qualification inventory for the original Contractor enterprise."""
    ref: ref_type('GbaBidEnterpriseFacts')
    organization_id: TextId
    run_id: TextId
    as_of: TimePoint
    capacity_ref: ref_type('ContractorCapacity')
    mapping_ref: ref_type('GbaCapacityMapping')
    qualification_coverage: Literal['complete','partial','unknown']
    qualification_refs: list[ref_type('Qualification')]
    qualification_evidence_refs: list[ref_type('Evidence')]


def gba_bid_capacity_source_schemas():
    from integration.contractor_procurement_handoff import ContractorProcurementHandoffBasis
    from integration.contractor_bid_costs import ContractorBidCostAdoptionView
    from integration.contractor_bid_quantities import ContractorQuantityMappingView
    from integration.contractor_bid_programme import ContractorBidProgrammeBasisView
    from src.actions.contracts.qs_cost_objects import QSCostPriceView
    from integration.bindings.gba_v1_tender_proposal import GbaTenderProposalMappingView

    return contractor_bid_schemas({'GbaCapacityMapping':GbaCapacityMappingView,
        'GbaBidEnterpriseFacts':GbaBidEnterpriseFactsView,
        'ContractorProcurementHandoffBasis':ContractorProcurementHandoffBasis,
        'ContractorCostAdoption':ContractorBidCostAdoptionView, 'Price':QSCostPriceView,
        'ContractorQuantityMapping':ContractorQuantityMappingView,
        'ContractorProgrammeBasis':ContractorBidProgrammeBasisView,
        'GbaTenderProposalMapping':GbaTenderProposalMappingView})


def prepare_gba_bid_capacity_projections(source, *, context, reading, facts_ref):
    """Translate calendar rows into A02's strict original-source projections.

    No feasibility, programme demand, productivity, quantity or price is
    inferred. A02 independently checks its actual planned task demands against
    these original resource rows. Qualification uncertainty is preserved.
    Host publication must expose these versions in a fresh authorized snapshot.
    """
    if not isinstance(reading, ActionReadView) or context.contract_ref.id != 'CONTRACTOR-A02':
        raise ValueError('Bid capacity production requires its actual authorized A02 reading')
    reading.check_method_context(context, 'CONTRACTOR-A02')
    facts_ref = Reference.model_validate(facts_ref)
    try:
        facts = reading.resolve(facts_ref)
        if not isinstance(facts, GbaBidEnterpriseFactsView) or facts.ref != facts_ref:
            raise ValueError('Bid enterprise facts require their concrete original projection schema')
        if (facts.organization_id != reading.organization_id or facts.run_id != context.run_id
                or facts.scope != context.scope or facts.author_organization_id != reading.organization_id):
            raise ValueError('Bid capacity facts change original firm, author, run or scope')
        now = context.business_time
        if (facts.as_of != now or facts.available_at.clock_ref != now.clock_ref
                or facts.available_at.offset > now.offset or not facts.effective_window.contains(now)):
            return {'kind':'needs_information','missing_fields':['current_original_bid_enterprise_facts'],
                    'requested_refs':[facts.ref]}
        grant = reading.resolve(facts.author_authority_ref)
        assignment = reading.resolve(facts.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or assignment.role != 'Contractor' or grant.organization_id != reading.organization_id
                or grant.actor_id != facts.author_actor_id or grant.function_ref != facts.author_function_ref
                or assignment.function_ref != facts.author_function_ref or facts.author_action_id not in grant.action_ids
                or not any(scope_covers(scope,facts.scope) for scope in grant.scopes)
                or facts.authored_at.clock_ref != now.clock_ref or facts.authored_at.offset > facts.available_at.offset
                or not grant.validity.contains(facts.authored_at) or not facts.effective_window.contains(facts.authored_at)):
            raise ValueError('Bid qualification inventory lacks original independent author authority')

        def evidence(ref, *, observed=False):
            row = reading.resolve(ref)
            if (not isinstance(row,EvidenceRecord) or observed and not supports_tender_source(
                    row, allow_synthetic_assumptions=facts.allow_synthetic_assumptions)
                    or row.effective_window is not None and not row.effective_window.contains(now)):
                raise ValueError('Bid capacity/qualification evidence is not current and independently sourced')

        for ref in [*facts.evidence_refs,*grant.basis_refs,*assignment.basis_refs]:
            evidence(ref)
        if not facts.qualification_evidence_refs:
            return {'kind':'needs_information','missing_fields':['independent_bid_qualification_inventory_evidence'],
                    'requested_refs':[facts.ref]}
        for ref in facts.qualification_evidence_refs:
            evidence(ref,observed=context.execution_mode != 'offline_fixture')
        unique_refs(facts.qualification_refs)
        for ref in facts.qualification_refs:
            qualification = reading.resolve(ref)
            if not isinstance(qualification,QualificationView) or qualification.organization_ref.id != reading.organization_id:
                raise ValueError('Bid qualification inventory changes original enterprise or schema')
        prepared = prepare_gba_capacity_input(source,context=context,reading=reading,mapping_ref=facts.mapping_ref)
        if prepared['kind'] != 'prepared':
            return prepared
        mapping = reading.resolve(facts.mapping_ref)
        data = prepared['data']
        resource_evidence = {mapping.source_evidence_ref.key(),*[ref.key() for ref in mapping.calendar_evidence_refs]}
        if any(ref.key() in resource_evidence for ref in facts.qualification_evidence_refs):
            raise ValueError('Normalized resource/calendar facts cannot substitute qualification inventory evidence')
        if any(row.resource_ref.kind != 'ResourcePool' for row in data.resources):
            return {'kind':'unsupported','capability_ref':{
                'kind':'Capability','id':'gba-bid-resource-pool-reference','version':'1'}}
        targets = [facts.capacity_ref,*[row.resource_ref for row in data.resources],
                   *[row.commitment_ref for row in data.commitments]]
        unique_refs(targets)
        grants = [reading.resolve(ref) for ref in context.authorization_refs]
        for target in targets:
            if target not in context.visible_refs or not any(
                    isinstance(row,Authorization) and row.organization_id == reading.organization_id
                    and row.actor_id == context.actor_id and row.function_ref == context.function_ref
                    and 'CONTRACTOR-A02' in row.action_ids and row.validity.contains(now)
                    and target in row.readable_refs for row in grants):
                raise ValueError('Produced bid capacity/resource target lacks current explicit read authority')
        evidence_refs = list({ref.key():ref for ref in [mapping.source_evidence_ref,*mapping.calendar_evidence_refs,
            *facts.evidence_refs,*facts.qualification_evidence_refs]}.values())
        common = {'organization_id':reading.organization_id,'scope':context.scope,'available_at':now,
                  'effective_window':facts.effective_window,'evidence_refs':evidence_refs}
        capacity = ContractorBidCapacityView(ref=facts.capacity_ref,as_of=now,coverage='complete',
            resources=data.resources,commitments=data.commitments,qualification_refs=facts.qualification_refs,
            qualification_coverage=facts.qualification_coverage,**common)
        resources = [ContractorBidResourceView(ref=row.resource_ref,resource_kind=row.resource_kind,
            region_id=row.region_id,total=row.total,**{**common,'effective_window':row.effective_window})
            for row in data.resources]
        commitments = [ContractorBidCommitmentView(ref=row.commitment_ref,resource_ref=row.resource_ref,
            quantity=row.quantity,window=row.window,**common) for row in data.commitments]
        objects = [capacity,*resources,*commitments]
        reading.recheck()
        return {'kind':'prepared','capacity_projection':capacity,'resource_projections':resources,
            'commitment_projections':commitments,'capacity_sha256':task_digest(capacity.model_dump(mode='json')),
            'objects_sha256':task_digest([obj.model_dump(mode='json') for obj in objects]),
            'source_record_sha256':prepared['source_record_sha256'],'capacity_input_sha256':prepared['input_sha256'],
            'enterprise_facts_sha256':task_digest(facts.model_dump(mode='json')),
            'context_sha256':task_digest(context.model_dump(mode='json')),'source_mode':prepared['source_mode'],
            'limitations':['Projections only; host must publish immutable current authorized versions.',
                           'A02 independently calculates its actual programme demands and qualification checks.',
                           'No conversion from normalized capacity to physical production, new reservation or core effect.']}
    finally:
        reading.recheck()
