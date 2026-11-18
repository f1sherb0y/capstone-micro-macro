"""Independently authored replies may unblock the same immutable transfer plan."""
from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, Reference
from src.actions.contracts.commercial_continuation_objects import (
    CommercialAcceptanceView, CommercialConsentView, CommercialTransferPlanView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_ROLES = {'OWN':'Owner','BANK':'Bank','GOV':'Government','CONTRACTOR':'Contractor',
          'SUPPLIER':'Supplier','ARCHITECT':'Architect','ENGINEER':'Engineer','QS':'QS'}


def commercial_acceptance_profiles(read_current):
    """Host supplies fresh context, authorized view and original reply's new ref.

    The plan's body/version/SHA stays unchanged when a new reply is received.
    A successor profile must explicitly select the new reply refs. Waking one
    reply does not prove every party accepted or transfer any responsibility.
    """
    if not callable(read_current):
        raise ValueError('A current authorized acceptance reader is required')

    def valid_evidence(reading, refs, at, now, *, mixed_basis=False):
        if at.clock_ref != now.clock_ref or at.offset > now.offset:
            return False
        for ref in refs:
            row = reading.resolve(ref)
            if mixed_basis and ref.kind != 'Evidence':
                continue
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                raise TaskConflict('Acceptance lacks exact typed original evidence')
            if row.effective_window is not None and not row.effective_window.contains(at):
                return False
        return True

    def profile(action_id, code, schema, kind, party_field):
        def evaluate(check):
            source = check.source['identity']
            if (source['action_id'] != action_id or check.condition.condition_code != code
                    or check.condition.trigger != 'dependency_change'
                    or check.signal.run_id != source['run_id']
                    or check.signal.organization_id != source['organization_id']):
                raise TaskConflict('Acceptance condition changes original task, run or recipient')
            old_refs = check.condition.object_refs
            if len(old_refs) != 1 or old_refs[0].kind != kind:
                raise TaskConflict('Acceptance wait requires its original party reply')
            context, reading, ref = read_current(check)
            if (not isinstance(context, ActionContext) or not isinstance(reading, ActionReadView)
                    or not isinstance(ref, Reference)):
                raise TaskConflict('Acceptance condition requires a typed authorized reading')
            if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != action_id
                    or context.business_time != check.signal.business_time):
                raise TaskConflict('Acceptance condition changes action, run, recipient or current time')
            reading.check_method_context(context, action_id)
            old_ref = old_refs[0]
            if (ref.kind, ref.id) != (old_ref.kind, old_ref.id):
                raise TaskConflict('Acceptance condition substitutes another reply identity')
            try:
                if ref.version == old_ref.version:
                    return 'unavailable'
                original, current = reading.resolve(old_ref), reading.resolve(ref)
                if not isinstance(original, schema) or not isinstance(current, schema):
                    raise TaskConflict('Acceptance condition lacks its original reply schema')
                fields = ['plan_ref','plan_sha256',party_field,'scope']
                if kind == 'ContinuationConsent': fields.append('contract_ref')
                if (original.ref != old_ref or current.ref != ref
                        or any(getattr(original, field) != getattr(current, field) for field in fields)):
                    raise TaskConflict('Acceptance reply changes original plan, scope or party')
                plan = reading.resolve(current.plan_ref)
                if (not isinstance(plan, CommercialTransferPlanView) or plan.organization_id != source['organization_id']
                        or plan.ref != current.plan_ref or current.scope != plan.scope
                        or content_digest(plan) != current.plan_sha256):
                    raise TaskConflict('Acceptance reply changes the immutable signed plan')
                if kind == 'ContinuationAcceptance':
                    if (plan.successor_organization_id != current.successor_organization_id
                            or (plan.acceptance_ref.kind,plan.acceptance_ref.id) != (ref.kind,ref.id)
                            or plan.successor_organization_id == source['organization_id']):
                        raise TaskConflict('Successor acceptance is not independent or belongs to another plan')
                elif (ref.kind,ref.id) not in {(r.kind,r.id) for r in plan.consent_refs}:
                    raise TaskConflict('Party reply is not an original plan consent')
                now = context.business_time
                if (current.available_at.clock_ref != now.clock_ref or current.available_at.offset > now.offset
                        or current.authored_at.clock_ref != now.clock_ref
                        or current.authored_at.offset > current.available_at.offset
                        or current.effective_window.start.clock_ref != now.clock_ref
                        or current.effective_window.end.clock_ref != now.clock_ref
                        or not current.effective_window.contains(now)
                        or not current.effective_window.contains(current.authored_at)):
                    return 'unavailable'
                if (plan.available_at.clock_ref != now.clock_ref
                        or current.authored_at.offset < plan.available_at.offset):
                    raise TaskConflict('Acceptance was authored before the signed plan was available')
                if kind == 'ContinuationAcceptance' and (
                        current.as_of.clock_ref != now.clock_ref
                        or current.as_of.offset > current.authored_at.offset):
                    return 'unavailable'
                party = getattr(current, party_field)
                grant = reading.resolve(current.author_authority_ref)
                assignment = reading.resolve(current.author_function_ref)
                if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                        or current.author_organization_id != party or grant.organization_id != party
                        or grant.actor_id != current.author_actor_id or grant.function_ref != current.author_function_ref
                        or assignment.function_ref != current.author_function_ref
                        or assignment.role != _ROLES.get(current.author_action_id.split('-')[0])
                        or current.author_action_id not in grant.action_ids
                        or not any(scope_covers(scope,current.scope) for scope in grant.scopes)):
                    raise TaskConflict('Acceptance reply substitutes the independent original party authority')
                if (grant.validity.start.clock_ref != now.clock_ref or grant.validity.end.clock_ref != now.clock_ref
                        or not grant.validity.contains(current.authored_at)):
                    return 'unavailable'
                if (plan.authored_at.clock_ref != now.clock_ref or plan.authored_at.offset > plan.available_at.offset
                        or not valid_evidence(reading, [*plan.evidence_refs, *plan.transfer_evidence_refs], plan.authored_at, now)
                        or not valid_evidence(reading, current.evidence_refs, current.authored_at, now)
                        or not valid_evidence(reading, [*grant.basis_refs, *assignment.basis_refs],
                            current.authored_at, now, mixed_basis=True)):
                    return 'unavailable'
                return 'ready' if isinstance(current.accepted, Known) and current.accepted.value is True else 'waiting'
            finally:
                reading.recheck()

        return ConditionProfile(action_id, code, '2', frozenset({'dependency_change'}), evaluate)

    return [p for action_id in ('CONTRACTOR-A12','SUPPLIER-A12') for p in (
        profile(action_id, 'commercial_handover_waiting_successor_acceptance',
                CommercialAcceptanceView, 'ContinuationAcceptance', 'successor_organization_id'),
        profile(action_id, 'commercial_handover_waiting_original_party_consent',
                CommercialConsentView, 'ContinuationConsent', 'party_organization_id'),
    )]
