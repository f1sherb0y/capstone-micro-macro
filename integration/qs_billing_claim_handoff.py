"""Link saved QS fee proposals to independently observed native FeeClaim records."""
from copy import deepcopy
from decimal import Decimal

from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.qs_billing_objects import (
    QSBillingClaimHandoffBasisView, QSBillingClaimView,
    QSBillingEngagementView, QSBillingProfileView, QSBillingCalculationView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def prepare_qs_billing_claim_handoff(saved, *, context, reading, basis_ref, claim_ref, validate_current):
    """Read an actual claim; neither accepted submission nor this helper posts it.

    The caller holds the actual source/authorization guard. validate_current
    independently checks native registration, current claim history, correction
    continuity and atomic advance-credit allocations against the original task.
    Actual received amounts remain independent receipt/ledger facts.
    """
    from integration.qs_billing_results import SavedQSBilling

    if (not isinstance(saved, SavedQSBilling) or not isinstance(reading, ActionReadView)
            or context.contract_ref.id != 'QS-A10' or not callable(validate_current)):
        raise TaskConflict('Fee handoff requires the original saved QS billing decision and current source gate')
    reading.check_method_context(context, 'QS-A10')
    if (saved.current_context != context or saved.identity.action_id != 'QS-A10' or saved.identity.role != 'QS'
            or saved.identity.run_id != context.run_id or saved.identity.organization_id != reading.organization_id
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or saved.result.kind != 'completed' or saved.result.payload.choice not in {'claim', 'correct'}):
        raise TaskConflict('Fee handoff requires its original completed claim/correction and unchanged snapshots')
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if (saved.audit.get('input_sha256') != saved.identity.input_sha256
            or saved.audit.get('result_sha256') != result_sha or saved.audit.get('result_kind') != 'completed'):
        raise TaskConflict('Fee handoff substitutes the original audited proposal')

    def read(ref, schema):
        ref = Reference.model_validate(ref)
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Fee handoff requires exact concrete source identities and versions')
        return row

    try:
        basis = read(basis_ref, QSBillingClaimHandoffBasisView)
        claim = read(claim_ref, QSBillingClaimView)
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        engagement = QSBillingEngagementView.model_validate(originals[saved.action_input.engagement_ref.key()])
        profile = QSBillingProfileView.model_validate(originals[engagement.billing_profile_ref.key()])
        calculation = QSBillingCalculationView.model_validate(originals[saved.action_input.calculation_ref.key()])
        proposal = saved.result.payload.claim
        expected = {'task_sha256':saved.identity.key, 'record_sha256':saved.record_sha256,
            'input_sha256':saved.identity.input_sha256, 'context_sha256':saved.identity.context_sha256,
            'result_sha256':result_sha, 'audit_sha256':task_digest(saved.audit),
            'source_reading_sha256':saved.source_reading_sha256,
            'claim_sha256':task_digest(claim.model_dump(mode='json'))}
        unique_refs(claim.work_fact_refs)
        unique_refs(claim.advance_credit_refs)
        unique_refs(claim.receipt_refs)
        unique_refs(basis.relation_evidence_refs)
        if (any(getattr(basis, name) != value for name, value in expected.items())
                or basis.run_id != context.run_id or basis.organization_id != reading.organization_id
                or basis.claim_ref != claim.ref or claim.scope != saved.context.scope or basis.scope != claim.scope
                or engagement.organization_id != reading.organization_id or engagement.relation != 'external'
                or engagement.payer_organization_id == reading.organization_id
                or claim.engagement_ref != proposal.engagement_ref or claim.billing_clause_ref != proposal.billing_clause_ref
                or claim.payer_id != proposal.payer_id or claim.payer_id != engagement.payer_id
                or claim.payee_organization_id != reading.organization_id or claim.billing_key != profile.billing_key
                or claim.prior_claim_ref != proposal.prior_claim_ref
                or {ref.key() for ref in claim.work_fact_refs} != {ref.key() for ref in proposal.work_fact_refs}
                or {ref.key() for ref in claim.advance_credit_refs} != {ref.key() for ref in calculation.advance_credit_refs}
                or claim.amount.currency != proposal.amount.currency
                or Decimal(claim.amount.value) != Decimal(proposal.amount.value)
                or claim.actual_received.currency != claim.amount.currency or Decimal(claim.actual_received.value) < 0
                or claim.ref == claim.prior_claim_ref
                or claim.status in {'unknown', 'rejected'}
                or saved.result.payload.choice == 'correct' and claim.prior_claim_ref is None):
            raise TaskConflict('Actual fee claim changes original proposal, provider, payer, scope, work, credits or amount')
        points = [saved.context.business_time, basis.registered_at, claim.available_at,
            basis.authored_at, basis.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))
                or not basis.effective_window.contains(context.business_time)
                or not basis.effective_window.contains(basis.authored_at)):
            raise TaskConflict('Fee handoff changes actual registration or observation chronology')
        original_grant = read(profile.authority_ref, Authorization)
        original_assignment = reading.resolve(saved.context.function_ref)
        if (originals.get(profile.authority_ref.key()) != original_grant.model_dump(mode='json')
                or originals.get(saved.context.function_ref.key()) != original_assignment.model_dump(mode='json')
                or not isinstance(original_assignment, RoleAssignment) or original_assignment.role != 'QS'
                or original_grant.actor_id != saved.context.actor_id
                or original_grant.function_ref != saved.context.function_ref
                or original_grant.organization_id != reading.organization_id
                or 'QS-A10' not in original_grant.action_ids
                or not original_grant.validity.contains(saved.context.business_time)
                or not any(scope_covers(scope, saved.context.scope) for scope in original_grant.scopes)):
            raise TaskConflict('Fee registration substitutes the original independently authorized QS proposal author')
        grant = read(basis.author_authority_ref, Authorization)
        assignment = reading.resolve(basis.author_function_ref)
        authored_refs = [claim.ref, basis.native_evidence_ref, *basis.relation_evidence_refs]
        if (not isinstance(assignment, RoleAssignment) or assignment.role != 'QS'
                or assignment.function_ref != basis.author_function_ref
                or basis.author_organization_id != reading.organization_id or grant.organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or grant.function_ref != basis.author_function_ref
                or basis.author_action_id not in grant.action_ids or not grant.validity.contains(basis.authored_at)
                or not any(scope_covers(scope, basis.scope) for scope in grant.scopes)
                or not {ref.key() for ref in authored_refs} <= {ref.key() for ref in grant.readable_refs}
                or basis.native_evidence_ref in basis.relation_evidence_refs):
            raise TaskConflict('Fee relation lacks independent scoped QS author authority and relation evidence')
        refs = [*basis.evidence_refs, *basis.relation_evidence_refs, basis.native_evidence_ref,
            *claim.evidence_refs, claim.amount.basis_ref, claim.actual_received.basis_ref]
        refs.extend(ref for row in (grant, assignment) for ref in row.basis_refs if ref.kind == 'Evidence')
        for ref in refs:
            evidence = read(ref, EvidenceRecord)
            if (reading._resolver.source_mode == 'formal' and evidence.source_kind == 'synthetic'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)
                    or ref in basis.relation_evidence_refs and evidence.basis_kind != 'observed'):
                raise TaskConflict('Fee relation requires available actual source and observed relation evidence')
        native = read(basis.native_evidence_ref, EvidenceRecord)
        if native.basis_kind != 'observed' or native.content_hash != basis.native_source_sha256:
            raise TaskConflict('Fee handoff lacks independently observed native claim registration')
        if validate_current(saved=deepcopy(saved), basis=basis.model_copy(deep=True), claim=claim.model_copy(deep=True),
                engagement=engagement.model_copy(deep=True), profile=profile.model_copy(deep=True),
                calculation=calculation.model_copy(deep=True), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Fee handoff requires actual host registration, correction and credit-allocation verification')
        return {'kind':'prepared', 'source_mode':reading._resolver.source_mode,
            'provenance':{**expected, 'basis_ref':basis.ref.model_dump(mode='json'),
                'basis_sha256':task_digest(basis.model_dump(mode='json')),
                'native_claim_id':basis.native_claim_id, 'native_event_id':basis.native_event_id}}
    finally:
        reading.recheck()
