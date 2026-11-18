"""Current, sourced A12 readiness may prompt a fresh continuation decision."""
from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, Reference, StrictRecord
from src.actions.contracts.commercial_continuation_objects import CommercialContinuationStateView, CommercialVerificationView
from src.actions.contracts.supplier_continuation_objects import SupplierContinuationStateView, SupplierResumeVerificationView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.commercial_acceptance_conditions import _ROLES
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def commercial_readiness_profiles(read_current):
    """Host supplies current context, authorized read view and new Verification.

    Each changed verification must still concern the same firm, state identity
    and family. One ready family only wakes a new decision: all families, actual
    occupied resources and any required capacity report remain action checks.
    """
    if not callable(read_current):
        raise ValueError('A current authorized readiness reader is required')

    def valid_evidence(reading, refs, at, now, *, mixed_basis=False):
        if at.clock_ref != now.clock_ref or at.offset > now.offset:
            return False
        for ref in refs:
            row = reading.resolve(ref)
            if mixed_basis and ref.kind != 'Evidence':
                continue
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                raise TaskConflict('Readiness lacks exact typed original/current evidence')
            if row.effective_window is not None and not row.effective_window.contains(at):
                return False
        return True

    def profile(action_id, schema, state_schema):
        code = 'commercial_resume_readiness_pending'

        def evaluate(check):
            source = check.source['identity']
            if (source['action_id'] != action_id or check.condition.condition_code != code
                    or check.condition.trigger != 'dependency_change'
                    or check.signal.run_id != source['run_id']
                    or check.signal.organization_id != source['organization_id']):
                raise TaskConflict('Readiness condition changes original task, run or recipient')
            old_refs = check.condition.object_refs
            if len(old_refs) != 1 or old_refs[0].kind != 'Verification':
                raise TaskConflict('Readiness wait requires one original verification')
            context, reading, ref = read_current(check)
            if (not isinstance(context, ActionContext) or not isinstance(reading, ActionReadView)
                    or not isinstance(ref, Reference)):
                raise TaskConflict('Readiness condition requires a typed authorized reading')
            if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != action_id
                    or context.business_time != check.signal.business_time):
                raise TaskConflict('Readiness condition changes action, run, recipient or current time')
            reading.check_method_context(context, action_id)
            old_ref = old_refs[0]
            if (ref.kind, ref.id) != (old_ref.kind, old_ref.id):
                raise TaskConflict('Readiness condition replaces the original verification')
            try:
                if ref.version == old_ref.version:
                    return 'unavailable'
                original, current = reading.resolve(old_ref), reading.resolve(ref)
                if not isinstance(original, schema) or not isinstance(current, schema):
                    raise TaskConflict('Readiness source lacks its original role verification schema')
                if (original.ref != old_ref or current.ref != ref
                        or original.organization_id != current.organization_id
                        or current.organization_id != source['organization_id']
                        or original.family != current.family or original.scope != current.scope
                        or (original.state_ref.kind,original.state_ref.id) != (current.state_ref.kind,current.state_ref.id)):
                    raise TaskConflict('Readiness changes original firm, family, scope or state identity')
                state = reading.resolve(current.state_ref)
                if (not isinstance(state, state_schema) or state.ref != current.state_ref
                        or state.organization_id != source['organization_id'] or state.run_id != source['run_id']
                        or state.scope != current.scope or state.scope != context.scope
                        or content_digest(state) != current.state_sha256):
                    raise TaskConflict('Readiness changes its actual current state content or source identity')
                now = context.business_time
                if state.coverage != 'complete' or state.as_of != now or current.as_of != now:
                    return 'unavailable'
                for row in (state, current):
                    if (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                            or row.effective_window.start.clock_ref != now.clock_ref
                            or row.effective_window.end.clock_ref != now.clock_ref
                            or not row.effective_window.contains(now)):
                        return 'unavailable'
                if (current.authored_at.clock_ref != now.clock_ref
                        or current.authored_at.offset > current.available_at.offset
                        or current.authored_at.offset < state.available_at.offset
                        or not current.effective_window.contains(current.authored_at)):
                    return 'unavailable'
                grant = reading.resolve(current.author_authority_ref)
                assignment = reading.resolve(current.author_function_ref)
                if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                        or grant.organization_id != current.author_organization_id
                        or grant.actor_id != current.author_actor_id or grant.function_ref != current.author_function_ref
                        or assignment.function_ref != current.author_function_ref
                        or assignment.role != _ROLES.get(current.author_action_id.split('-')[0])
                        or current.author_action_id not in grant.action_ids
                        or not any(scope_covers(scope,current.scope) for scope in grant.scopes)):
                    raise TaskConflict('Readiness substitutes its original independent author authority')
                if (grant.validity.start.clock_ref != now.clock_ref or grant.validity.end.clock_ref != now.clock_ref
                        or not grant.validity.contains(current.authored_at)):
                    return 'unavailable'
                if (not valid_evidence(reading, current.evidence_refs, current.authored_at, now)
                        or not valid_evidence(reading, state.evidence_refs, now, now)
                        or not valid_evidence(reading, [*grant.basis_refs, *assignment.basis_refs],
                            current.authored_at, now, mixed_basis=True)):
                    return 'unavailable'
                unique_refs([item.source_ref for item in current.source_digests])
                for item in current.source_digests:
                    row = reading.resolve(item.source_ref)
                    if not isinstance(row, StrictRecord) or content_digest(row) != item.source_sha256:
                        raise TaskConflict('Readiness substitutes an original source version or digest')
                    if hasattr(row, 'available_at') and (
                            row.available_at.clock_ref != now.clock_ref
                            or row.available_at.offset > current.authored_at.offset):
                        return 'unavailable'
                    if hasattr(row, 'effective_window') and row.effective_window is not None and (
                            row.effective_window.start.clock_ref != now.clock_ref
                            or row.effective_window.end.clock_ref != now.clock_ref
                            or not row.effective_window.contains(now)):
                        return 'unavailable'
                if not isinstance(current.supported, Known) or current.supported.value is not True:
                    return 'unavailable'
                return 'ready' if isinstance(current.ready, Known) and current.ready.value is True else 'waiting'
            finally:
                reading.recheck()

        return ConditionProfile(action_id, code, '2', frozenset({'dependency_change'}), evaluate)

    return [profile('CONTRACTOR-A12', CommercialVerificationView, CommercialContinuationStateView),
            profile('SUPPLIER-A12', SupplierResumeVerificationView, SupplierContinuationStateView)]
