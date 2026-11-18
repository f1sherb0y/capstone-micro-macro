"""Authenticate retained isolation-release rechecks without creating effects."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.supplier_quality_objects import (
    SupplierBatchRecheckView, SupplierQualityMethodView, SupplierQualityObservationMethodView,
    SupplierQualityRequirementView,
)
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def validate_isolation_release_recheck(execution, batch, *, now, resolve, amount, released):
    """Return original sources; caller retains one accumulator for the full ledger.

    A recheck version is not a second physical inspection. Conflicting versions
    under one recheck identity cannot supply another quantity allowance. Actual
    native release timing/effects remain the independent host's responsibility.
    Recheck evidence uses its real authorship time. The caller reads the release
    execution quantity historically: its source has no actual occurrence time.
    """
    sources = {}

    def read(ref, schema=None):
        row = resolve(ref)
        if ((schema is not None and not isinstance(row, schema))
                or getattr(row, 'ref', getattr(row, 'function_ref', ref)) != ref):
            raise ValueError('Isolation release lacks its exact original typed recheck source')
        sources[ref.key()] = row
        if hasattr(row, 'available_at') and (
                row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset):
            raise ValueError('Isolation release source is unavailable at the current authorized read point')
        return row

    def evidence(ref, at):
        row = read(ref, EvidenceRecord)
        if row.effective_window is not None and (
                row.effective_window.start.clock_ref != at.clock_ref
                or row.effective_window.end.clock_ref != at.clock_ref
                or not row.effective_window.contains(at)):
            raise ValueError('Isolation release evidence was invalid at the original recheck')

    def true(value):
        return isinstance(value, Known) and value.value is True

    def at_recheck(row, at):
        if (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset
                or row.effective_window.start.clock_ref != at.clock_ref
                or row.effective_window.end.clock_ref != at.clock_ref
                or not row.effective_window.contains(at)):
            raise ValueError('Isolation release uses a method or requirement unavailable or invalid at the original recheck')

    if (execution.choice != 'release_isolation' or execution.status != 'recorded'
            or execution.release_basis_ref is None):
        raise ValueError('Recorded isolation release requires its original passed recheck')
    check = read(execution.release_basis_ref, SupplierBatchRecheckView)
    at = check.authored_at
    quantity = amount(execution.quantity)
    if (check.physical_batch_key != batch.physical_batch_key or not true(check.supported) or not true(check.passed)
            or not check.requirement_refs or quantity <= 0
            or at.clock_ref != now.clock_ref or at.offset > check.available_at.offset
            or execution.available_at.clock_ref != now.clock_ref or at.offset > execution.available_at.offset
            or execution.available_at.offset > now.offset
            or check.effective_window.start.clock_ref != now.clock_ref
            or check.effective_window.end.clock_ref != now.clock_ref
            or not check.effective_window.contains(at) or not scope_covers(check.scope, execution.scope)):
        raise ValueError('Isolation release substitutes original passed scope, quantity or recheck chronology')
    method = read(check.method_ref, SupplierQualityMethodView)
    observation = read(method.observation_method_ref, SupplierQualityObservationMethodView)
    for row in (method, observation):
        at_recheck(row, at)
        if not true(row.supported) or not scope_covers(row.scope, check.scope):
            raise ValueError('Isolation release recheck lacks supported scoped original inspection/observation methods')
    if (method.executor_action_id not in observation.allowed_author_action_ids
            or (method.executor_organization_id, method.executor_actor_id, method.executor_function_ref,
                method.executor_authority_ref, method.executor_action_id) !=
                (check.author_organization_id, check.author_actor_id, check.author_function_ref,
                 check.author_authority_ref, check.author_action_id)):
        raise ValueError('Isolation release recheck replaces its actually supported original executor')
    refs = {ref.key() for ref in check.requirement_refs}
    if (len(refs) != len(check.requirement_refs) or len({ref.key() for ref in method.requirement_refs}) != len(method.requirement_refs)
            or refs != {ref.key() for ref in method.requirement_refs}):
        raise ValueError('Isolation release recheck replaces its original method requirements')
    for ref in check.requirement_refs:
        requirement = read(ref, SupplierQualityRequirementView)
        at_recheck(requirement, at)
        if (requirement.batch_ref.key()[:2] != batch.ref.key()[:2] or requirement.product_ref != batch.product_ref
                or method.ref not in requirement.allowed_method_refs
                or requirement.external_verification_required and check.author_organization_id == batch.organization_id):
            raise ValueError('Isolation release recheck substitutes original product/requirement or required independent verification')
    grant = read(check.author_authority_ref, Authorization)
    assignment = read(check.author_function_ref, RoleAssignment)
    roles = {'SUPPLIER': 'Supplier', 'CONTRACTOR': 'Contractor', 'OWN': 'Owner', 'ENGINEER': 'Engineer',
        'ARCHITECT': 'Architect', 'QS': 'QS', 'GOV': 'Government', 'BANK': 'Bank'}
    if (grant.organization_id != check.author_organization_id or grant.actor_id != check.author_actor_id
            or grant.function_ref != check.author_function_ref or check.author_action_id not in grant.action_ids
            or assignment.function_ref != check.author_function_ref
            or assignment.role != roles.get(check.author_action_id.split('-')[0])
            or grant.validity.start.clock_ref != at.clock_ref or grant.validity.end.clock_ref != at.clock_ref
            or not grant.validity.contains(at) or not any(scope_covers(scope, check.scope) for scope in grant.scopes)):
        raise ValueError('Isolation release recheck lacks the original independent author authority')
    # Retain all professional and authority evidence in the actual reading;
    # formal callers additionally authenticate observed native provenance.
    for row in tuple(sources.values()):
        for ref in getattr(row, 'evidence_refs', []):
            evidence(ref, at)
        for ref in getattr(row, 'basis_refs', []):
            if ref.kind == 'Evidence':
                evidence(ref, at)
            else:
                read(ref)
    evidence(check.scope_of_release.basis_ref, at)
    coverage = amount(check.scope_of_release)
    key, body = check.ref.key()[:2], check.model_dump(mode='json')
    previous = released.get(key)
    if previous is not None and previous[0] != body:
        raise ValueError('Isolation release rewrites one original recheck under multiple versions')
    total = quantity + (previous[1] if previous is not None else 0)
    if total > coverage:
        raise ValueError('Isolation releases count the same original recheck coverage more than once')
    released[key] = (body, total)
    return check, tuple(sources.values())
