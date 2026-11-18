"""Produce an A01 procurement package from native invitation facts and sourced terms."""
from copy import deepcopy
import hashlib

from integration.tender_source_policy import TenderSimulationSource, supports_tender_source

from src.actions.contracts.common import EvidenceRecord, Known, Reference, TextId, TimePoint, ValueState, TimeWindow, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_objects import (
    InvitationView, ProcurementPackageView, QualificationRequirement, ResourceDemand, contractor_screening_schemas,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class GbaTenderPackageTermsView(TenderSimulationSource):
    """Owner-authored procurement terms absent from the old native project DTO.

    Known values need independent observed evidence in formal mode. Unknown
    requirements stay unknown, including an unknown qualification list; they
    are not replaced with an empty list. Tick is not a business-time mapping.
    """
    ref: ref_type('GbaTenderPackageTerms')
    package_ref: ref_type('ProcurementPackage')
    invitation_ref: ref_type('Invitation') | None = None
    employer_ref: ref_type('Organization')
    recipient_organization_id: TextId
    run_id: TextId
    simulation_id: TextId
    project_id: TextId
    source_record_sha256: Digest
    source_evidence_ref: ref_type('Evidence')
    terms_evidence_refs: list[ref_type('Evidence')]
    as_of: TimePoint
    work_types: ValueState[list[TextId]]
    participation_window: ValueState[TimeWindow]
    work_window: ValueState[TimeWindow]
    qualification_requirements: ValueState[list[QualificationRequirement]]
    required_method_refs: ValueState[list[ref_type('WorkMethod')]]
    resource_demands: ValueState[list[ResourceDemand]]
    funding_signal: ValueState[bool]
    clarification_requirement_refs: list[ref_type('Requirement')]


def gba_tender_package_source_schemas():
    schemas = contractor_screening_schemas()
    schemas.register_kind('GbaTenderPackageTerms', GbaTenderPackageTermsView, str)
    return schemas


def read_invited_tender_project(engine, client, *, organization_id, project_id, read_guard):
    """Read only the requested own invitation under the actual engine writer guard."""
    from integration.bootstrap import enable_gba_imports

    if not callable(read_guard):
        raise ValueError('Actual engine read guard shared with writers is required')
    with read_guard():
        if (client.simulation_id != engine.simulation_id or client.tasks.run_id != client.run_id
                or client.organization_roles.get(organization_id) != 'Contractor'):
            raise ValueError('Tender source changes the original simulation, run or Contractor recipient')
        agent = engine.agents.get(organization_id)
        project = engine.projects.get(project_id)
        if agent is None or agent.agent_id != organization_id or agent.role != 'Contractor':
            raise ValueError('Tender source lacks its actual original Contractor')
        if project is None or project.project_id != project_id:
            return {'kind':'needs_information', 'missing_fields':['actual_requested_tender_project'], 'requested_refs':[]}
        if (project.current_stage.value != 'tendering'
                or organization_id not in project.flags.get('invited_contractor_ids', [])):
            return {'kind':'needs_information', 'missing_fields':['current_own_native_tender_invitation'], 'requested_refs':[]}
        facts = {'project_id':project.project_id, 'owner_id':project.owner_id, 'region_id':project.region,
                 'project_type':project.project_type, 'stage':project.current_stage.value, 'own_invited':True}
        from integration.owner_invitation_feedback import own_invitation_origin
        origin = own_invitation_origin(engine, client, project=project, organization_id=organization_id)
        if origin is not None:
            facts['own_invitation_origin'] = origin
        record = {'schema_version':'gba-v1-invited-tender-project.v1', 'macro_version':'gba-public-2026-08-21',
            'run_id':client.run_id, 'simulation_id':engine.simulation_id, 'organization_id':organization_id,
            'observed_tick':engine.current_tick, 'facts':deepcopy(facts), 'facts_sha256':task_digest(facts)}
        root = enable_gba_imports() / 'gba_construction_sim/backend'
        record['source_hashes'] = {name:hashlib.sha256((root/name).read_bytes()).hexdigest()
            for name in ('models/project.py', 'core/enums.py', 'simulation/project_lifecycle_engine.py')}
        record['record_sha256'] = task_digest(record)
        return record


def prepare_gba_tender_package(source, *, context, reading, terms_ref=None):
    """Fill source-derived employer/region/access; preserve independent terms.

    Returns a projection for the host's immutable publication boundary. It does
    not register it under an existing object version or change read authority.
    Native project_type is retained in source evidence, not silently converted
    to work_types. Native invitation membership does not fabricate an Invitation.
    """
    if not isinstance(reading, ActionReadView) or context.contract_ref.id != 'CONTRACTOR-A01':
        raise ValueError('Tender package production requires the actual authorized Contractor A01 reading')
    reading.check_method_context(context, 'CONTRACTOR-A01')
    if (not isinstance(source, dict) or source.get('schema_version') != 'gba-v1-invited-tender-project.v1'
            or source.get('macro_version') != 'gba-public-2026-08-21'
            or source.get('run_id') != context.run_id or source.get('organization_id') != reading.organization_id
            or task_digest(source.get('facts')) != source.get('facts_sha256')
            or task_digest({k:v for k,v in source.items() if k != 'record_sha256'}) != source.get('record_sha256')):
        raise ValueError('Tender package requires an intact original native invitation source record')
    if terms_ref is None:
        return {'kind':'needs_information', 'missing_fields':['independently_authorized_procurement_terms'], 'requested_refs':[]}
    terms_ref = Reference.model_validate(terms_ref)
    try:
        terms = reading.resolve(terms_ref)
        if not isinstance(terms, GbaTenderPackageTermsView) or terms.ref != terms_ref:
            raise ValueError('Tender terms lack their actual concrete original schema')
        facts = source['facts']
        if (facts.get('own_invited') is not True or facts.get('stage') != 'tendering'
                or terms.run_id != context.run_id or terms.simulation_id != source['simulation_id']
                or terms.project_id != facts['project_id'] or terms.employer_ref.id != facts['owner_id']
                or terms.recipient_organization_id != reading.organization_id or terms.scope != context.scope
                or terms.source_record_sha256 != source['record_sha256']):
            raise ValueError('Tender terms substitute original project, owner, recipient, scope or source version')
        now = context.business_time
        if (terms.as_of != now or terms.available_at.clock_ref != now.clock_ref
                or terms.available_at.offset > now.offset or not terms.effective_window.contains(now)):
            return {'kind':'needs_information', 'missing_fields':['current_authorized_procurement_terms'], 'requested_refs':[terms.ref]}
        grant = reading.resolve(terms.author_authority_ref)
        assignment = reading.resolve(terms.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or assignment.role != 'Owner' or grant.organization_id != facts['owner_id']
                or terms.author_organization_id != facts['owner_id'] or grant.actor_id != terms.author_actor_id
                or grant.function_ref != terms.author_function_ref or assignment.function_ref != terms.author_function_ref
                or terms.author_action_id not in grant.action_ids
                or not any(scope_covers(scope, terms.scope) for scope in grant.scopes)
                or terms.authored_at.clock_ref != now.clock_ref
                or terms.authored_at.offset > terms.available_at.offset
                or not grant.validity.contains(terms.authored_at)
                or not terms.effective_window.contains(terms.authored_at)):
            raise ValueError('Tender terms lack original independent Owner author authority')

        def evidence(ref, *, observed=False):
            row = reading.resolve(ref)
            if (not isinstance(row, EvidenceRecord) or observed and not supports_tender_source(
                    row, allow_synthetic_assumptions=terms.allow_synthetic_assumptions)
                    or row.effective_window is not None and not row.effective_window.contains(now)):
                raise ValueError('Tender package lacks current independent source evidence')
            return row

        original = evidence(terms.source_evidence_ref, observed=True)
        if original.content_hash != source['record_sha256']:
            raise ValueError('Tender source evidence changes the actual observed source content')
        for ref in [*terms.evidence_refs, *grant.basis_refs, *assignment.basis_refs]:
            evidence(ref)
        if not terms.terms_evidence_refs:
            return {'kind':'needs_information', 'missing_fields':['independent_original_procurement_terms_evidence'], 'requested_refs':[terms.ref]}
        for ref in terms.terms_evidence_refs:
            if ref == terms.source_evidence_ref:
                raise ValueError('Native invitation facts do not prove independently authored procurement terms')
            evidence(ref, observed=context.execution_mode != 'offline_fixture')
        if terms.package_ref not in context.visible_refs:
            raise ValueError('Produced tender package target is outside the actual invocation view')
        own_grants = [reading.resolve(ref) for ref in context.authorization_refs]
        if not any(isinstance(row, Authorization) and row.organization_id == reading.organization_id
                   and row.actor_id == context.actor_id and row.function_ref == context.function_ref
                   and 'CONTRACTOR-A01' in row.action_ids and row.validity.contains(now)
                   and terms.package_ref in row.readable_refs for row in own_grants):
            raise ValueError('Produced package target lacks current explicit read authority')
        fields = ('work_types', 'participation_window', 'work_window', 'qualification_requirements',
                  'required_method_refs', 'resource_demands', 'funding_signal', 'clarification_requirement_refs')
        evidence_refs = list({ref.key():ref for ref in
            [terms.source_evidence_ref, *terms.evidence_refs, *terms.terms_evidence_refs]}.values())
        package = ProcurementPackageView(ref=terms.package_ref, employer_ref=terms.employer_ref,
            scope=terms.scope, access_mode='invitation_only', region_id=Known[str](state='known', value=facts['region_id']),
            evidence_refs=evidence_refs, **{name:getattr(terms, name) for name in fields})
        for window in (package.participation_window, package.work_window):
            if isinstance(window, Known) and window.value.start.clock_ref != now.clock_ref:
                raise ValueError('Tender terms substitute an unsupported business clock')
        # Scope/clock are structural identities checked against the invocation.
        # Unknown missing_refs and capability markers remain unresolved gaps;
        # requiring them as current objects would erase the unknown branch.
        references = list(package.clarification_requirement_refs)
        if isinstance(package.required_method_refs, Known):
            references.extend(package.required_method_refs.value)
        if isinstance(package.qualification_requirements, Known):
            references.extend(row.requirement_ref for row in package.qualification_requirements.value)
        if isinstance(package.resource_demands, Known):
            for row in package.resource_demands.value:
                if row.region_id != facts['region_id'] or row.window.start.clock_ref != now.clock_ref:
                    raise ValueError('Tender demand changes the original source region or declared business clock')
                references.append(row.requirement_ref)
                evidence(row.quantity.basis_ref, observed=context.execution_mode != 'offline_fixture')
        for ref in references:
            reading.resolve(ref)
        reading.recheck()
        invitation = None
        if terms.invitation_ref is not None:
            if not isinstance(package.participation_window, Known):
                return {'kind':'needs_information', 'missing_fields':['explicit_native_invitation_validity_window'],
                        'requested_refs':[terms.ref]}
            if (terms.invitation_ref not in context.visible_refs or not any(
                    isinstance(row, Authorization) and row.organization_id == reading.organization_id
                    and row.actor_id == context.actor_id and row.function_ref == context.function_ref
                    and 'CONTRACTOR-A01' in row.action_ids and row.validity.contains(now)
                    and terms.invitation_ref in row.readable_refs for row in own_grants)):
                raise ValueError('Native invitation projection target lacks current actor read authority')
            invitation = InvitationView(ref=terms.invitation_ref, package_ref=package.ref,
                issuer_ref=package.employer_ref, recipient_actor_id=context.actor_id,
                effective_window=package.participation_window.value, evidence_refs=evidence_refs)
        return {'kind':'prepared', 'projection':package, 'projection_sha256':task_digest(package.model_dump(mode='json')),
            'invitation_projection':invitation,
            'invitation_sha256':None if invitation is None else task_digest(invitation.model_dump(mode='json')),
            'source_record_sha256':source['record_sha256'], 'terms_sha256':task_digest(terms.model_dump(mode='json')),
            'source_mode':'fixture' if context.execution_mode == 'offline_fixture' else 'formal',
            'limitations':['Original package projection only; host must publish an immutable authorized version.',
                           'Independent work/qualification/time/demand/funding terms remain as supplied, including unknown.',
                           'Invitation is a projection of observed native membership plus explicitly sourced validity, not a signature or participation receipt.']}
    finally:
        reading.recheck()
