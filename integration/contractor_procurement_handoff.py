"""Link distinct A01/A02 projections to one explicitly evidenced procurement version."""
from src.actions.contracts.common import EvidenceRecord, Known, Reference, TextId, ref_type
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.contractor_objects import ProcurementPackageView
from src.actions.contracts.contractor_bid_objects import ContractorBidPackageView
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class ContractorProcurementHandoffBasis(GovReviewAuthored):
    """Authorized relation between two action-specific views, not a new package.

    The original procurement reference/version remains identical. Each schema
    has its own projection digest, bound to the common observed source record.
    Submission windows and technical fields are independently supplied for A02;
    an A01 participation result supplies neither prices nor construction rights.
    """
    ref: ref_type('ContractorProcurementHandoffBasis')
    run_id: TextId
    organization_id: TextId
    package_ref: ref_type('ProcurementPackage')
    screening_context_sha256: Digest
    screening_input_sha256: Digest
    screening_result_sha256: Digest
    screening_audit_sha256: Digest
    screening_projection_sha256: Digest
    bid_projection_sha256: Digest
    procurement_source_sha256: Digest
    procurement_source_evidence_ref: ref_type('Evidence')
    screening_result_evidence_ref: ref_type('Evidence')


def prepare_contractor_procurement_handoff(screening, screening_result, screening_audit,
        bid, *, basis_ref, validate_current):
    """Validate a local participation handoff without executing either action.

    Host validation checks the actual common procurement snapshot and original
    A01 decision at the current A02 read point. Historical A01 authority may
    have expired; original audit/evidence is retained rather than rewritten.
    The current A02 reading supplies fresh permissions and the explicit basis.
    """
    from integration.contractor_screening_actions import PreparedContractorScreening
    from integration.contractor_screening_results import SavedContractorScreening
    from integration.contractor_bid_actions import PreparedContractorBid

    if (not isinstance(screening, (PreparedContractorScreening, SavedContractorScreening))
            or not isinstance(bid, PreparedContractorBid)
            or not callable(validate_current)):
        raise ValueError('Actual prepared A01/A02 invocations and fresh host handoff validation required')
    source_context, context, reading = screening.context, bid.context, bid.reading
    historical = isinstance(screening, SavedContractorScreening)
    source_organization = screening.organization_id if historical else screening.reading.organization_id
    if (source_context.run_id != context.run_id or source_context.scope != context.scope
            or source_organization != reading.organization_id
            or source_context.business_time.clock_ref != context.business_time.clock_ref
            or source_context.business_time.offset > context.business_time.offset
            or (source_context.execution_mode == 'offline_fixture') != (context.execution_mode == 'offline_fixture')):
        raise ValueError('Procurement handoff changes original run, enterprise, scope, clock or source mode')
    reading.check_method_context(context, 'CONTRACTOR-A02')
    source_registry = screening.registry if historical else screening.runner.registry
    source_registration = source_registry.get('CONTRACTOR-A01')
    source_contract = source_registration.contract
    source_input = source_contract.validate_input(screening.action_input)
    result = source_contract.result_adapter.validate_python(screening_result)
    if historical and (result != screening.result or screening_audit != screening.audit
            or task_digest(list(screening.source_reading)) != screening.reading_sha256):
        raise ValueError('Saved participation handoff substitutes its original result, audit or source evidence')
    if result.kind != 'completed' or result.payload.choice != 'participate':
        return {'kind':'needs_information', 'missing_fields':['completed_original_participation_decision'],
                'requested_refs':[source_input.package_ref]}
    source_contract.validate_decision(source_input, result.payload)
    source_hash = task_digest(source_input.model_dump(mode='json'))
    result_hash = task_digest(result.model_dump(mode='json'))
    if (source_hash != screening.input_sha256
            or task_digest(source_context.model_dump(mode='json')) != screening.context_sha256
            or task_digest(bid.action_input.model_dump(mode='json')) != bid.input_sha256
            or task_digest(context.model_dump(mode='json')) != bid.context_sha256):
        raise ValueError('Original procurement handoff input/context changed')
    audit_expected = {'schema_version':'action-audit.v1', 'run_id':source_context.run_id,
        'action_id':'CONTRACTOR-A01', 'operation_id':source_context.operation_id,
        'input_sha256':source_hash, 'input_version':source_context.contract_ref.version,
        'result_kind':'completed', 'result_sha256':result_hash}
    if (not isinstance(screening_audit, dict)
            or any(screening_audit.get(k) != v for k,v in audit_expected.items())
            or screening_audit.get('stages') != {'input_validation':'accepted','authorization':'accepted','processor':'bound'}
            or screening_audit.get('reading', {}).get('status') != 'accepted'
            or screening_audit.get('authorization_refs') != [list(ref.key()) for ref in source_context.authorization_refs]
            or screening_audit.get('processor_id') != source_registration.processor_id
            or screening_audit.get('reading', {}).get('source_mode') !=
               ('fixture' if source_context.execution_mode == 'offline_fixture' else 'formal')
            or screening_audit.get('reading', {}).get('read_token') != source_context.read_token):
        raise ValueError('Participation handoff lacks the exact successful original A01 audit')
    # Read each package with its ORIGINAL schema/resolver. No schema coercion
    # or changed object version is used to hide different action representations.
    source_evidence = screening.source_reading if historical else screening.reading.evidence()
    cached = [row['projection'] for row in source_evidence
              if Reference.model_validate(row['ref']) == source_input.package_ref]
    if len(cached) != 1:
        raise ValueError('Handoff lacks its actual retained original screening package projection')
    source_package = ProcurementPackageView.model_validate(cached[0])
    bid_package = reading.resolve(bid.action_input.package_ref)
    if (not isinstance(source_package, ProcurementPackageView) or not isinstance(bid_package, ContractorBidPackageView)
            or source_package.ref != bid_package.ref or source_package.scope != bid_package.scope
            or not isinstance(source_package.region_id, Known) or source_package.region_id.value != bid_package.region_id):
        raise ValueError('Handoff changes original procurement version, scope or known region')
    basis_ref = Reference.model_validate(basis_ref)
    basis = reading.resolve(basis_ref)
    if not isinstance(basis, ContractorProcurementHandoffBasis) or basis.ref != basis_ref:
        raise ValueError('Procurement handoff lacks its concrete original authorized basis')
    expected = {'run_id':context.run_id, 'organization_id':reading.organization_id, 'scope':context.scope,
        'package_ref':bid_package.ref, 'screening_context_sha256':screening.context_sha256,
        'screening_input_sha256':source_hash, 'screening_result_sha256':result_hash,
        'screening_audit_sha256':task_digest(screening_audit),
        'screening_projection_sha256':task_digest(source_package.model_dump(mode='json')),
        'bid_projection_sha256':task_digest(bid_package.model_dump(mode='json'))}
    if any(getattr(basis,k) != v for k,v in expected.items()):
        raise ValueError('Handoff basis substitutes original procurement projections or participation evidence')
    now = context.business_time
    if (basis.available_at.clock_ref != now.clock_ref or basis.available_at.offset > now.offset
            or not basis.effective_window.contains(now)):
        raise ValueError('Procurement handoff basis is unavailable or no longer valid')
    grant, assignment = reading.resolve(basis.author_authority_ref), reading.resolve(basis.author_function_ref)
    if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
            or grant.organization_id != basis.author_organization_id or grant.actor_id != basis.author_actor_id
            or grant.function_ref != basis.author_function_ref or assignment.function_ref != basis.author_function_ref
            or basis.author_action_id not in grant.action_ids
            or not any(scope_covers(scope,basis.scope) for scope in grant.scopes)
            or basis.authored_at.clock_ref != now.clock_ref or basis.authored_at.offset > basis.available_at.offset
            or not grant.validity.contains(basis.authored_at)):
        raise ValueError('Procurement projection relation lacks its original independent author authority')
    for ref in [*basis.evidence_refs, *grant.basis_refs, *assignment.basis_refs,
                basis.procurement_source_evidence_ref, basis.screening_result_evidence_ref]:
        evidence = reading.resolve(ref)
        if not isinstance(evidence, EvidenceRecord):
            raise ValueError('Procurement handoff lacks typed authorized original evidence')
    for ref, digest in ((basis.procurement_source_evidence_ref,basis.procurement_source_sha256),
                        (basis.screening_result_evidence_ref,result_hash)):
        evidence = reading.resolve(ref)
        if evidence.content_hash != digest or evidence.basis_kind != 'observed':
            raise ValueError('Procurement source/result evidence changes original observed content')
    if validate_current(screening=screening, screening_result=result.model_copy(deep=True),
            bid=bid, basis=basis.model_copy(deep=True)) is not None:
        raise ValueError('Actual procurement source and original participation require current host validation')
    reading.recheck()
    return {'kind':'prepared', 'invocation':bid, 'basis_sha256':task_digest(basis.model_dump(mode='json')),
        'screening_result_sha256':result_hash, 'procurement_source_sha256':basis.procurement_source_sha256,
        'projection_schemas':{'screening':'ContractorA01.ProcurementPackageView',
                              'bid':'ContractorA02.ContractorBidPackageView'},
        'limitations':['Local participation enables a handoff only; A02 must independently check and price the original bid.',
                       'No A01 intention registration, macro bid creation or resource reservation is asserted.']}
